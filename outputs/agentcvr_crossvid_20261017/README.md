# AgentCVR：CrossVid Lite2500

用户2026-10-17授权的CrossVid Lite2500原版运行已结束：北京时间2026-10-18 21:19完成推理/评分与记录审计，21:21完成边界审计。2500题均有记录，2499非顶层工程失败、1工程失败；239 CCQA已评分。边界审计发现182题出现超允许区间的视觉重建帧或音频请求，因此不能称为严格输入边界合规的完整benchmark成绩。GPU已释放；详细结果与限制见文末。

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

## 首批实测（2026-10-17 15:29 UTC）

GPU容器`ta-01M556T5G2ENMVMPKF5AW5KWZR`，实际hardware.txt为8张H100 80GB。
三道冒烟全部正常终答，成功结果保留到正式2500题；尚未形成全量主指标。

| 样本 | 原始回答 | 耗时 | 模型调用 |
|---|---|---:|---:|
| FSA1004 | `[135.14, 143.18]` | 118.49秒 | 6 |
| MOC431 | `A` | 309.98秒 | 8 |
| CCQA236 | 比较两视频菠菜处理、保脆与调味，原始全文在raw中 | 159.06秒 | 7 |

21次模型调用（Master14/Vision7）逐次核对原System、题面/选项、T0.5/seed0/8192、完整输入/输出token长度及逐题SHA通过，0 HTTP错，1次输出达到上限；最终三题均终答。
工具共8次视觉请求动作、3次音频动作。MOC第一次因time参数返回错误，模型随后自行改frame参数，实际成功18/42/21帧视觉调用，未改上游提示或执行器。

FSA本次实际返回结构化数值数组。原值完整保留；评分时先将非字符串JSON答案序列化，再调用作者的区间解析/正反序处理与IoU。原入口假定字符串，此处是明确的类型适配；严格原始格式得分另外保存，不能把两者混为一谈。
15:29时7/16模型服务就绪，继续自动加载其余副本；这是加载阶段，不是全量已完成。

## 正式全量与输入边界旁路审计（2026-10-17 15:40 UTC）

15:34已进入`phase=inference`，16模型服务全部就绪，8个worker并行；15:40 CPU审计快照已有15份完成记录。
最近主progress快照12/2500有效、0基础设施错、3 CCQA待Judge；这些是运行中快照，不代表最终分数。

检查原版执行器时发现标准视觉工具只加clip_begin，没有强制限制clip_end；PI/PEA/PSS若请求超出片段可能看到题面未提供内容。
PSS连续包络还可能采到原标注不连续区间之间的空隙。按照用户原版运行要求，未热改推理实现；用独立CPU脚本`agentcvr_boundary_audit.py`随轨迹测量。
该脚本依据成功视觉调用的frame mapping及原采样公式重建帧时间（容差一帧），对照官方允许区间；音频仅核对实际请求区间，不做媒体内容复解码。
违规样本单列，原始数据/分数保持，不把“原版能运行”当成“严格benchmark输入边界已验证”。

CPU app `ap-qSho9pZByEysoBYQgpx1Cv`完成旁路检查与自检：15份记录中已有1道相关片段题，3次视觉目标、96帧重建，0越界；样本很少，不能外推到全部2500。
核查JSON在正式root的`boundary_audit_partial.json`，独立脚本SHA256为`77c0f0ed7800882ed50eef0abc2ca5f4e3239bb7b4d226346b6dc2d00e6761f0`。
后台收尾入口在devbox控制目录：`modal run --env zheng-dev agentcvr_boundary_audit.py --after-pid 3224707`，日志`boundary-after-run.log`。
它等待现有GPU控制器退出，然后执行一次CPU审计；不会申请GPU或重新推理。正式完成写`boundary_audit.json`，若推理失败则保留partial标记。

数据保留在Modal；目前没有新增Lightsail原始结果迁移或GitHub Release数据上传。代码与Markdown报告持续备份，运行配置仍使用冻结d8c3232。

15:41 UTC独立Luna检查：21/2500 valid、0基础设施错误、0未终答，3个CCQA待Judge；BU3/FSA8/MOC1/NC3/PEA2/PSS1/CCQA3，主app仍1个GPU容器正常推理。任务继续，不据早期题型分布报告全量准确率。
后台CPU边界收尾控制器PID3235778/app ap-PhsXTU8TGswM8FGSrKjkED已明确进入等待GPU控制器3224707退出；不会重复提交推理。
本轮独立AI巡检已于15:41末次检查后结束；会话外没有持续AI巡检，远端推理/Judge/CPU收尾控制器继续运行。

