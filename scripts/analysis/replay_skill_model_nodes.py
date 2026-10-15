"""Replay frozen text Skill/Actor requests; never execute resulting actions.

Prepare all initial Global nodes plus first Video initial/later and later Global
nodes per question. Sampling uses trajectory positions, not correctness.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import threading
import time


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root, baseline):
    if (root / 'replay_inputs.json').exists():
        raise ValueError('Replay inputs already frozen')
    jobs = []
    for path in sorted((baseline / 'run/records').glob('*/*/result.json')):
        raw = read(path)
        requests, parsed = {}, {}
        for event in raw['events']:
            phase = 'selector' if event.get('skill_phase') == 'selection' else 'actor'
            key = (event.get('decision_id'), phase)
            if event['kind'] == 'structured_request' and event.get('schema') in ('skill_selection', 'global_decision', 'video_action'):
                requests[key] = event
            if event['kind'] == 'structured_parsed':
                parsed[key] = event['value']
        nodes = [key[0] for key in requests if key[1] == 'selector' and (key[0], 'actor') in requests]
        groups = {}
        for node in nodes:
            if node == 'global:1':
                group = 'global_initial'
            elif node.startswith('global:'):
                group = 'global_later'
            elif node.endswith(':1'):
                group = 'video_initial'
            else:
                group = 'video_later'
            groups.setdefault(group, node)
        for group, node in groups.items():
            for phase in ('selector', 'actor'):
                event = requests[node, phase]
                assert all(isinstance(m['content'], str) for m in event['messages'])
                jobs.append(dict(sample_id=raw['sample_id'], node=node, phase=phase, stratum=group,
                    source=str(path.resolve()), source_sha256=sha(path),
                    request={k:event[k] for k in ('messages', 'json_schema', 'schema')},
                    baseline_value=parsed[node, phase]))
    save(root / 'replay_inputs.json', jobs)
    save(root / 'replay_protocol.json', dict(input_sha256=sha(root / 'replay_inputs.json'),
        jobs=len(jobs), strata=Counter(j['stratum'] for j in jobs),
        selection='First node per question in each of four trajectory-position strata; no outcome filtering',
        limits='Text-only counterfactual outputs, no continuation. Actor sees saved35B Skill, not new27B selection.',
        config_sha256=sha(root / 'config.yaml'), execution_sha256=sha(root / 'execution.yaml')))
    print(f'Prepared {len(jobs)} text calls', flush=True)


def run(root):
    import fcntl
    import yaml
    from models.pool import install_pools
    from models.factory import ModelFactory
    from models.execution import execution_scope
    from mvagent.configs import MVAgentConfig
    from mvagent.batch import BatchExecutor, ExecutionConfig
    lock = (root / 'replay.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    protocol = read(root / 'replay_protocol.json')
    for filename, key in [('replay_inputs.json','input_sha256'), ('config.yaml','config_sha256'), ('execution.yaml','execution_sha256')]:
        if sha(root / filename) != protocol[key]:
            raise ValueError(f'Changed replay identity: {filename}')
    jobs = read(root / 'replay_inputs.json')
    for path, expected in {(j['source'], j['source_sha256']) for j in jobs}:
        if sha(Path(path)) != expected:
            raise ValueError('Baseline changed')
    data = yaml.safe_load((root / 'config.yaml').read_text())
    cfg = MVAgentConfig.from_dict(data)
    events = []
    batch = BatchExecutor(ExecutionConfig.from_yaml(root / 'execution.yaml'), on_event=events.append)
    clients, local = [], threading.local()
    started = time.time()
    try:
        batch.prepare(data)
        save(root / 'replay_pool.json', events)
        prepared = next(e for e in events if e['kind'] == 'batch_prepared')
        if prepared['question_workers'] != 6 or prepared['unavailable']:
            raise RuntimeError('Expected six verified healthy replicas')
        install_pools(batch.pools)
        def work(index):
            job = jobs[index]
            path = root / 'replay_results' / f'{index:04d}.json'
            if path.exists():
                return read(path)['status']
            if not hasattr(local, 'model'):
                local.model = ModelFactory.create_model(cfg.global_agent.model, cfg)
                clients.append(local.model)
            recorded = []
            start = time.time()
            try:
                req = job['request']
                with execution_scope(emit=recorded.append, deadline=time.monotonic()+240):
                    response = local.model.json_chat(messages=req['messages'], json_schema=req['json_schema'],
                        schema_name=req['schema'], max_tokens=2048, temperature=0, top_p=1)
                result = dict(status=response['status'], response=response)
            except Exception as exc:
                result = dict(status='error', error=str(exc))
            save(path, dict(index=index, sample_id=job['sample_id'], node=job['node'], phase=job['phase'],
                seconds=time.time()-start, events=recorded, **result))
            return result['status']
        counts = Counter()
        with ThreadPoolExecutor(max_workers=6) as executor:
            for future in as_completed([executor.submit(work, i) for i in range(len(jobs))]):
                counts[future.result()] += 1
                save(root / 'replay_status.json', dict(stage='running', completed=sum(counts.values()),
                    target=len(jobs), counts=counts, seconds=time.time()-started))
        save(root / 'replay_status.json', dict(stage='completed', completed=len(jobs), counts=counts,
            seconds=time.time()-started))
    finally:
        for client in clients:
            if hasattr(client, 'close'):
                client.close()
        batch.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        if args.baseline is None:
            parser.error('--baseline is required for prepare')
        prepare(args.output, args.baseline)
    else:
        try:
            run(args.output)
        except BaseException as exc:
            save(args.output / 'replay_status.json', dict(stage='failed', error=str(exc)))
            raise
