# 必要入口

从仓库根目录在计算服务器执行。`scripts/`只保留五个入口，`__init__.py`用于测试导入：

| 入口 | 用途 |
|---|---|
| `prepare_crossvid_data.py` | 下载固定CrossVid版本、从历史补齐BU视频、核验并完成预处理 |
| `prepare_cvbench_mvu_qas.py` | 将已下载的CVBench/MVU标注转换为评测输入并检查媒体引用 |
| `prepare_crossvid_train_cal_gate_split.py` | 必要时新建十任务CrossVid Train/Cal/Gate；不是重建Lite2500 |
| `generate_skills.py` | 不读题目和成绩，一次生成skill库 |
| `evolve_skills.py` | 从空库开始角色轮换反馈优化 |

[服务器手册](../docs/server-runbook.md)给出完整命令，[数据指南](../docs/data-preparation.md)给出下载和成功判据。
批量评测、评分和结果导出直接使用[`eval/agent_eval/`](../eval/agent_eval/README.md)。

CrossVid的续跑、媒体编码、对象标框和协议实现已收归[`eval/data_preparation/`](../eval/data_preparation/README.md)。
一键入口会调用这些实现，不要同时在同一数据目录启动下层命令。
重复的全数据集包装器、历史面板抽样、旧题号池及手动skill维护CLI已删除；历史代码可从Git恢复，不保留兼容入口。

**复现已有评测直接读取[Lite2500冻结清单](../configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json)，不要重新抽样。**
研究面板及格式区别见[split目录](../configs/skill_evolution/splits/README.md)。新划分默认十任务各`8,4,4`、seed `0`，
得到80/40/40；它只排除Lite2500题号、报告来源重叠，不是新的独立Test，也不替代已有80/40/176清单。
