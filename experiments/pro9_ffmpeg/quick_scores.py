"""Score exact saved answers first, without rereading every token log."""
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from pathlib import Path
import statistics
import sys

sys.path.insert(0, '/runs/devbox/pro9_ffmpeg_20261016/code/experiments/pro9_ffmpeg')
import evaluate as evaluation
from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
from expand_direct_answer import interval


def main():
    result = {}
    for model, name in [('27B','pro9_ffmpeg_27b_20261016'), ('35B-A3B','pro9_ffmpeg_35b_20261016')]:
        root = Path('/runs/devbox') / name
        jobs = evaluation.core.read(root/'jobs.json')
        ids = evaluation.core.read(root/'selection.json')['closed_ids']
        records = load_multibench_records('/assets', ids)
        scorer, _ = build_official_scorer(records,{})
        history = {r['sample_id']:r for r in evaluation.core.read(
            Path('/runs/devbox/pro6000_protocol_effects_20261016')/f'{model}_paired.json')}
        paths = [root/'shard0'/f'rank{i}.log' for i in range(8)]
        answers = {}
        with ThreadPoolExecutor(8) as pool:
            for text in pool.map(Path.read_text, paths):
                for line in text.splitlines():
                    if line.startswith('{"sample_id":'):
                        row = json.loads(line)
                        assert row['sample_id'] not in answers
                        answers[row['sample_id']] = row
        assert set(answers) == {j['sample_id'] for j in jobs} and len(answers)==330
        rows=[]
        for sid in ids:
            saved=answers[sid]
            if saved['status']!='ok':continue
            prediction=saved['prediction']
            if len(prediction)==200:
                prediction=evaluation.core.read(root/model/'records'/sid.split(':')[0]/sid/'result.json')['prediction']
            row=history[sid]
            row['arms']['restored']=evaluation.core.measure(prediction,records[sid],scorer)
            rows.append(row)
        scores={}
        for dataset in ['cvbench','mvu_eval','crossvid']:
            group=[r for r in rows if r['dataset']==dataset]
            scores[dataset]=dict(n=len(group),arms={arm:dict(score=evaluation.mean_score(group,arm),
                format_errors=sum(not r['arms'][arm]['format_ok'] for r in group))
                for arm in ['pro_agent','independent','direct','restored','e2e_after']})
            scores[dataset]['direct_delta_ci']=interval([dict(dataset=r['dataset'],task=r['task'],
                task_population=r['task_population'],old=r['arms']['direct'],new=r['arms']['restored']) for r in group])
        with ThreadPoolExecutor(8) as pool:
            saved=list(pool.map(evaluation.core.read,[root/model/'records'/j['dataset']/j['sample_id']/'result.json' for j in jobs]))
        valid=[r for r in saved if r['status']=='ok']
        assert len(valid)==len(rows)+sum(j['task']=='CCQA' and answers[j['sample_id']]['status']=='ok' for j in jobs)
        hashes={str(p.relative_to(root/'code/src')):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root/'code/src').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        assert hashes==evaluation.core.read(root/'code/experiments/pro9_ffmpeg/source_provenance.json')['experiment_sha256']
        assert all(r['prediction'][:200]==answers[r['sample_id']]['prediction'] for r in valid)
        expected={j['sample_id']:j['inputs'] for j in jobs}
        assert all(r['result']['input']==expected[r['sample_id']] for r in valid)
        result[model]=dict(benchmarks=scores, errors=[r for r in answers.values() if r['status']!='ok'],
            valid=len(valid),empty=sum(not r['prediction'].strip() for r in valid),
            brace_only=sum(r['prediction'].strip()=='}' for r in valid),
            forced=sum(r['result']['answer']['status']=='forced_with_gaps' for r in valid),
            mean_seconds=statistics.mean(r['seconds'] for r in valid),
            median_seconds=statistics.median(r['seconds'] for r in valid),
            longest=[{k:r[k] for k in ['sample_id','seconds','prediction']}|{'calls':len(r['call_files'])}
                     for r in sorted(valid,key=lambda r:r['seconds'],reverse=True)[:3]],source_hashes_verified=len(hashes))
        if model=='35B-A3B':
            report='score/ccqa_scores_official_qwen3_30b_a3b.json'
            opened={arm:evaluation.core.read(root/directory/report) for arm,directory in
                    [('restored',model),('pro_agent','pro_agent_reference'),('independent','independent_reference'),('e2e','e2e_reference')]}
            assert all(r['scored_answer_count']==30 and not r['failed_ids'] for r in opened.values())
            result[model]['ccqa']={arm:r['official_score'] for arm,r in opened.items()}
            result[model]['crossvid_ten_task']={arm:(9*scores['crossvid']['arms']['e2e_after' if arm=='e2e' else arm]['score']+r['official_score'])/10 for arm,r in opened.items()}
        target=Path('/runs/devbox/pro9_ffmpeg_large_20261016/analysis')
        target.mkdir(exist_ok=True)
        evaluation.core.write(target/f'quick_{model}.json',result[model])
        compact={**result[model],'longest':[{**r,'prediction':r['prediction'][:350]} for r in result[model]['longest']]}
        print(model,json.dumps(compact,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
