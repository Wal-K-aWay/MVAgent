"""Export saved LensWalk or Video-RSI panels in the five-file AgentCVR layout."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time

from common import sha256, write

EXPECTED = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}
MEDIA = re.compile(r'data:((?:image|video|audio)/[\w.+-]+);base64,[A-Za-z0-9+/=\r\n]+')
MEMBERS = {'input.jsonl': 'input', 'result.json': 'result', 'requests.jsonl': 'calls',
           'all_conversations.jsonl': 'conversations', 'all_tool_calls.jsonl': 'tool_calls',
           'item.json': 'item'}


def source_metadata(root, method):
    read = lambda p: json.loads(p.read_text())
    manifest = read(root/'manifest.json')
    assert manifest.get('method', method) == method
    children = [Path(c['root']) for c in manifest['children']] if 'children' in manifest else [root]
    owners, paths, labels_hash = {}, {root/'manifest.json', root/'samples.json', root/'summary.json'}, None
    for child in children:
        files = [child/name for name in ('manifest.json', 'samples.json', 'prepared/private_labels.json',
                                        'expected_service.json')]
        paths.update(files)
        digest = sha256(files[2])
        assert labels_hash is None or digest == labels_hash, 'Partitions disagree on labels'
        labels_hash = digest
        expected = read(files[3])
        assert expected['execution']['profile'] == {
            'rsi': 'qwen35-bf16-external-upstream', 'lenswalk': 'qwen35-bf16-lenswalk-tools'}[method]
        for sid in read(child/'samples.json'):
            assert sid not in owners, 'Duplicate question ownership'
            owners[sid] = child/'judgements'/(sid.replace(':', '_')+'.json') if 'children' in manifest else (
                child/method/sid.replace(':', '_')/'judge.json')
    assert set(owners) == set(read(root/'samples.json'))
    labels = read(children[0]/'prepared/private_labels.json')
    assert set(labels) == set(owners)
    hashes = {os.path.relpath(p, root): sha256(p) for p in paths}
    return labels, owners, hashes


def export_score(row, label, judge):
    points = len(label['sample']['ground_truth'])
    if row['infrastructure_error']:
        assert judge is None and row['score'] is None
        return dict(id=row['sample_id'], score=None, points=points, coverage=None, correctness=None,
                    status='infrastructure_error', judge_model=None, error=row.get('error'))
    assert judge['sample_id'] == row['sample_id'] and judge['status'] == 'ok'
    assert len(judge['coverage']) == len(judge['correctness']) == points
    assert judge['prediction'] == row['answer']
    assert judge['score'] == sum(judge['coverage']) + sum(judge['correctness'])
    assert row['score'] == judge['score']/(2*points)
    return dict(id=row['sample_id'], score=row['score'], points=points, coverage=judge['coverage'],
                correctness=judge['correctness'], status=judge['status'], judge_model=judge['response_model'])


def score_with_failures(rows, labels):
    weights = [len(labels[r['sample_id']]['sample']['ground_truth']) if r['task']=='CCQA' else 1 for r in rows]
    return sum((r['score'] if not r['infrastructure_error'] else 0)*w for r, w in zip(rows, weights))/sum(weights)


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


def call_summary(call):
    response = call.get('response') or {}
    usage = response.get('usage') or {}
    return dict(seconds=call.get('seconds'), http_status=call.get('http_status'),
                error=call.get('error'), model=response.get('model'),
                input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens'),
                finish_reasons=[choice.get('finish_reason') for choice in response.get('choices', [])])


def read_trace(row):
    source = row['raw_archive']
    trace, seen = {}, set()
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
                if name.endswith('.jsonl'):
                    value = []
                    for line in data.decode().splitlines():
                        try:
                            parsed = json.loads(line)
                            value.append(call_summary(parsed) if key == 'calls' else parsed)
                        except json.JSONDecodeError:
                            # Interrupted request logs remain visible rather than being dropped.
                            value.append({'error': 'malformed_saved_jsonl',
                                          'line_sha256': hashlib.sha256(line.encode()).hexdigest()})
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
        assert result['sample_id'] == row['sample_id']
        if 'status' in result:  # RSI's scorer stores null answers as empty strings; export the original null.
            assert (result['answer'] or '') == row['answer']
            assert ('finish' if result['status'] == 'answered' else result['status']) == row['terminal']
        else:
            assert result['answer'] == row['answer']
            assert len(trace.get('conversations', [])) == 1
            assert trace['conversations'][0]['answer'] == result['answer']
    return trace


def export_row(row, label):
    trace = read_trace(row)
    gt = label['sample']['ground_truth']
    if row['task'] == 'CCQA':
        gt = dict(answer=label['reference_answer'], scoring_points=gt)
    conversation = trace.get('conversations', [{}])[0]
    trajectory = dict(question=trace.get('input', [{}])[0].get('question'),
                      messages=conversation.get('chat_history', []), tools=trace.get('tool_calls', []),
                      calls=trace.get('calls', []), source_archive_sha256=row['raw_archive']['sha256'])
    result = trace.get('result', {})
    if 'status' in result:
        trajectory.pop('messages'); trajectory.pop('tools')
        trajectory.update(steps=result.get('trace', []), services=result.get('service_trace', []),
                          diagnostics=result.get('diagnostics', {}), usage=result.get('usage', {}))
        item = trace.get('item')
        if item is None:
            for service in result.get('service_trace', []):
                if service['service'] == 'deepseek':
                    payload = json.loads(service['arguments']['messages'][1]['content'])
                    candidate = payload.get('item', payload)
                    if 'question' in candidate:
                        item = candidate
                        break
        trajectory['question'] = item.get('question') if item else None
    for key in ('terminal', 'infrastructure_error', 'http_errors', 'tool_errors', 'question_timeout',
                'prepared_seconds', 'archive_seconds', 'score', 'error'):
        trajectory[key] = row.get(key)
    return dict(id=row['sample_id'], gt=gt, output=trace.get('result', {}).get('answer'),
                seconds=row['seconds'], trajectory=trajectory)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def encode_row(pair):
    row, label = pair
    value = export_row(row, label)
    assert value['id'] == row['sample_id'] and value['seconds'] == row['seconds']
    wire = encode(value)
    assert not MEDIA.search(wire.decode()), row['sample_id']
    return wire


def saved_prefix(path, selected, labels):
    if not path.exists():
        return 0
    count = 0
    with path.open('rb+') as stream:
        while True:
            offset = stream.tell(); line = stream.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                # A preempted append may leave only the final line incomplete.
                stream.truncate(offset)
                break
            value = json.loads(line); row = selected[count]; label = labels[row['sample_id']]
            gt = label['sample']['ground_truth']
            if row['task'] == 'CCQA':
                gt = dict(answer=label['reference_answer'], scoring_points=gt)
            assert set(value) == {'id', 'gt', 'output', 'seconds', 'trajectory'}
            assert value['id'] == row['sample_id'] and value['gt'] == gt and value['seconds'] == row['seconds']
            assert value['output'] == row['answer'] or (value['output'] is None and
                row['terminal'] in ('invalid_decision', 'engineering_error', 'missing_result', 'execution_error')
                and not row['answer'])
            assert value['trajectory']['source_archive_sha256'] == row['raw_archive']['sha256']
            assert value['trajectory']['terminal'] == row['terminal']
            count += 1
    return count


def export(root, out, method, archive_name):
    assert Path(archive_name).name == archive_name and archive_name.endswith('.tar.gz')
    progress = json.loads((root/'progress.json').read_text())
    assert progress['phase'] in ('completed', 'completed_with_errors') and progress['completed'] == 5321
    summary_sha = sha256(root/'summary.json')
    labels, judge_paths, source_hashes = source_metadata(root, method)
    summary = json.loads((root/'summary.json').read_text())
    rows = {r['sample_id']: r for r in summary['rows']}
    assert len(rows) == len(summary['rows']) == sum(EXPECTED.values())
    assert set(rows) == set(labels) == set(json.loads((root/'samples.json').read_text()))
    assert Counter(r['dataset'] for r in rows.values()) == EXPECTED
    if (out/'bundle.json').exists():
        bundle = json.loads((out/'bundle.json').read_text())
        assert bundle['source'] == str(root) and bundle['summary_sha256'] == summary_sha
        assert bundle['method'] == method and bundle['archive']['name'] == archive_name
        for entry in bundle['files']:
            assert sha256(out/'files'/entry['name']) == entry['sha256']
        assert sha256(out/bundle['archive']['name']) == bundle['archive']['sha256']
        write(out/'progress.json', dict(phase='completed', completed=len(rows), expected=len(rows)))
        print(json.dumps(bundle, ensure_ascii=False), flush=True)
        return
    out.mkdir(parents=True, exist_ok=True)
    source_commit = (Path(__file__).resolve().parents[2]/'.git/HEAD').read_text().strip()
    source_dir = out/'export_source'/source_commit; source_dir.mkdir(parents=True, exist_ok=True)
    for name in ('lenswalk_export.py', 'test_lenswalk_export.py'):
        shutil.copy2(Path(__file__).with_name(name), source_dir/name)
    (source_dir/'commit.txt').write_text(source_commit+'\n')
    files = out/'files'; files.mkdir(exist_ok=True)
    completed = 0
    started = time.time()
    for dataset, count in EXPECTED.items():
        selected = [r for sid, r in sorted(rows.items()) if r['dataset'] == dataset]
        path = files/f'{dataset}.jsonl'
        saved = saved_prefix(path, selected, labels)
        completed += saved
        print(f'{dataset}: retained {saved}/{count}', flush=True)
        with path.open('ab') as stream, ProcessPoolExecutor(max_workers=8) as pool:
            # Bound retained traces while reading original archives.
            for start in range(saved, count, 16):
                batch = selected[start:start+16]
                for wire in pool.map(encode_row, [(r, labels[r['sample_id']]) for r in batch]):
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
        judge = None
        if not row['infrastructure_error']:
            path = judge_paths[sid]
            source_hashes[os.path.relpath(path, root)] = sha256(path)
            judge = json.loads(path.read_text())
        judges.append(export_score(row, labels[sid], judge))
    assert len(judges) == 239
    (files/'ccqa_scores.jsonl').write_bytes(b''.join(map(encode, judges)))
    table = ['| Benchmark | 题数 | 评分方式 | 得分（%） | 有最终答案 | 未收尾 | 空答案 | 无效决策 | 工程失败 | 平均Agent用时（秒） | 平均视频准备用时（秒） |',
             '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for dataset, count in EXPECTED.items():
        selected = [r for r in rows.values() if r['dataset'] == dataset]
        score = score_with_failures(selected, labels)
        rule = '官方逐题评分平均；工程失败计0'
        if dataset == 'crossvid':
            tasks = summary['benchmarks'][dataset]['task_scores']
            scores = []
            for task in tasks:
                group = [r for r in selected if r['task'] == task]
                scores.append(score_with_failures(group, labels))
            assert len(scores) == 10
            score = sum(scores)/10
            rule = '十任务等权macro；工程失败计0；CCQA评分点加权'
        terminal = Counter(r['terminal'] for r in selected)
        table.append(f"| {dataset} | {count} | {rule} | {score*100:.2f} | "
                     f"{terminal['finish']+terminal['natural_text']} | {terminal['unfinished_tool_plan']} | "
                     f"{terminal['empty_answer']} | {terminal['invalid_decision']} | {sum(r['infrastructure_error'] for r in selected)} | "
                     f"{sum(r['seconds'] for r in selected)/count:.2f} | "
                     f"{sum(r['prepared_seconds'] for r in selected)/count:.2f} |")
    (files/'statistics.md').write_text('\n'.join(table)+'\n')
    entries = [dict(name=p.name, bytes=p.stat().st_size, sha256=sha256(p)) for p in sorted(files.iterdir())]
    assert len(entries) == 5
    write(out/'progress.json', dict(phase='packing', completed=completed, expected=len(rows)))
    target = out/archive_name
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
    assert all(sha256(root/name) == digest for name, digest in source_hashes.items())
    bundle = dict(source=str(root), summary_sha256=summary_sha, samples=len(rows), ccqa_scores=len(judges),
                  method=method, model=json.loads((root/'manifest.json').read_text()).get('model'),
                  ccqa_judged=sum(j['status']=='ok' for j in judges),
                  ccqa_infrastructure_failures=sum(j['status']=='infrastructure_error' for j in judges),
                  source_hashes=source_hashes,
                  export_commit=source_commit, export_code_sha256=sha256(Path(__file__)),
                  files=entries, archive=dict(name=archive_name, bytes=target.stat().st_size, sha256=sha256(target)),
                  source_archives_verified=len(rows), raw_sources_preserved=True,
                  omitted=['inline media payloads', 'token ID arrays', 'duplicate HTTP request/response bodies', 'job logs'],
                  inline_media='Any remaining inline media is replaced by MIME type and data URL SHA256',
                  seconds=time.time()-started)
    write(out/'bundle.json', bundle)
    write(out/'progress.json', dict(phase='completed', completed=completed, expected=len(rows)))
    print(json.dumps(bundle, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=['rsi', 'lenswalk'], required=True)
    parser.add_argument('--archive-name', required=True)
    args = parser.parse_args()
    export(args.root, args.output, args.method, args.archive_name)
