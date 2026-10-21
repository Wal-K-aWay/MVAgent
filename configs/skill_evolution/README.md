# Skill 生成配置与冻结划分

- `llm_generation.yaml`：一次生成使用的 `ApiVLMConfig` 参数；凭据为环境变量名。
  `max_retries: 1` 表示一次尝试，入口拒绝改为自动重试。
- `splits/`：保留已有冻结划分与 CrossVid 干净池；一次生成不读取这些数据。

```bash
python scripts/generate_skills.py \
  --config configs/skill_evolution/llm_generation.yaml \
  --runtime-config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --role both --output-dir /path/to/new-run
```

`--runtime-config` 仅提供角色动作预算，不启动 Actor、Selector、Embedding 或 Judge。
旧训练配方及训练入口已移除；没有可用的自进化循环。
详细协议见 [LLM 生成说明](../../docs/llm-skill-generation.md)。
