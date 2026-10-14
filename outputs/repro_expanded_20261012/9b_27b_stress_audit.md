# 八个独立副本的完整 MVAgent 重复性验收

8道开发题，每模型四遍，共64条完整轨迹；不评正确率、不调用Judge。
8×H100 80GB，每卡独立TP1/DP1、模型请求并发1；三模型统一BF16，标准加载器、同步inproc/eager、FlashInfer GDN prefill。
每题内部固定一个副本；每分片先在同一进程中乱序跑两遍，再完整重启并转到下一张卡跑两遍；每题后三遍都与首次结果比较。
seed0、temperature0、thinking关闭，context131072、prefill32768、mem0.94、expandable segments，prefix/MM缓存关闭；正常解码KV保留。RMSNorm固定native，配置与E2E 固定配置相同。
空skill，Global/Video各10步，每调用2048输出token/512帧；Video CPU并发2，实际模型调用串行。

| 模型 | 完整轨迹 | 模型调用 | 配对调用比较 | 不一致轨迹/24 | 8卡吞吐（轨迹/分钟） | 平均单题秒数 |
|---|---:|---:|---:|---:|---:|---:|
| 9B | 32 | 464 | 348 | 0 | 6.344 | 54.70 |
| 27B | 32 | 588 | 441 | 0 | 1.361 | 167.13 |

吞吐按两个阶段各自八副本实际墙钟窗口计算，包含Agent视频准备/动作/推理及分片尾部空闲，排除权重加载、进程退出和评分。
缓存冷暖及静态分片影响速度；这些均衡题型开发样例不能直接当作全量benchmark平均耗时。

## 长轨迹、错误与输出示例

- 9B：每轨迹2–21次模型调用，746–1950累计输出token，单次最大输入35049 token；结束原因{'stop': 464}；结构化校验失败0，模型错误0。
  实际样例crossvid:FSA:121最终答案：`{'answer': 'No equivalent step found in Video 2', 'reason': 'In Video 1, the step between 213s and 245s involves coating chicken pieces with a white powder in a clear plastic bag. However, the analysis of Video 2 explicitly states that this specific action (coating chicken with white powder using a clear plastic bag) was not observed in the provided footage. The available scenes in Video 2 include preparing sauce, chopping vegetables, mixing ingredients, deep-frying, and stir-frying, but none match the target step. Therefore, no functionally equivalent step exists in the provided evidence for Video 2.', 'status': 'answered'}`（仅展示输出，不判断正确率）。
- 27B：每轨迹10–28次模型调用，1422–6134累计输出token，单次最大输入13149 token；结束原因{'stop': 588}；结构化校验失败0，模型错误0。
  实际样例crossvid:FSA:121最终答案：`{'answer': '147,153', 'reason': "Video 1 (213s-245s) shows raw chicken being placed into a plastic bag with white powder, sealed, shaken to coat, and then opened. Video 2's analysis identifies the same functional step—placing raw chicken into a bag with white powder, sealing, shaking, and revealing coated chicken—occurring from 02:27 to 02:33. Converting 02:27 to seconds gives 147, and 02:33 gives 153. Thus, the equivalent interval in Video 2 is 147,153.", 'status': 'answered'}`（仅展示输出，不判断正确率）。

## 与此前独立GPU分配留存样例的附加对照

另将本次首遍与历史FlashInfer核心六题及额外六题的首遍比较；不新增推理。先核对保存的推理配置、共同软件版本字段与权重元数据，再逐调用比较输入哈希、token和语义轨迹。
历史manifest未记录全部新版本字段；这是历史复核，不能替代完整控制所有环境变量的跨主机实验。

| 模型 | 可比轨迹 | 配对调用 | GPU UUID清单无交集的轨迹 | 不一致轨迹 |
|---|---:|---:|---:|---:|
| 9B | 0 | 0 | 0 | 0 |
未满足配置/版本/权重元数据可比条件：['/runs/devbox/repro_agent_flashinfer_9b_20261011_p1', '/runs/devbox/repro_agent_flashinfer_9b_20261011_extra']。
| 27B | 0 | 0 | 0 | 0 |
未满足配置/版本/权重元数据可比条件：['/runs/devbox/repro_agent_flashinfer_27b_20261011_p1', '/runs/devbox/repro_agent_flashinfer_27b_20261011_extra']。

## 样例与边界

| Benchmark | 原生题型 | 样例 | 历史调用数 |
|---|---|---|---:|
| crossvid | FSA | crossvid:FSA:121 | 19 |
| crossvid | PEA | crossvid:PEA:693 | 56 |
| cvbench | Joint-video Spatial Navigating | cvbench:199 | 21 |
| mvu_eval | Comparison | mvu_eval:Comparison:1233 | 21 |
| mvu_eval | ICL | mvu_eval:ICL:713 | 33 |
| mvu_eval | KIR | mvu_eval:KIR:179 | 23 |
| mvu_eval | RAG | mvu_eval:RAG:971 | 22 |
| mvu_eval | SU | mvu_eval:SU:1235 | 24 |

原始记录：`/runs/devbox/repro_expanded_session_20261012_r3/stress`；完整原始审计：`/runs/devbox/repro_expanded_session_20261012_r3/stress_audit/raw_audit`。
源码快照SHA256：`428df5cd1841f45b1d931a599a14c0c66a20a82d6953035e1c2c931ad6277cda`；面板SHA256：`df6b9943789854a1c4b74df48fea42b526f273fd9300b22468a977b1b67cf84f`。
逐调用检查请求字节与prompt token哈希、完整输出token、真实forward进程/GPU身份及完整语义轨迹。独立VideoAgent调用按agent/video/decision配对，排除墙钟耗时。
已测范围是同一台八卡主机上的四次完整运行、两次独立进程生命周期；不是任意输入、任意硬件/版本或无限重复的数学保证。
仍使用原始MVAgent提示、视频处理、结构化验证和动作逻辑，实验仅以队列替换HTTP传输；正式HTTP服务、任意跨主机环境、一道题内逐调用轮换副本、进程内热迁卡、非空skill及更高并发未由本轮验收。
