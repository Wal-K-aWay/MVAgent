# Generator 中文镜像

System = TASK + BACKGROUND + CARD_CONTRACT；共用规范见 common.md。User 为 Train card-authoring input，包含 {context}。

生成有证据支持、可复用的整题方法。只返回 when_to_use、strategy 三个非空英文字符串，JSON 格式。程序分配编号，不返回 id。

两个字段遵循 CARD_CONTRACT。选择字段准确表达方法及必要前提。使用可观察条件、合法 action、来自输入或先前结果的参数，以及明确完成条件；strategy 使用编号的条件/action/参数说明。不假定 GT 已包含在返回证据中，不把已经清楚但未执行的规则当成缺失。领域线索可作说明，但保留通用证据关系；不承诺没有依据的题型能力。
