# AgentCVR作者公开8B：CVBench / MVU-Eval

## 当前：按用户要求切换8×H100

2026-10-16用户指定改用8个H100。旧H200 r4已主动停止并释放，最终124条answered记录完整保留（CV39/MVU85），hardware_migration.json记录原因。新运行仅更换GPU和独立目录/app，模型、T0.5、官方题面、适配System、8192输出预算、上下文长度及工具逻辑保持原冻结设置；不将H200结果纳入H100成绩。

- GPU实际核验：8×NVIDIA H100 80GB HBM3（每卡81,559MiB），H100!:8，CPU32核/内存256GiB。
- 冻结代码2596390，app ap-BkD0GPDeVjShel9RbVuh7m，GPU container ta-01M51VC1QV1YCMM0FJP5XZGGPR。
- 结果devbox/agentcvr_eval_h100_20261016；控制器PID2652001，日志agentcvr-eval-h100-20261016.log。
- inputs、Agent System和资产manifest与H200逐SHA相同，审计hardware_migration_audit.json已保存。
- 首套Master＋Vision已在同一张H100启动，Whisper已加载并实际调用；正在完成两个benchmark各一道首测，随后加载其余副本进入8路全量。尚未给出H100最终成绩。

以下是此前H200阶段的记录；费用与准确率快照均不作为H100测量结果。


**设置核对更正**：当前并非完全复现论文设置。论文temperature=0，公开代码默认及实际请求为0.5；当前8192是单次输出上限，总上下文40,960/131,072，不能等同于论文最大长度8192。统一改写CC System属于本项目跨benchmark适配。详见[逐项核对与真实请求证据](official_settings_audit.md)。本轮应称公开代码默认参数的适配评测。

本轮只测试AgentCVR，不运行AdSeek或CrossVid。目标为CVBench的997道可测题（官方64–66三题媒体损坏单列）及MVU-Eval的1824题，共2821题。GPU预算已获用户授权：8张；实际配置为H200:8，每卡一套Master、视觉服务和按需Whisper，共8路独立答题。

当前状态（2026-10-16 07:30 UTC）：r4已进入8路全量推理，10/2821有效：CVBench 3/4正确、MVU-Eval 4/6正确，均已终答，0基础设施错。70次模型调用（59 Master、11 Vision）HTTP错误/截断均0；官方Query、输入hash及输入/输出token数核对均0差异，审计留在first_batch_audit.json。07:31 UTC外部Volume读取确认继续增加至14/2821（CV4/6、MVU5/8，0基础设施错）；审计文件仍对应首10题。这是小样本进度，不是最终成绩。app ap-7RJFtaklNqyNCfLQyAEhRD，控制器PID2628400，container ta-01M51S0RZMQQ4B1SFP5VJCC6FR；实际阶段以Modal progress为准。

## 模型及方法身份

