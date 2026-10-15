# 12条空答案：逐轨迹根因分析

2026-10-15北京时间。范围仅为此前13:53–13:54比较快照中的12条：9B 3条、27B 8条、35B-A3B 1条。只读检查原始结果、事件、实际响应和冻结源码；没有修改项目代码、推理配置、评分或结果，没有重跑任何题目。

## 结论

| 类型 | 9B | 27B | 35B-A3B | 合计 |
|---|---:|---:|---:|---:|
| 终答初次和修复均2048 token截断，未生成answer字段 | 1 | 8 | 1 | 10 |
| 旧服务请求体过大触发传输错误，固定副本后续拒绝调用，无终答响应 | 2 | 0 | 0 | 2 |
| 日志显示超时导致空答案 | 0 | 0 | 0 | 0 |
| 收到完整合法终答JSON后被误丢弃 | 0 | 0 | 0 | 0 |

12条空字符串均由Runtime的`_terminal_fallback`产生，而非模型正常返回一个空answer。
10条共20次终答响应，全部finish_reason=length、completion_tokens=2048；对原文独立运行json.loads，全部为reason字符串未闭合（Unterminated string，char10），且均不存在answer字段。
另外2条在终答阶段没有model_response，不能归因于模型不愿回答或输出截断。

## 全部案例

“2×2048”表示初次终答和一次修复各达到2048输出token。耗时为整题记录秒数。

| 模型 | 题号 | 进入终答 | 耗时 | 直接失败 |
|---|---|---|---:|---|
| 9B | crossvid:BU:453 | 第2轮主动answer | 148.56 | 2×2048，重复列举独有行为 |
| 9B | crossvid:PEA:510 | 5轮后第6轮强制终答 | 174.41 | Broken pipe，随后固定副本拒绝请求 |
| 9B | crossvid:PEA:838 | 5轮后第6轮强制终答 | 219.40 | Connection reset by peer，随后固定副本拒绝请求 |
| 27B | crossvid:PEA:348 | 第2轮主动answer | 329.56 | 2×2048，报告与选项冲突 |
| 27B | crossvid:PEA:496 | 第3轮主动answer | 433.59 | 2×2048，补充观看后仍与选项冲突 |
| 27B | crossvid:PEA:618 | 第3轮主动answer | 382.65 | 2×2048，无拆卸/无多余步骤报告与选项冲突 |
| 27B | crossvid:PEA:628 | 第3轮主动answer | 431.83 | 2×2048，反复排除选项 |
| 27B | mvu_eval:KIR:448 | 5轮后第6轮强制终答 | 726.43 | 2×2048，跳水难度分组反复比较 |
| 27B | mvu_eval:KIR:458 | 第4轮主动answer | 476.66 | 2×2048，观察分组不对应任何选项 |
| 27B | mvu_eval:KIR:471 | 第3轮主动answer | 469.31 | 2×2048，分组与选项冲突、反复改变拟选答案 |
| 27B | mvu_eval:KIR:520 | 第4轮主动answer | 531.55 | 2×2048，单个最简单视频与集合选项不匹配 |
| 35B-A3B | crossvid:PEA:555 | 第2轮主动answer | 332.05 | 2×2048，明确进入重复论证循环 |

## 实际轨迹一：35B-A3B，PEA:555

1. 第1轮Global选择analyze_videos，分别询问三个VideoAgent是否有连续“拆下、重新装上”的多余步骤。
2. 三份报告都表示未观察到此类拆卸。第2轮Global仍在讨论“报告都说没有，但选项是某个视频或All videos”，决策reason达到1200字符，选择action=answer；尚有后续决策机会。
3. 独立回答器第一次生成2048 token，全部仍在reason中。以下原句重复16次：

> If I have to choose, and the evidence says 'No' for all, then D is the only option that is 'All', which is false.

4. JSON解析失败，系统发起一次修复，要求返回最小完整对象、压缩自由文本、不要继续重复之前分析。修复同样输出2048 token；上述句子重复21次，结尾甚至写到“This is a loop. Let”。
5. 两次均没有answer字段，Runtime返回空字符串。最终reason被固定写成“GlobalAgent reached its decision-loop safety limit.”，与实际第2轮主动回答不符。

这是模型在证据与选项冲突时没有收束，叠加reason先输出、整次2048 token预算和仅一次修复的失败。不是推理超时，也不是已经有完整答案后解析器误删。

## 实际轨迹二：27B，KIR:471与KIR:448

KIR:471：第1轮分别分析六个跳水视频；第2轮watch_videos比较；第3轮选择answer。终答认为视频1/3/4/6属于同一难度，视频2和5不同，但现有选项不对应这个分组。原响应反复出现“Wait, did I misread the 'watch_videos' result?”；修复中“I will output C and explain the evidence.”出现两次，随后又继续否定/比较选项。

这句话仍处于reason字符串，既没有闭合JSON，也没有answer字段。因此不能把reason里的候选C当作已提交答案，更不能说解析器丢掉了正确答案。两次均length/2048，整题469.31秒。

