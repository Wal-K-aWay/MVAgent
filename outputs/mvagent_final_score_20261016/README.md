# 旧全量 MVAgent：Judge 与最终评分

2026-10-16 05:13:24 UTC，三模型各239条CCQA评分完成，共717条、0最终Judge失败；15963条已有Actor记录全部读取并聚合。评分与汇总已完成，未重跑Actor，原始轨迹与原失败记录未改写。本报告对应旧独立回答器冻结协议，不是当前“主动直接回答、耗尽后独立兜底”协议的全量成绩。

## 分数与覆盖

全部为百分数。CVBench/MVU-Eval按实际有效题目平均；CrossVid按十类任务等权macro，其中CCQA按评分点加权。沿用冻结的官方逐题评分口径，闭式题保留原评分，新增CCQA Judge结果。

| 模型 | CVBench | MVU-Eval | CrossVid十类macro | CCQA子任务 |
|---|---:|---:|---:|---:|
| 9B | 56.77 | 36.13 | 26.89 | 16.31 |
| 27B | 69.21 | 56.99 | 44.81 | 30.25 |
| 35B-A3B | 65.30 | 52.33 | 33.95 | 13.61 |

| 模型 | CVBench有效/目标 | MVU-Eval有效/目标 | CrossVid有效/目标 | 顶层Actor失败 |
|---|---:|---:|---:|---:|
| 9B | 997/997 | 1824/1824 | 2500/2500 | 0；另有2条被标ok的已知工程故障 |
| 27B | 997/997 | 1823/1824 | 2499/2500 | 2 |
| 35B-A3B | 997/997 | 1823/1824 | 2499/2500 | 2 |

CVBench原选1000题，其中64–66源视频损坏，沿用E2E相同的997可测题；不声称1000题全部测完。CrossVid原选2500题未改变。表中“有效”沿用顶层状态，合计15959条进入评分，不表示每条都无中间故障。

未补跑的顶层失败：27B的`mvu_eval:TR:1493`、`crossvid:PEA:528`；35B的`mvu_eval:TR:1376`、`crossvid:MOC:426`。这些题不进入上表分母，也未被当成模型答错。

9B的`crossvid:PEA:510`、`crossvid:PEA:838`为此前已查明的传输故障被外层标ok、继承为空答案；上表仍保留原零分。单独排除这两条时，CrossVid为26.9176%（2498题），相同子集E2E为31.9972%。因此不能把所有零分归因于模型能力。新评分完成不等于原全量推理已补齐故障。

## CrossVid分项

| 任务 | 9B | 27B | 35B-A3B |
|---|---:|---:|---:|
| BU | 29.31 | 39.22 | 34.05 |
| NC | 26.65 | 51.80 | 48.80 |
| CC | 42.20 | 54.13 | 55.05 |
| PEA | 30.65 | 35.00 | 31.80 |
| PI | 46.00 | 74.00 | 62.00 |
| FSA | 0.07 | 25.16 | 8.18 |
| PSS | 18.13 | 53.85 | 7.14 |
| MSR | 32.52 | 46.01 | 39.88 |
| MOC | 27.10 | 38.71 | 38.96 |
| CCQA | 16.31 | 30.25 | 13.61 |

## 与当时冻结E2E的同题比较

