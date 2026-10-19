# LensWalk补测Qwen3.5-9B与27B

用户要求补跑9B和27B。每个模型使用与已完成35B相同的5321题：CVBench997、MVU-Eval1824、CrossVid既有Lite2500；全部全新推理，不继承35B答案。样本清单SHA256仍为`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`。只把各benchmark的首道既有题放到队首供集成验证，不重新抽题。

从35B已完成批次的冻结源码复制，只更换模型权重/服务名及结果落盘路径。LensWalk原prompt、工具、5轮、Planner未显式设置温度、Observer温度0.2、未显式设置输出上限、600秒请求和1800秒整题等待均保留。每模型8个独立H100，BF16、TP1/C1、seed0、thinking/prefix/MM cache关闭。模型接口仍为独立LensWalk工具调用profile，不连接MVAgent结构化输出服务。

媒体沿用原尺寸/FPS的多视频拼接和两位小数起始时间说明、8路按题临时准备、用后删除；模型图像设置沿用LensWalk原512最长边及180/32/128帧工具预算。原始token/输入哈希审计保留；逐题分开记录视频准备、Agent执行和归档耗时，模型负结果与工程失败分别记录。全部完成后由原控制器完成239道CCQA评分、官方汇总和GPU释放。

## 落盘与验证

runs卷文件名额已用约93%。新批次将逐题记录和原始tar分放`records/<id>.json`与`raw/<id>-attempt-*.tar`，CCQA判分放`judgements/<id>.json`；只在题目执行期间建立临时目录，避免永久多出每题一层目录。中断尝试仍保留，完整已记录结果（包括失败）在续跑时跳过。未修改任何旧运行或原始35B结果。

CPU `ap-7PeFQxrXJvldcgXt65Llij`检查通过：真实冻结源只有模型启动、状态标签及结果路径变化；server函数/类AST完全不变；实际续跑读回表达式保留成功及失败记录、实际Judge函数写回新路径通过；完成规定compileall。其余842份原文件SHA不变。9B/27B权重元数据来自同一只读weights卷，启动时逐卡核对实际execution和weights_manifest。

生产源码`649d2281f760e5305760c38b7f7c83505cb91f14`，分支`codex/lenswalk-models-20261019`。运行根及控制器如下：

| 模型 | runs下目录 | DEVBOX_NAME | host PID |
|---|---|---|---:|
| 9B | devbox/lenswalk_full_9b_20261019 | mvagent-lenswalk-9b-20261019 | 4129382 |
| 27B | devbox/lenswalk_full_27b_20261019 | mvagent-lenswalk-27b-20261019 | 4129397 |

后台继续使用既有`watch_full_mvagent.py`（SHA `ceb088e3c556c2564e8484df05b9ebc5e0288a31e89e5193be187660cc970dc3`），23小时续接、异常恢复次数受限；日志为devbox的`watch-lenswalk_full_{9b,27b}_20261019.log`。已提交控制器，实际模型启动和首题结果仍待验证；提交成功不代表推理或全量评测完成。

原始结果仅保留Modal。35B精简Release和仍在执行的Video-RSI不受本次操作影响；全量分数尚不可报告。
