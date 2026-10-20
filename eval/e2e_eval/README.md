# 端到端（E2E）测试

`run.py` 是 CVBench、MVU-Eval、CrossVid 三个 benchmark 的统一 E2E 入口：同一套命令行、同一个 vLLM 服务、
同一种输出格式。prompt、输入顺序、抽帧方式、生成参数和评分都直接取自（或直接调用）本目录下的官方源码；
协议参数只有两个：**每次模型调用最多 `F` 帧（`--frames`，默认 512），每帧最长边不超过 `S` 像素（`--max-side`，默认 448）**。
下文用 `F`、`S` 指代这两个参数。输入格式在三个 benchmark 间统一：帧都以有序 JPEG 图片输入，每个视频的帧前放一个
`Video k:` 文字标签（CrossVid 官方写法），模型看不到视频文件名。

```
eval/e2e_eval/
  run.py                  统一入口：infer（推理，原始记录先落盘）/ score（官方评分 + 汇总）
  serve.py                独立单卡同步服务池的启动与退出
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

历史验收、根因诊断与结果统一见 [实验记录](../../docs/experiments.md)。

共享同步推理后端位于 `src/models/vlm/local/sync_server.py`，正式 E2E 与 MVAgent
使用同一配置、版本锁、输入/token 审计。`serve.py` 和原 `infer/score/preview` CLI 保持不变。
启用媒体缓存时，正式 `infer` 自动在缓存中绑定逐题输入 SHA；后续模型/重复运行若输入变化会报错。
如果 `--media-cache-dir` 根目录已有独立审计的 `input_audit.json`，则逐题核对该清单，禁止加入未审计题目；
否则记录首次输入供后续复用（这不等于完成两次独立解码审计）。每次运行保存输入清单快照及 SHA。
三个模型应使用同一个固定媒体缓存；新协议/预处理代码应使用新缓存和新结果目录。

新评测使用下文的 `serve.py` 和 `run.py infer|score` 入口。
历史三模型后台矩阵控制器已移出当前代码树；既有任务沿用各自冻结源码和缓存，不改写或重复提交。
历史分片、结果及失败记录见[实验记录](../../docs/experiments.md)。

服务端请求时限1800秒，E2E默认HTTP等待1860秒。变更协议后使用新结果目录，保留旧冻结输入与源码。

## 统一协议与官方对齐

| | CVBench | MVU-Eval | CrossVid |
|---|---|---|---|
| 执行的官方代码 | `mvr_doc_to_text`、`extract_characters_regex`、adapter 的系统消息（AST 读取） | `build_messages_base`（含 `encode_video`）直接调用 | 十个 `eval/<TASK>.py` 的 `evaluate()` 直接调用 |
| 输入形式 | `Video k:` + 该视频的帧（JPEG，质量 95）（官方为提示图包围的 video 元素） | `Video k:` + 该视频的帧（JPEG，质量 75）（官方标签为 `[Video k] 文件名`） | `Video k:` 等标签与帧交替（官方） |
| 帧数 | 每视频 `F // 视频数`（官方 8） | 每视频 `F // 视频数`（官方 32） | 官方 `--frames` 设为 `F`，按各 task 官方规则分配（官方默认 128） |
| 分辨率 | 等比缩放，最长边 `S`（官方拉伸为 448×448） | `max_pixels=S`（官方 720） | 官方 `--length` 设为 `S`（官方默认 360） |
| 缩放与编码 | decord 按目标尺寸解码后编码 | 官方 `encode_video` | 官方 `cv2.resize(INTER_AREA)` 后 `cv2.imencode` |
| 采样下标 | `linspace(0, n-1, k).round()`（同 `qwen_vl_utils`） | 官方 | 官方 |
| 顺序与 prompt | system → [`Video k:`, 该视频的帧]×N → 题目（官方 prompt；去掉了解释提示图的那句话） | [`Video k:`, 该视频的帧]×N → 题目 → 官方原文答题指令→ 选项 | 官方 |
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
- 官方代码在 `F` 较大时的边界情况（历史全数据核查，`F`=512；原审计脚本见整理前提交）：
  FSA/CCQA 为每个视频写死 `F/2` 个帧占位符，视频不足 `F/2` 帧时官方 `evaluate()` 会失败——实际没有这样的视频；
  MOC/MSR 从帧目录取 `F/2` 帧时不截断，目录不足 `F/2` 张就重复取帧——66 题（Lite2500 中 22 题）受影响，
  目录最少 151 张；BU 有 194 题含短于其额度（`F // 视频数`）的视频，实际帧数少于额度（占位符按实际帧数生成，不影响运行）。
  这些都按官方逻辑保留。
- 官方数据缺陷：CVBench 的 `125/RQorrnJIc2Q.mp4` 在官方 `CVBench.zip` 中就只有 26,214,400 字节（截断在 25 MiB，
  文件头写 4034 帧，只能解出前 2420 帧），decord 无法打开，用到它的 cvbench:64–66 三题在官方流程中同样无法评测。
  这三题记为推理失败，CVBench 的完成度为 997/1000。

