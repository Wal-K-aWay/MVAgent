"""Audit cross-benchmark clustering using saved vectors; no model calls."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def reference_families(rows):
    """Input-read exploratory annotations, specified independently of vector scores.

    These broad evidence demands are proxies for sharing strategy, not proven Skills.
    Unannotated inputs are unknown, not negatives.
    """
    references=[]
    for row in rows:
        category,sid=row['category'],row['sample_id']
        family=None
        if category in {'crossvid/MOC','cvbench/Joint-video Counting','mvu_eval/Counting'}:
            if sid not in {'mvu_eval:Counting:122','mvu_eval:Counting:83'}:
                family='counting'
        elif category=='crossvid/PSS':
            family='sequence_order'
        elif category=='cvbench/Multi-video Temporal Reasoning':
            if sid not in {'cvbench:404','cvbench:430','cvbench:669','cvbench:761'}:
                family='sequence_order'
        elif sid in {f'mvu_eval:TR:{n}' for n in [1412,1415,1417,1424,1437,1455,269,304]}:
            family='sequence_order'
        elif category=='crossvid/PI' or sid=='mvu_eval:TR:1382':
            family='gap_completion'
        elif category in {'crossvid/CCQA','cvbench/Video Difference Caption'}:
            family='difference_comparison'
        elif category=='mvu_eval/Comparison':
            if sid not in {f'mvu_eval:Comparison:{n}' for n in [1193,1232,842,844]}:
                family='difference_comparison'
        if family:
            references.append(dict(sample_id=sid,dataset=row['dataset'],category=category,
                family=family,question=row['question'],options=row['options']))
    return references


def run(root):
    rows=read(root/'inputs.json');byid={r['sample_id']:r for r in rows}
    output=root/'cross_benchmark';output.mkdir(exist_ok=True)
    references=reference_families(rows);ref={r['sample_id']:r for r in references}
    save(output/'strategy_references.json',references)
    save(output/'protocol.json',dict(
        method='Reuse complete-link clusters on full660; inspect cross-benchmark pairs only',
        scope='Exploratory input-read broad strategy annotations; no independent Skill-success truth',
        unknown_policy='Unannotated questions are unknown, never negative labels',
        families=dict(Counter(r['family'] for r in references)),
        input_sha256=hashlib.sha256((root/'inputs.json').read_bytes()).hexdigest(),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reference_criteria={
            'counting':'Count entities/events/categories, or select a video using explicit quantities; excludes mere existence/facility completeness. Counting units, temporal anchors and aggregation differ.',
            'sequence_order':'Order provided video fragments or determine their relative order; excludes season identification and predicting a next step.',
            'gap_completion':'Infer missing middle content from supplied surrounding segments.',
            'difference_comparison':'Observe corresponding facts across videos and characterize differences, including edit differences. Alignment/detail/output forms may differ.'}))
    shutil.copy2(__file__,output/'source.py')
    indices={r['sample_id']:i for i,r in enumerate(rows)}
    families=sorted({r['family'] for r in references});summary={}
    for variant in ['question_options','question_options_metadata']:
        folder=root/variant
        vectors=np.vstack([np.load(p) for p in sorted(folder.glob('batch_*.npy'))])
        assert vectors.shape[0]==len(rows)
        sim=np.clip(vectors@vectors.T,-1,1)
        original=read(folder/'pooled_assignments.json')
        extended=read(folder/'pooled_assignments_extended.json')
        assignments={**original,**extended}
        affinity=[]
        categories=sorted({r['category'] for r in rows})
        for ai,a in enumerate(categories):
            ia=[i for i,r in enumerate(rows) if r['category']==a]
            for b in categories[ai+1:]:
                if a.split('/')[0]==b.split('/')[0]:continue
                ib=[i for i,r in enumerate(rows) if r['category']==b]
                sub=sim[np.ix_(ia,ib)]
                rates={t:float(np.mean([assignments[t][rows[i]['sample_id']]==assignments[t][rows[j]['sample_id']]
                       for i in ia for j in ib])) for t in ['0.4','0.5','0.6','0.7','0.75']}
                pair=np.unravel_index(np.argmax(sub),sub.shape)
                affinity.append(dict(category_a=a,category_b=b,mean_similarity=float(sub.mean()),
                    max_similarity=float(sub.max()),coassignment=rates,
                    strongest_pair=[rows[ia[pair[0]]]['sample_id'],rows[ib[pair[1]]]['sample_id']]))
        save(output/f'{variant}_category_affinity.json',affinity)
        cross_neighbors=[]
        for i,row in enumerate(rows):
            eligible=[j for j,r in enumerate(rows) if r['dataset']!=row['dataset']]
            ranked=sorted(eligible,key=lambda j:-sim[i,j])[:8]
            cross_neighbors.append(dict(query=row['sample_id'],category=row['category'],
                neighbors=[dict(sample_id=rows[j]['sample_id'],category=rows[j]['category'],
                    similarity=float(sim[i,j]),same_cluster_at_05=assignments['0.5'][row['sample_id']]==assignments['0.5'][rows[j]['sample_id']],
                    reference_relation=('same_family' if ref[row['sample_id']]['family']==ref[rows[j]['sample_id']]['family'] else 'different_family')
                        if row['sample_id'] in ref and rows[j]['sample_id'] in ref else 'unknown') for j in ranked]))
        save(output/f'{variant}_cross_neighbors.json',cross_neighbors)
        reference_metrics={}
        for family in families:
            anchors=[r for r in references if r['family']==family]
            pairs=[(a,b) for i,a in enumerate(anchors) for b in anchors[:i] if a['dataset']!=b['dataset']]
            per_pair={}
            for datasets in [('crossvid','cvbench'),('crossvid','mvu_eval'),('cvbench','mvu_eval')]:
                local=[(a,b) for a,b in pairs if {a['dataset'],b['dataset']}==set(datasets)]
                if not local:continue
                per_pair['/'.join(datasets)]=dict(pairs=len(local),
                    mean_similarity=float(np.mean([sim[indices[a['sample_id']],indices[b['sample_id']]] for a,b in local])),
                    direct_similarity_pass_rate={t:float(np.mean([sim[indices[a['sample_id']],indices[b['sample_id']]] >= float(t) for a,b in local]))
                        for t in ['0.4','0.5','0.6','0.7','0.75']},coassignment={t:sum(
                    assignments[t][a['sample_id']]==assignments[t][b['sample_id']] for a,b in local)/len(local)
                    for t in ['0.4','0.5','0.6','0.7','0.75']})
            retrieval=[];baseline=[];examples=[]
            for anchor in anchors:
                # Closed reference-set retrieval: all annotated families are candidates.
                eligible=[r for r in references if r['dataset']!=anchor['dataset']]
                ranked=sorted(eligible,key=lambda r:-sim[indices[anchor['sample_id']],indices[r['sample_id']]])[:8]
                retrieval.append(sum(r['family']==family for r in ranked)/len(ranked))
                baseline.append(sum(r['family']==family for r in eligible)/len(eligible))
                if len(examples)<12:
                    best=ranked[0]
                    examples.append(dict(query=anchor['sample_id'],neighbor=best['sample_id'],
                        neighbor_family=best['family'],similarity=float(sim[indices[anchor['sample_id']],indices[best['sample_id']]]),
                        same_cluster_at_05=assignments['0.5'][anchor['sample_id']]==assignments['0.5'][best['sample_id']]))
            reference_metrics[family]=dict(questions=len(anchors),counts_by_dataset=dict(Counter(r['dataset'] for r in anchors)),
                cross_pairs=len(pairs),per_benchmark_pair=per_pair,
                cross_reference_top8_same_family=float(np.mean(retrieval)),
                cross_reference_random_baseline=float(np.mean(baseline)),examples=examples)
        # Explicit cross-only pair precision/recall within annotated reference universe.
        pair_metrics={}
        for t in ['0.4','0.5','0.6','0.7','0.75']:
            tp=pred=actual=0
            for i,a in enumerate(references):
                for b in references[:i]:
                    if a['dataset']==b['dataset']:continue
                    same=a['family']==b['family'];together=assignments[t][a['sample_id']]==assignments[t][b['sample_id']]
                    actual+=same;pred+=together;tp+=same and together
            pair_metrics[t]=dict(same_family_pairs=actual,coassigned_pairs=pred,true_positive=tp,
                precision=tp/pred if pred else None,recall=tp/actual,f1=2*tp/(pred+actual))
        mixed=[]
        groups=defaultdict(list)
        for r in rows:groups[assignments['0.5'][r['sample_id']]].append(r)
        for label,group in groups.items():
            if len({r['dataset'] for r in group})>1:
                mixed.append(dict(cluster=label,size=len(group),category_counts=dict(Counter(r['category'] for r in group)),
                    reference_family_counts=dict(Counter(ref[r['sample_id']]['family'] for r in group if r['sample_id'] in ref)),
                    members=[r['sample_id'] for r in group]))
        summary[variant]=dict(families=reference_metrics,pair_metrics=pair_metrics,
            mixed_cluster_count_at_05=len(mixed),mixed_clusters_at_05=sorted(mixed,key=lambda g:-g['size']))
    save(output/'summary.json',summary)
    print(json.dumps({v:dict(pair_metrics=d['pair_metrics'],families={k:dict(
        cross_pairs=x['cross_pairs'],top8=x['cross_reference_top8_same_family'],baseline=x['cross_reference_random_baseline'],
        coassignment=x['per_benchmark_pair']) for k,x in d['families'].items()}) for v,d in summary.items()},indent=2))


def self_check():
    def row(sid, category):
        return dict(sample_id=sid,category=category,dataset=sid.split(':')[0],question='question',options=[])
    examples=[row('mvu_eval:TR:1412','mvu_eval/TR'),row('mvu_eval:TR:1382','mvu_eval/TR'),
              row('mvu_eval:TR:1535','mvu_eval/TR'),row('mvu_eval:Counting:83','mvu_eval/Counting'),
              row('mvu_eval:Counting:1040','mvu_eval/Counting')]
    actual={r['sample_id']:r['family'] for r in reference_families(examples)}
    assert actual=={'mvu_eval:TR:1412':'sequence_order','mvu_eval:TR:1382':'gap_completion',
                    'mvu_eval:Counting:1040':'counting'}
    print('self-check passed: mixed native category split and unknown/existence exclusion')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--self-check',action='store_true')
    args=parser.parse_args()
    if args.self_check:
        self_check()
    elif args.input:
        run(args.input.resolve())
    else:
        parser.error('--input or --self-check required')
