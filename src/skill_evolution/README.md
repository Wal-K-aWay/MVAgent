# Skill 方法

当前仅保留无反馈的 LLM 一次生成基线；尚无自进化训练循环。

```text
skill_evolution/
├── generation/
│   ├── cli.py          # 读取配置、选择角色、启动生成
│   ├── prompts.py      # System/User Prompt、角色契约、输出 Schema
│   └── generator.py    # 每角色一次调用，原始响应落盘、校验、合库
└── skill_specification.md  # 卡片编写规范；不作为生成模型的输入
```

入口为 `python scripts/generate_skills.py --role both --output-dir <new-directory>`。
默认每角色由LLM自主生成1–8张，`--max-cards N`设上限而非固定数量；两角色各生成一次。
完整成功后输出`runtime_with_skills.json`，只启用本次生成角色并明确task选卡，评测可直接使用。
模型参数在 [`configs/skill_evolution/llm_generation.yaml`](../../configs/skill_evolution/llm_generation.yaml)，
默认从现有无 skill 推理配置读取动作容量与步数；不加载其模型、题目或卡库。
输入边界、输出文件、完整中文 Prompt 镜像见 [生成说明](../../docs/llm-skill-generation.md)。

生成产物先保存到实验目录；明确选定的冻结库可原样收录到
[`src/mvagent/skills/skill_sets/`](../mvagent/skills/skill_sets/README.md)，供代码分发与复现。
当前收录 DeepSeek-Flash 的 6 张 Global / 8 张 Video 规范化库；不包含原始响应、轨迹或评分，
不自动发布新候选，也不改写已有运行的冻结引用。

复用关系：

- `models.llm.api.ApiLLMClient` / `ApiLLMConfig`：当前DeepSeek纯文本生成。
- `models.vlm.api.ApiVLMClient` / `ApiVLMConfig`：已有GLM等provider，按model_type选择。
- Global/Video 的动作 Prompt builder：动作名、参数和预算。
- `mvagent.skills.bank`：角色/阶段常量、schema v3、字数、渲染和哈希加载。
- `mvagent.utils.snapshot`：源码快照。
- `mvagent.utils.io`：原子 JSON 保存与指纹；生成器不读取评测样本或评分反馈。

评测和数据划分位于 [`eval/`](../../eval/README.md)，运行时选卡仍在
[`src/mvagent/skills/`](../mvagent/skills/README.md)。没有旧模块转发层，也不预建未来算法接口。
旧进化实现和负结果可从清理前提交 `de28149` 的 Git 历史及原始实验记录查阅，
不作为后续新方案的默认设计或 Prompt 输入。
