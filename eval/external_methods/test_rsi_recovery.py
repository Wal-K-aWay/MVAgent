"""Recovery must keep invalid model decisions and retry only failures or missing questions."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from common import sha256, write
import recover_rsi as recovery


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        previous, output = root/'previous', root/'recovery'
        frozen = previous/'frozen_repo'
        (frozen/'eval/external_methods').mkdir(parents=True)
        (frozen/'model.py').write_text('original model configuration')
        ids = ['cvbench:1','cvbench:2','cvbench:3','cvbench:4']
        original_hashes = {}
        for sid,terminal,failed in [(ids[0],'finish',False),(ids[1],'invalid_decision',False),(ids[2],'execution_error',True)]:
            path = previous/'rsi'/sid.replace(':','_')/'record.json'
            write(path,dict(sample_id=sid, terminal=terminal, infrastructure_error=failed,
                           answer='B' if terminal=='finish' else '', score=1 if terminal=='finish' else 0,
                           raw_archive={'path':'/original/attempt.tar'}))
            original_hashes[path] = sha256(path)
        write(previous/'samples.json',ids)
        write(previous/'prepared/private_labels.json',{sid:{'sample':{'videos':{'v':'source.mp4'}}} for sid in ids})
        write(previous/'client_environment.json',{'unchanged':'locked deps'})
        write(previous/'manifest.json',dict(method='rsi',samples_sha256=sha256(previous/'samples.json'),
            method_settings={'max_output_tokens':8192,'request_timeout_seconds':600},
            source_hashes={'model.py':sha256(frozen/'model.py')}))
        write(previous/'progress.json',dict(phase='failed',completed=3))
        media = root/'video.mp4'; media.write_bytes(b'unchanged cached video')
        timeline = root/'timeline.json'; write(timeline,{'segments':[]})
        key = recovery.media_key({'v':'source.mp4'})
        write(previous/'media_cache'/f'{key}.json',dict(video_path=str(media),timeline_path=str(timeline)))
        with patch.object(recovery,'EXPECTED',{'cvbench':4}), patch.object(recovery,'MEDIA_SOURCE',root/'unused'):
            recovery.recover(previous,output)
        restored = recovery.read(output/'inherited_records.json')
        assert set(restored)=={'cvbench_1','cvbench_2'}
        assert restored['cvbench_2']['terminal']=='invalid_decision' and restored['cvbench_2']['score']==0
        manifest = recovery.read(output/'recovery_manifest.json')
        assert manifest['retry_failures']==[ids[2]] and manifest['previously_unfinished']==[ids[3]]
        assert manifest['pending']==ids[2:] and len(manifest['cache_sources'])==1
        assert not list((output/'rsi').iterdir())
        assert all(sha256(path)==digest for path,digest in original_hashes.items())
        assert (output/'frozen_repo/model.py').read_bytes()==(frozen/'model.py').read_bytes()
        assert recovery.read(output/'manifest.json')['method_settings']==recovery.read(previous/'manifest.json')['method_settings']
    print('RSI recovery preserves model negatives, original records, cached media and settings; retries failures/missing only')


if __name__ == '__main__':
    main()
