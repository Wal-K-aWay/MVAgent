# AgentCVR：CrossVid Lite2500

用户2026-10-17授权运行同一份CrossVid Lite2500。CPU合同检查和完整compileall已通过，正式8H100任务已提交，尚无完整推理成绩；实际阶段以远端progress为准。

- 唯一主执行者：当前Codex会话；独立Luna每15分钟只读检查，会话外不承诺持续巡检。
- 分支`codex/agentcvr-20261016`，初始实现提交`6d2a7cf`；与此前CVBench/MVU结果分别保存，不重测这两套数据。
- runs：`devbox/agentcvr_crossvid_20261017_r2/`；仅原始结果/评分/源码快照写此新目录。
- Modal app：`wxu-sglang-baseline-gpu-test-agentcvr-crossvid-20261017`。只经modal-gpu入口提交；先CPU准备，再单个8×H100任务中冒烟、全量推理和CCQA Judge，结束释放。
- devbox独立代码`~/wxu-evolve-agent/agentcvr_crossvid_repo`，入口`~/wxu-evolve-agent/agentcvr_crossvid_control/agentcvr_crossvid_modal.py`；不替换其他任务代码或服务。

## 固定范围与模型

选择清单取已完成E2E的`devbox/e2e_full_20261012/9B/selection.json`中crossvid字段，2500题不重新抽样。
BU232、CC218、CCQA239、FSA616、MOC155、MSR163、NC334、PEA261、PI100、PSS182。
Actor为作者公开Qwen3-8B RL（revision0ca8538758507589a5bada39d2377847649adc09），视觉Qwen3-VL-8B-Thinking，Whisper large-v3。
沿用上一批验收部署：8×H100、每卡Master+Vision独立TP1，temperature0.5、seed0、输出8192、20轮；Master预留0.29、Vision0.50，prefix/MM processor cache关闭。
模型身份、参数与论文存在已披露差异，称为作者公开版本评测；[详细设置与训练来源](../agentcvr_20261016/official_settings_audit.md)。

## 官方行为与适配边界

十类任务各使用未修改的`master_<TASK>.prompt`；题目/选项走作者各任务入口形式，使用公开执行器、视觉/音频工具。
仅映射公开数据schema与实际存储路径；标签单独保存，不供推理读取。

- 普通视频/PEA保持原clip_begin/clip_end与相对时间；PI将开头/结尾作为两个独立context。
- PSS按作者实现对每段取首start至末end的连续包络（包含段内空隙），按数值片段编号排序。不是本项目E2E按不连续区间拼合的预处理，需披露。
- FSA保持作者原始query，包括参考区间及视频名称；不擅自删句改变方法。
- MOC/MSR当前公开QA直接包含vid与有序objects，而作者入口期望class及外部samples文件。将这两个字段映射为相同的class_id/有序sample_items，再直接执行作者prepare_metadata，沿用image_folder、画框与目标命名流程。
- 作者UAV prompt示例使用start_time/end_time，但执行器要求start_frame/end_frame；init_agent_state也忽略formatted_query/bbox_info。保留并记录这些原版行为，不能把自动修正后的系统冒充原版。CPU合同检查只证明输入映射，实际工具行为在冒烟/全量轨迹中观察。
- 普通视频最长边360沿用原实现；UAV分支按原实现直接读取图片并画框/JPEG，不擅自套用普通视频的缩放。

## 评分与持久化

主分复用作者逐任务答案解析，再按CrossVid指标计算：闭式题准确率、FSA时间IoU、CCQA按评分点加权；最终十类等权macro。
另保留原始答案直接按benchmark严格格式评分的诊断值，便于区分原方法后处理与原始输出格式。
CCQA复用本项目固定Qwen3-30B-A3B-Instruct-2507及官方Judge prompt，与既有E2E可比；失败报错，不填0。
正常未终答记0，基础设施失败单列；未满2500有效评分时不报告完整macro。

每题先写raw再写records，保留完整响应token、输入hash、工具轨迹、原始答案（含结构化答案）。
manifest冻结源码、模型/配置、官方输入清单与prompt/QA哈希；smoke成功结果复用到全量。
全量后执行逐题SHA、输入/题面/原System、请求配置、token计数审计。

时间预算：接入/CPU准备约1小时；8H100推理暂估12–18小时、保守24小时，不含排队。实际吞吐出来后更新；22小时执行段保留结果并沿用冻结源码续跑。

## 启动记录

- 生产冻结`d8c323254210cadbc57858961054ec514aaf17f1`，已推送并核对远端SHA。
- CPU最终app `ap-qJVJlyK9xrnAF37CHheqH2`正常完成：2500题覆盖、未改prompt/原生query、标签隔离、clip/UAV、原答案解析和CCQA汇总回归通过，完整compileall通过。旧CV/MVU2821合同回归在首个CPU app已通过；其后仅CrossVid模块修改。
- 初始CPU因漏传import_root失败，修复后检查通过；GPU提交前发现并修复CCQA汇总同名字段冲突。旧`devbox/agentcvr_crossvid_20261017`仅prepared/0题，保留作为准备历史；正式结果仅r2。
- GPU app `ap-SohrpBru66BAiWpCdwLXat`，唯一devbox控制器PID3224707，日志`~/wxu-evolve-agent/agentcvr_crossvid_control/agentcvr-crossvid-20261017.log`。
- 依次冒烟FSA1004、MOC431、CCQA236；保留成功结果，随后启动8路固定分片，不另跑重复验收矩阵。全量后切换239题CCQA评分、审计、写最终分数并结束GPU。
