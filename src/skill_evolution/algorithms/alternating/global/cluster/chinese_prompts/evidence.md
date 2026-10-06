# 动态作者输入中文镜像

每个 batch 使用完整当前库，簇不绑定卡。显示固定目标（反思阶段无固定目标）、全部 Global 库的 id/when_to_use、实际使用的相关完整卡。
案例用 case_1 等本地标签，原始题 ID 仅保存程序材料，不在 Prompt 显示。输入完整问题/选项/视频 ID/时长、公开动作参数返回结果、最终答案、GT 和 correct/partially correct/incorrect 离线反馈；不显示数值 Train score，不提供 Video 私有轨迹。
显示支持编辑、相关拒绝候选及 not_accepted 状态、上一候选 Train 选卡变化（不是金标准），不显示 Gate 数据或得分。上限为最终两字段的 word 数。
独立选择字段作者读取新生成/修改的正文；正文修订必须有真实使用目标版本的锚点。
