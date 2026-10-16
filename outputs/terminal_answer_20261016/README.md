# Global 主动回答与独立兜底

2026-10-16，按用户确定的方案恢复独立兜底、History旧排布，保留当前Global System和FFmpeg。代码检查点`0d30a8c`，固定运行依赖补齐检查点`aad5fad`，分支`codex/terminal-answer-20261016`。

## 最终行为

- 主动选择answer时，同一次决策的`parameters.answer`就是答案，不发独立回答请求。
- Global循环耗尽时，调用`GlobalAgent.answer()`；PRO6000专用System和问题/公开History模板生成`reason/answer`，沿用结构修复和错误记录，外部状态仍为`forced_with_gaps`。服务故障仍按原路径传播，本次不加入服务恢复或更改错误分类。
- 决策User顺序为Question→Videos→History→Available actions。当前Global决策System、全部动作说明（含主动回答门槛）、FFmpeg媒体实现和固定数值后端均未改变，已静态核对。
- 兜底System与模板逐字来自已核验的PRO6000 27B快照；理由长度沿用当前无字符硬限，整次2048 token，answer仍是开放非空字符串且最多2400字符。没有恢复旧27B/35B的1200字符终答上限。
- 移除仅供旧兜底使用的`answer_only`分支；公开eval CLI、普通决策和整题返回接口不变。skill继续影响正常决策与主动回答；兜底按旧接口只接收问题和公开History，不额外选卡。

“回答门槛”是Prompt的停止指导：旧版要求现有证据充分解决关键判断，当前允许判断已获支持或进一步取证无法增加有效信息时给出最佳判断。本轮解释其差别，未修改该指导。两版主动answer都直接提交答案。

## 验证

- Modal CPU `ap-2ZR6BhPLdYvTQI7WA5KoCm`：完整`compileall`通过，14项接口测试通过，覆盖主动回答单次调用、终止回答契约、History顺序、生成grammar、skill保留和异常记录。
- 该CPU命令末尾额外引用的`test_agent_finalize.py`不在隔离分支，命令整体因此返回2；这不是上述14项测试或编译失败，也不将该未运行测试记为通过。结果汇总器未在本轮修改。
- 补齐固定运行依赖后，在CPU `ap-RGGg56YwvmFqXTnykw9REI`重新执行完整compileall与14项接口检查，全部通过、整体rc0；后续新增profile入口断言已在实际GPU环境执行通过。
- GPU冒烟使用独立`mvagent-terminal-answer-20261016` / `sb-fS1XYdFx6xu4Nra6QussVk`，实际1×H100 80GB，三BF16模型依次加载、TP1/C1/seed0/T0固定。每模型1道完整题×2遍，再用固定History做2次兜底；只核对运行、输入hash、完整token与轨迹，不评分、不启动Judge。
- 首次启动未产生模型回答：隔离备份分支缺少已验收同步服务的接入依赖，误走普通vLLM并在过长IPC路径处退出。原记录保留在`devbox/terminal_answer_smoke_20261016`。已补齐10个必需运行/执行配置文件，逐文件SHA与此前900配对的实际冻结源完全一致；它们是既有固定配置，不是本轮新增数值优化。验证脚本现在先断言解析后的profile生效。
- 修复后新结果目录为`devbox/terminal_answer_smoke_20261016_r2`，复用同一张H100，原始记录和冻结源码只在runs volume；当前冒烟待完成。

既有900配对、旧独立回答器全量及PRO6000原始结果均不改写，本轮协议不能沿用其准确率成绩。未自动执行旧S/H/P或60/300题准确率计划；有限冒烟不证明所有输入的格式、准确率或重复性。

## 阶段结果：9B

CV664完整Agent两遍均主动提交C，固定最终History的独立兜底两遍均提交`}`。30实际调用/15配对，输入/完整token与轨迹0差异，0模型错误、0结构错误、0length。兜底reason自然结束且说明选择wire，但answer仍为右花括号。这是合法JSON中的模型答案格式失败，不是截断、解析丢字或服务故障；没有从reason提取答案来掩盖它。

本轮没有评分，因此不把主动C当作答对或准确率改善。恢复兜底调用并不能保证有效答案，当前按用户确定的调用架构保留这个负结果；27B/35B待完成。
