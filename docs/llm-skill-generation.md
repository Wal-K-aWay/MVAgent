# LLM 一次生成 Skill 库

这是借鉴 SkillOpt 一次生成基线的 MVAgent 适配，不是其未公开生成 Prompt 的严格复现。
仅提供通用多视频问答任务、角色信息边界、实际动作说明和 Skill 格式；不读取题目、媒体、
答案、轨迹、成绩或已有卡片。不按 benchmark 单独生成，不根据评测结果修订。

在远端项目环境中，凭据通过 `BIGMODEL_API_KEY` 环境变量注入：

```bash
python scripts/generate_skills.py --role both \
  --output-dir /runs/devbox/one_shot_skills/run1
```

输出目录必须不存在。默认 `--role global`，可选 `video` 或 `both`。
每个角色单独一次请求，默认 1–8 张卡；`--max-cards` 可预先限定为 1–8。
两种角色使用独立上下文，不读取另一角色刚生成的卡。
默认配置 `configs/skill_evolution/llm_generation.yaml` 使用 `glm-5.3-flash`，reasoning_effort=high、temperature=1、top_p=.95、
输出预算16384、HTTP超时600秒；使用现有 BigModel provider 的 JSON mode。
没有任务反馈、自动重试、生成修复、人工润色或按分数挑选。
该生成配置不改变 Actor 固定的 seed=0 等评测设置。

程序分配顺序数字 ID，role 由调用方设置，所有卡的 stages 为 initial/evidence。
Selector 的 task scope 保持原样；Global 每题、Video 每次请求首次选择后沿用。
现有 Runtime 校验字段、字数及渲染，之后重新按 SHA256 加载 role bank 和完整 bank。
这些检查不证明选卡适用性、真实行为或准确率收益；本入口不运行 Actor 或 Judge。

结果包含每角色 request.json、response.json、events.jsonl、validation.json、bank.json，
以及合并 bank.json、summary.json、生成配置、运行配置、源码快照和逐文件 SHA。
响应在解析之前保存；失败目录保留，不能覆盖后假称首次成功。
events 包含实际请求体、响应正文、模型身份、finish_reason、usage 和耗时；不含认证请求头。
使用现有 provider 日志，不声称保存了供应商完整 HTTP 响应或 reasoning_content。
生成数据只留实验 runs volume，不进入 Git；可共享的代码和本说明独立备份。

## 代码与配置

核心代码位于 [`src/skill_evolution/generation/`](../src/skill_evolution/README.md)：
`prompts.py` 管 Prompt/Schema，`generator.py` 管调用与产物，`cli.py` 管命令行。
`scripts/generate_skills.py` 仅启动 CLI。模型参数使用已有 `ApiVLMConfig`，
默认文件为 `configs/skill_evolution/llm_generation.yaml`，可通过 `--config` 指定。
`api_key` 只能填写环境变量名，入口固定一次尝试，不创建新模型客户端或重试框架。

默认 `--runtime-config` 为 `configs/inference/modal_qwen35_35b_a3b_no_skill.yaml`。
仅读取该配置中的动作预算；不是启动模型服务，也不会把完整配置发给生成模型。
角色描述、生成 Prompt、输出 Schema 和解码参数保持首次运行的协议。
角色/阶段常量与结构校验复用 `SkillBank`，动作说明复用两个 Agent 的 Prompt builder，
源码保存复用 `ensure_source_snapshot`，JSON 原子保存和哈希复用 `evaluation.store`。
旧算法、轨迹分析器、训练配置与默认旧卡库引用已经移除。

## 生成 System Prompt 中文镜像

你为冻结的多视频问答系统编写可复用 Skill。只使用给定任务描述、运行契约和 Skill 格式；
不会提供题目实例、媒体、答案、执行轨迹、成绩或已有 Skill。
为指定角色创建互补方法，自行确定范围；不预设 benchmark 分类，不用重复方法凑满数量。
每张卡恰有两个非空英文文本字段：

- `when_to_use`：根据 Selector 可见输入判断的适用条件。
- `strategy`：仅使用该角色动作和可见证据、自包含的执行方法。

Selector 最多选一张或不选，只读 `when_to_use`；Actor 只接收 `strategy`，因此执行前提和
排除条件写进 `strategy`。不能依赖另一张卡；依赖未来观察的分支放在 `strategy`。
遵守动作、记忆、回答契约，不虚构工具、额外输出字段或隐藏信息。不编码数据集名、task 代号、
样本身份或答案。Skill 指导可复用方法，而非当前一道题。
每卡简洁；两字段合计和含标题的渲染正文分别遵守给定字数上限。仅返回要求的 JSON。

