"""Judge the 30 open questions for all comparison arms with one shared cache."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

from run import ROOT, SIZE, SLUG, SHARDS, read, write, now, sha

SOURCE = Path('/runs/devbox/mvagent_full_20261014_transport/frozen_repo')
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'
ARMS = {'restored': ROOT/SIZE, **{k: ROOT/f'{k}_reference' for k in
        ['pro_agent', 'independent', 'e2e']}}


def prepare():
    ids = read(ROOT/'selection.json')['ccqa_ids']
    pro_directory = 'qwen3_5_27b_mvagent' if SIZE=='27B' else f'qwen3_5_{SLUG}'
    pro_path = Path('/runs/lightsail_outputs/mvagent/no_skill')/pro_directory/'score_ccqa_scores_official_deepseek_v4_flash.json'
    old_path = Path('/runs/devbox/mvagent_final_score_20261016/comparison')/f'{SIZE}.json'
    pro = {f"crossvid:CCQA:{r['id']}": r['prediction'] for r in read(pro_path)['samples']}
    old = {r['sample_id']: r for r in read(old_path)['rows']}
    cache = ROOT/'ccqa_judge_cache'; cache.mkdir(exist_ok=True)
    for arm, directory in ARMS.items():
        directory.mkdir(exist_ok=True)
        link = directory/'ccqa_judge_cache'
        if not link.exists(): link.symlink_to(cache, target_is_directory=True)
        assert link.resolve() == cache.resolve()
        for sid in ids:
            if arm == 'restored': continue
            prediction = (pro[sid] if arm=='pro_agent' else
                          old[sid]['prediction' if arm=='independent' else 'e2e_prediction'])
            record = dict(status='ok', sample_id=sid, prediction=prediction)
            path = directory/'records/crossvid'/sid/'result.json'
            if path.exists(): assert read(path)==record
            else: write(path, record)
    write(ROOT/'ccqa_reference_manifest.json', dict(
        at=now(), ids=ids, source_hashes={str(p):sha(p) for p in [pro_path,old_path]},
        policy='Use predictions only; rejudge all four arms with the same frozen official protocol and shared cache.'))


def judge():
    for shard in range(SHARDS):
        assert read(ROOT/f'shard{shard}/progress.json')['phase']=='completed'
    for sid in read(ROOT/'selection.json')['ccqa_ids']:
        assert read(ROOT/SIZE/'records/crossvid'/sid/'result.json')['status']=='ok'
    files = [SOURCE/'eval/agent_eval'/name for name in ['serve_ccqa_judge.sh','score_crossvid_ccqa.py']]
    write(ROOT/'judge_manifest.json', dict(at=now(), source_hashes={str(p):sha(p) for p in files},
        controller_sha256=sha(__file__),
        versions={k:importlib.metadata.version(k) for k in ['vllm','torch','transformers','openai']},
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid','--format=csv,noheader'],text=True)))
    with (ROOT/'judge_startup.log').open('a') as log:
        subprocess.run(['bash',str(files[0]),'0-7','8100'],check=True,stdout=log,stderr=subprocess.STDOUT,
                       env={**os.environ,'JUDGE_LOG_DIR':str(ROOT/'judge_servers')})
    for arm, directory in ARMS.items():
        write(ROOT/'judge_progress.json',dict(phase='judging',arm=arm,at=now()))
        subprocess.run([sys.executable,str(files[1]),'--output',str(directory),'--endpoints','8100-8107'],check=True)
        result=read(directory/REPORT)
        assert result['scored_answer_count']==30 and not result['failed_ids'],result
    write(ROOT/'judge_progress.json',dict(phase='completed',at=now()))


def report():
    summaries={}; paired={sid:{} for sid in read(ROOT/'selection.json')['ccqa_ids']}
    for arm,directory in ARMS.items():
        result=read(directory/REPORT)
        assert result['scored_answer_count']==30 and not result['failed_ids']
        summaries[arm]={k:result[k] for k in ['official_score','sum_score','all_score','scored_answer_count','judge']}
        for row in result['samples']:
            paired[f"crossvid:CCQA:{row['id']}"][arm]=row
    assert all(set(row)==set(ARMS) for row in paired.values())
    closed=read(ROOT/'analysis/closed_summary.json')['benchmarks']['crossvid']['arms']
    combined={arm:(9*closed['e2e_after' if arm=='e2e' else arm]['score']+s['official_score'])/10
              for arm,s in summaries.items()}
    write(ROOT/'analysis/ccqa_summary.json',dict(arms=summaries,crossvid_ten_task_estimate=combined))
    write(ROOT/'analysis/ccqa_paired.json',paired)
    print(summaries,combined,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','judge','report'])
    args=parser.parse_args()
    {'prepare':prepare,'judge':judge,'report':report}[args.mode]()
