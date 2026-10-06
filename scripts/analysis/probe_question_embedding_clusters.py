"""Input-only embedding diagnostic; benchmark categories are evaluation labels only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import random
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

from models.embeddings import EmbeddingConfig, embed
from models.execution import execution_scope
from mvagent.utils.media import probe_video_info
from skill_evolution.infra.benchmarks.catalog import load_multibench_records

REPO = Path(__file__).resolve().parents[2]
DATA = Path('/home/kww/datasets/Multi-Video')
THRESHOLDS = (.60, .65, .70, .75, .80, .85, .90, .95)


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_input(question, options, videos, with_metadata):
    # Native CrossVid choice questions already include the options and a protocol wrapper.
    if '\nQuestion:\n' in question:
        question = question.split('\nQuestion:\n', 1)[1]
    elif question.startswith('Question:\n'):
        question = question[len('Question:\n'):]
    question = question.split('\n\nOptions:\n', 1)[0].split('\n\nYour answer:', 1)[0].strip()
    parts = ['Question:\n' + question]
    if options:
        parts.append('Options:\n' + '\n'.join(options))
    if with_metadata:
        parts.append('Videos:\n' + '\n'.join(
            f"{v['video_id']}: {v['duration_sec']} seconds" for v in videos))
    return '\n\n'.join(parts)


def cluster_metrics(truth, labels):
    _, truth = np.unique(truth, return_inverse=True)
    _, labels = np.unique(labels, return_inverse=True)
    table = np.zeros((max(labels) + 1, max(truth) + 1), dtype=np.int64)
    np.add.at(table, (labels, truth), 1)
    sizes, classes = table.sum(axis=1), table.sum(axis=0)
    pairs = lambda x: float(np.sum(x * (x - 1) / 2))
    tp, predicted, actual = pairs(table), pairs(sizes), pairs(classes)
    total = len(labels) * (len(labels) - 1) / 2
    expected = predicted * actual / total
    denominator = (predicted + actual) / 2 - expected
    non_singletons = sizes > 1
    return dict(clusters=len(sizes), singleton_clusters=int(np.sum(sizes == 1)),
        largest_cluster=int(sizes.max()), multi_member_coverage=float(sizes[non_singletons].sum()/len(labels)),
        purity=float(table.max(axis=1).sum()/len(labels)),
        multi_member_purity=(float(table[non_singletons].max(axis=1).sum()/sizes[non_singletons].sum())
                             if non_singletons.any() else None),
        pair_precision=tp/predicted if predicted else None, pair_recall=tp/actual if actual else None,
        pair_f1=2*tp/(predicted+actual) if predicted+actual else None,
        adjusted_rand=(tp-expected)/denominator if denominator else 1.0)


def neighbors(similarity, rows, exclude_shared):
    scores, examples, per_class = [], [], defaultdict(list)
    for i, row in enumerate(rows):
        order = np.argsort(-similarity[i], kind='stable')
        eligible = []
        source_keys = set(row['source_keys'])
        for j in order:
            if j == i or (exclude_shared and source_keys.intersection(rows[j]['source_keys'])):
                continue
            eligible.append(int(j))
            if len(eligible) == 8:
                break
        if not eligible:
            continue
        score = np.mean([rows[j]['category'] == row['category'] for j in eligible])
        scores.append(float(score)); per_class[row['category']].append(float(score))
        if len(examples) < 30 and rows[eligible[0]]['category'] != row['category']:
            examples.append(dict(sample_id=row['sample_id'], neighbor=rows[eligible[0]]['sample_id'],
                category=row['category'], neighbor_category=rows[eligible[0]]['category'],
                similarity=float(similarity[i, eligible[0]])))
    counts = Counter(r['category'] for r in rows)
    n = len(rows)
    return dict(top8_same_category=float(np.mean(scores)),
        class_macro_top8=float(np.mean([np.mean(v) for v in per_class.values()])),
        uniform_random_baseline=sum(c*(c-1) for c in counts.values())/(n*(n-1)),
        per_category={k: float(np.mean(v)) for k,v in sorted(per_class.items())},
        examples=examples, evaluated_queries=len(scores))


def prepare(root):
    sources = [DATA/'CrossVid/qa.jsonl', DATA/'CVBench/QAs.json', DATA/'MVU-Eval/QAs.json',
        REPO/'eval/crossvid_2500.json',
        REPO/'eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json',
        REPO/'outputs/analysis/20260919_crossvid_lite2500/media_metadata.json',
        REPO/'outputs/analysis/20260919_crossvid_lite2500/all_features.json']
    ids = read(sources[3])
    ids += ['cvbench:' + str(r['id']) for r in read(sources[1])]
    ids += ['mvu_eval:' + r['task'] + ':' + str(r['id']) for r in read(sources[2])]
    records = load_multibench_records(DATA, ids)
    cv_categories = {'cvbench:'+str(r['id']): r['task_type'] for r in read(sources[4])}
    buckets = defaultdict(list)
    for sid, record in sorted(records.items()):
        category = cv_categories[sid] if record.dataset == 'cvbench' else record.native_task
        buckets[(record.dataset, category)].append(sid)
    rng = random.Random(20261001)
    selected = [sid for _, members in sorted(buckets.items())
                for sid in rng.sample(members, min(20, len(members)))]
    records = {sid: records[sid] for sid in sorted(selected)}
    cached = read(sources[5])['files']
    features = {r['sample_id']: r for r in read(sources[6])}
    paths = sorted({p for r in records.values() for p in r.sample.videos.values()})
    def duration(path):
        stat = Path(path).stat()
        old = cached.get(path)
        if old and old['stat'] == [stat.st_size, stat.st_mtime_ns]:
            return path, old['metadata']['duration_sec']
        return path, probe_video_info(path)['duration_sec']
    with ThreadPoolExecutor(max_workers=4) as pool:
        durations = dict(pool.map(duration, paths))
    rows = []
    for sid in sorted(records):
        record = records[sid]
        videos = [dict(video_id=k, duration_sec=durations[p]) for k,p in record.sample.videos.items()]
        assert all(math.isfinite(v['duration_sec']) and v['duration_sec'] > 0 for v in videos)
        category = cv_categories[sid] if record.dataset == 'cvbench' else record.native_task
        rows.append(dict(sample_id=sid, dataset=record.dataset, category=record.dataset+'/'+category,
            question=record.sample.question, options=record.sample.options, videos=videos,
            source_keys=features[sid]['source_keys'] if sid in features else
                ['path:'+p for p in record.sample.videos.values()]))
    save(root/'inputs.json', rows)
    save(root/'protocol.json', dict(n=len(rows), category_counts=dict(Counter(r['category'] for r in rows)),
        sources={str(p):sha(p) for p in sources}, input_sha256=sha(root/'inputs.json'),
        code_sha256=sha(__file__), git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        variants=['question_options', 'question_options_metadata'], thresholds=THRESHOLDS,
        method='cosine complete-link; no category/task/GT/media path in embeddings; no LLM calls',
        sampling=dict(seed=20261001, max_per_category=20, method='uniform within category, no correctness selection'),
        scope='category-balanced development diagnostic; not population-weighted, independent Test or Skill effectiveness validation',
        shared_source_limit='Known CrossVid source keys; exact media paths for CVBench/MVU. Whole-film isolation unknown.'))
    shutil.copy2(__file__, root/'source.py')
    shutil.copytree(REPO/'src', root/'src',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    save(root/'source_manifest.json', {str(p.relative_to(root/'src')):sha(p)
         for p in (root/'src').rglob('*') if p.is_file()})
    print('Prepared', len(rows), 'questions;', len(paths), 'unique media', flush=True)
    return rows


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    rows = read(root/'inputs.json') if (root/'inputs.json').exists() else prepare(root)
    protocol = read(root/'protocol.json')
    if sha(root/'inputs.json') != protocol['input_sha256'] or sha(__file__) != protocol['code_sha256']:
        raise ValueError('Frozen diagnostic inputs/code changed; use a new output root')
    config = EmbeddingConfig('http://127.0.0.1:8110/v1', 'qwen3_embedding_8b', timeout_sec=120)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(config.endpoint+'/models', timeout=10) as response:
        identity = json.load(response)
    if not any(m['id']==config.model and m.get('root')=='/home/kww/models/Qwen3-Embedding/Qwen3-Embedding-8B'
               for m in identity['data']):
        raise ValueError('Embedding service identity mismatch')
    save(root/'service_identity.json', identity)
    save(root/'embedding_config.json', config.to_dict())
    results = {}
    for variant in protocol['variants']:
        started = time.monotonic()
        folder = root/variant; folder.mkdir(exist_ok=True)
        texts = [render_input(r['question'], r['options'], r['videos'], variant.endswith('_metadata')) for r in rows]
        save(folder/'embedding_inputs.json', texts)
        batches = []
        for start in range(0,len(rows),32):
            batch_path = folder/f'batch_{start:05d}.npy'
            if not batch_path.exists():
                with (root/'embedding_events.jsonl').open('a') as events:
                    with execution_scope(emit=lambda event: events.write(json.dumps(event)+'\n')):
                        vectors = embed(config, tuple(texts[start:start+32]))
                np.save(batch_path, vectors)
            batches.append(np.load(batch_path))
            save(root/'status.json', dict(status='embedding', variant=variant, completed=min(start+32,len(rows)),total=len(rows)))
            if start % 320 == 0:
                print(variant, min(start+32,len(rows)), '/',len(rows),flush=True)
        vectors = np.vstack(batches)
        assert vectors.shape[0] == len(rows) and np.allclose(np.linalg.norm(vectors,axis=1),1)
        results[variant] = {}
        for dataset in ['crossvid','cvbench','mvu_eval','pooled']:
            indices = [i for i,r in enumerate(rows) if dataset=='pooled' or r['dataset']==dataset]
            subset = [rows[i] for i in indices]
            similarities = np.clip(vectors[indices] @ vectors[indices].T, -1, 1)
            distances = 1-similarities; np.fill_diagonal(distances,0)
            tree = linkage(squareform(distances,checks=False),method='complete')
            metrics = dict(n=len(indices), categories=len(set(r['category'] for r in subset)),
                neighbors=neighbors(similarities,subset,False),
                source_disjoint_neighbors=neighbors(similarities,subset,True), thresholds={})
            assignments = {}
            for threshold in THRESHOLDS:
                labels = fcluster(tree,1-threshold,criterion='distance')
                metrics['thresholds'][str(threshold)] = cluster_metrics([r['category'] for r in subset],labels)
                assignments[str(threshold)] = {r['sample_id']:int(label) for r,label in zip(subset,labels)}
            save(folder/f'{dataset}_assignments.json',assignments)
            results[variant][dataset] = metrics
            save(root/'metrics.json',results)
        print(variant, 'completed in', round(time.monotonic()-started,1),'seconds',flush=True)
    save(root/'status.json',dict(status='completed',questions=len(rows),variants=protocol['variants']))


def self_check():
    videos = [dict(video_id='video_1',duration_sec=12.5)]
    text = render_input('wrapper\nQuestion:\nWhich?\n\nOptions:\nA. One\n\nYour answer:', ['A. One'], videos, True)
    assert text.count('A. One') == 1 and 'wrapper' not in text and '12.5 seconds' in text
    assert 'Videos:' not in render_input('Which?', [], videos, False)
    good = cluster_metrics(['a','a','b','b'],[1,1,2,2])
    assert good['adjusted_rand']==good['pair_precision']==good['pair_recall']==1
    singleton = cluster_metrics(['a','a','b','b'],[1,2,3,4])
    assert singleton['purity']==1 and singleton['pair_precision'] is None and singleton['pair_recall']==0
    assert cluster_metrics(['a','a','b','b'],[1,1,1,1])['adjusted_rand']==0
    print('self-check passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--self-check',action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error('--output or --self-check required')
