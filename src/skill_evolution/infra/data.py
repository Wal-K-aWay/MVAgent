from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Protocol

from .skills import hash_json, SkillSet
from .benchmarks.aggregation import MeanScoreAggregator
from .benchmarks.catalog import BenchmarkRecord


SPLIT_NAMES = ("train", "eval")
ALL_SPLIT_NAMES = (*SPLIT_NAMES, "cal", "test")


@dataclass(frozen=True)
class SplitSample:
    sample_id: str
    split: str
    group_id: str

    def __post_init__(self) -> None:
        sample_id = str(self.sample_id).strip()
        split = str(self.split).strip()
        group_id = str(self.group_id).strip()
        if not sample_id or not group_id:
            raise ValueError("Split sample_id and group_id must be non-empty.")
        if split not in ALL_SPLIT_NAMES:
            raise ValueError(f"Unknown split {split!r}; expected train, cal, eval, or test.")
        object.__setattr__(self, "sample_id", sample_id)
        object.__setattr__(self, "split", split)
        object.__setattr__(self, "group_id", group_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "sample_id": self.sample_id,
            "split": self.split,
            "group_id": self.group_id,
        }


@dataclass(frozen=True)
class DataSplitManifest:
    """Frozen group-disjoint membership; Test is for independent evaluation only."""

    dataset: str
    seed: int
    samples: tuple[SplitSample, ...]

    def __post_init__(self) -> None:
        dataset = str(self.dataset).strip()
        samples = tuple(self.samples)
        if not dataset:
            raise ValueError("Split dataset must be non-empty.")
        if not samples:
            raise ValueError("Split manifest must contain samples.")
        sample_ids = [item.sample_id for item in samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Split sample IDs must be unique.")
        present = {item.split for item in samples}
        if not present.issubset(ALL_SPLIT_NAMES):
            raise ValueError("Unknown split in manifest.")
        group_splits: dict[str, set[str]] = {}
        for item in samples:
            group_splits.setdefault(item.group_id, set()).add(item.split)
        leaked = sorted(group for group, names in group_splits.items() if len(names) > 1)
        if leaked:
            raise ValueError(
                "Source groups cannot cross split boundaries: "
                + ", ".join(leaked[:5])
            )
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "samples", samples)

    @classmethod
    def from_json(cls, path: str | Path) -> "DataSplitManifest":
        source = Path(path).expanduser().resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Split manifest must be a JSON object.")
        version = int(payload.get("version", 0))
        if version != 2:
            raise ValueError("Unsupported split manifest version.")
        raw_samples = payload.get("samples")
        if not isinstance(raw_samples, list):
            raise ValueError("Split manifest samples must be a list.")
        manifest = cls(
            dataset=str(payload.get("dataset") or ""),
            seed=int(payload.get("seed", 0)),
            samples=tuple(
                SplitSample(
                    sample_id=item["sample_id"],
                    split=item["split"],
                    group_id=item["group_id"],
                )
                for item in raw_samples
            ),
        )
        return manifest

    @classmethod
    def from_groups(
        cls,
        *,
        dataset: str,
        sample_groups: Mapping[str, str],
        seed: int = 0,
        train_fraction: float = 0.67,
        eval_fraction: float | None = None,
    ) -> "DataSplitManifest":
        """Build one deterministic two-way group split without row leakage."""
        train_fraction = float(train_fraction)
        if not 0.0 < train_fraction < 1.0:
            raise ValueError("train_fraction must be in (0, 1).")
        if eval_fraction is not None:
            eval_fraction = float(eval_fraction)
            if not 0.0 < eval_fraction < 1.0:
                raise ValueError("eval_fraction must be in (0, 1).")
            if abs(train_fraction + eval_fraction - 1.0) > 1e-9:
                raise ValueError(
                    "Two-way train_fraction and eval_fraction must sum to 1.0."
                )
        groups: dict[str, list[str]] = {}
        for raw_sample_id, raw_group_id in sample_groups.items():
            sample_id = str(raw_sample_id).strip()
            group_id = str(raw_group_id).strip()
            if not sample_id or not group_id:
                raise ValueError("sample_groups keys and values must be non-empty.")
            groups.setdefault(group_id, []).append(sample_id)
        if len(groups) < 2:
            raise ValueError("At least two source groups are required for train/eval.")

        ordered_groups = sorted(groups)
        random.Random(int(seed)).shuffle(ordered_groups)
        total = sum(len(groups[group]) for group in ordered_groups)
        train_target = max(1, min(total - 1, round(total * train_fraction)))
        assignments: dict[str, str] = {}
        counts = {name: 0 for name in SPLIT_NAMES}
        for index, group_id in enumerate(ordered_groups):
            remaining_groups = len(ordered_groups) - index
            empty = [name for name in SPLIT_NAMES if counts[name] == 0]
            if remaining_groups == len(empty) and empty:
                split = empty[0]
            elif counts["train"] < train_target:
                split = "train"
            else:
                split = "eval"
            assignments[group_id] = split
            counts[split] += len(groups[group_id])

        samples = tuple(
            SplitSample(sample_id=sample_id, split=assignments[group_id], group_id=group_id)
            for group_id in sorted(groups)
            for sample_id in sorted(groups[group_id])
        )
        return cls(dataset=dataset, seed=seed, samples=samples)

    def ids(self, split: str) -> tuple[str, ...]:
        split = str(split).strip()
        if split not in ALL_SPLIT_NAMES:
            raise ValueError(f"Unknown split: {split!r}")
        return tuple(item.sample_id for item in self.samples if item.split == split)

    @property
    def manifest_hash(self) -> str:
        return hash_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "dataset": self.dataset,
            "seed": self.seed,
            "samples": [item.to_dict() for item in self.samples],
        }

    def write(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target




EVALUATOR_POLICY = "execution-v3"

@dataclass(frozen=True)
class EvaluationContext:
    """Frozen rollout and scoring identity, excluding Skill text."""

    sample_ids: tuple[str, ...]
    input_hashes: Mapping[str, str]
    rollout_seed: int
    execution_identity: Mapping[str, str]
    evaluation_identity: Mapping[str, str]
    repeat_id: str = "0"

    def __post_init__(self) -> None:
        sample_ids = tuple(str(item).strip() for item in self.sample_ids if str(item).strip())
        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("EvaluationContext sample IDs must be non-empty and unique.")
        input_hashes = {str(key): str(value) for key, value in self.input_hashes.items()}
        if set(input_hashes) != set(sample_ids):
            raise ValueError("input_hashes must contain exactly the frozen sample IDs.")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())
            for value in input_hashes.values()
        ):
            raise ValueError("Every input_hashes value must be a SHA256 digest.")
        input_hashes = {key: value.lower() for key, value in input_hashes.items()}
        execution = {str(key): str(value) for key, value in self.execution_identity.items()}
        evaluation = {str(key): str(value) for key, value in self.evaluation_identity.items()}
        required_execution = {
            "benchmark_adapter",
            "effective_config",
            "runtime_snapshot",
            "decoding",
        }
        evaluation.setdefault("aggregator", MeanScoreAggregator.identity)
        required_evaluation = {
            "scorer",
            "aggregator",
            "projector",
            "evaluator_prompt",
        }
        if missing := sorted(required_execution - set(execution)):
            raise ValueError("Execution identity is missing: " + ", ".join(missing))
        if missing := sorted(required_evaluation - set(evaluation)):
            raise ValueError("Evaluation identity is missing: " + ", ".join(missing))
        object.__setattr__(self, "sample_ids", sample_ids)
        object.__setattr__(self, "input_hashes", input_hashes)
        object.__setattr__(self, "rollout_seed", int(self.rollout_seed))
        object.__setattr__(self, "execution_identity", execution)
        object.__setattr__(self, "evaluation_identity", evaluation)

    @property
    def execution_context_hash(self) -> str:
        return hash_json(dict(self.execution_identity))

    @property
    def context_hash(self) -> str:
        return hash_json(
            {
                "ordered_inputs": [
                    [sample_id, self.input_hashes[sample_id]] for sample_id in self.sample_ids
                ],
                "rollout_seed": self.rollout_seed,
                "repeat_id": self.repeat_id,
                "execution_context_hash": self.execution_context_hash,
                "evaluation_identity": dict(self.evaluation_identity),
                "evaluator_policy": EVALUATOR_POLICY,
            }
        )

    def rollout_cache_key(self, skill_set: SkillSet, sample_id: str) -> str:
        if sample_id not in self.input_hashes:
            raise ValueError(f"Unknown sample ID: {sample_id}")
        return hash_json(
            {
                "sample_id": sample_id,
                "input_hash": self.input_hashes[sample_id],
                "skill_set_hash": skill_set.skill_set_hash(),
                "rollout_seed": self.rollout_seed,
                "repeat_id": self.repeat_id,
                "execution_context_hash": self.execution_context_hash,
            }
        )


