# Reviser 中文镜像

System = TASK + BACKGROUND + CARD_CONTRACT；共用规范见 common.md。User 为 Train card-authoring input，包含 {context}。

按反思模式修订目标卡，保留有证据支持的有效规则。返回 status（edit/skip）、revision_summary、when_to_use、strategy；skip 时两个内容字段均为 null。JSON 格式。目标 ID、role、stages 固定。revise_metadata 只修改 when_to_use，strategy 必须逐字保留；revise_body 修改有依据的正文缺陷并使选择字段与最终范围一致，避免无关改动。

两个字段遵循 CARD_CONTRACT。选择字段准确表达方法及必要前提。使用可观察条件、合法 action、来自输入或先前结果的参数，以及明确完成条件；strategy 使用编号的条件/action/参数说明。不假定 GT 已包含在返回证据中，不把已经清楚但未执行的规则当成缺失。领域线索可作说明，但保留通用证据关系；不承诺没有依据的题型能力。
