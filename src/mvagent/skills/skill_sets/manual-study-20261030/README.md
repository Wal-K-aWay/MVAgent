# 手写 Skill 机制与排版研究资源（2026-10-30）

**状态：部分开发测量。** 首批为8个机制（4 Global、4 Video）的24个排版快照，另有1个入口修订。候选区别取证的段落版及when-only修订各完成首Train40，相对空库分别+0.19231/+2.50pp；后者使用了同批Train诊断，不能称为稳定提升或独立确认。其余机制与排版正在测量，完整结果见[研究记录](../../../../../docs/skill-evidence-study-20261030.md)。
本批由 Codex 手工编写（不是人类领域专家独立卡片），英文操作句重新撰写，没有复制旧卡或调用 optimizer API；仅将历史合法 Train 公开轨迹中的缺口作为假设线索，未移植历史卡作为本轮种子。
正式研究仍从两个空库开始；这些资源须显式选择，默认不会加载，也不改变 Actor、Selector、工具、基础 Prompt、索引或评分。

每个机制有 `paragraph`、`numbered`、`headings` 三种排版；同一机制的操作句逐字相同且顺序相同，`when_to_use` 与 `meta` 相同。
`paragraph` 用空格连接原句；`numbered` 每句增加 `N. ` 并换行；`headings` 每句前增加 `#### Step N`。标题不增加操作描述。
排版增加的标记会改变token数；尚未进行排版间比较，不能从句子相同推断模型输出相同。纯排版诊断须另列，不冒充当前研究合同的正式消融或自动进化。

每个 SHA 命名文件均为 `schema_version: 3`、只有一张卡的非空整库；卡片 `id="1"`，`stages=["initial","evidence"]`。
库仅包含该角色卡；伙伴角色应使用本次实验显式冻结的库（初始可为空），不能把各单卡库拼接后沿用某个单库 SHA。
`manifest.json` 是离线目录索引，不是运行时库：它记录机制、原句、Train 来源、反例、与历史的关系，以及三种文件的字节 SHA256。
其中`status`保留建库时的未测试状态；本批实测进展以研究记录为准，原索引和旧24库字节保持不变。
24 个库的文件名均为完整 UTF-8 JSON 字节（含末尾换行）的 SHA256，与卡片的规范化内容哈希不同。

| 机制 | paragraph | numbered | headings |
|---|---|---|---|
| `global_dependency_closure` | [paragraph](a01f8b5e80aa73c4f5f8d74f6b3a87021fd4561b250b1144147d31f8be0c9619.json) | [numbered](c57521951888662030c358068f042f2eef494a6703f96a8e955dbc1b0df93446.json) | [headings](c051891d459bef0cd00ce6379d71160c8751ef1830d6c0ad555550e9ec103c7c.json) |
| `global_option_discrimination` | [paragraph](21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e.json) | [numbered](6255eeb992dc1f23a56ca843ba38aa5e702b33f98b48edbcb72cda4ec0730710.json) | [headings](05d5b3b751b3443b4e38ebcc8ceeeb11bfdcbdd2530af7e8c46072f3055a87b1.json) |
| `global_identity_candidates` | [paragraph](b08090d7d125fd18eeafb0b7c372e64d34afbd0d124db6181837735822bd1436.json) | [numbered](bb6f6f04cdc5c42b9662458740b3d4b3a2d2e11c357835c71ae76b5706be50c1.json) | [headings](6d298d3fdf16eaa9756fe2756e43cb5dff3e399863db1908dc40341d5be4f0ed.json) |
| `global_quantifier_bounds` | [paragraph](7434f8397ebc70bdcf0c6a105698e4e1d7872b876fd98f738d686d87d3c08f9d.json) | [numbered](3e7cf263204f1d412a86bffe89ebc633c04970bb9abbae030550ceaf49542b80.json) | [headings](b2bdabccc161b9a3bf6f080e6fb4ed61a80c903b88fabfd91a32d00979d636ee.json) |
| `video_negative_coverage` | [paragraph](886af9a3e61a6d48c2cf06b6d8e97957df7586246d212fbdf753564d740cbd56.json) | [numbered](7c7d61c23dc76da6bbae6aa8a6c466740e438a82ed048ffddbd4b118b2baf651.json) | [headings](d6779ab6c568630ab844ccb040c5e000ae67d11456224bf8a8dbfcbf4971067b.json) |
| `video_boundary_bracketing` | [paragraph](3e46018cb2341818e3f4231d58c151809d427a706841cf3e35238e88f6adee30.json) | [numbered](ae5b224dd497e1e78749b91cd090a0ad6eb69125bade55de1e528c48189560d2.json) | [headings](e524cf72dd595f7c858e629fb66c725332677abcd08309a9ae9b2c932eec7747.json) |
| `video_occlusion_identity` | [paragraph](bc0c8bcb27056899178445dd8c307f5ac62620e391054e5c2e7f7ec1169931b4.json) | [numbered](d5ff269276d009c36a75933b306064fbc81a9f685720895262e5d46d221cad42.json) | [headings](721129e2b06000b0f52c23b84a001a69904c1da0fca54f244291f8e01efa491b.json) |
| `video_observe_recovery` | [paragraph](1ccaf9f469aa727f310bd6e5fbde9bb084ba52ab6a1d9138075aa5148d089888.json) | [numbered](271050b5f087248275009451148ca31a59c61bcfbd0067b5804a5bce3a3a6641.json) | [headings](861c76dc1763dc6347f227dcd5f679d96b7c088da7cc27e05eaed471545b698e.json) |

