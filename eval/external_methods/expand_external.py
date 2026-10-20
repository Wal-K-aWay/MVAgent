"""Split two drained 27B groups into four owners, preserving every saved outcome."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from common import sha256, write
from lenswalk_partition import read, merge
from rsi_parallel import partition


def assign(ids, rows, costs):
    pending = [sid for sid in ids if sid not in rows]
    groups, loads = partition(pending, {sid: costs[sid] for sid in pending}, 4)
    for index, sid in enumerate(sid for sid in ids if sid in rows):
        groups[index % 4].append(sid)
    owners = [set(group) for group in groups]
    assert set().union(*owners) == set(ids) and sum(map(len, owners)) == len(ids)
    return [[sid for sid in ids if sid in group] for group in owners], loads


def initialize(previous, output, method):
    assert not output.exists(), 'Never overwrite an expansion'
    parent = read(previous/'manifest.json')
    assert parent['model'] == '27B' and len(parent['children']) == 2
    ids = read(previous/'samples.json')
    assert len(ids) == len(set(ids)) == 5321
    roots = [Path(child['root']) for child in parent['children']]
    template = read(roots[0]/'manifest.json')
    rows, sources = {}, {}
    def fingerprint(path):
        sources[str(path)] = dict(path=str(path), sha256=sha256(path))
    for root in roots:
        original = read(root/'manifest.json')
        assert original['driver_sha256'] == template['driver_sha256']
        assert original['source_hashes'] == template['source_hashes']
        assert read(root/'expected_service.json') == read(roots[0]/'expected_service.json')
        snapshot, drained = read(root/'handoff_snapshot.json'), read(root/'handoff_drained.json')
        assert drained['inference_retries'] == 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            checked = dict(pool.map(lambda p: (p.name, sha256(p)), (root/'records').glob('*.json')))
        assert all(checked[name] == digest for name, digest in snapshot['old_records'].items())
        assert len(checked) == len(snapshot['old_records']) + len(drained['preserved_inflight'])
        inherited = read(root/'inherited_records.json')
        fingerprint(root/'inherited_records.json')
        local = dict(inherited)
        for path in (root/'records').glob('*.json'):
            local[path.stem] = read(path)
            sources[str(path)] = dict(path=str(path), sha256=checked[path.name])
        for sid in drained['preserved_inflight']:
            archive = local[sid.replace(':', '_')]['raw_archive']
            assert sha256(archive['path']) == archive['sha256'], sid
        for row in local.values():
            sid = row['sample_id']
            assert sid not in rows
            rows[sid] = row
        fingerprint(root/'manifest.json')
        fingerprint(root/'handoff_drained.json')
    assert set(rows) <= set(ids)
    source = roots[0]/'frozen_repo'
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = dict(pool.map(lambda name: (name, sha256(source/name)), template['source_hashes']))
    assert actual == template['source_hashes']
    driver = (source/'eval/external_methods/lenswalk_full.py').read_text()
    assert "EXPECTED=manifest['expected_counts']" in driver
    history = Path('/runs/devbox')/('rsi_full_35b_parallel_media_20261018' if method == 'rsi'
                                   else 'lenswalk_full_35b_parallel_media_20261018')/'summary.json'
    costs = {row['sample_id']: sum(row[k] for k in ('seconds', 'prepared_seconds', 'archive_seconds'))
             for row in read(history)['rows']}
    groups, loads = assign(ids, rows, costs)
    commit = (Path(__file__).resolve().parents[2]/'.git/HEAD').read_text().strip()
    children = []
    for index, assigned in enumerate(groups):
        child = output.parent/(output.name+'-shard'+str(index))
        child.mkdir()
        # The runtime is unchanged; reference its existing immutable snapshot instead of copying it four times.
        (child/'frozen_repo').symlink_to(source.resolve(), target_is_directory=True)
        for name in ('expected_service.json', 'prepared/private_labels.json'):
            (child/name).parent.mkdir(parents=True, exist_ok=True)
            (child/name).symlink_to((roots[0]/name).resolve())
        name = 'client_environment.json' if method == 'rsi' else 'client_environment.tar.gz'
        (child/name).symlink_to((roots[0]/name).resolve())
        for name in (method, 'records', 'raw', 'judgements', 'episodes'):
            (child/name).mkdir()
        inherited = {sid.replace(':', '_'): rows[sid] for sid in assigned if sid in rows}
        write(child/'samples.json', assigned)
        write(child/'inherited_records.json', inherited)
        write(child/'manifest.json', dict(template, method=method, model='27B', recovery_order=assigned,
              source_snapshot=str(child/'frozen_repo'), expected_counts=dict(Counter(s.split(':')[0] for s in assigned)),
              samples_sha256=sha256(child/'samples.json'), full_panel_sha256=sha256(previous/'samples.json'),
              inherited_count=len(inherited), partition_index=index, expansion_commit=commit,
              source_snapshot_reference=str(source), expansion_from=str(previous)))
        write(child/'progress.json', dict(phase='prepared', expected=len(assigned), completed=len(inherited),
                                         models={'27B': {'finished': len(inherited)}}))
        children.append(dict(root=str(child), expected=len(assigned), inherited=len(inherited),
                             pending=len(assigned)-len(inherited), historical_pending_seconds=loads[index],
                             samples_sha256=sha256(child/'samples.json')))
    output.mkdir()
    write(output/'samples.json', ids)
    write(output/'manifest.json', dict(method=method, model='27B', created_at=template['created_at'],
          children=children, inherited_sources=sources, inherited_answers=len(rows), previous=str(previous),
          expansion_commit=commit, total_gpus=32, inference_retries=0,
          timing_source=str(history), timing_source_sha256=sha256(history),
          partition_policy='Four disjoint owners balanced by historical pending work; preserve all saved outcomes'))
    write(output/'progress.json', dict(phase='prepared', expected=5321, completed=len(rows), children=children))
    print(json.dumps(dict(method=method, preserved=len(rows), children=children)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize', 'merge'])
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=['lenswalk', 'rsi'])
    args = parser.parse_args()
    if args.action == 'initialize':
        assert args.previous and args.method
        initialize(args.previous, args.output, args.method)
    else:
        merge(args.output)
