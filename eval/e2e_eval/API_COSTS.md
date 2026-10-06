# 国产多模态模型官方 API 测试成本

更新日期：2026-09-22。

## 结论

> **实现边界：** `api/run.py` 当前实现的是五个模型均可比较的“512帧有序多图 +
> 官方实时 Chat Completions”协议。下述最低成本估算采用了原生视频和官方 Batch，
> 属于下一阶段目标协议；在对应传输、任务提交和账单预检实现前，不能直接用本表
> 的 Batch/原生视频价格外推当前脚本的实际账单。

在只使用模型厂商官方接口，并尽量采用官方 Batch、订阅额度和谷价的前提下，本轮五个模型的预计总成本为：

> **约 ¥1820–3050**

建议实际准备 **¥2500–3500**，其中包含少量输出、失败重试和视觉 token 波动。若不使用 MiniMax Token Plan、改用其官方按量 API，总成本约为 **¥2660–4640**。

## 512 帧实时接口实测（CVBench 前 10 题）

2026-09-22 使用同一组 CVBench 前 10 题完成了 Qwen3.8-Flash、GLM-5.3-Flash
和 DeepSeek Flash 的官方实时接口预检。三者均为每题总帧上限 512、最长边
720、单 worker；全部 10/10 成功且无最终错误。这里的费用按返回的 usage 和
下文实时单价计算，未读取厂商账单中的缓存折扣。

| 模型 | 实际视频帧 | 输入 / 输出 token | 串行用时 | 10 题估算费用 |
|---|---:|---:|---:|---:|
| Qwen3.8-Flash | 5118 | 870,115 / 27 | 8.9 分钟 | ¥0.696 |
| GLM-5.3-Flash | 5118 | 2,303,069 / 227 | 17.7 分钟 | 约¥2.454 |
| DeepSeek Flash | 5118 | 1,156,126 / 10 | 2.4 分钟 | 空闲¥1.156；高峰¥2.312 |

Qwen 将超过250个内联 data URI 的输入转换为临时 OSS 中的有序帧列表；
DeepSeek 为避开48 MiB请求体限制，最多保留24 MiB内联图片，其余用一小时
Files API引用。这些只是传输封装变化，没有改变帧内容和顺序。GLM 的第7题
出现约380秒长尾，因此均值106秒/题显著高于中位数69秒/题。

按该小样本均值机械外推，5324题实时多图协议约为：Qwen **¥371 / 79小时**、
GLM **¥1306 / 157小时**、DeepSeek空闲价 **¥616 / 21小时**（高峰约¥1231）。
若改为完整CrossVid、共11839题，则约为：Qwen **¥824 / 176小时**、GLM
**¥2905 / 349小时**、DeepSeek空闲价 **¥1369 / 47小时**（高峰约¥2738）。
时间均为单 worker 串行值。前10题共享部分视频，且全部来自CVBench，不能代替
三个 benchmark 的分层样本；尤其不能据此推断 CrossVid 开放题输出成本。

## 测试范围与输入协议

- CVBench：1000 题；MVU-Eval：1824 题；CrossVid Lite：2500 题；合计 5324 题。
- 这不是完整 CrossVid 9015 题。
- 每题最多 512 帧，最长边 720，关闭或采用最低思考强度。
- CVBench、MVU-Eval：支持时采用官方原生视频接口。
- CrossVid：采用有序多图，保留视频 ID、帧序、时间戳、bbox 和片段对应关系。
- DeepSeek 不支持视频文件，三个 benchmark 均采用有序多图。

Qwen、MiMo、GLM、MiniMax 的混合协议输入量暂按 4.5–8 亿 token 估算。DeepSeek 因逐帧图片计费，按 8.2–13.6 亿 token 估算，极端上限约 27.9 亿。美元按 `1 USD = 7.1 CNY` 折算。

## 官方最低成本汇总

| 模型 | 官方渠道与计费方式 | 输入/输出价格 | 预计成本 | 采用原因 |
|---|---|---:|---:|---|
| Qwen3.8-Flash | 阿里云百炼 Batch | ¥0.4 / ¥1.35 每百万 token | **¥180–320** | 官方实时价五折；支持图片和视频 |
| MiMo-V2.6-Flash | 小米 MiMo Batch | ¥0.5 / ¥1 每百万 token | **¥225–400** | 官方实时价五折；支持原生视频 |
| GLM-5.3-Flash | Z.ai 官方按量 API | $0.15 / $0.50 每百万 token | **约¥480–852** | 未查到可核验的官方 Batch 或峰谷折扣 |
| MiniMax M3 | 官方 Token Plan Max | **¥119/月** | **¥119** | 月度约18亿 token，较稳妥覆盖预计输入量 |
| DeepSeek-V4.1-Flash | 官方 API 空闲时段 | ¥1 / ¥4 每百万 token | **¥820–1360** | 空闲价为高峰价五折 |
| **合计** |  |  | **约¥1824–3051** | 不含税费、Judge 和较大规模重试 |

## 各模型计费说明

### Qwen3.8-Flash

| 方式 | 输入价 | 输出价 | 本轮成本 |
|---|---:|---:|---:|
| 官方实时 | ¥0.8/M | ¥2.7/M | ¥360–640 |
| **官方 Batch** | **¥0.4/M** | **¥1.35/M** | **¥180–320** |

Batch 是异步执行同一批测试，不是重复测试。使用中国内地百炼端点比国际区更便宜。正式提交前需确认 Batch 请求接受当前视频/多图载荷，并用固定小样本检查 usage 和输出映射。

