#!/usr/bin/env python3
"""Prepare a continuation of the interrupted matrix, changing only HTTP body admission."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys


def patch_transport(text):
    old = "if not 0 < length <= 512*1024*1024:"
    message = "Request body must be between 1 byte and 512 MiB"
    if text.count(old) != 1 or text.count(message) != 1:
        raise ValueError('Unexpected frozen HTTP implementation')
    return text.replace(old, "if not 0 < length <= 2*1024*1024*1024:").replace(
        message, "Request body must be between 1 byte and 2 GiB")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(source, output):
    source, output = source.absolute(), output.absolute()
    assert source.resolve().is_relative_to(Path('/runs').resolve())
    assert output.resolve().is_relative_to(Path('/runs').resolve())
    assert source != output and not output.exists(), 'Use a fresh continuation directory'
    read = lambda p: json.loads(p.read_text())
    original = source/'frozen_repo'
    old_manifest = read(source/'manifest.json')
    old_run = read(source/'9B/run_manifest.json')
    selected = read(source/'samples.json')
    failed = sorted(set(re.findall(r'(?:cvbench:[0-9]+|crossvid:[A-Z]+:[0-9]+)', old_run['error'])))
    assert len(selected) == 5321 and len(set(selected)) == 5321
    assert len(failed) == 101 and set(failed) <= set(selected)
    assert read(source/'progress.json')['phase'] == 'failed'
    oversized = []
    for sid in failed:
        row = read(source/'9B/records'/sid.split(':')[0]/sid/'result.json')
        assert row['status'] == 'error'
        size = max(e.get('body_bytes', 0) for e in row['events'] if e['kind'] == 'request_prepared')
        assert 512*1024**2 < size <= 2*1024**3, (sid, size)
        oversized.append(dict(sample_id=sid, body_bytes=size, error=row['error']))
    output.mkdir(parents=True)
    frozen = output/'frozen_repo'
    shutil.copytree(original, frozen, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
    server = frozen/'src/models/vlm/local/sync_server.py'
    server.write_text(patch_transport(server.read_text()))
    launcher = frozen/'prelaunch.py'
    text = launcher.read_text()
    for old, new in ((str(original), str(frozen)), (str(original.resolve()), str(frozen.resolve()))):
        text = text.replace(old, new)
    launcher.write_text(text)
    changes = []
    for relative, expected in old_manifest['source_hashes'].items():
        before = hashlib.sha256((original/relative).read_bytes()).hexdigest()
        assert before == expected, f'Original frozen source changed: {relative}'
        after = hashlib.sha256((frozen/relative).read_bytes()).hexdigest()
        if after != before:
            changes.append(dict(path=relative, before=before, after=after))
    assert [r['path'] for r in changes] == ['src/models/vlm/local/sync_server.py']
    # Media is addressed by its existing content keys; raw result files are never edited in place.
    (output/'media').symlink_to(source/'media', target_is_directory=True)
    sys.path[:0] = [str(frozen/'scripts'), str(frozen/'src')]
    os.environ['MVAGENT_PROJECT_ROOT'] = str(frozen.resolve())
    driver = load('continuation_driver', frozen/'scripts/run_full_mvagent.py')
    manifest = driver.prepare(output)
    assert read(output/'samples.json') == selected
    runner = load('continuation_runner', frozen/'eval/agent_eval/run.py')
    _, _, _, _, run_manifest = runner._prepare_output(
        output_dir=output/'9B', config_path=Path(manifest['configs']['9B']), dataset_root=Path('/assets'),
        sample_ids=tuple(selected), judge_model=None, resume=False, defer_open_qa_judge=True)
    run_manifest['scorer_identity'] = old_run['scorer_identity']
    run_manifest['inherited_from'] = str(source/'9B')
    runner._atomic_json(output/'9B/run_manifest.json', run_manifest)
    inherited = []
    for sid in selected:
        if sid in failed:
            continue
        relative = Path('9B/records')/sid.split(':')[0]/sid/'result.json'
        origin = source/relative
        assert origin.is_file(), sid
        target = output/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(origin)
        inherited.append(dict(sample_id=sid, source=str(origin), bytes=origin.stat().st_size))
    assert len(inherited) == 5220
    driver.write(output/'recovery.json', dict(source=str(source), output=str(output), changes=changes,
        inherited=inherited, retry=oversized, inference_changed=False,
        note='Existing successful raw records are referenced unchanged; atomic rescoring replaces links, not source files.'))
    driver.write(output/'progress.json', dict(started_at=driver.now(), phase='prepared', models={}, comparisons={}))
    shutil.copy2(__file__, output/'recovery_source.py')
    print(json.dumps(dict(prepared=str(output), inherited=len(inherited), retry=len(failed),
        largest_failed_body=max(r['body_bytes'] for r in oversized))), flush=True)


def self_check():
    old = "if not 0 < length <= 512*1024*1024:\n    raise ValueError('Request body must be between 1 byte and 512 MiB')\n"
    expected = "if not 0 < length <= 2*1024*1024*1024:\n    raise ValueError('Request body must be between 1 byte and 2 GiB')\n"
    assert patch_transport(old) == expected
    try:
        patch_transport(expected)
    except ValueError:
        pass
    else:
        raise AssertionError('Changed source must not be patched again')
    print('Frozen transport patch checks passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    elif args.source and args.output:
        prepare(args.source, args.output)
    else:
        parser.error('--source and --output are required')
