"""Read-only timing audit of the three published MVAgent result sets; run on Modal CPU."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import tarfile

OUT = Path('/runs/devbox/mvagent_timing_audit_20261020')
EXPORTS = {
    '9B': Path('/runs/devbox/frozen_9b_results_20261019'),
    '27B': Path('/runs/devbox/frozen_27b_results_20261019'),
    '35B-A3B': Path('/runs/devbox/frozen_35b-a3b_results_20261020'),
}
DATASETS = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}
FINAL = Path('/runs/devbox/frozen_full_35b_finish_20261020')


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def percentile(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo = int(pos)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo)


def summarize(rows):
    n = len(rows)
    times = [r['seconds'] for r in rows]
    sums = {key: math.fsum(r[key] for r in rows) for key in
            ['seconds', 'server_seconds', 'calls', 'output_tokens', 'input_tokens', 'trajectory_entries',
             'media_work_seconds', 'invalid', 'repair', 'truncated']}
    return dict(n=n, mean=statistics.fmean(times), sum_seconds=sums['seconds'],
                median=statistics.median(times), p90=percentile(times, .9), p95=percentile(times, .95),
                minimum=min(times), maximum=max(times),
                means={k: v/n for k, v in sums.items()},
                server_fraction=sums['server_seconds']/sums['seconds'],
                server_inclusive_output_tokens_per_second=sums['output_tokens']/sums['server_seconds'])


def scan(model):
    root = EXPORTS[model]
    manifest = read(root/'manifest.json')
    comparison = read(root/'comparison.json')['benchmarks']
    files = {r['name']: r for r in manifest['files']}
    baseline = {r['sample_id'] for r in read(FINAL/'baseline.json')[model]}
    provenance = {r['id']: r for r in manifest['raw_sources']}
    rows, mismatches = [], Counter()
    requests, gpu, schemas = Counter(), Counter(), defaultdict(Counter)
    examples = {}
    for ds, expected in DATASETS.items():
        digest = hashlib.sha256()
        with (root/'files'/f'{ds}.jsonl').open('rb') as stream:
            for line in stream:
                digest.update(line)
                row = json.loads(line)
                trace = row['trajectory']; result = trace['result']; events = trace['events']
                seconds = row['seconds']
                assert math.isfinite(seconds) and seconds > 0
                mismatches['seconds_vs_engine'] += seconds != result['time']
                calls = [e for e in events if e['kind'] == 'model_response']
                assert calls and all(math.isfinite(e['inference_seconds']) and e['inference_seconds'] >= 0 for e in calls)
                server = math.fsum(e['inference_seconds'] for e in calls)
                mismatches['server_sum_exceeds_total'] += server > seconds + .02
                timestamps = [e['time'] for e in events]
                span = max(timestamps) - min(timestamps)
                mismatches['event_span_exceeds_total'] += span > seconds + .05
                mismatches['nonzero_prefix_cache'] += any(e['usage']['prompt_tokens_details']['cached_tokens'] != 0 for e in calls)
                workers = {(e['worker']['pid'], e['worker']['gpu_uuid']) for e in calls}
                mismatches['nonsticky_question'] += len(workers) != 1
                for event in calls:
                    gpu[event['worker']['gpu_name']] += 1
                    bucket = schemas[event.get('schema') or 'unknown']
                    bucket.update(calls=1, seconds=event['inference_seconds'],
                                  input_tokens=event['usage']['prompt_tokens'], output_tokens=event['usage']['completion_tokens'])
                for event in events:
                    if event['kind'] == 'model_request':
                        p = event['payload']
                        params = {k: p.get(k) for k in ['temperature', 'top_p', 'max_tokens', 'seed', 'chat_template_kwargs']}
                        requests[json.dumps(params, sort_keys=True)] += 1
                source = provenance[row['id']]
                source_group = source.get('archive') or str(Path(source['path']).parents[3])
                item = dict(id=row['id'], dataset=ds, seconds=seconds, server_seconds=server,
                    calls=len(calls), output_tokens=sum(e['usage']['completion_tokens'] for e in calls),
                    input_tokens=sum(e['usage']['prompt_tokens'] for e in calls),
                    trajectory_entries=len(result['trajectory']), event_span=span,
                    media_work_seconds=sum(e.get('seconds', 0) for e in events if e['kind']=='media_clip_profile'),
                    invalid=sum(e['kind']=='structured_invalid' for e in events),
                    repair=sum(e['kind']=='structured_repair' for e in events),
                    truncated=sum(e.get('finish_reason')=='length' for e in calls),
                    reused=row['id'] in baseline, attempt=trace.get('attempt'), source_group=source_group)
                rows.append(item)
                if ds not in examples:
                    examples[ds] = dict(id=row['id'], event_keys={k: sorted(next(e for e in events if e['kind']==k))
                        for k in sorted({e['kind'] for e in events})}, result_keys=sorted(result))
        assert digest.hexdigest()==files[f'{ds}.jsonl']['sha256']
        group = [r for r in rows if r['dataset']==ds]
        assert len(group)==expected
        actual = statistics.fmean(r['seconds'] for r in group)
        mismatches['published_mean'] += abs(actual-comparison[ds]['seconds']) > 1e-8
    assert len(rows)==len({r['id'] for r in rows})==5321
    with (OUT/f'{model}_rows.jsonl').open('w') as stream:
        for row in rows: stream.write(json.dumps(row)+'\n')
    report = dict(total=summarize(rows), datasets={ds:summarize([r for r in rows if r['dataset']==ds]) for ds in DATASETS},
        subsets={key:summarize([r for r in rows if r['reused']==flag]) for key,flag in [('reused',True),('new',False)]},
        sources={key:summarize([r for r in rows if r['source_group']==key]) for key in sorted({r['source_group'] for r in rows})},
        checks=dict(mismatches), request_parameters=[dict(parameters=json.loads(k), calls=v) for k,v in requests.items()],
        gpu_names=dict(gpu), schemas=dict(schemas), attempts=dict(Counter(str(r['attempt']) for r in rows)),
        slowest=sorted(rows, key=lambda r:r['seconds'], reverse=True)[:5], examples=examples)
    write(OUT/f'{model}_summary.json', report)
    print('MODEL_COMPLETE', model, report['total'], report['checks'], flush=True)
    return model, report, rows


def settings():
    import yaml
    manifests, source_files, cards = {}, {}, []
    # Actual admitted cards and frozen source hashes, including the reused panel.
    for name in ['frozen_full_20261018','frozen_full_final_20261019','frozen_full_recovery_20261019',
                 'frozen_full_35b_finish_20261020','system_ablation_20261017','global_short_large_20261017']:
        root = Path('/runs/devbox')/name
        m = read(root/'manifest.json')
        manifests[name] = {k:m[k] for k in ['commit','profile','changes'] if k in m}
        manifests[name]['actor_hashes'] = {k:v for k,v in m.get('actor_hashes',{}).items()
            if k in ['src/mvagent/engine.py','src/mvagent/batch.py','src/models/vlm/local/sync_server.py',
                     'src/mvagent/agents/global_agent/prompts.py','src/mvagent/agents/video_agent/prompts.py',
                     'src/mvagent/utils/media.py']}
        baseline = root/'baseline_services.json'
        if baseline.exists():
            for model, group in read(baseline).items():
                for card in group: cards.append(dict(model=model, source=str(baseline), card=card))
        for shard in range(2):
            for model in EXPORTS:
                service = root/f'shard{shard}/services'/model
                identity = service/'startup_identity.json'
                if identity.exists():
                    for card in read(identity): cards.append(dict(model=model, source=str(identity), card=card))
                    manifests[str(service)] = {n:yaml.safe_load((service/n).read_text()) for n in ['config.yaml','execution.yaml']}
        archive = root/'source.tar.gz'
        if archive.exists():
            with tarfile.open(archive) as tar:
                for filename in ['src/mvagent/engine.py','src/mvagent/batch.py']:
                    data = tar.extractfile(filename).read()
                    digest = hashlib.sha256(data).hexdigest()
                    source_files.setdefault(filename,{})[digest]=data.decode()
    write(OUT/'settings.json', dict(manifests=manifests,cards=cards,source_files=source_files))
    profiles = Counter(json.dumps(r['card']['execution'],sort_keys=True) for r in cards)
    return dict(actual_cards=len(cards), profiles=[dict(profile=json.loads(p),count=n) for p,n in profiles.items()],
                frozen_code_variants={name:sorted(items) for name,items in source_files.items()})


def main():
    assert not OUT.exists(), 'Keep previous audit evidence'
    OUT.mkdir()
    (OUT/'source.py').write_bytes(Path(__file__).read_bytes())
    self_check()
    results={}; rows={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for model, report, items in pool.map(scan, EXPORTS): results[model]=report; rows[model]={r['id']:r for r in items}
    assert all(set(x)==set(rows['9B']) for x in rows.values())
    paired={}
    for model in ['27B','35B-A3B']:
        ratios=[rows[model][sid]['seconds']/r['seconds'] for sid,r in rows['9B'].items()]
        paired[model]=dict(median_ratio_to_9b=statistics.median(ratios),
            fraction_faster_than_9b=sum(v<1 for v in ratios)/len(ratios))
    report=dict(at=datetime.now(timezone.utc).isoformat(), models=results, paired=paired, settings=settings())
    write(OUT/'report.json',report)
    print('AUDIT_COMPLETE',json.dumps({m:{ds:r['mean'] for ds,r in x['datasets'].items()} for m,x in results.items()}),flush=True)


def self_check():
    assert percentile([1,2,3,4],.5)==2.5
    # The overall mean weights questions, rather than averaging benchmark means.
    assert statistics.fmean([1,1,10])==4 and (statistics.fmean([1,1])+10)/2==5.5


def refine():
    """Inspect each source cohort's frozen config without rescanning the published trajectories."""
    import yaml
    report=read(OUT/'report.json')
    # Trajectory entries include action results as well as decisions, not just Global steps.
    def labels(value):
        if isinstance(value,dict): return {('trajectory_entries' if k=='global_steps' else k):labels(v) for k,v in value.items()}
        if isinstance(value,list): return [labels(v) for v in value]
        return value
    report=labels(report)
    evidence=[]; configs=defaultdict(list); executions=defaultdict(list); source_hashes=defaultdict(lambda:defaultdict(list))
    for model,summary in report['models'].items():
        for source in summary['sources']:
            path=Path(source)
            if path.suffix!='.tar' and not (path/'input_config.yaml').exists():
                refs=read(EXPORTS[model]/'manifest.json')['raw_sources']
                ref=next(r for r in refs if 'path' in r and str(Path(r['path']).parents[3])==source)
                path=Path(ref['path']).resolve().parents[3]
            archive=tarfile.open(path) if path.suffix=='.tar' else None
            def get(relative):
                if archive is not None:
                    try: return archive.extractfile(model+'/'+relative).read()
                    except KeyError: return None
                f=path/relative
                return f.read_bytes() if f.exists() else None
            try:
                config=get('input_config.yaml')
                item=dict(model=model,source=source,resolved_source=str(path),config_found=config is not None)
                if config is not None:
                    cfg=yaml.safe_load(config)
                    item['config_sha256']=hashlib.sha256(config).hexdigest()
                    name,parameters=next(iter(cfg['models'].items()))
                    cfg['models']={'MODEL':{k:v for k,v in parameters.items() if k!='model_name'}}
                    for key in ['cache_dir','output_dir']:cfg['runtime'].pop(key,None)
                    normalized=json.dumps(cfg,sort_keys=True).replace(name,'MODEL')
                    configs[normalized].append(source)
                for relative in ['src/mvagent/engine.py','src/mvagent/batch.py',
                    'src/mvagent/agents/global_agent/prompts.py','src/mvagent/agents/video_agent/prompts.py']:
                    data=get(relative)
                    if data is not None: source_hashes[relative][hashlib.sha256(data).hexdigest()].append(source)
                if archive is not None:
                    try: stream=archive.extractfile(model+'/execution_events.jsonl')
                    except KeyError: stream=None
                else:
                    f=path/'execution_events.jsonl';stream=f.open('rb') if f.exists() else None
                if stream:
                    with stream:
                        for line in stream:
                            e=json.loads(line)
                            if e['kind']=='batch_prepared':
                                item['question_workers']=e['question_workers']
                                item['max_prepared_requests']=e['max_prepared_requests']
                                item['replicas']=[dict(gpu_count=len(r['gpus']),max_inflight=r['max_inflight']) for p in e['model_pools'].values() for r in p]
                                executions[json.dumps({k:item[k] for k in ['question_workers','max_prepared_requests','replicas']},sort_keys=True)].append(source)
                                break
                evidence.append(item)
            finally:
                if archive is not None:archive.close()
    report['source_cohorts']=dict(evidence=evidence,
        configurations=[dict(config=json.loads(k),sources=v) for k,v in configs.items()],
        actual_batch_settings=[dict(config=json.loads(k),sources=v) for k,v in executions.items()],
        frozen_file_hashes=source_hashes)
    write(OUT/'final_report.json',report)
    (OUT/'final_source.py').write_bytes(Path(__file__).read_bytes())
    print('REFINED_COHORTS',json.dumps(report['source_cohorts']),flush=True)


if __name__=='__main__':
    if sys.argv[1:]==['self-check']: self_check()
    elif sys.argv[1:]==['refine']: refine()
    else: main()
