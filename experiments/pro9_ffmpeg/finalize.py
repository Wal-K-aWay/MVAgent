"""Finish read-only result checks and summarize the completed 9B experiment."""
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

from run import ROOT, SIZE, read, write, sha, now
from judge import ARMS, SOURCE, REPORT


def main():
    jobs={r['sample_id']:r for r in read(ROOT/'jobs.json')}
    diagnostics=read(ROOT/'analysis/diagnostics.json')
    assert len(jobs)==len(diagnostics)==330
    assert set(jobs)=={r['sample_id'] for r in diagnostics}
    hashes={}
    for sid,job in jobs.items():
        path=ROOT/SIZE/'records'/job['dataset']/sid/'result.json'
        row=read(path)
        assert row['status']=='ok' and row['result']['input']==job['inputs']
        hashes[sid]=sha(path)
    write(ROOT/'analysis/record_hashes.json',hashes)

    provenance=read(ROOT/'code/experiments/pro9_ffmpeg/source_provenance.json')
    source=ROOT/'code/src'
    actual={str(p.relative_to(source)):sha(p) for p in source.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts}
    assert actual==provenance['experiment_sha256']
    assert provenance['changed_src_files']==['mvagent/utils/media.py']

    spec=importlib.util.spec_from_file_location('official_ccqa',SOURCE/'eval/agent_eval/score_crossvid_ccqa.py')
    scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
    qa={int(r['id']):r for r in read(Path('/assets/crossvid/QA/CCQA.json'))}
    expected={int(s.rsplit(':',1)[1]) for s in read(ROOT/'selection.json')['ccqa_ids']}
    cache_keys=set();judge_rows=0
    for arm,directory in ARMS.items():
        report=read(directory/REPORT)
        assert report['scored_answer_count']==30 and not report['failed_ids']
        assert {r['id'] for r in report['samples']}==expected
        assert report['judge']['model']==scorer.JUDGE_MODEL
        assert report['judge']['generation']==scorer.GENERATION
        for sample in report['samples']:
            item=qa[sample['id']]
            prompt=scorer.SCORE_PROMPT.format(QUESTION=item['question'],ANSWER=item['answer'],
                                            POINTS=item['scoring_points'],OUTPUT=sample['prediction'])
            key=hashlib.sha256(json.dumps({'model':scorer.JUDGE_MODEL,'prompt':prompt},
                                         ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            cached=read(ROOT/'ccqa_judge_cache'/key[:2]/f'{key}.json')
            assert cached['status']==sample['status']=='ok'
            for field in ['coverage','correctness','score']:assert cached[field]==sample[field],(arm,sample['id'],field)
            parsed=json.loads(scorer._extract(cached['response'],'score'))
            for field in ['coverage','correctness']:assert parsed[field]==cached[field]
            assert all(type(v) is bool for v in cached['coverage']+cached['correctness'])
            assert len(cached['coverage'])==len(cached['correctness'])==len(item['scoring_points'])
            assert cached['score']==sum(cached['coverage'])+sum(cached['correctness'])
            cache_keys.add(key);judge_rows+=1
    assert judge_rows==120

    times=sorted(r['seconds'] for r in diagnostics)
    timing=dict(mean_seconds=statistics.mean(times),median_seconds=statistics.median(times),
                p95_seconds=times[math.ceil(.95*len(times))-1],max_seconds=max(times),sum_seconds=sum(times))
    pairs=read(ROOT/'analysis/paired.json')
    by_id={r['sample_id']:r for r in diagnostics}
    formats=[dict(sample_id=r['sample_id'],prediction=r['arms']['restored']['prediction'],
                  answer_status=by_id[r['sample_id']]['answer_status'],
                  previous_direct=r['arms']['direct']['prediction'])
             for r in pairs if not r['arms']['restored']['format_ok']]
    changes={dataset:{arm:dict(
        improved=sum(r['arms']['restored']['score']>r['arms'][arm]['score'] for r in pairs if r['dataset']==dataset),
        regressed=sum(r['arms']['restored']['score']<r['arms'][arm]['score'] for r in pairs if r['dataset']==dataset))
        for arm in ['pro_agent','independent','direct','e2e_after']}
        for dataset in ['cvbench','mvu_eval','crossvid']}
    longest=[]
    for r in sorted(diagnostics,key=lambda r:r['seconds'],reverse=True)[:6]:
        longest.append(dict(sample_id=r['sample_id'],seconds=r['seconds'],calls=r['calls'],
                            truncations=len(r['truncated_calls']),answer_status=r['answer_status'],
                            prediction=r['prediction'],issues=r['trajectory_issues']))
    summary=dict(at=now(),timing=timing,empty=sum(not r['prediction'].strip() for r in diagnostics),
        brace_only=sum(r['prediction'].strip()=='}' for r in diagnostics),
        forced_answers=sum(r['answer_status']=='forced_with_gaps' for r in diagnostics),
        questions_with_truncation=sum(bool(r['truncated_calls']) for r in diagnostics),
        judge_rows=judge_rows,unique_judge_cache_entries=len(cache_keys),judge_cache_mismatches=0,
        source_files=len(actual),only_source_change=provenance['changed_src_files'],
        format_errors=formats,format_errors_by_answer_status=dict(Counter(r['answer_status'] for r in formats)),
        paired_changes=changes,longest=longest,
        all_source_hashes_verified=True,record_hashes_file='analysis/record_hashes.json')
    write(ROOT/'analysis/final_checks.json',summary)
    write(ROOT/'analysis/finalization_manifest.json',dict(
        at=now(),finalizer_sha256=sha(__file__),evaluator_sha256=sha(ROOT/'code/experiments/pro9_ffmpeg/evaluate.py'),
        selection_sha256=sha(ROOT/'selection.json'),source_provenance_sha256=sha(ROOT/'code/experiments/pro9_ffmpeg/source_provenance.json')))
    write(ROOT/'progress.json',dict(phase='completed',at=now(),actor_questions=330,
                                   judge_rows=judge_rows,audit='passed',report='analysis/final_checks.json'))
    # Full errors stay in the volume; the console carries only compact diagnostics.
    for row in longest:row['issues']=[x[:250] for x in row['issues'][:3]]
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
