# DeepSeek Skill 运行验证与三模型开发面板

用户于2026-10-21授权将生成skill保存到AWS，并先验证选卡/策略注入/完整运行，再用最多64张H100比较9B、35B-A3B和27B，目标批次约2–3小时。

## 固定输入

使用DeepSeek首次生成的Global 6张、Video 8张。原始响应未通过Schema，原因分别为多出的`strategy_note: null`和`strategy_placeholder: null`。本次仅删除这两个已知空字段，程序按卡片ID逐字核对`when_to_use`与`strategy`没有变化；没有重新调用生成模型、按成绩选卡或修订策略。

这是**格式规范化后的LLM一次生成库**，不能写成原始响应直接通过Schema。
完整库SHA256：`7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049`。
AWS保存位置：`outputs/skills/deepseek_flash_20261021/`（不进入Git），包括完整库、两个角色库、两份原始响应、规范化记录及逐文件传输核验。
Modal原件保留于runs volume的`devbox/deepseek_skill_eval_20261021/skills/`。

## 实验协议

- 冻结运行源码：`0894a470b322ac0ed74744a6d3131fbdd778ca14`，所有模型/两臂用同一份源码。既有历史成绩不代替本轮空库对照。
- 数据：从既有CrossVid Lite2500开发池按任务分层、seed=0抽取360题，十任务各36题；三模型与两臂使用同题集合。没有向生成器提供这些样本。
- 两臂：Global/Video均关闭skill；Global/Video均开启本次库，task scope、自然选择一张或不选，Selector沿用各自Actor模型。6/8张候选不触发embedding检索。
- 资源计划：9B两组8H100，35B-A3B和27B各三组8H100，总上限64；每卡独立BF16/TP1/DP1/C1，固定seed=0、temperature=0、thinking关闭、prefix/MM缓存关闭，其余预算不变。
- 先在9B进行3题真实运行，核对两角色非空选择、完整策略出现在Actor请求、task复用、实际H100/worker配置和最终回答，再扩容正式面板。
- 正式每模型720条rollout，总2160条；分片交错两臂顺序。原始输出先保存，CCQA统一使用既定本地Qwen3-30B-A3B-Instruct-2507 Judge，评分失败保持失败。
- 主指标为CrossVid十任务macro，CCQA任务内部按评分点加权；同时报告有效样本、错误、每任务分数、选卡/注入情况和耗时。
- 2–3小时是按历史吞吐估计的批次目标，首次实测后核对；排队、加载和长尾可能影响墙钟。正式题量调整必须在扩容前冻结，不能按分数删题。

## 状态

库结构、字数、渲染、SHA加载、六份角色配置及文本保持检查通过；原始Schema失败不改写。
首个准备脚本曾错误地按数组位置核对Video卡（运行时按字符串ID排序），已改为按ID核对，失败准备目录保留。
运行产物统一位于`/runs/devbox/deepseek_skill_eval_20261021/`；当前已提交9B的8H100实例，真实选卡/注入验证尚未完成，尚无面板准确率结果。
