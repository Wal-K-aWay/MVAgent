"""Sequential Global adaptation: fault → one candidate → full Gate → commit."""
from dataclasses import asdict, dataclass
import fcntl
import json
import math
from pathlib import Path
import random

from mvagent.skills.bank import MAX_SKILL_WORDS
from skill_evolution.infra.bank import BankStore
from skill_evolution.infra.data import EvaluationRequest
from skill_evolution.infra.evaluation import evaluate_batch, compact_report, compare
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import tree_hash, write_json
from .evidence import training_case, fault_context, card_content, used_skill
from .question_groups import QuestionGroups
from .stages import repair_operations, Stages, StageValidationError, candidate_bank
from .prompts import STAGE_TASKS, build_system_prompt


@dataclass(frozen=True)
class GlobalConfig:
    rounds: int = 3
    batch_size: int = 32
    patience: int = 3
    seed: int = 20260928
    issue_score_threshold: float = 1.0
    max_card_words: int = MAX_SKILL_WORDS

    def __post_init__(self):
        for name in ('rounds', 'batch_size', 'patience', 'max_card_words'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + ' must be a positive integer')
        if type(self.seed) is not int:
            raise ValueError('seed must be an integer')
        for name in ('issue_score_threshold',):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(name + ' must be in (0, 1]')
        if self.max_card_words > MAX_SKILL_WORDS:
            raise ValueError('max_card_words exceeds Runtime limit')


