"""CrossVid Lite2500 inputs, native AgentCVR answer parsing, and official metrics."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO), str(REPO / 'src')]
from common import write, sha256
from eval.e2e_eval.harness.common import official_constant, official_function, load_official_module

UPSTREAM = Path('/opt/AgentCVR/agent_system')
SELECTION = Path('/runs/devbox/e2e_full_20261012/9B/selection.json')
COUNTS = {'BU': 232, 'CC': 218, 'CCQA': 239, 'FSA': 616, 'MOC': 155,
          'MSR': 163, 'NC': 334, 'PEA': 261, 'PI': 100, 'PSS': 182}


def read(path):
    return json.loads(Path(path).read_text())


def make_item(task, row):
    """Map the released CrossVid paths/schema to the upstream task entry's inputs."""
    sid = f"crossvid:{task}:{row['id']}"
    item = dict(sample_id=sid, dataset='crossvid', task=task, query=row.get('question', ''),
                options=row.get('options', []), videos=[],
                system=(UPSTREAM / 'prompts' / f'master_{task}.prompt').read_text())
    def video(name, begin=0, end=None):
        return dict(path=str(Path('/assets/crossvid/videos') / name), begin=begin, end=end)
    if task in {'BU', 'CC', 'NC', 'PEA'}:
        begins = row.get('begin', [None] * len(row['videos']))
        ends = row.get('end', [None] * len(row['videos']))
        item['videos'] = [video(name, begins[i] or 0, ends[i]) for i, name in enumerate(row['videos'])]
    elif task in {'FSA', 'CCQA'}:
        item['videos'] = [video(row[key]) for key in ('video A', 'video B')]
        if task == 'FSA':
            template = official_constant(UPSTREAM / 'run_tasks/run_FSA_agent.py', 'GENERIC_GROUNDING_QUERY')
            ref = row['ref_segment']
            item['query'] = (template.format(BEGIN=ref[0], END=ref[1]) + '\n'
                + f'Reference Segment (Video 1): {ref}s\n'
                + f"Video 1 Name: {row['video A']}\nVideo 2 Name: {row['video B']}")
    elif task == 'PI':
        item['query'] = 'Given the Beginning and Ending clips of a movie scene, infer what most likely happened in the middle.'
        item['videos'] = [video(row['video'], *row[key]) for key in ('beginning', 'ending')]
    elif task == 'PSS':
        item['query'] = 'Review these video clips. They are shuffled segments from a single cooking video. Please determine their correct chronological order.'
        keys = sorted(row['segments'], key=lambda x: int(re.sub(r'\D', '', x) or 0))
        # Upstream uses the continuous first-start/last-end envelope, including gaps.
        item['videos'] = [video(row['video'], row['segments'][k][0][0], row['segments'][k][-1][1]) for k in keys]
    else:
        assert task in {'MOC', 'MSR'}
        item['uav'] = {'class_id': row['vid'], 'objects': row['objects']}
    return item


def official_inputs():
    selected = set(read(SELECTION)['crossvid'])
    assert len(selected) == 2500
    items, labels = [], {}
    for task in COUNTS:
        for row in read(Path('/assets/crossvid/QA') / f'{task}.json'):
            sid = f"crossvid:{task}:{row['id']}"
            if sid in selected:
                items.append(make_item(task, row))
                labels[sid] = dict(sample_id=sid, task=task, row=row)
    assert set(labels) == selected and Counter(x['task'] for x in items) == COUNTS
    random.Random(0).shuffle(items)
    return items, labels


def finish_prepare(output, items):
    manifest = read(output / 'manifest.json')
    manifest.update(benchmark_prompts='Unmodified upstream master_<TASK>.prompt and native task queries/options',
        protocol_adaptation='Only released dataset paths/schema mapped; native prompts/executor unchanged',
        scoring='Native AgentCVR answer parser followed by official CrossVid task metrics; raw-format diagnostic separate',
        media='Native independent clips; PSS continuous envelope; FSA filename query retained; UAV native image_folder/bboxes',
        known_upstream_limits='UAV prompts use time arguments while executor requires frame arguments; formatted_query/bbox_info kwargs ignored; retained, not silently fixed',
        selection_sha256=sha256(SELECTION), task_counts=COUNTS, excluded=[],
        assets_sha256={f'crossvid/QA/{t}.json': sha256(Path('/assets/crossvid/QA') / f'{t}.json') for t in COUNTS},
        native_prompt_sha256={t: sha256(UPSTREAM / 'prompts' / f'master_{t}.prompt') for t in COUNTS})
    write(output / 'selection.json', read(SELECTION)['crossvid'])
    write(output / 'manifest.json', manifest)
    write(output / 'smoke_ids.json', [next(x['sample_id'] for x in items if x['task'] == t)
                                     for t in ('FSA', 'MOC', 'CCQA')])


