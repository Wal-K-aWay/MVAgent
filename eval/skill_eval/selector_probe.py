#!/usr/bin/env python3
"""Measure selector wording and candidate-order sensitivity without video inference."""
from pathlib import Path
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import fcntl
import hashlib
import json
import math
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT_ROOT / 'src'), str(PROJECT_ROOT)]

from mvagent.utils.io import file_fingerprint, hash_json, tree_hash, write_json
from skill_evolution.configs.manual import BODY_STYLES, ENTRY_STYLES, load_manual, manual_bank

ORDERS = ('normal', 'reversed')


def validate_cases(value):
    if not isinstance(value, list) or not value:
        raise ValueError('Cases must be a nonempty JSON array')
    ids = set()
    for case in value:
        if not isinstance(case, dict) or set(case) != {'id', 'role', 'task', 'state', 'has_evidence'}:
            raise ValueError('Case fields must be id, role, task, state, has_evidence')
        if any(not isinstance(case[k], str) or not case[k].strip() for k in ('id', 'task')):
            raise ValueError('Case id and task must be nonempty strings')
        if case['id'] in ids:
            raise ValueError('Duplicate case id')
        ids.add(case['id'])
        if case['role'] not in ('global', 'video') or type(case['has_evidence']) is not bool:
            raise ValueError('Invalid role or evidence flag')
        state = case['state']
        if not isinstance(state, dict) or state.get('history', '') != '':
            raise ValueError('Selector cases cannot include retained history')
        if case['role'] == 'video':
            if state != {'history': ''}:
                raise ValueError('Video selector state must contain only empty history')
        else:
            if set(state) - {'videos', 'history'} or not isinstance(state.get('videos'), dict) or not state['videos']:
                raise ValueError('Global selector state requires a video metadata mapping')
            for video_id, metadata in state['videos'].items():
                if not isinstance(video_id, str) or not video_id.strip() or not isinstance(metadata, dict):
                    raise ValueError('Invalid video metadata')
                if set(metadata) != {'duration_sec'}:
                    raise ValueError('Only video IDs and durations enter selector cases')
                duration = metadata['duration_sec']
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                    raise ValueError('Duration must be positive and finite')
    return value


def variants(definition):
    if len(definition['methods']) > 8:
        raise ValueError('This wording probe requires the full catalog, at most eight methods')
    assert 'concise' in BODY_STYLES
    keys = [m['key'] for m in definition['methods']]
    expected = {m['key']: m['strategies']['concise'] for m in definition['methods']}
    result = {}
    for style in ENTRY_STYLES:
        for order in ORDERS:
            sequence = keys if order == 'normal' else list(reversed(keys))
            bank = manual_bank(definition, body='concise', entry=style, order=sequence)
            bank = replace(bank, sha256=hashlib.sha256(
                json.dumps(bank.to_dict(), ensure_ascii=False, indent=2).encode()).hexdigest())
            mapping = {str(i + 1): key for i, key in enumerate(sequence)}
            assert {mapping[c.id]: c.strategy for c in bank.cards} == expected
            result[style, order] = (bank, mapping)
        normal, normal_map = result[style, 'normal']
        reverse, reverse_map = result[style, 'reversed']
        assert {normal_map[c.id]: (c.when_to_use, c.strategy, c.stages) for c in normal.cards} == {
            reverse_map[c.id]: (c.when_to_use, c.strategy, c.stages) for c in reverse.cards}
    return result


def summarize(records):
    groups = {}
    for row in records:
        key = (row['role'], row['style'], row['order'])
        group = groups.setdefault(key, {'role': key[0], 'style': key[1], 'order': key[2],
            'selected': 0, 'abstained': 0, 'invalid': 0, 'error': 0, 'selected_methods': Counter()})
        if row['status'] == 'ok':
            selected = row['selected_methods']
            group['selected' if selected else 'abstained'] += 1
            group['selected_methods'].update(selected)
        elif row['status'] in ('invalid', 'error'):
            group[row['status']] += 1
        else:
            raise ValueError('Unknown selector result status')
    return {'completed': len(records), 'groups': list(groups.values()),
            'interpretation': 'Selection frequency is not selection correctness or task accuracy.'}


def pin_manifest(output, manifest):
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'manifest.json'
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError('Selector probe source, inputs, or configuration changed')
    else:
        if any(p.name != '.lock' for p in output.iterdir()):
            raise ValueError('Cannot use nonempty output without a manifest')
        write_json(path, manifest)
    return hash_json(manifest)


