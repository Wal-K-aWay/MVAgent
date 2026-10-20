# MVAgent 35B最后一题恢复（2026-10-20）

旧分片在MOC268的view_B、[2.5,3.5]秒、2FPS裁剪中，以stream-copy产生标称11帧的片段，实际均匀采样只读到1帧。
Qwen3VLProcessor要求至少2帧，因此8302副本失败；固定副本协议阻止跨卡接续，本题失败。
整批处理完1910题后控制器按失败退出，原始成功1909题保留，82条CCQA的后续Judge及全量汇总没有执行。

采用已在MOC552验收的media.py：检测实际可读采样不足2帧时才转码；模型、Prompt、预算与BF16/H100/seed0等数值配置不变。
旧分片沿用a0150f7冻结源，原本未包含这项后续修复。此次新建runs `devbox/frozen_full_35b_finish_20261020`，
引用已完成shard0和旧1的9B/27B；逐SHA检查、继承1909份35B成功记录，仅重新推理MOC268整题。
原失败与所有成功原件保留。唯一8H100池先补题再换Judge，完成82条评分后释放GPU，由CPU汇总三模型。

CPU准备已完成（ap-2RbyxmOcxdWQNJFM2ayvBV，rc0）：compileall、分片/评分self-check与真实MOC268回归通过，坏裁剪采样1帧→修复后至少2帧，重复生成SHA一致。1909份成功轨迹已核对SHA/token/cache/sticky并只读继承。接下来执行唯一8H100补题与Judge；尚未产生新的GPU结果。没有修改共享运行源码、main或其他正在进行的实验。
