# Modal storage cleanup — 2026-10-16

The user authorized the four cleanup candidates discussed in this session.
This work preserves raw experimental evidence; only redundant downloads and
Python bytecode are deleted without an archive. All data stays on Modal.

## Scope and dependency checks

- Bytecode: four completed runs (`e2e_full_20261012`,
  `repro_expanded_session_20261012_r3`, `external_vam65_20261015`,
  `external_upstream_nc80_20261015`). Only regular `.pyc` files and empty
  `__pycache__` directories are removed.
- Archive: `devbox/repro_expanded_session_20261012_r3/{agent,stress}`.
  Preserve every remaining file, directory and symbolic link in sibling
  `agent.tar.gz` and `stress.tar.gz` archives before removing loose trees.
- Redundant download: `/weights/AgentCVR-8B-original`. The existing
  `devbox/agentcvr_20261016/assets.json` records the original HF repository,
  exact revision and checksums. Actual H100 service command records must point
  to `AgentCVR-8B-merged`; all four merged shards and original provenance files
  must match the recorded SHA256 before deletion.
- **NC80 media is retained.** The live LensWalk cache manifest
  `devbox/lenswalk_full_35b_20261016/media_cache/6f9c15c7996b4d499e9cdcbe.json`
  directly references `devbox/external_upstream_nc80_20261015/prepared/media/crossvid_NC_80/`.
  The old run being superseded does not make this shared media disposable.

The active LensWalk and PRO9 27B/35B Sandbox commands were checked before work.
AgentCVR continues to use its merged Master, Vision model and Whisper.
No active experiment, source snapshot, model service or fixed input cache is modified.

## Verification and restoration

The fixed-scope script is `scripts/storage_cleanup_20261016.py`, invoked only
via `ssh modal-gpu` and Modal CPU. Its remote self-test covers regular files,
empty directories, symbolic links, same-size/same-mtime data corruption and an
extra unarchived file. Both corruption cases must prevent source removal.

Each archive is compared byte-for-byte with its source using GNU tar; the
complete file/directory/link inventory must remain unchanged. After commit,
the archive sizes and manifests are checked through the external Volume API.
Finalization rechecks SHA256, inventory and tar contents before removing sources.
Machine-readable inventories, provenance and action records are retained at
`devbox/storage_cleanup_20261016/` in the runs Volume.

Archived paths must be restored before historical scripts expecting loose
files can run. With the destination absent, use `tar -xzf <archive> -C /runs`.
The per-archive marker records its full path and checksum. Restore AgentCVR's
original checkpoint from the pinned HF revision before rerunning the FSDP merger;
the old preparation script's historical completion manifest is not proof that
the deleted download is still present.

## Other old experiments

- `tp8_cache_20261014`: failed setup with zero inference outputs; retain its
  failure record and frozen code. Suitable for archive rather than direct deletion.
- `tp8_cache_20261014_r2` and `_r3`: retired TP8/prefix-cache experiments. They
  substantiate the negative speed/reproducibility conclusion; archive candidates.
- `external_vam65_20261015`: VAM is retired, but its raw outputs, scores and
  timing data still underpin comparisons. Archive candidates, not disposable results.
- `repro_expanded_session_20261012_r2`: contains the 35B stress results used in
  the final expanded reproducibility report. Do not delete it as an obsolete retry.

No additional experiment deletion is included in this authorization.

The read-only candidate inventory found:

| Directory under `devbox/` | Bytes | Regular files | Directories |
|---|---:|---:|---:|
| `tp8_cache_20261014` | 236,634,252 | 2,805 | 832 |
| `tp8_cache_20261014_r2` | 790,068,550 | 2,926 | 913 |
| `tp8_cache_20261014_r3` | 558,472,404 | 2,403 | 736 |
| `repro_expanded_session_20261012_r2` (retain) | 3,268,155,195 | 9,219 | 2,507 |

The earlier whole-volume scan measured `external_vam65_20261015` at
5,785,626,465 bytes; this operation removes 1,379,425 bytes of its bytecode.
The remaining VAM data plus the three TP8 directories total 7,369,422,246 bytes.
This is candidate input size, **not** an estimate of archive savings.

## Execution status

In progress. Final reclaimed bytes, file counts and verification results will
be recorded here after the Modal actions complete.
