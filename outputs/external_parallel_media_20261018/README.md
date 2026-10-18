# 外部方法临时视频预处理恢复8路并发

用户明确要求提高Video-RSI和LensWalk测试效率。07:19 UTC的实测显示，LensWalk八个worker中只有两个推理，六个等待媒体；最近一小时仅处理5题。此前恢复时额外加入的两路预处理信号量让普通视频也排在长视频后，造成GPU空等。

## 改动与范围

分别复制各自正在运行的冻结源码，实际driver只做`threading.Semaphore(2)`→`threading.Semaphore(8)`这一处替换。仍是每方法8个worker，最多8题在途；不增加预取队列、额外GPU或永久视频缓存。原拼接/逐帧校验、题内视频复用、客户端停止后删除临时目录均不变。模型、Prompt、图像设置、token/步骤/时间预算、评分及Judge均保持原样。

新root为`devbox/rsi_full_35b_parallel_media_20261018`与`devbox/lenswalk_full_35b_parallel_media_20261018`。迁入旧temp批次全部已保存record，包括已重试失败、空答案、未收尾和格式问题；不会因调度变更再次重试失败题。只有没有完整record的题继续执行。保留旧目录和原始轨迹，继承文件在复制前后核对SHA；完整但未提交的attempt如存在会先要求恢复，不能悄悄覆盖。

切换准备与验证期间旧任务继续。准备通过后停止各自控制器及其Sandbox，再从新冻结目录恢复；未完成的在途题需重新准备/执行。旧root的`SCHEDULING_STOPPED.json`记录停机原因、Sandbox退出码及时间，不把旧progress残留的inference视作仍在运行。

## 验证与备份

冻结初始化源码`128e5138905b96a2e1b427f7ca8c6110faa0ac14`，分支`codex/external-parallel-media-20261018`，已推送且远端SHA一致。
Modal CPU `ap-JPzaNPMfQBL6rik8Vjmtb8` rc0：两个实际冻结driver仅一个数字不同、八线程同时进入、已重试失败与正常负结果不重跑、旧文件字节不变、完整compileall均通过。没有重跑已通过的全量媒体/模型一致性矩阵。

新运行启动后会沿用原逐卡execution/weights_manifest比较、token/输入哈希与prefix cache审计，首批实际输出计入正式结果。后台控制器仍负责续跑、官方评分、汇总准确率与耗时并释放GPU。

## 当前状态

08:02:41 UTC原RSI/Lens Sandbox均poll137、控制器3514200/3514203退出，两个旧root均保存`SCHEDULING_STOPPED.json`。原模型服务已释放；没有让新旧两套推理同时处理相同题目。

正式初始化CPU `ap-NIjB17RwwG9TOSr5c3gZOp` rc0：RSI继承2715（含17条已复现工程失败）、剩2606；Lens继承3692（含5条已复现工程失败）、剩1629。没有完整但未提交的孤立结果阻塞切换，原记录SHA全部保留。

新后台控制器RSI3587159、Lens3587165已提交，各8H100；DEVBOX_NAME分别`mvagent-rsi-parallel-media-35b-20261018`、`mvagent-lenswalk-parallel-media-35b-20261018`。日志为`watch-{rsi,lenswalk}_full_35b_parallel_media_20261018.log`。

| 方法 | Sandbox | Container | 模型启动时间UTC |
|---|---|---|---|
| Video-RSI | sb-v2by7zEl9SftnW2yv9FIbm | ta-01M570XNYTMCQ7B6TW6KZBVK1S | 08:09:53 |
| LensWalk | sb-TH9BknFkqijvDBGu3iuwPG | ta-01M570RC8PJNNY94WM708QFJTS | 08:08:13 |

08:11两项都在加载模型，尚无新完整结果；RSI此前短暂等待平台分配已经结束。实际模型就绪与新增结果以新root的progress.json为准，当前尚待启动核验。

八路并发会增加瞬时临时盘占用，并共享CPU带宽；不能保证8张GPU始终满载，也不能把名额增加4倍当作吞吐加速4倍。用后删除解决长期累积，无损编码与长模型输出成本仍存在；最终速度以新记录为准。
