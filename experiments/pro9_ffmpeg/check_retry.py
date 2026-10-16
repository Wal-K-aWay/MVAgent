"""Reproduce the actual short-clip failure and verify the FFmpeg repair on CPU."""
import importlib.util
from pathlib import Path
import sys

import run
from recovery import PARENT

sys.path.insert(0,str(run.CODE/'src'))
import cv2
from mvagent.utils.media import cut_video_segment

spec=importlib.util.spec_from_file_location('original_media',PARENT/'code/src/mvagent/utils/media.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
job=next(j for j in run.read(PARENT/'jobs.json') if j['sample_id']=='crossvid:MOC:565')
source=job['inputs']['videos']['view_A']
directory=run.ROOT/'probe';directory.mkdir(parents=True,exist_ok=True)


def bounds(path):
    capture=cv2.VideoCapture(path)
    count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    first_ok,_=capture.read();capture.set(cv2.CAP_PROP_POS_FRAMES,count-1);last_ok,_=capture.read()
    capture.release()
    return dict(frames=count,first=bool(first_ok),last=bool(last_ok))


original=old.cut_video_segment(source,[2.5,3.5],output_dir=str(directory),prefix='original',sampling_fps=2)
fixed=cut_video_segment(source,[2.5,3.5],output_dir=str(directory),prefix='fixed',sampling_fps=2)
repeat=cut_video_segment(source,[2.5,3.5],output_dir=str(directory),prefix='repeat',sampling_fps=2)
before,after=bounds(original),bounds(fixed)
assert not before['last'] and after['frames']>=2 and after['first'] and after['last'],(before,after)
assert run.sha(fixed)==run.sha(repeat)
plain_old=old.cut_video_segment(source,[0,10],output_dir=str(directory),prefix='plain_old',sampling_fps=2)
plain_new=cut_video_segment(source,[0,10],output_dir=str(directory),prefix='plain_new',sampling_fps=2)
assert run.sha(plain_old)==run.sha(plain_new)
run.write(directory/'decode_probe.json',dict(before=before,after=after,
    repeated_bytes_equal=True,ordinary_clip_bytes_unchanged=True,source=source))
print('Actual MOC565 clip:',before,'->',after,flush=True)
from vllm.multimodal.video import OpenCVVideoBackend
before_frames,_=OpenCVVideoBackend.load_bytes(Path(original).read_bytes(),num_frames=512,fps=2)
after_frames,_=OpenCVVideoBackend.load_bytes(Path(fixed).read_bytes(),num_frames=512,fps=2)
assert len(before_frames)==1 and len(after_frames)==2
print('Actual vLLM sampled frames: 1 -> 2',flush=True)
