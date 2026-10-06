from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Protocol, Set, TypeVar

from packaging.version import InvalidVersion, Version

from models.utils import is_loopback_host, validate_gpu_list


_LOCAL_FASTAPI_CONSTRAINT = "fastapi>=0.115,<0.137"
_WAIT_TRACE_INTERVAL_SEC = 60.0
_EXISTING_INFERENCE_PROBE_TIMEOUT_SEC = 15.0


T = TypeVar("T")


class ProcessHandle(Protocol):
    def poll(self) -> int | None:
        ...


class LocalServiceWaitTimeout(TimeoutError):
    """Raised when a local service does not become ready in time."""


class LocalServiceProcessExited(RuntimeError):
    """Raised when a newly started local service exits before readiness."""

    def __init__(self, exit_code: int) -> None:
        super().__init__(
            f"Local service exited during startup with code {exit_code}."
        )
        self.exit_code = int(exit_code)


@dataclass(frozen=True)
class LoopbackEndpoint:
    """Normalized loopback HTTP endpoint used by a local model service."""

    url: str
    root: str
    host: str
    port: int
    path: str


def parse_loopback_endpoint(
    endpoint: str,
    *,
    required_path: str,
) -> LoopbackEndpoint:
    """Validate and normalize one explicit-port loopback HTTP endpoint."""
    parsed = urllib.parse.urlparse(str(endpoint or "").strip())
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("endpoint must be an absolute loopback HTTP URL.")
    if not is_loopback_host(parsed.hostname):
        raise ValueError("endpoint must use a loopback host.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint has an invalid port.") from exc
    if port is None:
        raise ValueError("endpoint must include an explicit port.")
    if (
        parsed.path != required_path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        path_label = required_path or "/"
        raise ValueError(
            f"endpoint path must be exactly {path_label} with no query."
        )
    root = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, "", "", "", "")
    ).rstrip("/")
    normalized = urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            required_path,
            "",
            "",
            "",
        )
    )
    return LoopbackEndpoint(
        url=normalized,
        root=root,
        host=parsed.hostname,
        port=port,
        path=required_path,
    )


