"""Fresh Video-RSI 9B panel on four disjoint eight-H100 groups."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_models import replace_once
from lenswalk_partition import merge, read

TEMPLATE = Path('/runs/devbox/rsi_full_35b_parallel_media_20261018')
WEIGHTS_SOURCE = Path('/runs/devbox/lenswalk_full_9b_20261019/expected_service.json')
EXPECTED = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}


def partition(ids, costs):
    assert len(ids)==len(set(ids)) and set(ids)==set(costs)
    groups, loads = [[] for _ in range(4)], [0.0]*4
    # Historical runtimes balance ownership only; answers never enter the new model's input.
    for sid in sorted(ids, key=lambda sid: (-costs[sid], sid)):
        assert costs[sid]>=0
        index = min(range(4), key=lambda i: (loads[i], len(groups[i]), i))
        groups[index].append(sid)
        loads[index] += max(1, costs[sid])
    assert len(set().union(*map(set, groups)))==sum(map(len, groups))==len(ids)
    owners = [set(group) for group in groups]
    return [[sid for sid in ids if sid in group] for group in owners], loads


def patch_driver(source):
    changes = [
        ("'--model','/weights/Qwen3.5-35B-A3B'", "'--model','/weights/Qwen3.5-9B'"),
        ('def main(output):\n', 'def main(output):\n    global EXPECTED\n'),
        ("    manifest=read(output/'manifest.json')\n", "    manifest=read(output/'manifest.json')\n    EXPECTED=manifest['expected_counts']\n"),
        ("models={'35B-A3B':{'finished':len(values)}}", "models={'9B':{'finished':len(values)}}"),
        ("rows.update({p.parent.name:read(p) for p in (output/method).glob('*/record.json')})",
         "rows.update({p.stem:read(p) for p in (output/'records').glob('*.json')})"),
        ("                outcome['raw_archive']=archive_attempt(attempt,compress=method=='lenswalk')\n",
         "                outcome['raw_archive']=archive_attempt(attempt,compress=method=='lenswalk')\n"
         "                archive=Path(outcome['raw_archive']['path'])\n"
         "                target=output/'raw'/(directory.name+'-'+archive.name)\n"
         "                archive.replace(target);outcome['raw_archive']['path']=str(target)\n"),
        ("                write(directory/'record.json',outcome)\n",
         "                write(output/'records'/(directory.name+'.json'),outcome)\n"
         "                if not any(directory.iterdir()):directory.rmdir()\n"),
        ("                directory=output/method/row['sample_id'].replace(':','_');write(directory/'judge.json',result)",
         "                directory=output/'records';key=row['sample_id'].replace(':','_');write(output/'judgements'/(key+'.json'),result)"),
        ("write(directory/'record.json',row)", "write(directory/(key+'.json'),row)"),
    ]
    for before, after in changes:
        source = replace_once(source, before, after)
    compile(source, '<four-group RSI 9B driver>', 'exec')
    return source


def initialize(output):
    assert not output.exists(), 'Never overwrite a run'
    original = read(TEMPLATE/'manifest.json')
    assert read(TEMPLATE/'progress.json')['phase']=='completed_with_errors'
    assert original['method']=='rsi' and original['simultaneous_media_preparations']==8
    ids = read(TEMPLATE/'samples.json')
    assert len(ids)==len(set(ids))==5321 and dict(Counter(s.split(':')[0] for s in ids))==EXPECTED
    assert sha256(TEMPLATE/'samples.json')==original['samples_sha256']
    history = read(TEMPLATE/'summary.json')['rows']
    assert {row['sample_id'] for row in history}==set(ids)
    times = {row['sample_id']:{k:row[k] for k in ('dataset','task','seconds','prepared_seconds','archive_seconds','infrastructure_error')}
             for row in history}
    costs = {sid:sum(row[k] for k in ('seconds','prepared_seconds','archive_seconds')) for sid,row in times.items()}
    groups, loads = partition(ids, costs)
    expected_service = read(TEMPLATE/'expected_service.json')
    expected_service['weights_manifest'] = read(WEIGHTS_SOURCE)['weights_manifest']
    assert expected_service['weights_manifest']['shards']
    source = Path(__file__).resolve().parents[2]
    commit = (source/'.git/HEAD').read_text().strip()
    now = datetime.now(timezone.utc).isoformat()
    children = []
    for index, assigned in enumerate(groups):
        child = output.parent/(output.name+'-shard'+str(index))
        assert not child.exists()
        frozen = child/'frozen_repo'
        shutil.copytree(TEMPLATE/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
        driver = frozen/'eval/external_methods/lenswalk_full.py'
        assert sha256(driver)==original['driver_sha256']
        driver.write_text(patch_driver(driver.read_text()))
        (frozen/'.git/HEAD').write_text(commit+'\n')
        files = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        with ThreadPoolExecutor(max_workers=8) as pool:
            hashes = dict(zip((str(p.relative_to(frozen)) for p in files), pool.map(sha256, files)))
        allowed = {'eval/external_methods/lenswalk_full.py', '.git/HEAD'}
        assert all(hashes[name]==digest for name,digest in original['source_hashes'].items() if name not in allowed)
        for name in ('client_environment.json','prepared/private_labels.json'):
            (child/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TEMPLATE/name, child/name)
        for name in ('rsi','records','raw','judgements','episodes'):
            (child/name).mkdir()
        write(child/'samples.json', assigned)
        write(child/'inherited_records.json', {})
        write(child/'expected_service.json', expected_service)
        first = [next(sid for sid in assigned if sid.startswith(dataset+':')) for dataset in EXPECTED]
        order = first+[sid for sid in assigned if sid not in first]
        manifest = dict(original, created_at=now, model='9B', model_root='/weights/Qwen3.5-9B',
              source_snapshot=str(frozen), driver_commit=commit, driver_sha256=sha256(driver), source_hashes=hashes,
              samples_sha256=sha256(child/'samples.json'), full_panel_sha256=original['samples_sha256'],
              expected_counts=dict(Counter(s.split(':')[0] for s in assigned)), recovery_order=order,
              inherited_count=0, partition_index=index, template=str(TEMPLATE),
              result_layout='Flat records/raw/judgements; only active questions have scratch directories')
        for name in ('recovery_from','recovery_commit','existing_cached_groups'):
            manifest.pop(name, None)
        write(child/'manifest.json', manifest)
        write(child/'source_audit.json', dict(template_manifest_sha256=sha256(TEMPLATE/'manifest.json'),
              permitted_changes=sorted(allowed), unchanged_source_files=len(original['source_hashes'])-len(allowed),
              inherited_answers=0, weights_source=str(WEIGHTS_SOURCE), weights_source_sha256=sha256(WEIGHTS_SOURCE)))
        write(child/'progress.json', dict(phase='prepared', expected=len(assigned), completed=0,
              updated_at=now, models={'9B': {'finished': 0}}))
        children.append(dict(root=str(child), expected=len(assigned), inherited=0, pending=len(assigned),
              historical_work_seconds=loads[index], samples_sha256=sha256(child/'samples.json')))
    output.mkdir()
    shutil.copy2(TEMPLATE/'samples.json', output/'samples.json')
    write(output/'historical_timing.json', times)
    write(output/'manifest.json', dict(method='rsi', model='9B', created_at=now, children=children,
          inherited_sources={}, inherited_answers=0, template=str(TEMPLATE), source_commit=commit,
          samples_sha256=original['samples_sha256'], expected_counts=EXPECTED, total_gpus=32,
          partition_policy='Balance historical 35B preparation+inference+archive time; no historical answers inherited',
          historical_35b_32gpu_hours=max(loads)/8/3600))
    write(output/'progress.json', dict(phase='prepared', expected=5321, completed=0, children=children))
    print(json.dumps(dict(children=children, inherited_answers=0, historical_35b_32gpu_hours=max(loads)/8/3600,
                          source_commit=commit)), flush=True)


def estimate(output):
    now = datetime.now(timezone.utc)
    manifest = read(output/'manifest.json')
    history = read(output/'historical_timing.json')
    groups, rows = [], []
    for child in manifest['children']:
        root = Path(child['root']); progress = read(root/'progress.json')
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(read, (root/'records').glob('*.json')))
        rows.extend(values)
        starts = [datetime.fromisoformat(r['finished_at']).timestamp()-r['seconds']-r['prepared_seconds'] for r in values]
        elapsed = now.timestamp()-min(starts) if starts else None
        rate = len(values)/elapsed*3600 if elapsed and elapsed>0 else None
        groups.append(dict(root=str(root), phase=progress['phase'], completed=len(values), expected=child['expected'],
                           infrastructure_failures=sum(r['infrastructure_error'] for r in values),
                           terminal_answers=sum(r['terminal']=='finish' and not r['infrastructure_error'] for r in values),
                           processed_questions_per_hour=rate, measurement_seconds=elapsed))
    assert len(rows)==len({r['sample_id'] for r in rows}), 'Duplicate question across groups'
    paired = [r for r in rows if not r['infrastructure_error'] and not history[r['sample_id']]['infrastructure_error']]
    old_inference = sum(history[r['sample_id']]['seconds'] for r in paired)
    ratio = sum(r['seconds'] for r in paired)/old_inference if old_inference else None
    timing = {}
    for dataset in EXPECTED:
        selected = [r for r in paired if history[r['sample_id']]['dataset']==dataset]
        previous = sum(history[r['sample_id']]['seconds'] for r in selected)
        timing[dataset] = dict(samples=len(selected), ratio=sum(r['seconds'] for r in selected)/previous
                               if len(selected)>=3 and previous else None)
    projections=[]
    completed = {r['sample_id'] for r in rows}
    for child in manifest['children']:
        todo=[sid for sid in read(Path(child['root'])/'samples.json') if sid not in completed]
        work=sum(history[sid]['seconds']*(timing[history[sid]['dataset']]['ratio']
                 if timing[history[sid]['dataset']]['ratio'] is not None else 1)
                 +history[sid]['prepared_seconds']+history[sid]['archive_seconds'] for sid in todo)
        projections.append(work/8/3600)
    result=dict(updated_at=now.isoformat(), completed=len(rows), expected=5321, groups=groups,
          paired_valid_samples=len(paired), paired_9b_to_35b_inference_ratio=ratio, projected_remaining_hours=max(projections),
          paired_timing_by_dataset=timing, estimate_source_sha256=sha256(Path(__file__)),
          provisional=any(g['completed']<50 or (g['measurement_seconds'] or 0)<3600 for g in groups)
                      or any(t['samples']<20 for t in timing.values()),
          limitations='Early completed questions favor short runs; historical media timing includes prior cache regimes. Benchmarks with fewer than 3 valid pairs retain the historical timing placeholder. Projection excludes resource queues, loading and final Judge; 32/8=4 is a capacity ceiling, not a measured speedup.')
    write(output/'speed_estimate.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize','merge','estimate'])
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    {'initialize':initialize, 'merge':merge, 'estimate':estimate}[args.action](args.output)