## 生成 User Prompt 中文镜像

任务：回答证据分散在多个视频中的问题。系统包含一个全局协调者及每视频一个证据 Agent；
后者接收局部 instruction、返回报告，内部观察私有；协调者也可获取联合视觉观察。
目标 role 为 `{role}`，实际动作说明由 `generation/prompts.py` 中的 `build_role_architectures` 从冻结 Runtime 拼接，
包括参数占位示例，不包含已编写的 Skill 示例。

Global Selector 看完整问题、视频 ID 和时长，每题开始时选择一次（包括不选）；
Video Selector 只看本次 instruction，不看 Memory 或完整问题；每请求选一次，跨请求保留本视频观察记忆。
所有卡在 initial/evidence 阶段 eligible，stage 不调度未来切卡。
策略指导普通决策；Global answer-only 终答保留策略，Video 强制总结只读 Memory/instruction。

生成 1 至 `{max_cards}` 张，不必凑满。每卡文本及渲染正文上限 `{MAX_SKILL_WORDS}` words。
仅返回 `{"skills": [{"when_to_use": "...", "strategy": "..."}]}`。
调用方设置 ID、role、stages；不返回 metadata 或额外说明。

## 首次真实生成（2026-10-21 UTC）

运行源码 `98ad0c4`；Modal CPU app `ap-KtgWYywyIdxH6SrYeqKfzK` 已正常结束，GPU使用为0。
两个针对性测试和完整 `compileall src scripts eval/agent_eval demo.py` 通过。
每角色一次请求，无自动重试/格式修复；两次返回模型均为 `glm-5.3-flash`，finish_reason=stop。

| 角色 | 卡数 | 耗时/秒 | 输入token | 输出token（含reasoning） | 每卡字数 |
|---|---:|---:|---:|---:|---|
| Global | 5 | 23.94 | 1892 | 1064 | 173/179/140/133/129 |
| Video | 4 | 31.62 | 1338 | 1501 | 293/246/248/210 |

全部通过结构、字数、渲染与哈希加载。结束后通过新的 Volume SDK 读取核实完整库及两个角色库 SHA。
原始输入、响应、日志及库位于 runs volume 的 `devbox/one_shot_glm53_20261020/run1/`。
完整 `bank.json` SHA256：`1b9d4d10ceee49924b1a473c31a639a1d39de7f9ab5ac206866b9a0f5ccd5ee3`。

输出示例（Global第5张）：
“If phase-1 reports already resolve the question completely, skip phase 2 and answer directly”。

本次只验证生成流程，没有运行真实 Selector、Actor、视频问答或 Judge。
阅读产物发现 Global第3/4张、Video第6–9张的部分 when_to_use 依赖 History/Memory，
而当前 Selector 看不到这些信息，可能无法正确触发；Video策略还将每范围的帧上限写成跨范围共享上限。
这些是生成基线的局限，产物保留原样，没有据此改写或重新生成；不能据格式通过宣称策略有效。

## 清理与分层后的验证（2026-10-21 UTC）

源码 `39217ef`：旧算法和训练入口移除；生成器分层，共享评测迁至 `src/evaluation/`。
角色 Prompt、Schema 与有效模型配置逐项对比首次运行保存的请求，全部相同。
评分模块移动前后逐字节一致。26 个 CPU 回归用例通过（首轮25个通过，
一个新测试因排序GT误用整数失败；仅修为契约要求的字符串后补测通过），
另有 token 自检、完整 compileall 和5个CLI入口检查通过。
没有重装依赖、运行媒体测试、启动GPU、Selector、Actor或Judge。

真实 GLM 冒烟 app `ap-QQOhYUejHNczs0ya93OoF4` 已停止，tasks=0。
仅一次 Global 请求；返回 `glm-5.3-flash`、finish_reason=stop、1892输入/1339输出token，
返回5张卡，但第一张包含未允许的 `prerequisites` 字段：

```text
$.skills.0: Additional properties are not allowed ('prerequisites' was unexpected)
```

原始字段值为 `No cross-video evidence in History yet, or existing reports are insufficient for the question.`。
生成器先保存响应，再按现有 Schema 拒绝；没有发布角色库或合库，没有继续 Video 调用，
没有删除字段、自动修复或重新抽样。因此本次测到的是一次真实的格式失败及正确的失败留存，
不是新的有效skill库或准确率结果。此前首次运行的9张有效卡及原始材料保持不变。
记录仅在 runs volume 的 `devbox/skill_generation_cleanup_20261021/checks2/smoke1/`；
测试日志在同父目录及 `devbox/skill_generation_cleanup_20261021/step0.log`。