@dataclass(frozen=True)
class EvaluationRequest:
    skill_set: SkillSet
    context: EvaluationContext
    sample_ids: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class RolloutArtifact:
    sample_id: str
    artifact: Mapping[str, Any]
    bucket: str = "default"
    status: str = "ok"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", str(self.sample_id).strip())
        object.__setattr__(self, "bucket", str(self.bucket or "default"))
        object.__setattr__(self, "status", str(self.status or "unknown"))
        if not self.sample_id:
            raise ValueError("RolloutArtifact.sample_id must be non-empty.")


class RolloutExecutor(Protocol):
    def execute(self, request: EvaluationRequest) -> Sequence[RolloutArtifact]: ...


def batches(ids, size, seed):
    if size < 1:
        raise ValueError("Batch size must be positive")
    ordered = list(ids)
    random.Random(seed).shuffle(ordered)
    return [tuple(ordered[start:start + size]) for start in range(0, len(ordered), size)]


def media_groups(records, fingerprints):
    """Connected components include transitive sharing, not just equal video sets."""
    return group_by_media({sid: [fingerprints[p] for p in record.sample.videos.values()]
                           for sid, record in records.items()})


def group_by_media(sample_media):
    parents = {sid: sid for sid in sample_media}
    owner = {}
    def find(sid):
        while parents[sid] != sid:
            parents[sid] = parents[parents[sid]]
            sid = parents[sid]
        return sid
    for sid, media_ids in sample_media.items():
        for media in media_ids:
            if media in owner:
                a, b = find(sid), find(owner[media])
                parents[max(a, b)] = min(a, b)
            else:
                owner[media] = sid
    return {sid: find(sid) for sid in sample_media}


