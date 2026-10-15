# Offline Skill evolution

当前实现：MVAgent 专用 SkillOpt 衍生流程，空 Skill 起步，Video/Global 交替单角色编辑。
2026-09-16 删除 joint 优化；在线 `watch_videos` 保持不变。详细设计与实验状态见
`analysis/skill_evolution/next_steps.md`、`handoff.md`；Prompt 中文镜像见
`analysis/current/prompt_chinese_reference.md` 第17节。

## 流程

1. 每 Train batch 先取得当前 pair 的 Video 轨迹；按完整系统成败分别分析。
2. 合并、排名最多选择一个条件化 edit；evidence_refs 必须引用实际收到的案例。
3. 固定 Global，候选 Video 与父 pair 在完整 Gate 同题各评估一次。宏分差严格为正且
   无逐题新增 fatal/invalid 才接受（`single-positive-health-v1`）。平分保留父版本。
4. 以最新 pair 取得 Global 训练证据，重复提议与 Gate。执行身份完全相同才可缓存复用。
5. epoch 1 保存 pre-slow 比较快照；从 epoch 2 起，同一 Train panel 执行前后快照，
   分角色 slow/Meta。slow 是受保护的部署策略，仍走同一 Gate；Meta 只指导未来 optimizer。
6. 训练结束在选择集做初态/终态单次配对确认，通过选择终态，否则选择初态。该确认不是独立 Test。
   另行 evaluate 开发审计集，不能用它挑选 checkpoint。

## 证据与边界

Global 保留完整问题、公共动作/report、最终答案和离线 GT，不接入 Video 私有轨迹。
Video 保留局部 instruction、Memory/action/observation/report、实际范围/FPS；局部没有 GT。
终局标签始终是系统反馈。附下一公共 Global 动作类别只提供路由背景，不声称报告被如何使用。
帧数未记录就标未知；实际步数/帧上限来自配置。API reasoning_content 不进入 optimizer。

fast 的 evidence_refs 经 merge/ranking 传递并检查；Skill 应用器只接受 op/target/content。
引用有效不证明策略有效，Schema 也不能证明因果关系或单一语义。
slow 同题对齐 video_id+调用序号，标注 instruction/伙伴变化、缺失侧、同 pair 缓存。
更新账本包含精确候选、接受/拒绝、分差和健康问题，不向 optimizer 暴露 Gate 逐题 GT。
保护区 fast 不可修改，只有 slow 可替换。空 Meta 输出保留旧记忆。

## 入口与恢复

`scripts/run_skill_evolution.py --mode train|evaluate --config ... --execution-config ... --output-dir ...`
训练才加载 optimizer；evaluate 不加载。配置全部在 `configs/skill_evolution/`，GPU 池可共享
`configs/inference/execution/gpu2_7_single.yaml`。密钥只读环境变量。
新运行要求空目录，自动冻结源码；恢复必须用原冻结 runner、配置、数据、Skill、评分身份。
`--repeat-id` 强制新的推理身份，不承诺 token 绝对确定性。

runner → algorithms → infra → MVAgent/scorers；Runtime 不依赖进化。基础设施负责数据隔离、
原始结果先持久化、评分缓存、精确编辑、原子 pair/checkpoint、媒体与源码指纹。
`optimizer_calls/` 保存模型实际输入、输出和校验状态；`optimizer_events/` 保存已支持的模型事件；
`attempts/`、`gates/`、`slow_meta/`、`state/`、各 Skill 导出和 `summary.json` 提供接续依据。

历史三次 Gate 分析仅在 `scripts/analysis/run_gate_calibration.py` 保留其原解释，不能据此
宣称当前训练仍评估三次。E0 控制组的 joint 只存在其冻结源码，不引入开关或兼容层。
