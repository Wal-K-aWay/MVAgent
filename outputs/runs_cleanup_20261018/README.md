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

In progress. Final counts and external persistence verification will be added
when the single Modal cleanup task completes.
