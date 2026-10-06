# reflect 中文镜像

分析健康 Train 公开案例、实际选卡和注入版本。簇只组织案例，不绑定 Skill。每批选择一个 generate、revise_metadata、revise_body 或 skip。
revise_metadata：定位原始问题中可识别的条件缺失或误导导致误选/不选；对比任务目标、视频关系、证据需求与正文。不能按题材相似判定适用，不能将偶然领域、片段数量、时长或选项数量当必要条件。
revise_body：定位具体内容缺陷，锚点案例必须实际使用该完整版本。明确规则未执行不等于规则缺失。视觉/报告错误或答错本身不证明卡片缺陷；保留成功规则。
generate：有依据的方法尚不存在；没有选卡不自动证明需要新建。先考虑相近已有方法，也不能将无关错误塞进旧卡。
GT 是答案差异反馈，不是观察证据；不推测私有轨迹或未见帧。引用一个非满分锚点及支持案例标签；正文/新建编辑引用可编辑 Global 步骤；选择字段编辑可令 step=null。
返回 status、reason、target_skill_id、sample_id、step、evidence_ids。generate 不指定目标；revise 指定库中 Global 卡。skip 所有可空字段=null、evidence_ids=[]。
程序验证真实目标版本使用情况和锚点，不设模型置信度阈值。

文件结构：reflect/prompts.py定义TASK与REFLECT；REFLECT={context}，保持User原文本不变。reflect/schema.py定义动态build_schema与证据validate；__init__.py仅说明包用途。
