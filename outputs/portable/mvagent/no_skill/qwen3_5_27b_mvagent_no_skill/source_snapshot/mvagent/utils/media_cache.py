"""Bounded, content-addressed metadata/clip cache with process-safe leases."""
import fcntl
from functools import lru_cache, wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import time

from models.execution import current_scope, emit_event


@lru_cache(maxsize=4096)
def _fingerprint(path, size, modified_ns):
    # Files are immutable within a run; stat changes invalidate the memoized digest.
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prune(root, max_bytes):
    with (root / "prune.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        _prune(root, max_bytes)


def _prune(root, max_bytes):
    entries = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        if (path / "result.json").exists():
            entries.append(path)
            continue
        with (root / (path.name + ".lock")).open("a") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            # A dead producer may have left an unpublished clip behind.
            if not (path / "result.json").exists():
                shutil.rmtree(path)
    sizes = {p: sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) for p in entries}
    total = sum(sizes.values())
    for path in sorted(entries, key=lambda p: p.stat().st_mtime):
        if total <= max_bytes:
            break
        with (root / (path.name + ".lock")).open("a") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            shutil.rmtree(path, ignore_errors=True)
            total -= sizes[path]


def cached_media(kind):
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def call(*args, **kwargs):
            started = time.monotonic()
            scope = current_scope()
            cache = scope and scope["media_cache"]
            if not cache:
                value = function(*args, **kwargs)
                emit_event("media", operation=kind, cached=False, seconds=time.monotonic() - started)
                return value
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            parameters = dict(bound.arguments)
            source = Path(parameters["video_path"]).resolve()
            stat = source.stat()
            media_hash = _fingerprint(str(source), stat.st_size, stat.st_mtime_ns)
            key_params = {k: v for k, v in parameters.items()
                          if k not in ("video_path", "output_dir", "prefix", "temp_dir_prefix")}
            code_hash = hashlib.sha256(Path(function.__code__.co_filename).read_bytes() + Path(__file__).read_bytes()).hexdigest()
            key = hashlib.sha256(json.dumps([kind, media_hash, key_params, code_hash], sort_keys=True).encode()).hexdigest()
            root = Path(cache["root"])
            root.mkdir(parents=True, exist_ok=True)
            lease = (root / (key + ".lock")).open("a")
            try:
                # Retain a shared lease until this question has finished using the clip.
                fcntl.flock(lease, fcntl.LOCK_SH)
                directory = root / key
                manifest = directory / "result.json"
                hit = manifest.exists()
                if not hit:
                    fcntl.flock(lease, fcntl.LOCK_EX)
                    if not manifest.exists():
                        directory.mkdir(exist_ok=True)
                        if kind == "clip":
                            parameters.update(output_dir=str(directory), prefix="clip")
                        value = function(**parameters)
                        temporary = directory / "result.tmp"
                        temporary.write_text(json.dumps(value))
                        os.replace(temporary, manifest)
                    fcntl.flock(lease, fcntl.LOCK_SH)
                scope["leases"].append(lease)
                value = json.loads(manifest.read_text())
                if kind == "metadata":
                    value["path"] = parameters["video_path"]
                os.utime(directory, None)
                if not hit:
                    prune(root, cache.get("max_bytes", 10 * 1024 ** 3))
                emit_event("media", operation=kind, cached=hit, seconds=time.monotonic() - started)
                return value
            except BaseException:
                lease.close()
                raise
        return call
    return decorate
