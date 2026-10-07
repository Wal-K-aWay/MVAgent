# 端到端（E2E）测试

`run.py` 是 CVBench、MVU-Eval、CrossVid 三个 benchmark 的统一 E2E 入口：同一套命令行、同一个 vLLM 服务、
同一种输出格式。prompt、输入顺序、抽帧方式、生成参数和评分都直接取自（或直接调用）本目录下的官方源码；
协议参数只有两个：**每次模型调用最多 512 帧，每帧最长边不超过 448 像素**。

```
eval/e2e_eval/
  run.py                  统一入口：infer（推理，原始记录先落盘）/ score（官方评分 + 汇总）
  harness/
    common.py             路径、IO；从官方源码中按 AST 读取函数、常量和调用参数，按源码隔离加载官方脚本
    backends.py           VLLMBackend（多副本端点池，默认）/ APIBackend（api/ 下的闭源模型）
    media.py              CVBench 抽帧、共享预处理缓存、逐请求图像尺寸核查
    cvbench.py            lmms-eval mvr 任务 + Qwen2.5-VL adapter
    mvu_eval.py           调用官方 inference/main.py 的 build_messages_base
    crossvid.py           调用官方 eval/<TASK>.py 的 evaluate()
    ccqa.py               CCQA Judge（官方 score_CCQA.py 的 prompt 与汇总公式）
  api/                    闭源模型的 provider 配置（APIBackend 使用）
  CVBench/ MVU-Eval/ CrossVid/   官方源码快照（见文末，不修改）
```

## 统一协议与官方对齐

| | CVBench | MVU-Eval | CrossVid |
|---|---|---|---|
| 执行的官方代码 | `mvr_doc_to_text`、`extract_characters_regex`、adapter 的系统消息和提示句（AST 读取） | `build_messages_base`（含 `encode_video`）直接调用 | 十个 `eval/<TASK>.py` 的 `evaluate()` 直接调用 |
| 输入形式 | 每个视频的帧作为有序 JPEG 图片（质量 95），夹在该视频的起始、结束提示图之间（官方为 video 元素） | 逐帧 JPEG（质量 75）`image_url`（官方） | 逐帧 JPEG，图文交替（官方） |
| 帧数 | 每视频 `512 // 视频数`（官方 8） | 每视频 `512 // 视频数`（官方 32） | `--frames 512`，按各 task 官方规则分配（官方默认 128） |
| 分辨率 | 等比缩放，最长边 448（官方拉伸为 448×448） | `max_pixels=448`（官方 720） | `--length 448`（官方默认 360） |
| 缩放与编码 | decord 按目标尺寸解码后编码 | 官方 `encode_video` | 官方 `cv2.resize(INTER_AREA)` 后 `cv2.imencode` |
| 采样下标 | `linspace(0, n-1, k).round()`（同 `qwen_vl_utils`） | 官方 | 官方 |
| 顺序与 prompt | system → [起始提示图, 该视频的帧, 结束提示图]×N → 提示句 → 题目（同 adapter） | 官方 | 官方 |
| 生成参数 | temperature 0、top_p 1（yaml），max_tokens 128（adapter 硬编码） | **官方未设置**；本框架固定 temperature 0、top_p 1、max_tokens 1024 | 从官方 `chat()` 读取：max_tokens 8192、temperature 0、top_p 0.95 |
| thinking | 请求中显式关闭（与 MVAgent 相同） | 同左 | 同左 |
| 逐题评分 | `extract_characters_regex(out).strip().upper() == answer.strip().upper()` | `out.strip().upper()[:1] == ground_truth` | 严格相等（BU 与拼接后的答案比较）；FSA 用官方 `interval_iou`，解析失败记 0；CCQA 由 Judge 评分 |
| 汇总 | 按题平均，分 15 个 `task_type` | 按题平均，分 task | 十类 task 等权平均（O.Avg）；CCQA 为总得分 / 总满分 |

### 帧数分配

