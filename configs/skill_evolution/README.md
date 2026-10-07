# Skill 自进化配置

| 文件 | 用途 |
|---|---|
| `global_skilladaptor_35b.yaml` | `global-skilladaptor-v1`，需要 Train/Gate split |
| `global_cluster_35b.yaml` | `global-cluster-v1`，需要 Train/Gate split |
| `global_cluster_v2_35b.yaml` | `global-cluster-v2`，需要 version=2 的 Train/Cal/Gate split |
| `runtime/dynamic_35b_embedding.yaml` | 三个 recipe 共用的 MVAgent 运行时：35B Actor/Selector（与无 Skill 基线参数一致）、GLM-5.3-Flash optimizer（`BIGMODEL_API_KEY`）、DeepSeek CCQA Judge（`DEEPSEEK_API_KEY`）、Embedding 端点 `127.0.0.1:8110` |
| `splits/crossvid_lite2500_eval_seed20260919.json` | 冻结的 2500 题 CrossVid 评估面板（全部为 eval），附 `.audit.json`；新建 Train/Gate 必须排除其源媒体 |

```bash
PYTHONPATH=src python scripts/run_skill_evolution.py --mode train \
  --config configs/skill_evolution/global_cluster_v2_35b.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --split-manifest <冻结的 split> --output-dir <新的输出目录>
```

不传 `--skills` 时从空库开始；`--mode evaluate` 独立评估，不加载 optimizer。各算法的参数与流程见
`src/skill_evolution/algorithms/alternating/global/{adaptor,cluster,cluster_v2}/README.md`。
Modal 上的 Embedding 服务尚未部署：Skill 库超过 8 张卡时检索需要 8110 端点。
