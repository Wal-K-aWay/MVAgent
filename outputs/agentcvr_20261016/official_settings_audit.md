# H200 r4运行与官方设置核对（2026-10-16）

2026-10-17追加：已找到作者公开训练集并完成文本重合核查，见文末“CrossVid训练来源与可测性”。此前“训练集未取得”仅为10月16日历史状态。

此报告固定对应H200 r4审计快照。用户随后要求换8×H100，硬件迁移状态见README；温度、模型身份、提示适配等审计结论仍适用。

结论：**不完全一致**。准确名称应为“AgentCVR 作者公开 Qwen3-8B RL 权重＋公开执行器，采用 CVBench/MVU-Eval 官方题面和评分的跨 benchmark 适配评测”。不能称为论文配置逐项复现，也不能把官方题面一致扩大为完整消息、Agent System、数值设置全部一致。

本次只核对及记录，没有修改、停止或重启正在运行的 r4。推理冻结代码 ebd456d，作者代码 568b402c51254a04149d49d0bc4ad7c9d2fcf2f1。当前任务继续按原冻结配置执行，后续若改变设置必须另建实验并区分结果。

## 证据范围

- 核对[论文正文与附录 B/C](https://arxiv.org/html/2605.29643v1#A2)、[公开代码](https://github.com/wang-jh24/AgentCVR/tree/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/agent_system)、已下载模型卡/config、实际容器服务启动日志、16条服务命令及已落盘请求。
- Modal 原始证据：`devbox/agentcvr_eval_20261016_r4/official_settings_audit.json`，07:47 UTC快照。86题/639请求（Master511、Vision128），0HTTP错误、0题面/预期System差异、0原始记录hash差异；637个stop、2个length。这里的System一致是与我们的冻结适配版一致，不是与官方CC原文一致。
- 实际 `/opt/AgentCVR/agent_system` 与运行归档的 upstream 文件逐字相同；执行器、Qwen客户端、抽帧及音频四个关键文件的SHA256另与本地干净作者checkout一致。没有为审计重新推理已完成题。

## 会影响方法身份和结果的差异

| 项目 | 官方材料 | 当前实际设置 | 判断 |
|---|---|---|---|
| Master | 论文写Qwen3-VL-8B thinking；发布权重config与训练YAML为Qwen3-8B纯文本 | 作者qwen8b_crossvidRL，Qwen3ForCausalLM | 符合公开权重身份；不是已确认的论文VL checkpoint |
| 温度 | 论文附录B为0；公开qwen_agent.py与.env.example默认0.5 | 639/639请求为0.5，Master/Vision均如此 | 符合公开代码默认，**不符合论文温度** |
| 长度预算 | 论文称最大长度8192，表4训练prompt/response各4096；公开客户端max_tokens=8192 | 每次最多8192输出，服务总上下文Master40960/Vision131072 | 符合客户端输出默认；不能等同于论文8192总长。论文推理长度含义还需作者确认 |
| 实际长上下文 | 无法获得论文原始服务manifest | 已有22次请求输入+输出>8192（Master8/Vision14）；最大13430/15713 | 长度区别已涉及实际请求，不只是未触及的配置 |
| Master System | 作者按CrossVid任务配置不同prompt；没有CVBench/MVU官方入口 | 两套benchmark统一用改写后的master_CC.prompt | 是我们选择的适配策略，没有官方跨benchmark映射依据 |
| CC prompt改动 | 原CC包含烹饪专家角色、4视频、只答A–D | 删除首个角色段；视频编号推广；终答格式服从Query | 三处改动均会改变输入；不能称未改官方System |
| 遗留CC策略 | 原CC有烹饪示例、优先获取字幕示例、至少4工具调用要求 | 全部保留并用于两个benchmark的所有任务 | 会影响策略；不能把这种统一选prompt当作纯接口适配 |

最大长度不能仅凭论文一句话确定为`max_model_len=8192`，更不能未经说明把当前配置称作已对齐。将温度改为0也不能解决模型身份、System和长度含义的差异。

## 一致或可追溯保留的部分

- 视觉模型为Qwen3-VL-8B-Thinking；Whisper为large-v3，与论文8B视觉/音频描述一致，但论文未提供精确模型revision，不能证明逐文件同一版本。
- 公开任务入口MAX_TURNS=20，当前20；执行器自身函数默认100并未被使用。原重试与JSON解析逻辑保持。
- 原Decord抽帧、OpenCV缩放/JPEG流程、最长边360保持；帧数由Agent工具参数决定，无额外512总帧限制。当前视觉服务上限4096图片/请求是本地部署约束，官方服务同项参数未公开。
- Whisper原参数保持：beam_size=5、temperature=0、no_speech_threshold=0.6、logprob_threshold=-1、condition_on_previous_text=False；代码中的固定英文language及movie初始提示也保留。只改权重缓存位置，未改转写算法。
- 发布actor配置dtype=float32，使用作者verl原合并器转BF16；该转换就是上游合并器的实现，不是替换成未经RL的基础模型。推理为BF16、无量化。

## 官方 benchmark 提示的精确边界

- CVBench：题面调用官方mvr_doc_to_text，保留YAML两种答题指令及130道Yes/No分支；官方adapter的基础System置于Agent工具System之前。
- MVU：直接执行官方build_messages_base的文本分支，保持question → 原答题指令 → options；没有采用本项目E2E曾替换或后移的指令。
- 两者的完整题面放入AgentCVR的JSON `query`，`possible_answers=[]`避免重复选项。视频以编号/时长提供，随后按Agent动作取证。
- **这不是benchmark官方单次VLM消息的逐字复刻**：MVU官方消息包括文件名与整组视频帧，本次不显示文件名、不预塞全部帧；CV官方adapter的边界提示图片及固定8帧/448×448也未使用。它们由AgentCVR自身主动取证流程替代。
- 这些单次VLM媒体设置并非可直接套用到Agent而不改变方法；应明确写“官方题面与评分”，而非“完整官方端到端设置”。

## 部署、评分与额外限制

- 当前8×H200、每卡Master+Vision+Whisper、8独立TP1答题；论文是8×H800。实际vLLM0.19.1、torch2.10、transformers4.57.6、Whisper20250625、decord0.6、OpenCV-headless4.13.0.92。官方没有完整锁定这些部署版本及并行布局，无法证明一致。
- 实际服务使用FlashAttention、eager、prefix/MM processor cache关闭、seed=0；HTTP请求额外加return_token_ids及tool_call_id。后者已有token模板等价检查。seed与缓存/执行模式属于本项目部署选择，官方未给出完整对应值。
- 两个模型generation_config的top_p=0.95、top_k=20被vLLM默认加载，温度被请求覆盖为0.5；官方客户端未传top_p/top_k，服务缺省值未公开，不能据此断言相同或相反。
- CV用官方正则判分；MVU用官方首字符规则，均按题平均。取Agent final_answer字段评分，不把包含JSON/thought的整段决策当最终答案。CV损坏媒体64–66排除，只评997/1000题；MVU1824题。
- 单题额外3600秒时限；基础设施错从有效样本分母排除并报告覆盖率，正常未终答计0。这是我们的运行/汇总约定，不是官方完整协议。此快照86题均终答、无基础设施错，当前尚未产生分母差异。
- 训练集未取得，未证明无数据污染；没有用本次审计检查点挑选或修改模型/策略，没有启动额外对照试验。

## 结果使用建议

现有运行可作为“公开代码默认参数的跨benchmark适配基线”，保留已有结果和上述差异；不要标成“论文原设置复现”。严格论文对齐至少需要澄清VL Master权重与长度定义，以及制定并披露CVBench/MVU的Agent System适配。当前审计不把这些未知项伪装成已有官方答案。

## CrossVid训练来源与可测性（2026-10-17追加）

结论：有明确证据表明AgentCVR针对CrossVid任务类型进行合成脚本RL训练；现有公开证据不支持直接断言其使用了CrossVid正式测试样本。
可以将公开8B权重用于Lite2500同题对比，但须标注“任务定向合成数据RL”，不能称为未针对CrossVid训练的零样本方法，也不能声称完全排除了污染。
本次只调研与CPU查重，没有启动CrossVid推理、训练或Judge。

### 论文与公开代码

- [论文§4.2及附录H](https://arxiv.org/html/2605.29643v1#S4.SS2)描述基于任务模板、属性组合和LLM生成语义脚本，再在文本模拟器中用GRPO训练Master。§5.1将CrossVid作为真实视频评测集。
- [论文§5.4.1](https://arxiv.org/html/2605.29643v1#S5.SS4)另将真实BU/FSA视频转成文本脚本来测试模拟器一致性；该段描述的是一致性分析，不是这些转写脚本被用于RL更新的证据。
- 官方GitHub当前HEAD仍为`568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`。[README](https://github.com/wang-jh24/AgentCVR)明确分开合成数据、文本RL、真实视频评测三个阶段。
- 检查全部9个`data_synthesis/generate_full_dataset_*.py`：公开生成器采用硬编码场景/属性库及随机组合调用生成LLM；其中显式文件打开操作均为写入合成结果/错误记录，未见读取CrossVid QA/视频并改写训练题的调用。例：[行为生成器](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/data_synthesis/generate_full_dataset_behavior.py)从动物行为、人类活动和情境组合构造题目，[烹饪生成器](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/data_synthesis/generate_full_dataset_cooking.py)要求生成YouCook2风格数据。
- [预处理代码](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/verl/examples/data_preprocess/crossVid_tool_agent_loop.py)从`finished task/*_synthesis/task_*.json`读取合成题，写出`crossvid_train_mini.parquet`，`extra_info.videos`保存文字脚本。因此文件名和`data_source=crossvid_*`本身不证明读取了官方测试QA。
- [8B训练脚本](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/verl/crossvid_agent_8b.sh)确实将同一个parquet赋给train_files和val_files；这是公开训练配置没有独立验证集的问题，不能自动推导为真实CrossVid评测集与训练集相同。

### 更正：真实可下载训练集已找到

此前只检查了[8B模型卡](https://huggingface.co/xiaohua616/qwen8b_crossvidRL)指向的`xiaohua616/crossvid_train`链接，公开API/README至今返回401。
这次枚举作者公开datasets找到[**xiaohua616/crossvid_dataset**](https://huggingface.co/datasets/xiaohua616/crossvid_dataset)。该数据卡明确关联4B/8B Master，并指向同一官方预处理代码。
因此“训练集无法获取”的旧判断不完整；401来自旧链接，不能据此断言作者没有公开训练集。
模型卡有“scripted training data from ... CrossVid benchmark”的宽泛表述，必须结合实际脚本和数据解读，不能只凭措辞判断真实测试题泄露。

固定数据revision：`43cbd3bb7b9675202ee8a5cf966f8fff57282512`。
`crossvid_train.parquet`为40,359,205字节，下载后SHA256与HF LFS一致：
`1cf9422692eeeb392d38fc1066c08eeb7ff508ec29fbef6ff85d68317e5b2bba`。

实际读取8,407条，每条prompt只有system/user两个角色，另有答案、工具配置及文字视频脚本；不是数据卡泛称的完整多轮轨迹列表。

| 训练数据类别 | 条数 | 对应CrossVid任务 |
|---|---:|---|
| assembly | 1010 | PEA |
| behavior | 1200 | BU |
| movie | 1998 | NC |
| cooking | 1200 | CC |
| plot | 999 | PI |
| uav_count | 1000 | MOC |
| uav_position | 1000 | MSR |

公开生成器有9类，而这个发布文件实际只有7类；没有grounding/FSA、sort/PSS或CCQA条目。
这只是已发布文件的组成，不能证明历史训练绝无其他数据。抽看各类脚本是带时间轴的事件、字幕或多视角文字描述，与合成生成器的结构一致。

### 实际重合核查

在Modal纯CPU完整读取8,407条训练数据与当前CrossVid全部9,015条原始QA，并核对既有Lite2500 selection。
使用Unicode NFKC、忽略大小写/标点、合并空白的文本规范化；题目和“题目+选项”分别比较。

| 检查 | 全CrossVid | Lite2500 |
|---|---:|---:|
| 含显式question字段、已查题目文本 | 5852 | 1602 |
| 规范化题目完全匹配训练集 | 0 | 0 |
| 规范化题目+选项完全匹配训练user | 0 | 0 |

PI的251题没有独立question字段，另将其完整选项与999条合成plot的选项进行规范化精确匹配：0命中（因此Lite的100题也无命中）。
FSA2248题、PSS664题同样没有独立question字段，不能算入题目文本查重分母；Lite中对应616和182题。
额外提取官方QA媒体字段中的5,286个长度至少8字符的字符串，与训练视频脚本中的字符串值精确匹配，0命中。
该媒体检查不是视频内容比对，也不能排除改写后的描述。

### 可用范围与剩余限制

- **可以测**：固定公开8B checkpoint，在同一Lite2500上按AgentCVR原有CrossVid任务提示运行，统一官方评分，保留其训练方式、音频权限和部署差异。
- **不能这样写**：“AgentCVR完全没有针对CrossVid训练”“已证明训练与测试绝无重合”“这就是论文42.03%对应模型”。公开权重与论文Master模型身份差异仍存在。
- 未做逐条语义改写/近重复检测、真实视频内容比对、基础模型预训练数据审计；发布parquet与实际checkpoint训练输入之间没有可验证的训练文件哈希/完整历史清单。数据卡关联是作者声明，不能替代该证明。
- 即使没有正式题目重复，任务模板、奖励及方法设计显然针对CrossVid。它是任务定向训练基线，区别于完全未针对该benchmark训练的模型；任务类型相同本身不等于测试样本泄露。
- [Issue #1](https://github.com/wang-jh24/AgentCVR/issues/1)仍open且0评论，但现在已找到数据，不能再用该Issue断言训练集未公开。本次没有向作者发送Issue或消息。

核查代码：`eval/external_methods/agentcvr_training_audit.py`，远端实际源码SHA256
`38621acdf0928f5ab5c88a456528ceedd8a6798b03df61d4ebb9b83f3425c406`。
结果及训练parquet仅保存在runs volume的`devbox/agentcvr_training_audit_20261017/`，`audit.json`包含逐项数量、样例、官方QA与selection哈希。
最终CPU app `ap-sp9Jk1plcICwp2lpVt0qqd`正常完成；首次共享镜像缺pyarrow，在推理/读取训练数据前报错，随后用独立CPU镜像安装pyarrow21.0.0完成核查。
语法、自带规范化/解析断言、全部数据读取和覆盖校验通过；未运行模型推理或项目全量测试。
