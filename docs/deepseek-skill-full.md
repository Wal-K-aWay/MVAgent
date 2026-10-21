# DeepSeek skill 全量补测：48H100 与分层打乱顺序

用户于2026-10-21要求使用48张H100启动剩余评测，并打乱题目顺序，使中途停止后的样本尽量接近整体分布；随后明确只测skill组，复用已经完成的空库结果。

## 范围与冻结内容

- 模型：Qwen3.5-9B、35B-A3B、27B。每模型覆盖CVBench 997题、MVU-Eval 1824题、CrossVid Lite2500，共5321题；保留原CrossVid Lite2500清单和CVBench三个已知不可用样本的排除。
- 每模型复用先导实验已完成的360道skill题，只补4961题；三模型共14883次新运行。没有新空库推理或空库Judge调用。
- 使用[先导实验](deepseek-skill-pilot.md)的同一份库：Global 6张、Video 8张；SHA256 `7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049`。不根据本次成绩改卡。
- Actor源码仍冻结于`0894a470b322ac0ed74744a6d3131fbdd778ca14`，准备时逐文件核对先导快照。基础Prompt、动作预算、模型权重、seed=0、temperature=0、BF16、每卡TP1/DP1/C1、prefix/MM cache关闭均沿用已验证配置。
- 六个8H100节点：9B两个、27B两个、35B两个；其中35B一个节点使用7个Actor副本，另1张GPU运行既定Qwen3-30B-A3B-Instruct-2507 Judge。合计47张Actor＋1张Judge，峰值48张。
- 新任务显式授权覆盖三个benchmark；这不意味着可以将其逐题结果交给后续optimizer。本次卡库保持冻结，结果含既有开发数据，不声称新的独立Test证据。

## 顺序与阶段性结果

先按`benchmark × native task`分层，在各层内部用seed=0打乱题目，再分成互不重叠的两份清单。每层在两份清单中的题数最多相差1；每份清单采用按该层占比的最大缺额调度，将各题型交错排列。所有模型复用相同两份清单，分别为2481和2480题。

准备检查遍历了两个清单的全部前缀：任一题型的实际派发数相对该前缀按比例应有的数量，最大偏差分别为0.88312和0.88307道。原生`--sample-ids-file`保留列表顺序，BatchExecutor按该顺序取任务；运行中还会核对真实`question_start`事件。

这约束的是派发顺序。并发中的长题、失败或中途停止仍可能使已完成样本偏向较快的题，不能保证任意停止时刻都无偏。阶段性报告保留每层已评分数量、未覆盖层、工程失败和未评分记录，不把未评分题记为零。

单张Judge持续读取已经落盘的新CCQA答案，复用官方评分器和缓存；其余题目沿用原生闭式评分。每轮更新`interim.json`和`interim.md`，估计分遵循CrossVid十任务macro、CCQA评分点加权，以及CVBench/MVU按完整可测集合的任务人口加权。未覆盖全部任务时，该benchmark的整体估计为null；区间只在各层样本足够时给出。

区间采用题目级分层paired bootstrap，阶段性400次、最终2000次、seed=0；没有校正反复查看、可选停止或视频复用相关性，不能当作任意停止都有效的显著性保证。

## 空库复用

直接复用已发布的三模型完整空库答案和原CCQA评分；闭式题使用同一官方评分器复核，没有重新调用Actor或Judge。三模型各5321条均与本次ID集合匹配。原文件SHA、来源manifest及360题重合检查保存在`baseline_provenance.json`。

与先导实验的360道新跑空库结果相比，三个模型的最终答案均360/360一致；9B和27B评分也360/360一致。35B仅CCQA:308不同：相同答案在旧全量评分为2/3、先导评分为1。本轮对照统一采用旧全量评分，保留两份原件与差异说明，不静默修改分数或重新Judge。历史与当前冻结commit不同，因此仍明确标注为历史空库复用，不声称所有旧运行逐请求输入都已逐字验证。

## 运行与保存

- Modal app：`ap-XWjxjjJXkWAzYXkurNXUsc`，名称`wxu-sglang-baseline-gpu-test-deepseek-skill-full-20261021`。
- runs目录：`/runs/devbox/deepseek_skill_full_20261021/`。
- `panels/`、`order_audit.json`：完整范围、复用清单、剩余顺序和前缀分布核验。
- `shards/<tag>/skill/`：原生冻结快照、raw records、调用事件与CCQA评分；先导原始结果仍保留在原目录，以来源路径引用。
- `baseline_rows.json`、`baseline_provenance.json`：空库答案/评分复用与来源；`retained_skill_rows.json`：先导skill结果引用。
- `compact_rows.json`、`interim.json`、`interim.md`：阶段性逐题索引与报告；结束后生成`final_summary.json`及`final_report.md`。
- `manifest.json`、`private_ops/`：冻结输入和一次性操作脚本。原始数据只保存在Modal；本次没有把评测数据迁回AWS或加入Git。

08:08 UTC唯一主控制器PID1196446已启动，六个节点均已创建，处于分配/加载阶段，尚未确认首个新样本。准备时可用文件名额约60460，预计本批新增约34766；原始历史数据未清理。初始化曾因私有`inspect.py`遮蔽标准库而失败，改名`inventory.py`后准备成功；失败发生在GPU运行前。

本文件记录启动协议与当前状态，不代表全量结果已完成。主控制器负责结束后的资源释放，固定Judge负责持续评分；AI每15分钟巡检仅在会话活跃期间执行。
