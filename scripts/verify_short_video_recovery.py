"""Actual five-frame regression and a bounded full-trajectory recovery check."""
import os
from pathlib import Path
import sys

SOURCE=Path(os.environ.get('MVAGENT_PROJECT_ROOT','/repo'))
BASE=Path('/runs/devbox/direct_answer_large_20261016')
OUT=Path('/runs/devbox/direct_answer_large_recovery_20261017')
sys.path[:0]=[str(SOURCE/'src'),str(BASE/'frozen_repo/scripts'),str(BASE/'frozen_repo/eval/e2e_eval')]
from compare_direct_answer import read,write,sha
# The historical helper prepends its own snapshot; restore the source under test.
sys.path.insert(0,str(SOURCE/'src'))
from skill_evolution.infra.benchmarks.catalog import load_multibench_records


def cpu():
    from mvagent.agents.video_agent.agent import VideoAgent
    from mvagent.utils.media import probe_video_info
    from vllm.multimodal.video import OpenCVVideoBackend
    import inspect
    assert Path(inspect.getfile(VideoAgent)).resolve()==(SOURCE/'src/mvagent/agents/video_agent/agent.py').resolve()
    rec=load_multibench_records('/assets',['mvu_eval:TR:1493'])['mvu_eval:TR:1493']
    directory=OUT/'probe';directory.mkdir(parents=True,exist_ok=True)
    agent=VideoAgent.__new__(VideoAgent)
    agent.video_id='probe';agent.max_video_frames_per_request=512
    videos=[(p,probe_video_info(p)) for p in rec.sample.videos.values()]
    path,info=min(videos,key=lambda pair:pair[1]['duration_sec'])
    agent.video_path=path;agent.duration_sec=info['duration_sec']
    agent.source_frame_count=info['frame_count'];agent.cache_dir=str(directory)
    fps=agent._effective_fps(2,agent.duration_sec)
    before,_=OpenCVVideoBackend.load_bytes(Path(path).read_bytes(),num_frames=512,fps=fps)
    assert len(before)==1,(info,fps,len(before))
    fixed=agent._video_input_path([0,agent.duration_sec],fps)
    after,_=OpenCVVideoBackend.load_bytes(Path(fixed).read_bytes(),num_frames=512,fps=fps)
    digest=sha(Path(fixed))
    repeated=agent._video_input_path([0,agent.duration_sec],fps)
    assert len(after)>=2 and digest==sha(Path(repeated)),(len(after),digest,sha(Path(repeated)))
    path,info=max(videos,key=lambda pair:pair[1]['duration_sec'])
    agent.video_path=path;agent.duration_sec=info['duration_sec'];agent.source_frame_count=info['frame_count']
    fps=agent._effective_fps(2,agent.duration_sec)
    assert agent._video_input_path([0,agent.duration_sec],fps)==path
    result=dict(before_frames=len(before),after_frames=len(after),repeat_sha_equal=True,
                ordinary_full_video_unchanged=True,repaired_sha256=digest)
    write(directory/'cpu_check.json',result);print(result,flush=True)


def gpu():
    import yaml
    from mvagent.batch import BatchExecutor,ExecutionConfig
    from verify_direct_answer import trace
    original=read(OUT/'recovery_manifest.json')['original']['27B']
    anchor=sorted(s for s,r in original.items() if s.startswith('cvbench:') and r['status']=='ok')[0]
    sid='mvu_eval:TR:1493'
    records=load_multibench_records('/assets',[sid,anchor])
    cfg=yaml.safe_load((OUT/'27B/config.yaml').read_text())
    execution=ExecutionConfig.from_yaml(OUT/'27B/execution.yaml')
    batch=BatchExecutor(execution)
    saved={}
    def completed(payload):
        write(OUT/'verification'/f"{payload['sample_id']}.json",payload)
        assert payload['status']=='ok',payload.get('error')
        saved[payload['sample_id']]=payload
    try:
        batch.run([dict(sample_id=s,question=records[s].sample.question,videos=dict(records[s].sample.videos))
                   for s in [sid,anchor]],cfg,on_complete=completed)
    finally:batch.close()
    baseline={sid:read(OUT/'27B/records/mvu_eval'/sid/'result.json'),anchor:read(Path(original[anchor]['path']))}
    fields=['input','video_metadata','video_reports','watch_results','action_history','trajectory','answer','stop_reason']
    for s,row in saved.items():
        assert trace(row['events'])==trace(baseline[s]['events']),('Token/input mismatch',s)
        for field in fields:assert row['result'][field]==baseline[s]['result'][field],(s,field)
    result=dict(sample_ids=[sid,anchor],differences=0,model_errors=0,
        paired_calls=sum(sum(e['kind']=='model_response' for e in r['events']) for r in saved.values()),
        old_anchor_unchanged=True,whole_repaired_trajectory_repeated=True)
    write(OUT/'verification/summary.json',result);print(result,flush=True)


if __name__=='__main__':{'cpu':cpu,'gpu':gpu}[sys.argv[1]]()