- CVBench、MVU-Eval：每个视频平均分得 `512 // 视频数` 帧（视频本身不足时取全部帧），在整段视频上均匀抽取；
  除不尽的余数不用（例如 3 个视频共 510 帧）。
- CrossVid：沿用各 task 的官方规则，每题合计不超过 512 帧。BU/NC/CC/PEA 按视频数平均分；FSA/CCQA/MOC/MSR
  两个视频（视角）各一半；PI（给出电影的开头、结尾两段，推断中间情节）和 PSS（把一个烹饪视频的 3–5 段操作排序）
  的"片段"是同一个视频里的不同时间段，官方按片段时长成比例分配，等价于在所选片段上用同一帧率均匀抽帧，
  保留了片段的相对时长。PSS 片段时长差异很大（最长/最短中位数 4.6 倍，p90 13 倍），平均分会让短片段重复采样、
  长片段过稀；512 帧下按比例分配时最短片段仍有中位数 42 帧（PI 为 176 帧），因此保留官方做法。

### 可复现性

- 所有 benchmark 都是贪心解码（temperature 0），`run.py` 启动时校验，否则拒绝运行。贪心解码下 vLLM 会把
  top_p/top_k 重置为不生效，所以 CrossVid 官方的 top_p 0.95 与 1.0 等价，保留官方取值。
- thinking 在请求中显式关闭；服务端用 `--generation-config vllm`，不引入模型自带的采样默认值。
- 每个 vLLM 副本同时只处理一个请求（不可配置），各次运行的 batch 组成相同。在 H200 上实测：同一批 24 题重跑，
  模型输出与 prompt token 数逐题完全一致。
- 原始记录先落盘再评分；CCQA Judge 的响应按内容缓存，重新评分不会再次调用 Judge。

### 有意的偏差与说明

- **帧数与分辨率**：统一为 512 帧、448 像素，这是本协议主动改动的参数。CVBench 官方拉伸为 448×448，这里保持宽高比。
- **CVBench 的帧输入**：官方 adapter 把视频文件交给 `qwen_vl_utils` 作为 video 元素（Qwen2.5-VL 用真实采样时刻做位置编码）。
  本框架与另两个 benchmark 统一为逐帧图片：Qwen3.5 不给图片加时间标签，模型只能从图片顺序判断先后。
  （若用 vLLM 的 JPEG 帧序列视频输入，vLLM 0.19 默认只保留前 32 帧、并按帧序号标注时间，见审计文档。）
- **模型自身的预处理**：Qwen3.5 处理器会把每张图的尺寸取整到 32 的倍数；每题实际的 prompt token 数记录在原始记录中。
- **CVBench 提示图**：`res/videoN.png`、`endN.png` 按官方原图发送（约 1192 像素宽）。它们不是视频帧，不受 448 限制。
- **MVU-Eval 生成参数**：官方不传任何生成参数，取服务端默认（可能是随机采样）。本框架用贪心解码保证可复现；
  1024 的 token 上限只用来截断失控输出，不影响首字符评分。
- **失败处理**：官方 MVU-Eval 和 CrossVid 会静默丢弃失败的题。这里失败会记录为 error，重跑同一命令时会补跑；
  只有全部题目成功才给出总分。CCQA 的 Judge 失败同样报错，不记为 0 分。
- **CCQA Judge**：论文使用 GPT-4.1。本框架与 MVAgent 共用同一个固定 Judge（`deepseek-v4-flash`，代码在
  `eval/agent_eval/score_crossvid_ccqa.py`），prompt 和汇总公式与 `score_CCQA.py` 逐字一致（运行时校验）。

## 运行

vLLM 服务与 MVAgent 使用同一份配置（`configs/inference/modal_qwen35_*_no_skill.yaml` 及其 execution 配置，
在 devbox 上由 `prelaunch.py` 启动）。vLLM 0.19 未指定时每种模态默认允许 999 个输入，512 张图不需要额外参数。

