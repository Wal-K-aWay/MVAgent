# PRO6000完整9B源码＋FFmpeg：同题实验结果

2026-10-16完成。9B共330题，使用两个独立8×H100实例；330题推理、120份开放题Judge与最终核查全部完成，16张GPU已释放。
本次已在隔离实验分支恢复旧源码，共享主工作区及正式运行配置未替换。

本批CVBench和MVU-Eval分数高于上一轮直接回答方案，CrossVid闭式部分基本持平；格式错误和少数长轨迹开销更大。
不能据此把完整旧源码认定为更稳定的正式方案。

## 同题分数

300道闭式题复用之前面板，各benchmark100题；另从已完成的239道CCQA中以seed0抽30题。
表内都是这些同题的分数，不是全量benchmark成绩。CV/MVU沿用题型总体权重；CrossVid按任务macro，CCQA按评分点加权。

| Benchmark / 范围 | 原PRO6000 Agent | 旧独立回答器 | 上一轮直接回答 | 本次旧src＋FFmpeg | E2E |
|---|---:|---:|---:|---:|---:|
| CVBench，100题 | 68.98% | 63.62% | 69.39% | **75.05%** | 73.67% |
| MVU-Eval，100题 | 48.97% | 36.06% | 46.82% | **51.06%** | 42.94% |
| CrossVid闭式九类，100题 | 35.58% | 31.82% | 34.98% | **34.83%** | 28.55% |
| CCQA，30题 | 19.79% | 10.42% | 未测 | **23.44%** | 62.50% |
| CrossVid十类macro，130题子集 | 34.01% | 29.68% | 无完整口径 | **33.69%** | 31.95% |

本次相对上一轮直接回答的差值：CV **+5.65pp**、MVU **+4.23pp**、Cross闭式 **−0.16pp**。
对应配对分层bootstrap的95%区间分别为[−4.36,+15.06]、[−5.05,+13.20]、[−9.93,+10.28]pp，均跨0。
这是开发面板上的点估计改善，尚不能证明总体稳定增益或等效。

CCQA四组全部使用同一个冻结Qwen3-30B-A3B-Instruct-2507 Judge重新评分，并共用缓存；没有混用PRO旧DeepSeek分数。
四组分子/分母分别为本次45/192、PRO38/192、独立20/192、E2E120/192。
120份判分全部成功，对应119个唯一缓存；缓存、原始Judge响应和判分逐项匹配。
Cross十类按`(9×闭式九类macro＋CCQA分数)/10`计算，不能用旧独立回答器的CCQA替代缺失的直接回答器CCQA。

“上一轮直接回答”指已完成900面板中的9B结果；最新正式History前置＋独立兜底配置仅有小冒烟，不能把900面板当作其准确率成绩。
这批题来自反复使用的开发面板与共同可比较题池，区间也只描述该面板的不确定性。

## 格式、故障与长轨迹

| 闭式300题 | 原PRO6000 | 旧独立回答器 | 上一轮直接回答 | 本次 |
|---|---:|---:|---:|---:|
| 答案格式不合格 | 9 | 71 | 7 | **15** |
| 空答案 | 0 | 0 | 0 | **0** |
| 仅输出 `}` | 0 | 40 | 0 | **0** |

本次330题均有非空答案，0顶层Actor失败、0 HTTP错误。15个闭式格式问题不是15个最终JSON解析失败：
14题提交了“None”“None of the above”“Cannot determine”“No valid order exists”等，未按题目选项/顺序/区间要求答题；
另1题CV431沿用已知的输入选项标签缺陷，各方案均单列诊断。15个记录中8个来自主动终答、7个来自独立兜底，问题并不限于兜底。
最终答案仍保留开放字符串，没有添加合法选项枚举。

330题共4399次模型调用，103次达到2048输出token上限，涉及26题：视觉观察`text/uncertainty`83次、Global决策18次、独立终答2次。
16题在公开轨迹里记录了中间错误或无效结果；20题使用步数耗尽后的独立兜底。服务正常不意味着中间取证成功。

| 实际案例 | 最终输出 | 调用 / 触顶 | 单题耗时 |
|---|---|---:|---:|
| CV824 | `Cannot determine`，旧PRO和上一轮直接回答均为正确的A | 59 / 25 | 24.65分钟 |
| CrossVid PI6 | A | 59 / 25 | 25.09分钟 |
| CCQA415 | 给出Video A的时间/方法，并称Video B分析失败、无信息 | 59 / 25 | 26.66分钟 |

三题均出现视觉观察反复列举内容、2048token仍未闭合JSON，导致没有有效观察；VideoAgent达到步数上限后，Global又请求相同取证。
CV824的三次已核验观察调用，输入hash和完整输出token完全相同。Global虽然在理由中表示要更简洁，实际instruction没有改变，失败随之重复。
这3题贡献75/103次触顶，占全部单题累计耗时约18.2%。这是可重复的无效输出，不能把确定性等同于任务可靠性。