### 官方分与格式稳健分

每题同时给出两个分数，汇总口径相同：

- **官方分**（`score`）：完全按各 benchmark 官方评分规则。
- **格式稳健分**（`robust_score`）：输出符合要求的格式时等于官方分；否则按 `harness/answers.py` 的固定规则读出模型
  明确给出的最终答案（整段就是答案、`the answer is X`、单独一行的答案、`A, B, and D`、`2->4->1->3`、`42,50` 等，
  多处时取最后一次），再用官方的比较方式评分；读不出就算错，不做猜测。规则与被测系统无关，MVAgent 之后用同一套。
- **格式合格率**（`format_ok_rate`）：输出本身符合要求格式的比例。

历史官方/稳健分比较见实验记录；两种指标须对双方使用相同提取规则。

### 可复现性

后续三模型评测使用 [固定评测方案](../../configs/inference/README.md#固定评测方案)：
8×H100、BF16、8个独立TP1/DP1副本、每卡并发1，共享固定配置后端（prefix cache关闭）；不再按日期选择新配置。
后续推理继续固定 `seed=0`，不按日期更换；新建抽样/打乱也默认0，已有split和面板保留原manifest及抽样seed。
沿用已验收固定配置时正常跑一遍评测即可，不每批重复双遍或全矩阵验收；保留服务身份、输入哈希和完整token记录。
只有权重、数值配置、版本、硬件型号、并发、媒体预处理或调用路径变化、新故障证据或用户明确要求，
才对受影响部分做小规模复核。增加题目或换日期不自动触发回归；已有有限测试不构成任意输入的绝对保证。

已通过范围复用既有验收；数量、反例与限制统一见实验记录。

- 所有 benchmark 使用 temperature 0，启动时校验；贪心模式下 top_p/top_k 不生效，保留各官方取值。
- thinking 显式关闭，采样参数由当前共享服务固定。每个 GPU 副本仅一个请求在途。
- 原始记录先落盘再评分；CCQA Judge 响应按内容缓存，重新评分复用已有记录。

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
- **MVU-Eval 生成参数**：官方不传任何生成参数，取服务端默认（可能是随机采样）。本框架用贪心解码控制采样随机性；
  8192 的 token 上限只用来截断失控输出，不影响首字符评分。
- **MVU-Eval 答题指令**：2026-10-12按用户要求恢复官方原文
  `Please select the correct answer from the options. Answer with the option’s letter directly.`，
  直接保留 `build_messages_base` 的返回文本及其在问题与选项之间的位置，不再替换措辞。
  temperature 0、top_p 1、max_tokens 8192及无文件名标签保持原设置。
  此前改写提示词的重复性/格式结果属于历史协议，不能直接当作恢复官方提示词后的验收。
  旧诊断曾观察到官方措辞下9B先解释再回答；本次不改变评分规则或输出后处理。
  新运行须使用新输出目录和输入哈希清单，不可覆盖旧 `input_audit.json`；小回归脚本在自身输出目录内创建媒体缓存。
- **失败处理**：官方 MVU-Eval 和 CrossVid 会静默丢弃失败的题。这里失败会记录为 error，重跑同一命令时会补跑；
  只有全部题目成功才给出总分。CCQA 的 Judge 失败同样报错，不记为 0 分。
- **CCQA Judge**：论文使用 GPT-4.1。本框架与 MVAgent 共用同一个固定的本地 Judge：Qwen3-30B-A3B-Instruct-2507，
  在 vLLM 上每张 GPU 一个副本、每个副本同时只处理一个请求，贪心解码（启动脚本
  `eval/agent_eval/serve_ccqa_judge.sh`，客户端 `eval/agent_eval/score_crossvid_ccqa.py`）。prompt、system message、
  生成参数（temperature 0、top_p 0.95、最多 8192 token）和汇总公式与 `score_CCQA.py` 一致（prompt 运行时逐字校验）。
  2026-10-08 起取代 deepseek-v4-flash，此前 DeepSeek 评出的 CCQA 分数不要与之混用。
  Actor 的重复性验收不能外推到 Judge；复用逐答案 Judge 缓存，保留原评分与敏感性。历史反例见实验记录。

## 运行

本地 Qwen3.5 使用 [`serve.py`](serve.py) 启动独立单卡副本。HTTP 保留原测试接口，每个端点的
接收、标准 vLLM `LLM.chat` 和模型 forward 都在同一个进程主线程串行执行。
`run.py infer/score/preview`、`--endpoints`、题目选择与输出目录接口保持不变；闭源 API 仍走原 provider。

先经 `modal-gpu` 创建一个 `devbox.sh up --gpu 'H100!:8' --no-pool` Sandbox（访问规则见
`mvagent-environment` skill），在远端启动下列服务，再在同一 Sandbox 的另一个任务运行 `infer`。
服务启动日志在每端口目录的 `server.log`；全部出现 `READY` 后开始测评。换模型时先终止这个
`serve.py` 父进程（SIGTERM/Ctrl-C 会关闭它的全部副本），改模型路径和日志目录后再启动，复用同一 Sandbox。
E2E 不使用原 MVAgent 的 `prelaunch.py` / `devbox.sh serve` 启动路径。

```bash
# 以下 Python 命令在远端 /repo 执行；三模型分别用 9B、27B、35B-A3B
python eval/e2e_eval/serve.py --model /weights/Qwen3.5-9B \
  --gpus 0-7 --port 8100 --log-dir /runs/e2e/9b_servers_01
```

统一执行配置在 [`src/models/vlm/local/sync_server.py`](../../src/models/vlm/local/sync_server.py)：BF16、TP1/DP1、每卡并发1、
`uni`/inproc、同步 eager、FlashInfer GDN prefill；seed/temperature 0、thinking 关闭；
context131072、prefill32768、maxseq1、显存比例0.94；`PYTORCH_ALLOC_CONF=expandable_segments:True`
减少不同图像批次的显存碎片。正常解码 KV cache 开启，prefix/MM processor cache关闭。
保留usage.prompt_tokens_details.cached_tokens与cache_hit_rate观测字段；prefix关闭时计数为0。
固定配置 另设 `compilation_config.custom_ops=['all','-gemma_rms_norm']`，关闭 RMSNorm 算子内部的动态编译。
此配置变更会改变数值和部分输出，须使用新的输出目录；原命令行和调用接口不变。
固定 vLLM0.19.1、torch2.10.0、transformers4.57.6、xgrammar0.2.2、FlashInfer0.6.6、Triton3.6.0。
客户端核对服务配置、版本、运行源码、权重元数据及各副本的实际 GPU；普通 vLLM 异步服务或不匹配的配置会明确报错。
模型权重标识包含 JSON、Jinja 模板与 txt 文件哈希及 safetensors 文件名/大小/mtime，不是全部权重字节的哈希。

这是仅供同机 E2E 的非流式 chat 端点，只监听回环地址；不提供通用 OpenAI 服务的全部功能。
本地模型的 `--enable-thinking` 与非零采样参数不适用于此固定协议。服务推理失败后退出该池，需检查日志再显式重启。

```bash
# 推理：可断点续跑；同一 --output 下协议、模型、题目集合或源码变化会拒绝续写
python eval/e2e_eval/run.py infer --output OUT \
  --endpoints 8100-8107 \
  --benchmarks cvbench,mvu_eval,crossvid \
  --ids crossvid=eval/crossvid_2500.json \
  --media-cache-dir /work/e2e_media

# 评分与汇总。CCQA 由本地 Judge 评分：先在空闲 GPU 上启动 Judge（每张卡一个副本，端口从 8100 起），
# 再传 --judge-endpoints；不传时其他题照常评分，CCQA 记为未评分并列入 failures
bash eval/agent_eval/serve_ccqa_judge.sh 0-7 8100
python eval/e2e_eval/run.py score --output OUT --judge-endpoints 8100-8107

# 核对输入：按真实流程构造消息但不调用模型，按顺序打印文字原文与图片（连续同尺寸图片合并为一行）
python eval/e2e_eval/run.py preview cvbench:3 mvu_eval:Counting:0 crossvid:MOC:0
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
  source/              首次运行时冻结的 run.py、serve.py 与 harness/；续跑时必须一致
  selection.json       每个 benchmark 选中的 sample_id
  raw/<bench>.jsonl    每题一行，追加写入：status、output（模型原文）、error、media（帧数、尺寸）、
                       request（端点、usage、finish_reason、生成参数，服务端若返回 reasoning_content 也保存）、seconds
                       本地同步服务另存完整输出 token_ids、请求/输入/prompt token 哈希、实际 worker 与 inference_seconds
  scored/<bench>.json  逐题评分：prediction、answer、score（官方），format_ok、robust_prediction、robust_score
                       （格式稳健），CCQA 另有 coverage/correctness/points
  summary.json         各 benchmark 官方总分（CVBench/MVU-Eval 为 accuracy，CrossVid 为 o_avg）与格式稳健总分
                       （robust_accuracy / robust_o_avg）、格式合格率、分 task 分数、完成度，以及核查项（每次调用
                       最大帧数、最大边长、prompt token、finish_reason）；scoring_code_matches_inference 标明评分代码
                       是否与推理时冻结的代码一致
  judge_cache/         CCQA Judge 响应缓存
```

逐题记录与 MVAgent 的 sample_id 相同，可以直接按题对比。
本地响应缺失 token 审计或身份/哈希不符时不会记为成功。`request.seconds` 仍为客户端调用耗时，
新增的 `inference_seconds` 是服务端生成耗时。`manifest.runs[].backend.replicas` 保存每次启动的 PID/GPU UUID；
服务重启或换卡不改变续跑身份，源码、协议、权重或执行配置改变则拒绝续写，需新的输出目录。
升级前的旧目录保留原样，不能把缺少该执行协议和 token 证据的历史输出混入新运行。

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
