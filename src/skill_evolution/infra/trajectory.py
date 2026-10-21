"""Role-visible Train views, adapted from de28149's generic trajectory projection.

Use the runtime's public memory renderers; never forward raw model events or GT.
"""
from collections import defaultdict
from copy import deepcopy
import json,random
from mvagent.agents.global_agent.memory import GlobalAgentMemory
from mvagent.agents.video_agent.memory import VideoAgentMemory
from mvagent.utils.io import hash_json


def _selections(row, role, *, video_id=None, request_id=None):
    return [[item['id'] for item in event['selected']] for event in row.get('events', [])
            if event.get('kind') == 'skill_selection' and event.get('role') == role
            and (video_id is None or event.get('video_id') == video_id)
            and (request_id is None or event.get('request_id') == request_id)]


def global_view(row):
    result = row['result']
    memory = GlobalAgentMemory()
    memory.action_history = deepcopy(result['action_history'])
    return {'question': result['input']['question'],
            'videos': {key: {'duration_sec': value['duration_sec']}
                       for key, value in result['video_metadata'].items()},
            'history': memory.render_action_history(),
            'answer': {key: result['answer'][key] for key in ('reason', 'answer') if key in result['answer']},
            'selected_cards': _selections(row, 'global')}


def video_views(row):
    result = row['result']
    memories = defaultdict(VideoAgentMemory)
    for event in result['trajectory']:
        if event.get('agent') != 'VideoAgent':
            continue
        video_id = event['video_id']; output = event['output']
        instruction = event['input']['instruction']
        memory = memories[video_id]
        request = memory.begin_request(instruction)
        prior = memory.render_planner_view(request_id=request)
        context = hash_json({'video_id': video_id, 'instruction': instruction, 'prior_memory': prior})
        actions = []
        for step in output.get('steps', []):
            if step.get('action') == 'observe' and 'result' in step:
                entry = {key: deepcopy(step[key]) for key in ('action', 'parameters', 'result')}
                memory.add_action(entry, request_id=request)
                actions.append({'action': 'observe',
                                'parameters': {k: step['parameters'][k] for k in ('what', 'where', 'fps') if k in step['parameters']},
                                'result': memory._render_action(entry)})
        yield context, {'instruction': instruction,
                        'duration_sec': result['video_metadata'][video_id]['duration_sec'],
                        'prior_memory': prior, 'actions': actions,
                        'report': output.get('report', ''), 'status': output.get('status'),
                        'selected_cards': _selections(row, 'video', video_id=video_id,
                                                     request_id=output.get('request_id'))}


def examples(parent, role, config, *, candidate=None, attempt=0):
    if parent.partition != 'train' or (candidate is not None and candidate.partition != 'train'):
        raise ValueError('Only Train evaluations may supply optimizer examples')
    previous = {row['sample_id']: row for row in parent.train_rows}
    later = {row['sample_id']: row for row in candidate.train_rows} if candidate else {}
    if candidate is not None and set(later) != set(previous):
        raise ValueError('Paired Train evaluations must contain exactly the same questions')
    # Prefer changed/unsolved examples but retain successful references, without task buckets.
    rng = random.Random(config.seed + attempt)
    ids = sorted(previous); rng.shuffle(ids)
    ids.sort(key=lambda sid: (later.get(sid, previous[sid])['score'] == previous[sid]['score'], previous[sid]['score']))
    failures = [sid for sid in ids if previous[sid]['score'] < 1]
    successes = [sid for sid in ids if previous[sid]['score'] == 1]
    chosen = []
    while failures or successes:
        for pool in (failures, failures, successes):
            if pool:
                chosen.append(pool.pop(0))
            if len(chosen) >= config.examples_per_proposal:
                break
        if len(chosen) >= config.examples_per_proposal:
            break
    records = []
    for sid in chosen:
        before = previous[sid]; after = later.get(sid)
        feedback = {'parent_question_score': before['score']}
        if after:
            feedback['candidate_question_score'] = after['score']
        if role == 'global':
            value = {'parent': global_view(before), 'feedback': feedback}
            if after:
                value['candidate'] = global_view(after)
        else:
            views = list(video_views(before))
            if not views:
                continue
            context, view = views[rng.randrange(len(views))]
            value = {'parent': view, 'feedback': {**feedback, 'scope': 'whole question; NOT local correctness'}}
            if after:
                matched = dict(video_views(after)).get(context)
                if matched is not None:
                    value['candidate_same_local_context'] = matched
                else:
                    value['candidate_context_changed'] = True
        previews = {key: view for key, view in value.items() if isinstance(view, dict) and key != 'feedback'}
        budget = config.max_example_chars // len(previews)
        example = {key: val for key, val in value.items() if key not in previews}
        for key, view in previews.items():
            encoded = json.dumps(view, ensure_ascii=False)
            truncated = len(encoded) > budget
            if truncated:
                half = max(1, budget // 2)
                encoded = encoded[:half] + '\n[... omitted evidence ...]\n' + encoded[-half:]
            example[key] = {'trace': encoded, 'truncated': truncated}
        records.append(example)
    if not records:
        raise ValueError('No role-visible Train examples available')
    return records
