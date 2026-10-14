# 八个独立副本的完整 MVAgent 重复性验收

66道开发题，每模型四遍，共792条完整轨迹；不评正确率、不调用Judge。
8×H100 80GB，每卡独立TP1/DP1、模型请求并发1；三模型统一BF16，标准加载器、同步inproc/eager、FlashInfer GDN prefill。
每题内部固定一个副本；每分片先在同一进程中乱序跑两遍，再完整重启并转到下一张卡跑两遍；每题后三遍都与首次结果比较。
seed0、temperature0、thinking关闭，context131072、prefill32768、mem0.94、expandable segments，prefix/MM缓存关闭；正常解码KV保留。RMSNorm固定native，配置与E2E 固定配置相同。
空skill，Global/Video各5步，每调用2048输出token/512帧；Video CPU并发2，实际模型调用串行。

| 模型 | 完整轨迹 | 模型调用 | 配对调用比较 | 不一致轨迹/198 | 8卡吞吐（轨迹/分钟） | 平均单题秒数 |
|---|---:|---:|---:|---:|---:|---:|
| 35B-A3B | 264 | 3128 | 2346 | 0 | 3.442 | 107.47 |
| 9B | 264 | 3492 | 2619 | 0 | 5.074 | 58.64 |
| 27B | 264 | 3344 | 2508 | 0 | 2.555 | 122.49 |

吞吐按两个阶段各自八副本实际墙钟窗口计算，包含Agent视频准备/动作/推理及分片尾部空闲，排除权重加载、进程退出和评分。
缓存冷暖及静态分片影响速度；这些均衡题型开发样例不能直接当作全量benchmark平均耗时。

## 长轨迹、错误与输出示例

- 35B-A3B：每轨迹4–29次模型调用，289–4415累计输出token，单次最大输入46714 token；结束原因{'stop': 3128}；结构化校验失败0，模型错误0。
  实际样例cvbench:664最终答案：`{'answer': 'C', 'reason': 'All four videos explicitly mention or show the use of aluminum wire (or metal wire) wrapped around branches to bend and shape the bonsai tree. Video 1 shows black aluminum wire, Video 2 shows metal wire, Video 3 shows aluminum wire, and Video 4 shows dark-colored wire. While pruning shears are used in all videos, they are primarily for cutting, whereas the wire is the specific object used to aid in the shaping and holding of the branches. Gloves are not present in Video 3, and pliers are not explicitly identified as being used in all videos (Video 2 and 4 do not mention pliers being used for shaping).', 'status': 'answered'}`（仅展示输出，不判断正确率）。
- 9B：每轨迹2–37次模型调用，496–10152累计输出token，单次最大输入46722 token；结束原因{'stop': 3484, 'length': 8}；结构化校验失败0，模型错误0。
  实际样例cvbench:664最终答案：`{'answer': '}', 'reason': "The question asks for an object used across all videos to aid in bonsai shaping. Video 1 explicitly mentions 'black coiled aluminum wire'. Video 2 explicitly mentions 'Wire (铁丝)'. Video 4 mentions 'a coiled wire'. While pruning shears are present in Videos 1, 2, and 4, they are absent in Video 3 (which only shows yellow-handled pruning shears, but the question implies a common tool across the set, and wire is the only tool consistently described as being used for shaping/wiring in the summaries of all four videos, whereas Video 3's summary only lists shears, but the other videos emphasize wire for shaping. However, looking closer: Video 1 has wire. Video 2 has wire. Video 3 has NO wire mentioned, only shears. Video 4 has wire. This creates a conflict. Let's re-read carefully. Video 3 summary: 'displays yellow-handled pruning shears... No other bonsai shaping tools are visible.' Video 1: 'black coiled aluminum wire'. Video 2: 'Wire'. Video 4: 'coiled wire'. If the question implies a tool used in ALL videos, and Video 3 has no wire, then 'Aluminum wire' might be incorrect if strictly interpreted. However, often in these datasets, 'wire' is the intended answer for bonsai shaping even", 'status': 'answered'}`（仅展示输出，不判断正确率）。
