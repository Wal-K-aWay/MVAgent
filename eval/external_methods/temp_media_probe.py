"""Measure original concatenation on a persistent volume versus disposable local disk."""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import threading
import time

from common import sha256, write
from lenswalk_full import ADAPTERS, SOURCE, media_key, now, read
from prepare import prepare

ROOT=Path('/runs/devbox/external_temp_media_20261018')
PREVIOUS=Path('/runs/devbox/rsi_full_35b_recovery_20261017')
SAMPLES=['cvbench:764','mvu_eval:TR:1585','crossvid:PSS:341','crossvid:FSA:394']
LONG='crossvid:NC:80'


def bytes_used(root):
    size=0
    for path in root.rglob('*'):
        try:
            if path.is_file():size+=path.stat().st_size
        except FileNotFoundError:
            pass
    return size


@contextmanager
def peak_usage(paths):
    peak={str(p):0 for p in paths};peak['total']=0;done=threading.Event()
    def sample():
        values={str(path):bytes_used(path) for path in paths}
        for path,value in values.items():peak[path]=max(peak[path],value)
        peak['total']=max(peak['total'],sum(values.values()))
    def monitor():
        while not done.wait(.5):sample()
    sample();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:yield peak
    finally:
        done.set();thread.join();sample()


def media_pair(record, output, keep_volume=False):
    output.mkdir(parents=True,exist_ok=False)
    rows={}
    # Alternate first arm across the fixed panel; filesystem caches are not forcibly dropped.
    order=['volume','local'] if record.sample_id in (SAMPLES[0],SAMPLES[2]) else ['local','volume']
    with tempfile.TemporaryDirectory(prefix='external-media-',dir='/tmp') as temporary:
        local=Path(temporary)
        for arm in order:
            target=output/'volume' if arm=='volume' else local
            target.mkdir(exist_ok=True)
            started=time.monotonic()
            with tempfile.TemporaryDirectory(prefix='external-encoder-',dir='/tmp') as scratch:
                previous_tempdir=tempfile.tempdir
                try:
                    tempfile.tempdir=scratch
                    with peak_usage([target,Path(scratch)]) as peak:
                        item=prepare(replace(record,sample_id='media:'+media_key(record.sample.videos)),target)
                finally:tempfile.tempdir=previous_tempdir
            elapsed=time.monotonic()-started
            path=Path(item['video_path']);meta=read(path.parent/'timeline.json')
            rows[arm]=dict(seconds=elapsed,video_bytes=path.stat().st_size,
                video_sha256=sha256(path),peak_bytes_sampled=peak['total'],
                output_tree_peak_bytes=peak[str(target)],encoder_scratch_peak_bytes=peak[scratch],
                processing=[s['processing'] for s in meta['segments']],
                duration=meta['duration'],video_path=str(path))
            write(output/(arm+'_timeline.json'),meta)
            write(output/(arm+'_measurement.json'),rows[arm])
            if arm=='local':
                shutil.rmtree(local);local.mkdir()
        same=rows['volume']['video_sha256']==rows['local']['video_sha256']
        assert same, 'Media bytes changed; preserve volume output for diagnosis'
    result=dict(sample_id=record.sample_id,order=order,arms=rows,video_bytes_identical=same,
        local_directory_removed=not local.exists(),at=now(),
        measurement='One paired run; per-case 0.5-second sampled output and encoder-scratch peak; excludes original assets')
    if not keep_volume:
        shutil.rmtree(output/'volume')
    result['volume_media_retained']=keep_volume
    write(output/'comparison.json',result)
    return result


def initialize():
    assert not ROOT.exists()
    ROOT.mkdir(parents=True)
    frozen=ROOT/'frozen_repo'
    shutil.copytree(PREVIOUS/'frozen_repo',frozen,ignore=shutil.ignore_patterns('__pycache__'))
    names=('temp_media_probe.py','temp_media_run.py','test_temp_media.py','lenswalk_outcome.py')
    for name in names:shutil.copy2(ADAPTERS/name,frozen/'eval/external_methods'/name)
    old=read(PREVIOUS/'manifest.json')
    changed={'eval/external_methods/'+name for name in names}
    hashes={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert all(hashes.get(name)==digest for name,digest in old['source_hashes'].items() if name not in changed)
    commit=(SOURCE/'.git/HEAD').read_text().strip()
    (frozen/'.git/HEAD').write_text(commit+'\n');hashes['.git/HEAD']=sha256(frozen/'.git/HEAD')
    write(ROOT/'manifest.json',dict(created_at=now(),commit=commit,source_hashes=hashes,
        samples=SAMPLES,long_media_case=LONG,previous=str(PREVIOUS),inference_seed=0,
        policy='Same upstream media and inference parameters; change storage location/lifetime only; no Judge',
        runtime_cards_from=dict(rsi=str(PREVIOUS/'startup_verification.json'),
            lenswalk='/runs/devbox/lenswalk_full_35b_audit_recovery_20261017/startup_verification.json')))
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    records=load_multibench_records('/assets',SAMPLES)
    for sid in SAMPLES:
        record=records[sid]
        result=media_pair(record,ROOT/'media'/sid.replace(':','_'),keep_volume=True)
        write(ROOT/'progress.json',dict(phase='preparing',last_sample=sid))
        print(result,flush=True)
    write(ROOT/'progress.json',dict(phase='prepared',samples=len(SAMPLES),expected_rollouts=4*len(SAMPLES),completed_rollouts=0,at=now()))


def long_probe():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    write(ROOT/'long_progress.json',dict(phase='preparing',sample=LONG,at=now()))
    try:
        result=media_pair(load_multibench_records('/assets',[LONG])[LONG],ROOT/'long_media')
        write(ROOT/'long_progress.json',dict(phase='completed',result=result,at=now()))
        print(result,flush=True)
    except BaseException as exc:
        write(ROOT/'long_progress.json',dict(phase='failed',error=repr(exc),at=now()))
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','long'])
    args=p.parse_args();initialize() if args.mode=='prepare' else long_probe()
