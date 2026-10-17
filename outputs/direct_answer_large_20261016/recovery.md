# 直接回答扩样：只补失败与缺失题

## 已完成（2026-10-17 04:52 UTC）

恢复目标全部完成：35B694/694、27B1/1，原3805条成功保留，最终三模型各1500题、共4500条有效，0缺失/最终工程失败。35B04:34:40完成新增推理，27B TR1493于04:38:50回答B、官方分1、62.63秒。原失败文件与所有原3806份结果SHA在最终汇总中核对不变。

27B故障题完整重复一次，与旧CV0锚点比较共24次配对调用：输入哈希、完整token及完整结果均0差异、0模型错误；`verification/summary.json`确认old_anchor_unchanged与whole_repaired_trajectory_repeated均true。CPU媒体修复验收与真实GPU路径均通过，未扩展成全题双遍复测。

28条新增CCQA Judge成功、0failed_ids，加原122条共150条评分齐备。GPU04:45:31被host控制器释放，CPU完整汇总04:52:38写completed，host04:52:46正常结束；从driver02:08:09起约2小时45分钟。08:22 UTC独立复读：Sandbox poll137、watcher PID和state文件均不存在，无本任务后台运行。此次仅查状态和整理报告，没有新GPU或新推理。

最终同题E2E比较见[主报告最终表](README.md)：9B CV/MVU/Cross为61.57/49.41/34.89%，27B70.01/60.23/46.62%，35B66.16/51.02/37.86%。九格点估计均高于E2E，但CV三格及9B/35B Cross区间跨零；35B未完成子集的+10.52pp Cross不能沿用到完整面板。空答案/仅右花括号均0，格式失败28/13/38，仍有模型输出质量问题。

最终权威文件为恢复root的`analysis/summary.json`、各模型`*_paired.json`与`*_summary.json`，包含新增题、旧独立回答器、task明细及未校正配对区间。只27B单题使用修复，其余原样使用各自冻结源，原始尝试与负结果保留。以下为准备和启动时的历史记录。

## 恢复范围与历史记录

2026-10-17用户授权补跑。原始实验`/runs/devbox/direct_answer_large_20261016`保留；恢复目录为`/runs/devbox/direct_answer_large_recovery_20261017`。固定原selection，不重新抽题、不重跑3805条成功结果；仅补35B-A3B的694条缺失题和27B的`mvu_eval:TR:1493`。目标是最终三模型各1500条有效结果及完整评分。

35B继续使用原`frozen_repo`；27B只更改`src/mvagent/agents/video_agent/agent.py`的整段原视频快捷路径检查。原视频5帧/30fps约0.167秒，展示时长舍入为0.17秒，按11.8fps取样实际只有1帧。新检查使用真实帧数/帧率计算最少采样量，不足两帧时进入现有FFmpeg裁剪/确定性补帧路径。题目、Prompt、展示时长、reason预算、BF16/TP1/C1/seed0/T0、FlashInfer与缓存开关不变。该单题的新视频输入会变化，最终是保留旧成功记录与新恢复记录的组合，不能称整批4500题都使用修复后的媒体代码。

独立8H100、每卡一个模型副本，35B使用8100–8107，27B使用8200–8207，Judge使用8300–8307。分模型端口避免旧池隔离状态阻止新模型注册；身份校验保留。推理只有实际记录全部成功才标记完成；未测/失败不计零。已有CCQA评分保留，只为35B新增的28条CCQA调用固定Qwen3-30B Judge。原失败轨迹和SHA保留，最终离线汇总逐条核对原记录未改变。

媒体缓存放独立Sandbox的`/work`，不占runs的持久文件数；原始轨迹、输入哈希、token、服务日志和身份文件仍存runs。准备时仅清理已停止原实验的513个可再生pyc，保留源码与原始数据；记录清理清单。CPU挂载曾剩约6849个inode，预计本次新结果/源码快照需约两三千，不依赖删除其他实验的文件。