## 中断与恢复（2026-10-18）

01:08 UTC主任务和旁路审计日志均记录`user stopped from dashboard`；主progress随后为failed/KeyboardInterrupt。03:18只读核对records共1480：1478 answered、1 no_answer、1 infrastructure_error，剩余1020。scores快照1477条，与records差集的FSA1451/PEA365/NC72均answered。146条CCQA待Judge，最终评分和边界审计未完成。

BU567为模型正常无终答，保留零分；MSR548是视觉请求261571 token超过部署131072上下文导致的工程失败，保留原始记录，不通过缩帧/改提示或同配置重复尝试掩盖。完整2500有效macro仍不可声称。

用户确认恢复后，03:25 UTC经modal-gpu重新提交原控制入口，仅`--mode run`，没有重新prepare或同步覆盖源码：

- GPU app `ap-lYGDWgPZ56UvhmBabqlGav`，容器`ta-01M56GNMART3CT6RN6Y6C5WW6R`；devbox主控制器PID3475555。
- 日志`~/wxu-evolve-agent/agentcvr_crossvid_control/agentcvr-crossvid-resume-20261018.log`。
- 原r2结果目录、冻结源码d8c3232、8H100与原模型配置不变；worker按既有raw文件跳过已处理题，缺record则从raw恢复。
- CPU边界审计控制器PID3475909/app `ap-EHh0Bn87VA0b3x9wOmF6QZ`；等待主控制器退出，日志`boundary-after-resume-20261018.log`，不额外启动GPU。
- 预计恢复后约8–10小时（含启动、剩余推理和评分收尾，依赖实际吞吐）。03:26容器实查8张H100 80GB，phase=starting_models、ready_servers=0；尚无新增测量，不能把加载阶段写成推理完成。

本轮仅恢复既有任务及更新状态，无模型/推理代码变更，不重复已通过的验收矩阵。原始结果仍仅在Modal。

## 完成核验（2026-10-18 13:30 UTC）

原r2的progress=completed，2500/2500 records；2498 answered、1 no_answer(BU567)、1 infrastructure_error(MSR548)。239/239 CCQA已评分，pending_judge=0。推理/评分收尾北京时间21:19:20，CPU边界审计21:21:09。GPU app于13:19:28 UTC停止、CPU审计app于13:21:12停止，均0任务；两个host控制器已退出，无本实验后台GPU。

| 任务 | 已评分/应测 | 保存分数（%） |
|---|---:|---:|
| BU | 232/232 | 35.34 |
| CC | 218/218 | 80.28 |
| CCQA | 239/239 | 38.51 |
| FSA | 616/616 | 22.30 |
| MOC | 155/155 | 37.42 |
| MSR | 162/163 | 36.42 |
| NC | 334/334 | 45.81 |
| PEA | 261/261 | 32.18 |
| PI | 100/100 | 28.00 |
| PSS | 182/182 | 15.93 |

上述现有可评分样本的十类均值为37.2194%，仅供诊断：MSR缺1个工程失败样本，且包含下述越界读取样本，不能作为严格合规2500题官方总分。正式accuracy字段保留null，未把失败补零或悄悄剔除越界题后称官方成绩。

记录审计覆盖2500题、17441模型请求，原始SHA/输入hash/任务prompt/参数/token长度断言通过；统计到449次length结束及837次HTTP/请求异常。这里passed只表示这些记录与配置断言通过，绝不等于0请求失败或2500条可靠完整推理。837次请求异常的题目分布与原因尚未进一步拆分，不能只凭顶层仅1工程失败忽略它们。

边界审计覆盖543道PI/PEA/PSS题，3103个视觉目标、69647个重建采样帧；438个目标中1837帧越出允许区间，440次音频请求中99次越界。去重后共182道题受影响：PEA27、PI30、PSS125；视觉177题、音频64题，二者有重叠。JSON的affected_by_task原字段实际统计违规事件数（34/46/457），不是去重题数，本表按violations.sample_id重新去重。

这是原工具不强制clip_end及PSS连续包络行为的实测影响，不能声称无benchmark输入越界；与训练集是否泄露是不同问题。视觉帧时间由原采样规则重建、容差一帧，音频仅检查有效请求区间，未重新解码内容。原答案和评分保持原样，没有修边界重测。

原始回答、评分/Judge缓存、manifest/冻结源码、final_audit.json及boundary_audit.json均保存在Modal原r2目录。本次未迁入Lightsail或发布新的GitHub Release；仅更新Markdown报告。下一项分析是拆分请求异常与越界影响；如果要严格输入边界评测，需要独立标记修正协议与受影响题目，不能把修正版冒充原版。
