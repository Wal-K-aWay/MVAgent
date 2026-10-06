"""No-fixed-K clustering and cumulative-batch diagnostic using cached input embeddings.

Launch freezes inputs, source and protocol, then detaches a resumable CPU controller.
No trajectories, optimizer, selector, video inference or Judge calls are made.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import fcntl
import importlib.util
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

import numpy as np
from sklearn.cluster import HDBSCAN, DBSCAN
import sklearn

BASE = Path(__file__).resolve().parents[2]
PARENT = BASE / 'outputs/analysis/20261001_question_grouping_validation'
SEED = 20261001


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def helper(path):
    spec = importlib.util.spec_from_file_location('grouping_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs():
    result = []
    for size, samples, selection in itertools.product([3, 5, 10, 20], [2, 5, 10], ['eom', 'leaf']):
        result.append(dict(method='hdbscan', min_cluster_size=size, min_samples=samples,
                           cluster_selection_method=selection))
    for threshold, samples in itertools.product([.4, .5, .6, .7], [2, 3, 5]):
        result.append(dict(method='dbscan', threshold=threshold, min_samples=samples))
    for threshold in [.35, .4, .45, .5, .55, .6, .65, .7, .75]:
        result.append(dict(method='average', threshold=threshold))
    for k, threshold, resolution in itertools.product([8, 16, 32], [.45, .55, .65], [.5, 1, 2]):
        result.append(dict(method='mutual_knn_louvain', k=k, threshold=threshold, resolution=resolution))
    for k, threshold in itertools.product([8, 16, 32], [.45, .55, .65]):
        result.append(dict(method='neighborhood', k=k, threshold=threshold))
    return result


def cluster(sim, spec, module):
    if len(sim) < 2:
        return [[0]], 0
    if spec['method'] not in ['hdbscan', 'dbscan']:
        return module.groups_for(sim, spec, {}), 0
    # Preserve cosine distance directly; no PCA fitted using future batches.
    distance = np.asarray(np.clip(1 - sim, 0, 2), dtype=np.float64)
    np.fill_diagonal(distance, 0)
    if spec['method'] == 'hdbscan':
        if len(sim) < max(spec['min_cluster_size'], spec['min_samples']):
            return [[i] for i in range(len(sim))], len(sim)
        model = HDBSCAN(metric='precomputed', algorithm='brute',
                        min_cluster_size=spec['min_cluster_size'], min_samples=spec['min_samples'],
                        cluster_selection_method=spec['cluster_selection_method'], n_jobs=1)
    else:
        model = DBSCAN(metric='precomputed', eps=1-spec['threshold'], min_samples=spec['min_samples'], n_jobs=1)
    labels = model.fit_predict(distance)
    groups = [np.flatnonzero(labels == label).tolist() for label in sorted(set(labels)) if label >= 0]
    # Noise points remain independent materials, NEVER one shared noise cluster.
    groups.extend([[int(i)] for i in np.flatnonzero(labels < 0)])
    return groups, int(np.sum(labels < 0))


def coassigned(n, groups):
    together = np.eye(n, dtype=bool)
    for group in groups:
        together[np.ix_(group, group)] = True
    return together


def context(rows, families):
    datasets = np.array([r['dataset'] for r in rows])
    categories = np.array([r['category'] for r in rows])
    labels = np.array([families.get(r['sample_id'], 'UNKNOWN') for r in rows])
    known = labels != 'UNKNOWN'
    lower = np.tril(np.ones((len(rows), len(rows)), dtype=bool), -1)
    return datasets, categories, labels, lower, lower & (datasets[:, None] != datasets[None, :]) & known[:, None] & known[None, :]


def measure(rows, groups, families, module, ctx=None):
    datasets, categories, labels, lower, crossmask = ctx or context(rows, families)
    assigned = coassigned(len(rows), groups)
    native = {d: module.pair_metrics(categories[:, None] == categories[None, :],
             lower & (datasets[:, None] == d) & (datasets[None, :] == d), assigned) for d in sorted(set(datasets))}
    cross = module.pair_metrics(labels[:, None] == labels[None, :], crossmask, assigned)
    macro = float(np.mean([r['f1'] for r in native.values() if r['f1'] is not None]))
    counts = Counter(i for g in groups for i in g)
    return dict(objective=(macro+(cross['f1'] or 0))/2, native_macro_f1=macro, native=native,
                cross=cross, groups=len(groups), largest_group=max(map(len, groups)),
                multi_member_coverage=sum(any(len(g)>1 and i in g for g in groups) for i in range(len(rows)))/len(rows),
                mean_memberships=sum(counts.values())/len(rows)), assigned


def orders(rows, families, seed, scenario):
    rng = random.Random(seed)
    ids = list(range(len(rows)))
    rng.shuffle(ids)
    if scenario == 'category_blocked':
        categories = sorted({r['category'] for r in rows})
        rng.shuffle(categories)
        rank = {c:i for i,c in enumerate(categories)}
        ids.sort(key=lambda i: rank[rows[i]['category']])
    elif scenario == 'late_ordering':
        ids.sort(key=lambda i: families.get(rows[i]['sample_id']) == 'sequence_order')
    return ids


def video_id_duration_text(row):
    q = row['question']
    if row['options'] and '\nOptions:\n' not in q:
        q += '\n\nOptions:\n' + '\n'.join(row['options'])
    videos = '\n'.join(f"{v['video_id']}: duration={v['duration_sec']} seconds" for v in row['videos'])
    instruction = 'Retrieve multi-video questions requiring the same reasoning and evidence acquisition strategy, regardless of subject matter, benchmark or wording.'
    return f'Instruct: {instruction}\nQuery: {q}\n\nVideos:\n{videos}'


def prepare(root, representation):
    if (root/'protocol.json').exists():
        raise ValueError('Output already prepared; resume the frozen controller instead')
    root.mkdir(parents=True, exist_ok=True)
    for name in ['inputs.json', 'references.json', 'partition.json', 'source_partition.json', 'source_audit.json']:
        shutil.copy2(PARENT/name, root/name)
    folder = PARENT/'embeddings/strategy_full_input'
    rows = read(root/'inputs.json')
    if representation == 'video_id_duration':
        from models.embeddings import EmbeddingConfig, embed
        from models.execution import execution_scope
        inputs = [video_id_duration_text(row) for row in rows]
        path = root/'embedding_inputs.json'
        if path.exists() and read(path) != inputs:
            raise ValueError('Prepared embedding input identity changed')
        save(path, inputs)
        config = EmbeddingConfig('http://127.0.0.1:8110/v1', 'qwen3_embedding_8b', 120)
        identity = json.load(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(config.endpoint+'/models', timeout=10))
        save(root/'embedding_service.json', identity)
        assert any(m['id']==config.model and m.get('root')=='/home/kww/models/Qwen3-Embedding/Qwen3-Embedding-8B' for m in identity['data']), 'Embedding service identity mismatch'
        folder = root/'embedding_batches'
        folder.mkdir(exist_ok=True)
        for offset in range(0,len(inputs),32):
            batch = folder/f'batch_{offset:05d}.npy'
            if not batch.exists():
                save(root/'status.json',dict(status='running',phase='embedding',completed=offset,total=len(inputs),pid=os.getpid()))
                with (root/'embedding_events.jsonl').open('a') as events:
                    with execution_scope(emit=lambda e: events.write(json.dumps(e)+'\n')):
                        vector = embed(config,tuple(inputs[offset:offset+32]))
                np.save(batch,vector)
            print(f'Embedding {min(offset+32,len(inputs))}/{len(inputs)}',flush=True)
    else:
        inputs = read(folder/'inputs.json')
    assert len(rows) == len(inputs) == 660
    assert all(r['question'] in text and all(o in text for o in r['options']) for r,text in zip(rows,inputs))
    vectors = np.vstack([np.load(p) for p in sorted(folder.glob('batch_*.npy'))])
    assert vectors.shape == (660,4096) and np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors,axis=1), 1, atol=1e-5)
    np.save(root/'vectors.npy',vectors)
    save(root/'embedding_inputs.json',inputs)
    shutil.copy2(__file__,root/'controller.py')
    shutil.copy2(BASE/'scripts/analysis/test_question_grouping_methods.py',root/'grouping_helpers.py')
    shutil.copytree(BASE/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    snapshot = [root/'controller.py',root/'grouping_helpers.py',root/'vectors.npy',root/'embedding_inputs.json']
    snapshot += list((root/'src').rglob('*.py'))
    snapshot += [root/name for name in ['inputs.json','references.json','partition.json','source_partition.json','source_audit.json']]
    hashes = {str(p.relative_to(root)):sha(p) for p in snapshot}
    save(root/'source_manifest.json',hashes)
    families = {r['sample_id']:r['family'] for r in read(root/'references.json')}
    assert 'sequence_order' in set(families.values()), sorted(set(families.values()))
    protocol = dict(seed=SEED, seeds=[SEED,SEED+1,SEED+2], batch_sizes=[16,32,64],
        scenarios=['random','category_blocked','late_ordering'], specs=specs(), questions=660,
        representation=representation, embedding_model='qwen3_embedding_8b', vector_dimensions=4096,
        packages=dict(numpy=np.__version__,sklearn=sklearn.__version__),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        criterion='Select each method on original 330 dev IDs only, mean native macro pair F1 and cross-family pair F1.',
        limitations='Existing exploratory 179-family annotations; original ID split shares sources. Source split is stress only. No independent Test, no real trajectory pool or Skill efficacy/QA validation.',
        execution='Input-only sequential-arrival simulation. Canonically sorted accumulated sample IDs before every refit. All previous materials retained; batch-local baseline freezes within-batch groups only.',
        evaluation_labels='Native category/family used only for scoring and adversarial order generation, never clustering.',
        source=str(PARENT), source_manifest_hash=sha(root/'source_manifest.json'),
        comparison_root=str(BASE/'outputs/analysis/20261001_no_k_cross_batch') if representation=='video_id_duration' else None,
        embedding_input_contract='Complete question and options, fixed strategy instruction, ordered video_id-duration pairs; no derived statistics.' if representation=='video_id_duration' else 'Complete question and options, fixed strategy instruction, derived video/option summary.',
        scope=dict(model_calls=21 if representation=='video_id_duration' else 0,qa_rollouts=0,optimizer_calls=0,production_changed=False))
    save(root/'protocol.json',protocol)
    save(root/'status.json',dict(status='prepared',pid=None))


def run(root):
    start = time.monotonic()
    manifest = read(root/'source_manifest.json')
    assert all(sha(root/p)==h for p,h in manifest.items()), 'Frozen source/input changed'
    protocol = read(root/'protocol.json')
    assert sha(root/'source_manifest.json')==protocol['source_manifest_hash']
    module = helper(root/'grouping_helpers.py')
    rows = read(root/'inputs.json')
    families = {r['sample_id']:r['family'] for r in read(root/'references.json')}
    vectors = np.load(root/'vectors.npy')
    sim = np.asarray(np.clip(vectors@vectors.T,-1,1),dtype=np.float64)
    partition = read(root/'partition.json')
    dev = [i for i,r in enumerate(rows) if partition[r['sample_id']]=='dev']
    dev_rows = [rows[i] for i in dev]
    results = []
    for j,spec in enumerate(protocol['specs']):
        path = root/'development'/f'{j:03d}.json'
        if path.exists(): result = read(path)
        else:
            groups,noise = cluster(sim[np.ix_(dev,dev)],spec,module)
            metrics,_ = measure(dev_rows,groups,families,module)
            result = dict(spec=spec,metrics=metrics,noise=noise)
            save(path,result)
        results.append(result)
        save(root/'status.json',dict(status='running',phase='development',pid=os.getpid(),completed=j+1,total=len(protocol['specs']),elapsed_seconds=time.monotonic()-start))
    selected = {method:max((r for r in results if r['spec']['method']==method),key=lambda r:(r['metrics']['objective'],-r['metrics']['largest_group']))
                for method in sorted({r['spec']['method'] for r in results})}
    save(root/'selected.json',selected) # Freeze before confirmation/sequence checks.
    for label, parts in [('confirm',partition),('source_confirm',read(root/'source_partition.json')),('full',{r['sample_id']:'confirm' for r in rows})]:
        indices = [i for i,r in enumerate(rows) if parts[r['sample_id']]=='confirm']
        subset = [rows[i] for i in indices]
        for method,result in selected.items():
            groups,noise = cluster(sim[np.ix_(indices,indices)],result['spec'],module)
            metrics,_ = measure(subset,groups,families,module)
            # Independent pair enumeration verifies the optimized metric implementation.
            expected = module.evaluate(subset,groups,families)
            assert metrics['cross']==expected['cross'] and metrics['native']==expected['native']
            save(root/'static'/f'{label}_{method}.json',dict(metrics=metrics,noise=noise,spec=result['spec'],
                groups=[[subset[i]['sample_id'] for i in g] for g in groups]))
    # Fixed previous specs isolate the input change from development parameter selection.
    if protocol.get('comparison_root'):
        previous = read(Path(protocol['comparison_root'])/'selected.json')
        for label,parts in [('confirm',partition),('source_confirm',read(root/'source_partition.json')),('full',{r['sample_id']:'confirm' for r in rows})]:
            indices=[i for i,r in enumerate(rows) if parts[r['sample_id']]=='confirm']
            subset=[rows[i] for i in indices]
            for method,result in previous.items():
                groups,noise=cluster(sim[np.ix_(indices,indices)],result['spec'],module)
                metrics,_=measure(subset,groups,families,module)
                expected=module.evaluate(subset,groups,families)
                assert metrics['cross']==expected['cross'] and metrics['native']==expected['native']
                save(root/'fixed_previous'/f'{label}_{method}.json',dict(metrics=metrics,noise=noise,spec=result['spec'],groups=[[subset[i]['sample_id'] for i in g] for g in groups]))
    # Sequence experiment only on confirmation IDs; no tuning using sequence outcomes.
    confirm = [i for i,r in enumerate(rows) if partition[r['sample_id']]=='confirm']
    sequence_rows = [rows[i] for i in confirm]
    sequence_sim = sim[np.ix_(confirm,confirm)]
    tasks = list(itertools.product(protocol['seeds'],protocol['scenarios'],protocol['batch_sizes'],sorted(selected)))
    durations = []
    for task_idx,(seed,scenario,batch_size,method) in enumerate(tasks):
        task_start = time.monotonic()
        path = root/'sequences'/f'{seed}_{scenario}_{batch_size}_{method}.json'
        if path.exists(): continue
        spec = selected[method]['spec']
        arrival = orders(sequence_rows,families,seed,scenario)
        save(root/'orders'/f'{seed}_{scenario}.json',[sequence_rows[i]['sample_id'] for i in arrival])
        seen = set(); previous = None; previous_ids = []; batch_groups = []; steps=[]
        for offset in range(0,len(arrival),batch_size):
            fresh = arrival[offset:offset+batch_size]
            old = seen.copy(); seen.update(fresh); ids=sorted(seen)
            index = {i:j for j,i in enumerate(ids)}
            subset = [sequence_rows[i] for i in ids]
            groups,noise = cluster(sequence_sim[np.ix_(ids,ids)],spec,module)
            metrics,together = measure(subset,groups,families,module)
            fresh_groups,_ = cluster(sequence_sim[np.ix_(fresh,fresh)],spec,module)
            batch_groups.extend([[fresh[i] for i in g] for g in fresh_groups])
            baseline = [[index[i] for i in g] for g in batch_groups]
            baseline_metrics,baseline_assigned = measure(subset,baseline,families,module)
            _,_,labels,lower,crossmask = context(subset,families)
            isnew = np.array([i in fresh for i in ids])
            newold = lower & (isnew[:,None] != isnew[None,:])
            cross_batch = module.pair_metrics(labels[:,None]==labels[None,:],crossmask & newold,together)
            oldpeer = sum(any(together[index[i],index[j]] for j in old) for i in fresh)
            stability=None
            if previous is not None:
                oldindices=[index[i] for i in previous_ids]
                now=together[np.ix_(oldindices,oldindices)]
                tri=np.tril(np.ones(previous.shape,dtype=bool),-1)
                union=int(np.sum((previous|now)&tri))
                stability=dict(pair_jaccard=float(np.sum((previous&now)&tri))/union if union else 1.0,
                               changed_pairs=int(np.sum((previous!=now)&tri)))
            # Material quality around newly arriving known-family anchors (at most 4 peers).
            hit=pred=anchors=opportunity=0
            for i in fresh:
                label=families.get(sequence_rows[i]['sample_id'])
                if label is None: continue
                anchors+=1
                opportunity+=any(families.get(sequence_rows[j]['sample_id'])==label for j in old)
                peers=[j for j in old if together[index[i],index[j]]]
                peers.sort(key=lambda j:(-sequence_sim[i,j],j))
                for j in peers[:4]:
                    other=families.get(sequence_rows[j]['sample_id'])
                    if other is not None: pred+=1;hit+=other==label
            steps.append(dict(batch=offset//batch_size+1,seen=len(ids),new=len(fresh),noise=noise,accumulated=metrics,
                              batch_only=baseline_metrics,cross_batch_new_old=cross_batch,
                              new_with_historical_peer=oldpeer/len(fresh),old_pair_stability=stability,
                              historical_materials=dict(known_anchors=anchors,anchors_with_same_family_available=opportunity,
                                                       known_peer_pairs=pred,same_family_peer_pairs=hit,precision=hit/pred if pred else None)))
            previous=together;previous_ids=ids
        save(path,dict(seed=seed,scenario=scenario,batch_size=batch_size,method=method,spec=spec,steps=steps,
                       final_groups=[[sequence_rows[ids[i]]['sample_id'] for i in g] for g in groups],seconds=time.monotonic()-task_start))
        durations.append(time.monotonic()-task_start)
        completed=len(list((root/'sequences').glob('*.json')))
        eta=float(np.mean(durations[-10:]))*(len(tasks)-completed)
        save(root/'status.json',dict(status='running',phase='sequences',pid=os.getpid(),completed=completed,total=len(tasks),
                                   elapsed_seconds=time.monotonic()-start,estimated_remaining_seconds=eta,last_task=[seed,scenario,batch_size,method]))
        print(f'{completed}/{len(tasks)} sequence runs; ETA {eta/60:.1f} min',flush=True)
    all_results=[read(p) for p in sorted((root/'sequences').glob('*.json'))]
    summary=[]
    for method in selected:
        subset=[r for r in all_results if r['method']==method]
        summary.append(dict(method=method,sequences=len(subset),
            final_cross_f1=[r['steps'][-1]['accumulated']['cross']['f1'] for r in subset],
            mean_path_cross_f1=float(np.mean([s['accumulated']['cross']['f1'] or 0 for r in subset for s in r['steps']])),
            mean_batch_only_path_cross_f1=float(np.mean([s['batch_only']['cross']['f1'] or 0 for r in subset for s in r['steps']]))))
    save(root/'summary.json',dict(methods=summary,selected=selected,sequence_runs=len(all_results),scope=protocol['scope'],limitations=protocol['limitations']))
    save(root/'status.json',dict(status='completed',pid=os.getpid(),sequence_runs=len(all_results),elapsed_seconds=time.monotonic()-start,estimated_remaining_seconds=0))


def self_check():
    module=helper(BASE/'scripts/analysis/test_question_grouping_methods.py')
    sim=np.array([[1,.95,.1],[.95,1,.1],[.1,.1,1]])
    groups,noise=cluster(sim,dict(method='dbscan',threshold=.8,min_samples=2),module)
    assert noise==1 and sorted(map(len,groups))==[1,2]
    groups,noise=cluster(np.eye(3),dict(method='hdbscan',min_cluster_size=5,min_samples=2,cluster_selection_method='eom'),module)
    assert noise==3 and not coassigned(3,groups)[0,1]
    rows=[dict(sample_id=str(i),dataset='a' if i<2 else 'b',category='a/x' if i<2 else 'b/x') for i in range(3)]
    families={str(i):'sequence_order' for i in range(3)}
    measured,_=measure(rows,[[0,1,2]],families,module)
    assert measured['cross']==module.evaluate(rows,[[0,1,2]],families)['cross']
    assert set(orders(rows,families,SEED,'late_ordering'))==set(range(3))
    toy=np.full((12,12),.1);toy[:6,:6]=.95;toy[6:,6:]=.95;np.fill_diagonal(toy,1)
    clustered,noise=cluster(toy,dict(method='hdbscan',min_cluster_size=3,min_samples=2,cluster_selection_method='eom'),module)
    assert noise==0 and sorted(map(len,clustered))==[6,6]
    # A later batch can find old materials, while frozen batch-only groups cannot.
    together=coassigned(4,[[0,2],[1,3]])
    separate=coassigned(4,[[0],[1],[2],[3]])
    assert together[0,2] and not separate[0,2]
    row=dict(question='Full task context\nQuestion: compare videos',options=['A. x','B. y'],videos=[dict(video_id='video_1',duration_sec=2.5),dict(video_id='video_2',duration_sec=7)])
    text=video_id_duration_text(row)
    assert row['question'] in text and 'A. x' in text and 'video_1: duration=2.5 seconds' in text
    assert text.index('video_1')<text.index('video_2')
    assert not any(field in text for field in ['Video count:', 'Video durations in seconds:', 'Mean video', 'Minimum video', 'Maximum video', 'Option count:'])
    print('self-check passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['launch','run','self-check'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--representation',choices=['strategy_full_input','video_id_duration'],default='strategy_full_input')
    args=parser.parse_args()
    if args.command=='self-check': self_check()
    else:
        root=args.output.resolve()
        if args.command=='launch':
            prepare(root,args.representation)
            env=os.environ.copy()
            env.update(PYTHONPATH=str(root/'src'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
            with (root/'controller.log').open('a') as log:
                process=subprocess.Popen([sys.executable,str(root/'controller.py'),'run','--output',str(root)],
                    cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(root/'launch.json',dict(pid=process.pid,python=sys.executable,command='run',source_hash=sha(root/'controller.py')))
            print(json.dumps(dict(pid=process.pid,output=str(root))))
        else:
            lock = (root/'controller.lock').open('a')
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try: run(root)
            except Exception as error:
                save(root/'status.json',dict(status='failed',pid=os.getpid(),error=str(error),traceback=traceback.format_exc()))
                raise