- 官方源码：[wang-jh24/AgentCVR](https://github.com/wang-jh24/AgentCVR)，commit `568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`。其AgentExecutor、观察工具、语音工具及QwenModel原文件不修改。
- Master：[xiaohua616/qwen8b_crossvidRL](https://huggingface.co/xiaohua616/qwen8b_crossvidRL)，revision `0ca8538758507589a5bada39d2377847649adc09`。8路FSDP actor分片合计32,764,792,152字节；不下载优化器状态。作者发布的配置及训练代码使用纯文本Qwen3；[论文](https://arxiv.org/html/2605.29643v1)写Qwen3-VL，因此本轮是作者公开版本评测，不宣称复现论文42.03%对应的模型。
- 视觉模型：Qwen/Qwen3-VL-8B-Thinking，revision `92f3c4b4feadd3a016ef468d103bb5f58b2a2c6b`。音频：Whisper large-v3。保留原音视频权限；与仅视觉MVAgent对比时必须披露这一差别。
- 下载逐文件检查大小，LFS文件检查公布的SHA256；合并文件另记SHA256。PyTorch2.10读旧FSDP DeviceMesh失败后，使用隔离的PyTorch2.8 CPU环境执行原版verl合并器，按原实现转BF16。推理继续使用项目镜像的vLLM0.19.1、PyTorch2.10、Transformers4.57.6。
- 模型卡训练数据链接目前公开访问401；不能声称已验证训练数据与测试完全无重合。两套benchmark未发现直接训练使用证据，属于跨benchmark评测，而非已证实无污染。

## 用户指定的官方提示

- CVBench题面直接调用官方 `mvr_doc_to_text`，使用官方YAML的post_prompt1/post_prompt2，保留选项顺序和Yes/No分支；官方adapter的System原句也保留。130道Yes/No题已通过指令检查。
- MVU-Eval文本通过官方 `build_messages_base`的文本分支生成，原顺序为Question → 官方答题指令 → Options。不得采用此前测试过的“指令移后”版本。
- 完整官方文本只放入AgentCVR的Query一次；possible_answers设为空避免重复选项。Agent循环提供视频编号和时长，视频文件名不进入模型。原视频不拼接，时间轴独立，媒体由作者工具按需抽取。
- Agent工具System与benchmark题面分开：以原master_CC.prompt为基础去掉烹饪角色段，视频编号范围由固定1–4推广至实际视频数，final_answer格式服从官方Query以支持CVBench Yes/No；其余工具定义、原示例、至少4次工具调用要求保留。跨benchmark没有原生通用入口，这些适配须披露。
- 保留原入口20轮、Master与视觉temperature0.5、每次最多8192输出token、360最长边及原帧数选择。seed固定0，prefix/MM processor cache关闭，思考模式沿用模型模板。单题3600秒运维时限超时单列基础设施失败，不作为模型答错。

## 执行、评分与留档

`agentcvr_assets.py`在Modal CPU下载/合并。`agentcvr_modal.py --mode all`先CPU检查/冻结，再申请8H200；第一套模型就绪后先跑两个benchmark各一道完整题，再加载其余副本继续全量，已成功落盘题目跳过。22小时到达时结束当前执行段，控制器沿用同一冻结源码继续未完成题。

`agentcvr_worker.py`只读取不含答案的items.json；原始响应、轨迹及请求输入hash先写raw，再写轻量完成记录，评分在控制器中读取单独private_labels。保留完整模型响应及请求的token审计字段；图像base64替换为哈希，原视频/抽帧源码保留。HTTP错误、未终答与正常答案分别记录。原API缺少的tool_call_id仅用于OpenAI传输兼容，CPU检查确认该字段不改变Master tokenizer生成的输入token。

CVBench调用官方正则评分；MVU-Eval使用官方首字符评分，同时保留框架已有的格式诊断。主指标按题平均，基础设施错误单列有效样本与覆盖率；未终答按失败交付计零。不启动Judge。

持久化位置仅Modal runs volume `wxu-evolve-agent-runs-20261006`：

- `devbox/agentcvr_20261016/assets.json`、原失败及torch2.8成功合并日志。
- `devbox/agentcvr_eval_20261016/`：第一次CPU准备，通过提示契约但未进行GPU推理。
- `devbox/agentcvr_eval_20261016_r2/`：首次模型服务CLI参数失败，0响应；保留冻结源码和失败日志。
- `devbox/agentcvr_eval_20261016_r3/`：两模型同卡服务启动成功，但首题进程argv错误，0推理响应；保留原件。
- `devbox/agentcvr_eval_20261016_r4/`：当前控制器目标，冻结代码ebd456d；frozen_source.tar.gz、manifest、items、private_labels、raw、records、scores与progress。

modal-gpu控制器日志 `~/wxu-evolve-agent/devbox/agentcvr-eval-20261016-r4.log`，PID文件同名前缀。源码在独立 `agentcvr_repo`，不修改其他会话的活动服务。独立Luna代理已在07:31 UTC完成末次只读检查并结束；远端控制器继续运行。会话外没有持续的独立15分钟代理巡检。

CPU验证已经通过：2821条官方输入、130道CV Yes/No指令、标签隔离、传输tool_call_id的token等价，以及完整项目语法编译。GPU首测已有真实输出：CV363为A（5次Master调用，84.70秒，13,308输入/4,287输出token）；MVU KIR377为C（9次Master调用，163.65秒，31,907输入/10,867输出token）。最终有效样本数、分数和全量耗时仍待完成。

## 费用口径

按2026-10-16查询的[Modal公开定价](https://modal.com/pricing)，H200每秒$0.001261，8卡为$36.3168/小时；申请的32 CPU核及256GiB内存合计约$3.5551/小时，本任务约$39.87/小时，另外计存储与实际超出请求的资源使用。加载、失败启动及空闲等待均发生费用；最终按实际运行段时长估算，不把两道冒烟的耗时外推成保证。模型均本地推理，无额外按token计费的模型API/Judge。实际账单折扣、额度和税费未核实。
