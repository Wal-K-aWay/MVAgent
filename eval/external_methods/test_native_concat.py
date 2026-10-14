"""Remote CPU check: concatenate unlike video streams without changing decoded frames."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import av

from prepare import prepare


def decoded(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'NONE'
        return [(frame.width, frame.height, float(frame.pts * frame.time_base),
                 hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest())
                for frame in container.decode(stream)]


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for codec in ('libx264', 'mpeg4'):
            paths = []
            for i, (size, fps) in enumerate((('320x240', 10), ('480x272', 15))):
                path = root/f'{codec}_{i}.mp4'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'testsrc2=size={size}:rate={fps}',
                    '-t','1','-c:v',codec,'-threads','1','-pix_fmt','yuv420p','-n',str(path)],check=True)
                paths.append(path)
            originals = [decoded(path) for path in paths]
            item = prepare(SimpleNamespace(sample_id=codec, sample=SimpleNamespace(
                videos={f'video_{i+1}':str(path) for i,path in enumerate(paths)},
                question='Compare the two videos.', options=[])),root/'prepared')
            actual = decoded(item['video_path'])
            expected = [(w,h,t+i,digest) for i,frames in enumerate(originals) for w,h,t,digest in frames]
            assert len(actual) == len(expected) == 25, (codec,len(actual),len(expected))
            for a,e in zip(actual,expected):
                assert (a[0],a[1],a[3]) == (e[0],e[1],e[3]), (codec,a,e)
                assert abs(a[2]-e[2]) < .000002, (codec,a[2],e[2])
            print(codec, '25/25 decoded frames, original sizes/pixels and timing preserved')


if __name__ == '__main__':
    main()