class GlobalTrainer:
    def __init__(self, *, config, initial_skill_set, train_context, eval_context,
                 executor, scorer, aggregator, projector, optimizer,
                 embedding_config, sample_metadata, output_dir, episode_cache):
        self.config, self.initial = config, initial_skill_set
        self.train, self.gate = train_context, eval_context
        if not self.train.sample_ids or not self.gate.sample_ids or set(self.train.sample_ids) & set(self.gate.sample_ids):
            raise ValueError('Train and Gate must be nonempty and disjoint')
        self.executor, self.scorer, self.aggregator = executor, scorer, aggregator
        self.projector, self.metadata, self.cache = projector, sample_metadata, episode_cache
        self.root = Path(output_dir)
        self.store = BankStore(self.root / 'global_evolution')
        self.stages = Stages(optimizer)
        self.matcher = QuestionGroups(embedding_config, self.root / 'embeddings')
        self.identity = hash_json(dict(config=asdict(config), initial=self.initial.to_dict(),
            train=self.train.context_hash, gate=self.gate.context_hash, optimizer=optimizer.identity,
            embedding=embedding_config.to_dict(), system_prompts={name: build_system_prompt(name) for name in STAGE_TASKS},
            metadata={sid: sample_metadata[sid] for sid in self.train.sample_ids},
            source=tree_hash(Path(__file__).parent)))

    def rollout(self, bank, context, ids, label):
        print(json.dumps(dict(phase=label, samples=len(ids), bank=bank.skill_set_hash())), flush=True)
        result = evaluate_batch(self.executor, self.cache, self.scorer, self.aggregator,
            EvaluationRequest(bank, context, tuple(ids), label))
        write_json(self.root / 'evaluations' / (label + '.json'), compact_report(result))
        return result

    def _case(self, report, sid, bank):
        if sid not in self.train.sample_ids:
            raise ValueError('Optimizer cases must be Train-only')
        return training_case(report, sid, bank, self.projector, self.metadata[sid]['reference'])

    def run(self, *, resume=False):
        with (self.store.root / 'training.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._run(resume=resume)

    def _run(self, *, resume):
        state = self.store.initialize(self.initial, self.identity, resume=resume)
        grouping = self.matcher.build({sid: self.metadata[sid]['input'] for sid in self.train.sample_ids})
        write_json(self.root / 'question_groups.json', grouping)
        pool = {}
        for decision in state['decisions']:
            material_path = self.root / decision['materials_path']
            materials = json.loads(material_path.read_text())
            if hash_json(materials) != decision['materials_hash']:
                raise ValueError('Committed trajectory materials changed')
            for member in materials:
                sid = member['sample_id'] if member.get('excluded') else member['case']['sample_id']
                if sid not in self.train.sample_ids:
                    raise ValueError('Trajectory materials must be Train-only')
                if member.get('excluded'):
                    pool.pop(sid, None)
                else:
                    pool[sid] = member
        seed_gate = self.rollout(self.initial, self.gate, self.gate.sample_ids, 'seed_gate')
        bank = self.store.load(state['bank_hash'])
        current_gate = seed_gate if bank == self.initial else self.rollout(bank, self.gate, self.gate.sample_ids, 'resume_gate')
        history, rejected = {}, []
        for decision in state['decisions']:
            for sid, items in decision['failure_history'].items():
                history.setdefault(sid, []).extend(items)
            rejected.extend(decision['rejected'])
        no_accept = 0
        for decision in reversed(state['decisions']):
            if decision['accepted']:
                break
            no_accept += 1
        stopped = state['decisions'][-1].get('stop_reason') if state['decisions'] else None
        for round_index in range(state['next_round'], self.config.rounds):
            if stopped or no_accept >= self.config.patience:
                break
            directory = self.root / 'rounds' / f'{round_index:03d}'
            ids = list(self.train.sample_ids)
            random.Random(self.config.seed + round_index).shuffle(ids)
            ids = ids[:self.config.batch_size]
            parent = bank
            report = self.rollout(bank, self.train, ids, f'r{round_index}_train')
            faults, skips = [], []
            updates = {}
            def retain(case, health, localization):
                member = dict(case=case, health=health, localization=localization,
                    source_bank=case['bank_hash'], round=round_index,
                    run_identity=self.identity, trajectory_hash=hash_json(case),
                    faults=[dict(fault_ref=f"{case['sample_id']}@{case['bank_hash']}#step:{item['step']}",
                        **fault_context(case, item)) for item in localization['fault_chain']])
                pool[case['sample_id']] = updates[case['sample_id']] = member
            valid_issues = 0
            for index, sid in enumerate(ids):
                health = report['health'][sid]
                if health['fatal'] or health['invalid']:
                    skips.append(dict(sample_id=sid, reason='execution_error'))
                    pool.pop(sid, None)
                    updates[sid] = dict(sample_id=sid, excluded=True)
                    continue
                case = self._case(report, sid, bank)
                retain(case, health, dict(status='not_run', reason='Not localized.', fault_chain=[]))
                if report['scores'][sid].score >= self.config.issue_score_threshold:
                    continue
                valid_issues += 1
                try:
                    located = self.stages.localize(directory / f'localize_{index}', case, bank)
                except StageValidationError as exc:
                    skips.append(dict(sample_id=sid, reason=str(exc)))
                    retain(case, health, dict(status='invalid', reason=str(exc), fault_chain=[]))
                    continue
                retain(case, health, located)
                if located['status'] == 'located':
                    faults.append(dict(sample_id=sid, case=case, **located))
            faults.sort(key=lambda f: (self.matcher.labels[f['sample_id']], f['sample_id']))
            remaining = {f['sample_id']: len(f['fault_chain']) for f in faults}
            write_json(directory / 'faults.json', dict(faults=faults,
                cluster_by_id={sid: self.matcher.labels[sid] for sid in ids}, skipped=skips))
            attempts, accepted, round_history, round_rejected = [], [], {}, []
            for fault_index, fault in enumerate(faults):
                sid, case = fault['sample_id'], fault['case']
                # A preceding accepted candidate may change routing or the whole trajectory.
                # Re-localize the case rather than apply stale step indices to the new bank.
                if case['bank_hash'] != bank.skill_set_hash():
                    refreshed = self.rollout(bank, self.train, [sid], f'r{round_index}_refresh_{fault_index}')
                    health = refreshed['health'][sid]
                    if health['fatal'] or health['invalid']:
                        pool.pop(sid, None)
                        updates[sid] = dict(sample_id=sid, excluded=True)
                        continue
                    case = self._case(refreshed, sid, bank)
                    retain(case, health, dict(status='not_run', reason='Not localized.', fault_chain=[]))
                    if refreshed['scores'][sid].score >= self.config.issue_score_threshold:
                        continue
                    try:
                        fresh_fault = self.stages.localize(directory / f'refresh_{fault_index}', case, bank)
                    except StageValidationError as exc:
                        attempts.append(dict(status='invalid_localization', error=str(exc)))
                        retain(case, health, dict(status='invalid', reason=str(exc), fault_chain=[]))
                        continue
                    retain(case, health, fresh_fault)
                    if fresh_fault['status'] == 'skip':
                        continue
                    fault = dict(sample_id=sid, **fresh_fault)
                for chain_index, entry in enumerate(fault['fault_chain']):
                    fault_ref = f"{sid}@{case['bank_hash']}#step:{entry['step']}"
                    if remaining[sid] == 0:
                        break
                    remaining[sid] -= 1
                    attempt_dir = directory / f'fault_{fault_index}' / f'step_{chain_index}'
                    context = fault_context(case, entry)
                    context['fault_ref'] = fault_ref
                    context['group_cases'] = self.matcher.related(sid, pool)
                    attempt = dict(sample_id=sid, step=entry['step'], parent_hash=bank.skill_set_hash())
                    try:
                        target = used_skill(case, bank)
                        decision = self.stages.link(attempt_dir / 'link', case, context, target)
                        attempt['linker_decision'] = decision
                        operations = repair_operations(decision, target)
                        if not operations:
                            attempt['status'] = 'skip'
                            attempts.append(attempt)
                            continue
                        accepted_here = False
                        for operation_index, link in enumerate(operations):
                            operation_dir = attempt_dir / f'operation_{operation_index}'
                            attempt = dict(sample_id=sid, step=entry['step'], parent_hash=bank.skill_set_hash(),
                                linker_decision=decision, operation=link)
                            failures = []
                            if link['action'] == 'revise':
                                target = link['skill_id']
                                record = dict(sample_id=sid, bank_hash=bank.skill_set_hash(),
                                              input=case['input'], fault=context)
                                history.setdefault(target, []).append(record)
                                round_history.setdefault(target, []).append(record)
                                failures = history[target]
                            value = self.stages.generate(operation_dir / 'proposal', case, context, bank, link,
                                failures, rejected, self.config.max_card_words)
                            candidate = candidate_bank(bank, link, value, self.config.max_card_words)
                            if candidate is None:
                                attempt['status'] = 'skip'
                                attempts.append(attempt)
                                continue
                            raw = value['card']
                            current_cards = [c.to_dict() for c in bank.bank.cards if c.role == 'global']
                            comparable = [c for c in current_cards if c['meta']['id'] != link['skill_id']]
                            same_parent_rejected = [r for r in rejected if r['parent_hash'] == bank.skill_set_hash()]
                            if any(card_content(c) == card_content(raw) for c in comparable + [r['card'] for r in same_parent_rejected]):
                                attempt['status'] = 'duplicate'
                                attempts.append(attempt)
                                continue
                            attempt['candidate_hash'] = candidate.skill_set_hash()
                            self.store.snapshot(candidate)
                            candidate_gate = self.rollout(candidate, self.gate, self.gate.sample_ids,
                                f'r{round_index}_f{fault_index}_s{chain_index}_o{operation_index}_gate')
                            comparison = compare(current_gate, candidate_gate)
                            # The only acceptance rule: strict gain in complete official aggregate.
                            adopted = candidate_gate['score'] > current_gate['score']
                            write_json(operation_dir / 'validation.json', dict(accepted=adopted,
                                parent=compact_report(current_gate), candidate=compact_report(candidate_gate),
                                comparison=comparison))
                            attempt['status'] = 'accepted' if adopted else 'gate_rejected'
                            attempts.append(attempt)
                            if adopted:
                                accepted_here = True
                                bank, current_gate = candidate, candidate_gate
                                accepted.append(candidate.skill_set_hash())
                                # Re-localize remaining work against the accepted bank; old step IDs are stale.
                                if remaining[sid]:
                                    faults.append(dict(fault, sample_id=sid, case=case))
                                break
                            # No Gate scores, answers, traces or task breakdown enter optimizer inputs.
                            record = dict(parent_hash=bank.skill_set_hash(), card=raw, status='not_accepted')
                            rejected.append(record)
                            round_rejected.append(record)
                        if accepted_here:
                            break
                    except StageValidationError as exc:
                        attempts.append(dict(**attempt, status='invalid_stage', error=str(exc)))
                    finally:
                        write_json(directory / 'attempts.json', attempts)
            no_accept = 0 if accepted else no_accept + 1
            # A small successful minibatch is not evidence that all Train problems are solved.
            full_train = set(ids) == set(self.train.sample_ids)
            stopped = 'no_issues' if full_train and valid_issues == 0 and not skips else None
            if no_accept >= self.config.patience:
                stopped = 'patience'
            materials = [updates[sid] for sid in sorted(updates)]
            material_path = directory / 'materials.json'
            write_json(material_path, materials)
            decision = dict(materials_path=str(material_path.relative_to(self.root)),
                materials_hash=hash_json(materials), round=round_index, parent_hash=parent.skill_set_hash(), train_ids=ids,
                accepted=accepted, attempts=attempts, failure_history=round_history,
                rejected=round_rejected, stop_reason=stopped)
            state = self.store.commit(state, bank, decision)
        write_json(self.root / 'final_bank.json', bank.to_dict())
        summary = dict(status='completed', algorithm='global-skilladaptor-v1',
            rounds=state['next_round'], accepted=sum(len(d['accepted']) for d in state['decisions']),
            candidates_validated=sum(a['status'] in ('accepted', 'gate_rejected')
                for d in state['decisions'] for a in d['attempts']),
            skills=len(bank.bank.cards), initial_gate=seed_gate['score'], final_gate=current_gate['score'],
            delta=current_gate['score']-seed_gate['score'], bank_hash=bank.skill_set_hash(),
            stop_reason=stopped or 'round_limit', gate=compact_report(current_gate))
        write_json(self.root / 'summary.json', summary)
        return summary
