# Global scope v1（设计中，未实现）

`global-scope-v1` 是 Global skill 自进化的新方案，设计见 [docs/design.md](docs/design.md)。

核心思路：不使用任何预设的题型分类，用运行时 Selector 的选择给题目分组。

- 每张卡只在 Selector 选中它的题上起作用，所以只在这些题上实测净收益。
- 按测量结果修改 strategy、收窄 when_to_use 或删卡。
- 新卡的适用题型由 optimizer 从空组（Selector 一张卡都不选的题）的失败题中用自由文本描述，再由 Selector 落实成题目集合。
- 卡库在独立 Gate 上的官方总分提高，且提高幅度超出扰动噪声，才被接受。

目前只有设计文档。实现顺序与里程碑见设计第 10 节，决定记录见第 12 节。
