# 原项目设置一致性审计（2026-10-15）

结论：此前不能称为“除LLM外完全一致”。主要方法预算已按原版执行，但本次发现VAM跳过顶层路由、两方法客户端依赖版本未对齐；已修正代码并安装独立依赖环境。用户明确批准的通用答案、448限制、拼接提示和RSI HTTP1860秒继续保留。原云端服务的未公开默认值不能认证相同。

## 核对依据

- Video-RSI：commit `5ad014499a5e009b75e3ef05ac83595b78adda09`，使用官方发布的`artifacts/final_harness`，没有重跑进化。
- VAM：commit `4f759407945674e0b296ecee22bd53cf910ae39b` 的源码归档；本地reference没有独立.git，不能把父仓库HEAD误作VAM版本。
- 对照原始源码SHA、补丁、远端每题`effective_config.json`、模型与Embedding manifest以及实际HTTP请求。
- 13:28核对RSI70文件、VAM43文件及原Qwen Embedding实现90文件，与冻结后的`adapted_source_sha256.json`全部一致。
- 相对原始源码：RSI仅7个已记录补丁文件发生变化（通用答案、提示/修复格式、448图像和隔离适配）；VAM仅`frame_store.py`补充缺失的`import re`。但外层wrapper也必须审计，仅比较仓库文件不足以发现调用入口绕过。

## 原版参数对照

| 项目 | 原项目 | 当前目标设置 | 结论 |
|---|---|---|---|
| RSI规划/视觉输出 | 8192 / 8192 | 8192 / 8192 | 相同 |
| RSI temperature | 0 | 0 | 相同 |
| RSI步数/服务调用/帧暴露 | 11 / 64 / 256 | 11 / 64 / 256 | 相同 |
| RSI整题预算 | 1800秒 | 1800秒 | 相同 |
| RSI provider重试 | 1次重试，最多2次尝试 | 同左 | 相同 |
| RSI HTTP等待 | 240秒 | 1860秒 | 用户批准的例外；旧冻结批次仍240 |
| RSI抽帧 | 串行、imageio-ffmpeg、单帧60秒、JPEG编码1线程 | 同左 | 相同，额外四路并行已撤回 |
| RSI图像 | `scale=768:-2` | `scale=448:-2` | 用户批准；是固定宽度，不是统一最长边448 |
| RSI答案与Prompt | 单个实际选项 | 通用非空答案字符串及相应Prompt/修复规则 | 用户批准；不是逐字相同的Prompt |
| RSI技能与工具策略 | 发布的final harness/skill库 | 原文件 | 相同，未重新进化 |
| VAM各调用输出 | 原调用点220/300/500/700 | 原调用点值 | 相同，无统一2048覆盖 |
| VAM温度 | 原调用点0/0.1/0.2 | 原调用点值 | 相同，未强制全部temp0 |
| VAM检索轮数 | 默认20 | 20 | 相同，未设置VAM_AGENT_MAX_TURNS覆盖 |
| VAM索引FPS/帧数 | 0.5fps / None | 0.5fps / None | 相同 |
| VAM过滤 | Laplacian20、diff20、SSIM0.92、hist0、相似度0.88 | 同左 | 相同 |
| VAM事件 | 阈值0.80、最长300秒；finalize开启、等待120秒 | 同左 | 相同，相关环境变量未覆盖 |
| VAM记忆层 | 3600/86400秒窗口；间隔1/20/120秒；768/512尺寸；JPEG70/45 | 同左 | 相同 |
| VAM图像限制 | 1280²像素、5MB | 448²像素、5MB | 用户批准的像素面积例外 |
| VAM视频上下文 | 最新segment开启、base64上限10MB | 同左 | 相同，实际调用仍有video_url |
| VAM聊天等待/重试 | 240秒、连接60秒、最多10次尝试 | 同左 | 相同 |
| VAM Embedding等待/重试 | 60秒、连接10秒、最多4次尝试 | 同左 | 相同 |
| VAM顶层入口 | `stream_agent_response` | 已恢复同入口 | 旧wrapper直接search_generator，属于非预期差异 |
| VAM帧ID/索引状态轮询 | TUI前缀v、0.25秒 | 已恢复v、0.25秒 | 旧wrapper是input、2秒 |

当前调度按整题固定GPU副本，原RSI批处理配置并发16受本地端点数限制。它是适配层的资源调度，不等于原云API吞吐条件；不能直接用本地耗时复现论文速度。

