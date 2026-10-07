# E2E 测试代码与官方评测的一致性审计（2026-10-07）

只读审计，未改代码。对象：本地 vLLM runner `scripts/run_official_cvbench_mvu.py`（CVBench、MVU-Eval）、CrossVid 官方任务脚本 `eval/e2e_eval/CrossVid/eval/*.py` 及编排脚本 `scripts/official_crossvid/`、API runner `eval/e2e_eval/api/run.py`，以及 `outputs/e2e/qwen3_5_35b_a3b/` 的历史结果。
约束要求（用户指定）：每题最多 512 帧，图像最长边不超过 720 像素。

## 1. 三个 benchmark 的官方原始设置

| 项 | CVBench（lmms-eval `mvr` 任务；论文 arXiv 2508.19542） | MVU-Eval（NJU-LINK/MVU-Eval；arXiv 2511.07250） | CrossVid（chuntianli666/CrossVid；arXiv 2511.12263） |
|---|---|---|---|
| 仓库副本与上游 | 14 个关键文件逐字节一致（上游 f8dc8f7） | `main.py`、`analyze.py` 逐字节一致（上游 a5937ad） | prompt、抽帧、评分逻辑一致；另有两处与评测无关的补丁（进程池 `maxtasksperchild`、预处理缓存），README 未说明 |
| 帧数 | 开源模型每视频 8 帧（四视频共 32 帧）；论文消融 8/16/32 | 每视频 32 帧，无每题上限（13 个视频时 416 帧） | 脚本默认每题 128 帧（`--frames` 可改）；论文按模型取最大可接受帧数，Qwen2.5-VL 为 256 |
| 帧的分配 | 每视频固定帧数 | 每视频固定帧数 | BU/NC/CC/PEA 按视频数均分；FSA、CCQA、MSR/MOC 每个视频或视角各一半；PI/PSS 按区间时长比例 |
| 采样 | 固定帧数均匀采样（`linspace(...).round()`），不按 fps | 固定帧数均匀采样（`linspace`，取整为 int） | `linspace` 均匀采样后去重；区间按时间均匀取点 |
| 分辨率 | 强制缩放到 448×448（不保持宽高比） | 最长边 720，等比缩小 | 默认最长边 360（`--length` 可改），等比缩小 |
| 输入形式 | 每个视频一个 video 元素，前后各一张提示图（`res/videoN.png`、`endN.png`） | 逐帧 JPEG（quality 75），多个 `image_url` | 逐帧 JPEG，文字与图片交替，帧放在题目和选项之后 |
| prompt | system “You are a helpful assistant.”；选择题结尾 “Answer with the option's letter (A, B, C, or D) from the given choices directly.”；是非题为 “…word (YES or NO)…” | 每个视频前加 `[Video k] 文件名`；问题后接 “Please select the correct answer from the options. Answer with the option’s letter directly.”（撇号为 U+2019），再接选项；无 system | system “You are a helpful video analyzer.”；各 task 模板见 `eval/*.py`；帧标签为 `Video k:`、`Beginning/Ending:`、`Segment k:`、`View A/B:`、`Video A/B:` |
| 生成参数 | yaml：max_new_tokens 16、temperature 0、top_p 1（qwen 适配器硬编码 128） | 未设置，用服务端默认 | temperature 0、top_p 0.95、max_tokens 8192，每题最多重试 3 次 |
| 解析与评分 | 去掉前缀后取首个 `[ABCD]` 或 YES/NO；分母为全部 1000 题 | 首字符与答案比较；调用失败的题不计入分母 | 原始输出与答案严格相等，不做抽取；FSA 为 IoU 均值；CCQA 由 Judge 打分（论文用 GPT-4.1） |
| MSR/MOC 的目标标注 | — | — | 不在帧上画框，在文字中给出各目标出现的帧序号和框坐标 |

## 2. 本地实现与官方的差异

### CVBench
| 差异 | 严重程度 | 说明 |
|---|---|---|
| **vLLM 截断视频帧** | **严重** | vLLM 0.19 起，`data:video/jpeg` 序列默认只保留前 32 帧（`num_frames` 默认 32），且不再重新均匀采样。历史 prompt token 数完全符合“每视频 32 帧”的模型（997 题拟合残差标准差 9.4 token）。模型只看到每个视频开头的 12.5–25%，“Video X End” 提示图被放在截断处之后。历史 63.49% 不能算“512 帧”的结果 |
| 帧数 | 按设计不同 | 本地每视频取 512//N 帧（256/170/128），官方 8 帧 |
| 分辨率 | 按设计不同 | 本地保持宽高比、最长边 ≤720，官方 448×448。修复截断后，Qwen3.5 视频处理器的像素预算会把 256 帧的视频缩到约 416×224，720 上限实际不起作用 |
| 提示图超过 720 | 中 | `res/*.png` 约 1192 像素，原样发送；官方也如此，对分数影响小，但不满足 720 约束 |
| 时间戳 | 低 | jpeg 序列 fps 默认按 1 处理，Qwen3.5 会插入按帧序号算出的假时间戳 |
| 分母 | 低 | 本地剔除了 3 道媒体失败题（id 64–66），报告 633/997=63.49%；官方口径为 633/1000=63.30% |
| 默认参数与历史运行不一致 | 低 | runner 默认 `--cv-max-side 448`、每视频 8 帧；历史运行靠启动脚本传参。thinking 关闭靠服务端默认，未在请求中显式设置 |
| 其他 | 可忽略 | 是非题判定有 6 题与 lmms-eval 不同；JPEG q95 重编码；插值方式；索引取整 |

