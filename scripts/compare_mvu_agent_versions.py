"""Compare existing 35B MVAgent versions with RSI on the previously reported MVU IDs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path('/runs/devbox')
OUT = ROOT/'rsi_mvu_agent_versions_20261017'
SOURCE = ROOT/'direct_answer_large_20261016/frozen_repo'
sys.path.insert(0, str(SOURCE/'src'))
from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer


def main():
    assert not OUT.exists(), 'Keep previous analyses unchanged'
    hashes = {}
    def read(path):
        data = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    paired = read(ROOT/'external_baselines_paired_20261017/paired.json')['four_way']
    matched = {r['sample_id']:r for r in paired if r['dataset'] == 'mvu_eval'}
    assert len(matched) == 131
    direct = {r['sample_id']:r for r in read(ROOT/'direct_answer_large_recovery_20261017/analysis/35B-A3B_paired.json')}
    records = load_multibench_records('/assets', sorted(matched))
    scorer, identity = build_official_scorer(records, {})
    old_path = Path('/runs/lightsail_outputs/mvagent/no_skill/qwen3_5_35b_a3b/answers.jsonl.gz')
    old_data = old_path.read_bytes()
    hashes[str(old_path)] = hashlib.sha256(old_data).hexdigest()
    old = {r['sample_id']:r for line in gzip.decompress(old_data).decode().splitlines() if (r:=json.loads(line))['sample_id'] in matched}
    assert set(old) == set(matched)
    rows = []
    for sid, baseline in matched.items():
        saved = direct[sid]
        assert saved['arms']['direct']['score'] == baseline['scores']['mvagent']
        assert saved['arms']['independent']['score'] is not None
        predictions = dict(direct=saved['arms']['direct']['prediction'],
            independent=saved['arms']['independent']['prediction'], pro6000=old[sid]['prediction'])
        scores = {arm:scorer.score_prediction(sid, text).score for arm,text in predictions.items()}
        assert scores['direct'] == baseline['scores']['mvagent']
        assert scores['independent'] == saved['arms']['independent']['score']
        scores['video_rsi'] = baseline['scores']['video_rsi']
        rows.append(dict(sample_id=sid, task=saved['task'], predictions=predictions, scores=scores))
    assert sum(r['scores']['direct'] for r in rows) == 67
    assert sum(r['scores']['video_rsi'] for r in rows) == 76

    restored_root = ROOT/'pro9_ffmpeg_35b_20261016'
    jobs = read(restored_root/'jobs.json')
    available = {r['sample_id'] for r in jobs} & set(matched)
    def load(sid):
        path = restored_root/'35B-A3B/records/mvu_eval'/sid/'result.json'
        data = path.read_bytes()
        return sid, path, hashlib.sha256(data).hexdigest(), json.loads(data)
    restored = []
    with ThreadPoolExecutor(max_workers=8) as readers:
        for sid,path,digest,saved in readers.map(load, sorted(available)):
            hashes[str(path)] = digest
            assert saved['status'] == 'ok'
            base = next(r for r in rows if r['sample_id'] == sid)
            scores = dict(base['scores'], restored=scorer.score_prediction(sid,saved['prediction']).score)
            restored.append(dict(sample_id=sid, scores=scores, prediction=saved['prediction']))

    def aggregate(group):
        assert group
        return {arm:dict(correct=sum(r['scores'][arm] for r in group), n=len(group),
                         accuracy=mean(r['scores'][arm] for r in group)) for arm in group[0]['scores']}
    def contrasts(group):
        return {arm:dict(wins=sum(r['scores'][arm] > r['scores']['video_rsi'] for r in group),
                         losses=sum(r['scores'][arm] < r['scores']['video_rsi'] for r in group))
                for arm in group[0]['scores'] if arm != 'video_rsi'}
    result = dict(at=datetime.now(timezone.utc).isoformat(), model='Qwen3.5-35B-A3B', scorer=identity,
        original_131=aggregate(rows), original_131_contrasts=contrasts(rows),
        restored_overlap=aggregate(restored), restored_contrasts=contrasts(restored),
        source_sha256=hashes, limitations='Same final-answer scorer, but historical hardware and prompts differ; '
            'restored version covers only its own overlap. No new Actor/Judge calls.')
    OUT.mkdir()
    (OUT/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (OUT/'paired.json').write_text(json.dumps(dict(original_131=rows, restored_overlap=restored), ensure_ascii=False))
    (OUT/'analysis_source.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({k:v for k,v in result.items() if k != 'source_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
