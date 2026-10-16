# AdSeek / AgentCVR 原版补测：材料获取记录

核查时间：2026-10-16 06:18 UTC。当前原版补测被训练权重/代码缺失阻塞，完成实验单元0，有效样本0，无准确率结果。用户已授权8GPU；未申请GPU，未安装推理依赖，未进行训练或用其他骨干替换原版。

## 已确定的范围

| 原版系统 | 新增评测 | 当前可测题数 |
|---|---|---:|
| AdSeek | CVBench | 997 |
| AgentCVR | CVBench、MVU-Eval | 997 + 1824 |

CrossVid只引用论文公开结果，不重跑；不测AdSeek/MVU-Eval。CVBench原有64–66三道媒体损坏题继续单列，997题结果不能称完整1000题结果。共3818次答题是每种方法一个原版模型配置的计数，不是新增三种Qwen3.5骨干的矩阵。

## AgentCVR：官方源码已取得，训练权重未找到

- 官方仓库：[wang-jh24/AgentCVR](https://github.com/wang-jh24/AgentCVR)。通过隔离账号工具 `gh-kw git clone --depth 1` 下载，固定commit `568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`。
- Lightsail源码：`reference/AgentCVR/`；已同步到modal-gpu的 `~/wxu-evolve-agent/external_sources/AgentCVR-568b402/`。两个checkout均干净；`git archive HEAD`的SHA256均为 `ba1d386791751fc0d8906fb87c802990c2493a6257f504d39ddcb3dc763e41aa`。
- 当前官方仓库只有main分支，无tag，release数量0。文件树未附训练权重，`agent_system/.env.example`中的Master模型名为 `your-master-model`。根目录的 `AgentCVR_clean.tar.gz`仅45字节，经tar目录检查没有成员，不是模型发布包。
- [官方运行说明](https://github.com/wang-jh24/AgentCVR/blob/568b402c51254a04149d49d0bc4ad7c9d2fcf2f1/agent_system/README.md)需要用户配置Master/VLM模型端点；其入口针对CrossVid，CVBench/MVU-Eval仍需数据与题面适配。
- Hugging Face公开API按AgentCVR搜索models/datasets/spaces均为空。GitHub代码搜索和[论文](https://arxiv.org/html/2605.29643v1)未找到可确认的官方checkpoint下载链接。公开[Issue #1](https://github.com/wang-jh24/AgentCVR/issues/1)请求原始合成训练数据，本次核查回复数0；它本身不是权重发布声明。
- 所需材料：论文训练后的Master checkpoint及对应推理配置、工具模型身份。普通Qwen3-VL或Qwen3.5基础权重不能代替论文RL模型。

## AdSeek：未找到论文对应的公开代码和训练权重

- 核查[论文页面](https://arxiv.org/abs/2610.03099)及正文、GitHub仓库与代码搜索（AdSeek、AdsCVR、论文编号）、Hugging Face models/datasets/spaces查询，未找到可确认的作者发布入口。检索没有命中不等于证明材料从未发布，也不能排除作者通过其他渠道提供。
- Hugging Face唯一同名模型命中 `hyyyrrrrr/ADSeeker-weights`，包含 `mvtec_best.pth`、`mula_518.pth`，无模型卡。对应[Space源码](https://huggingface.co/spaces/hyyyrrrrr/adseeker-demo/blob/main/app.py)明确为 `AdaCLIP -- Zero-shot Anomaly Detection`，使用MVTec等图像数据和anomaly map；与多视频AdSeek无关，未下载这些权重。
- 所需材料：论文AdSeek代码、训练后checkpoint、对应配置（明确Stage 3 mixed或AdsCVR-only），以及用于确认模型身份/训练来源的说明。论文所述Qwen3-VL-8B骨干与4B视觉工具不等于可直接复现训练后的AdSeek。

## 下一项可执行实验

任一方法取得已确认的原版材料后，经modal-gpu下载到Modal持久化存储，核对revision和文件完整性，冻结源码与配置；先用指定benchmark的单选题验证一条完整原版调用和官方评分，再在已授权8GPU内继续该方法的指定范围。两方法可独立推进，不要求互相等待。

不改变原版提示/工具策略来冒充原模型，不启动RL重训来替代缺失checkpoint。尚未向作者发送Issue或邮件；目前需要作者公开发布或提供下载材料。8GPU许可仍有效，无需再次询问计算资源授权。

本记录是材料获取与实际阻塞说明，不是实验完成报告。上游源码保留为固定commit的本地/devbox克隆，不把第三方仓库完整复制进MVAgent；模型、数据与实验输出均未下载到Lightsail。
