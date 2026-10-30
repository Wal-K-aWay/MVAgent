# 手工 compact 执行版完整中文镜像

状态：未测试的手工研究资源；当前进展见[研究记录](skill-evidence-study-20261030.md)。仅 strategy 改写；meta 与 when_to_use 继承各机制原 paragraph 父卡，未采用另行修订的选项入口。

本对照同时改变步骤展开程度与文字长度，不是纯排版，也不宣称完全语义等价。目标为 strategy 100–160 英文词；继承入口后的全卡总词数另列。全部 8 卡均计划测试，不按当前 Train 分数选择。原 24 库与入口修订保持原样。

## 跨视频依赖闭合（global_dependency_closure）

英文权威子库：[3d763c9eeb3ed6ababe9007259e207718357fc53df39bde67b429bc731c1ac13](../src/mvagent/skills/skill_sets/manual-study-20261030/3d763c9eeb3ed6ababe9007259e207718357fc53df39bde67b429bc731c1ac13.json)。父 paragraph 库：`a01f8b5e80aa73c4f5f8d74f6b3a87021fd4561b250b1144147d31f8be0c9619`。角色：`global`；meta（原样）为 `{"id": "1", "role": "global", "stages": ["initial", "evidence"]}`。

strategy：220→141 英文词；含原入口共 186 词。

### when_to_use（父卡原入口完整镜像）

问题需要先在一个视频中建立某项事实，才能解释另一个视频中的事件、身份或状态；题目可能明确给出视图、标签或同步约定。在发出依赖该事实的局部请求前先解决参考依赖；相互独立的逐视频判断不需要此流程。

### strategy（compact 完整镜像）

遇到跨视频依赖时，区分所需参考事实与目标结果，只保留问题明确提供的约定。复用充分的公开 History；独立请求仍可并发。若目标依赖未知参考，先用 analyze_videos 获取该事实及可见依据。将返回的有支持描述、来源身份和必要时间约定放进随后目标请求的 instruction；并发请求不能使用兄弟请求尚未返回的报告。仅在联合视觉对应关系具有决定性时使用 watch_videos，说明关系，选择至少两个视频及各自时长内的有效 clip，不传 fps。将未解决的参考或假定的跨视频事实视为缺口，只在可能改变答案时澄清。当依赖证据支持所求结果时回答。达到运行时上限时，按题目格式给出证据最支持的非空答案，并在 reason 中保留重要不确定性。

## 候选答案区别驱动取证（global_option_discrimination）

英文权威子库：[f6dbd4c7a020c1e877ef85f712ea0b0feda2cd1d8dcd6fc6c265de2d1ea79adb](../src/mvagent/skills/skill_sets/manual-study-20261030/f6dbd4c7a020c1e877ef85f712ea0b0feda2cd1d8dcd6fc6c265de2d1ea79adb.json)。父 paragraph 库：`21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e`。角色：`global`；meta（原样）为 `{"id": "1", "role": "global", "stages": ["initial", "evidence"]}`。

strategy：196→134 英文词；含原入口共 180 词。

### when_to_use（父卡原入口完整镜像）

问题提供了多个候选答案，且可通过视频中的具体可见事实或关系区分它们的真伪。围绕候选之间的区别取证，而不是对每个视频作一般性叙述；排除未提供候选的开放问题，以及仅凭没有视觉支持的假设才能区分的候选。

### strategy（compact 完整镜像）

当给定候选需要通过视觉区分时，找出能区分它们的事实或关系，不遗漏限定和组合条件。标签不是证据。对可独立观察的区别使用 analyze_videos，在每条局部 instruction 中给出中立判据及必要背景，不要求局部代理选择答案选项。对具有决定性的跨视频关系使用 watch_videos：明确该关系，选择至少两个视频及各自时长内的有效 clip，不传 fps。缩小片段前，先用局部请求定位未知时刻。区分有支持、被反驳和未解决的候选；报告中的遗漏不能排除选项。若仍有多个候选，核查会影响结果的未决区别；报告支持本应互斥的答案时，重新核对准确条件。证据确定所求答案时停止；否则遵守有界终结，按要求格式给出最有支持的非空答案，并在 reason 中说明限制。

## 跨视角身份候选消歧（global_identity_candidates）

英文权威子库：[ea5d6c86faf4e2ecf05bfa1b788389c7f5f05c89143e2fbc0ed85c9f50ff7356](../src/mvagent/skills/skill_sets/manual-study-20261030/ea5d6c86faf4e2ecf05bfa1b788389c7f5f05c89143e2fbc0ed85c9f50ff7356.json)。父 paragraph 库：`b08090d7d125fd18eeafb0b7c372e64d34afbd0d124db6181837735822bd1436`。角色：`global`；meta（原样）为 `{"id": "1", "role": "global", "stages": ["initial", "evidence"]}`。

strategy：203→137 英文词；含原入口共 185 词。

### when_to_use（父卡原入口完整镜像）

