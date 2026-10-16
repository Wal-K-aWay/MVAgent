# 当前运行与官方设置核对（2026-10-16）

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
