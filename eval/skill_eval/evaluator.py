"""Whole-library evaluation through the existing native runner and official Judge."""
from pathlib import Path
import json,os,subprocess,sys
from eval.data import DataSplitManifest
from eval.benchmarks.catalog import load_multibench_records
from eval.benchmarks.aggregation import HierarchicalScoreAggregator
from eval.agent_eval.score_crossvid_ccqa import LocalJudge, _score_one, SCORE_PROMPT
from mvagent.utils.io import file_fingerprint, hash_json, write_json
from skill_evolution.infra.banks import runtime_with_bank, runtime_with_forced_card
from skill_evolution.infra.evaluation import Evaluation

CROSSVID_TASKS = {'BU', 'NC', 'CC', 'PEA', 'PI', 'FSA', 'PSS', 'MSR', 'MOC', 'CCQA'}
MANUAL_GLOBAL_MODE = 'manual_global_assignment_diagnostic'


def evaluation_variant(bank_sha256, *, forced_card=None, global_assignments=None):
    """Keep natural/forced identities stable; manual routing is a separate intervention."""
    if forced_card is not None and global_assignments is not None:
        raise ValueError('Choose forced_card or global_assignments, never both')
    if global_assignments is not None:
        return hash_json({'bank': bank_sha256, 'selection_mode': MANUAL_GLOBAL_MODE,
                          'global_assignments_sha256': hash_json(global_assignments)})
    return bank_sha256 if forced_card is None else hash_json({'bank': bank_sha256, 'forced_card': forced_card})


def assignment_groups(bank, ids, assignments):
    """Validate complete routing and retain the frozen partition order within groups."""
    if not isinstance(assignments, dict) or set(assignments) != set(ids):
        raise ValueError('Global assignments must cover exactly the partition sample IDs')
    global_ids = {card.id for card in bank.cards if card.role == 'global'}
    groups = {}
    for sid in ids:
        card_id = assignments[sid]
        if card_id is not None and (not isinstance(card_id, str) or card_id not in global_ids):
            raise ValueError(f'Assignment for {sid} must name a Global card or null')
        groups.setdefault(card_id, []).append(sid)
    return groups


def _pin_json(path, payload):
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError(f'Frozen evaluation input changed: {path}')
    else:
        write_json(path, payload)


