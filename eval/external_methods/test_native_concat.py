"""Remote CPU check: concatenate unlike video streams without changing decoded frames."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import av

from prepare import prepare


def decoded(path):
    with av.open(str(path), metadata_errors='ignore') as container:
        stream = container.streams.video[0]
        stream.thread_type = 'NONE'
        return [(frame.width, frame.height, float(frame.pts * frame.time_base),
                 hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest())
                for frame in container.decode(stream)]


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, codecs, variable_timing in (
            ('h264', ('libx264', 'libx264'), False),
            ('mpeg4', ('mpeg4', 'mpeg4'), False),
            ('mixed', ('libx264', 'mpeg4'), False),
            ('mixed_vfr', ('mpeg4', 'libx264'), True),
            ('preroll', ('libx264', 'libx264'), False),
            ('mixed_bt709', ('mpeg4', 'libx264'), False),
            ('mixed_bad_metadata', ('mpeg4', 'libx264'), False),
        ):
            paths = []
            for i, (codec, size, fps) in enumerate(zip(codecs, ('320x240', '480x272'), (10, 15))):
                path = root/f'{name}_{i}.mp4'
                command = ['ffmpeg','-v','error','-f','lavfi','-t','3',
                           '-i',f'testsrc2=size={size}:rate={fps}']
                if variable_timing:
                    command += ['-vf', "select='not(eq(mod(n,4),1))'", '-vsync', '0']
                if name == 'mixed_bt709' and i == 1:
                    command += ['-colorspace','bt709','-color_primaries','bt709',
                                '-color_trc','bt709','-color_range','tv']
                if name == 'mixed_bad_metadata' and i == 0:
                    command += ['-metadata','comment=bad_utf8_marker']
                subprocess.run(command + ['-c:v',codec,'-g','5','-threads','1',
                    '-pix_fmt','yuv420p','-n',str(path)],check=True)
                if name == 'mixed_bad_metadata' and i == 0:
                    payload = path.read_bytes()
                    assert payload.count(b'bad_utf8_marker') == 1
                    path.write_bytes(payload.replace(b'bad_utf8_marker', b'\xffad_utf8_marker'))
                    try:
                        with av.open(str(path)):
                            pass
                    except UnicodeDecodeError:
                        pass
                    else:
                        raise AssertionError('Fixture did not reproduce the invalid metadata')
                if name == 'preroll' and i == 1:
                    original_path = path.with_name('uncut.mp4')
                    path.rename(original_path)
                    subprocess.run(['ffmpeg','-v','error','-ss','0.4','-i',str(original_path),
                        '-t','2','-c:v','copy','-n',str(path)],check=True)
                paths.append(path)
            originals = [decoded(path) for path in paths]
            item = prepare(SimpleNamespace(sample_id=name, sample=SimpleNamespace(
                videos={f'video_{i+1}':str(path) for i,path in enumerate(paths)},
                question='Compare the two videos.', options=[])),root/'prepared')
            metadata = json.loads((Path(item['video_path']).parent/'timeline.json').read_text())
            segments = metadata['segments']
            processing = 'stream_copy' if len(set(codecs)) == 1 and name != 'preroll' else 'lossless_h264'
            assert all(s['processing'] == processing for s in segments)
            if processing == 'lossless_h264':
                assert all(s['remuxed_stream']['codec_name'] == 'h264' for s in segments)
                assert [s['verified_decoded_frames'] for s in segments] == [len(f) for f in originals]
            if variable_timing:
                assert len({round(b[2]-a[2], 6) for a, b in zip(originals[0], originals[0][1:])}) > 1
            actual = decoded(item['video_path'])
            expected = [(w,h,t+s['start']-s['source_start_time'],digest)
                        for s,frames in zip(segments,originals) for w,h,t,digest in frames]
            assert len(actual) == len(expected), (name,len(actual),len(expected))
            if not variable_timing and name != 'preroll':
                assert len(actual) == 75
            for a,e in zip(actual,expected):
                assert (a[0],a[1],a[3]) == (e[0],e[1],e[3]), (name,a,e)
                assert abs(a[2]-e[2]) < .000002, (name,a[2],e[2])
            for target in (.7, segments[1]['start']+.2,
                           segments[1]['start']+min(2.2, segments[1]['original_duration']*.8)):
                with av.open(item['video_path']) as container:
                    stream = container.streams.video[0]
                    container.seek(int(target / stream.time_base), stream=stream, backward=True)
                    frame = next(f for f in container.decode(stream) if float(f.pts*f.time_base) >= target-.000002)
                    reference = next(e for e in expected if e[2] >= target-.000002)
                    assert hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest() == reference[3]
            print(name, f'{len(actual)} decoded frames and three seeks: sizes/pixels/timing preserved')


if __name__ == '__main__':
    main()
