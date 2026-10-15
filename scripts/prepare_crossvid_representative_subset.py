#!/usr/bin/env python3
"""Freeze a metadata-stratified CrossVid development panel, without model calls.

Selection never reads predictions or answer labels. Existing Train/Gate source
paths, UAV scene identities and exact-byte duplicates are excluded first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mvagent.utils.media import probe_video_info
from skill_evolution.infra.data import DataSplitManifest, SplitSample, group_by_media
from skill_evolution.infra.store import file_fingerprint, write_json

QUOTAS = dict(BU=232, CC=218, CCQA=239, FSA=616, MOC=155,
              MSR=163, NC=334, PEA=261, PI=100, PSS=182)
NUMERIC = ("total_seconds", "max_seconds", "min_seconds", "duration_imbalance",
           "video_count", "question_chars", "min_fps", "max_pixels", "source_seconds",
           "temporal_segments", "reference_seconds", "object_count")


def allocate(capacities: dict[str, int], target: int) -> dict[str, int]:
    """Proportional integer allocation, with >=1 per nonempty stratum."""
    if not capacities or any(v <= 0 for v in capacities.values()):
        raise ValueError("Strata must be nonempty")
    if not len(capacities) <= target <= sum(capacities.values()):
        raise ValueError("Quota cannot cover all strata or exceeds population")
    total = sum(capacities.values())
    ideal = {k: target * n / total for k, n in capacities.items()}
    result = {k: max(1, int(v)) for k, v in ideal.items()}
    while sum(result.values()) < target:
        key = min((k for k in result if result[k] < capacities[k]),
                  key=lambda k: (result[k] - ideal[k], k))
        result[key] += 1
    while sum(result.values()) > target:
        key = min((k for k in result if result[k] > 1),
                  key=lambda k: (ideal[k] - result[k], k))
        result[key] -= 1
    return result


def source_paths(row: dict, task: str, root: Path) -> list[str]:
    if task in {"MOC", "MSR"}:
        return []  # Both annotated views share the explicit original UAV vid.
    if "videos" in row:
        names = row["videos"]
    elif "video" in row:
        names = [row["video"]]
    else:
        names = [row["video A"], row["video B"]]
    return sorted({str((root / "videos" / name).resolve()) for name in names})


def build_rows(root: Path) -> list[dict]:
    native = {f"crossvid:{task}:{r['id']}": r for task in QUOTAS
              for r in json.loads((root / "QA" / f"{task}.json").read_text())}
    rows = []
    for line in (root / "qa.jsonl").read_text().splitlines():
        qa = json.loads(line)
        sid, task = qa["id"], qa["task"]
        r = native[sid]
        inputs = [str((root / p).resolve()) for p in qa["videos"].values()]
        parents = source_paths(r, task, root)
        all_paths = sorted(set(inputs + parents))
        for p in all_paths:
            if not Path(p).is_file():
                raise FileNotFoundError(f"{sid}: {p}")
        keys = [f"path:{p}" for p in all_paths]
        if task in {"MOC", "MSR"}:
            keys.append(f"uav:{r['vid']}")
        durations = r.get("duration", [])
        durations = durations if isinstance(durations, list) else [durations]
        segments = sum(len(x) for x in r.get("segments", {}).values())
        ref = r.get("ref_segment", [])
        rows.append(dict(sample_id=sid, task=task, inputs=inputs, paths=all_paths,
                         source_keys=keys, parent_paths=parents,
                         question_chars=len(qa["question"]),
                         option_count=len(qa.get("options") or []),
                         source_seconds=sum(float(x) for x in durations),
                         temporal_segments=segments or len(inputs),
                         reference_seconds=float(ref[1] - ref[0]) if ref else 0.,
                         object_count=len(r.get("objects", []))))
    if len(rows) != 9015 or len({r['sample_id'] for r in rows}) != len(rows):
        raise ValueError("Expected 9015 unique CrossVid rows")
    return sorted(rows, key=lambda r: r["sample_id"])


def probe_all(paths: list[str], output: Path, workers: int) -> dict:
    """Reuse only metadata whose path/size/mtime and probing source match."""
    source_hash = file_fingerprint(ROOT / "src/mvagent/utils/media.py")
    cache = json.loads(output.read_text()) if output.exists() else {}
    if cache.get("probe_source_sha256") != source_hash:
        cache = {"probe_source_sha256": source_hash, "files": {}}
    entries = cache["files"]
    todo = []
    for path in paths:
        stat = Path(path).stat()
        identity = [stat.st_size, stat.st_mtime_ns]
        if entries.get(path, {}).get("stat") != identity:
            todo.append((path, identity))
    print(f"Metadata: {len(paths)} paths, {len(todo)} need probing", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_video_info, p): (p, s) for p, s in todo}
        for index, future in enumerate(as_completed(futures), 1):
            p, stat = futures[future]
            entries[p] = {"stat": stat, "metadata": future.result()}
            if index % 250 == 0:
                write_json(output, cache)
                print(f"Metadata {index}/{len(todo)}", flush=True)
    write_json(output, cache)
    return entries


def summary(rows: list[dict]) -> dict:
    result = {"n": len(rows)}
    for field in NUMERIC:
        values = np.asarray([r[field] for r in rows], dtype=float)
        result[field] = dict(mean=float(values.mean()), **{
            name: float(value) for name, value in zip(
                ("min", "p10", "p25", "p50", "p75", "p90", "max"),
                np.quantile(values, [0, .1, .25, .5, .75, .9, 1]))})
    result["video_count_histogram"] = dict(sorted(Counter(str(r['video_count']) for r in rows).items()))
    result["unique_source_keys"] = len({k for r in rows for k in r['source_keys']})
    groups = Counter(group_by_media({r['sample_id']: r['source_keys'] for r in rows}).values())
    result["source_connected_components"] = len(groups)
    result["largest_component_questions"] = max(groups.values())
    return result


def sample_task(rows: list[dict], target: int, seed: int) -> tuple[list[dict], dict]:
    # Nonempty bins preserve ties. Top duration decile is separated explicitly.
    cuts = np.unique(np.quantile([r['total_seconds'] for r in rows], [.25, .5, .75, .9]))
    qcut = float(np.median([r['question_chars'] for r in rows]))
    cells = defaultdict(list)
    for r in rows:
        duration_bin = int(np.searchsorted(cuts, r['total_seconds'], side='left'))
        multi_range = r['temporal_segments'] > r['video_count']
        key = f"v{r['video_count']}:d{duration_bin}:q{int(r['question_chars'] > qcut)}:m{int(multi_range)}"
        cells[key].append(r)
    counts = allocate({k: len(v) for k, v in cells.items()}, target)
    selected, audit = [], {}
    for key, members in sorted(cells.items()):
        ordered = sorted(members, key=lambda r: r['sample_id'])
        random.Random(f"{seed}:{rows[0]['task']}:{key}").shuffle(ordered)
        n, population = counts[key], len(ordered)
        for r in ordered[:n]:
            selected.append({**r, "stratum": key, "inclusion_probability": n / population,
                             "population_weight": population / n})
        audit[key] = {"population": population, "selected": n, "probability": n / population}
    return selected, dict(duration_cuts=cuts.tolist(), question_median=qcut, cells=audit)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/home/kww/datasets/Multi-Video/CrossVid'))
    parser.add_argument('--exclude', type=Path, action='append', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20260919)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.manifest.exists():
        raise FileExistsError(f"Refusing to replace frozen subset: {args.manifest}")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = build_rows(args.root)
    by_id = {r['sample_id']: r for r in rows}
    excluded_ids = {s.sample_id for p in args.exclude for s in DataSplitManifest.from_json(p).samples}
    blocked = [by_id[sid] for sid in sorted(excluded_ids & by_id.keys())]
    if not blocked:
        raise ValueError("Exclusion manifests contained no CrossVid IDs")
    blocked_keys = {k for r in blocked for k in r['source_keys']}
    candidates = [r for r in rows if not set(r['source_keys']) & blocked_keys]
    # Identical byte content necessarily has equal file size. Hash every possible
    # size collision with excluded files, avoiding an unnecessary whole-media scan.
    blocked_paths = {p for r in blocked for p in r['paths']}
    size_groups = defaultdict(set)
    for p in blocked_paths:
        size_groups[Path(p).stat().st_size].add(p)
    candidate_paths = {p for r in candidates for p in r['paths']}
    collision_paths = sorted(p for p in candidate_paths if Path(p).stat().st_size in size_groups)
    hashes_path = args.output / 'collision_hashes.json'
    hashes = json.loads(hashes_path.read_text()) if hashes_path.exists() else {}
    def fingerprint(p):
        stat = Path(p).stat(); identity = [stat.st_size, stat.st_mtime_ns]
        if hashes.get(p, {}).get('stat') != identity:
            hashes[p] = {'stat': identity, 'sha256': file_fingerprint(p)}
        return hashes[p]['sha256']
    relevant_sizes = {Path(p).stat().st_size for p in collision_paths}
    blocked_hashes = {fingerprint(p) for size in relevant_sizes for p in size_groups[size]}
    duplicates = set()
    for i, p in enumerate(collision_paths, 1):
        if fingerprint(p) in blocked_hashes:
            duplicates.add(p)
        if i % 100 == 0:
            write_json(hashes_path, hashes)
            print(f"Duplicate audit {i}/{len(collision_paths)}", flush=True)
    write_json(hashes_path, hashes)
    eligible = [r for r in candidates if not set(r['paths']) & duplicates]
    eligible_ids = {r['sample_id'] for r in eligible}
    print(f"Eligible {len(eligible)}/{len(rows)}, exact duplicate paths {len(duplicates)}", flush=True)
    info = probe_all(sorted({p for r in rows for p in r['inputs']}),
                     args.output / 'media_metadata.json', args.workers)
    for r in rows:
        metadata = [info[p]['metadata'] for p in r['inputs']]
        durations = [m['duration_sec'] for m in metadata]
        r.update(total_seconds=sum(durations), max_seconds=max(durations), min_seconds=min(durations),
                 duration_imbalance=max(durations) / sum(durations), video_count=len(metadata),
                 min_fps=min(m['fps'] for m in metadata),
                 max_pixels=max(m['width'] * m['height'] for m in metadata))
        if not r['source_seconds']:
            r['source_seconds'] = sum(durations)  # UAV uses presented-view duration.
    selected, strata, distributions = [], {}, {}
    for task, target in QUOTAS.items():
        full = [r for r in rows if r['task'] == task]
        population = [r for r in full if r['sample_id'] in eligible_ids]
        chosen, strata[task] = sample_task(population, target, args.seed)
        selected.extend(chosen)
        distributions[task] = {'full': summary(full), 'eligible': summary(population), 'selected': summary(chosen)}
    assert len(selected) == len({r['sample_id'] for r in selected}) == 2500
    assert not ({k for r in selected for k in r['source_keys']} & blocked_keys)
    selected_keys = {k for r in selected for k in r['source_keys']}
    reusable = [r['sample_id'] for r in rows if not set(r['source_keys']) & selected_keys]
    groups = group_by_media({r['sample_id']: r['source_keys'] for r in selected})
    manifest = DataSplitManifest('crossvid-lite2500-development-v1', args.seed, tuple(
        SplitSample(r['sample_id'], 'eval', groups[r['sample_id']])
        for r in sorted(selected, key=lambda r: r['sample_id'])))
    write_json(args.output / 'selected_features.json', selected)
    write_json(args.output / 'all_features.json', rows)
    write_json(args.output / 'future_training_source_guard.json', {
        'protected_source_keys': sorted(selected_keys),
        'path_disjoint_candidate_ids': sorted(reusable),
        'warning': 'Candidates still require content/source checks and separation from Gate; not a training manifest.'})
    audit = dict(protocol='crossvid-lite2500-development-v1', seed=args.seed, quotas=QUOTAS,
                 exclusion_manifests={str(p): file_fingerprint(p) for p in args.exclude},
                 source_files={str(p): file_fingerprint(p) for p in [args.root / 'qa.jsonl', *sorted((args.root/'QA').glob('*.json'))]},
                 script_sha256=file_fingerprint(Path(__file__)),
                 manifest_hash=manifest.manifest_hash, excluded_crossvid_ids=len(blocked),
                 eligible_counts=dict(Counter(r['task'] for r in eligible)),
                 content_duplicate_paths=sorted(duplicates),
                 collision_hashed_files=len(hashes), strata=strata, distributions=distributions,
                 model_outputs_used_for_selection=False,
                 future_source_disjoint_counts=dict(Counter(by_id[s]['task'] for s in reusable)),
                 limitations=[
                     'Development panel, not an untouched test or official CrossVid release.',
                     'Isolation covers original source files, prepared clips, shared UAV vid and exact-byte duplicates against exclusions.',
                     'Different movie clips from one film, assembly recordings from one session, re-encodings and semantic near-duplicates are not proven isolated.',
                     'Connected source components can be large; row count is not independent sample size.',
                     'Unequal within-task probabilities are retained for optional population-weighted estimates; official subset scores remain unweighted within each task.',
                     'Future enlarged Train/Gate is not silently reserved: its selection must exclude this frozen panel sources.',
                 ])
    write_json(args.output / 'audit.json', audit)
    # Publish membership only after all construction and isolation checks succeed.
    manifest.write(args.manifest)
    assert DataSplitManifest.from_json(args.manifest).manifest_hash == manifest.manifest_hash
    lines = ['# CrossVid Lite2500 抽样报告', '',
             '固定开发评估子集；没有推理或Judge调用，不按模型得分选题。', '',
             '|任务|全集|可用|抽取|总视频时长中位数：可用→抽取（秒）|视频数均值：可用→抽取|',
             '|---|---:|---:|---:|---:|---:|']
    for task, d in distributions.items():
        a, b = d['eligible'], d['selected']
        lines.append(f"|{task}|{d['full']['n']}|{a['n']}|{b['n']}|{a['total_seconds']['p50']:.1f}→{b['total_seconds']['p50']:.1f}|{a['video_count']['mean']:.2f}→{b['video_count']['mean']:.2f}|")
    lines.extend(['', '抽样：任务配额固定；任务内按视频数×总时长四分位/最高十分位×问题长度二分位×多段拼接状态分层；每非空层至少一题，其余近似比例分配，层内固定种子随机抽取。',
                  '', '原始视频时长与实际呈现时长分开；额外记录FPS、分辨率、最长/最短视频、长度不均衡、参考片段长度及对象数。这些描述性变量未全部强制匹配。',
                  '', 'audit.json给出全集、来源排除后可用总体、所选子集三方分布；selected_features.json记录每题纳入概率和权重。',
                  '', '## 边界', '', *['- '+x for x in audit['limitations']], ''])
    (args.output / 'report.md').write_text('\n'.join(lines))
    print(f"Frozen {args.manifest}: {manifest.manifest_hash}", flush=True)


if __name__ == '__main__':
    main()
