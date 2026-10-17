# Global scope v1（已有组件探针，完整进化循环未实现）

`global-scope-v1` 是 Global skill 自进化的新方案，设计见 [docs/design.md](docs/design.md)。

核心思路：不使用任何预设的题型分类，用运行时 Selector 的选择给题目分组。

- 每张卡只在 Selector 选中它的题上起作用，所以只在这些题上实测净收益。
- 按测量结果修改 strategy、收窄 when_to_use 或删卡。
- 新卡的适用题型由 optimizer 从空组（Selector 一张卡都不选的题）的失败题中用自由文本描述，再由 Selector 落实成题目集合。
- 卡库在独立 Gate 上的官方总分提高，且提高幅度超出扰动噪声，才被接受。

已有 `views.py` 轨迹视图、`prompts/` 中的模式发现与方法编写 Prompt、对应的 `chinese_prompts/`，
以及 `placebo/` 中的安慰剂文本。K1–K5 和迁移匹配诊断见 [组件探针结果](docs/probe_results.md)：
部分机制已验证，但所测四张卡尚未显示超出安慰剂的效果，不能据此宣称 skill 自进化有效。

完整进化循环尚未实现。实现顺序与里程碑见设计第 10 节，决定记录见第 12 节；
设计中的待办与会话笔记应结合上述实测结果、当前代码和最新用户决定读取。
