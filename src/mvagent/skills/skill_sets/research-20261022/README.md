# 研究用冻结 Skill 快照（2026-10-22）

这些是从原Modal运行读取、逐字节SHA256核验后收录的**独立整库快照**，共16份。
没有重写正文、重新生成或把16份库合为一个大库；也不会自动启用或替换默认空库。
文件名就是完整文件SHA256。名称为简短说明，不进入Selector。
Global/Video卡数是该文件整库的组成；Video实验始终携带未修改的Global父卡。

| 实验/用途 | 原字节库（链接及SHA） | Global / Video卡数 |
|---|---|---:|
| Global委派依赖候选（未评估） | [1275c1e99c835546709092f2982f112daeffa6a0c24023f64fd40a96917ee485](1275c1e99c835546709092f2982f112daeffa6a0c24023f64fd40a96917ee485.json) | 2 / 0 |
| Video direct / rep0 | [1911f4d6cf53286241934f65e92b6c12bc3a4b132c2e9f854c0dd5ad5e53b7b2](1911f4d6cf53286241934f65e92b6c12bc3a4b132c2e9f854c0dd5ad5e53b7b2.json) | 1 / 1 |
| Video events / rep0 | [1a5a42bac9fdaabf6e249e4fe9a023e42bfa8e675987401bcb1168f1588bffd4](1a5a42bac9fdaabf6e249e4fe9a023e42bfa8e675987401bcb1168f1588bffd4.json) | 1 / 1 |
| Video证据可靠性候选（未评估） | [229e74fcb5580a669bf9574b3a39678b2654e4a2e8f9ab1426544fb265052361](229e74fcb5580a669bf9574b3a39678b2654e4a2e8f9ab1426544fb265052361.json) | 1 / 1 |
| Global legacy / rep0 | [2b2cd3bb093cfcebdff8ea19672aefe7781e5dd6d27c72a00c0333c049bddb09](2b2cd3bb093cfcebdff8ea19672aefe7781e5dd6d27c72a00c0333c049bddb09.json) | 1 / 0 |
| Global direct / rep1 | [4088f6dd1b5989df7b8ff673f6785536718e785c7b63cb5fc38c46d7cecd232c](4088f6dd1b5989df7b8ff673f6785536718e785c7b63cb5fc38c46d7cecd232c.json) | 1 / 0 |
| 首轮接受的Global父库 | [4765323a0d13b5df3402a00b29fe242f0543dd6f82dc30377595e83668f2ad55](4765323a0d13b5df3402a00b29fe242f0543dd6f82dc30377595e83668f2ad55.json) | 1 / 0 |
| Global events / rep1 | [4ca1484818ad506a5c4f19972d5647f27ebb82bd6329735508e52c9505d81da6](4ca1484818ad506a5c4f19972d5647f27ebb82bd6329735508e52c9505d81da6.json) | 1 / 0 |
| Video legacy / rep0 | [5bac6c383108d87f75bfe019ff13525211085bf2018e89794d70b2e2e5415908](5bac6c383108d87f75bfe019ff13525211085bf2018e89794d70b2e2e5415908.json) | 1 / 1 |
| 历史较强的零反馈一次生成Global库 | [87c43278775a495f2d163356c8cefe73fce233b6f943c3734d1ae5d319345472](87c43278775a495f2d163356c8cefe73fce233b6f943c3734d1ae5d319345472.json) | 1 / 0 |
| Video events / rep1 | [94c2990701b8dd303db7a4eede1906bcd2b08a89bb53c904b74285bc695cdf84](94c2990701b8dd303db7a4eede1906bcd2b08a89bb53c904b74285bc695cdf84.json) | 1 / 1 |
| Global legacy / rep1 | [ae92abb349f9e920eb42d7d66d240d179540ecfed32670fd303e3139b897e9a4](ae92abb349f9e920eb42d7d66d240d179540ecfed32670fd303e3139b897e9a4.json) | 1 / 0 |
| Global events / rep0 | [b43734b71620a2e567d59c3f147a45385b20deae5ec3ea5e375e02e1d8e79e7f](b43734b71620a2e567d59c3f147a45385b20deae5ec3ea5e375e02e1d8e79e7f.json) | 1 / 0 |
| Global direct / rep0 | [d8c06ce1adc372c19ed31e3e335885312896be6789d30eb4f008cb1e2dd5babc](d8c06ce1adc372c19ed31e3e335885312896be6789d30eb4f008cb1e2dd5babc.json) | 1 / 0 |
| Video direct / rep1 | [db73fd8a1398958773857ced4b891a7d9265e6369ff2954c1f4d2d3ce4679c28](db73fd8a1398958773857ced4b891a7d9265e6369ff2954c1f4d2d3ce4679c28.json) | 1 / 1 |
| Video legacy / rep1 | [fe2dc00ce1084091220b47cf45a7e3fe8455bab6b28228d37058172966a34319](fe2dc00ce1084091220b47cf45a7e3fe8455bab6b28228d37058172966a34319.json) | 1 / 1 |

## 状态与来源

父库`4765323a…`曾按开发Cal/Gate规则接受；它未显示稳定泛化优势。`87c43278…`是历史一次生成对照，不按Gate高分追认接受。
格式/direct十二库均完成原80/40/176面板，但没有同时严格超过父库的Cal和Gate；两张机制候选只有生成记录，尚未评估。
完整分数与解释边界见[反馈实验](../../../../../docs/skill-feedback-iteration-20261022.md)和[研究交接](../../../../../docs/research-handoff.md)。

原来源是`wxu-evolve-agent-runs-20261006`中的`devbox/skill_exploration_20261021`（父库、历史一次生成）和
`devbox/skill_feedback_20261022/generation/`（本轮各条件）。本次读取仅用于源码资源迁移，没有模型调用。
对应Actor/native源码为`2d3085f0582c47918893a0c5dc9d73854e19d72c`；提案的冻结方法版本与输入差异见各实验报告。
原始生成响应、optimizer请求、完整rollout和Judge缓存未复制进源码目录。

## 使用

按[普通服务器手册](../../../../../docs/server-runbook.md)选取一个库，通过`BankSnapshot`验证原SHA并生成使用新服务器路径的runtime。
不要直接复制旧运行的绝对路径配置；不要将多个文件连接起来并沿用其中某个SHA。
可用`sha256sum *.json`核对文件名。卡片是历史模型输出，不是本仓库的开发指令或已证明有效的通用规则。