- 27B：每轨迹4–28次模型调用，338–9170累计输出token，单次最大输入35684 token；结束原因{'stop': 3340, 'length': 4}；结构化校验失败0，模型错误0。
  实际样例cvbench:664最终答案：`{'answer': 'B', 'reason': 'To determine the object used across all videos, we examine the summaries for each clip. Video 1 shows red gloves, pruning shears, aluminum wire, and pliers. Video 2 explicitly states that pruning shears are used, while red gloves, aluminum wire, and pliers are not observed. Video 3 confirms the use of pruning shears but notes the absence of red gloves, aluminum wire, and pliers. Video 4 shows pruning shears, aluminum wire, and pliers, but no red gloves. The only tool consistently identified as being used to shape or manipulate the bonsai tree in all four videos (Video 1, Video 2, Video 3, and Video 4) is the pruning shears. Red gloves are absent in Videos 2, 3, and 4. Aluminum wire and pliers are absent in Videos 2 and 3.', 'status': 'answered'}`（仅展示输出，不判断正确率）。

## 与此前独立GPU分配留存样例的附加对照

另将本次首遍与历史FlashInfer核心六题及额外六题的首遍比较；不新增推理。先核对保存的推理配置、共同软件版本字段与权重元数据，再逐调用比较输入哈希、token和语义轨迹。
历史manifest未记录全部新版本字段；这是历史复核，不能替代完整控制所有环境变量的跨主机实验。

| 模型 | 可比轨迹 | 配对调用 | GPU UUID清单无交集的轨迹 | 不一致轨迹 |
|---|---:|---:|---:|---:|
| 35B-A3B | 0 | 0 | 0 | 0 |
未满足配置/版本/权重元数据可比条件：['/runs/devbox/repro_agent_flashinfer_35b_20261011_p1', '/runs/devbox/repro_agent_flashinfer_35b_20261011_extra']。
| 9B | 0 | 0 | 0 | 0 |
未满足配置/版本/权重元数据可比条件：['/runs/devbox/repro_agent_flashinfer_9b_20261011_p1', '/runs/devbox/repro_agent_flashinfer_9b_20261011_extra']。
| 27B | 0 | 0 | 0 | 0 |
未满足配置/版本/权重元数据可比条件：['/runs/devbox/repro_agent_flashinfer_27b_20261011_p1', '/runs/devbox/repro_agent_flashinfer_27b_20261011_extra']。

## 样例与边界

