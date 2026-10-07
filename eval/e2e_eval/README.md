# 端到端（E2E）测试

`run.py` 是 CVBench、MVU-Eval、CrossVid 三个 benchmark 的统一 E2E 入口：同一套命令行、同一个 vLLM 服务、
同一种输出格式。prompt、输入顺序、抽帧方式、生成参数和评分都直接取自（或直接调用）本目录下的官方源码；
协议参数只有两个：**每次模型调用最多 `F` 帧（`--frames`，默认 512），每帧最长边不超过 `S` 像素（`--max-side`，默认 448）**。
下文用 `F`、`S` 指代这两个参数。输入格式在三个 benchmark 间统一：帧都以有序 JPEG 图片输入，每个视频的帧前放一个
`Video k:` 文字标签（CrossVid 官方写法），模型看不到视频文件名。

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
| 执行的官方代码 | `mvr_doc_to_text`、`extract_characters_regex`、adapter 的系统消息（AST 读取） | `build_messages_base`（含 `encode_video`）直接调用 | 十个 `eval/<TASK>.py` 的 `evaluate()` 直接调用 |
| 输入形式 | `Video k:` + 该视频的帧（JPEG，质量 95）（官方为提示图包围的 video 元素） | `Video k:` + 该视频的帧（JPEG，质量 75）（官方标签为 `[Video k] 文件名`） | `Video k:` 等标签与帧交替（官方） |
| 帧数 | 每视频 `F // 视频数`（官方 8） | 每视频 `F // 视频数`（官方 32） | 官方 `--frames` 设为 `F`，按各 task 官方规则分配（官方默认 128） |
| 分辨率 | 等比缩放，最长边 `S`（官方拉伸为 448×448） | `max_pixels=S`（官方 720） | 官方 `--length` 设为 `S`（官方默认 360） |
| 缩放与编码 | decord 按目标尺寸解码后编码 | 官方 `encode_video` | 官方 `cv2.resize(INTER_AREA)` 后 `cv2.imencode` |
| 采样下标 | `linspace(0, n-1, k).round()`（同 `qwen_vl_utils`） | 官方 | 官方 |
| 顺序与 prompt | system → [`Video k:`, 该视频的帧]×N → 题目（官方 prompt；去掉了解释提示图的那句话） | [`Video k:`, 该视频的帧]×N → 题目 → 指令 → 选项（官方顺序与原文） | 官方 |
| 生成参数 | temperature 0、top_p 1（yaml），max_tokens 128（adapter 硬编码） | **官方未设置**；本框架固定 temperature 0、top_p 1、max_tokens 8192（与 CrossVid 相同） | 从官方 `chat()` 读取：max_tokens 8192、temperature 0、top_p 0.95 |
| thinking | 请求中显式关闭（与 MVAgent 相同） | 同左 | 同左 |
| 逐题评分 | `extract_characters_regex(out).strip().upper() == answer.strip().upper()` | `out.strip().upper()[:1] == ground_truth` | 严格相等（BU 与拼接后的答案比较）；FSA 用官方 `interval_iou`，解析失败记 0；CCQA 由 Judge 评分 |
| 汇总 | 按题平均，分 15 个 `task_type` | 按题平均，分 task | 十类 task 等权平均（O.Avg）；CCQA 为总得分 / 总满分 |

### 帧数分配

- CVBench、MVU-Eval：每个视频平均分得 `F // 视频数` 帧（视频本身不足时取全部帧），在整段视频上均匀抽取；
  除不尽的余数不用（例如 `F`=512、3 个视频时共 510 帧）。
- CrossVid：沿用各 task 的官方规则，每题合计不超过 `F` 帧。BU/NC/CC/PEA 按视频数平均分；FSA/CCQA/MOC/MSR
  两个视频（视角）各一半；PI（给出电影的开头、结尾两段，推断中间情节）和 PSS（把一个烹饪视频的 3–5 段操作排序）
  的"片段"是同一个视频里的不同时间段，官方按片段时长成比例分配，等价于在所选片段上用同一帧率均匀抽帧，
  保留了片段的相对时长。PSS 片段时长差异很大（最长/最短中位数 4.6 倍，p90 13 倍），平均分会让短片段重复采样、
  长片段过稀；`F`=512 时按比例分配，最短片段仍有中位数 42 帧（PI 为 176 帧），因此保留官方做法。
