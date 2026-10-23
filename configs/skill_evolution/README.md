# Skill 生成配置与冻结划分

- `llm_generation.yaml`：一次生成的模型参数；当前为DeepSeek-Flash、`model_type: api_llm`、thinking/high，
  凭据为`DEEPSEEK_API_KEY`环境变量。也支持原有`api_vlm`配置；不新增客户端。
  `max_retries: 1` 表示首次请求后最多一次瞬时错误重试；入口固定该设置，不能称为严格单次HTTP尝试。
- `splits/`：保留已有冻结划分与 CrossVid 干净池；一次生成不读取这些数据。

```bash
python scripts/generate_skills.py \
  --config configs/skill_evolution/llm_generation.yaml \
  --runtime-config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --role both --output-dir /path/to/new-run
```

`--runtime-config` 提供角色动作预算，并作为成功后`runtime_with_skills.json`的基础；不启动 Actor、Selector、Embedding 或 Judge。
配套配置只启用本次生成的角色库，显式task选卡并绑定库SHA256，其他角色关闭skill。
`--max-cards N`是每角色上限，默认8；LLM自行决定1–N张，不按上限凑数。
`evolution.yaml`配置新角色轮换闭环的轮数、候选数、角色顺序和Train例子预算；Python校验在`src/skill_evolution/configs/`。
入口与冻结/恢复约定见[方法说明](../../src/skill_evolution/README.md)。旧训练配方和训练器未恢复。
详细协议见 [LLM 生成说明](../../docs/llm-skill-generation.md)。
普通服务器的Actor/Judge部署、完整十任务新split与rolewise命令见[服务器指南](../../docs/server-runbook.md)。
