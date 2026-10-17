"""Small recovery regressions; run on the remote CPU image."""
from pathlib import Path
import tempfile
import shutil

from common import sha256, write
from prepare import (packet_clock, preserve_terminal_duration, verify_concat_clock,
                     verify_frames, frame_signatures)
from recover_lenswalk import inherit_record


def main():
    assert verify_concat_clock([(0, .0407)], [0], .04) == .0407
    for bad in ([(.001, .04)], [(0, .042)], [(0, .04), (.04, .04)]):
        try:
            verify_concat_clock(bad, [0], .04)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted changed frames or excessive duration drift')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for terminal, failed in [('finish', False), ('empty_answer', False),
                                 ('unfinished_tool_plan', False), ('execution_error', True)]:
            source = root/'old'/terminal/'record.json'
            row = dict(sample_id=terminal, terminal=terminal, infrastructure_error=failed,
                       answer='', raw_archive=dict(path='/old/attempt.tar.gz', sha256='original'))
            write(source, row)
            before = sha256(source)
            sid, evidence = inherit_record(source, root/'new')
            assert sid == terminal
            target = root/'new/lenswalk'/terminal/'record.json'
            if failed:
                assert evidence is None and not target.exists()
            else:
                assert evidence['sha256'] == before == sha256(target)
                write(target, dict(row, score=0))
                assert sha256(source) == before, 'Judge updates changed the historical record'
        media = Path('/runs/devbox/lenswalk_full_35b_20261016/prepared/media/media_8daf0a83fec234283f074028')
        original = media/'concatenated.mp4'
        expected, duration = [], 0.0
        for index in range(6):
            packets = packet_clock(media/f'{index}.mp4')
            expected.extend(t+duration for t, _ in packets)
            duration += max(t+d for t, d in packets)
        broken = packet_clock(original)
        assert abs(max(t+d for t, d in broken)-duration) > .03
        fixed = root/'fixed.mp4'
        shutil.copyfile(original, fixed)
        preserve_terminal_duration(fixed, duration, max(expected))
        assert abs(verify_concat_clock(packet_clock(fixed), expected, duration)-duration) < .000002
        assert verify_frames(frame_signatures(original), frame_signatures(fixed), 'OR440') == 1090
    print('Keep all completed model outcomes, retry infrastructure failures, preserve originals')
    print('Real OR440: repair terminal sample duration; all 1090 RGB frames and PTS unchanged')


if __name__ == '__main__':
    main()
