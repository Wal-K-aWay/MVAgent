"""Exercise final aggregation against the frozen driver without starting a Judge."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

sys.path.insert(0,str(Path(sys.argv[1])/'frozen_repo/eval/external_methods'))
import lenswalk_full as run

rows={};records={}
def add(sid,dataset,task,score,points=1):
    rows[sid]=dict(sample_id=sid,dataset=dataset,task=task,score=score,
        infrastructure_error=False,terminal='finish',seconds=10,prepared_seconds=2)
    records[sid]=SimpleNamespace(sample=SimpleNamespace(ground_truth=['point']*points))

add('cv1','cvbench','choice',1);add('cv2','cvbench','choice',0)
add('mvu1','mvu_eval','choice',1)
for task in ('BU','CC','FSA','MOC','MSR','NC','PEA','PI','PSS'):
    add('cross'+task,'crossvid',task,.4)
add('qa1','crossvid','CCQA',0,1);add('qa2','crossvid','CCQA',1,3)
run.EXPECTED={'cvbench':2,'mvu_eval':1,'crossvid':11}
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);run.write(root/'manifest.json',dict(created_at='test'))
    run.score_all(root,records,rows,{},lambda:None,threading.Event(),root)
    result=json.loads((root/'summary.json').read_text())['benchmarks']
    assert result['cvbench']['score']==.5 and result['mvu_eval']['score']==1
    assert abs(result['crossvid']['score']-.435)<1e-12
    assert result['crossvid']['task_scores']['CCQA']['score']==.75
    rows['cv2'].update(infrastructure_error=True,score=None)
    rows['crossMSR']['terminal']='unfinished_tool_plan'
    run.score_all(root,records,rows,{},lambda:None,threading.Event(),root)
    result=json.loads((root/'summary.json').read_text())['benchmarks']
    assert result['cvbench']['expected']==2 and result['cvbench']['scored']==1
    assert result['cvbench']['infrastructure_failures']==['cv2']
    assert result['crossvid']['unfinished']==['crossMSR']
    assert result['crossvid']['terminal_answers']==10
print('Full-panel sample means, ten-task macro, point-weighted CCQA and failure separation passed')