class LibraryEvaluator:
    def __init__(self, *, output, runtime, execution, split_path, dataset_root, endpoints, identity):
        self.output, self.runtime = Path(output), runtime
        self.execution, self.dataset_root = Path(execution), Path(dataset_root)
        split = DataSplitManifest.from_json(split_path)
        if any(not sample.sample_id.startswith('crossvid:') for sample in split.samples):
            raise ValueError('Evolution accepts CrossVid only; Test benchmarks are not optimizer data')
        self.ids = {name: split.ids(key) for name, key in [('train', 'train'), ('cal', 'cal'), ('gate', 'eval')]}
        ids = tuple(s for values in self.ids.values() for s in values)
        if len(set(ids)) != len(ids) or not all(self.ids.values()):
            raise ValueError('Train/Cal/Gate must be nonempty and disjoint')
        self.records = load_multibench_records(self.dataset_root, ids)
        for part, sample_ids in self.ids.items():
            if {self.records[s].native_task for s in sample_ids} != CROSSVID_TASKS:
                raise ValueError(f'{part} must cover all ten CrossVid tasks')
        self.aggregator = HierarchicalScoreAggregator(
            dataset_of={s:r.dataset for s,r in self.records.items()},
            category_of={s:r.native_task for s,r in self.records.items()},
            task_population={(r.dataset,r.native_task):r.task_population for r in self.records.values()},
            sample_weights={s:r.sample_weight for s,r in self.records.items()})
        self.judge = LocalJudge(endpoints, timeout_sec=600)
        self.identity = hash_json({'run': identity, 'judge': self.judge.identity,
                                   'score_prompt': SCORE_PROMPT, 'split': split.manifest_hash,
                                   'dataset_sha256': file_fingerprint(self.dataset_root / 'crossvid/qa.jsonl')})
        self.runner = Path(__file__).resolve().parents[1] / 'agent_eval/run.py'

    def __call__(self, bank, partition, *, forced_card=None, global_assignments=None):
        loaded_bank = bank.load()
        ids = self.ids[partition]
        if forced_card is not None:
            if (not isinstance(forced_card, dict) or set(forced_card) != {'role', 'card_id'}
                    or not any(c.role == forced_card['role'] and c.id == forced_card['card_id'] for c in loaded_bank.cards)):
                raise ValueError('Forced diagnostic must identify a card and its role')
        groups = assignment_groups(loaded_bank, ids, global_assignments) if global_assignments is not None else None
        variant = evaluation_variant(bank.sha256, forced_card=forced_card, global_assignments=global_assignments)
        directory = self.output / 'evaluations' / variant / partition
        directory.mkdir(parents=True, exist_ok=True)
        artifact_path = directory / 'evaluation.json'
        identity = {'protocol': self.identity, 'bank': bank.sha256,
                    'partition': partition, 'ids': ids, 'forced_card': forced_card}
        if groups is not None:
            identity.update(selection_mode=MANUAL_GLOBAL_MODE, global_assignments_sha256=hash_json(global_assignments))
        evaluation_identity = hash_json(identity)
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text())
            if artifact['identity'] != evaluation_identity:
                raise ValueError('Cached evaluation identity changed')
            for relative, digest in artifact.get('group_artifact_sha256', {}).items():
                if file_fingerprint(directory / relative) != digest:
                    raise ValueError(f'Saved assignment group artifact changed: {relative}')
            rows = self._rows(directory, ids, artifact['raw_sha256']) if partition == 'train' else []
            for row in rows:
                row['score'] = artifact['scores'][row['sample_id']]
            return Evaluation(partition, bank.sha256, artifact['score'], len(ids), evaluation_identity, tuple(rows))
        effective = runtime_with_bank(self.runtime, bank)
        if forced_card is not None:
            effective = runtime_with_forced_card(effective, bank, **forced_card,
                                                directory=self.output / 'forced_strategies')
        native = directory / 'rollouts'
        print(json.dumps({'phase':'evaluate', 'partition':partition, 'bank':bank.sha256, 'samples':len(ids)}), flush=True)
        group_artifacts = {}
        if groups is None:
            self._run_native(directory, effective, ids)
        else:
            _pin_json(directory / 'global_assignments.json', global_assignments)
            _pin_json(directory / 'sample_ids.json', list(ids))
            provenance = []
            for card_id, group_ids in groups.items():
                group = directory / 'groups' / ('none' if card_id is None else 'card-' + card_id)
                if card_id is None:
                    group_runtime = runtime_with_bank(self.runtime, bank)
                    group_runtime['agents']['global_agent']['skill'] = {'enabled': False}
                else:
                    group_runtime = runtime_with_forced_card(effective, bank, role='global', card_id=card_id,
                                                            directory=self.output / 'forced_strategies')
                self._run_native(group, group_runtime, group_ids)
                for sid in group_ids:
                    source = group / 'rollouts/records/crossvid' / sid / 'result.json'
                    if not source.is_file():
                        raise ValueError(f'Missing grouped raw rollout: {source}')
                    destination = native / 'records/crossvid' / sid / 'result.json'
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    relative = os.path.relpath(source, destination.parent)
                    if destination.exists() or destination.is_symlink():
                        if not destination.is_symlink() or os.readlink(destination) != relative:
                            raise ValueError(f'Assignment rollout link changed: {destination}')
                    else:
                        destination.symlink_to(relative)
                paths = [group / name for name in ('runtime.json', 'sample_ids.json', 'rollouts/run_manifest.json')]
                hashes = {str(path.relative_to(directory)): file_fingerprint(path) for path in paths}
                group_artifacts.update(hashes)
                provenance.append({'card_id': card_id, 'sample_ids': group_ids,
                                   'directory': str(group.relative_to(directory)), 'artifact_sha256': hashes})
            write_json(directory / 'global_assignment_groups.json', provenance)
            for name in ('global_assignments.json', 'sample_ids.json', 'global_assignment_groups.json'):
                group_artifacts[name] = file_fingerprint(directory / name)
        rows = self._rows(directory, ids)
        scores = {}
        for row in rows:
            sid = row['sample_id']; record = self.records[sid]
            if row['status'] != 'ok':
                raise RuntimeError(f'Incomplete rollout: {sid}: {row.get("error")}')
            if record.native_task == 'CCQA':
                task = {'id': sid, 'point_count': int(record.sample_weight), 'prediction': row['prediction'],
                        'prompt': SCORE_PROMPT.format(QUESTION=record.judge_question,
                                                     ANSWER=record.reference_answer,
                                                     POINTS=list(record.sample.ground_truth), OUTPUT=row['prediction'])}
                result = _score_one(self.judge, self.output / 'judge_cache', task, 3)
                write_json(directory / 'judge' / (sid + '.json'), result)
                if result['status'] != 'ok':
                    raise RuntimeError(f'Judge failed for {sid}: {result.get("error")}')
                score = result['score'] / (2 * record.sample_weight)
            else:
                if row.get('scoring_status') != 'ok' or row.get('score') is None:
                    raise RuntimeError(f'Official score unavailable for {sid}')
                score = row['score']
            scores[sid] = float(score)
            row['score'] = float(score)
        aggregate = self.aggregator.aggregate(sample_ids=ids, scores=scores, buckets={})
        score = aggregate.bucket_scores['dataset:crossvid']
        raw_sha = {sid:file_fingerprint(native / 'records/crossvid' / sid / 'result.json') for sid in ids}
        artifact = {'identity': evaluation_identity, 'bank_sha256':bank.sha256, 'partition':partition,
                    'selection_mode':MANUAL_GLOBAL_MODE if groups is not None else 'natural' if forced_card is None else 'forced_diagnostic',
                    'forced_card':forced_card,
                    'samples':len(ids), 'score':score, 'scores':scores, 'raw_sha256':raw_sha,
                    'judge':self.judge.identity, 'metric':'CrossVid ten-task macro; CCQA point-weighted'}
        if groups is not None:
            artifact.update(global_assignments_sha256=hash_json(global_assignments),
                            group_artifact_sha256=group_artifacts)
        write_json(artifact_path, artifact)
        print(json.dumps({'phase':'scored', 'partition':partition, 'bank':bank.sha256,
                          'samples':len(ids), 'official_score':score}), flush=True)
        return Evaluation(partition, bank.sha256, score, len(ids), evaluation_identity,
                          tuple(rows) if partition == 'train' else ())

    def _run_native(self, directory, runtime, ids):
        directory.mkdir(parents=True, exist_ok=True)
        runtime_path, ids_path = directory / 'runtime.json', directory / 'sample_ids.json'
        _pin_json(runtime_path, runtime)
        _pin_json(ids_path, list(ids))
        native = directory / 'rollouts'
        cmd = [sys.executable, str(self.runner), '--config', str(runtime_path),
               '--execution-config', str(self.execution), '--dataset-root', str(self.dataset_root),
               '--benchmarks', 'crossvid', '--sample-ids-file', str(ids_path),
               '--output', str(native), '--defer-open-qa-judge']
        if (native / 'run_manifest.json').exists():
            cmd.append('--resume')
        with (directory / 'console.log').open('a') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)

    @staticmethod
    def _rows(directory, ids, fingerprints=None):
        rows = []
        for sid in ids:
            path = directory / 'rollouts/records/crossvid' / sid / 'result.json'
            if fingerprints is not None and file_fingerprint(path) != fingerprints[sid]:
                raise ValueError(f'Saved raw rollout changed: {sid}')
            row = json.loads(path.read_text())
            if row['sample_id'] != sid:
                raise ValueError('Rollout ID mismatch')
            rows.append(row)
        return rows