def run_case(case, style, order, bank, mapping, *, model, output, manifest_hash, timeout):
    from models.execution import execution_scope
    from mvagent.agents.base import BaseAgent
    from mvagent.skills.selection import select_skills

    identity = {'manifest_sha256': manifest_hash, 'case_sha256': hash_json(case),
                'bank_sha256': bank.sha256, 'id_to_method': mapping,
                'role': case['role'], 'case_id': case['id'], 'style': style, 'order': order}
    directory = output / 'records' / hash_json(identity)
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / 'result.json'
    if result_path.exists():
        saved = json.loads(result_path.read_text())
        if any(saved.get(k) != v for k, v in identity.items()):
            raise ValueError('Saved selector identity changed')
        for name, digest in saved['artifacts'].items():
            if file_fingerprint(directory / name) != digest:
                raise ValueError('Saved selector raw artifact changed')
        return saved
    attempt = len(list(directory.glob('events-*.jsonl')))
    event_path, raw_path = directory / f'events-{attempt:03d}.jsonl', directory / f'raw-{attempt:03d}.json'
    agent = BaseAgent('SelectorProbe', model, logger=lambda _: None)
    events, requests, decisions = [], [], []
    with event_path.open('x') as stream:
        def emit(event):
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
            events.append(event)

        def decide(prompt, **kwargs):
            request = {'messages': agent.build_messages(prompt, system_prompt=kwargs.get('system_prompt')),
                       'json_schema': kwargs.get('json_schema'), 'schema_name': kwargs.get('schema_name')}
            requests.append(request)
            write_json(directory / f'request-{attempt:03d}.json', request)
            decision = agent.decide_json(prompt, **kwargs)
            decisions.append(decision)
            return decision

        try:
            with execution_scope(emit=emit, deadline=time.monotonic() + timeout):
                result = select_skills(bank, role=case['role'], task=case['task'], state=case['state'],
                    has_evidence=case['has_evidence'], decide=decide, selection_cache={})
        except Exception as exc:
            result = {'status': 'error', 'error': f'{type(exc).__name__}: {exc}'}
    selections = [e for e in events if e['kind'] == 'skill_selection' and e.get('status') == 'ok']
    selected_ids = [item['id'] for item in selections[-1]['selected']] if selections else []
    if result['status'] == 'ok' and len(selections) != 1:
        raise RuntimeError('Successful selection has no unique selection event')
    raw = {**identity, 'result': result, 'requests': requests, 'decisions': decisions,
           'input_sha256': hash_json(requests), 'selected_ids': selected_ids}
    write_json(raw_path, raw)
    artifacts = {p.name: file_fingerprint(p) for p in (event_path, raw_path)}
    request_path = directory / f'request-{attempt:03d}.json'
    if request_path.exists():
        artifacts[request_path.name] = file_fingerprint(request_path)
    saved = {**identity, 'status': result['status'], 'error': result.get('error', ''),
             'input_sha256': raw['input_sha256'], 'selected_ids': selected_ids,
             'selected_methods': [mapping[sid] for sid in selected_ids], 'artifacts': artifacts}
    write_json(result_path, saved)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-config', 'execution-config', 'cases', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--definitions', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    import yaml
    from models.factory import ModelFactory
    from models.pool import install_pools
    from mvagent.batch import ExecutionConfig, prepare_model_pools
    from mvagent.configs import MVAgentConfig

    cases = validate_cases(json.loads(args.cases.read_text()))
    definitions = [load_manual(path) for path in args.definitions]
    by_role = {d['role']: variants(d) for d in definitions}
    if len(by_role) != len(definitions) or set(c['role'] for c in cases) - by_role.keys():
        raise ValueError('Provide one definition for every case role, without duplicate roles')
    runtime = yaml.safe_load(args.runtime_config.read_text())
    config = MVAgentConfig.from_dict(runtime)
    execution = ExecutionConfig.from_yaml(args.execution_config)
    inputs = {'runtime': args.runtime_config, 'execution': args.execution_config, 'cases': args.cases,
              **{f'definition-{d["role"]}': p for d, p in zip(definitions, args.definitions)}}
    manifest = {'source_sha256': tree_hash(PROJECT_ROOT / 'src'),
                'evaluation_sha256': tree_hash(PROJECT_ROOT / 'eval'),
                'input_sha256': {k: file_fingerprint(p) for k, p in inputs.items()},
                'body': 'concise', 'styles': list(ENTRY_STYLES), 'orders': list(ORDERS),
                'cases': len(cases), 'planned_calls': len(cases) * len(ENTRY_STYLES) * len(ORDERS)}
    output = args.output.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_hash = pin_manifest(output, manifest)
        for role, values in by_role.items():
            for (style, order), (bank, mapping) in values.items():
                bank_path = output / 'banks' / f'{role}-{style}-{order}.json'
                write_json(bank_path, bank.to_dict())
                assert file_fingerprint(bank_path) == bank.sha256
        refs = {}
        for role in by_role:
            agent = config.global_agent if role == 'global' else config.video_agent
            refs[role] = (agent.skill.selector if agent.skill and agent.skill.enabled and
                          agent.skill.mode == 'dynamic' and agent.skill.selector else
                          agent.model if role == 'global' else agent.planner)
        pools, failures = prepare_model_pools(runtime, execution)
        write_json(output / 'model_pools.json', {'unavailable': failures,
            'pools': {name: {'replicas': [r.to_dict() for r in pool.replicas], 'cards': pool.cards}
                      for name, pool in pools.items()}})
        workers = sum(len(pools[name].replicas) for name in {r.model_type for r in refs.values()} if name in pools) or 1
        jobs = [(case, style, order, *by_role[case['role']][style, order])
                for case in cases for style in ENTRY_STYLES for order in ORDERS]

        def run(job):
            model = ModelFactory.create_model(refs[job[0]['role']], config)
            try:
                return run_case(*job, model=model, output=output, manifest_hash=manifest_hash,
                                timeout=execution.question_timeout_sec)
            finally:
                model.close()

        records = []
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for record in executor.map(run, jobs):
                    records.append(record)
                    write_json(output / 'summary.json', summarize(records))
        finally:
            install_pools({})
        print(json.dumps(summarize(records), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
