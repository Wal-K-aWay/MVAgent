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

后台控制器PID2983720，DEVBOX_NAME=`mvagent-lenswalk-recovery-35b-20261017`，日志`~/wxu-evolve-agent/devbox/watch-lenswalk_full_35b_recovery_20261017.log`。先执行未完成OR440及工程失败Counting11/NC889，随后剩余未测和其他工程失败；只改变执行顺序，样本清单不变。控制器使用原23小时续跑/结束释放机制。

## GPU续跑已验证

Sandbox `sb-o16sAXluaafjXIWFVcunaU`于02:22:07 UTC创建，driver PID44；02:33:34进入8路真实推理。实际8张H100、8个独立worker、`qwen35-bf16-lenswalk-tools` profile、prefix/MM cache关闭已核验。冻结模型服务与客户端源码保持原样，首批原始归档中的effective_config再次确认5轮、512最长边、180/32/128帧预算、Observer温度0.2、Planner原缺省温度和无额外输出上限。

02:38:57 UTC快照为1429条（1422继承＋7新），新增4个终答、3个未收尾规划，0新基础设施失败。其中首4条完整原始调用审计合计51次模型调用、0 HTTP错误；`startup_verification.json`已从外部Volume SDK复读确认持久化。

| 新结果 | 原始输出/状态 | 推理秒 | 官方逐题分 |
|---|---|---:|---:|
| MVU OR440 | 未收尾规划，仍提出继续比较视频 | 142.14 | 0 |
| CrossVid MOC441 | C，finish | 148.28 | 0 |
| CrossVid CC78 | 未收尾规划，仍提出继续检查 | 199.30 | 0 |
| CrossVid NC16 | D，finish | 77.17 | 0 |

OR440的预处理阻断已解除，模型未交付最终答案仍作为负结果保留。首批不是准确率估计；全量推理与CCQA Judge仍在后台继续。Counting11旧日志确认20图视觉请求超过服务600秒并使副本退出，属于原等待上限触发；本轮按原设置重试，未改提示或增加输出/时间预算。02:38:57该题仍在推理，NC889仍在长媒体准备，不能声称它们已经补测成功。

会话内Luna检查已停止；只有远端控制器继续常驻，未承诺会话外独立代理巡检。

本次仅清理17882个可重新生成的`.pyc`和空`__pycache__`目录，共201313150字节，结果卷空余文件名额从约6697升至28718；未删除源码、原始结果、媒体或权重。两份删除清单位于runs根`devbox/lenswalk_recovery_pyc_cleanup[_extra]_20261017.json`。共享卷未来余量会随其他任务变化。

首轮恢复使用已冻结的5c99eb7入口。原进度和配置SHA、逐题继承SHA与待处理清单保存在`recovery_manifest.json`，原始数据只留Modal runs volume。

## 08:24 UTC后续检查与媒体补测队列

主批次新增609条结果（累计2031/5321），最近一小时99题、两小时205题。新结果包含357终答、199未收尾规划、51空答案和2个工程失败。NC889整段41468帧已通过严格像素/尺寸/时间校验，准备1882.85秒、推理426.40秒，模型未终答照常保留。Counting11重试仍触发600秒服务超时，625.33秒结束；不第三次重复该模型失败。

新增媒体失败NC851发生在第21323帧、870.168041秒：其YUV像素不变，但从BT.709片段切换到未标注色彩的片段时，解码器沿用前一段的色彩状态，RGB改变。新补丁为未标注YUV显式写出原本的默认矩阵/范围，保留原RGB，而非放宽校验。8种合成组合均通过，NC851两个真实来源的102帧RGB/尺寸/PTS逐帧一致；CPU app `ap-1S1gFK1FR2vCBEO0Rlgp15` rc0。

主批次保持原冻结源码继续。后续只补媒体处理失败，保留已有模型结果及HTTP超时；使用单个`inherited_records.json`索引继承结果，避免再复制数千个目录。CPU app `ap-OWLRWc6LYfihE38nHyxy9R`完成继承/筛选/原件不变、阶段门控、官方聚合与完整编译，rc0。

- 补丁快照：`devbox/lenswalk_boundary_fix_20261017/frozen_repo`，commit `48673c1603aa0940131ae58e0b30731019beb661`；driver SHA `2578d49cd45a481fc751ceb0de215d0406a57b719ca68ccf87c20ea7602a3891`。
- 排队控制器：modal-gpu PID3098699，`watch-lenswalk_full_35b_media_final_20261017.log`；脚本SHA `a721cf2a3e4b4bebc0b83dba2d3034c73013b5a742bbedbce16c1c21a7df5eb0`，源码副本在补丁目录`lifecycle_controller.py`。
- 后续结果：`devbox/lenswalk_full_35b_media_final_20261017`，DEVBOX_NAME=`mvagent-lenswalk-media-final-35b-20261017`。
- 08:49实际日志为`waiting_primary`，主批次2081题/inference；尚未为后续队列申请GPU。主批次推理和Judge结束后，CPU冻结继承表，再由原生命周期管理器启动媒体补测、重新汇总并释放GPU。主批次若failed/interrupted则停止排队，不盲目重复提交。

这次验证覆盖了实际失败边界的短片段，NC851完整补测尚未发生；模型、生成预算、帧数、图像限制和超时保持原配置。

## 09:19 UTC状态与存储维护

主批次2140/5321（CV430/997、MVU719/1824、CrossVid991/2500），包含1296终答、670未收尾、172空答案和2个工程失败。主控制器2983720与后续控制器3098699均存活；后续仍等待主批次完成，没有新增GPU。按此前一小时约99题估算，剩余推理约32小时，含长媒体、评分和补测预留1.5–2天；不是完成承诺或最终准确率。

结果卷文件数量接近500000上限。CPU app `ap-wnXVmPiZUC49wQJwsoLr7O`正在将以下退役方法的历史散文件转存为无压缩tar：`external_vam65_20261015/vam`、`external_methods_20261014/vam_remaining`、`meta_rest_run`、`meta_early_run`。归档目标`devbox/lenswalk_storage_relief_20261017`；源码`989ca93`。文件内容、权限及符号/硬链接经校验，原树二次核对未变，归档和清单commit后才移除散文件。当前LensWalk/RSI媒体缓存引用检查已通过，共享媒体和原始评测结论保留。

归档单测已通过。09:23从外部Volume SDK复读确认首份VAM归档完成：11041文件/11237条目、4811489280字节，SHA256 `a35a06b1f739f68f9a97f9d1a4b5aa3503e39e19b5f6e7fde1efd23c62fe2b62`，manifest为`archived_and_loose_files_removed`且原散文件树不存在。其余三目录继续处理，不能称全部完成；最终以目标目录`summary.json`及四份清单为准。任务内`progress.json`记录当前目录，CPU任务上限3小时，失败时保留未验证的原散文件，不盲目覆盖已有归档或重新删除。首次调用因子进程SDK路径缺失，在归档前退出；当前调用显式加入`/pkg`，未安装新依赖。

09:21独立末次检查为2147/5321、1300终答、673未收尾、172空答案、2工程失败；8个worker仍在处理，媒体补测队列等待中。会话内检查代理已停止，远端主控制器、补测队列和CPU归档继续运行；不宣称会话外仍有独立代理巡检。
