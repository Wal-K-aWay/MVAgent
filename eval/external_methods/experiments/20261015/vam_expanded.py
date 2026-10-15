"""Run VAM on the same 65-question panel and compare with the completed RSI batch."""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

ADAPTERS=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ADAPTERS),str(ADAPTERS/'experiments/20261014')]
from common import sha256, write
from current_smoke import infer, score
from original_images import summarize

BASE=Path('/runs/devbox/external_original_images_20261015')
SOURCE=Path('/runs/devbox/external_call_audit_20261015_r2/frozen_repo')
ROOT=Path('/runs/devbox/external_vam65_20261015')
SUPPORT=Path('/runs/devbox/external_methods_20261014/support')


def prepare():
    ROOT.mkdir(exist_ok=False)
    frozen=ROOT/'frozen_repo'
    shutil.copytree(SOURCE,frozen,ignore=shutil.ignore_patterns('__pycache__'))
    (frozen/'source_manifest.json').rename(frozen/'previous_source_manifest.json')
    shutil.copytree(ADAPTERS,frozen/'eval/external_methods',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    files={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}
    write(frozen/'source_manifest.json',dict(parent=str(SOURCE),files=files))
    shutil.copytree(BASE/'prepared',ROOT/'prepared',ignore=shutil.ignore_patterns('judge_cache'))
    items=json.loads((ROOT/'prepared/items.json').read_text())
    ids=[i['sample_id'] for i in items]
    assert len(ids)==len(set(ids))==65
    assert Counter(i.split(':')[0] for i in ids)==dict(crossvid=19,cvbench=30,mvu_eval=16)
    assert sha256(ROOT/'prepared/items.json')==sha256(BASE/'prepared/items.json')
    assert all(Path(i['video_path']).is_file() for i in items)
    for name in ('vam.py','native_server.py','embedding_server.py'):
        assert sha256(frozen/'eval/external_methods'/name)==sha256(SOURCE/'eval/external_methods'/name)
    rsi=json.loads((BASE/'rsi/progress.json').read_text())
    assert rsi['successful']==rsi['expected']==65 and rsi['failed']==0
    historical=json.loads((BASE/'latency_audit_20261015/analysis.json').read_text())['methods']['rsi']
    assert not historical['http_errors'] and max(r['seconds'] for r in historical['calls'])<600
    (ROOT/'rsi').mkdir()
    for name in ('progress.json','scores.json'):
        shutil.copy2(BASE/'rsi'/name,ROOT/'rsi'/name)
    write(ROOT/'rsi/reused_from.json',dict(root=str(BASE/'rsi'),actual_http_seconds=1860,
        requested_http_seconds=600,all_observed_requests_under_600=True,
        note='Reuse completed measurements, not a new run at HTTP600.'))
    env=dict(os.environ,PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    subprocess.run([sys.executable,'-m','compileall','-q',str(frozen/'eval/external_methods')],env=env,check=True)
    # Exercise the reporting path against completed results without inference or rescoring.
    fixture=ROOT/'report_test'
    fixture.mkdir()
    for name in ('prepared','rsi','vam'):
        (fixture/name).symlink_to(BASE/name,target_is_directory=True)
    for name in ('ready.json','progress.json','analysis.json'):
        shutil.copy2(BASE/name,fixture/name)
    summarize(fixture)
    report=json.loads((fixture/'final_summary.json').read_text())
    assert report['methods']['rsi']['datasets']['crossvid']['scored']==19
    assert report['methods']['vam']['datasets']['cvbench']['scored']==1
    write(ROOT/'ready.json',dict(samples=65,counts=dict(Counter(i.split(':')[0] for i in ids)),
        model='Qwen3.5-35B-A3B',rsi_result_source=str(BASE),rsi_actual_http_seconds=1860,
        rsi_current_http_seconds=600,rsi_all_requests_under_600=True,vam_http_seconds=240,
        vam_samples_fresh=65,vam_actor_replicas=7,embedding_replicas=1,
        source_manifest_sha256=sha256(frozen/'source_manifest.json'),
        selection_sha256=sha256(ROOT/'prepared/items.json'),
        duration_seconds=dict(total=sum(i['duration'] for i in items),
            median=statistics.median(i['duration'] for i in items),maximum=max(i['duration'] for i in items))))
    print('Frozen VAM65 panel and report check passed',flush=True)


def run():
    try:
        infer(ROOT,vam_only=True)
        score(ROOT,methods=('vam',))
        analysis=json.loads((ROOT/'analysis.json').read_text())
        analysis['methods']['rsi']=json.loads((BASE/'analysis.json').read_text())['methods']['rsi']
        write(ROOT/'analysis.json',analysis)
        summarize(ROOT)
        report=json.loads((ROOT/'final_summary.json').read_text())
        failures=[]
        for method in ('rsi','vam'):
            for row in report['methods'][method]['failures']:
                path=ROOT/method/row['sample_id'].replace(':','_')
                log=path/'job.log'
                failures.append(dict(method=method,**row,log=str(log),
                    diagnostic=log.read_text(errors='replace')[-2000:] if log.exists() else 'No job log'))
        report['failure_details']=failures
        report['provenance']=dict(rsi=str(BASE/'rsi'),vam=str(ROOT/'vam'),
            rsi_actual_timeout=1860,vam_timeout=240,rsi_replicas=6,vam_replicas=7,
            comparison='Same questions/media; per-question latency and differently sized batch walls reported separately.')
        write(ROOT/'final_summary.json',report)
        with (ROOT/'report.md').open('a') as stream:
            stream.write('\nRSI reuses the completed 1860-second run; every observed request was below 600 seconds. '
                         'VAM is a fresh 65-question run at HTTP240. RSI used six actor replicas; VAM uses seven.\n')
            stream.write('\nRuntime failures: '+(', '.join(r['method']+'/'+r['sample_id'] for r in failures) or 'none')+'\n')
            stream.write('\nFull per-question errors, all attempt times, and request-error counts: final_summary.json and analysis.json.\n')
        state=json.loads((ROOT/'progress.json').read_text())
        state.update(final_report=str(ROOT/'report.md'),finished_at=datetime.now(timezone.utc).isoformat())
        write(ROOT/'progress.json',state)
    except BaseException as exc:
        path=ROOT/'progress.json'
        state=json.loads(path.read_text()) if path.exists() else {}
        write(path,dict(state,phase='failed',error=repr(exc),at=datetime.now(timezone.utc).isoformat()))
        raise


if __name__=='__main__':
    {'prepare':prepare,'run':run}[sys.argv[1]]()