- 官方代码在 `F` 较大时的边界情况（`scripts/audit_e2e_frame_budget.py` 对全部数据的核查，`F`=512）：
  FSA/CCQA 为每个视频写死 `F/2` 个帧占位符，视频不足 `F/2` 帧时官方 `evaluate()` 会失败——实际没有这样的视频；
  MOC/MSR 从帧目录取 `F/2` 帧时不截断，目录不足 `F/2` 张就重复取帧——66 题（Lite2500 中 22 题）受影响，
  目录最少 151 张；BU 有 194 题含短于其额度（`F // 视频数`）的视频，实际帧数少于额度（占位符按实际帧数生成，不影响运行）。
  这些都按官方逻辑保留。

### 官方分与格式稳健分

每题同时给出两个分数，汇总口径相同：

- **官方分**（`score`）：完全按各 benchmark 官方评分规则。
- **格式稳健分**（`robust_score`）：输出符合要求的格式时等于官方分；否则按 `harness/answers.py` 的固定规则读出模型
  明确给出的最终答案（整段就是答案、`the answer is X`、单独一行的答案、`A, B, and D`、`2->4->1->3`、`42,50` 等，
  多处时取最后一次），再用官方的比较方式评分；读不出就算错，不做猜测。规则与被测系统无关，MVAgent 之后用同一套。
- **格式合格率**（`format_ok_rate`）：输出本身符合要求格式的比例。

在旧服务器三个模型的全量输出上验证：格式合格的部分两种分数一致；偏离格式的输出几乎都能读出答案（读不出的是空输出、
被截断或选项外的字母）。被格式拖低最明显的是 35B 的 CrossVid MOC（官方 13.1 → 稳健 36.0）、MSR（13.8 → 26.4）、
PEA（28.8 → 41.8）和 27B 的 FSA（1.6 → 7.9）、PSS（3.6 → 6.8）。MVU-Eval 的稳健分略低于官方分，因为首字符规则会把
`Based on ...` 误读成 B 而碰巧答对，稳健分不计这类巧合。

### 可复现性

- 所有 benchmark 都是贪心解码（temperature 0），`run.py` 启动时校验，否则拒绝运行。贪心解码下 vLLM 会把
  top_p/top_k 重置为不生效，所以 CrossVid 官方的 top_p 0.95 与 1.0 等价，保留官方取值。
- thinking 在请求中显式关闭；服务端用 `--generation-config vllm`，不引入模型自带的采样默认值。
- 每个 vLLM 副本同时只处理一个请求（不可配置），各次运行的 batch 组成相同。在 H200 上实测：同一批 36 题重跑，
  模型输出与 prompt token 数逐题完全一致。
- 原始记录先落盘再评分；CCQA Judge 的响应按内容缓存，重新评分不会再次调用 Judge。

### 有意的偏差与说明

- **帧数与分辨率**：统一为 `F` 帧、`S` 像素，这是本协议主动改动的参数。CVBench 官方拉伸为 448×448，这里保持宽高比。
- **CVBench 的帧输入**：官方 adapter 把视频文件交给 `qwen_vl_utils` 作为 video 元素（Qwen2.5-VL 用真实采样时刻做位置编码），
  每个视频前后各插一张提示图（"The video k" / "Video k End"），并加一句话解释这些提示图。本框架与另两个 benchmark
  统一为 `Video k:` 标签加逐帧图片，提示图和那句解释一并去掉，题目 prompt 本身不变。Qwen3.5 不给图片加时间标签，
  模型只能从图片顺序判断先后。去掉提示图每题平均少约 7.6k prompt token（约 12%）。
  （若用 vLLM 的 JPEG 帧序列视频输入，vLLM 0.19 默认只保留前 32 帧、并按帧序号标注时间，见审计文档。）