def contexts_for(item, video_processor):
    if 'uav' not in item:
        contexts = []
        for spec in item['videos']:
            _, _, _, fps, frames, duration = video_processor.process_video(
                spec['path'], 1, [(0, 1)], max_length=360, encode=False)
            begin = float(spec['begin'])
            end = float(spec['end']) if spec['end'] is not None else duration
            assert fps > 0 and frames > 0 and end > begin, spec
            contexts.append(dict(path=spec['path'], fps=fps, total_frames=frames,
                duration_seconds=end-begin, clip_begin=begin, clip_end=end))
        return contexts
    objects = re.findall(r'\{(.*?)\}', item['query'])
    obj_map = {tag: f'obj_{k+1}' for k, tag in enumerate(objects)}
    # Published QA embeds the old samples JSON's ordered objects directly; supply that same list.
    def metadata_open(path, *args, **kwargs):
        if str(path).startswith('__sample_schema__/'):
            return io.StringIO(json.dumps([{'moving': item['uav']['objects'], 'unmoving': []}]))
        return open(path, *args, **kwargs)
    prepare = official_function(UPSTREAM / 'run_tasks' / f"run_{item['task']}_agent.py", 'prepare_metadata',
        dict(os=os, json=json, open=metadata_open, frames_dir='/assets/crossvid/uav/frames',
             jsons_dir='/assets/crossvid/uav/bbox', samples_dir='__sample_schema__'))
    contexts = []
    for view in (1, 2):
        path, total, bbox, files = prepare(item['uav']['class_id'], 0, objects, view)
        assert path and total > 0, (item['sample_id'], view)
        contexts.append(dict(type='image_folder', path=path, total_frames=total,
            bbox_data=bbox, image_files=files, obj_map=obj_map, description=f'UAV View {"AB"[view-1]}'))
    return contexts


@lru_cache
def native_parser():
    return load_official_module(UPSTREAM / 'utils/answer_parse.py', 'agentcvr_native_answer_parser',
                               import_root=UPSTREAM)


def score_closed(label, answer):
    parser = native_parser(); task, row = label['task'], label['row']
    raw_text = answer if isinstance(answer, str) else json.dumps(answer)
    if task == 'FSA':
        predicted = parser.parse_json_interval_string(raw_text)
        if not predicted:
            numbers = re.findall(r'([\d]+\.?[\d]*)', raw_text)
            if len(numbers) >= 2:
                predicted = (float(numbers[0]), float(numbers[1]))
        prediction = sorted(predicted) if predicted else None
        iou = official_function(REPO / 'eval/e2e_eval/CrossVid/eval/FSA.py', 'interval_iou')
        score = iou(prediction, row['answer']) if prediction else 0.0
        try:
            raw_score = iou(tuple(map(float, raw_text.split(','))), row['answer'])
        except (ValueError, TypeError):
            raw_score = 0.0
    elif task == 'PSS':
        prediction = parser.parse_agent_output_sort(answer)
        score = float(prediction == row['answer']); raw_score = float(raw_text == row['answer'])
    else:
        function = (parser.parse_agent_output_multi_BU if task == 'BU' else
                    parser.parse_agent_output_json_list if task in {'MOC', 'MSR'} else parser.parse_agent_output_multi)
        prediction = function(answer, len(row['options']))
        truth = parser.extract_correct_list(row['answer'], len(row['options']))
        score = float(bool(truth) and set(prediction) == set(truth))
        expected = ''.join(row['answer']) if task == 'BU' else row['answer']
        raw_score = float(raw_text == expected)
    return dict(prediction=prediction, score=score, raw_format_score=raw_score)


def summarize(output):
    labels = read(output / 'private_labels.json')
    judged = read(output / 'judge_scores.json') if (output / 'judge_scores.json').exists() else {}
    stats = dict(completed=0, valid=0, errors=0, no_answer=0, pending_judge=0, seconds=0,
                 prompt_tokens=0, completion_tokens=0, accuracy=None)
    tasks = {t: dict(expected=n, completed=0, valid=0, scored=0, score_sum=0.0, weight=0) for t, n in COUNTS.items()}
    rows = []
    for path in sorted((output / 'records').glob('*.json')):
        record = read(path); sid = record['sample_id']; label = labels[sid]; task = label['task']
        stats['completed'] += 1; tasks[task]['completed'] += 1; stats['seconds'] += record['seconds']
        for key in ('prompt_tokens', 'completion_tokens'):
            stats[key] += record['usage'].get(key, 0)
        if record['status'] == 'infrastructure_error':
            stats['errors'] += 1
            rows.append(dict(sample_id=sid, task=task, status=record['status'], score=None))
            continue
        stats['valid'] += 1; tasks[task]['valid'] += 1
        no_answer = record['status'] != 'answered'
        stats['no_answer'] += no_answer
        weight = len(label['row']['scoring_points']) if task == 'CCQA' else 1
        scored = (judged.get(sid, {'score': None}) if task == 'CCQA' else score_closed(label, record['answer']))
        if no_answer:
            scored = dict(scored, score=0.0)
        if scored['score'] is None:
            stats['pending_judge'] += 1
        else:
            tasks[task]['scored'] += 1
            tasks[task]['score_sum'] += scored['score'] * weight
            tasks[task]['weight'] += weight
        rows.append(dict(scored, sample_id=sid, task=task, status=record['status'], answer=record['answer']))
    for t in tasks.values():
        t['score'] = t['score_sum'] / t['weight'] if t['weight'] else None
    if all(t['completed'] == t['expected'] and t['scored'] == t['expected'] for t in tasks.values()):
        stats['accuracy'] = sum(t['score'] for t in tasks.values()) / 10
    stats['tasks'] = tasks
    write(output / 'scores.json', dict(datasets={'crossvid': stats}, rows=rows))
    return {'crossvid': stats}


