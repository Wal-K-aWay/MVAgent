# 冻结的运行时 Skill 库

这里保存明确选定、供复现和对比实验使用的 schema v3 JSON 库。文件名为文件内容的
SHA256；同一库可包含 Global 和 Video 卡，Runtime 按 role/stage 过滤后自动选卡。
目录名记录来源，不能据此推断效果优于空库。

生成器先将候选库、原始响应和校验记录写入 `--output-dir` 指定的实验目录。
需要随代码分发的冻结库再原样复制到这里，并记录来源及哈希；不自动覆盖、挑选或发布候选。
原始响应、轨迹、评分、缓存和模型配置快照仍保存在实验目录，不复制进源码树。
空库条件通过 `enabled: false` 表示，无须空文件或占位库。

## 当前库

[`deepseek-flash-20261021/7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049.json`](deepseek-flash-20261021/7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049.json)

- DeepSeek-Flash，thinking/high；生成源码 `84cd9f9`，两个角色各一次生成，Global 6 张、Video 8 张。
- SHA256：`7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049`；29680 bytes。
- 原始输出未通过严格 Schema：Global 多出 `strategy_note: null`，Video 多出
  `strategy_placeholder: null`。后续仅删除这两个额外空字段，两个文本字段逐字保留；
  没有重新生成、人工润色、使用问答反馈或根据分数选库。此处是该规范化库的逐字节副本。
- Global 原始响应 SHA256：`a1f7b237076dbbb676b582d289deb302279316f74a987ef3c0392e84dfaff11b`。
- Video 原始响应 SHA256：`85e3531c31a572fced9c4149d358399e6e55ab4738b485b3400b85db34257fd9`。
- 原始响应与规范化记录保存在 Modal runs volume；已核验的 AWS 原件保留于
  `outputs/skills/deepseek_flash_20261021/`。完整来源和验证见
  [生成记录](../../../../docs/llm-skill-generation.md)及
  [三模型先导评测](../../../../docs/deepseek-skill-pilot.md)。

此库已验证选卡、注入和完整问答流程，但先导评测没有稳定提升的证据。
它是一份一次生成的对比基线，不是自进化产物，也不替换默认空库配置。

## 配置引用

将以下 skill 配置合入所用模型配置的两个角色中；保留原有模型和动作预算。
相对路径由 Runtime 按 `src/mvagent/` 解析，与启动命令的工作目录无关。

```yaml
agents:
  global_agent:
    skill: &deepseek_skill
      enabled: true
      mode: dynamic
      path: skills/skill_sets/deepseek-flash-20261021/7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049.json
      sha256: 7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049
      selection_scope: task
  video_agent:
    skill: *deepseek_skill
```

两个角色共享同一文件，但各自只选本角色的卡，不共享选卡结果。旧实验及正在运行的评测
继续读取各自的冻结副本；移动或发布库不改写它们的路径、哈希或源码。

## 清理记录

2026-10-21 删除未被现有配置或测试引用的 `authored-v000/`、`seed-v001/` 和
`dynamic-v003/`，共四份旧 Markdown 策略、两份旧 JSON 快照。
旧内容仍可从清理前提交 `653e947` 和原始冻结实验中查阅。
原 README 中尚未实现的 `zero-vNNN` 接受/进化流程说明也已移除；不作为后续算法的前提。
