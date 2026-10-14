# 采样与重复惩罚对 MVAgent 循环的影响（2026-10-13）

**已完成：能缓解部分循环和截断，但没有找到同时改善解释质量、取证行为和答案格式的统一设置。正式源码和默认配置未改。**
新增23次冻结请求（21候选＋2旧输出锚点）和6条完整Agent轨迹，共106次实际模型调用。
涉及4个复用开发题、7个冻结检查点，其中2题跑完整流程；不是106个独立样本。
所有原始结果留在Modal runs volume的`devbox/sampling_20261013/`。

## 条件与边界

| 条件 | temperature | top_p | top_k | presence_penalty |
|---|---:|---:|---:|---:|
| greedy原设置 | 0 | 1 | 0（不限制） | 0 |
| penalty：只加惩罚 | 0 | 1 | 0（不限制） | 1.5 |
| sampling：只开启采样 | 0.7 | 0.8 | 20 | 0 |
| official：采样＋惩罚 | 0.7 | 0.8 | 20 | 1.5 |

共同：35B-A3B BF16、1×H100、TP1/DP1/C1、固定配置数值设置、seed0、thinking关闭、min_p0、repetition_penalty1、frequency_penalty0，每次2048输出token。
保留当前refined System（SHA256 `acb36637f9288ad5a5ec6703abeed55d7d46ac253fb4fcf3fd8355ce0cb8b4a3`）、全部User/终答提示、JSON/schema、reason1200字符、Global/Video各5步和512帧。
官方条件来自[Qwen非thinking通用任务建议](https://huggingface.co/Qwen/Qwen3.5-35B-A3B#best-practices)。它是候选设置，不是已验证的本项目最优配置。

四个决策来自当前System的CV712、Counting88、CV376、BU504冻结输入；两个终答来自当前System完整CV712/Counting88。
另一个截断终答取自`decision_system_20261013/focused`的CV712：终答System与当前相同，但前面的决策历史来自已弃用的System，单独标为历史挑战。
完整Agent原greedy基线复用`decision_system_20261013/refined`的同协议两题，未混用更早的提示或reason限制。

只在runs冻结副本改`sync_server.validate_request`开放参数、`OpenAICompatibleProvider.chat`在记录请求前注入实验参数。
每个子进程通过`MVAGENT_SAMPLING_EXPERIMENT`指定参数，实际payload与服务器generation日志均保留；不能只看仍为greedy的基础YAML推断实际参数。
这是固定配置计算设置上的实验采样接口扩展，不属于原greedy正式协议的重复性验收。
没有改Prompt、工具、预算、媒体处理或正式配置，也没有新增答案枚举/强制修复规则。

## 冻结决策结果

表内为reason字符数和后续动作。1200表示触及原字符上限，完整JSON仍可正常结束；这不同于总token预算截断。

| 冻结输入 | 原greedy | 只加惩罚 | 只开启采样 | 官方组合 |
|---|---|---|---|---|
| CV712 | 402 / watch | 561 / analyze | **1200 / answer** | 512 / watch |
| Counting88 | 1200 / answer | 1200 / answer | 1200 / answer | **2 / answer，仅逗号与空格** |
| CV376 | 1200 / answer | 369 / answer | 575 / answer | 955 / answer |
| BU504正常对照 | 267 / answer | 272 / answer | 280 / answer | 319 / answer |

- CV712只开启采样由继续观看变成直接终答，理由还写满上限；放弃贪心并不必然改善重复或取证。
- Counting88官方组合虽然不再写满，但解释只剩标点，不能算解释质量改善。
- CV376官方组合最终比较了窄路、停放车辆等潜在风险，完成了一项有意义的判断；仅惩罚直接说证据无法作答，仅采样提出默认选第一个。这里只分析文本推进，没有评分或确认判断正确。
- BU504有明确共同动作，三组都保持直接回答，未引入无必要取证。

四个决策触顶数：原版2/4、仅惩罚1/4、仅采样2/4、官方组合0/4；官方组合的0/4包含一条标点理由，不能把触顶数单独当作成功指标。

## 截断终答：改善最明显，但并未全部完成题意要求

同一条CV712历史挑战输入，原greedy会循环到2048token且JSON未完成。本轮重新生成逐token匹配该故障。

| 条件 | 输出token | 结束 | 最终answer |
|---|---:|---|---|
| 原greedy | 2048 | length，JSON未完成 | 缺失 |
| 只加惩罚 | 125 | 自然stop | None of the options are consistently shown across all videos. |
| 只开启采样 | 112 | 自然stop | C |
| 官方组合 | 169 | 自然stop | None of the options are consistently mentioned or shown across all videos. |

这说明采样和惩罚各自都能打断至少一种已观测循环。
但仅采样的理由仍称“没有一个选项在所有视频中一致出现”，与提交C的依据不协调；其余两组未按题目要求提交选项。
当前Counting88冻结终答在三种新参数下也全部为非选项（长句或`None`）。当前CV712冻结终答则三组都保持C。
因此，“自然结束”“有效JSON”“理由与判断一致”“满足题目格式”必须分别判断。

候选21次冻结响应全部自然stop且通过原JSON/schema校验，无自动repair。
按7检查点各取一遍，输出token总数由原3077变为仅惩罚1002、仅采样1164、官方组合927；主要收益来自消除那条历史截断输出，不能外推总体吞吐。

## 完整 Agent 对照

| 题目 | 条件 | 调用 | 输出token | 秒 | Global reason字符 | 最终answer |
|---|---|---:|---:|---:|---|---|
| CV712 | 原greedy | 18 | 2299 | 157.69 | 182/381/545/251 | C |
| CV712 | 只加惩罚 | 12 | 1230 | 94.94 | 243/417 | 非选项：None of the options… |
| CV712 | 只开启采样 | 12 | 1512 | 115.95 | 228/**1200** | A |
| CV712 | 官方组合 | 14 | 1688 | 144.22 | **1，仅逗号**/596/295 | A |
| Counting88 | 原greedy | 15 | 997 | 68.62 | **1，仅逗号**/1200 | 非选项：None of the options… |
| Counting88 | 只加惩罚 | 15 | 753 | 60.97 | **1/1，均仅逗号** | 非选项：None of the options… |
| Counting88 | 只开启采样 | 15 | 1166 | 90.25 | 209/927 | No valid option |
| Counting88 | 官方组合 | 15 | 1037 | 96.11 | 186/**1，仅逗号** | No valid option found |

- **官方组合CV712**：单视频分析后发现冲突，实际调用联合观看；新观察报告称所有视频都出现榨汁器，随后提交A。相较原版18调用降至14，决策未触字符上限，但首步解释只有逗号。没有核实新的视觉陈述是否正确，不能把答案变化写成准确率提升。
- **仅惩罚CV712**：12调用、更少token，但直接依单视频报告结束，没有继续核实；最终从选项变成非选项。冻结当前终答时它仍答C，而完整流程失败，说明中间观察/动作变化会改变最终效果。
- **仅采样CV712**：最终虽提交A，决策仍反复争论“所有视频没有共同动作”和“必须选择”，写满1200字符；短终答也仍在讨论题目前提有误。生成选择并不等于循环已消除。
- **Counting88**：三种新条件都没有继续核实四份否定报告，最终均不提供题目要求的单个选项。仅采样的末次理由927字符，仍有明显重复论证；加惩罚的组则出现标点理由。

6条新完整轨迹、83次调用全部完成，0服务错误、0结构化错误、0repair、0总token截断。
按这两道单选题要求的严格形式作人工核对：原版1/2提供单个选项，仅惩罚0/2，仅采样1/2，官方组合1/2。未运行评分器，也未按参考答案判断对错；这不是正确率。
这6条新轨迹中的VideoAgent结构化理由均未触1200字符上限，标点理由发生在Global决策阶段。

两题合计输出token：原3296，仅惩罚1983，仅采样2678，官方组合2725。
单遍总耗时分别226.31、155.91、206.20、240.33秒。缓存、预热和执行路径不完全相同，不能以此声称稳定提速；更快的条件也可能更早放弃取证或丢失解释。

## 结论与后续使用

- 可以缓解部分机械重复，不必把temperature0视为循环的唯一原因，也不能把非零temperature视为通用解法。
- 官方组合在CV712的实际取证行为更有价值，但Counting88仍失败，且出现标点理由；仅惩罚和仅采样各有不同退步。
- **正式默认仍保持greedy、presence_penalty0。** 这轮没有证据支持整体替换固定评测协议。
- 每条件只测seed0的一条生成路径；没有检验跨seed稳定性、9B/27B、非空skill、独立新题或准确率不退步，也没有做新采样协议的重复性矩阵。
- 后续若比较候选参数，空库与进化库必须固定同一参数和Prompt版本；不能把旧greedy成绩归于新采样设置。

## 验证与产物

- 远端compileall和两项既有契约测试通过；新增参数的有效值、边界与非法值拒绝断言通过。
- 两条greedy锚点与旧完整token/文本一致，包括207token的正常决策和2048token的截断终答。
- 106/106响应与服务端实际generation参数、完整token、输入/请求/Prompt哈希和worker记录一致。
- 所有冻结请求messages/grammar与来源相同；各完整流程首个决策的messages/schema与原版相同。后续轨迹由参数自然分叉。
- AST和逐文件检查确认实验副本只改server采样校验和provider请求注入，正式源码/配置未改；本地文档路径、skill链接与git diff --check通过。
- `manifest.json`、`sampling_patch.diff`、`frozen_repo/`、`cases.json`、`replay/`、六个完整运行目录、`progress.json`、`analysis_summary.json`、`driver.py`与`audit.py`均在runs volume。
- 最终分析已从外部volume SDK确认可读；15:36:57 UTC显式down返回terminated，1×H100已释放。

巡检：[progress_checks.md](progress_checks.md)。
