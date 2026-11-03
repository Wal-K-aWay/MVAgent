# 手工多卡组合与完整中文来源映射

三库均未测试、未提交作业。原正文与入口的完整中文见[八机制镜像](manual-study-skills-zh.md)及[compact镜像](manual-compact-skills-zh.md)，仅引用ID按下面的来源顺序重编号，不新增执行文本。A 收录原八机制 paragraph；B 仅将 A 的第 2 张卡入口替换为已登记的 35fbe7… 来源，执行正文仍为原 paragraph；C 收录八张 compact 执行正文及各自原入口。没有重新撰写执行内容，也没有按 Train 分数挑机制。

按原 manifest 机制顺序，将卡片引用 ID 从各单卡库的 `1` 唯一重编号为 `1`–`8`；role、stages、when_to_use 和 strategy 均逐字复制对应来源。每角色及每阶段最多 4 个候选，走当前小库全展示路径，不触发 embedding 检索。完整源文件 SHA 与逐卡映射见 [组合谱系](../src/mvagent/skills/skill_sets/manual-study-20261030/combination_manifest.json)。

本组引入真实多卡竞争、两个角色同时启用及引用编号变化，不能把整库结果冒充单卡内容干预。C 同时保留 compact 的长度与步骤粒度变化，不是纯排版。预备全部三库在同一批 120 个不同 Train 题上测试，最多 360 新题次；来源相关性与历史接触仍存在。未读取最终系统比较、Cal/Gate、GT 或评分点。

自动进化仍从两个 schema 合法空库开始；这些手写组合仅作开发诊断，不能作为进化种子。

- A：[4b2c92c1035c9314c5abea4b221f7c386154d08ae91fcacad3eefe40e32bd4d0](../src/mvagent/skills/skill_sets/manual-study-20261030/4b2c92c1035c9314c5abea4b221f7c386154d08ae91fcacad3eefe40e32bd4d0.json)。

- B：[bcbc63302b1f1c634cc27a77e68525db30a307d9c574d78d49e5998aa4a65f74](../src/mvagent/skills/skill_sets/manual-study-20261030/bcbc63302b1f1c634cc27a77e68525db30a307d9c574d78d49e5998aa4a65f74.json)。

- C：[49ce3f8a3f622b8d876681a7e6b8bf0d56a19d812dcc034afb3ded39c5f56aa2](../src/mvagent/skills/skill_sets/manual-study-20261030/49ce3f8a3f622b8d876681a7e6b8bf0d56a19d812dcc034afb3ded39c5f56aa2.json)。
