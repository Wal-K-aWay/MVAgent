# 直接回答扩样：只补失败与缺失题

2026-10-17用户授权补跑。原始实验`/runs/devbox/direct_answer_large_20261016`保留；恢复目录为`/runs/devbox/direct_answer_large_recovery_20261017`。固定原selection，不重新抽题、不重跑3805条成功结果；仅补35B-A3B的694条缺失题和27B的`mvu_eval:TR:1493`。目标是最终三模型各1500条有效结果及完整评分。

35B继续使用原`frozen_repo`；27B只更改`src/mvagent/agents/video_agent/agent.py`的整段原视频快捷路径检查。原视频5帧/30fps约0.167秒，展示时长舍入为0.17秒，按11.8fps取样实际只有1帧。新检查使用真实帧数/帧率计算最少采样量，不足两帧时进入现有FFmpeg裁剪/确定性补帧路径。题目、Prompt、展示时长、reason预算、BF16/TP1/C1/seed0/T0、FlashInfer与缓存开关不变。该单题的新视频输入会变化，最终是保留旧成功记录与新恢复记录的组合，不能称整批4500题都使用修复后的媒体代码。

独立8H100、每卡一个模型副本，35B使用8100–8107，27B使用8200–8207，Judge使用8300–8307。分模型端口避免旧池隔离状态阻止新模型注册；身份校验保留。推理只有实际记录全部成功才标记完成；未测/失败不计零。已有CCQA评分保留，只为35B新增的28条CCQA调用固定Qwen3-30B Judge。原失败轨迹和SHA保留，最终离线汇总逐条核对原记录未改变。

媒体缓存放独立Sandbox的`/work`，不占runs的持久文件数；原始轨迹、输入哈希、token、服务日志和身份文件仍存runs。准备时仅清理已停止原实验的513个可再生pyc，保留源码与原始数据；记录清理清单。CPU挂载曾剩约6849个inode，预计本次新结果/源码快照需约两三千，不依赖删除其他实验的文件。

恢复控制器为`recover_direct_answer_large.py`，host管理器为`watch_direct_answer_recovery.py`；唯一提交者操作新命名Sandbox。GPU任务结束或失败即释放，5小时运行上限；成功后自动在Modal CPU进行完整同题比较。过程若失败，保留已完成题目和实际错误，不自动将缺失题标成成功。

验证包含：完整compileall、13项直接回答接口测试、恢复选择/官方聚合自检、真实短视频的vLLM CPU采样探针。27B实际整题成功后，再完整重跑该题一次，核对逐调用输入和token以及整条轨迹；另选一个旧成功CV题作不受影响锚点，与保存的请求/token比较。验证输出原样留runs，不将这些额外调用计入1500题分数。

首次CPU `ap-83vMomVxuSjyYf1PcmTlhB` 的compileall、13项接口检查和准备通过，但媒体验证脚本被历史辅助模块的sys.path覆盖而载入旧VideoAgent，探针失败，整体rc1。已修正验证脚本的导入顺序并加入被测源文件路径断言；首次准备原件保存为`direct_answer_large_recovery_20261017_prepare_initial`，没有GPU推理记录。源码/控制器已提交725bf99、03bb6c7、6501fbe；实际后续启动和验收见下方更新。

原始部分成绩与中断原因见[已有结果](README.md)。后续最终分数以恢复目录`analysis/summary.json`为准；准备完成或提交成功不等于补跑完成。
