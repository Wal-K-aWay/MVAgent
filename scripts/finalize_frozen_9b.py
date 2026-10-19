"""Finish the frozen 9B Judge and export AgentCVR-shaped result files on Modal."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from run_full_e2e import now, read, write, sha

SOURCE = Path(__file__).resolve().parents[1]
RUN = Path('/runs/devbox/frozen_full_final_20261019')
OUT = Path('/runs/devbox/frozen_9b_results_20261019')
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'


def judge():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT/'judge_complete.json').exists(), 'Judge already completed'
    frozen = OUT/'judge_source'
    frozen.mkdir()
    names = ['eval/agent_eval/serve_ccqa_judge.sh', 'eval/agent_eval/score_crossvid_ccqa.py',
             'scripts/finalize_frozen_9b.py']
    for name in names:
        dest = frozen/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE/name, dest)
    manifest = read(RUN/'manifest.json')
    score_source = 'eval/agent_eval/score_crossvid_ccqa.py'
    assert sha(SOURCE/score_source) == manifest['actor_hashes'][score_source]
    write(OUT/'judge_manifest.json', dict(at=now(), root=str(RUN), model='Qwen3-30B-A3B-Instruct-2507',
        source_hashes={name:sha(frozen/name) for name in names},
        hardware=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True),
        policy='Keep the prior 50 judgments. Score only the 189 newly completed CCQA answers; cache in the canonical shard dirs so later controllers reuse them.'))
    os.environ['JUDGE_LOG_DIR'] = str(OUT/'judge_servers')
    try:
        write(OUT/'progress.json', dict(phase='judge_loading', at=now()))
        subprocess.run(['bash', frozen/'eval/agent_eval/serve_ccqa_judge.sh', '0-3', '8400'], check=True)
        counts = []
        selection = read(RUN/'selection.json')
        for i, ids in enumerate(selection['partitions']):
            target = RUN/f'shard{i}/9B'
            expected = {int(s.rsplit(':',1)[1]) for s in ids if s.startswith('crossvid:CCQA:')}
            write(OUT/'progress.json', dict(phase='judging', shard=i, expected=len(expected), at=now()))
            subprocess.run([sys.executable, frozen/score_source, '--output', target, '--endpoints', '8400-8403'], check=True)
            result = read(target/REPORT)
            assert not result['failed_ids'] and {r['id'] for r in result['samples']}==expected
            assert all(r['status']=='ok' for r in result['samples'])
            write(OUT/f'judge/shard{i}.json',result)
            counts.append(len(expected))
        assert sum(counts)==189
        write(OUT/'judge_complete.json',dict(at=now(), new_judged=189, prior_judged=50, shards=counts))
        write(OUT/'progress.json',dict(phase='judge_completed',at=now(),new_judged=189))
    except BaseException:
        write(OUT/'progress.json',dict(phase='failed',at=now(),error=traceback.format_exc()))
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['judge'])
    globals()[parser.parse_args().mode]()
