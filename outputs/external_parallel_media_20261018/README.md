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

## LensWalk最终结果（2026-10-19）

精简结果和文本轨迹已按用户要求发布到[GitHub Release](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019)，共68.46 MB、仅五个文件，不含图片编码、token ID数组或重复HTTP体；[下载与字段说明](../lenswalk_release_20261019/README.md)。原始Modal记录保留。

04:18:18 UTC（北京时间12:18）全部5321题和239道CCQA Judge已完成，状态`completed_with_errors`；04:19控制器结束。05:47只读复查host3587165不存在，实际续接Sandbox `sb-NVXHhVNhafuN1302dcRAgn`已poll137，GPU已释放，无剩余排队题。原Sandbox曾于10月18日20:31退出，后台控制器已用同一冻结源续接，不能把旧Sandbox退出视作最终失败。

| Benchmark | 已处理 | 工程失败 | 工程失败计零得分 | 排除工程失败得分 | Agent平均秒/题 | 视频准备平均秒/题 |
|---|---:|---:|---:|---:|---:|---:|
| CVBench | 997/997 | 0 | 55.37% | 55.37% | 219.06 | 8.85 |
| MVU-Eval | 1824/1824 | 7 | 33.72% | 33.85% | 146.93 | 11.22 |
| CrossVid Lite | 2500/2500 | 2 | 21.77% | 21.79% | 267.85 | 185.99 |

逐题遵循原官方评分；CrossVid为十任务等权macro，CCQA保留239题的评分点加权。原summary排除工程失败；本表另以完整面板为分母计零作对照，不改写原分。模型空答案与未收尾输出仍参与原始答案评分，不作为工程失败排除。Agent时间包含多轮调用/工具/等待，不含视频准备、模型启动和Judge；均值包含失败题的已消耗时间，不是八卡并行墙钟。准备均值混合历次继承的缓存命中和新临时拼接，不能用于单独比较新旧预处理速度。

终态为2938 `finish`、294 `natural_text`、1669 `unfinished_tool_plan`、411 `empty_answer`、9 `missing_result`，共5321个唯一题号。未收尾和空答案是已执行完的模型负结果，不是尚待处理的题。9个工程失败均有HTTP错误并缺失结果：MVU Counting11/619/591/63、SU1201/1218、ICL632，CrossVid MSR62/32。本轮不重复这些失败或增加原预算，未诊断所有HTTP失败根因。

最终原始记录、轨迹、Judge、冻结源及summary仅保存在runs `devbox/lenswalk_full_35b_parallel_media_20261018`。summary大小26105423字节，SHA256 `36bd24d692daabc1ca71e323700da173812efccfbec803c05c13eb70c0cff6f8`；本次核对5321唯一题号及三benchmark完整数量，无新推理/Judge。Video-RSI不属于本次完成声明，其最近状态仍需单独查询。

## 启动与切换记录（历史）

08:02:41 UTC原RSI/Lens Sandbox均poll137、控制器3514200/3514203退出，两个旧root均保存`SCHEDULING_STOPPED.json`。原模型服务已释放；没有让新旧两套推理同时处理相同题目。

正式初始化CPU `ap-NIjB17RwwG9TOSr5c3gZOp` rc0：RSI继承2715（含17条已复现工程失败）、剩2606；Lens继承3692（含5条已复现工程失败）、剩1629。没有完整但未提交的孤立结果阻塞切换，原记录SHA全部保留。

新后台控制器RSI3587159、Lens3587165已提交，各8H100；DEVBOX_NAME分别`mvagent-rsi-parallel-media-35b-20261018`、`mvagent-lenswalk-parallel-media-35b-20261018`。日志为`watch-{rsi,lenswalk}_full_35b_parallel_media_20261018.log`。

| 方法 | Sandbox | Container | 模型启动时间UTC |
|---|---|---|---|
| Video-RSI | sb-v2by7zEl9SftnW2yv9FIbm | ta-01M570XNYTMCQ7B6TW6KZBVK1S | 08:09:53 |
| LensWalk | sb-TH9BknFkqijvDBGu3iuwPG | ta-01M570RC8PJNNY94WM708QFJTS | 08:08:13 |

08:20 UTC两项均已进入真实推理，实际每箱8个不同H100 worker的execution/weights_manifest全部等于各自上一批；新manifest及正在执行的冻结driver均确认8路准备。检查结果和该时刻完整progress快照已保存到各root的`parallel_media_startup_audit.json`。

RSI已新增7条正常终答、0新增工程失败，总记录2722；Lens已新增1条正常终答、0新增工程失败，总记录3693。新运行保留的17/5失败均来自旧批次，不能误当成这次新失败。

实际输出举例：RSI NC364答`A`，准备18.94秒/推理51.05秒；MOC443答`D`，准备2.24秒/推理96.32秒；CV235答`A`，准备2.09秒/推理44.40秒。Lens BU759答`AC`，准备3.14秒/推理92.69秒。这里验证完整执行与计时，不以几个答案推断总体准确率。

08:18:42 Lens的NC822/246仍在准备，另外6个worker已经进入推理；BU471/759首请求均HTTP200且cached_tokens=0。普通题没有再被两个长视频占住全部准备名额。RSI当时也有3个长视频准备、5题推理；抽查新MOC443的归档清理记录removed=true，实际临时目录不存在。没有增加预取积压或取消用后删除。

启动后两项后台控制器继续剩余题目、原官方评分/Judge与汇总，并负责最终释放GPU；LensWalk现已完成并释放，见上方最终结果。独立AI巡检只在当时会话内，退出后仅host控制器继续。实际后续进度读取新root，不恢复旧2路任务。

八路并发会增加瞬时临时盘占用，并共享CPU带宽；不能保证8张GPU始终满载，也不能把名额增加4倍当作吞吐加速4倍。用后删除解决长期累积，无损编码与长模型输出成本仍存在；最终速度以新记录为准。
