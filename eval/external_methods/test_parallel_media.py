"""Remote CPU regression for an eight-slot frozen continuation without rerunning failures."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from common import write,sha256
import resume_parallel_media as run


def main():
    for method,tag in [('rsi','rsi_full_35b_temp_20261018'),('lenswalk','lenswalk_full_35b_temp_20261018')]:
        source=(Path('/runs/devbox')/tag/'frozen_repo/eval/external_methods/lenswalk_full.py').read_text()
        target=run.parallel_driver(source)
        assert target.replace('media_gate=threading.Semaphore(8)','media_gate=threading.Semaphore(2)')==source
        scope={'threading':threading}
        exec(next(line.strip() for line in target.splitlines() if 'media_gate=threading.Semaphore' in line),scope)
        barrier=threading.Barrier(8,timeout=5)
        def enter(_):
            with scope['media_gate']:return barrier.wait()
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sorted(pool.map(enter,range(8)))==list(range(8))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';new=root/'new';frozen=old/'frozen_repo'
            write(frozen/'.git/HEAD','old')
            driver=frozen/'eval/external_methods/lenswalk_full.py';driver.parent.mkdir(parents=True);driver.write_text(source)
            (frozen/'model.py').write_text('unchanged model')
            ids=['cvbench:1','cvbench:2','cvbench:3','cvbench:4']
            write(old/'samples.json',ids);write(old/'prepared/private_labels.json',{})
            write(old/'expected_service.json',{'execution':'unchanged','weights_manifest':'unchanged'})
            write(old/'SCHEDULING_STOPPED.json',{'sandbox_exit_code':137})
            def row(sid,terminal,failed=False):return dict(sample_id=sid,terminal=terminal,infrastructure_error=failed,answer='',score=None if failed else 0)
            write(old/'inherited_records.json',{'cvbench_1':row(ids[0],'invalid_decision')})
            write(old/method/'cvbench_2/record.json',row(ids[1],'engineering_error',True))
            write(old/method/'cvbench_3/record.json',row(ids[2],'finish'))
            (old/('client_environment.json' if method=='rsi' else 'client_environment.tar.gz')).write_bytes(b'pinned')
            hashes={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}
            write(old/'manifest.json',dict(method=method,simultaneous_media_preparations=2,
                  driver_sha256=sha256(driver),samples_sha256=sha256(old/'samples.json'),source_hashes=hashes,
                  method_settings={'max_tokens':'unchanged'}))
            before={p:sha256(p) for p in old.rglob('*') if p.is_file()}
            with patch.object(run,'EXPECTED',{'cvbench':4}):run.resume(old,new,method)
            assert set(run.read(new/'inherited_records.json'))=={'cvbench_1','cvbench_2','cvbench_3'}
            assert run.read(new/'recovery_manifest.json')['pending']==[ids[3]]
            assert run.read(new/'recovery_manifest.json')['retained_infrastructure_failures']==[ids[1]]
            assert all(sha256(p)==digest for p,digest in before.items())
            assert run.read(new/'manifest.json')['simultaneous_media_preparations']==8
    print('Both actual frozen drivers changed only 2 to 8; eight preparations enter concurrently; inherited failures and normal negatives are not rerun; old files unchanged')


if __name__=='__main__':main()
