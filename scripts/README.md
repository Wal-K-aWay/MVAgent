# Supported tools

Run data preparation and model-dependent commands on the configured compute host.
Data preparation retains its existing interfaces and frozen manifests.
For a new research run, start with the entries below and follow the
[server runbook](../docs/server-runbook.md). Reuse a published split when continuing
an existing comparison; generating a new split is optional.

| Purpose | Entry point |
|---|---|
| Download CrossVid, restore deleted BU media from its pinned history, verify and prepare inputs | `prepare_crossvid_data.py` |
| Build a new ten-task CrossVid Train/Cal/Gate split | `prepare_crossvid_train_cal_gate_split.py` |
| Generate a one-shot LLM skill bank without task examples | `generate_skills.py` |
| Evolve role-specific skill libraries through Train/Cal/Gate | `evolve_skills.py` |

The remaining entries serve individual preparation, inspection or maintenance tasks.
`prepare_crossvid_data.py` already invokes the CrossVid preparation pipeline; do not
run its lower-level preparation commands concurrently on the same data directory.

| Purpose | Entry point |
|---|---|
| Legacy all-benchmark preparation; requires all inputs, `--check-only` checks layout, does not restore missing BU media | `prepare_all_multivideo.py` |
| Build the CrossVid manifest and derived media | `prepare_multivideo_benchmarks.py` |
| Resume CrossVid media preparation and validate completion | `run_crossvid_qa_preparation.py` |
| Build CVBench/MVU-Eval question manifests | `prepare_cvbench_mvu_qas.py` |
| Convert ordered frames to video | `frames_to_video.py` |
| Visualize question-referenced CrossVid objects | `visualize_crossvid_question_boxes.py` |
| Shared CrossVid question-format contract | `crossvid_protocol.py` |
| Build a CrossVid question-ID pool; not a Train/Cal/Gate manifest | `prepare_crossvid_clean_pool.py` |
| Freeze the metadata-stratified CrossVid evaluation panel | `prepare_crossvid_representative_subset.py` |
| Validate, edit, search and freeze skill libraries | `manage_skills.py` |

`__init__.py` supports imports shared by preprocessing and visualization.
Reuse existing frozen split manifests for comparisons; do not regenerate them to
change the seed or sampling composition.

`prepare_crossvid_train_cal_gate_split.py` now includes **all ten tasks, including
CCQA**, with default seed `0`, and refuses to overwrite its output. It creates a new
development split, excluding Lite2500 question IDs while keeping connected source
groups within one of Train/Cal/Gate. Source overlap with Lite2500 is reported, not
excluded. A quota failure writes no manifest; this seeded greedy assignment does
not prove that no other assignment exists. Before this handoff the script selected
nine closed tasks with default seed `20261006`; those historical manifests remain
unchanged and are not compatible with the current ten-task rolewise evaluator.
The new default `8,4,4` produces 80/40/40, not the historical 80/40/176 panel. See the
[server runbook](../docs/server-runbook.md) for the complete new-run command.
The retired choice-only and multibenchmark evolution split generators remain in
Git history. Their two-part or mixed-benchmark outputs do not meet the current
CrossVid-only, ten-task Train/Cal/Gate contract. The
[split inventory](../configs/skill_evolution/splits/README.md) distinguishes usable
research manifests, fixed evaluation panels and historical artifacts.

Trajectory processing stays with evaluation:

```bash
python eval/agent_eval/export_results.py /path/to/completed/run
```

This existing exporter reads saved records and writes tables; it does not call
models or rewrite source results. See [Agent evaluation](../eval/agent_eval/README.md)
for scoring/finalization. Skill generation is documented in
[`src/skill_evolution/`](../src/skill_evolution/README.md).

One-off ablations, selector experiments, timing probes, dated batch controllers
and historical report builders are removed from the current tree. Their findings,
including negative results and protocol differences, remain in
[the experiment history](../docs/experiments.md) and Git history.
The [repository guide](../docs/repository.md) identifies the historical source commit.
Regression checks are in [`tests/`](../tests/README.md).
The [one-shot generation protocol](../docs/llm-skill-generation.md) documents its
data boundary, frozen outputs, and Chinese prompt mirror.