KIR:448确实耗尽5个Global决策：两轮analyze_videos、三轮watch_videos，然后第6轮强制终答。回答器仍在不同视频难度分组与报告之间来回比较，两次均length/2048。真实步数耗尽解释了为什么进入强制终答，但空答案的直接原因仍是终答两次未完成，不能简单归为“max_steps”。

## 实际轨迹三：9B，BU:453

第1轮分析三个日常活动视频，第2轮主动answer。回答器反复列举哪些行为只出现在视频1、哪些跨视频共有。以下三类句子在初次输出和修复输出中分别都重复8次：使用笔记本电脑、把书放到书架、拿起笔记本电脑是视频1独有的行为。

两次都是2048 token，均未离开reason字符串。该例说明循环不限于复杂选项冲突，普通行为枚举也可能退化；不能假定只把总token预算加大就一定完成。

## 实际轨迹四：9B两条传输故障

原始结果实际位于`devbox/mvagent_full_20261013/9B`，当前transport目录通过符号链接继承它们。

| 题目 | 失败多视频请求体 | 当时上限 | 首次错误 | HTTP阶段耗时 |
|---|---:|---:|---|---:|
| PEA:510 | 552124587字节，526.55MiB | 512MiB | Broken pipe | 约0.0032秒 |
| PEA:838 | 546341525字节，521.03MiB | 512MiB | Connection reset by peer | 约0.0027秒 |

两题均在第5轮watch_videos时发送上述大请求。冻结旧服务在读取Content-Length后、读取正文前检查512MiB上限，超出即拒收；日志的立即断连与该检查一致，证据指向旧请求体限制，而非等待超时。

首次传输失败后，固定副本租约保留未完成/隔离状态。随后一次重试以及第6轮终答都在本地准入时被拒绝：

> Pinned replica failed for qwen3_5_9b_local; retry the whole question

每题因此有3条model_error，但没有终答model_response；两条空答案无法归因于生成能力。日志里后续endpoint显示8100是provider在获取租约前初始化的默认值，失败发生于准入，不能据此认定真的切换了GPU。

当前冻结服务已经提高到2GiB。不过前次恢复只重跑原来顶层status=error的101题，其余5220题原样继承；这两条由于终答故障被Runtime吞入兜底、外层status仍为ok，没有被列入重跑清单。上限已修复，并不意味着这两条遗留结果已修复。本次没有补跑或改变其评分。

## 工程边界与记录问题

1. **空答案的生成位置明确。** engine._request_terminal_answer遇到invalid结构化结果或异常后，调用_terminal_fallback；后者直接构造answer=""，并写固定的安全步数上限reason。
2. **错误原因被误标。** 12条中9条是第2–4轮主动选answer，只有3条真正走完5步；但12条最终reason都一样。详细失败仍在trajectory/events中，不能只读最终reason。
3. **外层status=ok不代表终答成功。** batch worker只要engine.answer正常返回对象就标ok；终答异常已被捕获，不再传到调度器。eval记录据此计为完成并评分0，resume也按该status跳过。这解释了之前“顶层0错误”与实际12条空答案同时存在。
4. **解析器在这10条中的拒绝有依据。** 独立json.loads复核全部20段原文都未闭合，不是合格JSON被错误识别。现有repair也实际执行，但20段均未生成answer字段；没有一个可直接恢复的结构化最终答案。
5. **长度约束须分清。** 实际终答请求schema中reason无字符maxLength；answer要求非空，maxLength2400字符。触发的是整次响应2048输出token上限。Global普通决策的reason仍有1200字符限制；部分案例决策reason触及它，但本次未做消融，不能据此断言这是终答循环的因果来源。

因此，2条传输失败属于工程故障及恢复遗漏；10条属于当前模型在既定输出协议/预算下无法完成终答，其中模型的重复论证是直接观察，reason先于answer、有限修复、空兜底和错误分类则是工程侧的影响因素。不能把全部12条都归为模型能力，也不能只归为JSON解析器问题。

## 证据与未做的工作

- 远端审计目录：`devbox/mvagent_parallel_20261015/empty_answer_audit_20261015`。summary.json、diagnosis.json、code_path_proof.json及12个案例JSON保存原始结果路径/哈希、完整响应与轨迹、终答schema和冻结源码证据。
- CPU读取与独立JSON解析均成功，无GPU推理、无Judge。三个CPU app为ap-8WRFJKIygUq6XJL4NkuNnP、ap-4b93GxV4cgDlz9o79h0czB、ap-7SmbhZaolDwula91DzJeYR。
- 核对了engine、LLM结构化调用、GlobalAgent、schema、batch和eval入口共7个文件；工作区与冻结源SHA256均一致，因此下列本地行号适用：engine.py的812/850错误处理和880空兜底；batch.py的120外层ok；eval/agent_eval/run.py的177恢复跳过；scripts/resume_full_mvagent.py的继承逻辑。
- 没有修改任何项目代码、prompt、schema、预算或恢复规则，没有重跑12题，没有扩大到运行中新增加的空答案，也没有重新观看原视频以判定视觉报告本身是否正确。不能声称提高预算或改变输出顺序一定解决；这些需要后续独立实验。
