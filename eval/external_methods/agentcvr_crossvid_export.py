"""Package the completed original AgentCVR CrossVid run on Modal CPU."""
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import io
from itertools import batched
import json
from pathlib import Path
import tarfile

import modal

app = modal.App('wxu-evolve-agent-agentcvr-crossvid-export-20261018')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
SOURCE = 'devbox/agentcvr_crossvid_20261017_r2'
DESTINATION = 'devbox/agentcvr_crossvid_release_20261018'
ARCHIVE = 'agentcvr-crossvid-results-20261018.tar.gz'


@app.function(image=modal.Image.debian_slim(python_version='3.12'), cpu=4, memory=8192,
              timeout=3600, volumes={'/runs': runs})
def package():
    root, out = Path('/runs') / SOURCE, Path('/runs') / DESTINATION
    out.mkdir(parents=True, exist_ok=True)
    read = lambda path: json.loads(path.read_text())
    encode = lambda value: (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if (out / 'bundle.json').exists():
        bundle = read(out / 'bundle.json')
        for entry in bundle['assets']:
            path = out / entry['name']
            assert path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256']
        return bundle
    assert read(root / 'progress.json')['phase'] == 'completed'
    scores = read(root / 'scores.json')
    scored = {row['sample_id']: row for row in scores['rows']}
    items = {row['sample_id']: row for row in read(root / 'items.json')}
    labels = read(root / 'private_labels.json')
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = {r['sample_id']: r for r in pool.map(read, sorted((root / 'records').glob('*.json')))}
    assert len(records) == 2500 and set(records) == set(scored) == set(items) == set(labels)
    summary = read(root / 'analysis_20261018/summary.json')
    assert summary['completed'] == 2500 and summary['status']['infrastructure_error'] == 1
    boundary = read(root / 'boundary_audit.json')
    affected = {v['sample_id'] for v in boundary['violations']}
    error_rows = read(root / 'analysis_20261018/request_error_samples.json')
    errors = {r['sample_id']: r['errors'] for r in error_rows}
    answers = []
    for sid in sorted(records):
        record, score, item, label = records[sid], scored[sid], items[sid], labels[sid]
        answers.append(dict(sample_id=sid, task=label['task'], question=item['query'],
            options=item['options'], model_answer=record['answer'],
            reference_answer=label['row'].get('answer'), scoring_points=label['row'].get('scoring_points'),
            prediction=score.get('prediction'), saved_score=score['score'],
            failure_zero_score=0.0 if record['status'] == 'infrastructure_error' else score['score'],
            status=record['status'], boundary_flag=sid in affected,
            request_errors=errors.get(sid, 0), seconds=record['seconds'],
            raw_file='raw/' + sid.replace(':', '_') + '.json', raw_sha256=record['raw_sha256']))
    assert len(answers) == 2500 and sum(a['boundary_flag'] for a in answers) == 182
    assert sum(a['request_errors'] for a in answers) == 837
    generated = {
        'crossvid.answers.jsonl': ''.join(json.dumps(a, ensure_ascii=False) + '\n' for a in answers).encode(),
        'summary.json': encode(summary),
        'request_error_samples.json': encode(error_rows),
    }
    table = io.StringIO(newline='')
    writer = csv.writer(table)
    writer.writerow(['task', 'questions', 'scored', 'failure_zero_score', 'exclude_failure_score', 'boundary_affected'])
    for task, stats in summary['tasks'].items():
        writer.writerow([task, stats['expected'], stats['scored'], stats['failure_zero_score'],
                         stats['exclude_failure_score'], stats['boundary_affected']])
    generated['crossvid.task-scores.csv'] = table.getvalue().encode()
    for name in ('scores.json', 'boundary_audit.json', 'final_audit.json'):
        generated[name] = (root / name).read_bytes()
    generated['README.txt'] = (
        'AgentCVR original released implementation on CrossVid Lite2500.\n'
        'All boundary-affected examples are retained. Ten-task macro with one infrastructure failure '
        'counted as zero: 37.197077%; excluding that failure: 37.219421%.\n'
        '182 examples have boundary flags; 87 have context-length HTTP errors. '
        'This is the original deployed behavior, not a boundary-corrected rerun.\n'
        'saved_score preserves the original score (null for infrastructure failure); '
        'failure_zero_score is a separate reporting convention. CCQA uses scoring-point weights.\n'
        'raw/: original answers, traces, requests/responses and tokens; records/: original raw hashes.\n'
        'metadata/: original inputs, reference labels, configuration, scores and audits. '
        'judge_cache/ and judged/: original Judge artifacts. analysis/: analysis and its source.\n'
        'No videos, weights or frozen execution environment are included. Original Modal files retained.\n'
    ).encode()
    files = []
    for directory in ('raw', 'records', 'judge_cache', 'judged', 'analysis_20261018'):
        files.extend(p for p in (root / directory).rglob('*') if p.is_file())
    files.extend(p for p in root.iterdir() if p.is_file() and p.suffix in ('.json', '.prompt', '.txt'))
    assert sum(p.parent.name == 'raw' for p in files) == 2500
    assert sum(p.parent.name == 'records' for p in files) == 2500
    entries, seen = [], set()
    temporary = out / (ARCHIVE + '.tmp')
    with temporary.open('wb') as stream, gzip.GzipFile(filename='', fileobj=stream, mode='wb',
            compresslevel=1, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w|') as archive:
        def add(name, data, source):
            assert not name.startswith('/') and '..' not in Path(name).parts and name not in seen
            seen.add(name)
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            entries.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source=source))
        with ThreadPoolExecutor(max_workers=16) as pool:
            for batch in batched(sorted(files), 32):
                for path, data in zip(batch, pool.map(Path.read_bytes, batch)):
                    assert not path.is_symlink()
                    relative = str(path.relative_to(root))
                    name = ('metadata/' + relative if path.parent == root else
                            relative.replace('analysis_20261018/', 'analysis/', 1))
                    add(name, data, SOURCE + '/' + relative)
                    if path.parent.name == 'raw':
                        assert entries[-1]['sha256'] == records[json.loads(data)['sample_id']]['raw_sha256']
                if len(entries) % 512 < 32:
                    print(json.dumps({'packaged_files': len(entries)}), flush=True)
        for name, data in generated.items():
            add(name, data, 'derived export; original scores retained under metadata/')
            if name != 'README.txt':
                (out / name).write_bytes(data)
        manifest = dict(source_volume='wxu-evolve-agent-runs-20261006', source_root=SOURCE,
            source_preserved=True, samples=2500, files=entries.copy())
        add('transfer_manifest.json', encode(manifest), 'export manifest')
    temporary.replace(out / ARCHIVE)
    expected = {e['path']: e for e in entries}
    checked = set()
    with tarfile.open(out / ARCHIVE, 'r|gz') as archive:
        for member in archive:
            assert member.isfile() and member.name in expected and member.name not in checked
            entry = expected[member.name]
            assert member.size == entry['bytes']
            with archive.extractfile(member) as data:
                assert hashlib.file_digest(data, 'sha256').hexdigest() == entry['sha256']
            checked.add(member.name)
    assert checked == set(expected)
    names = [ARCHIVE] + [name for name in generated if name != 'README.txt']
    bundle = dict(volume_root=DESTINATION, samples=2500, files=len(entries),
        uncompressed_payload_bytes=sum(e['bytes'] for e in entries), verified_all_members=True,
        assets=[dict(name=n, bytes=(out/n).stat().st_size, sha256=digest(out/n)) for n in names])
    (out / 'bundle.json').write_bytes(encode(bundle))
    runs.commit()
    return bundle


@app.local_entrypoint()
def main():
    print(json.dumps(package.remote(), indent=2))