### MVU-Eval
| 差异 | 严重程度 | 说明 |
|---|---|---|
| **帧数** | 主要偏差 | 历史运行传了 `--mvu-frames-per-video 512`，实际每视频 512//n 帧，平均每题 421 帧，是官方 32 帧/视频（平均 149 帧）的 3 倍。历史 51.26 是“512 帧预算”变体的分数 |
| 指令句被改写 | 中 | 本地为 “Select the correct answer from the options. Return exactly one uppercase option letter and no explanation.”，官方原句见上表 |
| 生成参数 | 低 | 本地 temperature 0、top_p 1、max_tokens 64、thinking 关闭；官方未设置 |
| summary 的 `accuracy` 字段 | 低 | 主键用的是本地解析，官方首字符口径在 `legacy_first_character_accuracy`；历史 1824 题两者逐题一致 |
| API runner 的 Qwen 传输 | 中（仅 API） | 超过 250 张图时打包成 video 帧列表上传，文档中“identical image_url parts”的说法不成立 |
| 分辨率取整 | 可忽略 | 6 个视频引用为 719 而非 720 像素 |
| 约束 | 满足 | 历史 1824 题每题最多 512 帧，最长边最大 720 |

### CrossVid
| 差异 | 严重程度 | 说明 |
|---|---|---|
| **MSR/MOC 解析口径** | 主要偏差 | 历史报告对 MSR/MOC 用“抽取最终选项”，其余 task 严格比较；官方全部严格比较。官方口径的 35B 总分为 31.07，不是报告中的 34.60 |
| 分辨率 | 无法确认 | 记录写 720，但启动脚本 `scripts/launch_full_end_to_end_512.sh` 中 CrossVid 为 360，35B 的运行参数文件未保留 |
| 帧数与分辨率参数 | 与官方逻辑一致 | 通过官方参数 `--frames 512 --length 720` 实现，不能与论文榜单（360 像素、各模型自己的帧数）直接比较；分辨率还会改变 MSR/MOC 文字中的框坐标 |
| CCQA Judge | 模型不同 | 历史用 DeepSeek-v4-flash，论文用 GPT-4.1；35B 当时的评分脚本不在仓库中，prompt 是否逐字一致无法确认；`scripts/official_crossvid/score_ccqa_m3.py` 的评分点格式和 top_p 与官方不同 |
| 约束 | 满足 | `--frames 512 --length 720` 下各 task 每题最多 512 帧（整除或最大余数法分配），最长边严格 ≤720 |

## 3. 按“最多 512 帧、最长边 ≤720”重跑前必须修改的内容

1. **CVBench**：
   - 请求中加入 `media_io_kwargs={"video": {"num_frames": -1}}`，或在服务端设置，关闭 vLLM 的 32 帧截断；
   - 对每题的 prompt token 数做断言，确认帧没有被丢；
   - 传入真实的采样 fps，避免假时间戳；
   - 提示图缩到 ≤720；
   - `--cv-max-side 720` 和帧数显式传参；
   - 请求中显式关闭 thinking；
   - 按 1000 题报告，或者修好 3 道失败题后补跑。
2. **MVU-Eval**：
   - 恢复官方指令句原文；
   - 明确帧数策略：官方 32 帧/视频，或每题 512 帧预算（512//n 帧/视频）；
   - summary 主键改为官方首字符口径。
3. **CrossVid**：
   - 用 `scripts/official_crossvid/` 的编排脚本，在 8 个端点上各跑一条 lane，传 `--frames 512 --length 720 --threads 1`，按 `eval/crossvid_2500.json` 过滤 QA 后均分；
   - vLLM 服务端：`limit-mm-per-prompt` 中 image ≥512、`max_model_len` 足够（约 15 万 token）、默认关闭 thinking；
   - 主表报告官方严格口径，宽松口径只作补充并对全部选择题统一处理；
   - CCQA 使用固定的 DeepSeek Judge，核对 prompt 与官方一致；Judge 失败时报错或补跑，不能静默丢弃。
4. **所有 benchmark**：每题的实际帧数、每帧分辨率、token 数都写入记录，并在汇总时检查约束。

## 4. 目前不能声称的

- 历史 Qwen3.5 E2E 在 CVBench 上看到了 512 帧（实际每视频 32 帧）。
- 历史 MVU-Eval 51.26 是官方 32 帧协议下的分数。
- 历史 CrossVid 34.60 是官方分数（官方严格口径为 31.07），以及它用了 720 像素。
- 所有输入图像最长边都 ≤720（CVBench 提示图不满足）。
