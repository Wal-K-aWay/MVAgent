# Global 决策 System：冲突取证与简洁表达（2026-10-13）

仅修改 `src/mvagent/agents/global_agent/prompts.py` 的 `GLOBAL_AGENT_SYSTEM_PROMPT`，保留第二版（refined，172词；原193词）。
User、独立终答System、VideoAgent提示、schema、字段顺序、预算、接口和采样配置都未改。

**结论：局部改善，没有消除循环或答案格式问题。** 第二版在CV712减少了冗长决策，但额外调用增加；Counting88未改善，且初始决策理由仅为逗号。不能宣称所有输入稳定遵循规则或准确率不下降。

## 通用规则与参考

- 冲突是具体待核实的问题：报告自信或分析已经完成，不代表证据完整、结论无误。
- 可用观察用于核实缺口；冲突说一次再行动，避免用重复论证替代观察。
- 每次检查解决一个明确不确定点；没有新增信息时调整重点。有依据或后续检查无益时结束，保留重要不确定性。
- 决策解释一到两句，只保留决定性证据/缺口及行动目的，完整输出当前步骤所需结果。

参考了[smolagents ToolCallingAgent](https://github.com/huggingface/smolagents/blob/main/src/smolagents/prompts/toolcalling_agent.yaml)
的行动/观察闭环、按需调用和避免同参数重复，以及
[OpenHands CodeAct固定版本](https://github.com/OpenHands/OpenHands/blob/754a96e7f33c68f55e7323d37f83234846cef519/openhands/agenthub/codeact_agent/prompts/system_prompt.j2)
的探索与验证原则。没有照搬工具名、领域例子、长规划或额外运行机制。

固定规则没有绑定reason/answer字段、动作名称、benchmark、视频编号、FPS或观察顺序。
“观察什么、选哪段、如何比较、不同问题采用什么证据策略”仍留给Actor与后续skill自进化。
空库基线和进化库比较须固定同一System版本；历史分数不等同于新版分数。

## 保留的 System 原文

```text
You coordinate the task by choosing actions that turn observations into a supported judgment.

- Preserve the task's definitions, constraints, identifiers, and required output. Use available evidence; separate observations, inferences, and unknowns. Missing information is not evidence of absence.
- Check conflicting evidence before concluding. When observations or reports disagree with each other or leave the required judgment unsupported, use an available observation to verify the specific point. A completed analysis may still be incomplete or mistaken; confidence in a report does not resolve a contradiction.
- Each check must address a named uncertainty. If it adds no information, change the focus rather than repeat it. Finish when the judgment is supported or further checks cannot add useful information, retaining material uncertainty.
- Keep each explanation to one or two short sentences: the decisive evidence or unresolved point and the purpose of the next action. State the conflict once, then take the action. Do not rehearse alternatives, guess what the task intended, or invent missing facts.
- Return the complete required response.
```

## 测试范围与对照

- 35B-A3B BF16，固定配置同步后端，FlashInfer GDN与native GemmaRMSNorm；seed0、temperature0、presence_penalty0、thinking关闭。
- 1×H100，TP1/DP1/C1，无skill；决策reason仍限1200字符、每次2048输出token、Global/Video各最多5步、最多512帧。
- 三版候选各重放4个既有决策：CV712、Counting88、CV376、BU504。消息中只替换System，User和schema完全相同。
- 三版候选各跑完整CV712/Counting88；CV712复用同协议旧concise基线，Counting88新跑旧System完整对照。
- 新增12次冻结重放、7条完整轨迹，共123次模型调用；涉及4个开发题，其中2题跑完整流程。不能将调用数当作独立样本数。
- 不评分、不调用Judge、不重跑重复性矩阵。四题均为复用开发题，不是独立测试集。
- 远端AST和逐文件检查确认src/config除一个System常量外与基线一致；远端compileall、两项既有终答契约测试通过。

## 冻结决策：原版与保留版

| 样例 | 原版动作 / reason字符 | 保留版动作 / reason字符 | 观察 |
|---|---|---|---|
| CV712 | watch_videos / 1200 | watch_videos / 402 | 保留继续观察，理由不再触顶 |
| Counting88 | answer / 1200 | answer / 1200 | 仍反复讨论“没有选项符合”，没有补证据 |
| CV376 | answer / 1200 | answer / 1200 | 仍把未出现事故与事故风险比较混淆，循环未解 |
| BU504 | answer / 320 | answer / 267 | 明确共同动作的对照保持直接回答 |

CV712保留版理由指出“某动作只在部分视频被报告，需要联合核实另一个视频是否漏看”，随后实际请求观看三个视频。
它是合理取证方向，但单个检查点不能证明新增观察一定有用，也不能证明最终判断正确。

## 完整 Agent：原版与保留版

| 样例 / 版本 | 调用 | 输出token | 秒 | Global决策reason字符 | 最终answer |
|---|---:|---:|---:|---|---|
| CV712 原版 | 14 | 2719 | 174.10 | 319 / 1200 / 1200 | C |
| CV712 保留版 | 18 | 2299 | 157.69 | 182 / 381 / 545 / 251 | C |
| Counting88 原版 | 15 | 1220 | 85.83 | 281 / 1200 | None of the options are correct as no video shows a ceiling fan. |
| Counting88 保留版 | 15 | 997 | 68.62 | 1 / 1200 | 同原版 |

- CV712新增一次针对video_3缺失细节的分析；四次Global决策均未触1200字符。终答理由从2555降到606字符，但它仍把一般“倾倒”与题目具体动作混为一谈，答案仍为C。没有把更短视作更准确。
- Counting88依旧把肯定的否定报告当作全部证据，没有继续观察；末次reason触顶，最终answer不是题目要求的单个选项。初始reason只含逗号，属于解释质量退步，schema仍接受它；本次未改变验证规则。
- 保留版两题共33调用、3296输出token；无服务错误、结构化错误、repair或token截断。原版两题合计29调用、3939token。
- 耗时是单遍观测，旧/新运行的缓存与启动环境并非独立受控；不能据此声称稳定提速。调用数增加也说明加强取证会增加成本。
- 1200字符触顶与2048 token截断是两种不同指标；结构化成功不代表题目格式或理由质量合格。

## 未采用版本

第一版177词强调“缺口说一次再行动”：三个冲突重放仍全部1200字符，CV712还由watch变成answer。
完整CV712为14调用/1932token/141.61秒，仍有一个1200字符决策；Counting88仍非选项答案、首步逗号理由。

第三版173词把简洁规则前置，并明确题目条件与报告的冲突也需核实。
重放仍有两个1200字符理由；完整CV712变为19调用/4236token/277.21秒，终答首次生成达到2048token上限，触发一次结构化失败与一次repair，最后仍答C。
因此不采用；保留原始负结果，不把“指令更强”当作实测更稳定。
第三版Counting88为15调用/1223token/84.47秒，决策理由312/1200字符，最终仍为非选项答案；未发现额外服务或结构化错误。

## 产物与限制

原始结果只在runs volume：`devbox/decision_system_20261013/`。
父目录为第一版及Counting88原版对照，`refined/`为保留版，`focused/`为第三版；各自包含冻结源码、manifest、配置、replay和正式CLI完整轨迹。
`final_audit.json`保存实际服务端token/输入哈希/采样参数核验；`audit.py`与各driver保留在同一volume。
123/123请求均与实际服务端记录一致，各版完整流程首个决策的User/schema相同，冻结重放只改System。
本地AST确认只有决策System改变且与被测SHA256一致；文档引用、skill符号链接与git diff --check通过。
保留版System的SHA256为`acb36637f9288ad5a5ec6703abeed55d7d46ac253fb4fcf3fd8355ce0cb8b4a3`。
最终审计从外部volume SDK确认可读，13:55 UTC显式down返回terminated，1×H100已释放。

运行时代码只改Global决策System；同步根AGENTS、Agent评测README、环境skill、状态笔记和报告索引。
此前工作区已有其他改动，本次没有重置或提交它们。

尚未验证9B/27B、未见过的题目、非空skill、准确率不退步或所有输入都能避免循环。没有新增答案枚举或格式修复机制。
保留版是通用规则的局部改善，不能作为问题已经解决的声明。巡检见[记录](progress_checks.md)。
