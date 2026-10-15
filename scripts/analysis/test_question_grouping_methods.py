"""Frozen development/confirmation comparison of input-only question grouping."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import shutil
import time
import urllib.request

import networkx as nx
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

from models.embeddings import EmbeddingConfig, embed
from models.execution import execution_scope
from mvagent.skills.selection import EMBEDDING_INSTRUCTION
from skill_evolution.infra.data import group_by_media

SEED=20261001
STRATEGY_INSTRUCTION='Retrieve multi-video questions requiring the same reasoning and evidence acquisition strategy, regardless of subject matter, benchmark or wording.'


def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)


def profile(row):
    durations=[v['duration_sec'] for v in row['videos']]
    return '\n'.join(['Video count: '+str(len(durations)),
        'Video durations in seconds: '+', '.join(map(str,durations)),
        f'Mean video duration in seconds: {np.mean(durations):.2f}',
        f'Minimum video duration in seconds: {min(durations):.2f}',
        f'Maximum video duration in seconds: {max(durations):.2f}',
        'Option count: '+str(len(row['options']))])


def numeric_features(rows):
    return np.array([[len(r['videos']),len(r['options']),
        np.mean([v['duration_sec'] for v in r['videos']]),
        min(v['duration_sec'] for v in r['videos']),max(v['duration_sec'] for v in r['videos']),
        np.std([v['duration_sec'] for v in r['videos']]) / np.mean([v['duration_sec'] for v in r['videos']])]
        for r in rows],dtype=float)


def candidate_specs():
    candidates=[]
    for method in ['complete','average']:
        for threshold in [.35,.4,.45,.5,.55,.6,.65,.7,.75]:
            candidates.append(dict(method=method,threshold=threshold))
    for k in [8,16,32]:
        for threshold in [.45,.55,.65]:
            candidates.append(dict(method='neighborhood',k=k,threshold=threshold))
        for resolution in [.5,1,2]:
            for threshold in [.45,.55]:
                candidates.append(dict(method='mutual_knn_louvain',k=k,threshold=threshold,resolution=resolution))
    return candidates


def groups_for(sim,spec,tree_cache):
    n=len(sim);method=spec['method'];threshold=spec['threshold']
    if method in ['complete','average']:
        if method not in tree_cache:
            distances=np.clip(1-sim,0,2);np.fill_diagonal(distances,0)
            tree_cache[method]=linkage(squareform(distances,checks=False),method=method)
        labels=fcluster(tree_cache[method],1-threshold,criterion='distance')
        return [np.flatnonzero(labels==label).tolist() for label in sorted(set(labels))]
    ranking=np.argsort(-sim,axis=1,kind='stable')
    nearest=[set(int(j) for j in ranking[i] if j!=i and sim[i,j]>=threshold) for i in range(n)]
    nearest=[set(sorted(js,key=lambda j:(-sim[i,j],j))[:spec['k']]) for i,js in enumerate(nearest)]
    if method=='neighborhood':
        # Local, overlapping evidence pools; do not take connected components.
        groups={tuple(sorted({i}|nearest[i])) for i in range(n) if nearest[i]}
        ordered=sorted(groups,key=lambda g:(-len(g),g));kept=[]
        for group in ordered:
            if not any(set(group).issubset(other) for other in kept):kept.append(set(group))
        covered=set().union(*kept) if kept else set()
        return [sorted(g) for g in kept]+[[i] for i in range(n) if i not in covered]
    graph=nx.Graph();graph.add_nodes_from(range(n))
    for i in range(n):
        for j in nearest[i]:
            if j>i and i in nearest[j]:graph.add_edge(i,j,weight=float(sim[i,j]))
    if not graph.number_of_edges():return [[i] for i in range(n)]
    return [sorted(g) for g in nx.community.louvain_communities(graph,weight='weight',
        resolution=spec['resolution'],seed=SEED)]


def pair_metrics(same,positive_mask,coassigned):
    tp=int(np.sum(same&positive_mask&coassigned));pred=int(np.sum(positive_mask&coassigned));actual=int(np.sum(same&positive_mask))
    return dict(tp=tp,predicted=pred,actual=actual,precision=tp/pred if pred else None,
        recall=tp/actual if actual else None,f1=2*tp/(pred+actual) if pred+actual else None)


def evaluate(rows,groups,families):
    n=len(rows);memberships=np.zeros((n,len(groups)),dtype=np.int32)
    for j,group in enumerate(groups):memberships[group,j]=1
    assigned=(memberships@memberships.T)>0
    lower=np.tril(np.ones((n,n),dtype=bool),-1)
    datasets=np.array([r['dataset'] for r in rows]);categories=np.array([r['category'] for r in rows])
    native={d:pair_metrics(categories[:,None]==categories[None,:],lower&(datasets[:,None]==d)&(datasets[None,:]==d),assigned)
            for d in sorted(set(datasets))}
    labels=np.array([families.get(r['sample_id'],'UNKNOWN') for r in rows]);known=labels!='UNKNOWN'
    crossmask=lower&(datasets[:,None]!=datasets[None,:])&known[:,None]&known[None,:]
    cross=pair_metrics(labels[:,None]==labels[None,:],crossmask,assigned)
    native_f1=float(np.mean([v['f1'] for v in native.values() if v['f1'] is not None]))
    cross_f1=cross['f1'] or 0
    # Predeclared balanced diagnostic objective; not evolution acceptance or QA score.
    objective=(native_f1+cross_f1)/2
    multi=[g for g in groups if len(g)>1]
    covered=set().union(*(set(g) for g in multi)) if multi else set()
    heterogeneous=[]
    for g in multi:
        fs={labels[i] for i in g if known[i]}
        if len(fs)>1:heterogeneous.append(g)
    return dict(objective=objective,native_macro_f1=native_f1,native=native,cross=cross,
        groups=len(groups),largest_group=max(map(len,groups)),
        multi_member_coverage=len(covered)/n,mean_memberships=float(memberships.sum(axis=1).mean()),
        multi_family_groups=len(heterogeneous),known_family_counts=dict(Counter(labels[known])))


def prepare(parent,root):
    root.mkdir(parents=True,exist_ok=False)
    rows=read(parent/'inputs.json');references=read(parent/'cross_benchmark/strategy_references.json')
    buckets=defaultdict(list)
    for row in rows:buckets[row['category']].append(row['sample_id'])
    rng=random.Random(SEED);partition={}
    for category,ids in sorted(buckets.items()):
        shuffled=sorted(ids);rng.shuffle(shuffled)
        for i,sid in enumerate(shuffled):partition[sid]='dev' if i<len(ids)//2 else 'confirm'
    sourcegroups=group_by_media({r['sample_id']:r['source_keys'] for r in rows})
    owners=defaultdict(set)
    for sid,g in sourcegroups.items():owners[g].add(partition[sid])
    overlap=[g for g,parts in owners.items() if len(parts)>1]
    # Separate source-disjoint stress split. No labels are used in assignment.
    source_parts={g:('dev' if int(hashlib.sha256((str(SEED)+g).encode()).hexdigest(),16)%2 else 'confirm')
                  for g in set(sourcegroups.values())}
    save(root/'partition.json',partition);save(root/'source_partition.json',{sid:source_parts[g] for sid,g in sourcegroups.items()})
    save(root/'source_audit.json',dict(groups=len(owners),shared_groups_in_id_split=len(overlap),
        shared_questions_in_id_split=sum(sourcegroups[sid] in overlap for sid in partition),
        warning='Primary split holds out question labels/identities, not source videos. Source split is a separately reported stress check, not independent Test.'))
    save(root/'inputs.json',rows);save(root/'references.json',references)
    save(root/'protocol.json',dict(seed=SEED,questions=len(rows),dev=sum(x=='dev' for x in partition.values()),
        confirm=sum(x=='confirm' for x in partition.values()),source=str(parent),input_hash=sha(parent/'inputs.json'),
        reference_hash=sha(parent/'cross_benchmark/strategy_references.json'),code_hash=sha(__file__),
        criterion='Mean of within-benchmark native-category macro pair F1 and cross-benchmark broad-family pair F1; thresholds selected on dev only.',
        methods=candidate_specs(),metadata_weights=[.05,.15,.30],
        limits='Exploratory labels; no independent Test, Skill effectiveness or QA gain established. Confirm is reclustered alone, no dev geometry.'))
    shutil.copy2(__file__,root/'controller.py')
    shutil.copytree(Path('src'),root/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))


def vectors_for(parent,root,rows):
    vectors={v:np.vstack([np.load(p) for p in sorted((parent/v).glob('batch_*.npy'))])
             for v in ['question_options','question_options_metadata']}
    texts=read(parent/'question_options/embedding_inputs.json')
    representations={
        'summary_concat':[t+'\n\n'+profile(r) for t,r in zip(texts,rows)],
        'strategy_instruction':[f'Instruct: {STRATEGY_INSTRUCTION}\nQuery: {t}' for t in texts],
        'strategy_summary':[f'Instruct: {STRATEGY_INSTRUCTION}\nQuery: {t}\n\n{profile(r)}' for t,r in zip(texts,rows)],
        'selector_query':[f'Instruct: {EMBEDDING_INSTRUCTION}\nQuery: {r["question"][:3000]}\nRecent evidence/history:\n' for r in rows],
        'metadata_only':[profile(r) for r in rows]}
    config=EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b',120)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    identity=json.load(opener.open(config.endpoint+'/models',timeout=10));save(root/'embedding_service.json',identity)
    if not any(m['id']==config.model and m.get('root')=='/home/kww/models/Qwen3-Embedding/Qwen3-Embedding-8B' for m in identity['data']):raise ValueError('Embedding identity mismatch')
    for name,inputs in representations.items():
        folder=root/'embeddings'/name;folder.mkdir(parents=True,exist_ok=True);save(folder/'inputs.json',inputs)
        batches=[]
        for start in range(0,len(inputs),32):
            path=folder/f'batch_{start:05}.npy'
            if not path.exists():
                with (root/'embedding_events.jsonl').open('a') as events:
                    with execution_scope(emit=lambda e:events.write(json.dumps(e)+'\n')):
                        vector=embed(config,tuple(inputs[start:start+32]))
                np.save(path,vector)
            batches.append(np.load(path))
        vectors[name]=np.vstack(batches);print('Embedded',name,flush=True)
    return vectors


def similarities(vectors,features,dev_indices):
    sims={name:np.clip(v@v.T,-1,1) for name,v in vectors.items() if name!='metadata_only'}
    transformed=np.log1p(features)
    # Scaling is fitted on dev only; never on confirmation data.
    median=np.median(transformed[dev_indices],axis=0)
    scale=np.quantile(transformed[dev_indices],.75,axis=0)-np.quantile(transformed[dev_indices],.25,axis=0)
    scale=np.maximum(scale,.1);scaled=(transformed-median)/scale
    distance=np.mean(np.minimum(np.abs(scaled[:,None,:]-scaled[None,:,:]),4),axis=2)
    numerical=np.exp(-distance);metadata=np.clip(vectors['metadata_only']@vectors['metadata_only'].T,-1,1)
    for weight in [.05,.15,.30]:
        sims[f'numeric_mix_{weight}']=(1-weight)*sims['question_options']+weight*numerical
        sims[f'metadata_embedding_mix_{weight}']=(1-weight)*sims['question_options']+weight*metadata
    return sims,dict(log1p_median=median.tolist(),iqr_scale=scale.tolist())


def run(parent,root):
    if not (root/'protocol.json').exists():prepare(parent,root)
    protocol=read(root/'protocol.json')
    if protocol['code_hash']!=sha(__file__) or protocol['input_hash']!=sha(parent/'inputs.json'):raise ValueError('Frozen experiment identity changed')
    rows=read(root/'inputs.json');families={r['sample_id']:r['family'] for r in read(root/'references.json')}
    partition=read(root/'partition.json');dev=[i for i,r in enumerate(rows) if partition[r['sample_id']]=='dev']
    vectors=vectors_for(parent,root,rows);sims,scaling=similarities(vectors,numeric_features(rows),dev);save(root/'numeric_scaling.json',scaling)
    specs=candidate_specs();records=[]
    dev_rows=[rows[i] for i in dev]
    for name,full in sims.items():
        sim=full[np.ix_(dev,dev)];cache={}
        for spec in specs:
            groups=groups_for(sim,spec,cache)
            measured=evaluate(dev_rows,groups,families)
            records.append(dict(representation=name,spec=spec,dev=measured))
        save(root/'development_metrics.json',records)
        print('Dev evaluated',name,flush=True)
    selected=max(records,key=lambda r:(r['dev']['objective'],-r['dev']['largest_group']))
    by_method={}
    for method in sorted({s['method'] for s in specs}):
        by_method[method]=max((r for r in records if r['spec']['method']==method),key=lambda r:r['dev']['objective'])
    baseline=dict(representation='question_options_metadata',spec=dict(method='complete',threshold=.75))
    fixed=[baseline,selected]+list(by_method.values())
    # Freeze choice before any confirm or source-stress evaluation.
    save(root/'selected.json',dict(selected=selected,by_method=by_method,baseline=baseline))
    confirms=[]
    partitions=[('confirm',partition,'confirm'),('source_confirm',read(root/'source_partition.json'),'confirm')]
    for name,split,target in partitions:
        indices=[i for i,r in enumerate(rows) if split[r['sample_id']]==target]
        subset=[rows[i] for i in indices];cache_by_rep={}
        for record in fixed:
            rep=record['representation'];spec=record['spec'];sim=sims[rep][np.ix_(indices,indices)]
            groups=groups_for(sim,spec,cache_by_rep.setdefault(rep,{}));metrics=evaluate(subset,groups,families)
            confirms.append(dict(partition=name,representation=rep,spec=spec,metrics=metrics))
        save(root/f'{name}_inputs.json',subset)
    save(root/'confirmation_metrics.json',confirms)
    # Full grouping is for inspectable material pools, not selection of parameters.
    rep=selected['representation'];spec=selected['spec'];groups=groups_for(sims[rep],spec,{})
    save(root/'selected_full_groups.json',[[rows[i]['sample_id'] for i in g] for g in groups])
    save(root/'selected_full_metrics.json',evaluate(rows,groups,families))
    np.save(root/'selected_similarity.npy',sims[rep])
    save(root/'status.json',dict(status='completed',dev_configs=len(records),confirm_checks=len(confirms),selected=selected))
    print('Selected:',json.dumps(selected),flush=True)


def self_check():
    sim=np.array([[1,.9,.4],[.9,1,.9],[.4,.9,1]])
    complete=groups_for(sim,dict(method='complete',threshold=.6),{})
    assert max(map(len,complete))==2
    local=groups_for(sim,dict(method='neighborhood',threshold=.6,k=1),{})
    assert any(set(g)=={0,1} for g in local) and any(set(g)=={1,2} for g in local)
    row=dict(sample_id='a',dataset='x',category='x/a',videos=[dict(duration_sec=10),dict(duration_sec=20)],options=['A','B'])
    assert 'Video count: 2' in profile(row) and '15.00' in profile(row)
    assert np.isfinite(numeric_features([row])).all()
    measured=evaluate([row,{**row,'sample_id':'b'}],[[0,1]],{})
    assert measured['native_macro_f1']==1 and measured['cross']['actual']==0
    print('self-check passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--self-check',action='store_true')
    args=parser.parse_args()
    if args.self_check:self_check()
    elif args.input and args.output:run(args.input.resolve(),args.output.resolve())
    else:parser.error('--input and --output, or --self-check required')
