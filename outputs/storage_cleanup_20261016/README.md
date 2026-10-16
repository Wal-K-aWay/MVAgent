# Modal storage cleanup — 2026-10-16

The user's final instruction is **delete useless data only; do not compress**.
Both large gzip attempts were stopped before verification or source removal.
No Agent/stress source tree was deleted. The final script contains no archive
creation or archive-removal phase and installs no compression dependency.

## Authorized deletion

- Completed-run Python bytecode: 6,035 regular `.pyc` files, 55,736,366 bytes,
  plus empty `__pycache__` directories. The four roots are `e2e_full_20261012`,
  `repro_expanded_session_20261012_r3`, `external_vam65_20261015` and
  `external_upstream_nc80_20261015`, all under `/runs/devbox/`.
- Redundant `/weights/AgentCVR-8B-original` download. Actual H100 service
  command records reference `AgentCVR-8B-merged`. Before deletion, all four
  retained merged weight shards are checked against the existing SHA256
  manifest. Original download provenance/checksums are retained, without
  repeating the earlier full download hash verification.
- Partial archives created by this cleanup itself. Their removal is reported
  separately and is not counted as savings against the initial storage baseline.

Only the runs and weights Volumes are mounted; benchmark assets are untouched.
The script runs on Modal CPU through `modal-gpu`, without GPU allocation.
The final remote self-check covers valid files, corruption and path traversal.
Machine-readable action records and provenance stay in the runs Volume at
`devbox/storage_cleanup_20261016/`.

## Retained data and dependencies

- **NC80's 7.76 GB media must remain.** The live LensWalk manifest
  `devbox/lenswalk_full_35b_20261016/media_cache/6f9c15c7996b4d499e9cdcbe.json`
  references `devbox/external_upstream_nc80_20261015/prepared/media/crossvid_NC_80/`.
  A superseded run can still hold shared inputs.
- The approximately 68 GB Agent/stress records stay as loose files at their
  original locations, as requested. Raw outputs, frozen source and failure
  evidence are not removed.
- `repro_expanded_session_20261012_r2` is not a disposable retry: 3,268,155,195
  bytes / 9,219 files include the 35B stress results used by the final report.
- Fixed E2E media, reproducibility inputs, active experiments and their shared
  dependencies are retained.

## Additional old results reviewed, not deleted

| Directory under `devbox/` | Bytes | Regular files | Directories |
|---|---:|---:|---:|
| `tp8_cache_20261014` | 236,634,252 | 2,805 | 832 |
| `tp8_cache_20261014_r2` | 790,068,550 | 2,926 | 913 |
| `tp8_cache_20261014_r3` | 558,472,404 | 2,403 | 736 |

The first TP8 run has no inference output but retains its setup failure record
and frozen code. The other two substantiate the negative speed/reproducibility
conclusion. VAM is retired, but `external_vam65_20261015` still contains outputs,
scores and timing data used in published comparisons. Its size after bytecode
cleanup is 5,784,247,040 bytes. These four directories total 7,369,422,246 bytes;
being old does not establish that their evidence is useless. They were not deleted
or compressed under this work item.

To remerge AgentCVR in future, first redownload the pinned original checkpoint
revision `0ca8538758507589a5bada39d2377847649adc09` from
`xiaohua616/qwen8b_crossvidRL`. The old asset preparation script can otherwise
mistakenly treat its historical download manifest as proof the files still exist.

## Outcome

Deletion completed at 2026-10-16 09:18:44 UTC. Net reclaimed space against
the original baseline is **32,836,417,279 bytes (32.84 GB)**:

| Removed | Bytes | Regular files |
|---|---:|---:|
| Redundant original AgentCVR download | 32,780,680,913 | 58 |
| Python bytecode | 55,736,366 | 6,035 |

The self-created incomplete archive (3,781,165,056 bytes) was also removed;
it is excluded from net savings. No compressed archive was retained. The
Agent/stress trees and the shared NC80 video remain at their original paths.

The final CPU application `ap-Ey3TT3nTWIx9KqX84r0Ok7` exited successfully.
The retained merged weights matched all four recorded SHA256 checksums.
An external Volume SDK read confirmed the completion record, absence of the
original checkpoint and all temporary/finished archives, eight retained model
directories, both original Agent/stress directories and the shared NC80 video.
Final remote self-test: valid input, content-corruption rejection and path
traversal rejection passed. Local AST parsing and `git diff --check` passed.
Runs inode usage at the final job mount was 433,027 / 500,000 (86.6%);
other experiments continue creating files, so this is a timestamped reading,
not a promise of fixed remaining capacity.
