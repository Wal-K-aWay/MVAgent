# Runtime regression checks

These checks protect supported MVAgent runtime behavior. Historical experiments
and the removed E2E runner are not part of this directory.

Run individual checks in the configured remote project environment:

```bash
PYTHONPATH=src python tests/test_direct_answer.py
PYTHONPATH=src python tests/test_model_pool.py
PYTHONPATH=src python tests/test_model_token_audit.py
PYTHONPATH=src python tests/test_prefix_cache_usage.py
PYTHONPATH=src python tests/test_agent_finalize.py
PYTHONPATH=src python tests/test_short_video.py
PYTHONPATH=src python tests/test_one_shot_skills.py
PYTHONPATH=src:. python tests/test_skill_evolution.py
PYTHONPATH=src:. python tests/test_skill_evaluation.py
PYTHONPATH=src:. python tests/test_evolution_snapshot.py
PYTHONPATH=src:. python tests/test_local_optimizer.py
PYTHONPATH=src python tests/test_evaluation_utilities.py
PYTHONPATH=src python tests/test_evaluation_snapshot.py
```

The checks cover direct and forced answers, model-pool configuration and question-level leasing, complete token
audits, cache accounting, deferred CCQA score aggregation and short-video clipping.
`test_model_token_audit.py` has a standalone assertion-based entry point, so
`unittest discover` alone does not execute every check.

The short-video check requires the original CrossVid MOC/552 view-B asset under
`/assets/crossvid/.mvagent_media/uav_question_boxes/`, FFmpeg and vLLM's decoder.
Other checks use synthetic records or model doubles but some import the full
project dependencies, including structured-output libraries.
Passing these checks is not a new benchmark measurement or a guarantee of
byte-identical outputs for arbitrary model inputs.

The one-shot generation check covers role/word limits, persistence of malformed or
truncated output, refusal to overwrite prior runs, merged banks, source snapshots and redaction.
It uses a model double and does not call an API.
The evaluation utility checks cover transitive source isolation, atomic-write failure
preservation, and closed-form official scores after the module relocation.

The evaluation snapshot check loads a synthetic closed-form sample, scores it,
changes the live workspace, verifies resume still uses the frozen evaluation code,
and rejects an altered snapshot. It performs no model calls or video decoding.

Generation checks also cover per-role cardinality bounds, forbidden extra fields,
role-specific Actor prompt/capacity inputs, and task-scoped hash-pinned runtime
configuration. Global-only generation disables an old Video bank without changing
the input configuration or Actor settings. No model API is used by these checks.

The generation CLI check uses the current DeepSeek configuration with a mocked HTTP
response, verifying JSON mode, thinking/high and one logged request per role without
authentication headers. It makes no network calls.

Evolution checks cover role-private information isolation, matched local contexts,
immutable single-role edits, saved-call resume, Cal gain rejected by Gate, official
macro/CCQA point weighting and Judge failure without overwriting raw rollouts.
The local optimizer check mocks pool preparation and HTTP transport, checking model/endpoint
binding, sync-server grammar/seed/token-audit fields, pool cleanup and unchanged commercial API routing.