问题的主要任务是判断某个特定人或物是否、或在何处跨视频对应，而不是判断物体是否属于相同类别或具有相似外观。根据题目给出的约定及可见区分证据建立身份候选，再比较未决候选；不从视频 ID 或时长假定对应关系。

### strategy（compact 完整镜像）

处理跨视频的物理身份对应时，仅根据问题的目标描述、已给约定和可见区分证据初始化候选。除非题目明确关联，一个视图中的标签不能确定另一视图的身份。用 analyze_videos 发出自洽的局部 instruction，获取候选特征、可见路径和锚点；初始化信息不足时询问，不猜测外观。保留所有相容候选及其来源；仅类别或颜色相似不能证明身份相同。若联合特征能解决对应，使用 watch_videos，选择至少两个不同视频及其时长内的有效 clip，不传 fps；缩小范围前先定位未知时刻。仅凭不相容的观察或明确约定排除候选。遮挡或未观察到的特征仍属未决。当有支持的身份依据解决对应时回答；达到运行时上限时，按要求格式给出证据最支持的答案，并在 reason 中披露剩余歧义。

## 量词答案上下界与停止（global_quantifier_bounds）

英文权威子库：[4f465281d95f7811cf18285cfa3f05fba6cbe95698bc38c76a3c44aeb5f95cd5](../src/mvagent/skills/skill_sets/manual-study-20261030/4f465281d95f7811cf18285cfa3f05fba6cbe95698bc38c76a3c44aeb5f95cd5.json)。父 paragraph 库：`7434f8397ebc70bdcf0c6a105698e4e1d7872b876fd98f738d686d87d3c08f9d`。角色：`global`；meta（原样）为 `{"id": "1", "role": "global", "stages": ["initial", "evidence"]}`。

strategy：193→129 英文词；含原入口共 172 词。

### when_to_use（父卡原入口完整镜像）

问题需要把可逐视频独立观察的条件，合成为全部、任意、恰好某数、计数或符合条件的子集答案。追踪哪些尚未解决的局部判断仍可能改变答案；排除统计单视频内重复事件的任务，以及无法逐视频独立决定的身份匹配。

### strategy（compact 完整镜像）

对于可逐视频独立判断的条件，保留谓词、限定、被计数实体，以及结果是是非判断、准确数量还是完整子集。用 analyze_videos 传递相同的中立判据和必要定义，请求各来源的可见依据与限制。区分有支持的符合项、排除项和未知项。符合项给出计数下界，加入未知项给出上界；遗漏不等于排除。检查解决未知项是否可能改变所求结果；即使是非结果已确定，准确子集仍可能需要解决每个潜在成员。仅对重要缺口追问；收紧上下界前，先解决谓词变化或报告冲突。当所有与证据相容的结果一致时回答。若运行时更早结束，按要求格式给出证据最支持的非空答案，并在 reason 中说明剩余界限。

## 否定判断与覆盖证据（video_negative_coverage）

英文权威子库：[c730c3d50cc923478071e6624e568bddc27588919748de42d98309497699de3e](../src/mvagent/skills/skill_sets/manual-study-20261030/c730c3d50cc923478071e6624e568bddc27588919748de42d98309497699de3e.json)。父 paragraph 库：`886af9a3e61a6d48c2cf06b6d8e97957df7586246d212fbdf753564d740cbd56`。角色：`video`；meta（原样）为 `{"id": "1", "role": "video", "stages": ["initial", "evidence"]}`。

strategy：198→138 英文词；含原入口共 186 词。

### when_to_use（父卡原入口完整镜像）

instruction 询问指定事件或物体是否不存在、是否只出现所列项目，或本地清单是否完整。在作否定或穷尽性断言前，先判断同视频观察覆盖了什么；只请求一个正例的任务不需要此流程。

### strategy（compact 完整镜像）

作否定或穷尽性判断时，仅使用本视频的 instruction 与保留 Memory，确定目标及所需可见和时间范围。检查正向依据、矛盾与覆盖限制；某项未被提及或进行过广泛采样，都不能证明不存在。若仍有重要缺口，用 observe 提出关于目标及可见性的中立 what，where 使用时长内合法、有序、互不重叠的区间，fps 使用允许值。区分未观察到与相反证据，保留遮挡、身份或采样带来的不确定性，不依熟悉活动补全内容。断言有支持，或运行时内可用观察无法解决重要限制时，停止取证。仅在已有可用同视频证据且 finish 可用时，概括有支持的判断与覆盖限制，不输出内部工具、区间、fps 或跨视频结论。否则遵守有界终结协议，不编造观察。

## 事件边界双侧状态夹逼（video_boundary_bracketing）

英文权威子库：[1d1eb682ea080fd7a9de9d8f015619deba515b10b819b6b47b40db71c795ecdd](../src/mvagent/skills/skill_sets/manual-study-20261030/1d1eb682ea080fd7a9de9d8f015619deba515b10b819b6b47b40db71c795ecdd.json)。父 paragraph 库：`3e46018cb2341818e3f4231d58c151809d427a706841cf3e35238e88f6adee30`。角色：`video`；meta（原样）为 `{"id": "1", "role": "video", "stages": ["initial", "evidence"]}`。

