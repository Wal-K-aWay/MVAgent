# RSI/VAM-only completion after the scope change

The user cancelled further MetaVideoAgent evaluation. Its completed outputs and
interrupted traces remain in the runs volume; it is excluded from new scoring.

- `score_remaining.py`: launch from `modal-gpu` with `modal run --env zheng-dev`.
  This one-off single-H100 function releases its GPU when the app exits.
- `finalize_remaining.py`: uses the saved inputs, predictions and R9 scoring code
  under `devbox/external_methods_20261014`. It records cancellation, merges RSI/VAM
  outputs, starts the fixed CCQA Judge and writes scores plus completion hashes.

These are run-specific recovery scripts, not new Actor evaluations. Do not launch
a second copy while the submitted completion task is active. Python syntax passed;
runtime assertions require exactly the 33 selected attempts for each retained method
and successful scoring of every valid prediction. The live job's scores remain the
validation evidence; submission alone does not mean scoring has completed.

The retired three-method finalizer and autoclose code are in Git commit `16d694f`.
No raw results, generated agent bundles, media, credentials or weights are included.
