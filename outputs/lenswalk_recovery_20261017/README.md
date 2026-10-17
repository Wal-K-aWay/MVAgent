# LensWalk 35B 剩余题恢复

原批次 `devbox/lenswalk_full_35b_20261016` 在1440/5321题后，因拼接末帧时长相差0.033367秒触发断言而退出。恢复仅继承1422个没有基础设施故障的原始模型结果，重跑18个基础设施失败及3881个未完成题，共3899题；模型空答案、未收尾规划等负结果不重新抽样或重跑。

新结果目录为 `devbox/lenswalk_full_35b_recovery_20261017`，02:20 UTC已完成初始化。旧结果、冻结源码、失败媒体保持原样。新目录复制逐题记录、引用原始归档和已完成媒体；之后CCQA评分只写新目录。题目清单、上游方法/模型/提示/抽帧/生成参数及600秒请求、1800秒整题等待保持原批次配置。

修复范围：

- FFmpeg拼接在不同FPS片段交界处可能把最后一帧的显示时长改为首段FPS；仅以原视频片段总时长修正末帧duration，保持所有帧PTS、包数、编码内容，并继续严格校验。
- PyAV忽略非UTF-8描述性metadata中的非法字符，不改变视频码流。
- 无损H.264编码明确保留色彩空间/范围/原色/传递函数。BWC-6原YUV像素不变，但旧流程丢失BT.709信息导致RGB变化。
- 无损编码用ultrafast与本地临时磁盘降低CPU和网络小写入成本；保留qp=0、原尺寸、原帧时间和完整RGB逐帧校验。
- 媒体时间校验报普通数据错误并记录在单题，模型身份/token审计断言仍会停止整批。准备与推理分别计时；新原始轨迹归档使用未压缩tar并逐文件核验。

修复代码已通过7类编码/尺寸/VFR/预滚/色彩/坏metadata拼接回归，以及缓存题面隔离、原始归档字节、六条历史真实LensWalk输出的worker/token审计。真实OR440修复后时长56.009999秒，全部1090帧PTS和RGB逐帧完全一致；BWC-6短片保留色彩信息后首帧RGB哈希与原视频一致。已有正常结果不产生新的模型推理。

CPU诊断`ap-BT6BxvTNa13XsIOcNsrzDp` rc0。首CPU回归`ap-zJcnF9VgW32WshbLgYpg8A`在上述检查通过后，因评分测试命令漏传目录而rc1；后续`ap-57DPdgjyS3YoylUkJnvCML`补齐正确评分调用、继承回归、完整编译和实际初始化，rc0。官方均分/十任务macro/CCQA评分点权重/工程失败分母自检通过；OR440的实际输入媒体已准备。

生产冻结提交`5c99eb7ea68050acb6f4c0b155bc7a4bf1ef7d26`，driver SHA `288d4be8bc66346494c1440df4c88499886d2a334bbe74e5b5d1b8d702573d9e`。题目清单SHA仍为`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`；与旧源比较，运行实现只变`prepare.py`与`lenswalk_full.py`，另有测试文件和恢复入口。LensWalk客户端/上游、模型服务/数值设置、样本与参考答案均沿用旧快照。

后台控制器PID2983720，DEVBOX_NAME=`mvagent-lenswalk-recovery-35b-20261017`，日志`~/wxu-evolve-agent/devbox/watch-lenswalk_full_35b_recovery_20261017.log`。先执行未完成OR440及工程失败Counting11/NC889，随后剩余未测和其他工程失败；只改变执行顺序，样本清单不变。控制器使用原23小时续跑/结束释放机制；新GPU推理的实际启动验证尚待记录。

本次仅清理17882个可重新生成的`.pyc`和空`__pycache__`目录，共201313150字节，结果卷空余文件名额从约6697升至28718；未删除源码、原始结果、媒体或权重。两份删除清单位于runs根`devbox/lenswalk_recovery_pyc_cleanup[_extra]_20261017.json`。共享卷未来余量会随其他任务变化。

恢复入口：`eval/external_methods/recover_lenswalk.py --previous OLD --output NEW`，随后从NEW冻结的`lenswalk_full.py`继续。原进度和配置SHA、逐题继承SHA与待处理清单保存在`recovery_manifest.json`，原始数据只留Modal runs volume。