恢复控制器为`recover_direct_answer_large.py`，host管理器为`watch_direct_answer_recovery.py`；唯一提交者操作新命名Sandbox。GPU任务结束或失败即释放，5小时运行上限；成功后自动在Modal CPU进行完整同题比较。过程若失败，保留已完成题目和实际错误，不自动将缺失题标成成功。

验证包含：完整compileall、13项直接回答接口测试、恢复选择/官方聚合自检、真实短视频的vLLM CPU采样探针。27B实际整题成功后，再完整重跑该题一次，核对逐调用输入和token以及整条轨迹；另选一个旧成功CV题作不受影响锚点，与保存的请求/token比较。验证输出原样留runs，不将这些额外调用计入1500题分数。

首次CPU `ap-83vMomVxuSjyYf1PcmTlhB` 的compileall、13项接口检查和准备通过，但媒体验证脚本被历史辅助模块的sys.path覆盖而载入旧VideoAgent，探针失败，整体rc1。已修正验证脚本的导入顺序并加入被测源文件路径断言；首次准备原件保存为`direct_answer_large_recovery_20261017_prepare_initial`，没有GPU推理记录。源码/控制器已提交725bf99、03bb6c7、6501fbe；实际后续启动和验收见下方更新。

原始部分成绩与中断原因见[已有结果](README.md)。后续最终分数以恢复目录`analysis/summary.json`为准；准备完成或提交成功不等于补跑完成。

## 启动更新

第二次CPU `ap-xN9UDQJUKzHCGfkX9KM38k`整体rc0，实际源文件路径断言通过；短视频vLLM采样1→2，重复FFmpeg补帧SHA一致，普通完整视频路径不变。结果存`probe/cpu_check.json`；补帧视频SHA256为`8acca617f65b7d5dda86ffbb16ec9408380ec2bc6089b2b3ec6d7d78d93e8208`。准备快照6501fbe，按manifest记录逐文件SHA。

Sandbox `sb-VSQvjZZgYgGpY3iIy4MB4t`于02:06:35 UTC申请，实际八张NVIDIA H100 80GB HBM3已确认；02:08:09启动恢复driver PID46。devbox名`mvagent-direct-large-recovery-20261017`，host管理器PID2976791，日志`~/wxu-evolve-agent/devbox/watch-direct_answer_large_recovery_20261017.log`。02:09仍加载35B，尚无新题完成；项目app `ap-lluPvOtRg7tYTpbvSVmWFd`近10分钟Traceback为0。该app同时承载其他Sandbox，仅本恢复实例属于本任务。

02:14进入正式推理，八个实际服务manifest与原35B的profile/权重清单完全一致，8个不同H100 UUID、单卡worker 0–7通过，证据`startup_identity.json`。没有沿用前轮失败的服务池，也未关闭身份检查。

02:16:53首批8条新增有效轨迹已完成，0顶层/模型调用错误；覆盖CV、MVU、Cross，含开放CCQA。30次响应检查实际token数量、请求与prompt哈希、cached_tokens=0及整题同一worker通过，证据`startup_records.json`。例：CV934答A、MVU Comparison1198答C、FSA1804答`230,275`、CCQA498提交完整自然语言比较。这里只证明启动与调用链正常，不把8条当最终准确率或新的双遍一致性结论。

原先35B在694条新增题上的平均整题耗时91.37秒，按8卡理想折算另694题约2.20小时；加负载波动、27B加载/整题复核、Judge和CPU汇总，当前估计还需约3小时（约2.5–3.5小时）。这不是完成时限保证；硬上限和失败会保留真实状态。

本轮按用户既有“正常运行后退出”要求结束会话；会话内独立检查代理做末次只读检查后停止，不宣称会话外仍有代理巡检。持续运行的是host后台控制器。27B实际GPU整题/重复性复核、28条新增Judge及4500条最终汇总仍待完成，不提前宣称整批成功。主工作区正式src未改；隔离恢复的修复、驱动和MD报告已在`codex/direct-answer-large-20261016`备份，本地status/benchmarks/skill/检查笔记不入Git。
