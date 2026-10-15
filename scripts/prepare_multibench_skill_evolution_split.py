#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from skill_evolution.infra.benchmarks import (
    EvaluationSample,
    crossvid_sample,
    cvbench_sample,
    mvu_eval_sample,
)
from skill_evolution.infra.data import DataSplitManifest, SplitSample, group_by_media
from skill_evolution.infra.store import file_fingerprint


CROSSVID_CHOICE_TASKS = ("BU", "CC", "MOC", "MSR", "NC", "PEA", "PI")
CROSSVID_NONCHOICE_TASKS = ("CCQA", "FSA", "PSS")
MVU_TASKS = ("Comparison", "Counting", "ICL", "KIR", "OR", "RAG", "SU", "TR")


@dataclass(frozen=True)
class SelectionRecord:
    sample_id: str
    dataset: str
    native_task: str
    output_task: str
    media: tuple[str, ...] = ()
    source_keys: tuple[str, ...] = ()

    @property
    def stratum(self) -> str:
        return f"{self.dataset}/{self.native_task}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_key(*parts: object) -> str:
    return hashlib.sha256(
        "\0".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()


def _validate_media(sample: EvaluationSample, *, sample_id: str) -> None:
    missing = [path for path in sample.videos.values() if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{sample_id} references missing media: " + ", ".join(missing[:3])
        )


def _crossvid_records(root: Path) -> tuple[list[SelectionRecord], Path]:
    source = root / "qa.jsonl"
    native = {
        f"crossvid:{task}:{row['id']}": row
        for task in (*CROSSVID_CHOICE_TASKS, *CROSSVID_NONCHOICE_TASKS)
        for row in json.loads((root / "QA" / f"{task}.json").read_text())
    }
    records: list[SelectionRecord] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = str(row.get("id") or "").strip()
        native_task = str(row.get("task") or "").strip().upper()
        if not sample_id or native_task not in {
            *CROSSVID_CHOICE_TASKS,
            *CROSSVID_NONCHOICE_TASKS,
        }:
            raise ValueError(f"Invalid CrossVid identity or task: {sample_id!r}.")
        sample = crossvid_sample(row, media_root=root)
        _validate_media(sample, sample_id=sample_id)
        original = native[sample_id]
        media = set(sample.videos.values())
        source_keys = ()
        if native_task in {"MOC", "MSR"}:
            source_keys = (f"source:crossvid:uav:{original['vid']}",)
        elif native_task in {"PI", "PSS", "PEA"}:
            parents = original["videos"] if native_task == "PEA" else [original["video"]]
            media.update(str((root / "videos" / path).resolve()) for path in parents)
            if any(not Path(path).is_file() for path in media):
                raise FileNotFoundError(f"{sample_id} references missing source media.")
        records.append(
            SelectionRecord(
                sample_id=sample_id,
                dataset="crossvid",
                native_task=native_task,
                output_task=sample.task.value,
                media=tuple(sorted(str(Path(p).resolve()) for p in media)),
                source_keys=source_keys,
            )
        )
    return records, source


def _json_records(
    *,
    root: Path,
    dataset: str,
    adapter,
) -> tuple[list[SelectionRecord], Path]:
    source = root / "QAs.json"
    rows = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{source} must contain a JSON list.")
    media_root = root / "videos"
    records: list[SelectionRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"{source} contains a non-object row.")
        raw_id = str(row.get("id") if row.get("id") is not None else "").strip()
        if not raw_id:
            raise ValueError(f"{source} contains an empty ID.")
        native_task = (
            str(row.get("task") or "").strip()
            if dataset == "mvu_eval"
            else "all"
        )
        if dataset == "mvu_eval" and native_task not in MVU_TASKS:
            raise ValueError(f"Unknown MVU-Eval task: {native_task!r}.")
        sample_id = (
            f"mvu_eval:{native_task}:{raw_id}"
            if dataset == "mvu_eval"
            else f"cvbench:{raw_id}"
        )
        sample = adapter(row, media_root=media_root)
        _validate_media(sample, sample_id=sample_id)
        records.append(
            SelectionRecord(
                sample_id=sample_id,
                dataset=dataset,
                native_task=native_task,
                output_task=sample.task.value,
                media=tuple(str(Path(p).resolve()) for p in sample.videos.values()),
            )
        )
    return records, source


def _requested_counts(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for task in CROSSVID_CHOICE_TASKS:
        counts[f"crossvid/{task}"] = {
            "train": args.crossvid_choice_train_per_task,
            "eval": args.crossvid_choice_eval_per_task,
        }
    for task in CROSSVID_NONCHOICE_TASKS:
        counts[f"crossvid/{task}"] = {
            "train": args.crossvid_nonchoice_train_per_task,
            "eval": args.crossvid_nonchoice_eval_per_task,
        }
    for task in MVU_TASKS:
        counts[f"mvu_eval/{task}"] = {
            "train": args.mvu_train_per_task,
            "eval": args.mvu_eval_per_task,
        }
    counts["cvbench/all"] = {
        "train": args.cvbench_train,
        "eval": args.cvbench_eval,
    }
    if any(value < 1 for split_counts in counts.values() for value in split_counts.values()):
        raise ValueError("Every requested train/eval stratum count must be positive.")
    return counts


def _excluded_ids(paths: Sequence[str]) -> tuple[set[str], list[dict[str, Any]]]:
    sample_ids: set[str] = set()
    audit: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        manifest = DataSplitManifest.from_json(path)
        sample_ids.update(item.sample_id for item in manifest.samples)
        audit.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "sample_count": len(manifest.samples),
            }
        )
    return sample_ids, audit