来源：[阿里云百炼模型价格](https://help.aliyun.com/en/model-studio/model-pricing)、[Qwen 视觉模型说明](https://docs.qwencloud.com/developer-guides/getting-started/vision-models)。

### MiMo-V2.6-Flash

| 方式 | 未命中缓存输入 | 输出 | 本轮成本 |
|---|---:|---:|---:|
| 官方实时 | ¥1/M | ¥2/M | ¥450–800 |
| **官方 Batch** | **¥0.5/M** | **¥1/M** | **¥225–400** |

Batch 同样是官方实时价五折。不能预先假定视觉内容命中 Prompt Cache，因此主预算按未命中缓存计算。原生视频应预编码为最多512帧、最长边720、无音频；不能只依赖动态 FPS。

来源：[MiMo 按量计费](https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go)、[MiMo Batch API](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/batch-api)。

### GLM-5.3-Flash

| 方式 | 输入价 | 输出价 | 本轮成本 |
|---|---:|---:|---:|
| **Z.ai 官方按量 API** | **$0.15/M** | **$0.50/M** | **约¥480–852** |

GLM-5.3-Flash 是原生多模态模型，但本次未查到能够稳定核验的官方 Batch 五折或峰谷计费规则。因此不能把 OpenRouter 的 Batch/促销价格当作 Z.ai 官方价格。国内 BigModel 控制台如显示更低人民币价，应在购买前保存价目截图、模型 ID 和时间，再替换本表预算。

来源：[GLM-5.3-Flash 官方发布说明](https://autoclaw.z.ai/blog/model/glm-5.3-flash/)、[Z.ai API](https://z.ai/consultation)。

### MiniMax M3

MiniMax 提供按量 API 和官方 Token Plan。Token Plan 的订阅 Key 可以接入自有 OpenAI 兼容工具，且额度覆盖文本、图片和视频理解。

| 方式 | 价格/额度 | 本轮成本 | 风险 |
|---|---:|---:|---|
| 官方按量 API，输入≤512K | $0.30/M 输入，$1.20/M 输出 | **约¥959–1704** | 最稳定，无订阅窗口限制 |
| Token Plan Plus | ¥49/月，月度约6亿 M3 token | ¥49 | 可能在输入量上界前耗尽 |
| **Token Plan Max** | **¥119/月，月度约18亿 M3 token** | **¥119** | 有5小时固定窗口、周窗口和动态限流 |
| Token Plan Ultra | ¥469/月，月度约71亿 M3 token | ¥469 | 本轮没有必要 |

本轮推荐 Max，而不是更便宜的 Plus：预计输入上界约8亿 token，Plus 标称6亿不足以稳妥覆盖。Max 的18亿额度足够，但它面向个人开发者和交互式场景，批量任务可能被限流；应将并发控制在官方允许范围并接受更长完成时间。如果接口实际限制妨碍5324题完成，应切换官方按量 API，届时总预算增加约 **¥840–1585**。

来源：[MiniMax 官方 API 价格](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise)、[MiniMax 中国区 Token Plan](https://platform.minimaxi.com/subscribe/token-plan?code=GRfkLENRwq&source=link)。

### DeepSeek-V4.1-Flash

| 北京时间 | 输入价 | 输出价 | 本轮成本 |
|---|---:|---:|---:|
| 工作日 09:00–12:00、14:00–18:00 | ¥2/M | ¥8/M | ¥1640–2720 |
| **其余空闲时段** | **¥1/M** | **¥4/M** | **¥820–1360** |

应在北京时间夜间、周末或其他空闲时段提交，并设置预算上限，避免失败重试跨入高峰。DeepSeek 只接受图片；每请求最多600张，512帧数量上可行，但请求体大小、Files API 和单图 token 仍需预检。不要按其他原生视频模型的3–6亿token口径估价。

来源：[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)、[DeepSeek 视觉输入限制](https://api-docs.deepseek.com/guides/vision/)。

## 预算情景

| 情景 | Qwen | MiMo | GLM | MiniMax | DeepSeek | 合计 |
|---|---:|---:|---:|---:|---:|---:|
| **最低官方方案** | Batch ¥180–320 | Batch ¥225–400 | 按量 ¥480–852 | Max Plan ¥119 | 空闲价 ¥820–1360 | **¥1824–3051** |
| MiniMax 改按量 | 同上 | 同上 | 同上 | ¥959–1704 | 同上 | **¥2664–4636** |
| 全部官方实时且 DeepSeek 空闲 | ¥360–640 | ¥450–800 | ¥480–852 | ¥959–1704 | ¥820–1360 | **¥3069–5356** |
| DeepSeek 全落入高峰 | Batch | Batch | 按量 | Max Plan | ¥1640–2720 | **¥2644–4411** |

## 执行建议

1. 先做每个模型 5–10 题的接口与账单预检，但这些样例随后作为正式结果保留，不重复推理。
2. Qwen、MiMo直接创建官方 Batch 任务；保存 `custom_id` 到题目 ID 的映射。
3. GLM 使用官方按量端点，设置账户硬预算和最大重试次数。
4. MiniMax 先购买 Max Token Plan，以低并发持续运行；只有确定套餐限制无法完成时才改按量。
5. DeepSeek仅在空闲时段启动，复用已上传图片和 Files API ID，避免重复上传。
6. 每条结果记录模型精确版本、接口、输入模态、实际帧数、输入/输出 token、缓存命中、价格档和请求时间。

以上成本不含 CCQA Judge、对象存储、税费、汇率波动和异常大规模重试。CCQA Judge 应作为独立账单报告。完整 CrossVid 9015 题不适用本预算。
