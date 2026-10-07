# 系统推理配置

- 本目录：模型、Agent 与 Skill 开关（MVAgent 配置）。
- `execution/`：模型池（每个副本的 GPU、端点、`max_inflight`）、问题 worker 与超时（ExecutionConfig）。

| 文件 | 用途 |
|---|---|
| `modal_qwen35_35b_a3b_no_skill.yaml` | 35B-A3B 无 Skill 基线；参数与旧服务器历史基线一致，权重路径为 `/weights` |
| `execution/modal_h200x8.yaml` | 一个 Modal `H200:8` 节点：每卡一个完整 35B 副本（TP=1），本机端点 8100–8107，每副本并发 1 |
| `modal_qwen35_9b_no_skill.yaml`、`modal_qwen35_27b_no_skill.yaml` | 9B、27B 无 Skill 基线；除模型名、权重路径和请求超时（300 s，与旧服务器 9B 配置一致）外与 35B 配置相同 |
| `execution/modal_h200x8_qwen35_9b.yaml`、`execution/modal_h200x8_qwen35_27b.yaml` | 对应模型的 `H200:8` 执行池：每卡一个副本（TP=1），每副本并发 1 |

模型池只接受本机 `127.0.0.1` 端点，并会校验本机 vLLM 进程与 GPU 绑定，因此运行时与
vLLM 必须在同一个容器内。在节点内运行：

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --dataset-root /assets --benchmarks cvbench mvu_eval \
  --output <新的输出目录>
```

调整每副本并发时复制执行配置并修改 `max_inflight`；它会改变批处理组合，结果不能与并发 1 的基线直接比较。
Skill 字段（`mode: dynamic`、`selection_scope`、`selector`、`embedding`）见
[`src/mvagent/skills/README.md`](../../src/mvagent/skills/README.md)。
