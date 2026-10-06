"""Cluster-organized full-library Train, separated authors and full-bank Gate."""
from dataclasses import asdict, dataclass
import fcntl
import json
from pathlib import Path
import random
from collections import Counter

from mvagent.skills.bank import MAX_SKILL_WORDS
from skill_evolution.infra.bank import BankSnapshot, BankStore
from skill_evolution.infra.data import EvaluationRequest
from skill_evolution.infra.evaluation import evaluate_batch, compact_report, compare
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import tree_hash, write_json
from .evidence import training_case, card_content
from .question_groups import QuestionGroups
from .stages import Stages, StageValidationError, candidate_bank


@dataclass(frozen=True)
class GlobalConfig:
    rounds: int = 3
    batch_size: int = 8
    patience: int = 3
    seed: int = 20261003
    max_card_words: int = MAX_SKILL_WORDS
    cluster_anchor: str | None = None

    def __post_init__(self):
        for name in ('rounds', 'batch_size', 'patience', 'max_card_words'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + ' must be a positive integer')
        if type(self.seed) is not int:
            raise ValueError('seed must be an integer')
        if self.cluster_anchor is not None and (not isinstance(self.cluster_anchor, str) or not self.cluster_anchor.strip()):
            raise ValueError('cluster_anchor must be a nonempty Train sample ID')
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
        self.store = BankStore(self.root / 'cluster_evolution')
        self.stages = Stages(optimizer)
        self.matcher = QuestionGroups(embedding_config, self.root / 'embeddings')
        self.identity = hash_json(dict(config=asdict(config), initial=self.initial.to_dict(),
            train=self.train.context_hash, gate=self.gate.context_hash, optimizer=optimizer.identity,
            embedding=embedding_config.to_dict(), metadata=sample_metadata,
            source=tree_hash(Path(__file__).parent)))

    def rollout(self, bank, context, ids, label):
        print(json.dumps(dict(phase=label, samples=len(ids), bank=bank.skill_set_hash())), flush=True)
        result = evaluate_batch(self.executor, self.cache, self.scorer, self.aggregator,
            EvaluationRequest(bank, context, tuple(ids), label))
        write_json(self.root / 'evaluations' / (label + '.json'), compact_report(result))
        return result

    def run(self, *, resume=False):
        with (self.store.root / 'training.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._run(resume=resume)

    def _run(self, *, resume):
        state = self.store.initialize(self.initial, self.identity, resume=resume)
        grouping = self.matcher.build({sid: self.metadata[sid]['input'] for sid in self.train.sample_ids})
        write_json(self.root / 'question_groups.json', grouping)
        selected_groups = grouping['groups']
        if self.config.cluster_anchor is not None:
            selected_groups = [g for g in selected_groups if self.config.cluster_anchor in g]
            if not selected_groups:
                raise ValueError('cluster_anchor is absent from Train')
        write_json(self.root / 'training_scope.json', dict(cluster_anchor=self.config.cluster_anchor,
            groups=selected_groups, sample_ids=[sid for g in selected_groups for sid in g]))
        # One shuffled pass over each selected cluster per epoch; one candidate per batch.
        schedule = []
        for epoch in range(self.config.rounds):
            for index, members in enumerate(selected_groups):
                ids = list(members)
                random.Random(self.config.seed + epoch * len(grouping['groups']) + index).shuffle(ids)
                for start in range(0, len(ids), self.config.batch_size):
                    schedule.append((epoch, members[0], ids[start:start + self.config.batch_size]))
        rejected, stale = [], {}
        routing_feedback = []
        for decision in state['decisions']:
            key = decision['cluster']
            routing_feedback=decision.get('routing_feedback',routing_feedback)
            if decision['status'] == 'accepted':
                stale[key] = 0
            elif decision['status'] != 'patience':
                stale[key] = stale.get(key, 0) + 1
            if decision.get('rejected'):
                rejected.append(decision['rejected'])
        seed_gate = self.rollout(self.initial, self.gate, self.gate.sample_ids, 'seed_gate')
        bank = self.store.load(state['bank_hash'])
        current_gate = seed_gate if bank == self.initial else self.rollout(bank, self.gate, self.gate.sample_ids, 'resume_gate')
        for cursor in range(state['next_round'], len(schedule)):
            epoch, cluster, ids = schedule[cursor]
            directory = self.root / 'batches' / f'{cursor:04d}'
            decision = dict(epoch=epoch, cluster=cluster, train_ids=ids,
                parent_hash=bank.skill_set_hash(), skill_id=None, status='skip')
            if stale.get(cluster, 0) >= self.config.patience:
                decision['status'] = 'patience'
                state = self.store.commit(state, bank, decision)
                continue
            train_bank = bank
            report = self.rollout(train_bank, self.train, ids, f'b{cursor}_train')
            cases, excluded = [], []
            for sid in ids:
                health = report['health'][sid]
                if health['fatal'] or health['invalid']:
                    excluded.append(sid)
                    continue
                case=training_case(report,sid,train_bank,self.projector,self.metadata[sid]['reference'])
                case['source_sample_id']=sid
                case['sample_id']='case_'+str(len(cases)+1)
                cases.append(case)
            library=[c.to_dict() for c in bank.bank.cards if c.role=='global']
            payload=dict(cases=cases,target_skill=None,library=library,rejected=rejected[-5:],
                routing_feedback=routing_feedback,max_card_words=self.config.max_card_words)
            write_json(directory / 'materials.json', dict(**payload, excluded=excluded,
                train_bank_hash=train_bank.skill_set_hash()))
            decision['excluded'] = excluded
            decision['selection_distribution']=dict(Counter(c['used_skill']['meta']['id'] if c.get('used_skill') else 'none' for c in cases))
            if any(c['offline_feedback']['score'] < 1 for c in cases):
                try:
                    reflection = self.stages.reflect(directory / 'reflect', payload)
                    if reflection['status'] != 'skip':
                        payload['reflection']=reflection
                        target_id=reflection['target_skill_id']
                        target=next((c for c in library if c['meta']['id']==target_id),None)
                        payload['target_skill']=target
                        payload['rejected']=[r for r in rejected if (r['card']['meta']['id']==target_id if target else r['cluster']==cluster)][-5:]
                        decision['edit_mode']=reflection['status']
                        link=dict(action='revise' if target else 'create',skill_id=target_id or '')
                        value = self.stages.generate(directory / 'proposal', payload, bank, link)
                        candidate = candidate_bank(bank, link, value, self.config.max_card_words)
                        if candidate is not None:
                            raw = value['card']
                            comparable = [c.to_dict() for c in bank.bank.cards if c.role == 'global' and c.id != target_id]
                            if any(card_content(c) == card_content(raw) for c in comparable):
                                decision['status'] = 'duplicate'
                            else:
                                self.store.snapshot(candidate)
                                routing_feedback=self.replay_routing(bank,candidate,grouping,directory)
                                decision['routing_feedback']=routing_feedback
                                candidate_gate = self.rollout(candidate, self.gate, self.gate.sample_ids, f'b{cursor}_gate')
                                adopted = candidate_gate['score'] > current_gate['score']
                                write_json(directory / 'validation.json', dict(accepted=adopted,
                                    parent=compact_report(current_gate), candidate=compact_report(candidate_gate),
                                    comparison=compare(current_gate, candidate_gate)))
                                decision.update(status='accepted' if adopted else 'gate_rejected',
                                    candidate_hash=candidate.skill_set_hash(), skill_id=raw['meta']['id'])
                                write_json(directory / 'change.json', dict(before=target, after=raw))
                                if adopted:
                                    bank, current_gate = candidate, candidate_gate
                                else:
                                    record = dict(card=raw,status='not_accepted',parent_hash=bank.skill_set_hash(),cluster=cluster)
                                    rejected.append(record)
                                    decision['rejected'] = record
                except StageValidationError as exc:
                    decision.update(status='invalid_stage', error=str(exc))
            else:
                decision['status'] = 'no_healthy_failures'
            stale[cluster] = 0 if decision['status'] == 'accepted' else stale.get(cluster, 0) + 1
            state = self.store.commit(state, bank, decision)
        write_json(self.root / 'final_bank.json', bank.to_dict())
        write_json(self.root / 'selection_statistics.json',dict(cluster_binding=False,train_batches=[dict(cluster=d['cluster'],train_ids=d['train_ids'],bank_hash=d['parent_hash'],edit_mode=d.get('edit_mode'),selection_distribution=d.get('selection_distribution',{})) for d in state['decisions']]))
        summary = dict(status='completed', algorithm='global-cluster-v1', batches=state['next_round'],
            clusters=len(grouping['groups']), optimized_clusters=len(selected_groups), accepted=sum(d['status'] == 'accepted' for d in state['decisions']),
            candidates_validated=sum(d['status'] in ('accepted', 'gate_rejected') for d in state['decisions']),
            initial_gate=seed_gate['score'], final_gate=current_gate['score'],
            delta=current_gate['score']-seed_gate['score'], bank_hash=bank.skill_set_hash(),
            skills=len(bank.bank.cards), gate=compact_report(current_gate))
        write_json(self.root / 'summary.json', summary)
        return summary

    def replay_routing(self,parent,candidate,grouping,directory):
        from .routing import replay_selection
        ids=list(dict.fromkeys(sid for group in grouping['groups'] for sid in group[:4]))
        feedback=replay_selection(self.executor,parent,candidate,{sid:self.metadata[sid]['input'] for sid in ids},directory/'train_routing')
        return [dict(case='probe_'+str(i+1),question=self.metadata[r['sample_id']]['input']['question'],before=r['before'],after=r['after']) for i,r in enumerate(feedback) if r['before']!=r['after']][:20]