def read_loopback_response(
    request: str | urllib.request.Request,
    *,
    timeout_sec: float,
) -> bytes:
    """Read one loopback HTTP response without consulting proxy settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(
        request,
        timeout=max(0.001, float(timeout_sec)),
    ) as response:
        return response.read()


def endpoint_cache_dir(
    cache_dir: str | Path,
    service_name: str,
    endpoint: str,
    *,
    digest_length: int = 16,
) -> Path:
    """Return a stable endpoint-keyed directory under one runtime cache."""
    normalized = str(endpoint or "").strip().rstrip("/")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[
        :digest_length
    ]
    return Path(cache_dir).expanduser().resolve() / service_name / digest


def wait_for_service(
    probe: Callable[[], T | None],
    *,
    timeout_sec: float,
    interval_sec: float,
    process: ProcessHandle | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    on_wait: Callable[[float], None] | None = None,
) -> T:
    """Poll until a service-specific probe returns a ready value."""
    started_at = monotonic()
    deadline = started_at + max(0.0, float(timeout_sec))
    while True:
        value = probe()
        if value is not None:
            return value
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                raise LocalServiceProcessExited(exit_code)
        now = monotonic()
        if now >= deadline:
            raise LocalServiceWaitTimeout(
                f"Local service was not ready after {timeout_sec} seconds."
            )
        if on_wait is not None:
            on_wait(now - started_at)
        sleep(max(0.0, float(interval_sec)))


class VLLMServiceError(RuntimeError):
    """Raised when a configured local vLLM service cannot be used safely."""


@dataclass(frozen=True)
class VLLMServiceStatus:
    """How the configured vLLM endpoint became available to this process."""

    state: str
    endpoint: str
    served_model_name: str
    log_path: Optional[str] = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "status": self.state,
            "endpoint": self.endpoint,
            "model": self.served_model_name,
        }
        if self.log_path:
            payload["log_path"] = self.log_path
        return payload


def _parse_endpoint(endpoint: str) -> LoopbackEndpoint:
    try:
        return parse_loopback_endpoint(endpoint, required_path="/v1")
    except ValueError as exc:
        raise VLLMServiceError(f"Invalid vLLM endpoint: {exc}") from exc


def _endpoint_root(endpoint: str) -> str:
    return _parse_endpoint(endpoint).root


def _read_response(url: str, timeout_sec: float, *, loopback: bool) -> bytes:
    del loopback
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    return read_loopback_response(request, timeout_sec=timeout_sec)


def _connection_unavailable(error: BaseException) -> bool:
    if isinstance(error, (socket.timeout, TimeoutError, ConnectionRefusedError, ConnectionResetError)):
        return True
    if isinstance(error, urllib.error.URLError):
        return _connection_unavailable(error.reason)
    return False


def _included_router_error(error: BaseException) -> bool:
    """Return whether an HTTP failure matches the FastAPI router regression."""
    if not isinstance(error, urllib.error.HTTPError) or error.code != 500:
        return False
    try:
        body = error.read(8192).decode("utf-8", errors="replace")
    except (AttributeError, OSError):
        return False
    return "_IncludedRouter" in body and "attribute 'path'" in body


def _incompatible_web_stack_message() -> str:
    return (
        "The installed vLLM 0.18.0 web stack is incompatible with FastAPI "
        "0.137 or newer and makes every endpoint return HTTP 500. Install "
        f"'{_LOCAL_FASTAPI_CONSTRAINT}' in the MVAgent environment, then "
        "explicitly stop the broken persistent vLLM process before retrying."
    )


def validate_vllm_web_stack() -> None:
    """Reject the known vLLM 0.18.0/FastAPI router incompatibility."""
    try:
        vllm_version = Version(importlib.metadata.version("vllm"))
        fastapi_version = Version(importlib.metadata.version("fastapi"))
    except (importlib.metadata.PackageNotFoundError, InvalidVersion):
        return
    if vllm_version == Version("0.18.0") and fastapi_version >= Version("0.137"):
        raise VLLMServiceError(_incompatible_web_stack_message())


def probe_vllm_server(endpoint: str, *, timeout_sec: float = 2.0) -> Optional[Set[str]]:
    """Return served model IDs, ``None`` when no server is reachable, or raise on a wrong server."""

    root = _endpoint_root(endpoint)
    try:
        _read_response(f"{root}/health", timeout_sec, loopback=True)
    except BaseException as exc:
        if _connection_unavailable(exc):
            return None
        if _included_router_error(exc):
            raise VLLMServiceError(_incompatible_web_stack_message()) from exc
        raise VLLMServiceError(
            f"Configured vLLM endpoint {endpoint} responded but does not provide a usable /health endpoint: {exc}"
        ) from exc

    try:
        raw_models = _read_response(
            f"{root}/v1/models",
            timeout_sec,
            loopback=True,
        )
        payload = json.loads(raw_models.decode("utf-8"))
    except BaseException as exc:
        if _included_router_error(exc):
            raise VLLMServiceError(_incompatible_web_stack_message()) from exc
        raise VLLMServiceError(
            f"Configured vLLM endpoint {endpoint} responded but does not provide a usable /v1/models endpoint: {exc}"
        ) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise VLLMServiceError(f"Configured vLLM endpoint {endpoint} returned an invalid /v1/models response.")
    model_ids = {
        str(item.get("id")).strip()
        for item in data
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not model_ids:
        raise VLLMServiceError(f"Configured vLLM endpoint {endpoint} returned no served model IDs.")
    return model_ids


def probe_vllm_inference(
    endpoint: str,
    *,
    served_model_name: str,
    timeout_sec: float,
) -> None:
    """Require one real text completion from an otherwise healthy endpoint."""
    root = _endpoint_root(endpoint)
    payload = {
        "model": str(served_model_name).strip(),
        "messages": [{"role": "user", "content": "Reply OK."}],
        "temperature": 0.0,
        "max_tokens": 4,
    }
    request = urllib.request.Request(
        f"{root}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer EMPTY",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        raw_response = read_loopback_response(
            request,
            timeout_sec=max(0.001, float(timeout_sec)),
        )
        response = json.loads(raw_response.decode("utf-8"))
    except BaseException as exc:
        raise VLLMServiceError(
            f"Configured vLLM endpoint {endpoint} passes metadata health checks "
            "but failed a real inference readiness probe. Explicitly stop the "
            f"broken persistent vLLM process before retrying: {exc}"
        ) from exc

    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise VLLMServiceError(
            f"Configured vLLM endpoint {endpoint} returned an invalid inference "
            "readiness response. Explicitly stop the broken persistent vLLM "
            "process before retrying."
        )


class VLLMServiceManager:
    """Reuse or start one persistent, loopback-only vLLM OpenAI server."""

    def __init__(
        self,
        cfg: object,
        *,
        cache_dir: str | Path,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self._status: Optional[VLLMServiceStatus] = None
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._log = logger or (lambda message: print(message, flush=True))

    def _trace(
        self,
        event: str,
        *,
        fields: list[tuple[str, object]] | None = None,
    ) -> None:
        """Emit one atomic local-service lifecycle event."""
        lines = ["", f"MODEL vLLM | {event}"]
        lines.extend(f"  {key}: {value}" for key, value in fields or ())
        self._log("\n".join(lines))

    @property
    def service_dir(self) -> Path:
        return endpoint_cache_dir(
            self.cache_dir,
            "vllm",
            self.cfg.endpoint,
        )

    @property
    def log_path(self) -> Path:
        return self.service_dir / "server.log"

    @property
    def temp_dir(self) -> Path:
        """Return a persistent temp root beside the disposable Runtime cache."""
        name = self.cache_dir.name or "mvagent"
        return self.cache_dir.parent / f"{name}-tmp"

    @property
    def lock_path(self) -> Path:
        return (
            Path("/tmp")
            / "mvagent-vllm"
            / "locks"
            / f"{self.service_dir.name}.lock"
        )

    def _validate(self) -> LoopbackEndpoint:
        if not str(self.cfg.model_name or "").strip():
            raise VLLMServiceError("local_vllm model_name cannot be empty.")
        if not str(self.cfg.served_model_name or "").strip():
            raise VLLMServiceError("local_vllm served_model_name cannot be empty.")
        endpoint = _parse_endpoint(self.cfg.endpoint)
        gpus = self.cfg.gpus
        validate_gpu_list(
            gpus,
            label="local_vllm",
            error_class=VLLMServiceError,
        )
        if float(self.cfg.startup_timeout_sec) <= 0:
            raise VLLMServiceError("local_vllm startup_timeout_sec must be positive.")
        if not 0 < float(self.cfg.gpu_memory_utilization) <= 1:
            raise VLLMServiceError("local_vllm gpu_memory_utilization must be in (0, 1].")
        if int(self.cfg.max_model_len) <= 0:
            raise VLLMServiceError("local_vllm max_model_len must be positive.")
        if int(self.cfg.max_videos_per_request) <= 0:
            raise VLLMServiceError(
                "local_vllm max_videos_per_request must be positive."
            )
        return endpoint

    def build_start_command(self) -> list[str]:
        endpoint = self._validate()
        command = [
            "vllm",
            "serve",
            str(self.cfg.model_name),
            "--host",
            endpoint.host,
            "--port",
            str(endpoint.port),
            "--served-model-name",
            str(self.cfg.served_model_name),
            "--dtype",
            str(self.cfg.dtype),
            "--tensor-parallel-size",
            str(len(self.cfg.gpus)),
            "--gpu-memory-utilization",
            str(float(self.cfg.gpu_memory_utilization)),
            "--max-model-len",
            str(int(self.cfg.max_model_len)),
            "--limit-mm-per-prompt.video",
            str(int(self.cfg.max_videos_per_request)),
            "--mm-processor-cache-gb",
            "0",
            "--generation-config",
            "vllm",
        ]
        if str(self.cfg.reasoning_parser or "").strip():
            command.extend(["--reasoning-parser", str(self.cfg.reasoning_parser)])
        if not self.cfg.enable_thinking:
            command.extend(
                [
                    "--default-chat-template-kwargs",
                    json.dumps({"enable_thinking": False}),
                ]
            )
        return command

    @contextmanager
    def _service_lock(self) -> Iterator[None]:
        lock_dir = self.lock_path.parent
        lock_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(lock_dir, 0o1777)
        with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
            os.chmod(self.lock_path, 0o666)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _status_for_existing(self, model_ids: Set[str]) -> VLLMServiceStatus:
        expected = str(self.cfg.served_model_name).strip()
        if expected not in model_ids:
            available = ", ".join(sorted(model_ids))
            raise VLLMServiceError(
                f"Configured vLLM endpoint {self.cfg.endpoint} does not serve '{expected}' "
                f"(available: {available}). Refusing to replace an existing server."
            )
        return VLLMServiceStatus(
            state="reused",
            endpoint=str(self.cfg.endpoint),
            served_model_name=expected,
        )

    def _probe_existing(self) -> Optional[VLLMServiceStatus]:
        model_ids = probe_vllm_server(self.cfg.endpoint, timeout_sec=min(2.0, float(self.cfg.startup_timeout_sec)))
        if model_ids is None:
            return None
        status = self._status_for_existing(model_ids)
        probe_vllm_inference(
            self.cfg.endpoint,
            served_model_name=status.served_model_name,
            timeout_sec=min(
                _EXISTING_INFERENCE_PROBE_TIMEOUT_SEC,
                float(self.cfg.startup_timeout_sec),
            ),
        )
        return status

    def _probe_started_metadata(self) -> Optional[VLLMServiceStatus]:
        model_ids = probe_vllm_server(
            self.cfg.endpoint,
            timeout_sec=min(2.0, float(self.cfg.startup_timeout_sec)),
        )
        return self._status_for_existing(model_ids) if model_ids is not None else None

    def _log_tail(self, *, max_bytes: int = 4096) -> str:
        try:
            with self.log_path.open("rb") as log_handle:
                log_handle.seek(0, 2)
                position = log_handle.tell()
                log_handle.seek(max(0, position - max_bytes))
                text = log_handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return " ".join(text.split())[-max_bytes:]

    def _start_process(self) -> subprocess.Popen[bytes]:
        validate_vllm_web_stack()
        self._assert_sufficient_gpu_memory()
        self.service_dir.mkdir(parents=True, exist_ok=True)
        command = self.build_start_command()
        child_env = os.environ.copy()
        child_env["CUDA_VISIBLE_DEVICES"] = ",".join(str(gpu) for gpu in self.cfg.gpus)
        if not str(child_env.get("TMPDIR") or "").strip():
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            child_env["TMPDIR"] = str(self.temp_dir)
        self._trace(
            "Starting service",
            fields=[
                ("endpoint", self.cfg.endpoint),
                ("model", self.cfg.served_model_name),
                ("gpus", child_env["CUDA_VISIBLE_DEVICES"]),
                ("temp_dir", child_env["TMPDIR"]),
                ("log_path", self.log_path),
            ],
        )
        try:
            with self.log_path.open("ab", buffering=0) as log_handle:
                return subprocess.Popen(
                    command,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                    env=child_env,
                )
        except OSError as exc:
            raise VLLMServiceError(f"Failed to start vLLM service: {exc}") from exc

    def _assert_sufficient_gpu_memory(self) -> None:
        """Fail fast when the target GPU cannot hold the configured memory budget."""
        if shutil.which("nvidia-smi") is None:
            return
        budget = float(self.cfg.gpu_memory_utilization)
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free,memory.total",
                    "--format=csv,noheader,nounits",
                    "--id=" + ",".join(str(gpu) for gpu in self.cfg.gpus),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return
        rows = [
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip()
        ]
        for row in rows:
            parts = [part.strip() for part in row.split(",")]
            if len(parts) != 2:
                continue
            try:
                free_mib = float(parts[0])
                total_mib = float(parts[1])
            except ValueError:
                continue
            if free_mib < budget * total_mib:
                raise VLLMServiceError(
                    f"GPU memory is insufficient for the local_vllm service: "
                    f"GPU {self.cfg.gpus} has {free_mib:.0f} MiB free of "
                    f"{total_mib:.0f} MiB, below the configured "
                    f"{budget:.0%} utilization budget. Stop other processes "
                    "on the GPU or lower gpu_memory_utilization."
                )

    def _wait_for_started_service(self, process: subprocess.Popen[bytes]) -> VLLMServiceStatus:
        next_wait_trace = 0.0
        expected = str(self.cfg.served_model_name).strip()

        def trace_wait(elapsed: float) -> None:
            nonlocal next_wait_trace
            if elapsed >= next_wait_trace:
                self._trace(
                    "Waiting for service",
                    fields=[
                        ("endpoint", self.cfg.endpoint),
                        ("elapsed", f"{elapsed:.1f}s"),
                        ("log_path", self.log_path),
                    ],
                )
                next_wait_trace = elapsed + _WAIT_TRACE_INTERVAL_SEC

        started_at = time.monotonic()
        try:
            status = wait_for_service(
                self._probe_started_metadata,
                timeout_sec=float(self.cfg.startup_timeout_sec),
                interval_sec=0.25,
                process=process,
                sleep=time.sleep,
                monotonic=time.monotonic,
                on_wait=trace_wait,
            )
        except LocalServiceProcessExited as exc:
            tail = self._log_tail()
            suffix = f" Log tail: {tail}" if tail else ""
            raise VLLMServiceError(
                "vLLM service exited during startup with code "
                f"{exc.exit_code}.{suffix}"
            ) from exc
        except LocalServiceWaitTimeout as exc:
            tail = self._log_tail()
            suffix = f" Log tail: {tail}" if tail else ""
            raise VLLMServiceError(
                f"Timed out waiting for vLLM service at {self.cfg.endpoint} "
                f"after {self.cfg.startup_timeout_sec} seconds.{suffix}"
            ) from exc

        probe_vllm_inference(
            self.cfg.endpoint,
            served_model_name=expected,
            timeout_sec=min(
                float(self.cfg.timeout_sec),
                float(self.cfg.startup_timeout_sec),
            ),
        )

        ready = VLLMServiceStatus(
            state="started",
            endpoint=status.endpoint,
            served_model_name=expected,
            log_path=str(self.log_path),
        )
        self._trace(
            "Service ready",
            fields=[
                ("endpoint", ready.endpoint),
                ("model", ready.served_model_name),
                (
                    "startup_elapsed",
                    f"{time.monotonic() - started_at:.1f}s",
                ),
                ("log_path", ready.log_path),
            ],
        )
        return ready

    def ensure_running(self) -> VLLMServiceStatus:
        """Return a usable endpoint, reusing it first and never stopping it later."""

        self._validate()
        if self._status is not None:
            return self._status

        self._trace(
            "Probe endpoint",
            fields=[
                ("endpoint", self.cfg.endpoint),
                ("model", self.cfg.served_model_name),
            ],
        )
        existing = self._probe_existing()
        if existing is not None:
            self._status = existing
            self._trace(
                "Reused service",
                fields=[
                    ("endpoint", existing.endpoint),
                    ("model", existing.served_model_name),
                ],
            )
            return existing

        with self._service_lock():
            self._trace(
                "Probe endpoint after lock",
                fields=[("endpoint", self.cfg.endpoint)],
            )
            existing = self._probe_existing()
            if existing is not None:
                self._status = existing
                self._trace(
                    "Reused service",
                    fields=[
                        ("endpoint", existing.endpoint),
                        ("model", existing.served_model_name),
                    ],
                )
                return existing
            process = self._start_process()
            self._process = process
            self._status = self._wait_for_started_service(process)
            return self._status

    def close(self) -> None:
        """Intentionally keep started vLLM processes alive for future MVAgent runs."""


__all__ = [
    "VLLMServiceError",
    "VLLMServiceManager",
    "VLLMServiceStatus",
    "probe_vllm_inference",
    "probe_vllm_server",
    "validate_vllm_web_stack",
]
