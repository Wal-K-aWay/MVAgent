# 三模型 E2E 最终结果：Lightsail 本地分析副本

本目录同时保存MVU-Eval官方指令原位置与移到选项后的结果，按模型统一归入`9B/`、`35B-A3B/`、`27B/`。
[最终分析](reports/final_results.md)用官方分、稳健分两张表展示三个模型和三个benchmark；MVU单元格为“原位置 → 移后”。

## 迁入与完整性

- 原位置基线于2026-10-13迁入：671个文件、42,800,648字节（40.82 MiB）。
- 指令移后复测于2026-10-15迁入：29个文件、18,117,891字节（17.28 MiB）。
- 两批最初共700个迁入文件。两份重复报告的关键内容并入总报告后删除，现保留698个文件、60,905,027字节；逐文件大小与SHA256核对一致，原始回答、评分与分析JSON不变。
- 本目录已由`outputs/e2e_final_20261013/`改名为`outputs/e2e/`。
- 原`mvu_instruction_after_20261014/`分组目录已删除；其模型文件归入对应模型目录，共享文件归入`analysis/`、`reports/`及本目录。
- 数据不入Git；仅明确选中的Markdown报告备份。Modal原件保留，媒体、权重、冻结运行环境、分片副本和服务日志未下载。

## 每个模型的文件

下表中的路径均相对于`9B/`、`35B-A3B/`或`27B/`。不带后缀的文件仍对应原位置基线。

| 内容 | 原位置基线 | MVU指令移后 |
|---|---|---|
| 原始回答与token | `raw/mvu_eval.jsonl` | `raw/mvu_eval_instruction_after.jsonl` |
| 逐题评分 | `scored/mvu_eval.json` | `scored/mvu_eval_instruction_after.json` |
| 汇总 | `summary.json`（三个benchmark） | `summary_mvu_instruction_after.json`（仅MVU） |
| 题目清单 | `selection.json` | `selection_mvu_instruction_after.json` |
| 运行/模型/源码身份 | `manifest.json` | `manifest_mvu_instruction_after.json` |
| 本轮输入哈希 | 原始回答的`request`中保留 | `input_audit_mvu_instruction_after.json` |
| 原位置与移后配对 | — | `comparison_mvu_instruction_after.json` |

`raw/`和`scored/`中的CVBench、CrossVid文件以及`judge_cache/`保持原样；不覆盖原有回答、评分或summary。

## 共享分析、报告与迁移清单

- `analysis/analysis.json`、`analysis/cache_audit.json`仍是原位置基线的核查和Judge缓存分析。
- `analysis/mvu_instruction_after.json`是MVU复测配对分析；同目录的`mvu_instruction_after_manifest.json`、`mvu_instruction_after_progress.json`、
  `mvu_instruction_after_source_provenance.json`、`mvu_instruction_after_original_input_sha256.json`、`mvu_instruction_after_selection.json`保存全局元数据。
- 报告仅保留[总报告](reports/final_results.md)：总览、分项、MVU对照、评测设置及Judge限制。
- 原位置迁移清单与校验：`transfer_manifest.json`、`transfer_verification.json`。
- MVU复测迁移清单与校验：`transfer_manifest_mvu_instruction_after.json`、`transfer_verification_mvu_instruction_after.json`。
  新清单的`path`相对本目录，`original_import_path`记录整理前位置；远端`source`、文件大小和SHA256不变；`removed_reports`记录已合并删除的两份迁入报告。

## 来源与边界

来源volume为`wxu-evolve-agent-runs-20261006`。

| 模型/批次 | 原路径 |
|---|---|
| 9B原位置 | `devbox/e2e_full_20261012/9B` |
| 35B-A3B原位置 | `devbox/e2e_full_20261013_timeout/35B-A3B` |
| 27B原位置 | `devbox/e2e_full_20261013_timeout/27B` |
| MVU指令移后（三模型） | `devbox/mvu_instruction_after_20261014/{9B,35B-A3B,27B}` |

原位置分析JSON来自`devbox/e2e_results_analysis_20261013/`。重跑仍需Modal上的冻结环境和媒体，文件整理不改写原manifest内的远端来源路径。
原位置基线三模型各5321道可测题、CCQA各239条全评分；CVBench64–66源视频损坏，完整1000题总分为null。
35B的两组相同Judge文本判定不一致，715/717条评分与现存缓存一致；保留原分数，敏感性说明见总报告。
MVU复测是同样1824题的三模型单遍对照，共5472条有效响应、0请求错误，不调用Judge。
本次仅整理本地文件，没有新增推理或评分。
