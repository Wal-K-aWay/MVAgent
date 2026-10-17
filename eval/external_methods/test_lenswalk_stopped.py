"""A stopped recovery keeps model negatives and HTTP errors, including bulk inheritance."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from common import sha256, write
import recover_lenswalk_stopped as recovery


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        previous, output=root/'previous',root/'recovery'
        ids=[f'cvbench:{i}' for i in range(5)]
        rows={sid:dict(sample_id=sid, answer='A' if i==0 else '',
            terminal=['finish','unfinished_tool_plan','missing_result','execution_error'][i],
            infrastructure_error=i>=2, calls=0 if i==3 else 3, seconds=0 if i==3 else 100,
            score=1 if i==0 else 0, raw_archive={'path':'original.tar'}) for i,sid in enumerate(ids[:4])}
        write(previous/'inherited_records.json', {'cvbench_0':rows[ids[0]], 'cvbench_1':rows[ids[1]]})
        for sid in ids[2:4]:
            write(previous/'lenswalk'/sid.replace(':','_')/'record.json', rows[sid])
        write(previous/'samples.json', ids)
        write(previous/'progress.json', {'phase':'failed','completed':4})
        write(previous/'prepared/private_labels.json', {sid:{'sample':{'videos':{'v':'old.mp4'}}} for sid in ids})
        media=root/'video.mp4';media.write_bytes(b'unchanged cached video')
        timeline=root/'timeline.json';write(timeline,{'segments':[]})
        key=recovery.media_key({'v':'old.mp4'})
        write(previous/'media_cache'/f'{key}.json', {'video_path':str(media),'timeline_path':str(timeline)})
        (previous/'client_environment.tar.gz').write_bytes(b'unchanged')
        model=previous/'frozen_repo/model.py';model.parent.mkdir();model.write_text('original model')
        original={'samples_sha256':sha256(previous/'samples.json'), 'source_hashes':{'model.py':sha256(model)},
                  'max_turns':5,'request_timeout_seconds':600,'max_output_tokens':None}
        write(previous/'manifest.json', original)
        def freeze(source, destination):
            assert source==previous
            write(destination/'patch_manifest.json', {'commit':'test', 'source_hashes':original['source_hashes'],
                                                       'driver_sha256':'unchanged'})
        with patch.object(recovery,'EXPECTED',{'cvbench':5}), patch.object(recovery,'freeze',freeze):
            recovery.recover(previous,output)
        restored=recovery.read(output/'inherited_records.json')
        assert list(restored)==['cvbench_0','cvbench_1','cvbench_2']
        assert restored['cvbench_1']==rows[ids[1]] and restored['cvbench_2']==rows[ids[2]]
        evidence=recovery.read(output/'recovery_manifest.json')
        assert evidence['pending']==ids[3:] and evidence['retry_failures']==[ids[3]]
        assert evidence['previously_unfinished']==[ids[4]] and evidence['retained_infrastructure_failures']==[ids[2]]
        assert evidence['cached_media_groups']==1
        assert (output/'media_cache'/f'{key}.json').read_bytes()==(previous/'media_cache'/f'{key}.json').read_bytes()
        manifest=recovery.read(output/'manifest.json')
        assert all(manifest[k]==original[k] for k in ('max_turns','request_timeout_seconds','max_output_tokens'))
        assert sha256(model)==original['source_hashes']['model.py']
    print('Stopped recovery keeps original model outcomes, HTTP failures, bulk references and settings')


if __name__=='__main__':main()