strategy：216→142 英文词；含原入口共 181 词。

### when_to_use（父卡原入口完整镜像）

instruction 要求本视频中事件的开始、完成、持续区间，或对边界敏感的顺序。先确认事件，再用周围状态变化界定要求的端点；排除不需要边界定位的一般性描述和粗顺序任务。

### strategy（compact 完整镜像）

处理事件边界时，保留动作与对象条件、所需端点和有支持的同视频锚点。若事件尚未建立，用 observe 识别事件与相关状态变化，where 采用合法、有序、互不重叠的区间，fps 使用允许值。用此前非事件状态及事件出现界定起点，用事件持续及其后改变或完成状态界定终点。采样中的首次出现或裁剪边缘本身不是边界。保留周边背景，检查可信锚点尚无支持的一侧；若身份或锚点可疑，则扩大范围，不反复细化它。将画面外或有歧义的端点保留为未决。instruction 所需的时间区别得到支持时停止。仅在已有可用同视频证据且 finish 可用时，概括有支持的源视频时间、精度和缺失边界，不输出内部区间或 fps；遵守运行时上限，不编造区间。

## 遮挡后身份重新确认（video_occlusion_identity）

英文权威子库：[d4445ad2e10e19111a2b543ca96b48f4a381a6cd5cc48a071ed0aea653099003](../src/mvagent/skills/skill_sets/manual-study-20261030/d4445ad2e10e19111a2b543ca96b48f4a381a6cd5cc48a071ed0aea653099003.json)。父 paragraph 库：`bc0c8bcb27056899178445dd8c307f5ac62620e391054e5c2e7f7ec1169931b4`。角色：`video`；meta（原样）为 `{"id": "1", "role": "video", "stages": ["initial", "evidence"]}`。

strategy：207→146 英文词；含原入口共 190 词。

### when_to_use（父卡原入口完整镜像）

instruction 要求在本视频中追踪特定人或物、判断该实体的后续行为，或区分它的重复出现与不同实体。维持本地身份连续性，并明确解决再次出现时的身份；排除不依赖身份的静态类别或属性检查。

### strategy（compact 完整镜像）

进行局部身份跟踪时，仅根据 instruction 给定的约定及保留的同视频证据初始化目标；缺少识别特征时询问，不任意解释标签。用 observe 检查可区分外观、运动和地标，where 采用合法、有序、互不重叠的区间，fps 使用允许值。仅凭有支持的连续性或区分依据延续身份。发生遮挡、离画或无法区分的交会后，保留相容候选，不直接选择最近的再次出现。若身份不确定性会改变所求行为或计数，检查中断两侧及候选的区分特征，不编造隐藏路径。仅在有支持时区分不同实体与重复出现。局部结果有支持，或请求内无法解决歧义时停止。仅在已有可用同视频证据且 finish 可用时，概括有支持的身份、行为及不确定性，不输出内部区间、fps、跨视频匹配或虚构轨迹。

## 观察工具反馈驱动恢复（video_observe_recovery）

英文权威子库：[d3132336c3660dd08c821df83dc65406d77dc418550abb786185114ad3440a0e](../src/mvagent/skills/skill_sets/manual-study-20261030/d3132336c3660dd08c821df83dc65406d77dc418550abb786185114ad3440a0e.json)。父 paragraph 库：`1ccaf9f469aa727f310bd6e5fbde9bb084ba52ab6a1d9138075aa5148d089888`。角色：`video`；meta（原样）为 `{"id": "1", "role": "video", "stages": ["initial", "evidence"]}`。

strategy：224→149 英文词；含原入口共 192 词。

### when_to_use（父卡原入口完整镜像）

instruction 要求细粒度动作细节、短暂局部事件，或依赖可执行观察计划的事件区间。根据实际时长及可用反馈调整同视频观察；先前报错或隐藏 Memory 不是选中本卡的前提。

### strategy（compact 完整镜像）

对于依赖细节的局部请求，保留实际目标，observe 前检查时长及保留的同视频证据。what 应中立且可通过视觉回答；where 使用时长内合法、有序、互不重叠且起点早于终点的区间，保留小数秒，fps 使用允许值。将拒绝或失败反馈作为诊断，不当作观察；仅在反馈支持纠正时，更改导致问题的参数或取证请求。成功观察仍无有效信息时，先区分问题不相关、覆盖不足与细节未决，再更改 what、where 或 fps。不要原样重复无效请求。当证据支持局部结果，或运行时内没有有依据的纠正时停止。不得延长循环、绕过验证、增加帧预算或调用不可用动作。仅在已有可用同视频证据且 finish 可用时，概括有支持的事实与不确定性，不输出内部失败、区间或 fps；否则遵守有界终结，不声称观察成功。
