# VAM 退役与 LensWalk 本地接入验证

2026-10-16，LensWalk 已接入本地 Qwen3.5-35B-A3B。三个 benchmark 的6道开发题全部完成执行，5题产生终答；MSR361耗尽原版5轮后仍在规划，不能算有效答案。该结果证明接口可运行，不是完整 benchmark 成绩或论文复现。

## 逐题结果

| 数据 / 题目 | 输出 | 结束方式 | 官方逐题分 | 整题秒数 | 模型请求 |
|---|---|---|---:|---:|---:|
| CVBench 764，单选 | 长解释，最终选 D | 自然文本；未按要求只输出字母 | 0 | 113.01 | 15 |
| MVU-Eval TR1585，单选 | `B` | finish | 1 | 98.16 | 11 |
| CrossVid MSR361，多选 | “I need to continue my investigation…” | 轮数耗尽，留下未完成工具计划 | 0 | 343.17 | 52 |
| CrossVid PSS341，排序 | `1->2->3` | finish | 1 | 78.50 | 7 |
| CrossVid FSA394，定位 | `42.04,52.55` | finish | IoU 0.587454 | 158.09 | 17 |
| CrossVid CCQA73，开放问答 | 自然语言比较两段视频的腌菜制作过程 | finish | 未启动 Judge | 309.74 | 36 |

开放题原回答称视频A没有腌菜制作、主要是肉类处理和三明治组装；视频B用米醋和水腌制胡萝卜与白萝卜。这里仅展示模型输出，不对其正确性背书。

有效轮总墙钟1145.50秒（19.09分钟），其中模型启动44.03秒；6题累计1100.67秒（18.34分钟），平均183.44秒、中位135.55秒。单题计时包括客户端初始化、抽帧、工具调度及所有模型调用，不含已有拼接媒体的准备。首次冷启动曾用214.35秒；开发失败轮的记录单独保留，不混入有效轮测速。

共138次请求：28次规划、110次视觉响应；累计380个图片输入（含重复观看）、240767输入token、20506输出token。0 HTTP错误、0输出token截断、每次prefix命中0、同一H100副本。MVU TR1585和FSA394各有1次同时填写`num_slices`与`slice_duration_sec`的互斥参数错误，随后自行恢复。这两次是模型工具使用错误，不是服务故障。

`execution.success`只表示包装器正常退出，不能直接当作有效答题数。MSR361的最后一条assistant消息仍带观察工具调用，上游把其中的规划文本保存成了answer；最终分析将其单列。CV764没有调用finish，但最后自然文本确实提出了D这一答案，同时有格式偏差。4次finish加这1条自然终答，共5个终答。

## 保留的原版设置与适配

- 上游 release `c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77`。原System/User、工具定义、观察逻辑和默认5轮保留；scan次数限制、subject registry、字幕及初始直接帧注入均按代码默认关闭。公开代码默认5轮与论文20次工具调用有区别。
- 原版最长边512，scan/segment/stitched默认帧预算180/32/128；没有额外448限制。复用已验证的原视频拼接，拼接阶段不缩放、不调FPS；题面说明多视频任务、时间轴，两位小数。
- Planner原请求未指定温度，本地标准vLLM API缺省为1；Observer显式0.2。两者原请求均未设输出token上限，实际上限为剩余上下文。138次实际请求/服务端参数逐一核对，未套2048或8192。
- 本地Qwen为BF16、单H100、TP1/C1、seed0、thinking关闭、prefix/MM cache关闭，沿用固定FlashInfer GDN及原生GemmaRMSNorm数值后端。此次为单卡顺序接入验证，batch_size=1（上游默认15），workers沿用8；不代表8卡批量吞吐。
- 客户端单独使用Python3.11（上游要求Python<3.12）；服务端仍用已验收的Python3.12/vLLM0.19.1。服务单请求600秒、冒烟执行器单题1800秒；此次没有触发。
- 唯一修改的上游文件是评测入口，增加inference-only开关，避免调用其内置评分。原始答案先保存，再用本项目官方评分器离线评分；参考答案不进入推理输入文件。
- 本地原生工具解析使用官方`qwen3_coder`，只在解析返回值时展开schema的本地引用，模型看到的原工具schema不变。云API默认值及strict执行语义不能据此宣称与本地后端完全等价。

接口开发曾出现两轮失败：第一轮时间区间schema的`$ref`被原生解析器当成字符串，结果整理也误计`tool_raw`重复事件；第二轮已有4次视觉响应，但复制渲染后的Pydantic迭代器导致后续规划服务失败。现仅复制工具schema、排除重复日志事件，两项回归均通过。初始CV规划请求核对显示，原轮与最终轮的首个请求、prompt token及输出token相同，支持修复没有改写初始模型输入；这不是一般重复性证明。

## VAM 清理

已删除活动VAM适配器、视觉Embedding服务/下载器、补丁、过时混合启动入口，以及本机/devbox上的VAM与视觉Embedding源码克隆。删除前确认四个旧外部实验Sandbox均已退出。

删除VAM专属`Qwen3-VL-Embedding-8B`共16,305,638,705字节，独立客户端依赖403,485,886字节，合计16,709,124,591字节（约16.71GB）。共享Qwen3.5、MVAgent文本`Qwen3-Embedding-8B`、Judge、历史答案/评分和冻结源保留。清理审计为`devbox/vam_retirement_20261016/manifest.json`，状态completed。

## 验证与留档

远端完整compileall、适配契约/传输审计、原生工具解析/开放答案/API缺省检查、原版两项mock及RSI预算/600秒检查通过；后续两项接口修复分别通过针对性回归，最终6题完成真实模型调用。有效轮源与当前`lenswalk.py`、`lenswalk_server.py`、补丁SHA一致；模型相关代码备份版本为`b33633b`，完整工作区按文件哈希冻结，不能将该提交当作整个共享工作区的单一快照。

原始数据仅保存在Modal runs volume `wxu-evolve-agent-runs-20261006`：

- `devbox/external_lenswalk_20261016_r3/`：冻结源码、6题输入/轨迹、实际请求、官方评分、`integration_summary.json`、`audit.json`、`source_input_audit.json`及分析源码。
- 不带后缀和`_r2`目录：原始失败证据；准备阶段失败目录另存。
- 本次Sandbox：`sb-4HtAjF2y42Ye3CIXyHfwPD`，独立名称`mvagent-lenswalk-20261016`。实验结束后释放；巡检停止。

所有题目来自已用过的65题开发面板，仅覆盖少量题型；不据此计算完整benchmark准确率、比较论文排名或声称所有输入都稳定。未跑全量、未训练或进化LensWalk、未评开放题Judge。运行入口及参数表见[适配说明](../../eval/external_methods/README.md)。
