"""Resume a stopped LensWalk batch without rerunning any saved model outcome."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import shutil
import time

from common import sha256, write
from lenswalk_full import EXPECTED, archive_attempt, closed_score, media_key, now, read
from lenswalk_outcome import inspect
from recover_lenswalk import PATCH_FILES, freeze, inherit_record, media_failure


def recover(previous, output):
    assert not output.exists(), 'Never overwrite historical results'
    progress = read(previous/'progress.json')
    assert progress['phase'] == 'failed'
    original = read(previous/'manifest.json')
    ids = read(previous/'samples.json')
    assert len(ids) == len(set(ids)) == sum(EXPECTED.values())
    assert sha256(previous/'samples.json') == original['samples_sha256']
    paths = list((previous/'lenswalk').glob('*/record.json'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        loaded = list(pool.map(inherit_record, paths))
    bulk = previous/'inherited_records.json'
    rows = {r['sample_id']:r for r in read(bulk).values()} if bulk.exists() else {}
    bulk_sha = sha256(bulk) if bulk.exists() else None
    evidence = {sid:dict(path=str(bulk), sha256=bulk_sha) for sid in rows}
    rows.update({sid:row for sid,row,_ in loaded})
    evidence.update({sid:source for sid,_,source in loaded})
    assert len(rows) == progress['completed'] and set(rows) <= set(ids)
    output.mkdir(parents=True)
    freeze(previous, output)
    patch = read(output/'patch_manifest.json')
    allowed = {'eval/external_methods/'+name for name in PATCH_FILES}
    assert all(patch['source_hashes'].get(name)==digest for name,digest in original['source_hashes'].items()
               if name not in allowed | {'.git/HEAD'})
    for name in ('samples.json', 'prepared/private_labels.json'):
        (output/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(previous/name, output/name)
    (output/'client_environment.tar.gz').symlink_to(previous/'client_environment.tar.gz')
    for name in ('media_cache', 'prepared/items', 'lenswalk', 'episodes'):
        (output/name).mkdir(parents=True, exist_ok=True)
    labels = read(previous/'prepared/private_labels.json')
    salvaged = {}
    for result_path in sorted((previous/'lenswalk').glob('*/attempt-*/result.json')):
        result = read(result_path)
        sid = result['sample_id']
        if sid in rows:
            continue
        assert sid in ids and sid not in salvaged
        attempt = result_path.parent
        row = inspect(attempt, read(attempt/'service_card.json'))
        from skill_evolution.infra.benchmarks.catalog import load_multibench_records
        record = load_multibench_records('/assets', [sid])[sid]
        started = read(attempt/'started.json')
        active = next(a for a in progress['active'].values() if a['sample_id']==sid)
        prep_seconds = (datetime.fromisoformat(active['started_at'])-
                        datetime.fromisoformat(started['started_at'])).total_seconds()
        assert active['phase']=='inference' and prep_seconds>=0
        archived_copy = output/'lenswalk'/sid.replace(':','_')/attempt.name
        shutil.copytree(attempt, archived_copy)
        archive_started = time.monotonic()
        archive = archive_attempt(archived_copy)
        row.update(sample_id=sid, dataset=record.dataset, task=record.native_task,
            attempt=str(attempt), seconds=result['seconds'], prepared_seconds=prep_seconds,
            timing_source='Recovered adapter seconds; outer client wall time was not saved',
            finished_at=datetime.fromtimestamp(result_path.stat().st_mtime, timezone.utc).isoformat(),
            worker=started['worker'], question_timeout=False, raw_archive=archive,
            archive_seconds=time.monotonic()-archive_started,
            score=None if row['infrastructure_error'] else closed_score(record, row['answer']))
        rows[sid] = row
        evidence[sid] = dict(path=str(result_path), sha256=sha256(result_path), raw_archive=archive)
        salvaged[sid] = dict(answer=row['answer'], terminal=row['terminal'], score=row['score'],
                            calls=row['calls'], http_errors=row['http_errors'])
    retry = [sid for sid in ids if sid in rows and media_failure(rows[sid])]
    missing = [sid for sid in ids if sid not in rows]
    pending = retry+missing
    inherited = {sid:row for sid,row in rows.items() if sid not in retry}
    write(output/'inherited_records.json', {sid.replace(':','_'):row for sid,row in inherited.items()})
    cached = 0
    for key in {media_key(labels[sid]['sample']['videos']) for sid in pending}:
        path = previous/'media_cache'/f'{key}.json'
        if path.exists():
            value = read(path)
            assert Path(value['video_path']).is_file() and Path(value['timeline_path']).is_file()
            shutil.copy2(path, output/'media_cache'/path.name)
            cached += 1
    write(output/'recovery_manifest.json', dict(created_at=now(), previous=str(previous),
        original_progress_sha256=sha256(previous/'progress.json'),
        original_manifest_sha256=sha256(previous/'manifest.json'),
        inherited={sid:evidence[sid] for sid in inherited}, salvaged=salvaged,
        retry_failures=retry, previously_unfinished=missing, pending=pending, cached_media_groups=cached,
        retained_infrastructure_failures=[sid for sid,row in inherited.items() if row['infrastructure_error']]))
    write(output/'manifest.json', dict(original, created_at=now(), recovery_from=str(previous),
        recovery_order=pending, recovery_commit=patch['commit'],
        source_snapshot=str(output/'frozen_repo'), driver_sha256=patch['driver_sha256'],
        source_hashes=patch['source_hashes']))
    write(output/'progress.json', dict(phase='prepared', expected=len(ids), completed=len(inherited),
        remaining=len(pending), updated_at=now()))
    assert len(inherited)+len(pending)==len(ids) and not set(inherited)&set(pending)
    assert all(sha256(source['path'])==source['sha256'] for _,_,source in loaded)
    assert not bulk.exists() or sha256(bulk)==bulk_sha
    print(dict(inherited=len(inherited), pending=len(pending), cached_media_groups=cached,
               retry_media=retry, salvaged=salvaged), flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    recover(args.previous, args.output)