```bash
# 推理：可断点续跑；同一 --output 下协议、模型、题目集合或源码变化会拒绝续写
python eval/e2e_eval/run.py infer --output OUT \
  --endpoints 8100-8107 \
  --benchmarks cvbench,mvu_eval,crossvid \
  --ids crossvid=eval/crossvid_2500.json \
  --media-cache-dir /work/e2e_media

# 评分与汇总（CCQA 需要 DEEPSEEK_API_KEY）
python eval/e2e_eval/run.py score --output OUT
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--benchmarks` | `cvbench,mvu_eval,crossvid` 的任意子集 |
| `--crossvid-tasks` | CrossVid task 子集，默认全部十类 |
| `--ids BENCH=PATH` | 只测 JSON 列表中的题目（ID 格式与 MVAgent 相同：`cvbench:<id>`、`mvu_eval:<task>:<id>`、`crossvid:<TASK>:<id>`） |
| `--limit N` | 冒烟测试：每个 benchmark 前 N 题（CrossVid 为每个 task 前 N 题） |
| `--frames` / `--max-side` | 协议参数，默认 512 / 448；改动后应使用新的 `--output` |
| `--endpoints` | vLLM 端点：URL、端口或端口范围（`8100-8107`）；`--model` 默认取端点唯一的模型 |
| `--workers` | 并发准备的题数，默认为请求槽数的 2 倍，让解码与推理重叠 |
| `--api-model` | 用 `api/` 中的闭源模型代替 vLLM（例如 `glm-5.3-flash`），凭据只从环境变量读取 |
| `--media-cache-dir` | 与模型无关的预处理缓存，换模型时可复用；传空字符串关闭 |

## 输出

```
OUT/
  manifest.json        identity（协议、模型与权重、各 benchmark 的官方设置、题目集合哈希、源码与官方文件哈希）
                       + runs（每次运行的端点、并发、git 版本、开始/结束时间与结果计数）
  source/              首次运行时冻结的 run.py 与 harness/；续跑时必须一致
  selection.json       每个 benchmark 选中的 sample_id
  raw/<bench>.jsonl    每题一行，追加写入：status、output（模型原文）、error、media（帧数、尺寸）、
                       request（端点、usage、finish_reason、生成参数）、seconds
  scored/<bench>.json  逐题官方评分：prediction、answer、score（CCQA 另有 coverage/correctness/points）
  summary.json         各 benchmark 总分（CVBench/MVU-Eval 为 accuracy，CrossVid 为 o_avg）、分 task 分数、
                       完成度，以及核查项（每次调用最大帧数、最大边长、prompt token、finish_reason）
  judge_cache/         CCQA Judge 响应缓存
```

逐题记录与 MVAgent 的 sample_id 相同，可以直接按题对比。

## 官方源码快照

这些文件是官方仓库的精简快照，直接纳入 MVAgent 的 git，不修改其中的评测逻辑
（CrossVid 只多了一个可选的预处理缓存 `utils/preprocess_cache.py` 和进程池的 `maxtasksperchild`，
二者不影响抽帧、prompt 或评分）。数据集在 Modal volume `/assets` 下（布局见 `mvagent-environment` skill）。

| Benchmark | 官方仓库 | 导入的 commit | 保留范围 |
|---|---|---|---|
| CVBench | `https://github.com/Hokhim2/CVBench` | `f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed` | CVBench/MVR 题目与 prompt、Video-R1 评测入口、lmms-eval 运行时、MVR task、Qwen2.5-VL/OpenAI 兼容 adapter、提示图 |
| MVU-Eval | `https://github.com/NJU-LINK/MVU-Eval` | `a5937adea78e9649af53cd9a4e30a91ed7fd3df2` | `inference/`、README、license |
| CrossVid | `https://github.com/chuntianli666/CrossVid` | `b53ada63551f9ac4a726b381b627d17ece066281` | `eval/`、README、license |

发表结果时同时报告 MVAgent 的 commit 和上面三个上游 commit。闭源 API 的价格估算见 [`API_COSTS.md`](API_COSTS.md)，
provider 细节见 [`api/README.md`](api/README.md)。