def audit_split(manifest, records, fingerprints):
    groups = media_groups(records, fingerprints)
    members = {name: [sid for sid in manifest.ids(name) if sid in records] for name in ALL_SPLIT_NAMES}
    splits = {}
    for name, ids in members.items():
        for sid in ids:
            splits.setdefault(groups[sid], set()).add(name)
    overlap = {name: [sid for sid in ids if len(splits[groups[sid]]) > 1] for name, ids in members.items()}
    return {"counts": {name: len(ids) for name, ids in members.items()},
            "overlapping_ids": overlap, "media_groups": groups}


def build_evaluation_context(
    *,
    name: str,
    sample_ids: tuple[str, ...],
    records: Mapping[str, BenchmarkRecord],
    base_config_sha256: str,
    runtime_snapshot_sha256: str,
    manifest_hash: str,
    scorer_identity: Mapping[str, Any],
    aggregator_identity: str,
    repeat_id: str = "0",
    media_fingerprints: Mapping[str, str] | None = None,
) -> EvaluationContext:
    from .store import file_fingerprint
    ground_truth_hash = hash_json(
        [
            [sample_id, list(records[sample_id].sample.ground_truth)]
            for sample_id in sample_ids
        ]
    )
    open_qa_annotation_hash = hash_json(
        [
            [
                sample_id,
                records[sample_id].judge_question,
                records[sample_id].reference_answer,
                list(records[sample_id].sample.ground_truth),
            ]
            for sample_id in sample_ids
            if records[sample_id].sample.task.value == "open_qa"
        ]
    )
    return EvaluationContext(
        sample_ids=sample_ids,
        input_hashes={
            sample_id: hash_json(
                {
                    "question": records[sample_id].sample.question,
                    "videos": [[key, media_fingerprints[path] if media_fingerprints else file_fingerprint(path)]
                               for key, path in records[sample_id].sample.videos.items()],
                }
            )
            for sample_id in sample_ids
        },
        rollout_seed=0,
        repeat_id=repeat_id,
        execution_identity={
            "benchmark_adapter": "mvagent-multibench-canonical-v1",
            "effective_config": base_config_sha256,
            "runtime_snapshot": runtime_snapshot_sha256,
            "decoding": "mvagent-configured-deterministic",

        },
        evaluation_identity={
            "scorer": (
                str(scorer_identity.get("type") or "multibench-scorer")
                + ":"
                + hash_json(dict(scorer_identity))
            ),
            "aggregator": aggregator_identity,
            "projector": "trajectory-projector-v7-normalized-evaluation",
            "evaluator_prompt": "none",
            "ground_truth_hash": ground_truth_hash,
            "open_qa_annotation_hash": open_qa_annotation_hash,
            "split_manifest_hash": manifest_hash,
        },
    )
