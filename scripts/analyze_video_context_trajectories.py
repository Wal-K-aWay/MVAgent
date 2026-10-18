"""Read-only B/C trajectory comparison; save diagnostics without changing scores."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/runs/devbox/video_context_20261018')
MODELS = ('9B', '27B', '35B-A3B')
read = lambda p: json.loads(p.read_text())


def parsed(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def responses(raw, schema=None):
    return [e for e in raw['events'] if e['kind'] == 'model_response'
            and (schema is None or e.get('schema') == schema)]


def visual_signature(events, field):
    # Group by video/round: thread completion order has no semantic meaning.
    groups = defaultdict(list)
    for event in events:
        groups[(event.get('video_id'), event.get('global_round'))].append(event[field])
    return dict(groups)


def episode(raw):
    calls = responses(raw)
    actions = [e for e in calls if e.get('schema') == 'video_action']
    first_round = min((e['global_round'] for e in actions), default=None)
    first = {}
    for event in actions:
        if event['global_round'] == first_round:
            first.setdefault(event['video_id'], parsed(event['text']))
    visual = [e for e in calls if e.get('schema') == 'visual_observation'
              and e['global_round'] == first_round]
    history = raw['result']['action_history']
    analyze = next((h for h in history if h['action'] == 'analyze_videos'), None)
    reports = {r['video_id']: r.get('report', '') for r in analyze.get('outcomes', [])} if analyze else {}
    length = Counter(e.get('schema') for e in calls if e['finish_reason'] == 'length')
    prompt_tokens = sum(e['usage']['prompt_tokens'] for e in calls)
    return dict(first_round=first_round, first=first, visual=visual, reports=reports,
                length=dict(length), prompt_tokens=prompt_tokens,
                global_actions=[v for e in responses(raw, 'global_decision') if (v := parsed(e['text']))],
                history=history)


def compare(item):
    model, before, after = item
    raws = []
    for row in (before, after):
        payload = Path(row['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == row['sha256']
        raw = json.loads(payload)
        assert raw['status'] == 'ok'
        raws.append(raw)
    b, c = map(episode, raws)
    first_global = [responses(r, 'global_decision')[0] for r in raws]
    same_global_input = first_global[0]['request_sha256'] == first_global[1]['request_sha256']
    same_global_output = first_global[0]['token_ids'] == first_global[1]['token_ids']
    common = set(b['first']) & set(c['first'])
    changes = Counter()
    for video in common:
        x, y = b['first'][video], c['first'][video]
        if x != y:
            changes['action_json'] += 1
        if not x or not y or x['action'] != 'observe' or y['action'] != 'observe':
            changes['not_two_observes'] += 1
            continue
        for field in ('what', 'where', 'fps'):
            changes[field] += x['parameters'][field] != y['parameters'][field]
    visual_equal = visual_signature(b['visual'], 'request_sha256') == visual_signature(c['visual'], 'request_sha256')
    outputs_equal = visual_signature(b['visual'], 'token_ids') == visual_signature(c['visual'], 'token_ids')
    if not b['visual'] and not c['visual']:
        stage = 'no_first_round_visual'
    elif not visual_equal:
        stage = 'first_round_observation_changed'
    elif not outputs_equal:
        stage = 'same_visual_request_different_output'
    elif b['reports'] != c['reports']:
        stage = 'report_changed_same_first_round_visual'
    else:
        stage = 'first_round_evidence_and_reports_same'
    matched = Counter()
    by_hash = defaultdict(list)
    for e in responses(raws[0]):
        by_hash[e['request_sha256']].append(e)
    for e in responses(raws[1]):
        for old in by_hash.get(e['request_sha256'], []):
            matched['pairs'] += 1
            matched['different_prompt_tokens'] += old['prompt_token_ids_sha256'] != e['prompt_token_ids_sha256']
            matched['different_output_tokens'] += old['token_ids'] != e['token_ids']
    scores = [r['arms']['direct']['score'] for r in (before, after)]
    result = dict(model=model, sample_id=before['sample_id'], dataset=before['dataset'], task=before['task'],
        B=scores[0], C=scores[1], outcome='win' if scores[1] > scores[0] else 'loss' if scores[1] < scores[0] else 'tie',
        first_global_same_input=same_global_input, first_global_same_output=same_global_output,
        stage=stage, first_action_changes=dict(changes), matched_requests=dict(matched),
        question=raws[0]['result']['input']['question'])
    for arm, detail, raw, row in zip(('B', 'C'), (b, c), raws, (before, after)):
        result[arm + '_detail'] = {**{k:v for k,v in detail.items() if k != 'visual'},
            'visual': [dict(video=e['video_id'], schema=e['schema'], text=e['text'], request_sha256=e['request_sha256']) for e in detail['visual']],
            'answer': raw['prediction'], 'path': row['path'], 'sha256': row['sha256']}
    return result


def self_check():
    a = [dict(video_id='v1',global_round=1,text='a'),dict(video_id='v2',global_round=1,text='b')]
    assert visual_signature(a, 'text') == visual_signature(a[::-1], 'text')
    assert parsed('{"action":"finish"}') == {'action':'finish'}
    assert parsed('{"action":') is None


def main():
    self_check()
    items = []
    for model in MODELS:
        b = {r['sample_id']:r for r in read(ROOT/'analysis'/f'boundary_only_{model}_paired.json')}
        c = read(ROOT/'analysis'/f'with_question_{model}_paired.json')
        assert len(b) == len(c) == 102 and set(b) == {r['sample_id'] for r in c}
        items.extend((model, b[r['sample_id']], r) for r in c)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(compare, items))
    output = ROOT/'analysis/trajectories'
    output.mkdir(exist_ok=False)
    (output/'analysis_source.py').write_text(Path(__file__).read_text())
    summary = {}
    for model in MODELS:
        subset = [r for r in rows if r['model'] == model]
        report = dict(n=len(subset), outcomes=dict(Counter(r['outcome'] for r in subset)),
            stages={o:dict(Counter(r['stage'] for r in subset if r['outcome']==o)) for o in ('win','loss','tie')},
            first_global_input_differences=sum(not r['first_global_same_input'] for r in subset),
            first_global_output_differences=sum(not r['first_global_same_output'] for r in subset),
            parameter_changed_questions={k:sum(r['first_action_changes'].get(k,0)>0 for r in subset) for k in ('what','where','fps')},
            prompt_tokens={a:sum(r[a+'_detail']['prompt_tokens'] for r in subset) for a in ('B','C')},
            matched_requests=dict(sum((Counter(r['matched_requests']) for r in subset),Counter())),
            changed=[{k:r[k] for k in ('sample_id','dataset','B','C','outcome','stage','first_action_changes')} for r in subset if r['outcome']!='tie'])
        summary[model] = report
        (output/f'{model}.json').write_text(json.dumps(subset,ensure_ascii=False,indent=2))
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == '__main__':
    self_check() if '--self-check' in sys.argv else main()
