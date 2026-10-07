# Global scope v1（设计中，未实现）

`global-scope-v1` 是 Global skill 自进化的新方案，设计见 [docs/design.md](docs/design.md)。

核心思路：optimizer 只根据 Train 轨迹写方法（strategy）；一张卡适用于哪些题，由强制注入后逐题配对的净收益决定；when_to_use 按实测范围编写，并只跑 Selector 做离线校准；卡库在独立 Gate 上的官方总分提高，且提高幅度超出扰动噪声，才被接受。

目前只有设计文档。实现顺序与里程碑见设计第 10 节，需要确认的决定见第 12 节。
