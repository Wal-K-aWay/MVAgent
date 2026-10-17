"""Small recovery regressions; run on the remote CPU image."""
from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch

from common import sha256, write
import recover_lenswalk as recovery
from prepare import (packet_clock, preserve_terminal_duration, verify_concat_clock,
                     verify_frames, frame_signatures)
from recover_lenswalk import inherit_record, media_failure


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
                                 ('unfinished_tool_plan', False), ('execution_error', True),
                                 ('missing_result', True)]:
            source = root/'old'/terminal/'record.json'
            row = dict(sample_id=terminal, terminal=terminal, infrastructure_error=failed,
                       answer='', calls=0 if terminal=='execution_error' else 3,
                       seconds=0 if terminal=='execution_error' else 625,
                       raw_archive=dict(path='/old/attempt.tar.gz', sha256='original'))
            write(source, row)
            before = sha256(source)
            sid, restored, evidence = inherit_record(source)
            assert sid == terminal
            assert restored == row and evidence['sha256'] == before
            assert media_failure(restored) == (terminal=='execution_error')
            write(root/'new/inherited_records.json', {sid:dict(restored, score=0)})
            assert sha256(source) == before, 'Inherited index changed the historical record'
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
        previous, output, snapshot = root/'primary', root/'media_retry', root/'patch/frozen_repo'
        adapter = snapshot/'eval/external_methods'
        adapter.mkdir(parents=True)
        (adapter/'lenswalk_full.py').write_text('frozen driver')
        write(snapshot.parent/'patch_manifest.json', dict(commit='frozen', source_hashes={},
            driver_sha256=sha256(adapter/'lenswalk_full.py')))
        cases = {'cvbench:1': ('finish', False, 5), 'cvbench:2': ('empty_answer', False, 4),
                 'cvbench:3': ('missing_result', True, 625), 'cvbench:4': ('execution_error', True, 0)}
        original_hashes = {}
        for sid, (terminal, failed, seconds) in cases.items():
            path = previous/'lenswalk'/sid.replace(':','_')/'record.json'
            write(path, dict(sample_id=sid, terminal=terminal, infrastructure_error=failed,
                calls=0 if seconds==0 else 3, seconds=seconds, answer='', raw_archive={'path':'old.tar'}))
            original_hashes[path] = sha256(path)
        write(previous/'samples.json', list(cases))
        write(previous/'prepared/private_labels.json', {sid:{'sample':{'videos':{}}} for sid in cases})
        write(previous/'manifest.json', dict(samples_sha256=sha256(previous/'samples.json')))
        write(previous/'progress.json', dict(phase='completed_with_errors'))
        (previous/'client_environment.tar.gz').write_bytes(b'unchanged client')
        with patch.object(recovery, 'ADAPTERS', adapter), patch.object(recovery, 'EXPECTED', {'cvbench':4}):
            recovery.recover(previous, output)
        result = recovery.read(output/'recovery_manifest.json')
        assert result['pending'] == ['cvbench:4']
        assert result['retained_infrastructure_failures'] == ['cvbench:3']
        assert len(recovery.read(output/'inherited_records.json')) == 3
        assert not list((output/'lenswalk').iterdir()), 'Duplicated inherited result directories'
        assert (output/'frozen_repo').resolve() == snapshot.resolve()
        assert all(sha256(path)==digest for path,digest in original_hashes.items())
    print('Keep model outcomes and HTTP failures; retry media failures only; preserve originals')
    print('Real OR440: repair terminal sample duration; all 1090 RGB frames and PTS unchanged')


if __name__ == '__main__':
    main()
