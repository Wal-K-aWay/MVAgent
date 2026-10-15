"""Freeze and evaluate native image settings, reusing the verified multi-video inputs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

ADAPTERS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ADAPTERS))
from common import sha256, write

BASE = Path('/runs/devbox/external_upstream_20261015')
REPAIRED = Path('/runs/devbox/external_upstream_nc80_20261015')
ROOT = Path('/runs/devbox/external_original_images_20261015')
SUPPORT = '/runs/devbox/external_methods_20261014/support'


def prepare():
    ROOT.mkdir(exist_ok=False)
    frozen = ROOT/'frozen_repo'
    shutil.copytree(REPAIRED/'runtime_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    (frozen/'source_manifest.json').rename(frozen/'previous_runtime_manifest.json')
    shutil.copytree(ADAPTERS, frozen/'eval/external_methods', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    relative = 'external_sources/Video-RSI/solver_full_workspace/engine/services.py'
    services = frozen/relative
    services.write_text(services.read_text().replace('scale=448:-2', 'scale=768:-2'))
    original = json.loads((BASE/'frozen_repo/source_manifest.json').read_text())['files']
    assert sha256(services) == original[relative], 'RSI services must exactly match upstream'
    items = json.loads((REPAIRED/'retry_prepared/items.json').read_text())
    assert len(items) == len({item['sample_id'] for item in items}) == 65
    for item in items:
        assert Path(item['video_path']).is_file()
        write(ROOT/'prepared/items'/(item['sample_id'].replace(':','_')+'.json'), item)
    write(ROOT/'prepared/items.json', items)
    shutil.copy2(REPAIRED/'retry_prepared/private_labels.json', ROOT/'prepared/private_labels.json')
    write(ROOT/'prepared/selection.json', dict(sample_ids=[item['sample_id'] for item in items],
        reused_from=str(REPAIRED/'retry_prepared'), policy='Identical 65 questions and verified media; native method image settings'))
    dependencies = Path(SUPPORT)/'upstream_clients_20261015'
    write(ROOT/'client_environments.json', {method:json.loads((dependencies/(method+'_manifest.json')).read_text())
                                          for method in ('rsi','vam')})
    write(frozen/'source_manifest.json', dict(parent=str(REPAIRED/'runtime_repo'),
        reason='Native method images; keep concatenation and generic answers; local RSI HTTP600',
        files={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}))
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    subprocess.run([sys.executable,'-m','compileall','-q',str(frozen/'eval/external_methods')],env=env,check=True)
    check = """import sys,base64,io
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from native_server import configure
assert configure().ENGINE_CONFIG['limit_mm_per_prompt']=={'image':512,'video':8}
sys.path.insert(0,sys.argv[2])
from vam.config import Settings
assert Settings(_env_file=None).llm_max_image_pixels==1280*1280
from vam.vision.image_limits import ensure_image_limit
from PIL import Image
buffer=io.BytesIO();Image.new('RGB',(2048,1536)).save(buffer,format='JPEG')
uri='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()
image=Image.open(io.BytesIO(base64.b64decode(ensure_image_limit(uri).split(',',1)[1])))
assert 448*448 < image.width*image.height <= 1280*1280
print('Native image defaults and service profile checked')
"""
    subprocess.run([sys.executable,'-c',check,str(frozen/'eval/external_methods'),
                    str(frozen/'external_sources/Visual-Agentic-Memory')],env=env,check=True)
    write(ROOT/'ready.json', dict(rsi_image_width=768, vam_image_pixels=1280*1280,
        embedding_image_pixels=1800*32*32, rsi_http_timeout_seconds=600,
        source_manifest_sha256=sha256(frozen/'source_manifest.json'), samples=65))
    write(REPAIRED/'superseded.json', dict(at=datetime.now(timezone.utc).isoformat(),
        reason='User requested native image settings; 448 run superseded', replacement=str(ROOT)))
    print('Prepared native-image 65+3 matrix',flush=True)


def summarize():
    labels = json.loads((ROOT/'prepared/private_labels.json').read_text())
    analysis = json.loads((ROOT/'analysis.json').read_text())
    report = dict(at=datetime.now(timezone.utc).isoformat(), protocol=json.loads((ROOT/'ready.json').read_text()),
                  methods={}, phase_timing=json.loads((ROOT/'progress.json').read_text()))
    markdown = ['# Native-image RSI / VAM evaluation', '',
        'Development panel; official scoring. Runtime failures are separate from incorrect answers.', '',
        '| Method | Benchmark | Scored / attempted | Official score | Successful mean / median seconds | Failed |',
        '|---|---|---:|---:|---:|---:|']
    for method in ('rsi','vam'):
        progress = json.loads((ROOT/method/'progress.json').read_text())
        score = json.loads((ROOT/method/'scores.json').read_text())
        assert progress['completed'] == progress['expected'] and not score['pending_judge']
        assert len(score['rows'])+len(score['failed']) == progress['expected']
        datasets = {}
        for dataset in ('crossvid','cvbench','mvu_eval'):
            rows = [r for r in progress['samples'] if labels[r['sample_id']]['dataset']==dataset]
            scored = [r for r in score['rows'] if labels[r['sample_id']]['dataset']==dataset]
            successful = [r['seconds'] for r in rows if r['success']]
            value = (score.get('aggregate') or {}).get('bucket_scores',{}).get('dataset:'+dataset)
            datasets[dataset] = dict(attempted=len(rows),scored=len(scored),official_score=value,
                covered_tasks=sorted({labels[r['sample_id']]['task'] for r in scored}),
                successful_mean_seconds=statistics.mean(successful) if successful else None,
                successful_median_seconds=statistics.median(successful) if successful else None,
                all_attempt_seconds=sum(r['seconds'] for r in rows),
                failed=[r for r in rows if not r['success']])
            d = datasets[dataset]
            points = f'{value*100:.2f}%' if value is not None else 'n/a'
            timing = (f'{d["successful_mean_seconds"]:.2f} / {d["successful_median_seconds"]:.2f}'
                      if successful else 'n/a')
            markdown.append(f'| {method} | {dataset} | {len(scored)} / {len(rows)} | {points} | {timing} | {len(d["failed"])} |')
        report['methods'][method] = dict(datasets=datasets, batch_seconds=progress['batch_seconds'],
            predictions=score['rows'], failures=score['failed'],
            request_errors=sum(row['request_errors'] for row in analysis['methods'][method]['samples']))
    markdown += ['', 'Timing excludes model startup and scoring; batch wall time and every failed attempt are saved separately.',
                 'CrossVid uses task macro; CVBench/MVU use official population weighting on this panel.',
                 'VAM has only one question per benchmark, so its scores are smoke results.']
    write(ROOT/'final_summary.json', report)
    (ROOT/'report.md').write_text('\n'.join(markdown)+'\n')
    print(json.dumps({method:{dataset:{k:v for k,v in d.items() if k!='failed'}
                            for dataset,d in value['datasets'].items()} for method,value in report['methods'].items()},indent=2),flush=True)


def infer():
    frozen = ROOT/'frozen_repo'
    sys.path.insert(0,str(frozen/'eval/external_methods/experiments/20261014'))
    from current_smoke import infer as run_methods, score
    try:
        run_methods(ROOT)
        for path in (ROOT/'vam').glob('*/effective_config.json'):
            effective = json.loads(path.read_text())
            assert effective['settings']['llm_max_image_pixels'] == 1280*1280
            assert effective['agent_entrypoint'].startswith('vam.agent.stream_agent_response')
        assert json.loads((ROOT/'embedding/manifest.json').read_text())['max_pixels'] == 1800*32*32
        score(ROOT)
        summarize()
    except BaseException as exc:
        state = json.loads((ROOT/'progress.json').read_text())
        state.update(phase='failed',error=repr(exc))
        write(ROOT/'progress.json',state)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','infer','summarize'])
    globals()[parser.parse_args().phase]()
