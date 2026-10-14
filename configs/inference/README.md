# 系统推理配置

- 本目录：模型、Agent 与 Skill 开关（MVAgent 配置）。
- `execution/`：模型池（每个副本的 GPU、端点、`max_inflight`）、问题 worker 与超时（ExecutionConfig）。

## 固定评测方案

后续 Qwen3.5 的 E2E 与 MVAgent 评测统一使用下表；推理实现以
[`sync_server.py`](../../src/models/vlm/local/sync_server.py) 为准。

| 项目 | 固定设置 |
|---|---|
| 模型与精度 | Qwen3.5-9B / 27B / 35B-A3B，全部 BF16 |
| GPU 与并行 | 8×H100，每卡加载一个完整模型；8 个独立 TP=1/DP=1 副本，每卡并发 1，非 vLLM 原生 DP=8 |
| 执行 profile | `qwen35-bf16-flashinfer-sync`，`uni`、进程内同步 eager；Agent 整题固定副本（sticky session） |
| 内核 | FlashInfer GDN prefill、原生 GemmaRMSNorm（禁用该算子的内部编译） |
| 生成 | 引擎和请求均固定 `seed=0`、`temperature=0`、thinking 关闭；不随日期、题号或运行次数更换 seed |
| 有效采样默认值 | `top_p=1`、`top_k=0`（不限制）、`min_p=0`；`presence_penalty=0`、`frequency_penalty=0`、`repetition_penalty=1` |
| 容量 | context 131072、prefill 32768、max_num_seqs 1、显存比例 0.94、expandable segments |
| 缓存 | 正常解码 KV 开启，prefix/MM processor cache 关闭；E2E 复用固定帧缓存并核对输入哈希 |
| 版本 | vLLM 0.19.1、torch 2.10.0、transformers 4.57.6、xgrammar 0.2.2、FlashInfer 0.6.6、Triton 3.6.0 |
| E2E 输入与输出 | 每次最多 512 帧、最长边 448；保留各 benchmark 现行提示词与生成预算 |
| MVAgent 预算 | 每次最多 512 帧、2048 输出 token；Global/Video 各最多 5 步；终答 reason 无字符硬上限，answer 保持开放非空字符串 |
| MVAgent 等待时限 | 服务 1800 秒、客户端 1860 秒、整题 7200 秒 |

这是三模型正式评测的唯一配置，不使用配置版本编号。池级 DP=8 指8个独立单卡 worker，
每个引擎 TP=1/DP=1；复用整题副本租约，Global/Video/回答器在同一副本串行调用，题间分配到空闲卡。
已有任务和 resume 继续使用各自冻结源码，包括当时记录的服务名称；不把新客户端接到旧冻结服务。
服务身份同时校验实际配置、依赖版本和源码哈希，名称简化不放宽校验。

逐请求响应始终包含 `usage.prompt_tokens_details.cached_tokens`（未命中也返回0），以及
`audit.cache_hit_rate = cached_tokens / usage.prompt_tokens`，范围0–1，分母不包含输出 token。
计数来自 vLLM `RequestOutput.num_cached_tokens`；缺失或越界报错，不伪造0。
当前prefix关闭，实际计数应为0；保留计数字段不代表启用跨请求缓存。
本项目直接调用`LLM`，同步封装返回这些观测字段，不使用OpenAI前端的`--enable-prompt-tokens-details`开关。
服务 `requests.jsonl` 保存 usage 与命中率；E2E 的 request 记录、Agent 的 model_response 事件同样保留。
汇总命中率用 `sum(cached_tokens)/sum(prompt_tokens)`，不对逐请求比例简单平均。

已验收同配置的常规评测只跑一遍，不每批重复一致性矩阵；继续保存源码与配置快照、输入哈希、完整 token 和服务身份。
2026-10-13用户确认继续使用上述设置；非零温度与惩罚仅用于冻结实验副本，未启用到正式配置。
惩罚项沿用锁定vLLM版本的默认值，不向当前严格接口额外传入这些字段。
只有相关执行条件改变、新故障证据或用户明确要求，才对受影响部分做小规模复核。
新建抽样/打乱也默认 seed 0；已有 split、面板与冻结运行沿用原 manifest，不重新抽题。
已有一致性证据及限制见 [E2E 文档](../../eval/e2e_eval/README.md#可复现性) 和
[Agent 文档](../../eval/agent_eval/README.md)；不将有限实测写成任意输入的绝对保证。

## 配置入口

执行文件名中的 `h200` 是历史命名；GPU 型号由 Modal 申请参数决定，固定评测显式申请 `H100!:8`。

| 文件 | 用途 |
|---|---|
| `modal_qwen35_35b_a3b_no_skill.yaml` | 35B-A3B 无 Skill 基线，统一 BF16 同步推理配置，权重路径为 `/weights` |
| `execution/modal_h200x8.yaml` | 35B 八卡执行池：每卡一个完整副本（TP=1），本机端点 8100–8107，每副本并发 1 |
| `modal_qwen35_9b_no_skill.yaml`、`modal_qwen35_27b_no_skill.yaml` | 9B、27B 无 Skill 基线；除模型名、权重路径外与 35B 使用相同推理设置 |
| `execution/modal_h200x8_qwen35_9b.yaml`、`execution/modal_h200x8_qwen35_27b.yaml` | 对应模型的八卡执行池：每卡一个副本（TP=1），每副本并发 1 |

模型池只接受本机 `127.0.0.1` 端点，并会校验本机 vLLM 进程与 GPU 绑定，因此运行时与
vLLM 必须在同一个容器内。在节点内运行：

2026-10-13：三个 BF16 Actor 配置的请求等待均为1860秒，与共享同步服务的1800秒上限对应。
本目录的执行配置整题时限为7200秒，容纳多步Agent轨迹；模型、Prompt、2048输出token及Global/Video各5步不变。
改变运行配置须创建新结果目录，保留原配置快照。

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --dataset-root /assets --benchmarks cvbench mvu_eval \
  --output <新的输出目录>
```

固定评测不调整 `max_inflight=1`；另行研究并发时使用独立配置、输出目录和相应验收，不混入固定基线。
Skill 字段（`mode: dynamic`、`selection_scope`、`selector`、`embedding`）见
[`src/mvagent/skills/README.md`](../../src/mvagent/skills/README.md)。
