# AgentCVR结果的AWS Lightsail副本

用户于2026-10-17明确授权把AgentCVR逐题原始答案和最终结果保存到本机。本次复制最终H100恢复批次的全部2821题，不混入旧H200或失败批次。

本地目录：`/home/ubuntu/weili/kww/MVAgent/outputs/agentcvr_20261016/data/`。

| 路径 | 内容 |
|---|---|
| `answers/cvbench.jsonl` | 997题的原始模型答案、问题、参考答案、官方判分、状态和原始文件索引 |
| `answers/mvu_eval.jsonl` | 1824题的同类信息，保留未终答题 |
| `raw/*.json` | 2821份原始逐题JSON，含回答、完整保存轨迹、模型请求/响应、token记录和输入hash |
| `records/*.json` | 2821份原始轻量完成记录及raw SHA256 |
| `summary.json` | 最终两套benchmark的汇总分数、样本数、token与耗时统计 |
| `metadata/scores.json` | 官方逐题评分及汇总 |
| `metadata/` | 完成状态、输入/标签、模型/配置manifest、最终审计和恢复来源等原始文件 |
| `transfer_manifest.json` | 每个迁入文件的来源、字节数及SHA256 |
| `transfer_receipt.json` | Lightsail完成校验后的回执、归档SHA和目标路径 |

答案表中的`model_answer`保留原字符串；`reference_answer`、`official_prediction`和`official_score`是独立字段，不把参考答案当成模型答案。最终分数CVBench567/997=56.87%，MVU-Eval803/1824=44.02%；MVU RAG873未终答仍按0计入。

Modal原件继续保留于volume `wxu-evolve-agent-runs-20261006`的`devbox/agentcvr_eval_h100_20261016_r2/`。打包在Modal CPU执行，经`ssh modal-gpu`流式中转；dev box不暂存大文件，本机只进行流式落盘、解包和SHA校验。媒体、权重和冻结执行环境未迁入。

传输脚本为`eval/external_methods/agentcvr_export.py`和`agentcvr_download.py`。数据与JSON清单不提交Git；GitHub只备份脚本和Markdown说明。最终核验信息以本地`transfer_receipt.json`为准；只有完整验证通过才将`data.partial`改名为`data`。

传输完成：5658个迁入文件共1,796,010,344字节（约1.80GB），整包与每文件大小/SHA256全部一致；另生成本地校验回执。整包SHA256为`2f543ef90e4ada146849d0514f66feed20bf63cc31c62e85b7f6dcaf5746bd91`。997/1824行答案表已核验；未额外保存1.80GB中转tar，正式数据直接解包落盘。归档文件mtime统一为0，不用本地mtime推断推理完成时间；时间以原始JSON和progress为准。
