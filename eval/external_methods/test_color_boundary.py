"""Reproduce NC851's BT.709-to-unspecified boundary using its real source videos."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from prepare import frame_signatures, prepare, verify_frames


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clips = []
        for index, name in enumerate(('BWC-4.mp4', 'earth7-7.mp4')):
            path = root/f'{index}.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', '/assets/crossvid/videos/movie/'+name,
                            '-t', '2', '-map', '0:v:0', '-c:v', 'copy', '-an', '-n', str(path)], check=True)
            clips.append(path)
        item = prepare(SimpleNamespace(sample_id='nc851_boundary', sample=SimpleNamespace(
            videos={f'video_{i+1}': str(p) for i, p in enumerate(clips)},
            question='Boundary regression.', options=[])), root/'prepared')
        metadata = json.loads((Path(item['video_path']).parent/'timeline.json').read_text())
        expected = (f for p, segment in zip(clips, metadata['segments'])
                    for f in frame_signatures(p, segment['start']-segment['source_start_time']))
        count = verify_frames(expected, frame_signatures(item['video_path']), 'real NC851 color boundary')
        assert count > 80
        print(f'NC851 real-source boundary: {count} RGB frames, dimensions and PTS unchanged')


if __name__ == '__main__':
    main()
