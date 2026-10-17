# Global简洁System与Video通用要求：隔离对照

## 最终结果（2026-10-17 12:48 UTC）

已完成全部612条新Agent轨迹，三模型每个候选各102/102有效，缺失和整题工程失败均0；90份CCQA Judge全部成功。两个候选各使用8×H100并行执行。11:36开始，12:41前推理和Judge全部完成（约65分钟），12:46 CPU正式汇总完成（约70分钟），在两小时预算内。两个Sandbox、host控制器与本任务state均已释放/清理，没有本实验GPU继续计费。

以下为同题官方分（百分制）；CV30、MVU30按task人口权重估计，Cross42为十task macro，其中15个CCQA按评分点聚合。括号是相对当前MVAgent基线的百分点变化，E2E使用同题结果（MVU为官方指令移后版）。这些102题是开发筛选面板，不是完整benchmark或独立Test。

| 模型 | Benchmark | 当前MVAgent | 简洁Global | Video通用要求＋自身ID | E2E |
|---|---|---:|---:|---:|---:|
| 9B | CVBench | 66.60 | 74.70（+8.10） | 64.00（−2.60） | 70.30 |
| 9B | MVU | 34.49 | 50.96（+16.47） | 37.49（+3.00） | 29.98 |
| 9B | CrossVid | 30.49 | 40.76（+10.27） | 39.54（+9.05） | 39.50 |
| 27B | CVBench | 77.55 | 78.40（+0.85） | 79.85（+2.30） | 70.85 |
| 27B | MVU | 57.90 | 54.02（−3.88） | 57.57（−0.33） | 36.44 |
| 27B | CrossVid | 50.68 | 52.74（+2.07） | 57.08（+6.41） | 44.85 |
| 35B-A3B | CVBench | 81.00 | 74.90（−6.10） | 80.05（−0.95） | 69.05 |
| 35B-A3B | MVU | 46.92 | 43.34（−3.58） | 49.72（+2.80） | 41.84 |
| 35B-A3B | CrossVid | 48.10 | 53.20（+5.10） | 41.43（−6.67） | 44.79 |

简洁Global的九格点估计均高于同题E2E，但相对当前MVAgent有六正三负；不能因超过E2E就宣称优于当前方案。9B最有继续扩样价值；27B/MVU与35B/CV、MVU仍是负信号。Video候选没有形成统一收益，尤其35B/Cross下降。此轮不据小样本替换统一评测基线，也不按这批题为各模型挑不同prompt后当作独立验证；候选代码留在隔离分支供后续改进。

每task内2000次配对bootstrap（seed0），仅简洁Global的9B/MVU与9B/Cross相对基线95%区间严格高于0，分别[+3.04,+32.82]与[+0.056,+20.76]pp；其余包含或触及0。没有共享视频聚类、多重比较或反复开发校正，Cross多数task每类仅3题，不能作稳定提升证明。

### 格式、截断与成本

| 模型 | 闭式格式错误：基线 / Global / Video（各87题） | 触顶调用：基线 / Global / Video | 平均整题秒：基线 / Global / Video |
|---|---|---|---|
| 9B | 2 / 2 / 1 | 5 / 5 / 3 | 55.33 / 49.62 / 45.99 |
| 27B | 0 / 0 / 1 | 5 / 4 / 3 | 107.03 / 91.71 / 86.38 |
| 35B-A3B | 0 / 0 / 1 | 5 / 5 / 2 | 89.05 / 90.65 / 76.78 |

三套均0空答案、0仅右花括号。两个新候选全部模型请求错误0；Global中间structured_invalid共14次、repair13次、length14次（13题），Video三项各8次（8题）。最终能交出答案不代表所有中间调用都未截断。Global最终格式错误2/261与基线持平，Video3/261；Video减少触顶，但尚未改善最终格式合格率。

格式失败仍是模型给出不符合题目要求的非空表达：短Global为PEA784的“None of the above”和Counting127的无法判断；Video为CV774的“None of the above”、FSA2115的“No equivalent step found”，以及35B/CV199以长句解释布局不一致而未选项。没有新增选项枚举或硬编码格式限制。

简洁System没有自动产生更短的轨迹：基线/Global/Video总调用3412/3752/3382，输出token为438427/506876/435318。Global输出token增加15.6%，35B增加约28.0%。上述耗时是本轮实测与历史同题对照，不是同时重跑、控制GPU/媒体缓存状态的纯吞吐实验；不要把时间变化全部归因于prompt长短。

CCQA Judge审计：基线与Video有23对逐字相同答案，其中35B/CCQA56出现一次评分差异（基线0，Video为1/3，3个评分点）。其他相同答案评分一致，Global与另外两组没有相同CCQA答案可比较。若仅将该相同答案统一为旧分，Video的35B/Cross由41.43降至41.22（相对基线−6.88pp），不改变负方向；官方原始评分保留，不静默改分。没有人工重评全部开放题。

