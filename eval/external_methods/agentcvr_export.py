"""Package the completed AgentCVR results on Modal CPU for Lightsail transfer."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import gzip
import io
from itertools import batched
import json
from pathlib import Path
import tarfile
import time

import modal

app = modal.App('wxu-evolve-agent-agentcvr-export-20261017')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
SOURCE = 'devbox/agentcvr_eval_h100_20261016_r2'
DESTINATION = 'devbox/agentcvr_lightsail_export_20261017'


@app.function(image=modal.Image.debian_slim(python_version='3.12'), cpu=2, memory=4096,
              timeout=3600, volumes={'/runs': runs})
def package():
    root, output = Path('/runs') / SOURCE, Path('/runs') / DESTINATION
    output.mkdir(parents=True, exist_ok=True)
    def read(path):
        return json.loads(path.read_text())
    def encode(value):
        return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    if (output / 'bundle.json').exists():
        result = read(output / 'bundle.json')
        assert (output / 'results.tar').stat().st_size == result['bytes']
        return result
    progress = read(root / 'progress.json')
    assert progress['phase'] == 'completed' and progress['completed'] == 2821
    assert read(root / 'final_audit.json')['phase'] == 'passed'
    items = {x['sample_id']: x for x in read(root / 'items.json')}
    labels = read(root / 'private_labels.json')
    scores = read(root / 'scores.json')
    scored = {x['sample_id']: x for x in scores['rows']}
    records = {x['sample_id']: x for x in (read(p) for p in sorted((root / 'records').glob('*.json')))}
    assert len(records) == 2821 and set(records) == set(items) == set(scored)
    answers = {'cvbench': [], 'mvu_eval': []}
    for sid, item in items.items():
        record, score = records[sid], scored[sid]
        answers[item['dataset']].append(dict(sample_id=sid, task=labels[sid]['task'],
            question=item['query'], model_answer=record['answer'], reference_answer=score['answer'],
            official_prediction=score['prediction'], official_score=score['score'], status=record['status'],
            seconds=record['seconds'], raw_file='raw/' + sid.replace(':', '_') + '.json',
            raw_sha256=record['raw_sha256']))
    for dataset, expected in [('cvbench', 997), ('mvu_eval', 1824)]:
        assert len(answers[dataset]) == expected
        assert sum(r['official_score'] for r in answers[dataset]) == scores['datasets'][dataset]['correct']

    entries = []
    transfer = dict(created=time.time(), source_volume='wxu-evolve-agent-runs-20261006',
        source_root=SOURCE, source_preserved=True, samples=2821, raw_files=2821, record_files=2821,
        excluded='media, weights, frozen execution environment, old H200/failed runs', files=entries)
    temporary = output / 'results.tar.tmp'
    with tarfile.open(temporary, 'w') as archive:
        def add(name, data, source):
            assert not name.startswith('/') and '..' not in Path(name).parts
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            entry = dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source=source)
            entries.append(entry)
            return entry
        files = sorted((root / 'raw').glob('*.json')) + sorted((root / 'records').glob('*.json'))
        assert len(files) == 5642
        with ThreadPoolExecutor(max_workers=8) as readers:
            for batch in batched(files, 16):
                for path, data in zip(batch, readers.map(Path.read_bytes, batch)):
                    relative = str(path.relative_to(root))
                    entry = add(relative, data, SOURCE + '/' + relative)
                    if path.parent.name == 'raw':
                        sid = json.loads(data)['sample_id']
                        assert entry['sha256'] == records[sid]['raw_sha256'], sid
                if len(entries) % 512 == 0:
                    print(json.dumps({'packaged_files': len(entries)}), flush=True)
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix in ('.json', '.prompt'):
                add('metadata/' + path.name, path.read_bytes(), SOURCE + '/' + path.name)
        for dataset, rows in answers.items():
            data = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode()
            add('answers/' + dataset + '.jsonl', data, 'derived from original records and official scores')
        add('summary.json', encode(scores['datasets']), SOURCE + '/scores.json:datasets')
        transfer_bytes = encode(transfer)
        info = tarfile.TarInfo('transfer_manifest.json'); info.size = len(transfer_bytes); info.mode = 0o644
        archive.addfile(info, io.BytesIO(transfer_bytes))
    temporary.replace(output / 'results.tar')
    (output / 'transfer_manifest.json').write_bytes(transfer_bytes)
    result = dict(volume_path=DESTINATION + '/results.tar', bytes=(output / 'results.tar').stat().st_size,
        sha256=digest(output / 'results.tar'), manifest_sha256=hashlib.sha256(transfer_bytes).hexdigest(),
        files=len(entries) + 1, payload_bytes=sum(x['bytes'] for x in entries) + len(transfer_bytes), samples=2821)
    (output / 'bundle.json').write_bytes(encode(result))
    runs.commit()
    return result


@app.function(image=modal.Image.debian_slim(python_version='3.12'), cpu=2, memory=2048,
              timeout=1800, volumes={'/runs': runs})
def compress_archive():
    output = Path('/runs') / DESTINATION
    bundle = json.loads((output / 'bundle.json').read_text())
    source = output / 'results.tar'
    assert source.stat().st_size == bundle['bytes']
    temporary = output / 'results.tar.gz.tmp'
    digest = hashlib.sha256()
    with source.open('rb') as stream, temporary.open('wb') as destination:
        with gzip.GzipFile(filename='', mode='wb', fileobj=destination, compresslevel=1, mtime=0) as compressed:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                compressed.write(block)
    assert digest.hexdigest() == bundle['sha256']
    target = output / 'results.tar.gz'
    temporary.replace(target)
    with target.open('rb') as stream:
        result = dict(volume_path=DESTINATION + '/results.tar.gz', bytes=target.stat().st_size,
                      sha256=hashlib.file_digest(stream, 'sha256').hexdigest(),
                      uncompressed_bytes=bundle['bytes'], uncompressed_sha256=bundle['sha256'])
    (output / 'release_asset.json').write_text(json.dumps(result, indent=2) + '\n')
    runs.commit()
    return result


@app.local_entrypoint()
def main(compress: bool = False):
    print(json.dumps(compress_archive.remote() if compress else package.remote(), indent=2))
