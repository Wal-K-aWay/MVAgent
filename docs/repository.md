# Repository layout and results

| Path | Purpose |
|---|---|
| `src/` | MVAgent, model adapters, shared evaluation and skill generation |
| `configs/` | Inference/generation settings and frozen split manifests |
| `eval/` | MVAgent evaluation, scoring, trajectory export and required annotation metadata |
| `scripts/` | Supported preprocessing, visualization and skill-management tools |
| `tests/` | Runtime, evaluation and generation regression checks |
| `docs/` | Shared documentation, historical findings and protocol differences |
| `demo.py`, `requirements.txt` | Demo entry point and environment dependencies |

Local agent instructions, session notes, worktrees, analysis artifacts, result
directories and reference clones are excluded from the public tree. Keep these
locally; `.gitignore` prevents accidental addition. Model-facing prompts and authored
skills under `src/` are part of the implementation and remain versioned.
When changing optimizer prompts or schemas, keep the adjacent Chinese mirrors
consistent, including action names, JSON fields and template variables. Changes to
runtime selector prompts or authored skill text also require the corresponding
Chinese documentation to be updated.

## Released results

Existing Releases and their result attachments are retained:

| Method | Release |
|---|---|
| MVAgent 9B / 27B / 35B-A3B | [MVAgent results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019) |
| Qwen3.5 E2E | [E2E results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/qwen35-e2e-results-20261017) |
| AgentCVR | [AgentCVR results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/agentcvr-results-20261018) |
| LensWalk | [LensWalk results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019) |
| Video-RSI | [Video-RSI results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/video-rsi-results-20261020) |

Download the named result attachments from the Release page; GitHub's automatic
“Source code” archives contain the repository, not the result attachments.
Use the published SHA256 values to verify downloads. Original experiment records
remain in the runs volume; compact public packages do not replace those originals.

## Historical source and cleanup boundary

The tree before this cleanup is
[`fbdcefac2bf2f20cedd62e17c9049497fabd6823`](https://github.com/Wal-K-aWay/MVAgent/tree/fbdcefac2bf2f20cedd62e17c9049497fabd6823).
It retains the old portable result snapshots and intermediate experiment scripts
in Git history. Historical script names in [experiments.md](experiments.md) refer
to that history or to the explicitly named experiment branch, not to supported
current entry points. No Git history or Release is rewritten by this cleanup.
A normal full clone still downloads historical Git objects.

The cleanup preserves the contents of runtime code, model-facing prompts, inference
and split configurations and dependencies. The follow-up evaluation cleanup removes
the E2E runner and moves required CVBench metadata unchanged into `eval/agent_eval/`.
The scoring formulas and Judge prompt are preserved; the optional E2E report
comparison is removed. The Actor-pool regression is retained without E2E imports.
Completed answers and scores are not recomputed. Existing jobs keep their frozen
source and paths; they must not be switched to a new checkout while running.

An old shared development checkout may contain local modifications that differ from
the accepted public runtime. Cleaning its auxiliary files does not authorize
resetting those modifications. Keep a local snapshot before retiring worktrees,
and use a separate clean checkout for public-repository maintenance.

The skill cleanup removes previous evolution algorithms, prompts, training recipes
and optimizer-only infrastructure from the current tree. Shared benchmark code
moves unchanged to `src/evaluation/`; one-shot generation is organized under
`src/skill_evolution/generation/`. The pre-cleanup source is `de28149`; its algorithms
and negative findings remain in Git history and frozen experiment artifacts.
