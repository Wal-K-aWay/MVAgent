# Frozen experiment completion scripts

These files archive the one-off finalizer and completion handler submitted for
`devbox/external_methods_20261014`. They contain that run's paths, process IDs and
Sandbox ID. They are recovery records, not commands to rerun for a new experiment.

- `finalize.py` runs inside the experiment Sandbox, after the existing inference
  batches. It reuses the VAM GPU for the fixed CCQA Judge and writes final scores.
- `autoclose.py` runs on `modal-gpu`, detached from SSH. It waits for the inference
  and finalizer to exit, archives logs, verifies persisted score hashes from outside
  the volume mount, and terminates only that Sandbox.

No raw results, generated agent bundles, media, credentials or weights are included.
The code was syntax-checked; the live completion handler was confirmed running.
Its full completion path had not executed when this checkpoint was saved.
