"""Summarize observed A/B inputs, outputs, timings and disposable-media cleanup."""
from collections import Counter
from pathlib import Path
import statistics

from common import sha256,write
from lenswalk_full import now,read
from temp_media_probe import ROOT,SAMPLES
from temp_media_run import model_calls


def first_difference(left,right):
    for i,(a,b) in enumerate(zip(left,right)):
        if a!=b:return i
    return min(len(left),len(right)) if len(left)!=len(right) else None


def main():
    manifest=read(ROOT/'manifest.json')
    methods={}
    for method in ('rsi','lenswalk'):
        paths=sorted((ROOT/method).glob('*/comparison.json'))
        pairs=[read(p) for p in paths]
        valid=[p for p in pairs if p['valid_comparison']]
        mismatches=[]
        for pair,path in zip(pairs,paths):
            if pair['ordered_model_calls_equal']:continue
            a,b=[model_calls(path.parent/arm/'requests.jsonl') for arm in ('volume','local')]
            index=pair['first_ordered_mismatch']
            detail=dict(sample_id=pair['sample_id'],call_index=index)
            if index<min(len(a),len(b)):
                detail.update(prompt_token_index=first_difference(a[index].get('prompt_token_ids',[]),b[index].get('prompt_token_ids',[])),
                    output_token_index=first_difference(a[index].get('token_ids',[]),b[index].get('token_ids',[])),
                    images_equal=a[index].get('image_sha256')==b[index].get('image_sha256'))
            mismatches.append(detail)
        methods[method]=dict(pairs=len(pairs),valid_pairs=len(valid),
            answer_equal=sum(p['answer_equal'] for p in valid),
            ordered_model_calls_equal=sum(p['ordered_model_calls_equal'] for p in valid),
            model_call_multisets_equal=sum(p['model_call_multisets_equal'] for p in valid),
            first_differences=mismatches,
            http_errors=sum(r['http_errors'] for p in pairs for r in p['rows'].values()),
            outcomes=dict(Counter(r['terminal'] for p in pairs for r in p['rows'].values())),
            calls=sum(r['calls'] for p in pairs for r in p['rows'].values()),
            mean_inference_seconds={arm:statistics.mean(p['rows'][arm]['seconds'] for p in valid) if valid else None
                                    for arm in ('volume','local')},
            local_inputs_deleted=all(p['local_directory_removed'] for p in pairs),
            cases=[dict(sample_id=p['sample_id'],valid=p['valid_comparison'],answers={a:r['answer'] for a,r in p['rows'].items()},
                        seconds={a:r['seconds'] for a,r in p['rows'].items()},model_calls_equal=p['model_call_multisets_equal']) for p in pairs])
    long=read(ROOT/'long_progress.json') if (ROOT/'long_progress.json').exists() else {'phase':'not_started'}
    summary=dict(at=now(),inference_commit=manifest['commit'],methods=methods,
        media=[read(ROOT/'media'/sid.replace(':','_')/'comparison.json') for sid in SAMPLES],long_media=long,
        limitations=['Four reused development cases; no correctness score or Judge',
                     'One pair per case; uncontrolled OS caches and concurrent load',
                     'CPU generation and GPU input-reading/inference timed separately; no measured prefetch pipeline',
                     '0.5-second filesystem sampling can miss short peak occupancy'],
        cleanup=read(ROOT/'cleanup.json') if (ROOT/'cleanup.json').exists() else None)
    directory=ROOT/'analysis';directory.mkdir(exist_ok=True)
    (directory/'analysis_source.py').write_bytes(Path(__file__).read_bytes())
    summary['analysis_source_sha256']=sha256(directory/'analysis_source.py')
    write(directory/'summary.json',summary)
    print(summary,flush=True)


if __name__=='__main__':
    assert first_difference([1,2],[1,3])==1 and first_difference([1],[1,2])==1
    assert first_difference([1,2],[1,2]) is None
    main()