def _select(
    *,
    records: Sequence[SelectionRecord],
    requested: Mapping[str, Mapping[str, int]],
    seed: int,
    excluded_sample_ids: set[str],
) -> tuple[DataSplitManifest, dict[str, Any]]:
    by_id = {record.sample_id: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("Benchmark sample IDs must be globally unique.")
    by_stratum: dict[str, list[SelectionRecord]] = defaultdict(list)
    for record in records:
        by_stratum[record.stratum].append(record)

    fingerprints: dict[str, str] = {}
    owners: dict[str, str] = {}
    selected_media: dict[str, tuple[str, ...]] = {}

    def media_keys(record: SelectionRecord) -> tuple[str, ...]:
        for path in record.media:
            if path not in fingerprints:
                fingerprints[path] = file_fingerprint(path)
        return (*record.source_keys,
                *(f"path:{path}" for path in record.media),
                *(f"sha256:{fingerprints[path]}" for path in record.media))

    for sample_id in sorted(excluded_sample_ids & by_id.keys()):
        owners.update(dict.fromkeys(media_keys(by_id[sample_id]), "excluded"))

    selected: dict[str, dict[str, list[SelectionRecord]]] = {
        split: {stratum: [] for stratum in requested} for split in ("train", "eval")
    }
    # Alternate splits and tasks so the first partition cannot exhaust shared media.
    strata = sorted(requested, key=lambda s: (len(by_stratum[s]) / sum(requested[s].values()), s))
    candidates = {
        (split, stratum): iter(sorted(by_stratum[stratum], key=lambda r: _stable_key(seed, split, stratum, r.sample_id)))
        for split in selected for stratum in strata
    }
    for index in range(max(n for counts in requested.values() for n in counts.values())):
        for split in selected:
            for stratum in strata:
                if index >= requested[stratum][split]:
                    continue
                for record in candidates[split, stratum]:
                    if record.sample_id in selected_media or record.sample_id in excluded_sample_ids:
                        continue
                    paths = (*record.source_keys, *(f"path:{p}" for p in record.media))
                    if any(key in owners and owners[key] != split for key in paths):
                        continue
                    keys = media_keys(record)
                    if any(key in owners and owners[key] != split for key in keys):
                        continue
                    selected[split][stratum].append(record)
                    selected_media[record.sample_id] = keys
                    owners.update(dict.fromkeys(keys, split))
                    break
                else:
                    raise ValueError(
                        f"{stratum}: only {len(selected[split][stratum])} of "
                        f"{requested[stratum][split]} {split} samples fit the media isolation constraint."
                    )

    groups = group_by_media(selected_media)

    samples: list[SplitSample] = []
    selected_records: list[SelectionRecord] = []
    for split in ("train", "eval"):
        strata = sorted(selected[split])
        max_count = max(len(selected[split][stratum]) for stratum in strata)
        for index in range(max_count):
            for stratum in strata:
                if index >= len(selected[split][stratum]):
                    continue
                record = selected[split][stratum][index]
                samples.append(
                    SplitSample(
                        sample_id=record.sample_id,
                        split=split,
                        group_id=groups[record.sample_id],
                    )
                )
                selected_records.append(record)

    manifest = DataSplitManifest(
        dataset="mvagent-multibench-broad-v1",
        seed=seed,
        samples=tuple(samples),
    )
    record_by_id = {record.sample_id: record for record in selected_records}
    audit: dict[str, Any] = {
        "excluded_known_sample_count": len(excluded_sample_ids & set(by_id)),
        "selection_policy": "seeded-stratified-alternating-media-disjoint-v2",
        "requested_counts": requested,
        "available_samples_by_stratum": {s: len(rows) for s, rows in sorted(by_stratum.items())},
        "source_group_counts": {
            split: len({groups[sid] for sid in manifest.ids(split)}) for split in selected
        },
        "media_fingerprints": {p: fingerprints[p] for p in sorted({p for sid in selected_media for p in by_id[sid].media})},
        "source_keys": {sid: list(by_id[sid].source_keys) for sid in selected_media if by_id[sid].source_keys},
        "sample_counts": {
            split: len(manifest.ids(split)) for split in ("train", "eval")
        },
        "dataset_counts": {
            split: dict(
                sorted(
                    Counter(
                        record_by_id[sample_id].dataset
                        for sample_id in manifest.ids(split)
                    ).items()
                )
            )
            for split in ("train", "eval")
        },
        "native_task_counts": {
            split: dict(
                sorted(
                    Counter(
                        record_by_id[sample_id].stratum
                        for sample_id in manifest.ids(split)
                    ).items()
                )
            )
            for split in ("train", "eval")
        },
        "output_task_counts": {
            split: dict(
                sorted(
                    Counter(
                        record_by_id[sample_id].output_task
                        for sample_id in manifest.ids(split)
                    ).items()
                )
            )
            for split in ("train", "eval")
        },
        "integrity": {
            "test_sample_count": len(manifest.ids("test")),
            "duplicate_sample_ids": len(samples)
            - len({sample.sample_id for sample in samples}),
            "source_groups_crossing_splits": sum(
                len(
                    {
                        sample.split
                        for sample in samples
                        if sample.group_id == group_id
                    }
                )
                > 1
                for group_id in {sample.group_id for sample in samples}
            ),
        },
    }
    return manifest, audit


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a fresh, physical-media-group-disjoint train/eval manifest "
            "covering CrossVid, CVBench, and MVU-Eval."
        )
    )
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--exclude-manifest", action="append", default=[])
    parser.add_argument("--crossvid-choice-train-per-task", type=int, default=6)
    parser.add_argument("--crossvid-choice-eval-per-task", type=int, default=3)
    parser.add_argument("--crossvid-nonchoice-train-per-task", type=int, default=12)
    parser.add_argument("--crossvid-nonchoice-eval-per-task", type=int, default=6)
    parser.add_argument("--mvu-train-per-task", type=int, default=4)
    parser.add_argument("--mvu-eval-per-task", type=int, default=2)
    parser.add_argument("--cvbench-train", type=int, default=20)
    parser.add_argument("--cvbench-eval", type=int, default=15)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    dataset_root = Path(args.dataset_root).expanduser().resolve()
    crossvid, crossvid_source = _crossvid_records(dataset_root / "CrossVid")
    cvbench, cvbench_source = _json_records(
        root=dataset_root / "CVBench",
        dataset="cvbench",
        adapter=cvbench_sample,
    )
    mvu_eval, mvu_source = _json_records(
        root=dataset_root / "MVU-Eval",
        dataset="mvu_eval",
        adapter=mvu_eval_sample,
    )
    excluded_ids, excluded_audit = _excluded_ids(tuple(args.exclude_manifest))
    records = (*crossvid, *cvbench, *mvu_eval)
    manifest, audit = _select(
        records=records,
        requested=_requested_counts(args),
        seed=args.seed,
        excluded_sample_ids=excluded_ids,
    )
    target = manifest.write(args.output)
    audit.update(
        {
            "version": 1,
            "manifest": str(target),
            "manifest_sha256": _sha256(target),
            "manifest_hash": manifest.manifest_hash,
            "seed": args.seed,
            "source_record_counts": {
                "crossvid": len(crossvid),
                "cvbench": len(cvbench),
                "mvu_eval": len(mvu_eval),
            },
            "source_validation": {
                "globally_unique_sample_ids": True,
                "all_rows_normalized": True,
                "all_referenced_media_exist": True,
            },
            "sources": [
                {"path": str(path), "sha256": _sha256(path)}
                for path in (crossvid_source, cvbench_source, mvu_source,
                             *sorted((dataset_root / "CrossVid" / "QA").glob("*.json")))
            ],
            "excluded_manifests": excluded_audit,
        }
    )
    audit_target = (
        Path(args.audit_output).expanduser().resolve()
        if args.audit_output
        else target.with_suffix(".audit.json")
    )
    audit_target.parent.mkdir(parents=True, exist_ok=True)
    audit_target.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in audit.items() if k not in {"media_fingerprints", "source_keys"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
