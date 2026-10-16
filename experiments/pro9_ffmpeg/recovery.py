"""Preserve the first attempt and rerun only its failed questions."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import run

PARENT = Path('/runs/devbox/pro9_ffmpeg_27b_20261016')


def prepare():
    assert run.SIZE == '27B' and run.ROOT != PARENT
    if (run.ROOT/'recovery_manifest.json').exists():
        return
    jobs = run.read(PARENT/'jobs.json')
    def load(job):
        path = PARENT/run.SIZE/'records'/job['dataset']/job['sample_id']/'result.json'
        return job, path, run.read(path), run.sha(path)
    with ThreadPoolExecutor(8) as pool:
        saved = list(pool.map(load, jobs))
    failed = [job for job, _, row, _ in saved if row['status']=='error']
    assert len(saved)==330 and len(failed)==14
    assert 'crossvid:MOC:565' in {j['sample_id'] for j in failed}
    retained = []; origins = {}
    for job, path, row, digest in saved:
        sid = job['sample_id']
        origins[sid] = dict(path=str(path), sha256=digest, status=row['status'])
        if row['status']=='ok':
            assert row['result']['input']==job['inputs']
            destination = run.ROOT/run.SIZE/'records'/job['dataset']/sid
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists():destination.symlink_to(path.parent,target_is_directory=True)
            assert destination.resolve()==path.parent.resolve()
            retained.append(job)
    for name in ['base_config.json','selection.json']:
        run.write(run.ROOT/name,run.read(PARENT/name))
    run.write(run.ROOT/'jobs.json',failed+retained)
    run.write(run.ROOT/'smoke_ids.json',['crossvid:MOC:565','cvbench:34'])
    old = run.read(PARENT/'code/experiments/pro9_ffmpeg/source_provenance.json')['experiment_sha256']
    new = run.read(run.HERE/'source_provenance.json')['experiment_sha256']
    changed = [name for name in old if old[name]!=new[name]]
    assert changed==['mvagent/utils/media.py']
    run.write(run.ROOT/'recovery_manifest.json',dict(parent=str(PARENT),at=run.now(),
        failed_ids=[j['sample_id'] for j in failed],original_records=origins,
        reused=316,rerun=14,changed_source_files=changed,
        parent_source_sha256=run.sha(PARENT/'code/experiments/pro9_ffmpeg/source_provenance.json'),
        recovery_source_sha256=run.sha(run.HERE/'source_provenance.json'),
        policy='316 immutable successful records from first attempt; 14 new full rollouts with short-clip repair. No resampling or answer-based selection.'))
    print('Prepared 14 retries and 316 immutable reused records',flush=True)


def audit():
    manifest=run.read(run.ROOT/'recovery_manifest.json')
    jobs={j['sample_id']:j for j in run.read(run.ROOT/'jobs.json')}
    for sid,origin in manifest['original_records'].items():
        assert run.sha(origin['path'])==origin['sha256'],sid
        path=run.ROOT/run.SIZE/'records'/jobs[sid]['dataset']/sid/'result.json'
        row=run.read(path)
        assert row['status']=='ok' and row['result']['input']==jobs[sid]['inputs'],sid
        if origin['status']=='ok':assert path.resolve()==Path(origin['path']).resolve()
        else:assert path.resolve()!=Path(origin['path']).resolve()
    # The unchanged anchor must retain its old request hashes and generated tokens.
    def trace(root, attempt):
        row=run.read(root/'smoke/cvbench:34'/str(attempt)/'result.json')
        events=[run.read(Path(p)) for p in row['call_files']]
        return [(e['response']['audit']['input_sha256'],e['response']['choices'][0]['token_ids']) for e in events]
    assert trace(PARENT,0)==trace(run.ROOT,0)
    run.write(run.ROOT/'analysis/recovery_audit.json',dict(at=run.now(),originals_unchanged=330,
        reused_verified=316,retried_successfully=14,unchanged_anchor_tokens_equal=True,
        caveat='Combined recovery cohort; only the 14 retries use repaired media handling.'))
    print('330 results complete; original 330 files unchanged; unchanged anchor token-identical',flush=True)


if __name__=='__main__':
    {'prepare':prepare,'audit':audit}[sys.argv[1]]()
