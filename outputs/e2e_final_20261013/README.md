# 三模型 E2E 最终结果：Lightsail 本地分析副本

原位置基线于2026-10-13按用户要求迁入：671个数据文件、42,800,648字节（40.82 MiB），全部与Modal导出清单的文件大小及SHA256一致。
数据不入git；已有`/outputs/`忽略规则生效。Modal原件保留，本地可直接查看与做轻量分析。

2026-10-15新增MVU-Eval“官方原句移到选项后”复测：29个文件、18,117,891字节（17.28 MiB），逐文件大小及SHA256核对一致，
保存在`mvu_instruction_after_20261014/`。两批共700个迁入文件、60,918,539字节；各自的迁移清单和校验记录分别保留。
旧的独立本地MVU报告及巡检记录也已移入该子目录。媒体、权重、冻结源码、分片副本和服务日志继续只留Modal。

[最终分析](reports/final_results.md)的总览现分为官方分、稳健分两张表，行是三个模型，列是三个benchmark；
MVU列统一使用指令移后的结果，原位置成绩在对照小节保留。三个顶层模型目录及其summary仍是原位置基线，未被覆盖。

## 内容

原位置基线的三个模型目录为`9B/`、`27B/`、`35B-A3B/`，各包含：

- `raw/`：三个benchmark的原始回答、推理状态、token与输入哈希。
- `scored/`：三个benchmark逐题评分，包括CCQA的coverage/correctness。
- `judge_cache/`：固定本地Qwen3 Judge的原始响应缓存。
- `summary.json`、`selection.json`、`manifest.json`：汇总、选题与模型/配置/源码身份。

顶层`analysis/analysis.json`保存原位置基线的三模型逐题核对、同题比较与格式统计；`analysis/cache_audit.json`保存Judge共享缓存追查。
[最终分析](reports/final_results.md)与[核对说明](reports/audit.md)为报告副本。
`transfer_manifest.json`逐文件记录原volume路径、大小与SHA256；`transfer_verification.json`记录本机实际校验结果。

2026-10-13本地清理后，本目录的最终分析与核对说明为唯一报告入口；原启动/恢复说明合并到
[运行历史](reports/run_history.md)。671个迁入数据文件的SHA256再次核对一致。

MVU复测子目录`mvu_instruction_after_20261014/`包含：

- 三个模型的`raw/mvu_eval.jsonl`、`scored/mvu_eval.json`、`summary.json`、`selection.json`、`manifest.json`和`input_audit.json`。
- 根级实验manifest、完成状态、源码来源、原输入哈希与全量题目清单；`comparison/`和`analysis/`保存原位置与移后的配对结果。
- `transfer_manifest.json`、`transfer_verification.json`记录本次29个文件的来源、大小、SHA256及迁入核验。
- [完整复测报告](mvu_instruction_after_20261014/final_results.md)和`progress_checks.md`由原本地目录迁入；其中`analysis/report.md`是迁移前的远端原始报告，保留原文与哈希。

## 来源与边界

来源volume为`wxu-evolve-agent-runs-20261006`：

| 模型 | 原路径 |
|---|---|
| 9B | `devbox/e2e_full_20261012/9B` |
| 27B | `devbox/e2e_full_20261013_timeout/27B` |
| 35B-A3B | `devbox/e2e_full_20261013_timeout/35B-A3B` |
| MVU指令移后（三模型） | `devbox/mvu_instruction_after_20261014/{9B,27B,35B-A3B}` |

分析JSON来自`devbox/e2e_results_analysis_20261013/`。
不包含固定帧缓存、视频、权重、冻结源码、分片重复结果或服务日志；重跑实验仍需Modal上的冻结环境和数据。

原位置基线三模型各5321道可测题、CCQA各239条全评分；CVBench64–66源视频损坏，完整1000题总分为null。
35B的两组相同Judge文本判定不一致，715/717条评分与现存缓存一致；本地忠实保留原结果，不自动用缓存覆盖原评分。
缓存差异及其对总分的微小影响见报告，不能将Judge缓存视为所有历史判定的唯一来源。

新增MVU复测为同样1824题的三模型单遍对照，共5472条有效响应、0请求错误，不调用Judge。
本地迁移不改变任何原始回答或评分，也没有启动新的推理任务。
