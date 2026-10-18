"""Remote CPU checks: media lifetime, recovery preservation, and both frozen drivers."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from common import sha256, write
import recover_temp_media as recovery
import temporary_media


def lifetime():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        attempt = root/'attempt'; attempt.mkdir()
        def prepare(output, record, lock):
            video = output/'video.mp4';video.write_bytes(b'unchanged-video')
            write(output/'timeline.json', dict(video_sha256=sha256(video)))
            item = output/'item.json';write(item, dict(video_path=str(video)))
            return item
        with patch.object(temporary_media, 'LOCAL_ROOT', root):
            for fail in (False, True):
                try:
                    with temporary_media.temporary_item(prepare, None, attempt, None) as item:
                        video = Path(json.loads(item.read_text())['video_path'])
                        assert video.read_bytes()==b'unchanged-video'
                        assert (attempt/'timeline.json').is_file()
                        if fail:raise RuntimeError('client failure')
                except RuntimeError:
                    assert fail
                assert not video.parent.exists()
                assert json.loads((attempt/'media_cleanup.json').read_text())['removed']
            def failed_prepare(output, record, lock):
                (output/'partial.mp4').write_bytes(b'partial')
                raise ValueError('encoder failure')
            try:
                with temporary_media.temporary_item(failed_prepare, None, attempt, None):
                    raise AssertionError('Failed preparation yielded an item')
            except ValueError:pass
            assert not list(root.glob('external-media-*'))


def recovery_contract():
    source = (recovery.ADAPTERS/'lenswalk_full.py').read_text()
    patched = recovery.patch_driver(source)
    assert 'item=prepare_item(output,record,' not in patched and 'media.close()' in patched
    for method in ('rsi','lenswalk'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);old=root/'old';new=root/'new'
            frozen=old/'frozen_repo'
            write(frozen/'.git/HEAD','old revision')
            target=frozen/'eval/external_methods/lenswalk_full.py';target.parent.mkdir(parents=True)
            target.write_text(source)
            (frozen/'model.py').write_text('unchanged model source')
            ids=['cvbench:1','cvbench:2','cvbench:3','cvbench:4']
            def row(sid,terminal,failed=False):
                return dict(sample_id=sid,terminal=terminal,infrastructure_error=failed,
                            answer='',score=None if failed else 0,raw_archive={'path':'/old/raw.tar'})
            write(old/'inherited_records.json',{'cvbench_1':row(ids[0],'empty_answer')})
            write(old/method/'cvbench_2/record.json',row(ids[1],'invalid_decision'))
            write(old/method/'cvbench_3/record.json',row(ids[2],'execution_error',True))
            write(old/'samples.json',ids)
            write(old/'prepared/private_labels.json',{})
            write(old/'USER_PAUSED.json',{'reason':'paused'})
            write(old/'progress.json',dict(completed=3,episode=str(old/'episode')))
            write(old/'episode/pool_verification.json',{'0':{'execution':{'seed':0},'weights_manifest':{'model':'fixed'}}})
            client='client_environment.json' if method=='rsi' else 'client_environment.tar.gz'
            (old/client).write_bytes(b'pinned client')
            hashes={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}
            write(old/'manifest.json',dict(method=method,samples_sha256=sha256(old/'samples.json'),
                  source_hashes=hashes,method_settings={'max_tokens':'unchanged'}))
            old_hashes={p:sha256(p) for p in old.rglob('*') if p.is_file()}
            with patch.object(recovery,'EXPECTED',{'cvbench':4}):
                recovery.recover(old,new,method)
            inherited=recovery.read(new/'inherited_records.json')
            assert set(inherited)=={'cvbench_1','cvbench_2'}
            assert inherited['cvbench_1']['terminal']=='empty_answer'
            manifest=recovery.read(new/'recovery_manifest.json')
            assert manifest['retry_failures']==[ids[2]] and manifest['previously_unfinished']==[ids[3]]
            assert manifest['pending']==ids[2:]
            assert not (new/'media_cache').exists() and not (new/'prepared/media').exists()
            assert all(sha256(p)==digest for p,digest in old_hashes.items())
            assert (new/'frozen_repo/model.py').read_text()=='unchanged model source'


if __name__=='__main__':
    lifetime()
    recovery_contract()
    for method, tag in [('rsi','rsi_full_35b_recovery_20261017'),
                        ('lenswalk','lenswalk_full_35b_audit_recovery_20261017')]:
        path=Path('/runs/devbox')/tag/'frozen_repo/eval/external_methods/lenswalk_full.py'
        recovery.patch_driver(path.read_text())
    print('Temporary media survives the client and is removed on success/failure; recovery preserves negatives and source identities; both actual frozen drivers patch cleanly')
