# Qwen3.5-35B-A3B 三 Benchmark 端到端结果

## 测试配置

| 配置项 | 值 |
|---|---|
| 模型 | Qwen3.5-35B-A3B |
| 推理框架 | 本地 vLLM，OpenAI-compatible API |
| 每题总帧数上限 | 512 |
| 图像最长边上限 | 720 |
| CrossVid M.Avg 解析 | MSR、MOC 均抽取模型回答中的最终选项 |
| CCQA Judge | DeepSeek-v4-flash，官方 Coverage/Correctness Prompt |

## 总览

| Benchmark | 主指标 | 分数（%） | 覆盖 |
|---|---|---:|---:|
| CVBench | Overall micro accuracy | 63.49 | 997/1000 |
| MVU-Eval | 官方首字符 Overall accuracy | 51.26 | 1824/1824 |
| CrossVid | O.Avg，M.Avg 使用最终选项 | 34.60 | 各 task 见下表 |

## CVBench

类别分数为论文任务分组内的 micro accuracy，Overall 为全体已完成样例的官方 micro accuracy。

| Object Association | Event Association | Complex Reasoning | Overall | 正确数 | 覆盖 |
|---:|---:|---:|---:|---:|---:|
| 66.53 | 61.89 | 63.06 | 63.49 | 633 | 997/1000 |

## MVU-Eval

| Overall | Comparison | Counting | ICL | KIR | OR | RAG | SU | TR | 覆盖 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 51.26 | 80.00 | 51.98 | 20.73 | 46.98 | 42.86 | 51.92 | 52.51 | 58.71 | 1824/1824 |

## CrossVid

| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（最终选项） | CCQA |
|---:|---:|---:|---:|---:|---:|
| 512 | 34.60 | 41.18 | 31.06 | 31.06 | 25.97 |

| Task | BU | NC | CC | PEA | PI | FSA | PSS | MSR（最终选项） | MOC（最终选项） | CCQA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 分数（%） | 29.60 | 38.82 | 67.55 | 28.75 | 84.46 | 4.04 | 4.67 | 26.26 | 35.87 | 25.97 |
| 有效样例 | 848 | 1221 | 795 | 953 | 251 | 2246 | 664 | 594 | 566 | 871 |

O.Avg 是十个 task 分数的非加权宏平均；C.Avg 为 BU、NC、CC、PEA 的宏平均；T.Avg 为 PI、FSA、PSS 的宏平均；M.Avg 为最终选项解析后的 MSR、MOC 宏平均。最终选项解析将原严格 M.Avg 的 13.44 提高到 31.06，并将 O.Avg 从 31.07 修正为 34.60。

## 数据完整性说明

- CVBench 的 3 条缺失来自损坏样例，不计入 997 条有效样例的分母。
- CrossVid 的 CC、FSA、CCQA 分别缺少 3、2、1 条损坏样例。
- MVU-Eval 使用官方首字符解析；CrossVid 仅 MSR、MOC 按本次约定改用最终选项抽取。