def judge_and_finish(output):
    from eval.e2e_eval.harness.ccqa import judge_outputs
    labels = read(output / 'private_labels.json')
    records = [read(p) for p in sorted((output / 'records').glob('*.json'))]
    assert len(records) == 2500
    pending = [(labels[r['sample_id']], r['answer']) for r in records
               if labels[r['sample_id']]['task'] == 'CCQA' and r['status'] == 'answered']
    write(output / 'progress.json', dict(phase='judging', expected=2500, completed=2500, updated=time.time()))
    starter = None
    try:
        if pending:
            with (output / 'judge_startup.log').open('w') as log:
                starter = subprocess.Popen(['bash', str(REPO / 'eval/agent_eval/serve_ccqa_judge.sh'), '0-7', '8300'],
                    env=dict(os.environ, JUDGE_LOG_DIR=str(output / 'judge_logs')),
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            if starter.wait(timeout=1260) != 0:
                raise RuntimeError('CCQA Judge startup failed')
            # Separate per-sample caches prevent identical prompts racing to overwrite historical verdicts.
            def one(pair, rank):
                sid = pair[0]['sample_id']
                identity, scores = judge_outputs([pair], cache_dir=output / 'judge_cache' / sid.replace(':', '_'),
                    endpoints=[f'http://127.0.0.1:{8300+rank}/v1'], attempts=3, timeout=1860)
                result = scores[sid]
                if result['status'] != 'ok':
                    raise RuntimeError(f'Judge failure: {sid}: {result}')
                write(output / 'judged' / (sid.replace(':', '_') + '.json'), result)
                return sid, result, identity
            def shard(rank):
                return [one(pair, rank) for pair in pending[rank::8]]
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = [result for group in pool.map(shard, range(8)) for result in group]
            write(output / 'judge_scores.json', {sid: result for sid, result, _ in results})
            write(output / 'judge_identity.json', [identity for _, _, identity in results])
        totals = summarize(output)
        audit_records(output)
        write(output / 'progress.json', dict(phase='completed', expected=2500, completed=2500,
            datasets=totals, updated=time.time()))
    except BaseException as exc:
        write(output / 'progress.json', dict(phase='failed', stage='judge_or_final_audit',
            error=f'{type(exc).__name__}: {exc}', expected=2500, completed=2500, updated=time.time()))
        raise
    finally:
        if starter is not None:
            try:
                os.killpg(starter.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def audit_records(output):
    items = {x['sample_id']: x for x in read(output / 'items.json')}
    counts = Counter(); observed = set()
    def check(path):
        record = read(path); sid = record['sample_id']; rawpath = output / 'raw' / path.name
        assert sha256(rawpath) == record['raw_sha256']
        raw = read(rawpath); item = items[sid]
        assert raw['input_sha256'] == hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        for k in ('answer', 'status', 'sample_id'):
            assert raw[k] == record[k]
        local = Counter(samples=1, calls=len(raw['calls']))
        for call in raw['calls']:
            request = call['request']
            assert request['temperature'] == .5 and request['max_tokens'] == 8192 and request['seed'] == 0
            if request['model'] == 'agentcvr-master':
                assert request['messages'][0]['content'] == item['system']
                payload = json.loads(request['messages'][1]['content'][0]['text'])
                assert payload['query'] == item['query'] and payload.get('possible_answers', []) == item['options']
            if call.get('error') or call.get('http_status', 200) >= 400:
                local['http_errors'] += 1
            else:
                response = call['response']; choice = response['choices'][0]; usage = response['usage']
                assert len(response.get('prompt_token_ids') or []) == usage['prompt_tokens']
                assert len(choice.get('token_ids') or []) == usage['completion_tokens']
                local['length_finishes'] += choice['finish_reason'] == 'length'
        return sid, local
    with ThreadPoolExecutor(max_workers=8) as pool:
        for sid, stats in pool.map(check, sorted((output / 'records').glob('*.json'))):
            assert sid not in observed
            observed.add(sid); counts.update(stats)
    assert observed == set(items)
    write(output / 'final_audit.json', dict(phase='passed', **counts, updated=time.time()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['judge', 'audit'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    (judge_and_finish if args.mode == 'judge' else audit_records)(args.output)
