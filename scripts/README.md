# Supported tools

Run data preparation and model-dependent commands on the configured compute host.
Data preparation retains its existing interfaces and frozen manifests.

| Purpose | Entry point |
|---|---|
| Prepare and validate all benchmark inputs | `prepare_all_multivideo.py` |
| Build the CrossVid manifest and derived media | `prepare_multivideo_benchmarks.py` |
| Resume CrossVid media preparation and validate completion | `run_crossvid_qa_preparation.py` |
| Build CVBench/MVU-Eval question manifests | `prepare_cvbench_mvu_qas.py` |
| Convert ordered frames to video | `frames_to_video.py` |
| Visualize question-referenced CrossVid objects | `visualize_crossvid_question_boxes.py` |
| Shared CrossVid question-format contract | `crossvid_protocol.py` |
| Build a CrossVid pool excluding evaluation source recordings | `prepare_crossvid_clean_pool.py` |
| Freeze the metadata-stratified CrossVid evaluation panel | `prepare_crossvid_representative_subset.py` |
| Build CrossVid Train/Cal/Gate splits | `prepare_crossvid_train_cal_gate_split.py` |
| Build choice-only or multibenchmark evolution splits | `prepare_crossvid_choice_evolution_split.py`, `prepare_multibench_skill_evolution_split.py` |
| Generate a one-shot LLM skill bank without task examples | `generate_skills.py` |
| Evolve role-specific skill libraries through Train/Cal/Gate | `evolve_skills.py` |
| Validate, edit, search and freeze skill libraries | `manage_skills.py` |

`__init__.py` supports imports shared by preprocessing and visualization.
Reuse existing frozen split manifests for comparisons; do not regenerate them to
change the seed or sampling composition.

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
