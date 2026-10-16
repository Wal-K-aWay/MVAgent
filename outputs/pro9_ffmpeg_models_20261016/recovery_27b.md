# 27B失败题补跑

状态（2026-10-16 12:52 UTC）：完整双遍复核通过，14题已开始并行补跑，最后读取4/14成功、0新失败；尚未完成全部补跑与评分。

原目录`devbox/pro9_ffmpeg_27b_20261016`的330条记录保持不变，新目录为`devbox/pro9_ffmpeg_27b_retry_20261016`。316条成功记录只建立只读用途的引用；14道失败题从冻结问题与原始视频完整重跑，不从中间轨迹续接。输入题面、Prompt、schema、输出预算、seed0/temperature0/BF16和固定推理profile不变。

## 修复范围

仅在隔离实验分支的`src/mvagent/utils/media.py`增加最小帧数短片段的边界可解码检查。普通片段仍FFmpeg stream copy；若这种短片的首尾帧不可解码，改用FFmpeg按原时间区间精确重编码。不用OpenCV逐帧裁剪、不改模型后端、采样参数或Agent策略；OpenCV只用于既有元数据和两次边界读取。

实际MOC565的[2.5,3.5]秒窗口：旧输出声明11帧、最后一帧不可解码；修复后为10帧、首尾可解码。CPU复核修复产物两次SHA相同、普通[0,10]秒片段新旧SHA相同，原有普通/补帧裁剪及schema桥检查通过。GPU启动入口的真实vLLM解码器也已验证采样由1帧变2帧。

这是对本次观测到故障的最小修复，不是所有视频解码问题的通用证明。旧316份结果由原源码产生，只有14份新结果使用修复，汇总须标明这层来源，不将其描述为330题全新协议重测。

## 执行与验证

- `PRO_MODEL=27B PRO_RUN_ROOT=/runs/devbox/pro9_ffmpeg_27b_retry_20261016`。
- 新jobs只是原330题的重排，让14个失败任务分布到8卡；保留原selection，不重抽题。
- MOC565与原正常锚点CV34各两遍已通过：42响应/21配对，输入hash、完整token和除时间外完整结果均一致。两遍MOC565均B，分别181.8/176.8秒，18调用；CV34均A、各3调用。之后只补14题，其余316跳过。
- 14题全部成功后，四组各30道CCQA统一Judge；GPU释放后，用Modal CPU汇总330题。
- 保留原330文件SHA；收尾再次核验原件不变、316条引用不变、14条新记录成功，并对正常锚点比较新旧token。
- 已观测到的服务故障不通过随机重试选择答案；没有更换seed或放宽答案格式。

## 运行身份

源码冻结`fb23d1075d22e74ebc42c52b470cb860081e7d9e`，实际文件SHA见新目录`code_identity.json`。源文件清单仍105，只有media.py相对原实验改变。
Sandbox `sb-r7uGenacmq2vj4bh4jGnmx`，DEVBOX_NAME `mvagent-pro9-ffmpeg-27b-retry-20261016`，jobtag `pro9_ffmpeg_27b_retry_20261016_pipeline`。实际8个单卡worker的execution与weights_manifest均与原27B服务一致，prefix/MM缓存关闭；12:50:01进入正式inference。

后台收尾由modal-gpu上的`finish_retry.py`执行，读取持久化阶段文件，不对推理服务做同步轮询；完成Judge后释放本轮GPU，随后调用CPU评分与审计。日志`~/wxu-evolve-agent/devbox/pro9_ffmpeg_27b_retry_finish_20261016.log`。首版状态读取未捕获SDK包装后的FileNotFoundError，已按实际异常修正并通过缺失/正常/损坏JSON自检；没有重新提交GPU或Actor。

本轮不替换共享主工作区的正式src/Prompt/配置。此前27B失败结果和原分数仍保留，补跑结果另报。
