# AdSeek / AgentCVR 原版补测：材料获取记录

核查时间：2026-10-16，追加深入检索。**更正06:18 UTC的结论：已找到与官方仓库关联的AgentCVR训练权重，名称不含AgentCVR，此前仅按方法名检索漏掉了它们。** AdSeek仍未找到可确认的公开代码/权重。当前完成实验单元0，有效样本0，无准确率结果；8GPU授权有效，尚未申请GPU。

## 已确定的范围

| 原版系统 | 新增评测 | 当前可测题数 |
|---|---|---:|
| AdSeek | CVBench | 997 |
| AgentCVR | CVBench、MVU-Eval | 997 + 1824 |

CrossVid只引用论文公开结果，不重跑；不测AdSeek/MVU-Eval。CVBench原有64–66三道媒体损坏题继续单列，997题结果不能称完整1000题结果。共3818次答题是每种方法一个原版模型配置的计数，不是新增三种Qwen3.5骨干的矩阵。

## AgentCVR：代码和训练权重均已找到，论文/发布配置存在差异

- 官方仓库：[wang-jh24/AgentCVR](https://github.com/wang-jh24/AgentCVR)。通过隔离账号工具 `gh-kw git clone --depth 1` 下载，固定commit `568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`。
- Lightsail源码：`reference/AgentCVR/`；已同步到modal-gpu的 `~/wxu-evolve-agent/external_sources/AgentCVR-568b402/`。两个checkout均干净；`git archive HEAD`的SHA256均为 `ba1d386791751fc0d8906fb87c802990c2493a6257f504d39ddcb3dc763e41aa`。
- 当前官方仓库只有main分支，无tag，release数量0。文件树未附训练权重，`agent_system/.env.example`中的Master模型名为 `your-master-model`。根目录的 `AgentCVR_clean.tar.gz`仅45字节，经tar目录检查没有成员，不是模型发布包。
- [官方运行说明](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/agent_system/README.md)需要用户配置Master/VLM模型端点；其入口针对CrossVid，CVBench/MVU-Eval仍需数据与题面适配。
- 历史检索只按AgentCVR方法名和论文arXiv标签查询为空。扩大至HF模型名关键词CrossVid后，找到下表两个训练checkpoint。HF账号 `xiaohua616` 的公开fullname为 `wangjiahe`；模型卡明确写AgentCVR Master Agent，所链旧GitHub地址 `xiaohua616/AgentCVR` 经API和网页均重定向到论文官方 `wang-jh24/AgentCVR`。这提供了作者关联证据，而不是仅凭相似模型名判断。

| 公开checkpoint | 固定revision | actor模型分片大小（不含优化器） |
|---|---|---:|
| [xiaohua616/qwen4b_crossvidRL](https://huggingface.co/xiaohua616/qwen4b_crossvidRL) | `1d93a956cf0a6955be91e2089b499d23b0a8b0d6` | 17,647,548,760 bytes，8分片 |
| [xiaohua616/qwen8b_crossvidRL](https://huggingface.co/xiaohua616/qwen8b_crossvidRL) | `0ca8538758507589a5bada39d2377847649adc09` | 32,764,792,152 bytes，8分片 |

- 两者首个模型分片的固定revision下载HEAD均返回HTTP200，长度与HF文件元数据一致；尚未下载或验证全部权重。8B首片SHA256元数据为 `ea14409bc1ac0c63ad1155d594c73b325c135bcde061b50e57dcbf36ec019095`，全量下载仍需逐文件校验。
- 仓库结构是 `actor/model_world_size_8_rank_0.pt` 至rank7，`FSDP_version=1, world_size=8`。附有tokenizer/config及优化器状态，但没有直接可加载的根目录HF权重；模型卡中AutoModel直接加载示例不适用于当前发布布局。应使用源码内 `verl/verl/model_merger/fsdp_model_merger.py` 合并模型分片，评测无需下载优化器。**8路训练分片不等于推理必须TP8。**
- 重要版本差异：两个checkpoint的 `actor/huggingface/config.json` 都是 `architectures=[Qwen3ForCausalLM]`、`model_type=qwen3`。官方 `verl/examples/sglang_multiturn/config/crossvid_qwen3_grpo.yaml` 第20行也指定 `Qwen/Qwen3-8B`；而[论文§5.1](https://arxiv.org/pdf/2605.29643)称Master为Qwen3-VL-4B/8B thinking。公开代码与公开checkpoint彼此一致，但不能据此证明与论文42.03%对应的模型完全相同。这个差异不是我们擅自换骨干造成的。
- 模型卡链接的训练数据 [xiaohua616/crossvid_train](https://huggingface.co/datasets/xiaohua616/crossvid_train)，本次公开API与README访问均HTTP401，不能称已取得数据，也不能据错误码断言是不存在还是权限受限。公开[Issue #1](https://github.com/wang-jh24/AgentCVR/issues/1)仍无回复；因此训练来源重合审计尚不可完成。训练集缺失不必阻止固定checkpoint的推理，但限制数据泄露结论。
- 检查官方全部提交：只有一次初始提交；作者GitHub账号公开仓库没有另一个AgentCVR模型入口。唯一公开fork `groupthinking/AgentCVR` 与官方HEAD完全相同、release为空；未发现其他发布分支或新增权重。

## AdSeek：未找到论文对应的公开代码和训练权重

- 核查[论文页面](https://arxiv.org/abs/2610.03099)及正文、GitHub仓库与代码搜索（AdSeek、AdsCVR、论文编号）、Hugging Face models/datasets/spaces查询，未找到可确认的作者发布入口。检索没有命中不等于证明材料从未发布，也不能排除作者通过其他渠道提供。
- 新增核查[arXiv原始LaTeX源码](https://arxiv.org/src/2610.03099v1)：源码包11,963,358 bytes，直接在内存查看文本，没有发现GitHub/Hugging Face/ModelScope下载链接。正文对“released code”的泛称没有附可用URL；附录提供SFT/RL参数，而非可下载checkpoint。
- 沿共同作者的HiDe/E-VAds公开项目及Tennine2077主页/仓库追踪，未找到AdSeek发布链接；不把同组其他项目当作AdSeek。补充ModelScope域名定向网页搜索未命中对应模型，这不是对其未索引/私有仓库的完整排除。
- Hugging Face唯一同名模型命中 `hyyyrrrrr/ADSeeker-weights`，包含 `mvtec_best.pth`、`mula_518.pth`，无模型卡。对应[Space源码](https://huggingface.co/spaces/hyyyrrrrr/adseeker-demo/blob/main/app.py)明确为 `AdaCLIP -- Zero-shot Anomaly Detection`，使用MVTec等图像数据和anomaly map；与多视频AdSeek无关，未下载这些权重。
- 所需材料：论文AdSeek代码、训练后checkpoint、对应配置（明确Stage 3 mixed或AdsCVR-only），以及用于确认模型身份/训练来源的说明。论文所述Qwen3-VL-8B骨干与4B视觉工具不等于可直接复现训练后的AdSeek。

## 下一项可执行实验

AgentCVR的可下载材料阻塞已解除；当前需确定“原版”的报告口径：按作者公开Qwen3-8B checkpoint补测并披露论文差异，或只接受论文所述Qwen3-VL checkpoint、等待作者说明。已就这一具体差异询问用户，不重复询问8GPU许可。确认采用公开版本后，经modal-gpu下载到Modal持久化存储，合并FSDP分片，核对完整性，冻结源码与配置；先用指定benchmark单选题验证完整调用和官方评分，再继续CVBench/MVU-Eval。AdSeek仍等待代码/训练checkpoint，两方法无需互等。

普通Qwen3-VL基础模型确实可下载，但不代表AgentCVR/AdSeek训练后的策略。未修改原提示/工具策略，未启动RL重训，未向作者发送Issue或邮件。

本记录是材料获取与实际阻塞说明，不是实验完成报告。上游源码保留为固定commit的本地/devbox克隆，不把第三方仓库完整复制进MVAgent；模型、数据与实验输出均未下载到Lightsail。