## 实际运行证据与纠正

13:28的旧RSI批次491次请求均为temperature0/max_tokens8192（其中79次HTTP错误，参数核对不代表请求成功）；旧VAM62次请求为7次0.1/700、54次0.1/500、1次0/500。旧VAM没有300-token顶层路由调用，与wrapper直接调用检索循环一致。

**更正之前的记录：旧VAM的3份实际effective_config均为200704像素，Embedding manifest也是200704，即448²。此前声称旧轮未启用448是错误判断，混淆了工作区版本与远端冻结版本。**旧轮需要排除完整原版结论的原因是跳过顶层路由；依赖版本也未对齐。

恢复原入口后的TR1585真实端到端冒烟完成：返回`B`，内部耗时18.49秒（索引17.91秒、问答0.58秒），3次实际调用、0请求错误。顶层路由请求为300token/temperature0，实际输出`{"type":"final","text":"B"}`；这是原Agent允许的直接回答路径，没有强行替换为检索。此次冒烟仍使用旧共享客户端依赖，只证明恢复后的入口可运行；不与旧轮耗时作纯因果提速比较。

记录：`devbox/external_vam_router_20261015`。原RSI延长HTTP验证仍为TR1585返回B、482.05秒、5调用/0请求错误，最长8192token响应447.81秒。

## 依赖差异与修复

旧环境RSI锁文件22项中13项不匹配，包括NumPy2.2.6而非2.5.2、ONNXRuntime1.31.0而非1.29.0、Pillow12.2.0而非12.3.0，OpenCV使用headless4.13而非要求的opencv-python5.0.0.93。旧VAM的NumPy2.2.6和OpenCV4.13也违反其NumPy<2、OpenCV<4.11约束。

已在Modal CPU独立安装：

- RSI：原`requirements-lock.txt`全部22项固定版本，逐项版本及NumPy/OpenCV实际导入检查通过。
- VAM：全部13项适用依赖约束通过；NumPy1.26.4、opencv-python4.10.0.84。后续运行时导入发现共享SciPy需要NumPy≥2，另以SciPy1.14.1对齐间接依赖，兼容性与SSIM检查已通过，warnings-as-errors无警告。
- 两个客户端通过独立PYTHONPATH目录运行，不将互相冲突的依赖注入Qwen模型服务。Qwen服务仍为既有固定BF16运行环境。
- 路径：`devbox/external_methods_20261014/support/upstream_clients_20261015`，保存两个安装日志、版本manifest与实际导入路径。新run_batch逐方法保存`client_environment.json`。

新环境完整重跑RSI65题和VAM3题，旧环境的成功题也不复用。原记录与分数保留为历史，不覆盖。新环境完整GPU矩阵尚待执行，不把安装/导入检查写成全部实验通过。

## 必要适配与无法认证的部分

- 多视频拼接、两位小数起止时间说明、原视频时间坐标映射、视觉评测不提供音频，均属于既定输入协议；原方法本来是单视频输入。
- 每题独立记忆库与空会话，避免题间数据污染；原TUI可长期保留跨问答记忆。局部临时文件放在记忆库同一文件系统，避免原子移动跨设备失败。
- 本地模型端点、OCR/Python路径和实际模型身份不同；Modal缺少Landlock，保留seccomp与外层Sandbox，无法声称与原文件系统隔离完全相同。
- Embedding权重仍是原Qwen3-VL-Embedding-8B，但由本地官方实现服务，BF16/sdpa、默认instruction、8192上下文、448²像素。云端如何解释input_type、内部图像/视频处理和数值实现不可见，不能证明向量逐位等同。
- VAM的448²限制作用于图像上传与Embedding图像；原video_url上下文仍走10MB视频路径，不能声称视频帧处理后的尺寸一律为448。
- 本地Qwen使用seed0、thinking关闭、默认top_p1、131072上下文、单请求最多512张image/8个video；原云服务没有公开相同数值环境。13:28已观测RSI单请求最多32张image，VAM最多4张image/1个video，未达到本地媒体数量上限；不能外推任意输入。
- VAM没有锁死全部依赖版本，满足声明范围不等于复原作者机器上的每一个二进制版本。云端模型更换本身也不可能保证相同答案。

源码配置：`eval/external_methods/upstream_settings.json`；远端审计：`devbox/external_upstream_20261015/settings_audit_20261015.json`。没有改写运行中的冻结源码。
