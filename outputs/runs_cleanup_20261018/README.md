# Runs cleanup and consolidation — 2026-10-18

The user authorized cleanup of obsolete runs content, useless directories and
mergeable duplicates. The existing preference is no compression. This work
keeps raw answers, scores, negative results, shared media and source files.

The fresh read-only inventory counted 505,477 entries against the runs Volume's
500,000 limit (371,391 files, 128,074 directories, 6,012 symbolic links). It
measured 2,392,843,461,246 logical file bytes. Earlier live Sandbox statvfs
readings were stale; a fresh mount reported zero free inodes.

## Fixed scope

Only experiment roots with a date of 2026-10-15 or earlier are eligible.
Current 2026-10-16/17/18 runs, undated roots and linked roots are excluded.
Actual new GPU Sandboxes were checked; the devbox App was recreated during
other work, so the old App ID is not an authoritative running-task list.

- Merge **identical Git object directories**, verified by relative paths,
  modes, file sizes and SHA256. Keep one already-persisted canonical store.
  Each repository retains its original working files, refs, index and HEAD;
  Git's standard `objects/info/alternates` points to the retained store.
- Verify the detached/branch HEAD and the complete object-ID set are unchanged
  after merging. Future Git writes remain local to the borrowing repository.
- Remove regular `.pyc` files only when the corresponding Python source exists.
- Remove empty directories bottom-up in eligible old runs, retaining the run
  root, Git internals and symbolic links.

No model weights or benchmark assets are mounted. No archive or compression
command is used. No experiment is restarted or modified.

## Safety and provenance

The initial Volume is over its inode limit, so creation of a new audit directory
can fail. Before removing duplicate objects, an intent comment is appended to
that repository's existing `.git/config` and committed. It records the canonical
store, duplicate fingerprint, entry/byte counts, original HEAD and full object-ID
set hash. Modal task logs also record each intent. Canonical bytes are never
removed. Once duplicate entries are removed, standard alternates are created,
verified and committed; full manifests are then persisted to
`devbox/runs_cleanup_20261018/` in the runs Volume.

The retained canonical object stores are shared dependencies. Future cleanup
must inspect Git alternates before removing these stores. Do not run destructive
Git garbage collection against a shared store without accounting for borrowers.
The merged repositories remain readable at their original paths; no extraction
or compression tooling is required.

The remote small fixture test verifies the historical-date boundary, an actual
Git commit, object-tree equality, identical HEAD/object-ID set after alternates,
file retrieval and `git fsck --full`. Local validation is AST parsing and
`git diff --check`; no project test suite, inference or Judge is needed.

## Outcome

Completed. The mutating job `ap-SAuBuMYoVKvhaI3K1RZzwQ` exited successfully,
followed by fresh-container verification `ap-4w1XhB5WtJIRkOfwodIVsa` (also successful).
The mutating helper was committed as `46ab20c`; the final helper additionally
provides read-only verification and rejects accidentally repeating completed cleanup.

| Action | Result |
|---|---:|
| Identical Git stores consolidated | 26 copies → 2 canonical stores + 24 alternates |
| Net entries eliminated by Git-store consolidation | 19,972 |
| Disposable bytecode files removed | 1,357 |
| Empty old-run directories removed | 1,345 |
| Total entries removed, before small audit-file overhead | **22,674** |
| Duplicate/bytecode logical bytes removed | **2,391,247,762 (2.39 GB)** |

All 24 repositories had identical HEAD and full object-ID sets before and after
merging, including verification from a newly mounted container. Their original
paths and working source files remain. No raw result, score, shared media,
negative-result evidence or model weight was deleted. No compression was performed.

The job's own post-cleanup mount reported 17,176 free inodes; the subsequent
fresh mount reported **477,220 used / 500,000, 22,780 free (95.444% used)**.
Other tasks operate on the shared Volume, so the full snapshot-to-snapshot
change is not attributed to this cleanup. The action manifest is authoritative
for this work item's removal counts.

The two retained Git repositories whose object stores are now shared are:

- `/runs/devbox/concise_system_smoke_20261013/frozen_repo/.git`
- `/runs/devbox/tp8_cache_20261014/freeze_setup_failed/.git`

Their age or the `freeze_setup_failed` name does **not** make these object stores
disposable. Borrower paths and original object hashes are listed in
`devbox/runs_cleanup_20261018/merged.json`; full scope and deletion records are in
`plan.json` and `completed.json`. Those JSON records remain only on Modal.

GitHub's inherited proxy failed TLS during backup. Per-command removal of proxy
environment variables and `http.proxy` allowed the existing `gh-kw` account to
push; no global proxy, credential, account or remote setting was changed.
