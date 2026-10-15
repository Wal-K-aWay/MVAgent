#!/usr/bin/env python3
"""Isolated 9B answer-protocol replay; never edits or connects to a production run."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time

SOURCE = Path('/runs/devbox/mvagent_full_20261014_transport/frozen_repo')
ALIGNMENT = Path('/runs/devbox/pro6000_alignment_20261015/r2')
VARIANTS = ['independent', 'direct', 'with_decision_reason']
DIRECT_ACTION = '''### Action: answer
Return the final answer directly from the question and accumulated History.
No further evidence collection is available.

Fields:
- reason: Give a concise evidence-based explanation.
- action: answer
- parameters.answer: The requested answer representation. When options are present,
  use only the selected option label or explicitly requested option text.

Return one complete JSON object:
{"reason":"<brief basis>","action":"answer","parameters":{"answer":"<requested answer>"}}

'''


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def requests(record):
    from mvagent.agents.global_agent.memory import GlobalAgentMemory
    events = record['events']
    answer = next(e for e in events if e['kind'] == 'structured_request' and e.get('schema') == 'global_answer')
    decision = [e for e in events if e['kind'] == 'structured_request' and e.get('schema') == 'global_decision'][-1]
    last = [e['output'] for e in record['result']['trajectory']
            if e.get('agent') == 'GlobalAgent' and e.get('action') == 'decide'][-1]
    assert last['action'] == 'answer', 'Select checkpoints with an explicit answer decision'
    question = record['result']['input']['question']
    memory = GlobalAgentMemory()
    memory.action_history = deepcopy(record['result']['action_history'])
    history = memory.render_action_history()
    base = dict(messages=deepcopy(answer['messages']), json_schema=deepcopy(answer['json_schema']), schema_name='global_answer')
    added = deepcopy(base)
    added['messages'][-1]['content'] += '\n\n## Previous decision rationale\n' + last['reason']
    direct = dict(messages=deepcopy(decision['messages']), schema_name='global_decision')
    user = direct['messages'][-1]['content']
    # Frozen runs have different section orderings; replace only named instruction blocks.
    for heading, body in [('Available actions', DIRECT_ACTION), ('Decision strategy',
            'The evidence collection is complete. Submit the best-supported final answer now.\n\n')]:
        user, count = re.subn(r'(?ms)^## '+heading+r'\n.*?(?=^## |\Z)',
                             lambda match: '## '+heading+'\n'+body, user, count=1)
        assert count == 1, heading
    # The standalone answerer has no video metadata; keep the evidence identical in this arm.
    user, count = re.subn(r'(?ms)^### Videos\n.*?(?=^## |\Z)', '', user, count=1)
    assert count == 1
    direct['messages'][-1]['content'] = user
    direct['json_schema'] = dict(type='object', additionalProperties=False,
        required=['reason', 'action', 'parameters'], properties=dict(
            reason=deepcopy(base['json_schema']['properties']['reason']),
            action=dict(type='string', enum=['answer']),
            parameters=dict(type='object', additionalProperties=False, required=['answer'],
                            properties=dict(answer=deepcopy(base['json_schema']['properties']['answer'])))))
    result = dict(independent=base, direct=direct, with_decision_reason=added)
    for request in result.values():
        assert question in request['messages'][-1]['content']
        assert history in request['messages'][-1]['content'], 'Evidence changed across arms'
        assert 'maxLength' not in request['json_schema']['properties']['reason']
    assert added['messages'][:-1] == base['messages'][:-1]
    assert added['messages'][-1]['content'] == base['messages'][-1]['content'] + '\n\n## Previous decision rationale\n' + last['reason']
    return result, dict(question=question, history=history, previous_decision_reason=last['reason'])


def measure(prediction, record):
    from skill_evolution.infra.benchmarks.scoring import ChoiceScorer
    from harness.answers import option_labels, leads_with_choice, read_choice, read_yes_no
    protocols = dict(cvbench='cvbench', mvu_eval='first_char', crossvid='exact')
    scorer = ChoiceScorer(protocol=protocols[record.dataset])
    labels = option_labels(record.sample.options)
    parsed = read_choice(prediction, labels)
    if record.dataset == 'cvbench':
        parsed = parsed or read_yes_no(prediction)
    return dict(answer=prediction, brace_only=prediction == '}',
        format_ok=leads_with_choice(prediction, labels) or
                  (record.dataset == 'cvbench' and bool(re.match(r'(?i:yes|no)\b', prediction))),
        extractable=parsed is not None,
        score=scorer.score(prediction=prediction, sample=record.sample).score,
        robust_score=scorer.score(prediction=parsed or '', sample=record.sample).score)


def prepare(output):
    import yaml
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    from models.utils import validate_json_schema
    assert not (output/'panel.json').exists(), 'Use the existing frozen panel; do not reselect'
    rows = json.loads((ALIGNMENT/'9B_paired.json').read_text())
    compact = json.loads((ALIGNMENT/'9B_current_compact.json').read_text())
    rng = random.Random(0)
    selected = []
    anchors = {('mvu_eval', 'brace'): 'mvu_eval:Comparison:1232', ('cvbench', 'correct'): 'cvbench:664'}
    for dataset in ['cvbench', 'mvu_eval', 'crossvid']:
        eligible = [r for r in rows if r['dataset'] == dataset and r['task'] not in ['BU', 'FSA', 'PSS', 'CCQA']
                    and compact[r['sample_id']]['last_decision'].get('action') == 'answer']
        for group, count in [('brace', 4), ('correct', 2), ('wrong', 2)]:
            choices = [r for r in eligible if
                       (r['new_agent_prediction'] == '}' if group == 'brace' else
                        r['new_agent_extractable'] and r['new_agent_robust_score'] == (1 if group == 'correct' else 0))]
            choices.sort(key=lambda r: r['sample_id'])
            anchor = anchors.get((dataset, group))
            fixed = [r for r in choices if r['sample_id'] == anchor]
            assert not anchor or len(fixed) == 1
            picked = fixed + rng.sample([r for r in choices if r['sample_id'] != anchor], count-len(fixed))
            selected.extend(dict(row=r, stratum=group) for r in picked)
    selected.append(dict(row=next(r for r in rows if r['sample_id'] == 'cvbench:712'), stratum='refusal_anchor'))
    ids = [p['row']['sample_id'] for p in selected]
    assert len(ids) == len(set(ids)) == 25
    records = load_multibench_records('/assets', ids)
    panel = []
    for picked in selected:
        row = picked['row']; sid = row['sample_id']
        path = Path(compact[sid]['source_path']); raw = path.read_bytes(); saved = json.loads(raw)
        arms, content = requests(saved)
        for variant, request in arms.items():
            example = dict(reason='Evidence reviewed', answer='}')
            if variant == 'direct':
                example = dict(reason='Evidence reviewed', action='answer', parameters=dict(answer='}'))
            validate_json_schema(example, request['json_schema'])
        baseline = measure(saved['prediction'], records[sid])
        assert baseline['score'] == row['new_agent_score'], (sid, baseline, row)
        assert baseline['robust_score'] == row['new_agent_robust_score'], (sid, baseline, row)
        reference = [e for e in saved['events'] if e['kind'] == 'model_response' and e.get('schema') == 'global_answer']
        assert reference
        panel.append(dict(sample_id=sid, dataset=row['dataset'], stratum=picked['stratum'],
            source_path=str(path), source_sha256=hashlib.sha256(raw).hexdigest(),
            evidence_sha256=digest(dict(question=content['question'], history=content['history'])),
            content=content, requests=arms, historical_baseline=baseline,
            reference_responses=[{k:e.get(k) for k in ['text','token_ids','request_sha256','prompt_token_ids_sha256','finish_reason']} for e in reference]))
    snapshot = output/'frozen_repo'
    snapshot.mkdir()
    for name in ['src', 'scripts', 'eval', 'configs']:
        shutil.copytree(SOURCE/name, snapshot/name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
    shutil.copy2(__file__, output/'probe_answer_protocol.py')
    (output/'prelaunch.py').write_text(Path('/repo/.probe_prelaunch.py').read_text().replace('"/repo/src"', repr(str(snapshot/'src'))))
    config = yaml.safe_load(Path('/runs/devbox/mvagent_full_20261014_transport/configs/9B.yaml').read_text())
    config['runtime']['cache_dir'] = str(output/'runtime_cache')
    execution = dict(question_workers=1, max_prepared_requests=1, question_retries=0, question_timeout_sec=7200,
        model_pools={'qwen3_5_9b_local':dict(replicas=[dict(gpus=[0],endpoint='http://127.0.0.1:8100/v1',max_inflight=1)])})
    for name, value in [('config',config),('execution',execution)]:
        (output/f'{name}.yaml').write_text(yaml.safe_dump(value, sort_keys=False))
    write(output/'panel.json', panel)
    write(output/'manifest.json', dict(prepared_at=datetime.now(timezone.utc).isoformat(), source=str(SOURCE),
        samples=ids, sample_seed=0, inference_seed=0, model='Qwen3.5-9B', gpu='H100!:1', variants=VARIANTS,
        panel_sha256=digest(panel), probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        purpose='Fixed-evidence diagnostic, not population accuracy; no new vision calls or Judge',
        selection='Per benchmark 4 brace failures, 2 readable correct, 2 readable wrong; CV712 additional refusal; proactive answer checkpoints; Cross single-choice tasks only',
        direct='Reconstructed direct decision contract, not a byte-for-byte historical PRO prompt; all arms unbounded reason, 2048 tokens',
        config=config, execution=execution,
        source_hashes={str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.rglob('*.py')}))
    write(output/'progress.json', dict(phase='prepared', planned=75, completed=0))
    print(json.dumps(dict(phase='prepared', samples=ids, strata=dict(Counter(p['stratum'] for p in panel)))),flush=True)


def run(output):
    import yaml
    from models.execution import execution_scope
    from models.factory import ModelFactory
    from mvagent.batch import ExecutionConfig, prepare_model_pools
    from mvagent.configs import MVAgentConfig
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    panel = json.loads((output/'panel.json').read_text())
    manifest = json.loads((output/'manifest.json').read_text())
    assert digest(panel) == manifest['panel_sha256']
    assert not (output/'results').exists(), 'Do not overwrite a partial or completed experiment'
    config = yaml.safe_load((output/'config.yaml').read_text())
    execution = yaml.safe_load((output/'execution.yaml').read_text())
    state = dict(phase='loading', planned=75, completed=0, started_at=datetime.now(timezone.utc).isoformat())
    write(output/'progress.json', state)
    with (output/'startup.log').open('w') as log:
        subprocess.run([sys.executable,str(output/'prelaunch.py'),str(output/'config.yaml'),str(output/'execution.yaml'),'qwen3_5_9b_local'],stdout=log,stderr=subprocess.STDOUT,check=True)
    cfg = MVAgentConfig.from_dict(config)
    pools, failed = prepare_model_pools(config, ExecutionConfig(**execution))
    assert not failed and len(next(iter(pools.values())).replicas) == 1
    client = ModelFactory.create_model(cfg.global_agent.model, cfg)
    records = load_multibench_records('/assets', [p['sample_id'] for p in panel])
    summaries = []
    try:
        # Paired triples deliver a complete comparison immediately; baseline always first.
        for index, item in enumerate(panel):
            sid = item['sample_id']
            order = ['independent'] + (VARIANTS[1:] if index % 2 == 0 else VARIANTS[:0:-1])
            for variant in order:
                events = []; started = time.monotonic()
                with execution_scope(emit=events.append):
                    result = client.json_chat(**item['requests'][variant])
                seconds = time.monotonic()-started
                write(output/'results'/variant/(sid+'.json'), dict(sample_id=sid,variant=variant,result=result,events=events,seconds=seconds,evidence_sha256=item['evidence_sha256']))
                calls = [e for e in events if e['kind']=='model_response']
                assert calls and all(len(e['token_ids']) == e['usage']['completion_tokens'] and e['worker']['forward_calls'] > 0 for e in calls)
                value = result.get('value') or {}
                prediction = str((value.get('parameters') or {}).get('answer','') if variant=='direct' else value.get('answer','')).strip()
                summary = dict(sample_id=sid,dataset=item['dataset'],stratum=item['stratum'],variant=variant,
                    status=result['status'],seconds=seconds,reason_chars=len(value.get('reason','')),**measure(prediction,records[sid]),
                    calls=len(calls),tokens=sum(e['usage']['completion_tokens'] for e in calls),
                    lengths=sum(e['finish_reason']=='length' for e in calls),repairs=sum(e['kind']=='structured_repair' for e in events))
                if variant=='independent':
                    current = [{k:e.get(k) for k in ['text','token_ids','request_sha256','prompt_token_ids_sha256','finish_reason']} for e in calls]
                    summary['matches_historical_tokens_and_input'] = current == item['reference_responses']
                summaries.append(summary)
                write(output/'summary.json', summaries)
                state.update(phase='running',completed=len(summaries),latest=summary)
                write(output/'progress.json',state)
                print(json.dumps(summary,ensure_ascii=False),flush=True)
                if variant=='independent':
                    assert summary['matches_historical_tokens_and_input'], f'Baseline replay diverged: {sid}'
        state.update(phase='completed',finished_at=datetime.now(timezone.utc).isoformat())
        write(output/'progress.json',state)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(Path('/runs/devbox').resolve()) and output.name.startswith('answer_ablation_')
    output.mkdir(parents=True, exist_ok=True)
    root = SOURCE if args.prepare else output/'frozen_repo'
    sys.path[:0] = [str(root/'src'),str(root/'eval/e2e_eval')]
    try:
        (prepare if args.prepare else run)(output)
    except Exception as exc:
        import traceback
        write(output/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