### 结论与恢复入口

- 保留已验收基线固定标签 `baseline/mvagent-direct-20261017` → `1b711bf6a466c6dee70c273d24fbd98bd4f0c80d`。共享工作区冻结在 `codex/current-code-freeze-20261017` → `d56579030c7f400a2379d822cd976986d136e9ca`，附 `docs/frozen_evaluation_20261017.md`；两者已推送并核验远端SHA。
- 本次简洁Global及独立Video实验驱动在 `codex/system-ablation-20261017`；实际推理冻结commit为 `519c6984a7a6ca4a136753b71414c890aa88ed54`，后续仅报告变化。主共享工作区和其他在跑实验没有热更新。Video候选由驱动显式生成，不是分支默认启用的生产配置。
- 9B简洁Global可作为下一次预先冻结样本的扩样候选；现有证据不支持三模型统一采用Video新规则。尚未测试“简洁Global＋Video新规则”的组合，也未测试向Video传完整原题。后者会改变instruction-only信息边界；不能用本轮结果判断加入原题的收益。
- 新服务器可先clone仓库，然后 `git switch -c my-next-experiment baseline/mvagent-direct-20261017` 恢复固定已验收代码；复现本候选则从 `519c698` 创建分支。依赖、权重/数据挂载、Modal权限和本地环境skill需单独准备，不随Git克隆分发。

证据仅在runs volume `devbox/system_ablation_20261017`：`manifest.json`、`source.tar.gz`、`samples.json`、`baseline.json`、两个候选各模型的原始records与Judge、`analysis/summary.json`、六个配对表以及`analysis/additional_audit.json`。正式CPU汇总app `ap-K2OLy20Bx2pnMs2ceSSbXn`成功，额外统计CPU成功；612条全部核验token长度/缓存计数0/输入hash/整题单worker，闭式官方分重算一致。采用已验收数值配置，未额外全量双遍生成，不能声称任意输入绝对确定。

下面保留设计、启动与阶段记录；其中“运行中”和未完成数字均是当时状态，最终以上述完整结果为准。

## 设计与执行记录

2026-10-17，用户先授权冻结代码，再测试两个提示候选，目标约两小时取得开发面板结果。

共享工作区快照已推送 `codex/current-code-freeze-20261017`，`d56579030c7f400a2379d822cd976986d136e9ca`，恢复说明在该分支 `docs/frozen_evaluation_20261017.md`。本实验从已完成4500条直接回答分支 `1b711bf` 派生，保留已验收的极短视频采样修复。主工作区不热更新，其他实验不改动。

| 对照臂 | Global | Video |
|---|---|---|
| baseline | 已测通用System | 已测System；复用4500条中的同题结果及评分 |
| global_short | 仅替换为PRO6000的简短角色/证据边界System | 不变 |
| video_rules | 保留baseline Global System | 普通Planner System增加任务定义传递、具体证据与不确定性保留、简洁但完整；显式写入当前video_id |

简洁Global的完整System（User与schema不变）：

> You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.

Video没有新增完整原题、其他视频报告或内部跨角色轨迹。加入完整原题会改变既有信息边界，此轮先检验在现有局部instruction下能否改善。video_id以前存在于对象/日志和视觉请求，普通Planner User没有显式身份行；此臂仅在其System显示已有身份。步数耗尽的Video终止性总结沿用原来的空System，不能声称该调用也接受新规则。Video臂合并了通用要求与身份显示，若有效再拆分其贡献。

Video新增文字：

> Preserve the active instruction's definitions and distinctions in each observation request. Report the concrete observed evidence needed to resolve that instruction, retaining relevant identities, quantities, relations, and uncertainty. Keep explanations concise without omitting required information. Use only evidence from your assigned video; do not infer facts about other videos or select the global answer.

三模型使用相同102题：CV30、MVU30、Cross42（九闭式任务各3题，CCQA15题）；每个候选306次完整Agent，两个候选共612次新推理，另复用306基线。选择seed0，不按得分筛题；这是反复使用的开发池，不是独立Test，也不是scope优化器的Train/Gate流程。小面板只作筛选，不证明九格稳定提升。

固定H100/BF16、8独立TP1/C1、seed0/temperature0、FlashInfer/native norm、prefix/MM cache关闭、2048token、512帧、Global/Video各5步、直接answer与answer_only收尾。User、schema、接口与正式评分不改。两个独立8卡Sandbox各负责一个候选，三模型依次加载，模型切换使用独立端口避免残留租约。CCQA使用同一固定本地Judge，失败单列，不记零。

预留加载、Judge与汇总时间，使用历史同题耗时估计预算，实际可能受GPU排队和长尾影响。控制器有墙钟上限；到时报告实际有效样本及缺失，不把未完成写成完成。源码存单个不可变tar归档，实际每模型source_snapshot及服务身份保留，结果只在Modal runs `devbox/system_ablation_20261017`。完成后释放本实验GPU。

