# Video-RSI、LensWalk与当前基线：同题阶段比较

2026-10-17 11:20 UTC，仅对已有结果做Modal CPU统计，无新增Actor/Judge推理。四方模型均为完整本地Qwen3.5-35B-A3B；MVAgent使用当前直接回答版、空skill库，E2E的MVU使用官方答题指令移到选项后的版本。各方法保留自身采样、调用和生成预算，不能解释为等成本架构消融。

## Video-RSI已有全部结果

| Benchmark | 已处理 | 可评分 | 正确数 | 当前准确率/得分 |
|---|---:|---:|---:|---:|
| CVBench | 303 | 303 | 191 | 63.04% |
| MVU-Eval | 487 | 487 | 268 | 55.03% |
| CrossVid | 650 | 573（九类） | 含连续IoU，不列正确题数 | 九类macro 36.08% |

共1440/5321条记录，1417无工程错误，其中1394给出终答、23为invalid_decision。23个工程失败均在CrossVid，单列而不记为模型零分；54条CCQA待Judge，因此1363条已经评分，没有十类CrossVid总分。模型invalid_decision依官方原始答案评分计零，保留分母。CrossVid按题直接平均30.30%，与九类等权macro不同。

RSI于10:20:24 UTC因`AssertionError((55.976632, 56.009999))`停止，源root为`devbox/rsi_full_35b_20261016`。11:19复查旧Sandbox `sb-ePIHdBg91VaZ6W113TVdQG` poll137、watcher2775586不存在，GPU已释放；不能描述为仍在后台推理。还有3881题无最终记录。此轮不改写原结果或恢复GPU任务。

## 四方共同399题

| Benchmark | 共同题数 | LensWalk | Video-RSI | E2E | MVAgent直接版 |
|---|---:|---:|---:|---:|---:|
| CVBench | 147 | 55.78% | 58.50% | 66.67% | 67.35% |
| MVU-Eval | 131 | 32.06% | 58.02% | 39.69% | 51.15% |
| CrossVid九类 | 121 | 25.81% | 33.82% | 34.23% | 41.08% |

每行四方题号完全一致，工程失败和未判分CCQA不进入共同集合，模型未能给出终答的结果仍保留。CV/MVU为本子集按题平均，不是按task人口权重推算的全集分数；CrossVid为九类等权macro，包含FSA平均IoU。不同集合的得分不能直接作差：第一表用RSI全部可评分结果，本表只用四方交集。

在这批题上，Video-RSI三个benchmark均高于LensWalk。相对MVAgent，RSI在CV/MVU/Cross分别为−8.84/+6.87/−7.26个百分点；相对E2E为−8.16/+18.32/−0.41个百分点。MVU当前点估计更高，但RSI赢MVAgent28题、输19题，仅131个共同样本，尚不能声称稳定总体优势。CrossVid对E2E基本持平，不能说RSI普遍超过E2E。LensWalk在四方共同题上三个benchmark均最低。

| 同题单题平均推理秒数 | LensWalk | Video-RSI | MVAgent |
|---|---:|---:|---:|
| CVBench | 230.67 | 160.77 | 86.04 |
| MVU-Eval | 140.72 | 165.16 | 98.03 |
| CrossVid | 263.68 | 425.40 | 107.22 |

外部方法此处不含拼接准备，MVAgent用原始记录的整题推理时间；不是并行墙钟。RSI约为MVAgent的1.87/1.68/3.97倍，且比LensWalk在MVU和CrossVid更慢。调用、帧数、生成预算不同，不能将用时差全部归因于框架调度；本次没有额外读取E2E逐题计时。

## LensWalk更大的三方交集

当前MVAgent只覆盖每benchmark500题，LensWalk此前2360题快照中有658道可评分题与它重合。RSI可配对的399题恰好均在这658题内，故RSI三方比较与上表四方集合相同。

| Benchmark | 共同题数 | LensWalk | E2E | MVAgent直接版 |
|---|---:|---:|---:|---:|
| CVBench | 233 | 55.36% | 64.81% | 66.09% |
| MVU-Eval | 220 | 30.91% | 40.45% | 50.91% |
| CrossVid九类 | 205 | 25.47% | 31.85% | 43.40% |

LensWalk相对MVAgent为−10.73/−20.00/−17.92个百分点，相对E2E为−9.44/−9.55/−6.38个百分点。234/658题未收尾或为空（35.56%），是已观察到的交付问题；不能据此认定所有分差都来自收尾，也未做修改收尾策略的因果实验。

## 来源与验证

- LensWalk固定使用此前`devbox/lenswalk_partial_20261017_1108/snapshot.json`的2360条快照；不把本轮新跑出的题混入上次成绩。
- 当前MVAgent/E2E来自`devbox/direct_answer_large_recovery_20261017/analysis/35B-A3B_paired.json`，其中1500条当前MVAgent、同题E2E预测及评分已保存。没有使用旧独立回答器分数替代当前MVAgent。
- RSI读取1440个逐题`record.json`并保存文件SHA；运行状态、错误和未评分情况一起保留。
- 统一评分定义的`scoring.py`和`catalog.py`在三个方法冻结源码中SHA完全一致；三方/四方同题身份、基线分数、score范围、聚合自检通过。泛化后的LensWalk分析与首轮658题统计完全一致。
- CPU `ap-WxUvAc4m6velyUD9Lt2PQP`完成首轮LensWalk比较；`ap-zjeUzhnnA4RIW9iUgmrTPL`完成RSI和四方汇总，均rc0。新原始/派生数据仅runs `devbox/external_baselines_paired_20261017/`，含summary、paired、rsi_snapshot及实际分析源码。

这些是尚未完成批次和开发面板交集的描述性结果，完成速度与难度可能影响覆盖；没有CCQA评分、独立留出集或显著性结论。不得直接把不同覆盖的全量/阶段分数拿来宣称方法排序。
