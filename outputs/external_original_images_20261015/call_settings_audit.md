# RSI HTTP600与模型调用检查

2026-10-15，北京时间。用户要求Video-RSI请求等待改为600秒，VAM保持240秒；若问题来自模型在原提示词下的表现，则保持原方法，不优化提示词或采样。此前65题RSI/3题VAM仍是1860秒历史批次，不改写其配置与成绩。

## 已保存的改动

- `rsi.py`中本地HTTP等待1860→600秒，实际配置记录同步；原solver1800秒、两角色8192 token、temperature0、1次请求重试不变。
- `test_rsi_timeout.py`验证两角色原`PinnedProvider.chat`最终收到600秒，同时校验原solver/温度/token/重试未变。
- 设置审计、说明及新准备流程的超时元数据同步为600；历史冻结运行保留原值。
- VAM不改代码；实际超时读取函数返回请求240秒、连接60秒。Embedding仍为原60秒/连接10秒。

## 调用核对结果

远端CPU读取既有503次服务端实际生成记录：468次RSI均为temperature0/top_p1/max_tokens8192/seed0；VAM35次均保持原调用点的temperature和token上限。没有发现参数被接入层错误覆盖。所有方法均未启用额外JSON约束，符合原项目的提示词约束方式。

本地`SamplingParams`实际默认：top_k0（不截断）、min_p0、presence_penalty0、frequency_penalty0、repetition_penalty1、ignore_eos=False。490次自然结束输出含模型EOS；13次触顶输出均未产生模型两个EOS中的任何一个（248044/248046）。本轮重复不是已经输出EOS、服务却继续生成。

权重目录的配置、tokenizer和模板文件SHA逐一与原服务manifest匹配；冻结的模型服务、外部适配入口和RSI视觉工具源SHA不变。最大实际输入34793 token，低于131072上下文限制，没有触及上下文截断边界。

CV722不合格视觉回复与CV764合格视觉回复的实际prompt token解码均保留JSON要求，结尾均为Qwen3.5官方非thinking模板的空`<think>…</think>`段。`thinking=disabled`已经转换为`enable_thinking=False`，没有误开thinking。两条完整输出token解码与客户端保存的原始文本一致，没有接入层重复拼接、丢弃JSON或误取别的响应字段的迹象。

## 格式不合格和重复的来源

171次视觉服务调用全部包含上游原句“Return one JSON object using this format”及`observations`、`image_indices`等字段要求。按原解析器检查：

| 结果 | 次数 |
|---|---:|
| 合格、带帧引用的观察 | 99 |
| 没有可解析JSON对象 | 65 |
| JSON对象缺少observations列表 | 5 |
| observations没有有效带帧引用的观察 | 2 |

失败通常从开头就写成自然语言“Based on the provided images…”以及Markdown列表，未遵循要求的对象结构，并非网络等待不足导致JSON被传输层截断。11条触顶视觉报告也全部未形成合格观察。

RSI三题相同工具参数重复执行2–5次；已有实际请求和输出哈希相同，且该批0 HTTP错误，因此这些重复不是超时重试。模型再次选择同一个动作，原框架按指令执行，temperature0使相同视觉输入再次得到相同回复。VAM原检索代码也会逐查询检查候选，复用同一`inspection_prompt`，候选重叠时可再次检查同一帧；它没有跨查询的请求去重，这与接入层出错不同。

一个需要保留的限制：沿用原项目temperature0等参数，不等于Qwen3.5推荐的最佳采样。Qwen官方非thinking通用任务建议temperature0.7/top_p0.8/top_k20/presence_penalty1.5，并说明presence_penalty可用于减轻循环重复。[官方模型卡](https://huggingface.co/Qwen/Qwen3.5-35B-A3B#best-practices)。这里的差异是既定评测选择；不能既保持原参数，又声称已经使用Qwen最佳采样。未做采样干预，不能量化它对本批重复的因果贡献。

目前证据支持“Qwen3.5在原项目提示词与生成设置组合下，部分请求遵循格式不佳，并出现重复”，没有发现需要修复的本地调用配置错误。不能据此说模型在任何设置下都不能输出JSON，也不能证明更换推理后端完全没有影响。按用户要求保留原提示词、温度、输出预算、解析器和执行逻辑，不加入重复惩罚、强制JSON、自动改写或结果缓存。

## 验证与产物

CPU实际传参检查、VAM超时读取检查和已有源码语法检查通过。原冻结包不包含`scripts`/`demo.py`，本次没有对不存在的路径宣称完成全项目检查。

单卡H100真实复测正在执行：重放CV722的一条原不合格视觉请求，再以600秒新默认跑完整CV764题；不新增Judge或准确率实验。结果另存Modal runs volume `devbox/external_call_audit_20261015`，含`audit.json`、`end_token_audit.json`、冻结源码和原始请求。完成后补充实测结果。