- **模型自身的预处理**：Qwen3.5 处理器会把每张图的尺寸取整到 32 的倍数；每题实际的 prompt token 数记录在原始记录中。
- **MVU-Eval 去掉文件名**：官方在每个视频前写 `[Video k] 文件名`，这里改为 `Video k:`。TR（时间排序）中有 68 题的
  文件名形如 `xHr8X2Wpmno_2_cnt6.mp4`，按其中的片段序号排序就 100% 得到答案；Comparison 中的 nuScenes 题用文件名
  （`CAM_FRONT_LEFT` 等）区分相机视角。MVAgent 只看到 `video_1`、`video_2` 这样的位置编号，看不到文件名，
  因此 E2E 也不给文件名，两者得到的信息一致。
- **MVU-Eval 生成参数**：官方不传任何生成参数，取服务端默认（可能是随机采样）。本框架用贪心解码保证可复现；
  8192 的 token 上限只用来截断失控输出，不影响首字符评分。
- **MVU-Eval 答题格式**：官方把答题指令放在选项之前，消息以选项列表结尾。`F`=512 时 Qwen3.5-9B 在 64 道抽样题中
  有 53 道先写分析而不直接作答（官方首字符评分 4/64，格式稳健分 26/64）。prompt 保持官方原样，由格式稳健分反映能力。
- **失败处理**：官方 MVU-Eval 和 CrossVid 会静默丢弃失败的题。这里失败会记录为 error，重跑同一命令时会补跑；
  只有全部题目成功才给出总分。CCQA 的 Judge 失败同样报错，不记为 0 分。
- **CCQA Judge**：论文使用 GPT-4.1。本框架与 MVAgent 共用同一个固定 Judge（`deepseek-v4-flash`，代码在
  `eval/agent_eval/score_crossvid_ccqa.py`），prompt 和汇总公式与 `score_CCQA.py` 逐字一致（运行时校验）。

## 运行

vLLM 服务与 MVAgent 使用同一份配置（`configs/inference/modal_qwen35_*_no_skill.yaml` 及其 execution 配置，
在 devbox 上由 `prelaunch.py` 启动）。vLLM 0.19 未指定时每种模态默认允许 999 张图；`F` 不超过 999 时不需要额外参数。

```bash
# 推理：可断点续跑；同一 --output 下协议、模型、题目集合或源码变化会拒绝续写
python eval/e2e_eval/run.py infer --output OUT \
  --endpoints 8100-8107 \
  --benchmarks cvbench,mvu_eval,crossvid \
  --ids crossvid=eval/crossvid_2500.json \
  --media-cache-dir /work/e2e_media

# 评分与汇总（CCQA 需要 DEEPSEEK_API_KEY）
python eval/e2e_eval/run.py score --output OUT

# 核对输入：按真实流程构造消息但不调用模型，按顺序打印文字原文与图片（连续同尺寸图片合并为一行）
python eval/e2e_eval/run.py preview cvbench:3 mvu_eval:Counting:0 crossvid:MOC:0
```

耗时参考（默认 `F`、`S`；Qwen3.5-9B，单张 H200，每副本一个请求；2026-10-07 冒烟实测）：每题模型调用
CVBench 约 8.3 s（2 个视频的题约 5.9 万 prompt token）、MVU-Eval 约 10.4 s（约 7.3 万）、CrossVid 约 8.3 s（约 6.1 万）。
解码与编码在 CPU 上与推理重叠进行，冷缓存时 CrossVid 每题约 7.5 s CPU 时间。

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
                       request（端点、usage、finish_reason、生成参数，服务端若返回 reasoning_content 也保存）、seconds
  scored/<bench>.json  逐题评分：prediction、answer、score（官方），format_ok、robust_prediction、robust_score
                       （格式稳健），CCQA 另有 coverage/correctness/points
  summary.json         各 benchmark 官方总分（CVBench/MVU-Eval 为 accuracy，CrossVid 为 o_avg）与格式稳健总分
                       （robust_accuracy / robust_o_avg）、格式合格率、分 task 分数、完成度，以及核查项（每次调用
                       最大帧数、最大边长、prompt token、finish_reason）；scoring_code_matches_inference 标明评分代码
                       是否与推理时冻结的代码一致
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
