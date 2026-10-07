# E2E 测试与官方评测的一致性审计（2026-10-07）

本文分两部分：旧 E2E 结果存在的问题（用于解读历史数字），以及统一框架 `run.py` 的修复与验证证据。
统一协议、命令和输出格式见 [`README.md`](README.md)。

## 1. 三个 benchmark 的官方原始设置

| 项 | CVBench（lmms-eval `mvr`；arXiv 2508.19542） | MVU-Eval（arXiv 2511.07250） | CrossVid（arXiv 2511.12263） |
|---|---|---|---|
| 帧数 | 每视频 8 帧（论文消融 8/16/32） | 每视频 32 帧 | `--frames` 默认每题 128；论文按模型取最大可接受帧数 |
| 分辨率 | 拉伸为 448×448 | 最长边 720，等比 | `--length` 默认 360，等比 |
| 输入形式 | 每视频一个 video 元素（`qwen_vl_utils` 解码为张量并带真实采样帧率），前后各一张提示图 | 逐帧 JPEG（质量 75）`image_url`，每视频前加 `[Video k] 文件名` | 逐帧 JPEG，与 `Video k:` 等文字交替 |
| 生成参数 | temperature 0、top_p 1；adapter 硬编码 max_new_tokens 128 | 未设置（服务端默认） | max_tokens 8192、temperature 0、top_p 0.95，每题最多 3 次尝试 |
| 评分 | 正则抽取首个 A–D/YES/NO；分母 1000 | 首字符；调用失败的题不计入分母 | 严格相等；FSA 为 IoU；CCQA 由 Judge 打分（论文用 GPT-4.1） |

## 2. 旧结果的问题（`outputs/e2e/` 下的历史 E2E）

| Benchmark | 问题 | 影响 |
|---|---|---|
| CVBench | vLLM 0.19 对 `data:video/jpeg` 帧序列默认只保留前 32 帧（`num_frames` 默认 32），且不重新采样 | 模型只看到每个视频开头的 12.5–25%，“Video X End”提示图落在截断处之后；历史 63.49% 不是“512 帧”的结果 |
| CVBench | 帧序列按 1 fps 标注时间 | Qwen3.5 看到的时间标签是帧序号，不是秒数 |
| CVBench | 剔除了 3 道媒体失败题 | 官方口径为 633/1000=63.30%，不是 633/997=63.49% |
| MVU-Eval | 每题 512 帧预算（平均 421 帧，官方 32 帧/视频平均 149 帧）；指令句被改写 | 历史 51.26 是变体协议下的分数 |
| CrossVid | MSR/MOC 用“抽取最终选项”，其余 task 严格比较 | 官方严格口径的 35B 总分为 31.07，不是 34.60 |
| CrossVid | 分辨率参数未留存（记录写 720，启动脚本为 360） | 无法确认历史运行的分辨率 |

## 3. 统一框架的修复

| 问题 | 修复 | 验证（Qwen3.5-9B，H200，2026-10-07） |
|---|---|---|
| prompt、顺序、评分与官方不一致的风险 | MVU-Eval 直接调用 `build_messages_base`；CrossVid 直接调用各 task 的 `evaluate()`；CVBench 的 `mvr_doc_to_text`、`extract_characters_regex`、系统消息、yaml 生成参数按 AST 从官方文件读取；CrossVid 生成参数从官方 `chat()` 读取并校验十个脚本一致 | 本机核对 AST 读取结果与官方文件一致；图片输入版冒烟（每个 benchmark/task 3 题，共 36 题）两轮全部成功且逐题一致 |
| CVBench 帧截断与假时间戳 | 改为逐帧图片输入（与 MVU-Eval、CrossVid 一致），不再经过 vLLM 的视频加载路径 | 曾验证 vLLM 视频路径：JPEG 帧序列不加 `num_frames=-1` 时只保留 32 帧，时间标签为帧序号（0.5/2.5/4.5/6.5）。图片输入没有这两个问题，但模型也看不到时间 |
| MVU-Eval 文件名泄露答案；E2E 与 MVAgent 得到的信息不一致 | 三个 benchmark 统一用 `Video k:` 标签分隔视频：MVU-Eval 不再显示 `[Video k] 文件名`，CVBench 去掉提示图及解释它的那句话 | MVU-Eval TR 的 68 题仅凭文件名中的片段序号排序即 100% 命中答案；MVAgent 的视频 ID 只是 `video_1`… |
| 失败题被丢弃或静默改分母 | 失败记为 error，重跑同一命令补跑；全部成功才给总分；CCQA Judge 失败报错 | 冒烟中 CCQA 未配置 Judge 凭据时，score 明确报告“未评分”，CrossVid 总分为空 |
| 帧数、分辨率无法事后核实 | 每题记录实际帧数、每帧尺寸、prompt token、finish_reason；summary 汇总最大值 | 冒烟（默认 `F`=512、`S`=448）：三个 benchmark 每次调用最多 `F` 帧、最长边 `S` |
| 运行参数遗失 | manifest 记录协议、模型权重、题目集合哈希、源码与官方文件哈希；`source/` 冻结代码，续跑时必须一致 | 见冒烟输出 `manifest.json` |

## 4. 目前不能声称的

- 与论文榜单可直接比较：帧数和分辨率按统一协议改变，CCQA Judge 也不同于论文的 GPT-4.1。
- 模型看到的每帧最长边恰好是 `S`：Qwen3.5 处理器会把图片尺寸取整到 32 的倍数（例如 448×252 → 448×256）。
- CVBench 与官方输入形式相同：官方为 video 元素（带真实时间），这里是逐帧图片（无时间信息）。
- CVBench、MVU-Eval 的视频分隔方式与官方相同：两者都改用 CrossVid 的 `Video k:` 文字标签。
- MVU-Eval 的生成设置与官方完全相同：官方不传生成参数，本框架固定为贪心解码、max_tokens 1024。
