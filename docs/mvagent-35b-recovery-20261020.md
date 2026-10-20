# MVAgent 35B恢复与全量评测完成（2026-10-20）

截至08:16:53 UTC，35B的5321题推理及239条CCQA评分全部齐全，缺失0、工程失败0。
本次只新推理一题、补做82条Judge；恢复使用的8张H100已于08:10:22释放。

| Benchmark | 有效题数 | MVAgent 35B | 同题E2E |
|---|---:|---:|---:|
| CVBench | 997 | 67.50% | 64.49% |
| MVU-Eval | 1824 | 54.28% | 36.62% |
| CrossVid Lite，十任务宏平均 | 2500 | 41.27% | 32.24% |

CVBench/MVU按题平均，CrossVid十任务等权、CCQA按评分点加权；MVU E2E采用官方指令移后版本。
包含1500条复用开发题和3821条补测，不能称为独立Test。
全量35B仍有121条最终答案格式偏差，模型内部有496次结构解析偏差、438次修复事件；
这些与工程失败分开统计，不更改原答案或将它们剔除。

旧分片在MOC268的view_B、[2.5,3.5]秒、2FPS裁剪中，以stream-copy产生标称11帧的片段，实际均匀采样只读到1帧。
Qwen3VLProcessor要求至少2帧，因此8302副本失败；固定副本协议阻止跨卡接续，本题失败。
整批处理完1910题后控制器按失败退出，原始成功1909题保留，82条CCQA的后续Judge及全量汇总没有执行。

采用已在MOC552验收的media.py：检测实际可读采样不足2帧时才转码；模型、Prompt、预算与BF16/H100/seed0等数值配置不变。
旧分片沿用a0150f7冻结源，原本未包含这项后续修复。此次新建runs `devbox/frozen_full_35b_finish_20261020`，
引用已完成shard0和旧1的9B/27B；逐SHA检查、继承1909份35B成功记录，仅重新推理MOC268整题。
原失败与所有成功原件保留。唯一8H100池先补题再换Judge，完成82条评分后释放GPU，由CPU汇总三模型。

CPU准备完成（ap-2RbyxmOcxdWQNJFM2ayvBV，rc0）：compileall、分片/评分self-check与真实MOC268回归通过，坏裁剪采样1帧→修复后至少2帧，重复生成SHA一致。1909份成功轨迹已核对SHA/token/cache/sticky并只读继承。没有修改共享运行源码、main或其他正在进行的实验。

08:04 UTC实际GPU补题完成：MOC268返回B，官方闭式得分1.0，耗时456.75秒；13次模型响应、0模型错误，保留2次可恢复结构输出偏差。关键view_B [2.5,3.5]片段实用decode_repair_transcode，原错误未再出现。该分片1910/1910推理齐、0工程失败，随后执行82条开放题Judge。运行代码始终冻结358120f；新的MD提交不改变运行源。

08:09:17剩余82条Judge成功、failed_ids为空；08:10:22唯一GPU池已释放（poll0）。首轮CPU汇总在新增保留SHA检查处因传入字符串而非Path停止，修正路径类型后仅重跑CPU汇总，不重推理/Judge。运行源仍358120f，分析脚本哈希另记在summary。

最终CPU任务ap-Pxag1g90i1xO9Ds9yvDNUP返回rc0，三模型各5321有效、missing/errors均为空，根progress为completed。
1909份继承成功记录和旧失败记录的SHA256再次核验不变。239条CCQA由旧面板50条、已完成shard0的107条及本次82条组成。
分析源提交cca7420；脚本SHA256为`b58d4a20bae5330ce80ff29efe008caa281e5254a3c99db62af8dad05608235e`。
最终证据位于runs volume的`devbox/frozen_full_35b_finish_20261020/analysis/`：
`summary.json`、`35B-A3B_paired.json`、`recovery_smoke.json`，并由根目录的manifest/inheritance关联冻结源码及原件。

额外CPU核对ap-c2vZu0MJUHNUFhX8Ii7RDu确认三模型全部239条CCQA的评分点数与数据集一致。
附带重汇总的27B中，CCQA608在当前来源的分数为1，而已发布包保留2/3，因此其CrossVid宏平均为48.11391%，与发布版48.10070%相差0.01321个百分点。
这是现存评分来源差异，本次未重新推理或Judge 27B，也未改写其发布结果；27B对外仍引用原已核验包。35B上表使用本次完整的239条评分。

本恢复阶段未重跑全矩阵一致性验证；完整结果、旧失败和冻结环境仍保存在Modal。
随后用户授权公开发布35B答案与文本轨迹，已追加至原MVAgent Release，见[发布与下载记录](mvagent-35b-release-20261020.md)。
恢复主控及独立检查均已结束，其他在途实验未改动。
