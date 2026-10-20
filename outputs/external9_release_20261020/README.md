# Video-RSI and LensWalk 9B results

Both Qwen3.5-9B runs processed the same 5,321 questions: CVBench 997, MVU-Eval 1,824 and CrossVid Lite2500. Compact answers and text trajectories are appended to the existing [Video-RSI release](https://github.com/Wal-K-aWay/MVAgent/releases/tag/video-rsi-results-20261020) and [LensWalk release](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019), preserving their 35B attachments.

| Method | CVBench | MVU-Eval | CrossVid Lite2500 | Infrastructure failures |
|---|---:|---:|---:|---:|
| Video-RSI 9B | 57.97% | 46.66% | 29.47% | 0 |
| LensWalk 9B | 56.27% | 36.35% | 25.05% | 113 |

Scores include all questions, with infrastructure failures counted as zero in aggregation. CrossVid uses the equal-weight mean of its ten task scores; CCQA is weighted by scoring points, including failed questions' points in the denominator. The original per-question score remains null for infrastructure failures. There was no new inference or Judge call during export.

Video-RSI has 5,223 normal final answers and 98 invalid decisions. LensWalk has 3,941 final-answer terminal states, 1,259 unfinished tool plans and 14 empty answers. Infrastructure failure is a separate flag that may overlap terminal states. LensWalk's 113 infrastructure failures include three CCQA questions explicitly exported as unscored, with `status=infrastructure_error`, `score=null`; the other 236 CCQA questions retain saved Judge results. Video-RSI retains all 239 saved CCQA scores. Failed and unfinished outcomes are not silently dropped or rerun.

| Method | Benchmark | Mean Agent seconds | Mean media preparation seconds |
|---|---|---:|---:|
| Video-RSI 9B | CVBench | 64.42 | 2.73 |
| Video-RSI 9B | MVU-Eval | 87.85 | 2.43 |
| Video-RSI 9B | CrossVid | 157.91 | 153.88 |
| LensWalk 9B | CVBench | 159.51 | 2.69 |
| LensWalk 9B | MVU-Eval | 109.89 | 2.60 |
| LensWalk 9B | CrossVid | 193.94 | 154.37 |

`seconds` measures the Agent execution for one question, including its tool and model calls. It excludes media preparation and archival, available separately as `trajectory.prepared_seconds` and `trajectory.archive_seconds`. These averages include processed failures. They are neither batch wall-clock time nor pure token-generation time.

Each archive contains exactly five files: `cvbench.jsonl`, `mvu_eval.jsonl`, `crossvid.jsonl`, `ccqa_scores.jsonl` and `statistics.md`. Answer rows contain `id`, `gt`, `output`, `seconds` and `trajectory`. Final outputs retain their original values; text trajectories, error information and call/token statistics remain. Inline media, complete token ID arrays, duplicate request/response bodies, job logs, weights and frozen environments are omitted.

| Attachment | Bytes | SHA256 |
|---|---:|---|
| `video-rsi-9b-results-compact-20261020.tar.gz` | 115,828,455 | `3479f2218ac6d8ceccf8ee0b784e71b406a0b09197a08069b7da380737211927` |
| `lenswalk-9b-results-compact-20261020.tar.gz` | 86,864,175 | `33c6ce8a573641007b0e3a4a683ac21490073bb06857fcce54260710697f8fe6` |

Original runs remain in the Modal runs volume at `devbox/rsi_9b_32gpu_20261020` and `devbox/lenswalk_9b_parallel_20261019`. Exported packages and verification records are at `devbox/external9_release_20261020/{rsi,lenswalk}`. Only authorized publication bundles and receipts are staged locally in `outputs/external9_release_20261020/`; data is not committed to Git.

The exporter and verifier at `4c0aeda70c9c85235c1741dcbe87d64c23f28946` passed remote CPU compilation and export tests. Every source archive, final answer, ground truth, time, call count and token total was checked against saved results; tar member sizes and SHA256 hashes were checked after packing. Local transfer sizes and SHA256 match Modal. Both public assets report the expected sizes and SHA256 digests. Independent anonymous downloads returned HTTP 200 and matched the complete archive sizes and SHA256; the existing 35B asset IDs, sizes, digests and URLs are unchanged.
