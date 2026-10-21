# Shared evaluation utilities

These modules serve MVAgent evaluation and dataset preparation, independently of
skill generation or any optimization algorithm.

| Module | Responsibility |
|---|---|
| `benchmarks/` | Existing dataset adapters, official scoring, aggregation and Judge protocol |
| `data.py` | Frozen split manifests and connected media-source groups |
| `store.py` | Atomic JSON writes and content fingerprints for offline tools |

The benchmark implementation is moved unchanged from the retired evolution
infrastructure. Public callers use this package directly; there are no aliases to
the old modules. Optimizer checkpoints, candidate acceptance, rollout caches and
trajectory localization are removed. Existing experiments resume only from their
own frozen source, including their original import paths.
