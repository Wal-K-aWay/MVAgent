"""Modal CPU checks for fresh RSI ownership, unchanged policy, persistence and full scoring."""
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
from datetime import datetime, timezone

from common import sha256, write
from lenswalk_partition import merge, read
from rsi_9b_32gpu import TEMPLATE, partition, patch_driver, estimate
from test_lenswalk_partition_merge import same_statistics


def main():
    original = (TEMPLATE/'frozen_repo/eval/external_methods/lenswalk_full.py').read_text()
    patched = patch_driver(original)
    functions = lambda source:{n.name:ast.dump(n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    before, after = functions(original), functions(patched)
    assert {key for key in before if before[key]!=after[key]}=={'start_actor','main','score_all'}
    assert 'media_gate=threading.Semaphore(8)' in patched
    assert "question_timeout=7200" in patched
    assert "card['execution']==expected['execution'] and card['weights_manifest']==expected['weights_manifest']" in patched
    ids = read(TEMPLATE/'samples.json')
    baseline = read(TEMPLATE/'summary.json')
    by_id = {row['sample_id']:row for row in baseline['rows']}
    costs={sid:sum(by_id[sid][key] for key in ('seconds','prepared_seconds','archive_seconds')) for sid in ids}
    groups, loads = partition(ids, costs)
    assert len(groups)==4 and sum(map(len,groups))==len(set(sum(groups,[])))==5321
    assert max(loads)-min(loads)<=max(costs.values())
    assert partition(ids,costs)==(groups,loads)
    assert len(set(sum(partition(ids,dict.fromkeys(ids,0))[0],[])))==5321
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'records').mkdir()
        write(root/'records/cvbench_72.json',dict(sample_id='cvbench:72',infrastructure_error=True))
        tree=ast.parse(patched)
        main_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        load=next(n for n in main_node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
                  and ast.unparse(n.value.func)=='rows.update')
        env=dict(output=root,rows={},read=read)
        exec(compile(ast.Module(body=[load],type_ignores=[]),'<actual RSI resume>','exec'),env)
        assert env['rows']['cvbench_72']['infrastructure_error']
        score=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='score_all')
        one=next(n for n in ast.walk(score) if isinstance(n,ast.FunctionDef) and n.name=='one')
        env.update(records={'crossvid:CCQA:1':SimpleNamespace(sample=SimpleNamespace(ground_truth=['point']),
                   judge_question='',reference_answer='')},judge=None,SCORE_PROMPT='{OUTPUT}',
                   _score_one=lambda *args,**kwargs:dict(status='ok',score=2),write=write)
        exec(compile(ast.Module(body=[one],type_ignores=[]),'<actual RSI judge persistence>','exec'),env)
        row=dict(sample_id='crossvid:CCQA:1',answer='raw answer')
        env['one'](row)
        assert read(root/'records/crossvid_CCQA_1.json')['score']==1
        assert read(root/'judgements/crossvid_CCQA_1.json')['status']=='ok'
        children=[]
        for index,assigned in enumerate(groups):
            child=root/str(index)
            write(child/'samples.json',assigned)
            write(child/'summary.json',{'rows':[by_id[sid] for sid in assigned]})
            write(child/'progress.json',{'phase':'completed_with_errors'})
            (child/'frozen_repo').symlink_to(TEMPLATE/'frozen_repo',target_is_directory=True)
            children.append(dict(root=str(child),samples_sha256=sha256(child/'samples.json')))
        output=root/'merged'
        write(output/'samples.json',ids)
        write(output/'manifest.json',dict(children=children,inherited_sources={},created_at='test'))
        merge(output)
        same_statistics(read(output/'summary.json')['benchmarks'],baseline['benchmarks'])
    print('Four disjoint balanced owners; original RSI runtime preserved; failed outcomes skipped; flat Judge persistence; 5321 scored rows merged without inference/Judge')


def check_estimate():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);children=[];history={}
        for index in range(4):
            child=root/f'shard{index}';ids=[f'cvbench:{2*index+j}' for j in range(2)]
            if index==3:ids[1]='crossvid:BU:7'
            children.append(dict(root=str(child),expected=2))
            write(child/'samples.json',ids)
            write(child/'progress.json',dict(phase='inference'))
            for sid in ids:
                history[sid]=dict(dataset=sid.split(':')[0],seconds=100,prepared_seconds=10,archive_seconds=1,infrastructure_error=False)
            row=dict(sample_id=ids[0],seconds=50 if index<3 else 1,prepared_seconds=10,
                     terminal='finish' if index<3 else 'missing_result',infrastructure_error=index==3,
                     finished_at=datetime.now(timezone.utc).isoformat())
            write(child/'records'/(ids[0].replace(':','_')+'.json'),row)
        write(root/'manifest.json',dict(children=children))
        write(root/'historical_timing.json',history)
        estimate(root)
        result=read(root/'speed_estimate.json')
        assert result['completed']==4 and result['paired_valid_samples']==3
        assert result['paired_9b_to_35b_inference_ratio']==.5 and result['provisional']
        assert result['projected_remaining_hours']==111/8/3600
        assert result['paired_timing_by_dataset']['crossvid']==dict(samples=0,ratio=None)
        assert result['groups'][3]['infrastructure_failures']==1
    print('Speed estimate excludes infrastructure failures from paired timing; early sample caveat and slowest-shard projection retained')


if __name__=='__main__':
    main()
    check_estimate()
