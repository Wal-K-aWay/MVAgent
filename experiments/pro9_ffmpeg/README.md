# 完整PRO6000 9B源码＋FFmpeg实验

用户要求仅先测试9B，可用16张GPU。此分支是隔离实验，不替换共享主工作区。

`src/`完整来自导入提交`6b1e5641719e5e12202737ed66f218250a8b4bd6`的
`outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot/`。105个文件逐Git blob及SHA256校验；
唯一源码差异为`mvagent/utils/media.py`中的分段函数及其FFmpeg依赖导入。保留旧Prompt、schema、
无字段字符硬限、直接回答/独立兜底、串行VideoAgent、memory和客户端。

分段采用PRO27B/35B的FFmpeg stream copy与短视频补帧转码实现，移除对新版execution日志和媒体缓存的依赖，
不引入其他新版src文件。保留旧输入检查与帧数需求。完整清单见`source_provenance.json`。

## 环境边界

不是原PRO6000硬件/依赖的逐位复刻。模型仍为9B BF16，在两个独立8×H100实例上运行；每卡TP1/C1、
整题固定副本，seed0、temperature0、FlashInfer GDN、native GemmaRMSNorm、prefix/MM缓存关闭。
当前已验收的同步服务原样置于`backend/`，没有放进历史src。

旧LocalVLLMClient复用显式端点。实验外部`bridge.py`只把旧
`response_format.json_schema.schema`映射成`structured_outputs.json`，不添加紧凑grammar或新字符限制；
保留旧客户端自身省略顶层oneOf/uniqueItems的行为及生成后的完整schema校验。
桥附加seed0、关闭thinking及token日志，记录原请求（媒体以内容哈希表示）、实际响应及完整token。

基于旧input_config调整权重/缓存/端口路径，显式声明当前服务BF16、131072上下文、0.94显存比例与1860秒HTTP等待。
2048输出token、512帧、Global/Video各5步、旧2次重试、skill关闭等保持旧设置。
因此结论应称为“旧src＋FFmpeg在固定H100环境的效果”，不能把差异全部归因于裁剪器。

## 面板与执行

- 复用`direct_answer_random_20261015`的全部300题（每benchmark100），不重新抽题。
- 从已完成旧全量9B的239条CCQA中以seed0固定抽30题，单列开放题结果。
- 直接复用历史记录的完整问题和视频输入；保存来源SHA，不把参考答案/评分点送给Actor。
- 两组8卡分16份，各worker顺序处理自己的题目。先对一个CV题和一个CCQA题各跑两遍，记录调用路径变化后的token比较。
- 主指标使用同一冻结官方评分器，与PRO历史、已完成独立回答器/直接回答面板同题比较。
  CCQA四组（本次、PRO、独立回答器、E2E）使用同一个Qwen Judge与共享缓存重新评分，不能混用PRO旧DeepSeek分数。
- 新结果仅写`/runs/devbox/pro9_ffmpeg_20261016`，历史轨迹只读；源代码及Markdown可在本地/Git保存。

入口：`run.py prepare`准备330题；`run.py serve --shard 0|1`在各8卡实例启动服务与worker。
`check.py`验证旧schema字段转换、FFmpeg普通/补帧分段；`evaluate.py`用已有冻结评分器聚合闭式结果和同题差值。
运行中的实际进展以Modal结果目录的`shard0/progress.json`、`shard1/progress.json`和每rank进度为准，不能把申请成功当作完成测试。

`judge.py prepare`仅整理旧答案；Actor完成后，`judge.py judge`加载原冻结Judge并评分四组各30题。
Judge错误不计零分，全部成功才聚合；`judge.py report`在闭式评分文件就绪后单独执行，可以纯CPU复用原始Judge结果。
`finalize.py`核对330条原始记录、旧src哈希、120份Judge与共享缓存，输出最终审计及completed状态。

本次冻结桥在客户端重启时会复用日志编号；运行时已单独归档并逐SHA验证全部28个冒烟响应，
`smoke_trajectory_audit.json`验证除时间外的完整结果一致。分支后续修复为沿用已有最大编号，远端自检通过；
这一日志修复没有热更新到本次330题的冻结Actor进程。源manifest记录的是实际运行文件哈希。

## 27B和35B-A3B追加实验

2026-10-16用户要求两模型也测试旧src＋FFmpeg。统一使用上面的PRO6000 **9B**源码快照，不切换成各模型不同的旧源码；
105个src哈希与9B实验完全一致。复用同330题、推理seed0、2048token/512帧/5+5步；各模型独立8H100，TP1/并发1。
仅模型权重/服务别名和输出根目录变化。9B原结果和源码快照不改写；正式主工作区不替换。

实验脚本用`PRO_MODEL=27B`或`PRO_MODEL=35B-A3B`选择模型。结果根分别为
`/runs/devbox/pro9_ffmpeg_27b_20261016`和`/runs/devbox/pro9_ffmpeg_35b_20261016`。
`run.py prepare`复用9B输入清单，并核对该模型历史输入完全一致；`judge.py prepare`准备各模型的旧PRO/独立/E2E答案。
`pipeline.py`依次运行8个固定服务、两题各两遍完整冒烟、330题分片、同箱切换Judge并评分四组各30题。
模型身份、全部中间调用token/hash以及除运行时间外完整结果需通过冒烟；桥日志编号沿用已有最大值。
Actor/Judge完成后，`evaluate.py`、`judge.py report`和`finalize.py`在CPU收尾，不重跑Actor。

27B历史PRO结果目录实际名为`qwen3_5_27b_mvagent`。这些旧PRO结果来自各自当时源码，作为历史参照；
本轮三模型统一旧9B src，因此不能把历史差值解释为单一裁剪器或某一句Prompt的因果效果。
9B当时使用16卡分片，新增模型各8卡；整体墙钟不能直接用来比较模型速度。

结果分析见`outputs/pro9_ffmpeg_models_20261016/README.md`。27B为316有效/14工程失败，未进入Judge；35B为330有效并完成Judge。
`quick_scores.py`复用冻结官方评分器读取已保存答案，核对输入/源码和有效题数，按有效同题计算分数及区间；不重跑模型。
它不要求27B全部成功，也不把失败记零；27B的开放题和十类总分保留缺口。不能把pipeline的遍历完成等同于全部题有效。