Train 来源限于以下报告中明确标识的训练轨迹描述，不以其 Cal/Gate 分数或确认案例推导正文：

- [手工 Global 卡的 Train 设计依据](../../../../../docs/manual-global-skills-zh.md)和[手工 Video 卡的 Train 局部缺口](../../../../../docs/manual-video-skills-zh.md)。
- [探索报告](../../../../../docs/skill-exploration-results.md)的“已观察到的传递问题”及 Train 无效观察诊断。
- [反馈实验](../../../../../docs/skill-feedback-iteration-20261022.md)的“Global委派的约定与依赖诊断”Train 公开视图。

这些报告同时含历史验证汇总；作者此前阅读过这些汇总，此处不宣称作者对历史成绩盲法。卡片内容的推导范围限定为上述合法 Train 描述，未使用确认分区逐题内容或轨迹。
G1 与旧未测委派候选、G3 与联合比较、G4 与共同判据、V1 与逐项证据、V2 与事件边界存在明确继承；V3 的局部遮挡程序尚无已证实效用。
历史是否选中、行为变化或个别成绩均不能当成本批有效性的证明；媒体处理或运行身份不同的旧分数不能冒充新协议对照。

Global 只使用公开报告与联合观察，必要信息经 action 参数传递；Video 只用当前 instruction 与同视频证据，不声称拥有完整原题、其他视频或伙伴私有轨迹。
Video Selector 的入口不依赖隐藏 Memory 或未来报错；工具恢复遵守现有合法区间、FPS、帧预算、动作可用性、finish 前提与循环上限。
排版等句只证明资源构造，不证明视觉事实、策略执行或准确率；完整自然选卡评估与实际注入证据仍待获得。

[完整中文镜像](../../../../../docs/manual-study-skills-zh.md)逐卡保留入口与全部操作句。

## Train 入口收窄候选（完成首40题）

首批 Train 公开输入审读发现：开放式比较问题中的源视频标签可能被当成候选答案，使候选区别卡在没有答案列表时被选中。新候选只改 `when_to_use`，要求明确带标签的候选答案列表，且问题要求从中选择；视频列表、源视频标签和对象标记不算答案列表。

新库：[35fbe7b62f2fb0ba9dd1e20915289f46b7e5f4669f81816cdb68cd26e7f49b77](35fbe7b62f2fb0ba9dd1e20915289f46b7e5f4669f81816cdb68cd26e7f49b77.json)，父库：[21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e](21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e.json)。新库的 `meta` 与 paragraph `strategy` 逐字保持父库，未改写执行步骤、Actor 或 Selector。离线关系见 [entry_refinement.json](entry_refinement.json)，其中状态保留建库时未测试记录，实测见研究记录。首40题对原入口2改善/0退步，但选中率17→20/40；没有稳定收益结论。原 8 机制／24 排版文件及 `manifest.json` 保持原样。

本次只从 Train 的 Global 公开问题输入和终答审读得到入口假设，不使用 Cal/Gate 或冻结评测案例。这是单独的启用条件修订，不是新增机制或新增排版；后续分数与原入口应在同协议、同题下比较。

## Compact 执行候选（未测试）

另写8个paragraph短执行版，strategy由原193–224词压缩到129–149词；每个子库只改strategy，meta和when_to_use逐字继承原paragraph父库，G2不混入新when。完整资源、父子SHA、字数、压缩差别及反例见[step_refinement.json](step_refinement.json)，[完整中文镜像](../../../../../docs/manual-compact-skills-zh.md)。

保留前提、核心程序、未知/失败分支、停止条件与角色边界，压缩重复的工具字段说明。这同时改变步骤展开程度与文字长度，不是纯排版，也不声称完全语义等价。全部8个子库均计划在同120个Train题自然评估，最多960新增题次；没有按当前Train分数选卡，目前未提交、未测试。

加上这8个执行修订，本目录共33个非空单卡快照（24排版+1入口+8执行），仍只有8个基础机制。初始manifest与全部旧快照保持原样；默认运行不自动加载这些库。

## 多卡与双角色组合（未测试）

另有3个八卡整库快照：原paragraph八机制、仅替换G2新when、八个compact正文。所有文本按来源逐字复制，只按原机制顺序把引用ID改为1–8；每角色4候选，走小库全展示，不触发embedding。完整来源与映射见[combination_manifest.json](combination_manifest.json)、[中文说明](../../../../../docs/manual-combined-skills-zh.md)。

它们测库内竞争和两个角色同时启用，不能冒充单卡内容干预。三库全计划测同120个Train题，最多360新题次，当前未提交。现本目录合计36个非空整库快照（33单卡+3八卡），仍为8个基础机制；默认不启用，也不作为自动进化种子。
