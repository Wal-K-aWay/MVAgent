# Global删减控制：删除全部程序性正文

控制标签：**删除全部程序性正文**（`global_terminal_only`）。这是单卡诊断对照，不是已接受的 skill；源码留存用于复核实验，不代表推荐部署。

英文运行时文件：[manual_global_terminal_bank.json](../src/skill_evolution/configs/manual_global_terminal_bank.json)。只有 1 张 Global 卡，ID 为 `1`；`stages` 沿用原卡的 `["initial", "evidence"]`。`when_to_use` 只说明提供视频的问题回答任务，不增加操作。

`strategy` 逐字保留原 concise temporal_anchor 的最后一句：

> Answer from supported evidence in the requested format.

除此以外，删除原 strategy 的全部句子，包括时间锚点、参考先行/事实传递、同步时间、等价步骤边界、缺失中段/排序、细化锚点及 joint watch 条款；不追加同义解释或新约束。

原卡来自冻结 bank `7c3f0aa4f4b2e3e1d6f0bbf07778a3aa462fcc67f9c7837983abfa4b756d4fcd` 的 Global ID `3`。其既有评估 variant 为 `d6979725424d6612f4941215fea51e87a28bce10eb8438e472bee1ab87ad49e1`。本控制用新单卡 ID `1`，不改写原库或历史结果。

完整中文镜像（仅文档，不提供给 Actor）：

```json
{
  "schema_version": 3,
  "skills": [
    {
      "meta": {
        "id": "1",
        "role": "global",
        "stages": [
          "initial",
          "evidence"
        ]
      },
      "when_to_use": "在回答有关所提供视频的问题时使用。",
      "strategy": "依据有支持的证据，按所要求的格式作答。"
    }
  ]
}
```

使用真实静态注入、`forced card_id=1` 跑相同 Train80；Video 仍为空库，模型、seed、动作预算、评分与其他配置沿用对照。Actor 只接收 strategy，朴素 applicability 与新编号不是本次被测的自然路由机制。

它检验原卡的详细程序正文对既有收益是否必要；长度、语义、上下文均同时改变，**分差不能单独解释为纯长度效应**。若收益仍在，也不能单凭此结果证明通用终答句有稳定语义收益；若消失，也不自动证明原 temporal 程序有效。结果、机制证据和正在进行的补充确认见[阶段结果](skill-exploration-results.md)。

本轮已完成Train80评分；完整简短正文与本删减正文的365题对照在查看其结果前冻结。二者均固定注入，不替代自然整库Cal/Gate接受。
