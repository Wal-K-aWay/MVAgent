"""Export the saved LensWalk panel in the five-file AgentCVR release layout."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import time

from common import sha256, write

EXPECTED = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}
ARCHIVE = 'lenswalk-results-with-trajectories-20261019.tar.gz'
MEDIA = re.compile(r'data:((?:image|video|audio)/[\w.+-]+);base64,[A-Za-z0-9+/=\r\n]+')
MEMBERS = {'input.jsonl': 'input', 'result.json': 'result', 'requests.jsonl': 'calls',
           'all_conversations.jsonl': 'conversations', 'all_tool_calls.jsonl': 'tool_calls',
           'job.log': 'log', 'timeline.json': 'timeline'}


def redact_media(value):
    if isinstance(value, dict):
        return {k: redact_media(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_media(v) for v in value]
    if isinstance(value, str) and 'data:' in value:
        return MEDIA.sub(lambda m: '[media omitted;mime=' + m[1] + ';data_url_sha256='
                         + hashlib.sha256(m[0].encode()).hexdigest() + ']', value)
    return value


class HashedReader:
    def __init__(self, stream):
        self.stream, self.digest = stream, hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def read_trace(row):
    source = row['raw_archive']
    trace, hashes, seen = {}, {}, set()
    with Path(source['path']).open('rb') as stream:
        reader = HashedReader(stream)
        with tarfile.open(fileobj=reader, mode='r|*') as archive:
            for member in archive:
                if not member.isfile():
                    continue
                relative = str(Path(member.name).relative_to(Path(member.name).parts[0]))
                assert relative in source['files'] and relative not in seen, relative
                seen.add(relative)
                name = Path(member.name).name
                if name not in MEMBERS:
                    continue
                key = MEMBERS[name]
                assert key not in trace, (row['sample_id'], key)
                data = archive.extractfile(member).read()
                digest = hashlib.sha256(data).hexdigest()
                assert digest == source['files'][relative], (row['sample_id'], relative)
                hashes[relative] = digest
                if name.endswith('.jsonl'):
                    value = []
                    for line in data.decode().splitlines():
                        try:
                            value.append(json.loads(line))
                        except json.JSONDecodeError:
                            # Interrupted request logs remain visible rather than being dropped.
                            value.append({'unparsed_line': line})
                elif name.endswith('.json'):
                    value = json.loads(data)
                else:
                    value = data.decode()
                trace[key] = redact_media(value)
        while reader.read(1024 * 1024):
            pass
        assert reader.digest.hexdigest() == source['sha256'], row['sample_id']
    assert seen == set(source['files']), row['sample_id']
    result = trace.get('result')
    if result is None:
        assert row['infrastructure_error'], row['sample_id']
    else:
        assert result['sample_id'] == row['sample_id'] and result['answer'] == row['answer']
        assert len(trace.get('conversations', [])) == 1
        assert trace['conversations'][0]['answer'] == result['answer']
    trace['record'] = {k: v for k, v in row.items() if k not in ('raw_archive', 'worker', 'attempt')}
    trace['source'] = dict(archive=source['path'], sha256=source['sha256'], members=hashes)
    return trace


def export_row(row, label):
    trace = read_trace(row)
    gt = label['sample']['ground_truth']
    if row['task'] == 'CCQA':
        gt = dict(answer=label['reference_answer'], scoring_points=gt)
    return dict(id=row['sample_id'], gt=gt, output=trace.get('result', {}).get('answer'),
                seconds=row['seconds'], trajectory=trace)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def export(root, out):
    assert not out.exists(), 'Use a new export directory; never overwrite an existing bundle'
    progress = json.loads((root/'progress.json').read_text())
    assert progress['phase'] in ('completed', 'completed_with_errors') and progress['judged'] == 239
    summary_sha = sha256(root/'summary.json')
    summary = json.loads((root/'summary.json').read_text())
    rows = {r['sample_id']: r for r in summary['rows']}
    labels = json.loads((root/'prepared/private_labels.json').read_text())
    assert len(rows) == len(summary['rows']) == sum(EXPECTED.values())
    assert set(rows) == set(labels) == set(json.loads((root/'samples.json').read_text()))
    assert Counter(r['dataset'] for r in rows.values()) == EXPECTED
    out.mkdir(parents=True)
    source_dir = out/'export_source'; source_dir.mkdir()
    for name in ('lenswalk_export.py', 'test_lenswalk_export.py'):
        shutil.copy2(Path(__file__).with_name(name), source_dir/name)
    source_commit = (Path(__file__).resolve().parents[2]/'.git/HEAD').read_text().strip()
    (source_dir/'commit.txt').write_text(source_commit+'\n')
    files = out/'files'; files.mkdir()
    completed = 0
    started = time.time()
    for dataset, count in EXPECTED.items():
        selected = [r for sid, r in sorted(rows.items()) if r['dataset'] == dataset]
        with (files/f'{dataset}.jsonl').open('wb') as stream, ThreadPoolExecutor(max_workers=8) as pool:
            # Bound retained traces while reading the 50 GB of original archives.
            for start in range(0, count, 16):
                batch = selected[start:start+16]
                for r, value in zip(batch, pool.map(lambda r: export_row(r, labels[r['sample_id']]), batch)):
                    assert value['id'] == r['sample_id'] and value['seconds'] == r['seconds']
                    wire = encode(value)
                    assert not MEDIA.search(wire.decode()), r['sample_id']
                    stream.write(wire)
                completed += len(batch)
                write(out/'progress.json', dict(phase='exporting', completed=completed, expected=len(rows),
                                               seconds=time.time()-started))
                if completed % 128 < 16:
                    print(f'Exported {completed}/{len(rows)}', flush=True)
    judges = []
    for sid, row in sorted(rows.items()):
        if row['task'] != 'CCQA':
            continue
        judge = json.loads((root/'lenswalk'/sid.replace(':', '_')/'judge.json').read_text())
        points = len(labels[sid]['sample']['ground_truth'])
        assert judge['sample_id'] == sid and judge['status'] == 'ok'
        assert len(judge['coverage']) == len(judge['correctness']) == points
        assert judge['prediction'] == row['answer']
        assert judge['score'] == sum(judge['coverage']) + sum(judge['correctness'])
        assert row['score'] == judge['score']/(2*points)
        judges.append(dict(id=sid, score=row['score'], points=points, coverage=judge['coverage'],
                           correctness=judge['correctness'], status=judge['status'],
                           judge_model=judge['response_model']))
    assert len(judges) == 239
    (files/'ccqa_scores.jsonl').write_bytes(b''.join(map(encode, judges)))
    table = ['| Benchmark | 题数 | 评分方式 | 得分（%） | 有最终答案 | 未收尾 | 空答案 | 工程失败 | 平均Agent用时（秒） | 平均视频准备用时（秒） |',
             '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for dataset, count in EXPECTED.items():
        selected = [r for r in rows.values() if r['dataset'] == dataset]
        score = sum(r['score'] if not r['infrastructure_error'] else 0 for r in selected)/count
        rule = '官方逐题评分平均；工程失败计0'
        if dataset == 'crossvid':
            tasks = summary['benchmarks'][dataset]['task_scores']
            scores = []
            for task in tasks:
                group = [r for r in selected if r['task'] == task]
                scores.append(tasks[task]['score'] if task == 'CCQA' else
                              sum(r['score'] if not r['infrastructure_error'] else 0 for r in group)/len(group))
            assert len(scores) == 10
            score = sum(scores)/10
            rule = '十任务等权macro；工程失败计0；CCQA评分点加权'
        terminal = Counter(r['terminal'] for r in selected)
        table.append(f"| {dataset} | {count} | {rule} | {score*100:.2f} | "
                     f"{terminal['finish']+terminal['natural_text']} | {terminal['unfinished_tool_plan']} | "
                     f"{terminal['empty_answer']} | {sum(r['infrastructure_error'] for r in selected)} | "
                     f"{sum(r['seconds'] for r in selected)/count:.2f} | "
                     f"{sum(r['prepared_seconds'] for r in selected)/count:.2f} |")
    (files/'statistics.md').write_text('\n'.join(table)+'\n')
    entries = [dict(name=p.name, bytes=p.stat().st_size, sha256=sha256(p)) for p in sorted(files.iterdir())]
    assert len(entries) == 5
    write(out/'progress.json', dict(phase='packing', completed=completed, expected=len(rows)))
    target = out/ARCHIVE
    with target.open('wb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb',
            compresslevel=1, mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w|') as archive:
        for entry in entries:
            info = tarfile.TarInfo(entry['name']); info.size = entry['bytes']; info.mode = 0o644
            with (files/entry['name']).open('rb') as data:
                archive.addfile(info, data)
    write(out/'progress.json', dict(phase='verifying', completed=completed, expected=len(rows)))
    checked = []
    with tarfile.open(target, 'r|gz') as archive:
        for member, entry in zip(archive, entries, strict=True):
            assert member.isfile() and member.name == entry['name'] and member.size == entry['bytes']
            with archive.extractfile(member) as data:
                assert hashlib.file_digest(data, 'sha256').hexdigest() == entry['sha256']
            checked.append(member.name)
    assert len(checked) == 5 and sha256(root/'summary.json') == summary_sha
    bundle = dict(source=str(root), summary_sha256=summary_sha, samples=len(rows), ccqa_scores=len(judges),
                  export_commit=source_commit, export_code_sha256=sha256(Path(__file__)),
                  files=entries, archive=dict(name=ARCHIVE, bytes=target.stat().st_size, sha256=sha256(target)),
                  source_archives_verified=len(rows), raw_sources_preserved=True,
                  inline_media='Replaced by MIME type and SHA256 of the original data URL',
                  seconds=time.time()-started)
    write(out/'bundle.json', bundle)
    write(out/'progress.json', dict(phase='completed', completed=completed, expected=len(rows)))
    print(json.dumps(bundle, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    export(args.root, args.output)
