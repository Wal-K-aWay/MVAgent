"""Whole-library evaluation through the existing native runner and official Judge."""
from pathlib import Path
import json,subprocess,sys
from eval.data import DataSplitManifest
from eval.benchmarks.catalog import load_multibench_records
from eval.benchmarks.aggregation import HierarchicalScoreAggregator
from eval.agent_eval.score_crossvid_ccqa import LocalJudge, _score_one, SCORE_PROMPT
from mvagent.utils.io import file_fingerprint, hash_json, write_json
from skill_evolution.infra.banks import runtime_with_bank
from skill_evolution.infra.evaluation import Evaluation

CROSSVID_TASKS = {'BU', 'NC', 'CC', 'PEA', 'PI', 'FSA', 'PSS', 'MSR', 'MOC', 'CCQA'}


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
                                   'score_prompt': SCORE_PROMPT, 'split': split.manifest_hash})
        self.runner = Path(__file__).resolve().parents[1] / 'agent_eval/run.py'

    def __call__(self, bank, partition):
        bank.load()
        ids = self.ids[partition]
        directory = self.output / 'evaluations' / bank.sha256 / partition
        directory.mkdir(parents=True, exist_ok=True)
        artifact_path = directory / 'evaluation.json'
        evaluation_identity = hash_json({'protocol': self.identity, 'bank': bank.sha256,
                                         'partition': partition, 'ids': ids})
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text())
            if artifact['identity'] != evaluation_identity:
                raise ValueError('Cached evaluation identity changed')
            rows = self._rows(directory, ids, artifact['raw_sha256']) if partition == 'train' else []
            for row in rows:
                row['score'] = artifact['scores'][row['sample_id']]
            return Evaluation(partition, bank.sha256, artifact['score'], len(ids), evaluation_identity, tuple(rows))
        runtime_path, ids_path = directory / 'runtime.json', directory / 'sample_ids.json'
        write_json(runtime_path, runtime_with_bank(self.runtime, bank))
        write_json(ids_path, ids)
        native = directory / 'rollouts'
        cmd = [sys.executable, str(self.runner), '--config', str(runtime_path),
               '--execution-config', str(self.execution), '--dataset-root', str(self.dataset_root),
               '--benchmarks', 'crossvid', '--sample-ids-file', str(ids_path),
               '--output', str(native), '--defer-open-qa-judge']
        if (native / 'run_manifest.json').exists():
            cmd.append('--resume')
        print(json.dumps({'phase':'evaluate', 'partition':partition, 'bank':bank.sha256, 'samples':len(ids)}), flush=True)
        with (directory / 'console.log').open('a') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
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
                    'samples':len(ids), 'score':score, 'scores':scores, 'raw_sha256':raw_sha,
                    'judge':self.judge.identity, 'metric':'CrossVid ten-task macro; CCQA point-weighted'}
        write_json(artifact_path, artifact)
        print(json.dumps({'phase':'scored', 'partition':partition, 'bank':bank.sha256,
                          'samples':len(ids), 'official_score':score}), flush=True)
        return Evaluation(partition, bank.sha256, score, len(ids), evaluation_identity,
                          tuple(rows) if partition == 'train' else ())

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
