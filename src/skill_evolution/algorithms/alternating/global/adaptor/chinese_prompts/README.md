# Global 优化阶段中文 Prompt 镜像

这里采用平铺结构，每个阶段一个 Markdown 文件，方便阅读；不需要跟随英文代码的包结构。
仅供文档阅读，不被程序加载。修改英文 Prompt 或 Schema 时同步对应阶段的镜像。
字段名、动作名、枚举、ID 和模板变量保持原样；示例附中文释义及完整英文原文与 JSON。

| 内容 | 中文镜像 | 英文源 |
|---|---|---|
| 共享背景 | [common.md](common.md) | [common.py](../prompts/common.py) |
| Localizer | [localizer.md](localizer.md) | [localizer/](../prompts/localizer/) |
| Linker | [linker.md](linker.md) | [linker/](../prompts/linker/) |
| Reviser | [reviser.md](reviser.md) | [reviser/](../prompts/reviser/) |
| Generator | [generator.md](generator.md) | [generator/](../prompts/generator/) |
| 消息拼接 | [__init__.md](__init__.md) | [__init__.py](../prompts/__init__.py) |

每个阶段文件包含 Prompt 分块及末尾的 Schema 说明。System 拼接规则如下；
User 为上下文、规则、示例与输出格式。实际轨迹和动态 Schema 以运行请求为准。

当前拼接：Reviser/Generator 的 System 为 TASK + BACKGROUND + CARD_CONTRACT；其他阶段仍为 TASK + BACKGROUND。User仅保留阶段指导、动态案例和输出合同。共用示例只出现一次。长度采用输入上限，无1800软目标或固定字段篇幅配额。候选直接按输入长度限制校验，超限拒绝。