## 速度与重复性

- 330题单题均值76.42秒、中位数51.17秒、P95为165.41秒、最大1599.71秒；累计单题耗时25217.98秒。
- 两组正式推理于06:17:50和06:22:58 UTC开始，分别于07:03:09和07:06:36完成。
  首组开始至全部推理结束约48.76分钟，实际吞吐约6.77题/分钟；不含GPU排队、模型加载、冒烟和Judge。
  固定分片遇到少数长题后有明显收尾等待，不能把16卡理解为线性16倍提速。
- 调用路径改变后的两题完整冒烟各运行两遍：28响应、14配对调用，输入hash和完整输出token均一致。
  除运行时间外，输入、视频报告、联合观察、动作历史、完整轨迹、最终答案和终止原因也完全一致。
- 正式330题复用既有固定数值配置的验收，不再逐题双跑。有限冒烟不构成任意输入的绝对确定性保证；Judge的重复性也不能由Actor验收推导。

## 源码与实际配置

旧src完整来自提交`6b1e5641719e5e12202737ed66f218250a8b4bd6`的
`outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot/`，共105文件。
唯一差异为`mvagent/utils/media.py`的FFmpeg分段及依赖导入；普通分段使用stream copy，短片段按旧采样需求补帧转码。
旧Prompt、schema、memory、直接回答、独立兜底、串行VideoAgent和客户端均保留。

固定服务单独放在实验backend目录，外部桥只转换旧JSON-schema接口封装，不加入新grammar或字符上限。
BF16、16个独立TP1/并发1 worker、整题固定副本、seed0、temperature0、thinking关闭、FlashInfer GDN、原生GemmaRMSNorm，prefix/MM缓存关闭。
逐请求核查16个实际GPU、模型token数量、消息/schema转换、seed/温度/预算、sticky身份与cache0；330个原始记录SHA和105源文件SHA也全部核验。
旧config仅调整当前环境所需的权重/缓存/端口、BF16、131072上下文、0.94显存比例及1860秒HTTP等待；2048输出token、512帧、Global/Video各5步沿用旧配置。
因此这是“旧src＋FFmpeg在固定H100环境”的整体实验，不是原PRO6000软硬件逐位复刻，也不是某一句Prompt或裁剪器的单因素消融。

冻结Actor文件对应实验分支`dc79669`中的运行文件，实际身份以远端manifest的SHA为准。
后续分支修复桥的日志编号递增，避免客户端重启覆盖历史日志，没有热更新本批推理。
本批28个冒烟响应已在编号复用前另存archive，并逐SHA校验完整。Judge全部成功后，首次离线汇总因CPU评分文件尚未就绪报错；
文件就绪后单独重做汇总成功，没有重跑Actor/Judge。后续脚本把Judge与报告汇总显式分开。

## 产物与验证

原始数据仅保存在Modal runs volume `wxu-evolve-agent-runs-20261006`下的`devbox/pro9_ffmpeg_20261016`：

- `code/`、`selection.json`、`jobs.json`、`base_config.json`、两组`manifest.json/servers.json`：冻结源码、抽样、输入和实际服务身份。
- `9B/records/`、`shard*/rank*/calls/`、`shard*/server*/requests.jsonl`：完整轨迹、实际请求/响应和token。
- `smoke_http_archive/`、`smoke_archive_manifest.json`、`smoke_trajectory_audit.json`：两题重复性证据。
- `9B/score/`、三个`*_reference/score/`、`ccqa_judge_cache/`、`judge_manifest.json`：四组统一Judge及原始缓存。
- `analysis/closed_summary.json`、`paired.json`、`diagnostics.json`、`ccqa_summary.json`、`ccqa_paired.json`：完整同题分析。
- `analysis/final_checks.json`、`record_hashes.json`、`finalization_manifest.json`和根目录`progress.json`：最终核验与完成状态。

远端旧src/实验脚本编译、桥转换、FFmpeg普通分段/补帧/空区间检查、完整冒烟、正式推理和评分均已完成。
最终评分CPU app为`ap-R8sUdINgt6e7t5wA3EApHo`；首次最终审计`ap-X9W3a2KwSS9TUhfENw0MFf`，补充终答来源统计及completed状态的收尾`ap-U2MOoxkphpgMKcLpeZSczx`，均rc0。
两组Sandbox `sb-d9oJJrFjKbKcpMQYtzHSrF`与`sb-5VLkroN5v9cTZiXcq1Kz7W`均已显式终止并以SDK poll=137确认退出；独立巡检已停止。

实验入口与环境说明见[README](../../experiments/pro9_ffmpeg/README.md)。本机及Git只保存代码和Markdown，没有下载原始结果。
本轮没有测试27B/35B，也没有运行全量benchmark；尤其不能把闭式点估计改善推广成所有模型、所有任务上的稳定收益。
