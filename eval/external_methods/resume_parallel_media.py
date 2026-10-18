"""Resume both frozen external methods with eight media preparation slots."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_full import ADAPTERS, EXPECTED, now, read
from recover_temp_media import load_rows


def parallel_driver(source):
    before = 'media_gate=threading.Semaphore(2)'
    assert source.count(before) == 1
    result = source.replace(before, 'media_gate=threading.Semaphore(8)')
    compile(result, '<eight-slot driver>', 'exec')
    return result


def resume(previous, output, method):
    assert not output.exists(), 'Never overwrite a result directory'
    receipt = read(previous/'SCHEDULING_STOPPED.json')
    assert receipt['sandbox_exit_code'] is not None, 'Old executor must be stopped first'
    original = read(previous/'manifest.json')
    assert original['simultaneous_media_preparations'] == 2
    assert original.get('method', 'lenswalk') == method
    ids = read(previous/'samples.json')
    assert len(ids) == len(set(ids)) == sum(EXPECTED.values())
    assert sha256(previous/'samples.json') == original['samples_sha256']
    rows, evidence = load_rows(previous, method)
    assert set(rows) <= set(ids)
    # Already retried engineering failures are outcomes too; do not repeat them again.
    pending = [sid for sid in ids if sid not in rows]
    completed_keys = {sid.replace(':','_') for sid in rows}
    orphaned = [str(p) for pattern in ('*/attempt-*/result.json', '*/attempt-*.tar', '*/attempt-*.tar.gz')
                for p in (previous/method).glob(pattern)
                if p.relative_to(previous/method).parts[0] not in completed_keys]
    assert not orphaned, f'Preserve completed uncommitted attempts before resuming: {orphaned}'
    output.mkdir(parents=True)
    frozen = output/'frozen_repo'
    shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    driver = frozen/'eval/external_methods/lenswalk_full.py'
    assert sha256(driver) == original['driver_sha256']
    driver.write_text(parallel_driver(driver.read_text()))
    commit = (ADAPTERS.parents[1]/'.git/HEAD').read_text().strip()
    (frozen/'.git/HEAD').write_text(commit+'\n')
    for name in ('resume_parallel_media.py','test_parallel_media.py'):
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    files = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with ThreadPoolExecutor(max_workers=16) as pool:
        hashes = dict(zip((str(p.relative_to(frozen)) for p in files), pool.map(sha256,files)))
    changed = {'eval/external_methods/lenswalk_full.py', '.git/HEAD'}
    assert all(hashes.get(name)==digest for name,digest in original['source_hashes'].items() if name not in changed)
    for name in ('samples.json','prepared/private_labels.json','expected_service.json'):
        (output/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(previous/name,output/name)
    client = 'client_environment.json' if method=='rsi' else 'client_environment.tar.gz'
    (output/client).symlink_to((previous/client).resolve())
    for name in (method,'episodes'):(output/name).mkdir()
    write(output/'inherited_records.json',{sid.replace(':','_'):row for sid,row in rows.items()})
    write(output/'manifest.json',dict(original,created_at=now(),recovery_from=str(previous),
          recovery_order=pending,recovery_commit=commit,source_snapshot=str(frozen),
          simultaneous_media_preparations=8,driver_sha256=sha256(driver),source_hashes=hashes))
    write(output/'recovery_manifest.json',dict(created_at=now(),previous=str(previous),
          original_manifest_sha256=sha256(previous/'manifest.json'),inherited=evidence,
          pending=pending,retained_infrastructure_failures=[sid for sid,row in rows.items() if row['infrastructure_error']],
          scheduling_change='Only Semaphore(2) -> Semaphore(8); model, media algorithm and cleanup unchanged',
          stopping_receipt=receipt))
    write(output/'progress.json',dict(phase='prepared',expected=len(ids),completed=len(rows),remaining=len(pending),updated_at=now()))
    unique={value['path']:value['sha256'] for value in evidence.values()}
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(lambda pair:sha256(Path(pair[0]))==pair[1],unique.items()))
    print(dict(method=method,inherited=len(rows),pending=len(pending),retained_failures=sum(r['infrastructure_error'] for r in rows.values()),commit=commit),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--method',choices=['rsi','lenswalk'],required=True)
    args=parser.parse_args();resume(args.previous,args.output,args.method)