| Benchmark | 原生题型 | 样例 | 历史调用数 |
|---|---|---|---:|
| crossvid | BU | crossvid:BU:836 | 12 |
| crossvid | BU | crossvid:BU:264 | 0 |
| crossvid | CC | crossvid:CC:288 | 17 |
| crossvid | CC | crossvid:CC:496 | 0 |
| crossvid | CCQA | crossvid:CCQA:778 | 9 |
| crossvid | CCQA | crossvid:CCQA:823 | 0 |
| crossvid | FSA | crossvid:FSA:121 | 19 |
| crossvid | FSA | crossvid:FSA:768 | 0 |
| crossvid | MOC | crossvid:MOC:433 | 13 |
| crossvid | MOC | crossvid:MOC:521 | 0 |
| crossvid | MSR | crossvid:MSR:455 | 9 |
| crossvid | MSR | crossvid:MSR:26 | 0 |
| crossvid | NC | crossvid:NC:1135 | 15 |
| crossvid | NC | crossvid:NC:793 | 0 |
| crossvid | PEA | crossvid:PEA:693 | 56 |
| crossvid | PEA | crossvid:PEA:533 | 0 |
| crossvid | PI | crossvid:PI:178 | 11 |
| crossvid | PI | crossvid:PI:52 | 0 |
| crossvid | PSS | crossvid:PSS:9 | 18 |
| crossvid | PSS | crossvid:PSS:5 | 0 |
| cvbench | Cross-video Anomaly Detection | cvbench:648 | 9 |
| cvbench | Cross-video Anomaly Detection | cvbench:722 | 0 |
| cvbench | Cross-video Counterfactual Reasoning | cvbench:779 | 9 |
| cvbench | Cross-video Counterfactual Reasoning | cvbench:446 | 0 |
| cvbench | Cross-video Entity Matching | cvbench:612 | 9 |
| cvbench | Cross-video Entity Matching | cvbench:902 | 0 |
| cvbench | Cross-video Event Retrieval | cvbench:399 | 10 |
| cvbench | Cross-video Event Retrieval | cvbench:315 | 0 |
| cvbench | Cross-video Object Recognition | cvbench:664 | 16 |
| cvbench | Cross-video Object Recognition | cvbench:591 | 0 |
| cvbench | Cross-video Procedural Transfer | cvbench:655 | 15 |
| cvbench | Cross-video Procedural Transfer | cvbench:412 | 0 |
| cvbench | Cross-video Scene Recognition | cvbench:232 | 15 |
| cvbench | Cross-video Scene Recognition | cvbench:20 | 0 |
| cvbench | Joint-video Counting | cvbench:438 | 12 |
| cvbench | Joint-video Counting | cvbench:49 | 0 |
| cvbench | Joint-video Spatial Navigating | cvbench:199 | 21 |
| cvbench | Joint-video Spatial Navigating | cvbench:205 | 0 |
| cvbench | Joint-video Summarization | cvbench:795 | 9 |
| cvbench | Joint-video Summarization | cvbench:503 | 0 |
| cvbench | Multi-video Attribute Recognition | cvbench:158 | 9 |
| cvbench | Multi-video Attribute Recognition | cvbench:766 | 0 |
| cvbench | Multi-video Key-Action Recognition | cvbench:190 | 10 |
| cvbench | Multi-video Key-Action Recognition | cvbench:961 | 0 |
| cvbench | Multi-video Temporal Reasoning | cvbench:286 | 17 |
| cvbench | Multi-video Temporal Reasoning | cvbench:68 | 0 |
| cvbench | Multi-view Scene Understanding | cvbench:171 | 12 |
| cvbench | Multi-view Scene Understanding | cvbench:659 | 0 |
| cvbench | Video Difference Caption | cvbench:136 | 10 |
| cvbench | Video Difference Caption | cvbench:173 | 0 |
| mvu_eval | Comparison | mvu_eval:Comparison:1233 | 21 |
| mvu_eval | Comparison | mvu_eval:Comparison:818 | 0 |
| mvu_eval | Counting | mvu_eval:Counting:591 | 12 |
| mvu_eval | Counting | mvu_eval:Counting:77 | 0 |
| mvu_eval | ICL | mvu_eval:ICL:713 | 33 |
| mvu_eval | ICL | mvu_eval:ICL:741 | 0 |
| mvu_eval | KIR | mvu_eval:KIR:179 | 23 |
| mvu_eval | KIR | mvu_eval:KIR:551 | 0 |
| mvu_eval | OR | mvu_eval:OR:752 | 15 |
| mvu_eval | OR | mvu_eval:OR:1187 | 0 |
| mvu_eval | RAG | mvu_eval:RAG:971 | 22 |
| mvu_eval | RAG | mvu_eval:RAG:1339 | 0 |
| mvu_eval | SU | mvu_eval:SU:1235 | 24 |
| mvu_eval | SU | mvu_eval:SU:1137 | 0 |
| mvu_eval | TR | mvu_eval:TR:1500 | 16 |
| mvu_eval | TR | mvu_eval:TR:1467 | 0 |

原始记录：`/runs/devbox/repro_expanded_session_20261012_r3/agent`；完整原始审计：`/runs/devbox/repro_expanded_session_20261012_r3/agent_audit/raw_audit`。
源码快照SHA256：`190bcfaf4a41cdfeb603a068dbe9f6105a16b153cf426db7cc09e4a73d8bc0cc`；面板SHA256：`4fb7a82c2659ea37f504e96ce1679b7e4e73b028410543e88d1973e92c725b4e`。
逐调用检查请求字节与prompt token哈希、完整输出token、真实forward进程/GPU身份及完整语义轨迹。独立VideoAgent调用按agent/video/decision配对，排除墙钟耗时。
已测范围是同一台八卡主机上的四次完整运行、两次独立进程生命周期；不是任意输入、任意硬件/版本或无限重复的数学保证。
仍使用原始MVAgent提示、视频处理、结构化验证和动作逻辑，实验仅以队列替换HTTP传输；正式HTTP服务、任意跨主机环境、一道题内逐调用轮换副本、进程内热迁卡、非空skill及更高并发未由本轮验收。