每格为E2E→MVAgent（差值pp），各模型只在双方均有有效评分的同题集合上比较。MVU的E2E采用原提示位置，不是后续官方指令移后的复测；不可把下面的MVU增益直接套到后者。[E2E两套结果](https://github.com/Wal-K-aWay/MVAgent/blob/1e2215e/outputs/e2e/reports/final_results.md)另行保留。

| 模型 | CVBench | MVU-Eval：原提示位置E2E | CrossVid |
|---|---|---|---|
| 9B | 62.09→56.77（−5.32） | 15.84→36.13（+20.29） | 31.98→26.89（−5.08） |
| 27B | 68.10→69.21（+1.10） | 46.19→56.99（+10.81） | 42.03→44.81（+2.79） |
| 35B-A3B | 64.19→65.30（+1.10） | 25.01→52.33（+27.32） | 32.13→33.95（+1.82） |

27B/35B的E2E数值与其全集分数略有区别，是因各排除相同的2条Actor失败题。此处未统一重写历史标签解析或参考答案处理；已有格式、标签与提示位置差异仍须结合此前同题分析解释。数据为复用开发集，不作独立留出集结论。

## Judge协议与审计

- 沿用原冻结`score_crossvid_ccqa.py`与`serve_ccqa_judge.sh`，Judge为Qwen3-30B-A3B-Instruct-2507；8张实际H100、每卡独立服务、每端点并发1，官方System/评分Prompt，temperature=0、top_p=0.95、max_tokens=8192，服务使用`--generation-config vllm`。
- 三模型各239题、757个评分点，满分各1514；实际得分分别247、458、206。覆盖与正确性布尔数组、原始响应缓存和评分总和完成核对，最终失败0，未把Judge故障记零分。
- 每模型214个不同Judge输入、239条逻辑评分，报告记录11条缓存命中/228条非缓存评分。不同题号存在完全相同文本；并发首次请求可能重复计算，所以不能把缓存文件数当实际调用数。
- 27B的CCQA737出现一条报告判定与同prompt最终缓存不同；本轮保留原始逐题判定。若统一按现存缓存，CCQA从30.2510%变为30.3831%，CrossVid从44.8124%变为44.8256%，差0.01321pp。9B/35B没有此差异。未新增重复性实验，不把Actor的一致性验收外推给Judge。
- 每模型5321条记录ID与原选择清单一致；保存逐条原始结果SHA256，独立复算CrossVid十类macro及CCQA评分点加权结果，断言通过。原始记录只读，新目录通过符号链接引用它们。

## 产物与执行

所有JSON、原始轨迹、Judge缓存及运行日志仍仅在Modal runs volume `wxu-evolve-agent-runs-20261006`。

- 新评分根：`devbox/mvagent_final_score_20261016/`。
- 每模型：`score/ccqa_scores_official_qwen3_30b_a3b.json`、`ccqa_judge_cache/`、`record_hashes.json`。
- 总体：`analysis.json`、`comparison/{9B,27B,35B-A3B}.json`、`comparison.md`、`judge_audit.json`、`progress.json`。
- 溯源：`manifest.json`、`aggregation_manifest.json`、`controller.py`、`aggregation_controller.py`、`audit_judge.py`；含冻结评分源码哈希、原Actor manifest、依赖版本与GPU身份。
- 原Actor：`devbox/mvagent_full_20261014_transport/{9B,27B}`与`devbox/mvagent_full_35b_parallel_20261015/35B-A3B`；原`failed`状态保留，不伪装为无故障完成。
- 冻结源码：`devbox/mvagent_full_20261014_transport/frozen_repo`；原记录commit为`4eb309ba973856ac4ae4b2dcb067535d143bdac7`，具体运行内容以冻结源码哈希为准。
- Judge Sandbox `sb-JQEfj0L0ipHOD97gokTGhA`：完成评分并外部确认持久化后主动释放，最终poll137；不是Judge运行失败。为避免GPU等待文件读取，原串行后处理停止，转CPU并行读取，未重做Judge。
- CPU汇总 [ap-NUSGjID7kFsnLpos0QO33h](https://modal.com/apps/modal-labs/zheng-dev/ap-NUSGjID7kFsnLpos0QO33h)：rc0，05:13:24 UTC完成。只读检查代理已结束，无后台任务遗留。

编排脚本：[score_existing_full_mvagent.py](../../scripts/score_existing_full_mvagent.py)；Judge缓存审计：[audit_full_mvagent_judge.py](../../scripts/audit_full_mvagent_judge.py)。本机仅保存代码和本Markdown报告，未下载原始评测数据。
