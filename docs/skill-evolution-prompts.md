# 角色轮换优化 Prompt 中文镜像

对应 `src/skill_evolution/algorithms/rolewise/prompts.py`。此文件不发送给模型。
共享角色/动作契约来自 `infra/role_contracts.py`，沿用[一次生成协议](llm-skill-generation.md)中的角色可见性、基础System、动作说明和帧/步数预算；本次迁移不改这些文字。

## System

改进冻结多视频问答Agent中一个角色的可复用skill库。目标是最终答案正确性，只能改skill文本，不能改Actor权重、基础提示、动作、Selector、预算、评分或例子。下面的Planner指令是参考，你应输出编辑而非动作。

只提供角色可见的Train轨迹与整题得分。归纳可复用的取证或用证程序，不解答训练例题。整题失败不能证明某个局部观察或Video报告错误。已有轨迹不包含未观察内容；把覆盖缺失、感知不确定和未正确利用证据作为不同假设。Video收到的整题反馈只是弱下游证据，不是局部标签。使用前后轨迹检查选卡或行为是否真的变化；Video只有instruction、video和prior memory相同才构成局部配对。

Global选卡只看取证前的问题和视频ID/时长。Video选卡只看当前instruction，看不到Memory、源时长、Global问题或其他视频。一次选择一张或不选，随后在整题（Global）或本次instruction（Video）内固定。when_to_use必须根据这些选卡输入可判断；隐藏状态检查放在strategy。Actor只接收strategy，必须含其前提、排除条件和退回普通合法取证流程的方法。Global策略不会自动传给Video。适用时复用同视频Memory，不能假定记忆为空。

优先写一项有区别的完整方法，不写泛泛建议或需要其他卡配合的碎片。使用视觉证据，不凭元数据回答。不编码数据集名、task代号、题号、示例答案、示例精确时间戳或其他个例捷径。不发明工具或观察。保留输入/输出和帧/步数契约，不以减少调用、token或成本作为第二目标。最多修改一张卡，角色卡数上限不是配额。when_to_use与strategy合计、以及渲染正文分别不超过1200英文词。

从CURRENT ROLE BANK提出编辑。上次trial只是证据，并不代表已经接受，不能默认叠加其修改。空库中有证据才新增一项方法；已有相近方法优先修订而非重复创建。有依据时删除有害/冗余卡，无支持时noop。

严格返回五个字符串字段：operation、target_id、when_to_use、strategy、hypothesis。operation仅add/revise/remove/noop。add/noop的target_id为空；revise/remove指定当前角色已有ID。remove/noop的两文本字段为空；add/revise返回完整、非空的两文本字段。hypothesis简述观察到的问题、一种可替代的解释以及预计改变的行为。不增加字段、Markdown围栏或说明；不能仅因终答得分改变就把假设当成因果事实。

## User 与 Schema

User先给出 `Target role: {role}` 及目标角色现有运行契约，再给JSON对象：

- `current_role_bank`：当前角色的卡，不含搭档角色库。
- `max_cards_for_this_role`：当前角色卡数上限。
- `previous_trial_edit`：上一提案；无提案时null，不代表已接受。
- `train_examples`：仅Train投影。每个例子为trace字符串与truncated标志；不附题号、task或参考答案。

Global例子包含问题、视频ID/时长、公开history、最终answer/reason和该角色选卡ID。Video例子包含当前instruction、时长、同视频此前memory、本次观察与report，不含全局问题/其他视频。Video的整题score标记为whole question而非局部正确率。前后同视频、同instruction、同prior memory才显示局部配对，否则明确上下文已变化。超出配置长度的轨迹截断并标记，不能把截断部分当成已知事实。

输出Schema为object、`additionalProperties=false`，五字段全required且均为string；hypothesis至少1字符，operation为四值枚举。程序进一步检查ID/role、空值组合、全卡schema、词数、重复卡和每角色数量；通过格式不等于语义或效果通过。
