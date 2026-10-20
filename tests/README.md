# Runtime regression checks

These six checks were moved unchanged from `scripts/`. They protect supported
runtime behavior; historical experiment/probe scripts are not part of this directory.

Run individual checks in the configured remote project environment:

```bash
PYTHONPATH=src python tests/test_direct_answer.py
PYTHONPATH=src python tests/test_e2e_sync.py
PYTHONPATH=src python tests/test_model_token_audit.py
PYTHONPATH=src python tests/test_prefix_cache_usage.py
PYTHONPATH=src python tests/test_agent_finalize.py
PYTHONPATH=src python tests/test_short_video.py
```

The checks cover direct and forced answers, endpoint/CLI contracts, complete token
audits, cache accounting, deferred CCQA score aggregation and short-video clipping.
`test_model_token_audit.py` has a standalone assertion-based entry point, so
`unittest discover` alone does not execute every check.

The short-video check requires the original CrossVid MOC/552 view-B asset under
`/assets/crossvid/.mvagent_media/uav_question_boxes/`, FFmpeg and vLLM's decoder.
Other checks use synthetic records or model doubles but some import the full
project dependencies, including structured-output libraries.
Passing these checks is not a new benchmark measurement or a guarantee of
byte-identical outputs for arbitrary model inputs.
