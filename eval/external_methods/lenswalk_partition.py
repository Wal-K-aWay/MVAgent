"""Split the frozen LensWalk panel without repeating any saved outcome."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading

from common import sha256, write
from lenswalk_models import replace_once


def read(path):
    return json.loads(Path(path).read_text())


def partition(ids, completed):
    assert len(ids) == len(set(ids)) and set(completed) <= set(ids)
    groups = [[], []]
    # Balance pending work within each benchmark; inherited outcomes cost no inference.
    for saved in (False, True):
        for dataset in sorted({sid.split(':')[0] for sid in ids}):
            subset = [sid for sid in ids if (sid in completed) == saved and sid.split(':')[0] == dataset]
            for index, sid in enumerate(subset):
                groups[index % 2].append(sid)
    assert not set(groups[0]) & set(groups[1])
    assert set(groups[0]) | set(groups[1]) == set(ids)
    owners = [set(group) for group in groups]
    return [[sid for sid in ids if sid in group] for group in owners]


def patch_driver(source):
    source = replace_once(source, 'def main(output):\n', 'def main(output):\n    global EXPECTED\n')
    source = replace_once(source, "    manifest=read(output/'manifest.json')\n",
                          "    manifest=read(output/'manifest.json')\n    EXPECTED=manifest['expected_counts']\n")
    compile(source, '<partitioned frozen LensWalk>', 'exec')
    return source


def initialize(previous, output):
    assert not output.exists(), 'Never overwrite a run'
    receipt = read(previous/'SCHEDULING_STOPPED.json')
    assert receipt['sandbox_exit_code'] is not None
    original = read(previous/'manifest.json')
    assert original['model'] == '9B'
    ids = read(previous/'samples.json')
    assert len(ids) == 5321 and sha256(previous/'samples.json') == original['samples_sha256']
    rows = read(previous/'inherited_records.json')
    sources = {}
    for path in (previous/'records').glob('*.json'):
        row = read(path)
        rows[path.stem] = row
        sources[row['sample_id']] = dict(path=str(path), sha256=sha256(path))
    by_id = {row['sample_id']: row for row in rows.values()}
    assert len(by_id) == len(rows)
    # A result without a record must be salvaged before any question can be reassigned.
    assert not [p for p in (previous/'lenswalk').glob('*/attempt-*/result.json')
                if p.parent.parent.name not in rows]
    groups = partition(ids, by_id)
    commit = (Path(__file__).resolve().parents[2]/'.git/HEAD').read_text().strip()
    children = []
    for index, assigned in enumerate(groups):
        child = output.parent/(output.name+'-shard'+str(index))
        assert not child.exists()
        frozen = child/'frozen_repo'
        shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
        driver = frozen/'eval/external_methods/lenswalk_full.py'
        assert sha256(driver) == original['driver_sha256']
        driver.write_text(patch_driver(driver.read_text()))
        (frozen/'.git/HEAD').write_text(commit+'\n')
        files = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        with ThreadPoolExecutor(max_workers=8) as pool:
            hashes = dict(zip((str(p.relative_to(frozen)) for p in files), pool.map(sha256, files)))
        allowed = {'eval/external_methods/lenswalk_full.py', '.git/HEAD'}
        assert all(hashes[name] == value for name, value in original['source_hashes'].items() if name not in allowed)
        for name in ('prepared/private_labels.json', 'expected_service.json'):
            (child/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous/name, child/name)
        (child/'client_environment.tar.gz').symlink_to((previous/'client_environment.tar.gz').resolve())
        for name in ('lenswalk', 'records', 'raw', 'judgements', 'episodes'):
            (child/name).mkdir()
        write(child/'samples.json', assigned)
        inherited = {sid.replace(':', '_'): by_id[sid] for sid in assigned if sid in by_id}
        write(child/'inherited_records.json', inherited)
        expected = dict(Counter(sid.split(':')[0] for sid in assigned))
        write(child/'manifest.json', dict(original, recovery_from=str(previous), recovery_order=assigned,
              source_snapshot=str(frozen), driver_commit=commit, driver_sha256=sha256(driver), source_hashes=hashes,
              samples_sha256=sha256(child/'samples.json'), full_panel_sha256=original['samples_sha256'],
              expected_counts=expected, inherited_count=len(inherited), partition_index=index))
        write(child/'progress.json', dict(phase='prepared', expected=len(assigned), completed=len(inherited),
              models={'9B': {'finished': len(inherited)}}))
        children.append(dict(root=str(child), expected=len(assigned), inherited=len(inherited),
                             pending=len(assigned)-len(inherited), samples_sha256=sha256(child/'samples.json')))
    output.mkdir()
    shutil.copy2(previous/'samples.json', output/'samples.json')
    write(output/'manifest.json', dict(original, children=children, inherited_sources=sources,
          previous=str(previous), partition_commit=commit, stopping_receipt=receipt))
    write(output/'progress.json', dict(phase='prepared', expected=len(ids), completed=len(rows), children=children))
    print(json.dumps(children), flush=True)


def merge(output):
    manifest = read(output/'manifest.json')
    ids = read(output/'samples.json')
    rows = {}
    for child in manifest['children']:
        root = Path(child['root'])
        assert read(root/'progress.json')['phase'] in ('completed', 'completed_with_errors')
        assert sha256(root/'samples.json') == child['samples_sha256']
        selected = read(root/'summary.json')['rows']
        assert {r['sample_id'] for r in selected} == set(read(root/'samples.json'))
        for row in selected:
            key = row['sample_id'].replace(':', '_')
            assert key not in rows, 'Duplicate question across partitions'
            rows[key] = row
    assert len(rows) == len(ids) == 5321 and {r['sample_id'] for r in rows.values()} == set(ids)
    for source in manifest['inherited_sources'].values():
        assert sha256(source['path']) == source['sha256'], 'An original saved outcome changed'
    driver = Path(manifest['children'][0]['root'])/'frozen_repo/eval/external_methods/lenswalk_full.py'
    sys.path[:0] = [str(driver.parent), str(driver.parents[2]/'src'), str(driver.parents[2])]
    spec = importlib.util.spec_from_file_location('partition_frozen_driver', driver)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    records = load_multibench_records('/assets', ids)
    assert not any(not r['infrastructure_error'] and r['task']=='CCQA' and r['score'] is None for r in rows.values())
    # All Judge calls were done by each question's unique owner; aggregation is CPU-only.
    module.score_all(output, records, rows, {}, lambda: None, threading.Event(), output)
    write(output/'progress.json', dict(phase='completed_with_errors' if any(r['infrastructure_error'] for r in rows.values()) else 'completed',
          expected=len(ids), completed=len(rows), children=manifest['children'], duplicate_ids=0,
          models={'9B': {'finished': len(rows)}}))
    print('Merged 5321 distinct scored outcomes; original records unchanged', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize', 'merge'])
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    initialize(args.previous, args.output) if args.action == 'initialize' else merge(args.output)
