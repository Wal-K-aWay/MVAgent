# 结构化 Train 反馈：字段与中文镜像

对应实现：[infra/feedback.py](../src/skill_evolution/infra/feedback.py)。本模块不调用模型，不新增 System Prompt；以下说明镜像其发给优化器的数据结构。

`format_feedback(example, max_chars)` 接收已经按角色投影、尚未截断的一个 Train 案例，返回可直接 JSON 序列化的字典。它不选择样本、不计算分数、不读取其他角色、GT 或 Cal/Gate，也不改变 Actor/Selector。调用方必须先完成角色公开投影；旧 `trace` 字符串和未知视图字段会报错。

## 输入和输出

输入保留现有 `parent`、`candidate` 或 `candidate_same_local_context`、`candidate_context_changed` 及 `feedback` 契约。没有候选局部视图时，不伪造一份；得分仍是整题反馈，不是 Video 局部正确性标签。

| 输出字段 | 中文含义 |
|---|---|
| `shared` | 两份可见视图完全相同的字段，只列一次，适用于两臂。只有父视图时该字典为空。 |
| `parent` | 父视图中未放入 shared 的字段。 |
| `candidate` / `candidate_same_local_context` | 原候选键名保持不变；只列候选的差异字段。 |
| `visible_views_identical` | 两个完整输入视图是否相同；不代表未提供的内部 token、视觉事实或整题分数相同。 |
| `shared_event_prefixes` | 两臂某事件字段完全相同的连续前缀，仅存一份；不是整个历史相同。 |
| `feedback` / `candidate_context_changed` | 保留调用方原值，不重评分或补造配对。 |

`history`、`actions` 和 `request_feedback` 作为事件序列处理。Global 使用公开渲染器的 `Event N — action` 标记切整块，也识别明确的 `Step N:` 等标题；没有可靠标题的文本按一个完整块处理。Video 的后两者原本就是事件数组。各序列输出：

```json
{
  "event_count": 4,
  "events": [
    {"index": 1, "event": "完整第一事件"},
    {"index": 4, "event": "完整最后事件"}
  ],
  "omitted_ranges": [[2, 3]]
}
```

`index` 是该臂原事件序列中从1开始的位置，不是两臂共同时间轴；同一个 index 不意味着同一局部状态或因果配对。若提取共同前缀，余下两臂仍沿用原序号并独立排序。`event_count` 是当前这个序列段在省略前的事件数；`omitted_ranges` 是被省略的原序号闭区间。文本和嵌套字典作为完整事件保留，不用字符串 diff 拼出新观察，不按后来相似的文本重新对齐。

## 字符预算与保护范围

预算按返回字典的 `json.dumps(..., ensure_ascii=False, indent=2, allow_nan=False)` 字符长度计算，包括结构与省略标记；它不是 token 上限或整个 optimizer 请求上限。调用方把该字典嵌入更深层 JSON 时会增加缩进空白，须与整个请求预算区分。

完整结果能装下时保留全部事件。否则先保护所有非事件字段，包括问题/指令、视频时长、`prior_memory`、终答/报告、选卡结果、请求 `error` 和反馈。**这些字段自身连同省略元数据超过预算时直接报错，不静默切断。**

剩余预算按各事件序列轮流尝试：先末事件，再首事件，再中间事件；已拆出共同前缀时，分支的首事件就是首个可见分歧。仅加入能完整放下的事件；放不下时明确记录省略范围。这个顺序保护近期证据与分歧，但不是已证明最优的事件价值判断，也不能保证每个末事件都能装下。

相同视图只保留 `shared` 一份，即使整题分数不同也不伪造行为变化。任何分数差仍需考虑其他角色、后续过程和 Judge 差异。此表示改动是否改善提案或问答准确率，需要同样本、同模型、同预算的后续对照；结构完整不等于结论正确。

检查入口为 `tests/test_skill_feedback.py`，应在远端 CPU 环境运行；本模块只依赖 Python 标准库。