验收报告逐模型×benchmark的官方分、对当前baseline及E2E同题差值、格式/空答案/右花括号、翻转数、调用与耗时；Cross报十task macro，CCQA按点评分。保留负结果。改变提示后答案可以变化，固定数值配置已验收的重复性不重新做双遍矩阵。

状态（2026-10-17 11:36 UTC）：CPU `ap-rhAeHltojgdDFBYORpgkf9` 完整compileall、13接口测试和System替换自检通过；CPU `ap-sUJ8ieXKVGv0f17PoBzzuA` 完成提交前控制器修正归档，均rc0。首版准备源码与manifest保留在 `preparation_attempts/initial`，题目清单未变。最终冻结提交 `519c6984a7a6ca4a136753b71414c890aa88ed54`，归档SHA `209cc39a79fa2a265e62d6f6b377fcb3aefbfcd16cd2e983d922c63a001f6e48`。

两个候选已申请独立8×H100：Global `sb-33cmVnrutj7rIEiCadGwU7`，Video `sb-dL95bKvQlYPNUFoldBXUTL`，开始9B加载；尚无准确率结论。host控制器PID3147193，日志 `~/wxu-evolve-agent/devbox/watch-system_ablation_20261017.log`；两候选依次9B→27B→35B→固定Judge，完成后自动释放本实验GPU并汇总。服务启动前检查实际manifest/profile/8个GPU身份，正式逐题保留输入哈希和token日志。

基于所选同题旧耗时，单臂9B/27B/35B总GPU秒为5643.52/10916.93/9082.70，按8卡加25%波动及27分钟加载/评分预留，预计约1.56小时；非保证。11:38健康检查：共享项目app有3任务（含无关任务），近5分钟Traceback为0；Global八卡已加载约19GB/卡，处于服务预热。


## 阶段结果（2026-10-17 12:23 UTC，尚未完成全矩阵）

两候选9B与27B均102/102有效、整题工程失败0；35B当前Global27/102、Video47/102落盘。尚未执行本轮CCQA Judge，不报告Cross十类总分。以下各CV/MVU单元都是同30题、按既有task人口权重估计的开发子集，不能与前4500面板的500题单元直接相减。

| 模型 | Benchmark | 当前基线 | 简洁Global | Video通用要求＋身份 | 同题E2E |
|---|---|---:|---:|---:|---:|
| 9B | CVBench | 66.60 | 74.70 | 64.00 | 70.30 |
| 9B | MVU | 34.49 | 50.96 | 37.49 | 29.98 |
| 27B | CVBench | 77.55 | 78.40 | 79.85 | 70.85 |
| 27B | MVU | 57.90 | 54.02 | 57.57 | 36.44 |

每模型87道闭式题：9B基线格式失败2，Global2，Video1；27B基线0，Global0，Video1。四个新模型/候选单元均空答案0、仅右花括号0。9B基线两个格式失败均在MVU，因此Global的CV增益发生在两边格式都合格的题上；Global的格式失败总数虽持平，失败题已变成PEA784和Counting127，不能声称原合格题全部保持合格。Video的9B新失败为CV774，27B为FSA2115（No equivalent step found）。

闭式翻转：9B Global CV5胜3负、MVU6胜1负；Video CV0胜1负、MVU1胜0负。27B Global CV2胜2负、MVU1胜2负；Video CV1胜0负、MVU1胜1负。权重不同，翻转个数不能直接当官方百分点。

案例保存在Global/9B/closed_cases.json并核对基线原件SHA：CV154从C错到D对，两版都3调用，候选区分场地中的标牌与教学活动；CV199从B对到A错，候选从联合观看改为分视频取证、3→24调用，依赖单视频推断跨视频方位。Counting136虽然改答正确，理由仍包含对不确定墙数的猜测；Counting155从F对到E错，候选把未量化的multiple与明确3幅比较，缺少有效复核。没有人工重新观看视频，不将这些文本轨迹当作完整视觉根因证明。

首批实际请求核验：每臂8记录，共133响应（Global76、Video57），seed0/T0/2048、输入hash、实际token计数、cache0和整题单卡全部通过；实际Global System分别为短版SHA e04f4c1c26b17d87ff1c73ab1442969e88e5b9fff4171dc56de715d097ee8320和原版SHA acb36637f9288ad5a5ec6703abeed55d7d46ac253fb4fcf3fd8355ce0cb8b4a3，Video臂19次普通Planner请求已核验新规则与对应video_id。没有额外双遍生成。文件为各臂9B/startup_calls_audit.json；阶段闭式分和格式分别为closed_preliminary.json、format_preliminary.json。

Git冻结另提供固定标签 baseline/mvagent-direct-20261017 → 1b711bf6a466c6dee70c273d24fbd98bd4f0c80d，已推送并核验远端解引用SHA。它保留已验收的直接回答实现；共享工作区快照d565790另存，两个用途不可混为完整研究工作区都已验证。
