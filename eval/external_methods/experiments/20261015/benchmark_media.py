"""Paired media-only timing; compare exact ordered image bytes and timestamps."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = Path('/runs/devbox/external_methods_current_20261014_r2/frozen_repo')


def load_services(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(output):
    deadline = time.monotonic()+1200
    for port in (8100, 8101):
        while True:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2):
                    break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError('Models must finish initialization before CPU timing')
                time.sleep(5)
    output.mkdir(parents=True, exist_ok=False)
    sources = output/'sources'
    shutil.copytree(BASE/'external_sources/Video-RSI', sources/'rsi')
    patch = Path(__file__).with_name('rsi_parallel.patch')
    shutil.copyfile(patch, output/'rsi_parallel.patch')
    with patch.open() as stream:
        subprocess.run(['patch', '-p1'], cwd=sources/'rsi', stdin=stream, check=True)
    baseline = load_services(BASE/'external_sources/Video-RSI/solver_full_workspace/engine/services.py', 'rsi_baseline')
    parallel = load_services(sources/'rsi/solver_full_workspace/engine/services.py', 'rsi_parallel')
    os.environ['FRAME_STORE_PATH'] = str(output/'unused_memory.sqlite3')
    sys.path.insert(0, str(BASE/'external_sources/Visual-Agentic-Memory'))
    from vam.video import extract_data_uris_ffmpeg
    items = json.loads(Path('/runs/devbox/external_methods_native_20261014/prepared_r2/items.json').read_text())
    panel = {}
    for dataset in ('crossvid', 'cvbench', 'mvu_eval'):
        group = sorted([r for r in items if r['sample_id'].startswith(dataset+':') and r['duration'] <= 300],
                       key=lambda row: row['duration'])
        for item in (group[0], group[len(group)//2]):
            panel[item['sample_id']] = item
    (output/'panel.json').write_text(json.dumps(list(panel.values()), indent=2))
    results, signatures = [], {}
    for method in ('rsi', 'vam'):
        for sid, item in panel.items():
            for repeat, variants in enumerate((('baseline', 'candidate'), ('candidate', 'baseline'))):
                for variant in variants:
                    directory = output/method/sid.replace(':', '_')/f'{repeat}_{variant}'
                    directory.mkdir(parents=True)
                    started = time.monotonic()
                    if method == 'rsi':
                        config = json.loads((BASE/'external_sources/Video-RSI/config.example.json').read_text())
                        config['services']['ffmpeg'] = 'ffmpeg'
                        module = baseline if variant == 'baseline' else parallel
                        services = module.Services(item, {'video_path': item['video_path']}, config, directory,
                                                   provider=module.OfflineProvider())
                        sampled = services.sample(dict(start=0, end=item['duration'], count=32))
                        fingerprint = [(f['timestamp'], hashlib.sha256(services.frames[f['id']]['path'].read_bytes()).hexdigest())
                                       for f in sampled]
                    else:
                        original_run = subprocess.run
                        def limited(command, *args, **kwargs):
                            if Path(command[0]).name == 'ffmpeg':
                                command = list(command)
                                index = command.index('-i')
                                command[index:index] = ['-threads', '2']
                                command[-1:-1] = ['-threads', '1', '-filter_threads', '1']
                            return original_run(command, *args, **kwargs)
                        tempfile.tempdir = str(directory)
                        if variant == 'candidate':
                            subprocess.run = limited
                        try:
                            frames, _, _, _ = extract_data_uris_ffmpeg(item['video_path'], .5, None, 20., 20., .92, 0.)
                        finally:
                            subprocess.run = original_run
                        fingerprint = [(t, hashlib.sha256(uri.encode()).hexdigest()) for t, uri in frames]
                    seconds = time.monotonic()-started
                    key = method, sid
                    if key in signatures:
                        assert fingerprint == signatures[key], (key, variant, 'input images changed')
                    else:
                        signatures[key] = fingerprint
                    row = dict(method=method, sample_id=sid, duration=item['duration'], repeat=repeat,
                               variant=variant, seconds=seconds, frames=len(fingerprint), identical=True)
                    results.append(row)
                    (output/'measurements.json').write_text(json.dumps(results, indent=2))
                    print(json.dumps(row), flush=True)
    summary = []
    for (method, sid), fingerprint in signatures.items():
        timings = {variant: statistics.median(r['seconds'] for r in results
                   if (r['method'], r['sample_id'], r['variant']) == (method, sid, variant))
                   for variant in ('baseline', 'candidate')}
        summary.append(dict(method=method, sample_id=sid, frames=len(fingerprint), **timings,
                            speedup=timings['baseline']/timings['candidate']))
    (output/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
