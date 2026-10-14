# 历史验收与诊断记录

2026-10-13按用户要求移除十个独立报告目录，合并保留20份历史记录；过时巡检记录已删除。
以下状态和下一步均属于记录当时；不代表当前任务，原始数据的Modal路径保持不变。
当前三模型E2E分数见[最终结果](e2e_final_20261013/reports/final_results.md)。

- [concise_system_smoke_20261013/README.md](#concise_system_smoke_20261013-readme)
- [e2e_alignment_20261012/README.md](#e2e_alignment_20261012-readme)
- [e2e_alignment_20261012/formal.md](#e2e_alignment_20261012-formal)
- [e2e_alignment_20261012/progress_checks.md](#e2e_alignment_20261012-progress-checks)
- [e2e_input_preview_20261012/README.md](#e2e_input_preview_20261012-readme)
- [e2e_input_preview_20261012/preview.md](#e2e_input_preview_20261012-preview)
- [formal_repro_integration_20261012/README.md](#formal_repro_integration_20261012-readme)
- [formal_repro_integration_20261012/audit.md](#formal_repro_integration_20261012-audit)
- [formal_repro_integration_20261012/final_io.md](#formal_repro_integration_20261012-final-io)
- [formal_repro_integration_20261012/formal.md](#formal_repro_integration_20261012-formal)
- [formal_repro_integration_20261012/progress_checks.md](#formal_repro_integration_20261012-progress-checks)
- [mvu_official_restore_20261012/README.md](#mvu_official_restore_20261012-readme)
- [mvu_official_restore_20261012/preview.md](#mvu_official_restore_20261012-preview)
- [mvu_official_restore_20261012/raw_report.md](#mvu_official_restore_20261012-raw-report)

- [final_system_smoke_20261013/README.md](#final_system_smoke_20261013-readme)
- [mvagent_runtime_check_20261013/README.md](#mvagent_runtime_check_20261013-readme)
- [policy_analysis_20261013/README.md](#policy_analysis_20261013-readme)
- [repro_cleanup_20261012/README.md](#repro_cleanup_20261012-readme)
- [repro_cleanup_20261012/history.md](#repro_cleanup_20261012-history)

- [MVAgent 66题历史小批测试](#mvagent_pilot_20261013-readme)

---

<a id="concise_system_smoke_20261013-readme"></a>

## concise_system_smoke_20261013/README.md

原本地路径：`outputs/concise_system_smoke_20261013/README.md`；原文件SHA256：`f6d0d9a6ce65014b0f7b3d72e9a13f2ce51578a9b73547be053bb6563f2c755c`。

# 简洁表达与最佳判断：System 修订小测（2026-10-13）

已参考之前“简洁理由＋最佳判断”的措辞进一步完善两个 System。
冻结终答输出更短，CV712 的冻结决策改为继续取证；但不按题目要求作答和长理由问题仍存在。

## 实际改动

仅修改 [GlobalAgent 的两个 System 常量](../src/mvagent/agents/global_agent/prompts.py)：

- 决策解释用少量短句说明决定性证据或关键缺口，以及为何选择该行动；保留必要比较，
  不复述全部历史、不反复纠结同一组可能性、不展开长篇自我辩论，完整提交本步响应。
- 若有行动可以解决关键缺口或矛盾，针对缺口继续获取证据；证据与题意不一致不足以证明题目无效。
  完成关键比较或没有有用的允许行动时再结束。
- 终答解释同样要求少量短句；当前阶段必须作答，按任务要求提交最佳判断。
  允许解释的位置简述重要不确定性，不能用缺证据的讨论或无依据的“题目无效”替代所要求的结果。

规则不依赖字段名、动作名、模型或 benchmark，不新增固定句数/字符硬限制。
User 模板与构造函数、schema、步数、输出预算及数值 profile 均未改；决策 reason 仍限 1200 字符，
终答 reason 沿用无字符上限，完整响应仍限 2048 token。
AST 对照确认只有两个 System 常量变化，8 个重放请求的其他消息和 schema 与上一版完全相同。

## 设置与范围

Qwen3.5-35B-A3B BF16，seed=0、temperature=0、thinking 关闭，固定同步后端，1×H100、TP1/DP1/C1，无 skill。
复用上一版 4 个开发题的冻结问题/History，各决策和终答一次，共 8 次调用；
随后正式 `eval/agent_eval/run.py --inference-only` 完整跑 CV712 一遍。
对照直接读取上一版 `devbox/final_system_smoke_20261013`，不重跑旧版本。
旧“简洁理由＋最佳判断”User 追加实验仅作措辞参考，不能把它的 8/8 格式结果归于当前 System。

## 冻结请求对照

| 题目 | 决策：前 → 后 | 决策理由字符：前 → 后 | 终答：前 → 后 | 终答 token：前 → 后 |
|---|---|---:|---|---:|
| CV712 | answer → watch_videos | 1200 → 1200 | 非选项说明 → 非选项说明 | 153 → 74 |
| Counting88 | answer → answer | 1200 → 1200 | 非选项说明 → 非选项说明 | 114 → 105 |
| CV376 | answer → answer | 1200 → 1200 | C → C | 206 → 95 |
| BU504 | answer → answer | 374 → 320 | A → A | 107 → 64 |

终答总输出 580 → 338 token（减少 41.7%），累计请求耗时 35.53 → 22.57 秒；
终答理由长度分别 551→245、434→389、1011→463、426→223 字符。
但按题目直接给选项仍为 2/4；CV712 实际输出：
`None of the options are consistently mentioned or shown across all videos.`
Counting88 仍输出 `None of the options are correct as no video shows a ceiling fan.`

CV712 新决策要求联合比较三段视频，并重点检查 video_1 是否遗漏榨汁机使用。
动作参数通过现有运行时校验，但仍选了三个视频的完整区间；这仅证明动作改变，不证明取证效率或判断正确。
其他三个冻结决策仍终答，3/4 理由仍碰到字符上限。
决策输出总 token 930 → 1066，累计请求耗时 64.02 → 75.54 秒；包含新增观看动作的参数。
八次重放合计 1510 → 1404 token、99.56 → 98.11 秒，不能把终答局部收益外推为整体提速。

## 完整 CV712

完整任务正常完成：14 次调用、2719 输出 token、174.10 秒，最终输出 `C`。
Global 轨迹为：分析三个视频 → 向 video_3 索取补充报告 → 终答。
三个决策理由分别 319、1200、1200 字符；终答理由 2555 字符，仍反复比较同一组候选，
说明软性简洁要求在完整任务中依旧可能失效。

终答解释承认 video_2 没有“把果汁倒入玻璃杯”，仍以另两段出现该动作为依据选 C，
过程中还尝试把题目“所有视频”解释为更宽泛的共同主题。
这是实际输出中的证据缺口和题意偏移，不能因成功提交字母就认定推理正确。
本轮不读取参考答案评分，也未逐帧核验视觉报告。

22 次实际调用均无模型错误、结构化错误、修复或 2048-token 截断；完整 token 数量及实际新 System 已核验。
远端完整 compileall 和 2 项已有终答契约测试通过。没有重跑重复性矩阵，也没有测试 9B/27B、非空 skill 或大样本。

## 留档

原始数据仅存 runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/concise_system_smoke_20261013/`：
`manifest.json`、`frozen_repo/`、`driver.py`、配置及样本清单、`replay/`、`agent/records/`、各阶段日志、
`progress.json`、`analysis_source.py`、`analysis_summary.json`。
09:12:53 UTC 完成推理，09:14 完成审计。已从外部 volume 读取审计/manifest/progress/完整原始记录确认持久化。
09:16 UTC 显式 down 释放测试 Sandbox，返回 `terminated`。
09:18 UTC 独立检查确认指定 dev box 已不存在、最终审计和原始记录目录仍可读取，巡检结束。

Commit：`4eb309ba973856ac4ae4b2dcb067535d143bdac7`；工作区含未提交内容，复现以冻结快照为准。
prompts.py SHA256：`a45b327267e62ccfec5b3466eb6e6200610f99151fc1291663c132c05c98289f`。
新旧 System 会影响动作、答案和耗时；空库与进化库须使用同一版本，不能沿用历史分数。


---

<a id="e2e_alignment_20261012-readme"></a>

## e2e_alignment_20261012/README.md

原本地路径：`outputs/e2e_alignment_20261012/README.md`；原文件SHA256：`cc0762108ccb930f410533866ec8fdcbe3a30f067940a646041b073fd13e522b`。

# E2E 旧探针对齐与 RMSNorm 确定性修复

2026-10-12清理补注：本文记录当时的实验。下列旧配置诊断目录（含张量、日志及安装源码副本）已退役，
`e2e_sync_norm_20261012` 的固定配置正式结果仍完整保留；来源与删除范围见
[清理记录](validation_history.md#repro_cleanup_20261012-readme)。共享实现后来移至 `src/models/vlm/local/sync_server.py`。


完成时间：2026-10-12 03:42 UTC。根因定位、候选张量验证、三模型正式 E2E 重测及服务端审计均已完成；GPU Sandbox 已释放。

用户要求是在固定推理环境下，任意合法输入重复时完整 token 一致。不能依靠题目名单、固定答案缓存或只报告通过的小面板。本轮不评正确率，不调用 Judge。

## 已定位的问题

vLLM 0.19.1 的 Qwen3.5 使用 `GemmaRMSNorm`。它的 `forward_cuda` 内部自行调用 `torch.compile`，外层 `enforce_eager=True` 没有关闭这条局部编译路径。静态、动态编译产生不同的 BF16 数值；进程之前处理过的张量形状、布局及 dispatch key 可以影响采用的编译版本。

这与题目的语义无关。同一输入可以因为执行历史不同而经过不同数值路径。小面板的 token 相同，也不等于内部数值相同：35B 的加追踪对照中，首选 token 仍相同，但全部采样步的 logits 已不同。

证据链：

1. 固定 GPU、PID、模型对象、请求字节和调用顺序，旧 `LLM.chat` 复用同一个 Python 请求对象也出现差异，排除 HTTP 为必要条件。
2. 旧配置与旧探针 manifest 的 engine config 逐项相等。恢复 mem0.95、关闭 expandable segments 后仍失败，显存配置变更不是必要条件。
3. 9B、35B 的视觉输入、视觉输出、decoder0 输入完全相同；最早出现差异的位置都是 `decoder0.input_layernorm.output`。
4. 捕获真实输入张量后，单独运行静态/动态编译 RMSNorm，两个输出 SHA 分别逐字节匹配模型中的第一次/第二次 RMSNorm 输出。不是只凭日志猜测。
5. 9B 单算子 A/B/A：先处理 A，再处理其他长度的 view，回到完全相同的 A，774 个 BF16 元素改变，最大绝对差 0.03125；切到 native 稳定，恢复 auto 后再次出现同样变化。另一轮使用独立张量而非 view 的 A/B/A 没有触发该 auto 反例，负结果保留；静态/动态两种数值结果仍不同。
6. 实际 35B 的重编译日志记录了 RMSNorm 的 32768→26025 形状变化及 dispatch key guard 变化。
7. 关闭该算子的局部编译后，9B、35B 各三次真实反例请求的完整 token、采集的层间张量、全部输出 raw/processed logits 均相同；运行时核验所有 GemmaRMSNorm 实际使用 `forward_native`。

安装环境的 `layernorm.py`、`custom_op.py`、`compilation.py`、`qwen3_5.py` 已冻结到 runs volume，并记录 SHA。机制也与 [PyTorch 动态形状说明](https://docs.pytorch.org/docs/main/user_guide/torch_compiler/torch.compiler_dynamic_shapes.html) 和 [编译数值变化说明](https://pytorch.org/blog/training-production-ai-models/) 相符；实测结论以本轮固定版本和捕获张量为依据。

## 旧探针与 HTTP 的受控对照

每组 31 次真实生成。`legacy` 恢复旧 mem0.95/无 expandable；`current` 是修复前配置 的 mem0.94/expandable。两者均未启用本轮 RMSNorm 修复。

| 模型 | 配置 | 响应 | 与同题首轮比较 | token 不一致 |
|---|---|---:|---:|---:|
| 9B | legacy | 31 | 23 | 23 |
| 9B | current | 31 | 23 | 23 |
| 27B | legacy | 31 | 23 | 0 |
| 27B | current | 31 | 23 | 0 |
| 35B-A3B | legacy | 31 | 22 | 22 |
| 35B-A3B | current | 31 | 22 | 22 |

合计 186 响应、136 比较、90 差异。这不是随机抽样的不稳定率：调度刻意重复已知反例，并与冷态首个回答比较。35B 的 CV171 首次 `C`，后续 `A`；9B 的 ICL713 在第139或130个 token 分叉。不能把不同配置的输出差异混入各自重复性指标。

每组同时覆盖旧复用对象、旧重新解析对象、新包装直调、串行 HTTP；所有请求均实际 forward，输入和 prompt SHA 保持相同。

## 修改

- `eval/e2e_eval/harness/sync_vllm.py`：关闭 RMSNorm 内部编译，增加 `compilation_config={'custom_ops': ['all', '-gemma_rms_norm']}`。使用 vLLM 已有配置切到原生 RMSNorm，无第三方补丁或新依赖。
- 保持 BF16、TP1/DP1、每卡并发1、uni/inproc、FlashInfer GDN、seed/temperature 0、thinking关闭、context131072/prefill32768、mem0.94/expandable、prefix/MM关闭、正常解码KV开启。
- 保持 `run.py infer/score/preview`、`--endpoints`、消息、抽帧、输出预算及返回接口。新配置可能改变旧答案，必须使用新结果目录，不能混合旧 profile 的输出。
- 新增 `scripts/diagnose_e2e_alignment.py`、`scripts/diagnose_e2e_norm.py`，保留可复核的同进程路径对照、张量捕获和单算子实验。
- 同步 E2E README、环境 skill 和 `.claude/status.md`。

## 验证状态

- 远端六个 CPU 接口测试、完整 compileall 通过；本机编辑文件 AST 和 `git diff --check` 通过。
- native 反例：9B/35B 各3响应，2次与首轮比较，完整 token 与上述张量/logits全相同。
- native 27B：31响应、23重复比较，0差异。
- 正式入口：`e2e_sync_norm_20261012` 于03:15:52 UTC开始、03:41:45完成，原CLI、33开发题×4遍×3模型；396正式响应、297比较全部一致，0运行错误。

| 模型 | 正式响应 | 重复比较 | 差异 | 实际换卡题目 | 四遍E2E墙钟 |
|---|---:|---:|---:|---:|---:|
| 9B | 132 | 99 | 0 | 33/33 | 213.83秒 |
| 27B | 132 | 99 | 0 | 33/33 | 268.76秒 |
| 35B-A3B | 132 | 99 | 0 | 33/33 | 269.13秒 |

覆盖同进程重复、全部八卡、完整重启后换卡、媒体重新解码及冷热缓存。时间含解码/HTTP/推理/落盘，不含服务加载，只是开发面板测量，不外推全题库。35B 的 CVBench 有4次达到既定128-token预算，完整已生成序列仍相同；另两模型全部自然停止。

额外9个冒烟响应与面板同题比较全部一致。历史八题对照三模型共24响应，新旧配置相比9B/27B/35B分别4/3/5题输出改变；这是配置变更的影响，不计入相同配置重复比较。必须使用新输出目录，不能复用旧答案作为新profile结果。

`server_audit.py` 对全部429实际响应按请求SHA、逻辑输入SHA、prompt SHA、完整token、结束原因、PID/GPU/model object/forward次数做多重集精确匹配，全部通过。三模型全部16端点生命周期与8卡轮换已核验；resume不增加请求且不改raw。详见[正式重测原始报告](validation_history.md#e2e_alignment_20261012-formal)。

正式源码快照SHA256：`73d9b161ed64fbe5dbdd0467cabf6d037dc1085fd7dc21ef434b33b5f2d613c0`。
正式报告SHA256：`394d527f7b79778d3c1540725743f6eee8bb20457ceb3489ea4a35b73ec1c113`。
Sandbox于03:42 UTC正常terminate，随后status返回no devbox；独立检查代理的资源终态核对见[监控记录](validation_history.md#e2e_alignment_20261012-progress-checks)。

## 来源与限制

唯一 Sandbox：`mvagent-e2e-align-20261012` / `sb-8YfOD0amLTz6l2sBZ5Vn1T`，8×H100。HEAD为 `4eb309ba973856ac4ae4b2dcb067535d143bdac7`，包含未提交源码，复现必须使用每个运行的冻结源码，不能只 checkout HEAD。

原始 JSON/PT/日志仅存于 Modal runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/`：

- `e2e_alignment_20261012`：初始对照、源码包、配置对齐、`audit_cause.py`、`causal_metrics.json`、安装源码。
- `e2e_alignment_trace_v2_20261012`：9B/35B 各9次边界和 logits 追踪。
- `e2e_alignment_components_20261012`：两模型各3次第0层组件追踪。
- `e2e_norm_candidate_20261012`：三模型 native 候选及35B compiled对照、实际norm/GDN张量。
- `e2e_norm_kernel_20261012`、`e2e_norm_kernel_v2_20261012`：两种内存视图协议的单算子实验，各60次算子调用。
- `e2e_norm_compile_log_20261012`：35B实际模型3次调用与重编译日志。
- `e2e_sync_norm_20261012`：修复后的正式 E2E 重测。

初版两个 trace 子任务各保存10响应后失败：诊断误将 chunked prefill 丢弃的采样 logits 计作输出 token。后续按 `discard_request_mask` 过滤并从首次请求开始捕获，保留了初版失败记录。追踪会增加同步，35B的首选token可能因此不再翻转，所以保留未加追踪对照，不能仅凭带追踪的短答案通过判定修复。

本次定位并移除了已观察到的历史依赖数值路径；有限回归不能证明所有输入、版本和硬件的数学意义上的绝对确定性。MVAgent 的原服务入口未在本轮改写，旧MVAgent通过记录不能冒充新profile验证。未做正确率或全题库速度外推。


---

<a id="e2e_alignment_20261012-formal"></a>

## e2e_alignment_20261012/formal.md

原本地路径：`outputs/e2e_alignment_20261012/formal.md`；原文件SHA256：`394d527f7b79778d3c1540725743f6eee8bb20457ceb3489ea4a35b73ec1c113`。

# 正式 E2E 同步执行入口验收

使用原 run.py infer / --endpoints / --ids 接口，真实解码512帧/最长边448，原benchmark提示与输出预算保持不变。不评分、不调用Judge。
8个独立BF16/TP1/DP1/C1/uni进程，同步eager、FlashInfer GDN，prefix/MM缓存关闭；HTTP处理和实际forward均在同一个进程主线程串行执行。

| 模型 | 正式CLI响应 | 重复比较 | 不一致 | 曾换到其他GPU的题目 | 全池GPU覆盖 |
|---|---:|---:|---:|---:|---:|
| 35B-A3B | 132 | 99 | 0 | 33/33 | 8/8 |
| 9B | 132 | 99 | 0 | 33/33 | 8/8 |
| 27B | 132 | 99 | 0 | 33/33 | 8/8 |

35B-A3B：另有3个冒烟响应，与面板同题比较0个差异；与旧进程内探针对照8个冻结输入，5个差异；端到端四轮总墙钟269.13秒（含解码/HTTP/推理/落盘，不含服务加载），结束原因{'stop': 128, 'length': 4}。
9B：另有3个冒烟响应，与面板同题比较0个差异；与旧进程内探针对照8个冻结输入，4个差异；端到端四轮总墙钟213.83秒（含解码/HTTP/推理/落盘，不含服务加载），结束原因{'stop': 132}。
27B：另有3个冒烟响应，与面板同题比较0个差异；与旧进程内探针对照8个冻结输入，3个差异；端到端四轮总墙钟268.76秒（含解码/HTTP/推理/落盘，不含服务加载），结束原因{'stop': 132}。

每模型两轮关闭媒体缓存并重新解码；整池重启并轮换GPU后，再跑冷缓存和热缓存各一轮。重复请求均重新推理。
服务重启后对旧输出目录执行相同infer命令，已完成记录被跳过，raw文件及服务请求计数不变。
所有模型的同进程及重启比较均按实际输出逐个token、输入/输入token哈希、文本和结束原因核对；动态端点分配的换卡覆盖按表中实际数统计。
只验收这33道开发题；未跑全题库，不构成任意输入、软件版本或硬件上的保证。CVBench维持128输出token上限，截断单列，不改官方生成预算。
原始记录、服务日志、源码快照：`/runs/devbox/e2e_sync_norm_20261012`。
源码快照SHA256：`73d9b161ed64fbe5dbdd0467cabf6d037dc1085fd7dc21ef434b33b5f2d613c0`。


---

<a id="e2e_alignment_20261012-progress-checks"></a>

## e2e_alignment_20261012/progress_checks.md

原本地路径：`outputs/e2e_alignment_20261012/progress_checks.md`；原文件SHA256：`49d8ec118bdc82164a8a49c0348c62530ec28d67e94f11fe036989959283cf5f`。

# E2E alignment progress checks

All times UTC. Checks are read-only against the Modal run volume and devbox status. Raw experiment output remains on the runs volume.

## 2026-10-12 02:56–02:58 UTC

- **Stage:** eight diagnosis subprocesses started at 02:43; six base profile runs and two current-profile trace runs. By 02:58, the six base runs were complete.
- **Effective outputs:** base profile matrix 186/186 persisted generations across six runs. Each failed initial trace group persisted 10 records, then failed on the 11th attempted generation (index 10); these are partial trace groups.
- **Observed repeat differences:** 9B legacy/current 23/31 each; 27B legacy/current 0/31 each; 35B-A3B legacy/current 22/31 each. Hashes were unchanged for recorded output differences; an observed 9B legacy case first differed at token 139.
- **Latest key evidence:** `9B_current_trace` and `35B-A3B_current_trace` failed on the 11th attempted generation (02:53:50 and 02:50:57) with `AssertionError` at `len(record['logits']) == len(record['token_ids'])`. The incomplete-prefill path yielded more sampler rows than output tokens. The base comparisons continued to produce outputs.
- **Job/health:** `e2e_alignment_20261012` ran with one deployed Modal app task and zero tracebacks. GPUs 0 and 3 were active at the snapshot; HTTP endpoints were down as expected for direct in-process diagnosis.
- **Blocker at that check:** trace capture's sampler row count exceeded output token count on the first captured trace, terminating both trace runs.
- **Next action:** root repaired the trace capture path and launched V2 traces. No duplicate base jobs were submitted.
- **Volume evidence:** `devbox/e2e_alignment_20261012/job.log`, run `progress.json`/`events.jsonl`, and trace logs.

## 2026-10-12 03:12 UTC

- **Stage:** original profile matrix, V2 traces, component trace, norm candidate, and kernel checks all completed. Formal validation `e2e_sync_norm_20261012` began with 35B-A3B; by the latest parent update, `p1_smoke3` and its 33-case `p1_panel0` completed with zero errors, and the controller moved to `historicalbridge`.
- **Effective outputs:** base profile matrix 186/186 persisted responses across six runs. Trace V2 persisted 18/18 responses (9 per model); component traces completed 6/6 responses (3 per model). Norm candidate persisted 3/3 for 9B native, 3/3 for 35B-A3B native, 31/31 for 27B native, and 3/3 for the 35B traced control. Formal validation had 36 successful 35B responses so far (3 smoke + 33 panel), with zero request errors.
- **Latest evidence:** all completed native norm runs were token-identical across their repetitions; 9B and 35B captures also had matching boundaries and logits. The 35B control captured mismatching norm and GDN tensors (34 boundary hashes differ; both compared logits differ despite the same chosen token). V2 traces show matching visual output and decoder0 input, then divergence at decoder0 output; component traces locate 35B's earliest divergence at `decoder0.input_layernorm.output`. Direct legacy calls themselves can differ, so HTTP transport is not required to reproduce the issue.
- **Mechanism checks:** compile logs show Gemma RMSNorm recompiling for shape 32768→26025. The 9B isolated A/B/A tensor probe changed 774 BF16 values (maximum absolute delta 0.03125) under the automatic custom op and stayed stable under native forward. Static/dynamic compiled hashes match the old model's first/second RMSNorm outputs; native forward is a third, distinct stable value. These are targeted mechanism checks, not full E2E validation.
- **Job/health:** profile, V2 trace, component trace, norm candidate, and kernel check jobs finished. `e2e_sync_norm_20261012` remained running with all eight GPUs allocated; health showed one deployed app task and zero tracebacks.
- **Current blocker:** complete the all-model public E2E validation and historical bridge. This run checks output consistency only; no accuracy or Judge evaluation is included.
- **Next action:** main executor continues formal validation through the remaining model runs and bridge phase. No duplicate submissions are needed.
- **Volume evidence:** `devbox/e2e_alignment_trace_v2_20261012/`, `devbox/e2e_alignment_components_20261012/`, `devbox/e2e_norm_candidate_20261012/`, `devbox/e2e_norm_kernel_20261012/`, and `devbox/e2e_sync_norm_20261012/`.

### Follow-up at 2026-10-12 03:16 UTC

- The 27B native norm candidate finished 31/31 with zero repeated-token differences. Formal 35B-A3B validation completed a 3-response smoke phase and a 33-case panel with zero request errors, then moved to the historical bridge. All-model public E2E validation remains in progress.
- Health remains one deployed app task with zero tracebacks. No accuracy judgment or Judge evaluation is part of this run. No independent action is needed while it is progressing normally.

## 2026-10-12 03:30 UTC

- **Stage:** formal E2E validation completed 35B-A3B and 9B p1. It was restarting 9B for p2; 27B has not started in the progress stream yet.
- **Effective samples:** per main executor accounting, 35B-A3B has 132 formal responses and 99 repeat comparisons with 0 differences; 9B has 66 formal responses and 33 repeat comparisons with 0 differences. The separate historical bridge produced 8 responses per model and had 5 differences for 35B-A3B and 4 for 9B. No request errors were reported for the completed panels.
- **Latest evidence:** 9B p1 repeat panel finished at 03:29:33 with no differences; model restart for p2 began at 03:29:39. 35B-A3B completed both p1 and p2 panels with no repeat differences.
- **Job/health:** `e2e_sync_norm_20261012` remains running. All eight GPUs are allocated during the phase transition; app health remains one task and zero tracebacks, with all HTTP endpoints down as expected.
- **Single most important blocker:** finish remaining 9B p2 and 27B validation, then verify task count reaches zero after the main executor releases the sandbox.
- **Next action:** continue read-only progress checks; no duplicate submission or intervention is needed during normal model restart.

## Final check at 2026-10-12 03:42 UTC

- **Stage and result:** formal output-consistency validation finished at 03:41:45. Across all three models it produced 396 formal responses and 297 repeat comparisons, with zero differences and zero request errors. The extra smoke set added 9 responses with zero differences. All 33 questions per model crossed GPUs, and the full-pool restart check passed.
- **Historical bridge:** 24 extra responses included 12 cross-configuration changes (5 for 35B-A3B, 4 for 9B, 3 for 27B). These compare different configurations and are not repeatability failures.
- **Total observed output:** 429 actual responses (396 formal + 9 smoke + 24 bridge). This is a finite output-consistency result; no accuracy or Judge evaluation was run.
- **Resource release:** final read-only `health` check at 03:42:41 reported the Modal app with `tasks=0` and zero tracebacks. `status` reported no dev box. The parent also confirmed the `down` command completed around 03:42 UTC. Periodic monitoring is stopped.
- **Volume evidence:** `devbox/e2e_sync_norm_20261012/` on the runs volume.


---

<a id="e2e_input_preview_20261012-readme"></a>

## e2e_input_preview_20261012/README.md

原本地路径：`outputs/e2e_input_preview_20261012/README.md`；原文件SHA256：`f880517f40619990677cd063a7fa17e3967848c615358e3ef5a271a2e4e660f3`。

# E2E 真实输入预览（2026-10-12）

> 历史预览：生成后用户要求恢复MVU-Eval官方答题指令。下方MVU样例记录修改前的文本，当前实现已恢复官方原文；原始预览不改写。

通过当前 `eval/e2e_eval/run.py preview` 在 Modal CPU 上实际构造三题输入，参数为 `--frames 512 --max-side 448`。
任务 `ap-8mOQqTuklu9PkQonKqRCZM` 返回rc0，已结束；无GPU、模型推理或评分。

下方 role 块展示发送前的实际 messages 顺序，英文文字原样保留。连续图片合并成数量和尺寸说明；
真实请求为逐张独立 `image_url` 内容块，并不把方括号占位文字发给模型。
`generation` 和 `media` 是预览元数据，不属于提示词；其中的调试视频路径不会送入模型。
正式客户端还显式设置 `seed=0`、`enable_thinking=false`。这里未展示模型 chat template 的特殊token及视觉processor内部编码。

- CVBench 664：system + user；先4组视频帧，再指令/问题/选项；512帧。
- MVU-Eval ICL713：只有user消息；先4组视频帧，再问题/作答指令/选项；短视频共401帧。
  问题中前三个视频的示范标签属于ICL题目本身，并未加入待答Video 4的标准答案。
- CrossVid BU836：system + user；先指令/问题/选项，再3组视频帧，最后 `Your answer:`；510帧。

原始预览留在runs volume：`devbox/e2e_input_preview_20261012/preview.md`；下方未改动其文本。

```text

################ cvbench:664 (Cross-video Object Recognition) ################
generation: {"max_tokens": 128, "temperature": 0.0, "top_p": 1.0}
media: {"frames": 512, "frame_max_side": 448, "videos": [{"video": "389/1QSxsXzHh4A.mp4", "source_frames": 5801, "source_fps": 25.0, "original_size": [854, 480], "size": [448, 251], "frames": 128}, {"video": "389/1RLbiIWhYQQ.mp4", "source_frames": 6836, "source_fps": 30.0, "original_size": [1280, 720], "size": [448, 252], "frames": 128}, {"video": "389/bAoqNN_RdaI.mp4", "source_frames": 8895, "source_fps": 30.0, "original_size": [1280, 540], "size": [448, 189], "frames": 128}, {"video": "389/SdXrmpOsnw4.mp4", "source_frames": 5828, "source_fps": 30.0, "original_size": [1270, 720], "size": [448, 253], "frames": 128}]}
===== role: system =====
[text]
You are a helpful assistant.
===== role: user =====
[text]
Video 1:

[128 x image/jpeg 448x251]
[text]
Video 2:

[128 x image/jpeg 448x252]
[text]
Video 3:

[128 x image/jpeg 448x189]
[text]
Video 4:

[128 x image/jpeg 448x253]
[text]
Select the best answer to the following multiple-choice based on the listed all videos. Respond with only the letter (A, B, C, or D) of the correct option.
What object is used across all videos to aid in bonsai shaping?
A. Red gloves.
B. Pruning shears.
C. Aluminum wire.
D. Pliers.
Answer with the option's letter (A, B, C, or D) from the given choices directly.

################ mvu_eval:ICL:713 (ICL) ################
generation: {"max_tokens": 8192, "temperature": 0.0, "top_p": 1.0}
media: {"frames": 401, "frame_max_side": 448, "videos": 4, "frames_per_video": 128}
===== role: user =====
[text]
Video 1:

[100 x image/jpeg 448x251]
[text]
Video 2:

[105 x image/jpeg 448x252]
[text]
Video 3:

[96 x image/jpeg 448x252]
[text]
Video 4:

[100 x image/jpeg 448x252]
[text]
The answer of the Video 1 is 3.0, the answer of the Video 2 is 3.2, the answer of the Video 3 is 3.4. Based on the above video and answers, infer what the question is, and then answer the question about Video 4.
[text]
Select the correct answer from the options. Return exactly one uppercase option letter and no explanation.
[text]
A. 2.4
B. 1.5
C. 2.0
D. 1.8

################ crossvid:BU:836 (BU) ################
generation: {"max_tokens": 8192, "temperature": 0.0, "top_p": 0.95}
media: {"frames": 510, "frame_max_side": 448}
===== role: system =====
[text]
You are a helpful video analyzer.
===== role: user =====
[text]

Provide you several videos and a multiple-choice question with 1-3 correct answer choices.
Watch the videos carefully, and think about the question based on the information from the videos.
Only output the capital letters of ALL your choices, e.g., "BCD".

Question:
Which activities are performed in all three videos?

Options:
A. Cooking food
B. Tidying up a closet/cabinet
C. Talking on a phone
D. Sneezing

Input frames:
Video 1:

[170 x image/jpeg 336x448]
[text]
Video 2:

[170 x image/jpeg 448x336]
[text]
Video 3:

[170 x image/jpeg 448x252]
[text]


Your answer:


```


---

<a id="e2e_input_preview_20261012-preview"></a>

## e2e_input_preview_20261012/preview.md

原本地路径：`outputs/e2e_input_preview_20261012/preview.md`；原文件SHA256：`92ec0bb92d00bb09ecac86b3a38b84029d7437f7f8cb3d2495e4f21b3b2aae90`。


################ cvbench:664 (Cross-video Object Recognition) ################
generation: {"max_tokens": 128, "temperature": 0.0, "top_p": 1.0}
media: {"frames": 512, "frame_max_side": 448, "videos": [{"video": "389/1QSxsXzHh4A.mp4", "source_frames": 5801, "source_fps": 25.0, "original_size": [854, 480], "size": [448, 251], "frames": 128}, {"video": "389/1RLbiIWhYQQ.mp4", "source_frames": 6836, "source_fps": 30.0, "original_size": [1280, 720], "size": [448, 252], "frames": 128}, {"video": "389/bAoqNN_RdaI.mp4", "source_frames": 8895, "source_fps": 30.0, "original_size": [1280, 540], "size": [448, 189], "frames": 128}, {"video": "389/SdXrmpOsnw4.mp4", "source_frames": 5828, "source_fps": 30.0, "original_size": [1270, 720], "size": [448, 253], "frames": 128}]}
===== role: system =====
[text]
You are a helpful assistant.
===== role: user =====
[text]
Video 1:

[128 x image/jpeg 448x251]
[text]
Video 2:

[128 x image/jpeg 448x252]
[text]
Video 3:

[128 x image/jpeg 448x189]
[text]
Video 4:

[128 x image/jpeg 448x253]
[text]
Select the best answer to the following multiple-choice based on the listed all videos. Respond with only the letter (A, B, C, or D) of the correct option.
What object is used across all videos to aid in bonsai shaping?
A. Red gloves.
B. Pruning shears.
C. Aluminum wire.
D. Pliers.
Answer with the option's letter (A, B, C, or D) from the given choices directly.

################ mvu_eval:ICL:713 (ICL) ################
generation: {"max_tokens": 8192, "temperature": 0.0, "top_p": 1.0}
media: {"frames": 401, "frame_max_side": 448, "videos": 4, "frames_per_video": 128}
===== role: user =====
[text]
Video 1:

[100 x image/jpeg 448x251]
[text]
Video 2:

[105 x image/jpeg 448x252]
[text]
Video 3:

[96 x image/jpeg 448x252]
[text]
Video 4:

[100 x image/jpeg 448x252]
[text]
The answer of the Video 1 is 3.0, the answer of the Video 2 is 3.2, the answer of the Video 3 is 3.4. Based on the above video and answers, infer what the question is, and then answer the question about Video 4.
[text]
Select the correct answer from the options. Return exactly one uppercase option letter and no explanation.
[text]
A. 2.4
B. 1.5
C. 2.0
D. 1.8

################ crossvid:BU:836 (BU) ################
generation: {"max_tokens": 8192, "temperature": 0.0, "top_p": 0.95}
media: {"frames": 510, "frame_max_side": 448}
===== role: system =====
[text]
You are a helpful video analyzer.
===== role: user =====
[text]

Provide you several videos and a multiple-choice question with 1-3 correct answer choices.
Watch the videos carefully, and think about the question based on the information from the videos.
Only output the capital letters of ALL your choices, e.g., "BCD".

Question:
Which activities are performed in all three videos?

Options:
A. Cooking food
B. Tidying up a closet/cabinet
C. Talking on a phone
D. Sneezing

Input frames:
Video 1:

[170 x image/jpeg 336x448]
[text]
Video 2:

[170 x image/jpeg 448x336]
[text]
Video 3:

[170 x image/jpeg 448x252]
[text]


Your answer:



---

<a id="formal_repro_integration_20261012-readme"></a>

## formal_repro_integration_20261012/README.md

原本地路径：`outputs/formal_repro_integration_20261012/README.md`；原文件SHA256：`db6fe219ac582a3584c998c9d6a7b99a3648642163cf6e0446bda06d1a483cda`。

# 正式 E2E / MVAgent 复现配置接入与验收

2026-10-12 完成。正式入口已接入此前验证的 BF16 / TP1 / DP1 / 单卡并发1、同步 in-process eager、FlashInfer GDN、原生 GemmaRMSNorm 配置。三模型均实测通过，原 CLI 参数和输出记录结构保留，新增可选 `--inference-only`。

## 本次修改

- [共享服务与固定配置](../src/models/vlm/local/sync_server.py)：由 E2E 专用文件移入 `src`，支持 Agent 的紧凑 grammar、video `media_io_kwargs` 与模型别名；固定版本并校验实际 forward、输入和完整 token。`serve.py` 继续提供原 E2E 启动接口。
- [模型服务管理](../src/models/vlm/local/service.py)、[模型池](../src/models/pool.py)、[API provider](../src/models/vlm/api/providers/openai_compatible.py)：依据 `execution_profile` 启动同步服务，验证已有服务配置和 GPU，默认保留 token/input/worker 审计。普通非此 profile 的模型（例如 Judge）保留原服务能力。
- [批量执行](../src/mvagent/batch.py)：一道题的所有 Global/Video/Selector 调用固定到一个副本，视频并行线程共享串行模型租约。生产 execution YAML 的8副本接口保留。
- [E2E 入口](../eval/e2e_eval/run.py)：共享服务源码进入冻结记录；复用帧缓存时自动绑定逐题输入 SHA，已有独立输入审计则严格验证。首次缓存绑定不冒充独立解码审计。
- [Agent 入口](../eval/agent_eval/run.py)：增加 `--inference-only`，仅保存轨迹和审计，不评分、不调用 Judge；9B 已完成结果的 `--resume` 实测通过。
- [模型配置解析](../src/mvagent/configs/model_config.py)：三个 Modal inference YAML、Agent 默认35B/9B YAML及进化配置的35B Actor统一引用 固定 profile，去掉冲突旧参数；默认权重路径统一到 `/weights`。
- 文档、AGENTS、环境 skill、旧诊断脚本引用和 devbox prelaunch 的同步服务停止逻辑一起更新。Agent Prompt、动作和评分规则没有修改。

## 实测

8卡申请排队10分钟后取消，实际用同一 Sandbox 的两张 H100 80GB，三个模型依次运行；每卡执行设置与生产8副本一致。本次未重新测试每模型8副本同时满载。

|模型|E2E 响应 / 重复比较|完整 Agent 轨迹 / 比较|Agent 调用 / 对应调用比较|差异|
|---|---:|---:|---:|---:|
|9B|6 / 3|4 / 2|80 / 40|0|
|27B|6 / 3|4 / 2|86 / 43|0|
|35B-A3B|6 / 3|4 / 2|90 / 45|0|
|合计|18 / 9|12 / 6|256 / 128|0|

E2E 三个历史开发样例分别来自 CVBench、MVU-Eval、CrossVid。Agent 使用历史长程开发样例 `mvu_eval:Comparison:818` 和 `crossvid:MOC:521`；最长轨迹9B/27B/35B分别33/28/24次调用。每个对应调用的输入/prompt哈希、完整 token IDs、文本和结束原因均一致，完整语义轨迹也一致。

0模型错误、0结构化校验失败。9B有4次、27B有2次达到原有2048-token输出上限，两遍均一致；35B均正常stop。这是输出一致性结果，没有评估正确率、答案格式或非空 skill。

274个正式客户端响应（18 E2E + 256 Agent）与292条服务端记录匹配；其余18条均为4-token服务准备探针。原始审计见 [audit.md](validation_history.md#formal_repro_integration_20261012-audit)，实际输出和耗时见 [formal.md](validation_history.md#formal_repro_integration_20261012-formal)。例如35B在 `cvbench:664` 输出 `C`，实际 token IDs 为 `[34, 248046]`。

远端完整 `compileall`、8个接口/配置/整题租约测试、token审计和Agent入口自检通过。仅对新增/改变的接口做小规模验收，未重跑此前的大矩阵。

## 最终 I/O 修正与来源

主矩阵完成后，仅将共享 `write_json` 恢复为临时文件加原子替换。AST核对确认推理函数和配置均未改变。最终版本再次通过远端compileall和8个接口测试，并重启35B服务，对同一已测CV题补两次正式E2E：1次重复比较0差异，且与主矩阵旧源码结果一致。见 [final_io.md](validation_history.md#formal_repro_integration_20261012-final-io)。这2次响应与主矩阵分开报告。

所有原始 JSON、token、轨迹、日志及源码快照都保留在 Modal runs volume `wxu-evolve-agent-runs-20261006`：

- 主矩阵：`devbox/formal_repro_integration_20261012_r2`，archive SHA256 `eedbf661d1925ff86e59a0960232fb6ee5deb81f821ed4ffc4ffa8270b5bbaac`。
- 最终I/O版本：`devbox/formal_repro_final_io_20261012`，archive SHA256 `24d08333f07f4c1a56a3e62576e4b2b0c1576ee564953119c214b671a1f158da`。
- 主矩阵共享服务源码 SHA256 `3ba83b26db413cf058ac960acfdde77e272f471953e45ed43073d36d0c33fc08`；最终为 `524536b0b3ec5b07aab64b926878635afc1ec4fb2cd438922365953ba1096ccd`。
- HEAD `4eb309ba973856ac4ae4b2dcb067535d143bdac7`，含未提交修改；复现须使用归档源码，不能仅用HEAD。

最初一次driver在加载前因 `/runs` 符号链接的路径检查误判退出，没有产生GPU推理样本；已修复，失败日志保留在 `devbox/formal_repro_integration_20261012/job.log`。不把这个启动失败计为模型复现失败，也不删除负记录。

GPU Sandbox `sb-so6nGI32d84YT7MYky0sjA` 已于15:10 UTC前正常terminated；独立检查确认无活动Sandbox、app任务数0，巡检已停止。记录见 [progress_checks.md](validation_history.md#formal_repro_integration_20261012-progress-checks)。本机只保存代码与Markdown。有限开发样例通过不构成任意输入/软件/硬件的通用确定性证明；非空skill、全量benchmark与新8副本吞吐不在本次验收范围。


---

<a id="formal_repro_integration_20261012-audit"></a>

## formal_repro_integration_20261012/audit.md

原本地路径：`outputs/formal_repro_integration_20261012/audit.md`；原文件SHA256：`c1930499c1687f53a3b39c6bcc29b7ddbc31941857d3d7d255f1950f68045e78`。

# 原始记录核对

{
  "models": [
    {
      "model": "9B",
      "client_responses": 86,
      "server_responses": 92,
      "readiness_probes": 6,
      "agent_finish_reasons": {
        "stop": 76,
        "length": 4
      },
      "full_text_and_finish_equal": true
    },
    {
      "model": "27B",
      "client_responses": 92,
      "server_responses": 98,
      "readiness_probes": 6,
      "agent_finish_reasons": {
        "stop": 84,
        "length": 2
      },
      "full_text_and_finish_equal": true
    },
    {
      "model": "35B-A3B",
      "client_responses": 96,
      "server_responses": 102,
      "readiness_probes": 6,
      "agent_finish_reasons": {
        "stop": 90
      },
      "full_text_and_finish_equal": true
    }
  ],
  "source_difference_only": "write_json",
  "request_errors": 0
}

每个正式客户端响应与服务端真实forward日志逐token匹配。额外服务响应均为4-token启动/复用探针。
所有Agent对应调用的输入哈希、prompt哈希、完整token、文本、结束原因均一致。
AST核对确认最终源文件与主矩阵仅write_json函数不同，推理代码和配置无变化。


---

<a id="formal_repro_integration_20261012-final-io"></a>

## formal_repro_integration_20261012/final_io.md

原本地路径：`outputs/formal_repro_integration_20261012/final_io.md`；原文件SHA256：`3145961d45db3fbcbcf7a1841631920abbb0db85d103da23121844536c50bfa9`。

# 最终原子落盘修正补验收

仅将共享 manifest 写入恢复为临时文件+原子替换，推理代码与配置不变。

最终版本远端 compileall、8个接口测试通过；35B重启服务后同题2次正式E2E响应、1次重复比较均一致，且与主矩阵该题结果一致。

实际输出："C"

源码SHA256：24d08333f07f4c1a56a3e62576e4b2b0c1576ee564953119c214b671a1f158da


---

<a id="formal_repro_integration_20261012-formal"></a>

## formal_repro_integration_20261012/formal.md

原本地路径：`outputs/formal_repro_integration_20261012/formal.md`；原文件SHA256：`2054f8c6531f18bb9e65fb2f5de3087f28d4446e8dc6b4a0d0cdec82b6160235`。

# 正式入口小规模回归

三个 BF16 模型；两张 H100 顺序换模型；原正式 CLI；无评分/Judge。

|模型|E2E响应/比较|Agent轨迹/比较|模型调用/比较|差异|
|---|---:|---:|---:|---:|
|9B|6/3|4/2|80/40|0|
|27B|6/3|4/2|86/43|0|
|35B-A3B|6/3|4/2|90/45|0|

每题全部 Agent 调用均固定在一个 GPU/进程；每个响应均验证真实 forward、输入与完整 token IDs。
小样本仅验收正式入口接入，不替代此前大规模复现证据；本次没有重启矩阵或非空 skill 评估。

原始记录：`/runs/devbox/formal_repro_integration_20261012_r2`。源码 SHA256：`eedbf661d1925ff86e59a0960232fb6ee5deb81f821ed4ffc4ffa8270b5bbaac`。

## 9B

实际输出（未评价正确率）：

```json
{
  "actual_e2e_outputs": {
    "cvbench:664": "C",
    "mvu_eval:ICL:713": "Based on the provided videos and answers, we can deduce the question being asked.\n\n### Analysis of the Videos and Answers\n\n- **Video 1:** Shows a female diver performing a dive from a 3-meter springboard. The given answer is `3.0`.\n- **Video 2:** Shows the same female diver performing another dive from the 3-meter springboard. The given answer is `3.2`.\n- **Video 3:** Shows the same female diver performing a third dive from the 3-meter springboard. The given answer is `3.4`.\n- **Video 4:** Shows a male diver performing a dive from a 10-meter platform.\n\nThe pattern from Videos 1, 2, and 3 suggests that the question is asking for the score of the dive shown in each video. The scores are increasing (`3.0`, `3.2`, `3.4`), which is typical for a series of dives in a competition where a diver's performance improves.\n\n### Inferring the Question\n\nThe question is most likely: \"What is the score for the dive shown in the video?\"\n\n### Answering the Question for Video 4\n\nVideo 4 shows a male diver from a different event (London 2012 Olympics, as seen on the background banner). We are not given the score for this dive, and we must infer it from the options provided.\n\nThe options are:\n- A. 2.4\n- B. 1.5\n- C. 2.0\n- D. 1.8\n\nIn competitive diving, scores are typically given on a scale from 0 to 10. A score of `3.0` or higher is considered a good dive. The scores in the first three videos are all above `3.0`. The score for the dive in Video 4 is likely to be lower than the previous ones, as it is from a different athlete and event.\n\nAmong the given options, `2.4` is the highest score. It is a plausible score for a dive that is not perfect but is still executed with some skill. The other options (`1.5`, `2.0`, `1.8`) are quite low and would indicate a significant error or a very poor dive. Given that the diver in Video 4 completes the dive without a major fall or error, a score of `2.4` is the most reasonable inference among the choices.\n\nTherefore, the most likely score for the dive in Video 4 is `2.4`.\n\nA",
    "crossvid:FSA:121": "213,245"
  },
  "actual_agent_answers": {
    "crossvid:MOC:521": "C",
    "mvu_eval:Comparison:818": "C"
  },
  "agent_max_calls": 33,
  "timings": [
    {
      "kind": "e2e",
      "repeat": 0,
      "seconds": 39.04
    },
    {
      "kind": "agent",
      "repeat": 0,
      "seconds": 354.569
    },
    {
      "kind": "e2e",
      "repeat": 1,
      "seconds": 23.663
    },
    {
      "kind": "agent",
      "repeat": 1,
      "seconds": 324.347
    }
  ]
}
```

## 27B

实际输出（未评价正确率）：

```json
{
  "actual_e2e_outputs": {
    "cvbench:664": "C",
    "mvu_eval:ICL:713": "C",
    "crossvid:FSA:121": "The segment from 213s to 245s in Video 1 shows the host adding the cooked chicken back into the pan with the sauce and tossing it to coat. This is the final step of combining the components.\n\nIn Video 2, the equivalent action occurs after the sauce has been prepared and the chicken has been fried. The host adds the fried chicken to the wok with the sauce and stirs everything together. This process is shown from approximately 289s to 317s.\n\nTherefore, the functionally equivalent step in Video 2 is:\n289,317"
  },
  "actual_agent_answers": {
    "crossvid:MOC:521": "C",
    "mvu_eval:Comparison:818": "C"
  },
  "agent_max_calls": 28,
  "timings": [
    {
      "kind": "e2e",
      "repeat": 0,
      "seconds": 36.578
    },
    {
      "kind": "agent",
      "repeat": 0,
      "seconds": 559.06
    },
    {
      "kind": "e2e",
      "repeat": 1,
      "seconds": 32.663
    },
    {
      "kind": "agent",
      "repeat": 1,
      "seconds": 529.734
    }
  ]
}
```

## 35B-A3B

实际输出（未评价正确率）：

```json
{
  "actual_e2e_outputs": {
    "cvbench:664": "C",
    "mvu_eval:ICL:713": "C",
    "crossvid:FSA:121": "200,208"
  },
  "actual_agent_answers": {
    "crossvid:MOC:521": "None of the options can be selected due to missing evidence",
    "mvu_eval:Comparison:818": "D"
  },
  "agent_max_calls": 24,
  "timings": [
    {
      "kind": "e2e",
      "repeat": 0,
      "seconds": 25.549
    },
    {
      "kind": "agent",
      "repeat": 0,
      "seconds": 337.087
    },
    {
      "kind": "e2e",
      "repeat": 1,
      "seconds": 15.573
    },
    {
      "kind": "agent",
      "repeat": 1,
      "seconds": 315.369
    }
  ]
}
```


---

<a id="formal_repro_integration_20261012-progress-checks"></a>

## formal_repro_integration_20261012/progress_checks.md

原本地路径：`outputs/formal_repro_integration_20261012/progress_checks.md`；原文件SHA256：`e3e9f9f7c2a7666a6609df558228be35e42cfff6d91e3466f5bff0b58a414259`。

# Formal E2E / MVAgent integration progress checks

## 2026-10-12 13:52 UTC

- Completed experiment units: 0 GPU units; valid model samples: 0.
- Completed implementation evidence: remote `compileall`, 8 CPU interface/config/per-question lease tests, and token-audit self-check all passed by 13:42 UTC. Worktree now includes the shared sync server at `src/models/vlm/local/sync_server.py`, formal E2E and Agent integration, per-question replica lease, input-cache binding, and inference-only CLI; `.claude/status.md` was updated at 13:47 UTC.
- Stage: one unique Sandbox `DEVBOX_NAME=mvagent-formal-repro-20261012` is still provisioning/building. Parent reports app tasks=0 and no state file/GPU measurement. No Modal inspection was run because no GPU task is active yet.
- Planned sample: 8 GPUs hosting 9B×2, 27B×3, 35B×3 replicas; each model E2E 3 questions×2 and Agent 2 questions×2; verify through `scripts/verify_formal_repro.py`; remote results under `/runs/devbox/formal_repro_integration_20261012`.
- Single current blocker: Sandbox startup has not completed, so the first end-to-end GPU sample cannot begin. Next action: let the existing `up` finish, then start/monitor the already planned verification without creating another Sandbox.
- 13:52 UTC state update from parent: Sandbox `sb-sDznjNYil0yfQdbSriLbHU` was created at 13:46:20; image build completed in 47.77s, but the single `up` process is still waiting for the first sandbox exec (resource queue suspected). Modal app `ap-lluPvOtRg7tYTpbvSVmWFd` reports tasks=0. No inference sample yet; keep waiting on this same `up`.

## 2026-10-12 13:56 UTC update

- Completed experiment units and valid GPU samples remain 0.
- Stage changed from provisioning to replacement allocation. The 8-GPU Sandbox `sb-sDznjNYil0yfQdbSriLbHU` remained at tasks=0 for about 10 minutes; parent explicitly cancelled it at 13:56 UTC, and it returned `terminated`. The old `up` exited with “Sandbox was cancelled by user”; this was client cancellation, not a GPU/model failure.
- One replacement request is pending under the same `DEVBOX_NAME`, now requesting H100:2. Plan is sequential testing of all three models with the same sample counts; production execution YAML remains configured for 8 replicas. No duplicate request is active.
- Current blocker: replacement Sandbox allocation/first exec has not started. Next action: wait for this single request, then run the planned small regression sequentially.

## 2026-10-12 14:03 UTC update

- Completed experiment units and valid GPU samples remain 0.
- The replacement Sandbox `sb-so6nGI32d84YT7MYky0sjA` was allocated on H100:2; parent reports the `up`/113.8 MB code push completed with rc=0. Final CPU `compileall`, 8 interface tests (including 5 formal model configs), Agent self-check, and driver `--help` passed. The CPU Modal app completed.
- Read-only devbox health: app `ap-lluPvOtRg7tYTpbvSVmWFd` state=deployed, tasks=1, tracebacks in the last hour=0. Read-only GPU/endpoint status: both GPUs at 4 MiB / 0%; ports 8100–8107 and 8110 are down. Therefore no model server or inference measurement has started yet.
- Stage: latest driver push completed; parent is starting `formal_repro_integration_20261012`. Current blocker: inference task has not started / server endpoints are not up. Next action: monitor the already planned run and check once endpoints/tasks show actual progress.

## 2026-10-12 14:04 UTC update

- The formal verification job was submitted under tag `formal_repro_integration_20261012` (controller PID 62); parent confirms two real H100 80GB devices and planned sequential 9B→27B→35B service runs. However, read-only status immediately showed the job `finished`, both GPUs idle (4 MiB / 0%), and all service endpoints down.
- Job log exited before inference: `verify_formal_repro.py: Use a fresh directory in the runs volume`. The requested output path `/runs/devbox/formal_repro_integration_20261012` failed its fresh-directory guard; no `progress.log` exists there. Valid GPU samples remain 0.
- Current blocker: output-path freshness check prevents the controller from beginning. Next action belongs to the primary executor: select a new run output directory/tag and restart the planned job once.
- Clarification from parent (14:05 UTC): the error alone does not establish that the target directory already contains results. The guard also validates the resolved `/runs` prefix and `source.tar.gz`; `/runs` may be a symlink whose `.resolve()` result fails the expected prefix. Parent is inspecting the resolved path and directory contents. Preserve the failed log; valid GPU samples remain 0.

## 2026-10-12 14:07 UTC update

- Parent inspected the output-volume guard: `/runs/devbox/formal_repro_integration_20261012` resolves to `/__modal/volumes/vo-WSTKijaHW9LRTLHV3g9I75/devbox/formal_repro_integration_20261012`, and the target contained only the failed job's 123-byte `job.log`; there was no previous archive. Thus the initial failure was path-resolution validation, not stale experiment data.
- Parent fixed the guard to compare against `Path('/runs').resolve()`, switched to the shared `harness.common.git` helper to avoid container git ownership trouble, and froze `prelaunch.py`. They are pushing these changes, then will rerun with tag `formal_repro_integration_20261012_r2` on the existing Sandbox. No new Sandbox is planned.
- Completed GPU units / valid samples: 0. Stage: code push before retry. Current blocker: retry cannot start until push completes; next action is observe the existing Sandbox and r2 job.

## 2026-10-12 14:18 UTC update

- Primary executor reports the first 9B round: all 3 E2E questions completed and input-manifest checks passed. Agent has 1 completed trajectory (`crossvid:MOC:521`, 7 model calls); a second Agent trajectory (`mvu_eval:Comparison:818`) has 31 model responses and is still running, with 0 model errors. Counted as 3 completed E2E responses and 1 completed Agent trajectory; the unfinished Agent trajectory is not counted as a completed unit.
- Independent read-only health: app deployed, tasks=1, tracebacks in last hour=0. GPU memory is 78,167 / 78,587 MiB; GPU1 at 32% utilization. `devbox status` still lists its standard ports 8100–8107 and 8110 as down, while the parent reports the integration task's events advancing every few seconds; this port view does not establish task failure.
- Stage: active 9B E2E/Agent regression; no external blocker. Parent reports controller PID 95 is the sole owner and output tag is `formal_repro_integration_20261012_r2`. Continue observing; do not submit or stop anything.

## 2026-10-12 14:23 UTC update

- Correcting the 14:18 port interpretation: the service is on ports 8100/8101. The status probe can time out because `SerialServer` handles `/v1/models` and model forwards on the same main thread; while a long request runs, metadata probes cannot reply. Port-down output during a forward is an observation limit, not evidence the endpoints are elsewhere or the server failed. Use process/GPU state and the run's request/event files to judge progress.
- Read-only output-volume progress for the 9B stage: `progress.json` reports phase `agent-1`, all 6/6 E2E responses complete, and 2 Agent runs launched. `agent-0` reports 2/2 trajectories complete (summary: 2 samples completed); `agent-1` reports 1/2 trajectories complete as of 14:20:58 UTC. Thus 3/4 Agent trajectories are complete and the fourth remains in progress. No model errors reported by parent.
- Stage: active 9B Agent run; after it finishes, controller proceeds sequentially to 27B and 35B. No blocker; latest event evidence confirms ongoing work.

## 2026-10-12 14:38 UTC update

- Independent read-only health: app deployed, tasks=1, tracebacks in last hour=0. GPU memory is 78,601 / 79,921 MiB, GPU utilization 46% / 42%; 8101 reports up (8100's metadata probe may time out during forwards). The r2 job is still running.
- Volume progress has advanced from 9B to 27B. 9B is complete: 6/6 E2E responses and 4/4 Agent trajectories. For 27B, `progress.json` reports all 6 E2E responses complete; `agent-0/progress.json` reports 2/2 trajectories complete. The `agent-1` output directory exists but does not yet have its progress file, so its two trajectories are not counted complete. 35B has not started.
- Cumulative completed samples: 12 E2E responses; 6 complete Agent trajectories (4 on 9B, 2 on 27B). Current stage: 27B Agent, with its second batch pending/starting. No actual error or blocker; GPU and health show active work. Continue observing the same controller.
- Parent follow-up at 14:39 UTC: 27B Agent second round is now active; its first round made 43 successful model calls (28 + 15), with no failures. Correction to the separate status message: nvidia-smi reports MiB, so 78,601 / 79,921 MiB is about 76.8 / 78.1 GiB, respectively. The earlier progress-file line correctly preserves the raw MiB values.

## 2026-10-12 14:46 UTC update

- Primary executor reports 27B complete: E2E 6 responses / 3 comparisons; Agent 4 trajectories / 2 full-trajectory comparisons / 86 model calls (43 paired-call comparisons), with 0 differences. 9B completed 6 E2E responses / 3 comparisons and 4 Agent trajectories / 2 comparisons / 80 model calls (40 paired-call comparisons), also passed. Cumulative complete: 12 E2E responses, 8 Agent trajectories, 166 model calls, 0 reported differences.
- Stage: 35B-A3B model loading. No blocker or reported error; the single controller continues.
- Parent found and restored atomic `write_json` persistence (temp file + rename, three I/O lines), with no inference-path change. This fix has not been pushed during the active run so the frozen source hash stays fixed. After the main matrix, parent plans to push it, rerun final CPU regression, and perform two 35B E2E requests on the final version; the ongoing run will remain separately identified by its frozen source.

## 2026-10-12 14:54 UTC update

- Independent read-only health: app deployed, tasks=1, tracebacks in last hour=0. GPU memory 78,159 / 78,639 MiB; GPU0/1 utilization 16% / 0%. Port 8101 is up; other service probes may time out during a serialized forward.
- 35B-A3B is active. Its output `progress.json` reports phase `e2e-1`, with the first 3 E2E responses completed; `agent-0/progress.json` and summary show 2/2 Agent trajectories complete. The second E2E run is in progress; the second Agent run is not yet complete. 9B and 27B remain fully complete.
- Cumulative completed samples now: 15 E2E responses and 10 Agent trajectories (9B: 6 + 4, 27B: 6 + 4, 35B: 3 + 2). The primary executor remains the only controller; no blocker or reported model error.

## 2026-10-12 15:01 UTC update

- Primary executor reports the main three-model matrix complete and passed. By model: Agent calls 9B 80, 27B 86, 35B 90; aggregate 256 model calls / 128 paired-call comparisons. Agent: 12 complete trajectories / 6 full-trajectory comparisons. E2E: 18 responses / 9 comparisons. All reported 0 token differences, 0 model errors, and 0 structured-output errors.
- Main report has been generated; its source archive and report retain the main-matrix SHA. Stage now is final persistence-fix acceptance: parent is pushing the restored atomic `write_json` change, then plans CPU 8-test regression and two single-GPU 35B E2E requests on `cv664` under a separate tag `formal_repro_final_io_20261012`. These checks are supplemental and separately identified from the completed main matrix.
- Current blocker: final push/verification has not completed. Parent owns the controller and plans to down the Sandbox and stop monitoring after the supplemental check.

## 2026-10-12 15:13 UTC final check

- Primary executor reports all authorized work complete. Final I/O supplement passed: 2 E2E responses / 1 comparison, 0 token differences, and output `C` with token IDs `[34, 248046]` matches the original 35B same-input result. Final compileall and all 8 CPU interface/config tests passed; AST comparison confirms final shared source differs from the main-matrix source only in atomic `write_json` persistence.
- Main matrix remains separately identified: 18 E2E responses / 9 comparisons; 12 Agent trajectories / 6 full-trajectory comparisons; 256 model calls / 128 paired-call comparisons; 0 differences, model errors, or structured-output errors. Client/server audit: 274 client records matched 292 server records, with 18 extra preparation probes; call text and finish reasons also matched.
- Independent resource teardown confirmation: `devbox status` returns `no dev box: run up first`; Modal health reports app `ap-lluPvOtRg7tYTpbvSVmWFd`, state=deployed, tasks=0, tracebacks in last hour=0. No GPU Sandbox or running task remains.
- Parent reports final source SHA `524536b0...`, matching the GPU supplemental check; final README/formal/audit/final_io reports and `.claude/status.md` are complete. No further experiment action remains; periodic checks stop here.


---

<a id="mvu_official_restore_20261012-readme"></a>

## mvu_official_restore_20261012/README.md

原本地路径：`outputs/mvu_official_restore_20261012/README.md`；原文件SHA256：`941c4099015a60b54a5b8924ce516dd4df4f4d8aab7d2adf2b1a6a689a2d8bb0`。

# MVU-Eval 官方答题指令恢复（2026-10-12）

已按用户要求恢复：

> Please select the correct answer from the options. Answer with the option’s letter directly.

`harness/mvu_eval.py`直接保留官方`build_messages_base`返回的原句，保留该句出现一次的校验；
删除自定义指令常量和替换操作，protocol记录实际官方原文。问题、选项、消息顺序、帧数、分辨率、
无文件名标签、temperature/seed、thinking、输出预算及评分均未改动。

`verify_formal_repro.py`改用本次输出目录内的共享媒体缓存，避免读取绑定旧提示词的历史input_audit。
运行CLI不变；新协议必须使用新输出目录与输入哈希清单，不能覆盖此前验收结果。

## 验证

- 本机改动文件AST、文档链接、`git diff --check`通过。
- Modal完整compileall及8项现有接口/配置/缓存测试通过。
- 原preview入口实际生成`mvu_eval:ICL:713`，官方原句恰好出现一次，自定义句不存在；401帧、最长边448。
- 1×H100 80GB，Qwen3.5-9B BF16，保留已验收固定配置后端；正式infer CLI执行同一题两次，每次真实推理。
- 2响应/1次比较，完整1226输出token、输入SHA、prompt token SHA、文本、结束原因均一致；0请求错误，均自然stop。
- 未评分、未调用Judge；未重新运行三模型大面板、跨卡或重启矩阵。

实际输出以`Based on the provided videos and answers...`开头，长解释后以`Answer: A`结尾。
这说明恢复官方指令后仍可能先解释；重复一致不等于只输出选项或答案正确。评分/输出后处理未调整。
完整文本见[原始报告](validation_history.md#mvu_official_restore_20261012-raw-report)，消息顺序见[实际预览](validation_history.md#mvu_official_restore_20261012-preview)。

## 来源

- runs volume：`devbox/mvu_official_restore_20261012/`；含smoke.py、CPU检查日志、服务日志、repeat0/repeat1原始响应与各自冻结源码、manifest及input_audit。
- MVU适配器SHA256：`3db442a46149f04d19ef665069f46cbf11d01dd8da66ef58ee7a55f0e9a5a7c0`。
- 输入SHA256：`c824bb507e78471ee076edbf5d04bed887fc33b1f5b4f445a99d28eda51685bb`。
- Sandbox `sb-wCgKph7F8EwHOVESx92zDV` 已正常terminated；本地仅Markdown，无原始JSON或媒体下载。


---

<a id="mvu_official_restore_20261012-preview"></a>

## mvu_official_restore_20261012/preview.md

原本地路径：`outputs/mvu_official_restore_20261012/preview.md`；原文件SHA256：`452a5c988d35e0ffa9e093264c87aa77089eefa39f3fb50978b6fae19a3a6bbd`。


################ mvu_eval:ICL:713 (ICL) ################
generation: {"max_tokens": 8192, "temperature": 0.0, "top_p": 1.0}
media: {"frames": 401, "frame_max_side": 448, "videos": 4, "frames_per_video": 128}
===== role: user =====
[text]
Video 1:

[100 x image/jpeg 448x251]
[text]
Video 2:

[105 x image/jpeg 448x252]
[text]
Video 3:

[96 x image/jpeg 448x252]
[text]
Video 4:

[100 x image/jpeg 448x252]
[text]
The answer of the Video 1 is 3.0, the answer of the Video 2 is 3.2, the answer of the Video 3 is 3.4. Based on the above video and answers, infer what the question is, and then answer the question about Video 4.
[text]
Please select the correct answer from the options. Answer with the option’s letter directly.
[text]
A. 2.4
B. 1.5
C. 2.0
D. 1.8


---

<a id="mvu_official_restore_20261012-raw-report"></a>

## mvu_official_restore_20261012/raw_report.md

原本地路径：`outputs/mvu_official_restore_20261012/raw_report.md`；原文件SHA256：`1f56bd59d7a8e75504c94233e6f14f8d87b7af90371117fbe83ee8af5cb2e95e`。

# MVU-Eval official instruction restoration

{
  "model": "Qwen3.5-9B BF16",
  "case": "mvu_eval:ICL:713",
  "responses": 2,
  "comparisons": 1,
  "differences": 0,
  "instruction": "Please select the correct answer from the options. Answer with the option’s letter directly.",
  "output": "Based on the provided videos and answers, we can deduce the question and then apply the logic to find the answer for Video 4.\n\n### Analysis of the Provided Information\n\n- **Video 1:** Shows a female diver performing a dive from a 3-meter springboard. The given answer is `3.0`.\n- **Video 2:** Shows a female diver performing a dive from a 3-meter springboard. The given answer is `3.2`.\n- **Video 3:** Shows a male diver performing a dive from a 3-meter springboard. The given answer is `3.4`.\n- **Video 4:** Shows two male divers performing a synchronized dive from a 10-meter platform.\n\n### Inferring the Question\n\nThe values `3.0`, `3.2`, and `3.4` are very close to each other and are consistent with the scores awarded in competitive diving. Therefore, the question is most likely asking for the score of the dive shown in the video.\n\n### Answering the Question for Video 4\n\nThe video shows a synchronized dive from a 10-meter platform. In competitive diving, dives from higher platforms (like the 10m platform) are generally more difficult and carry a higher base score than dives from springboards (like the 3m springboard).\n\n- The dives in Videos 1, 2, and 3 are from a 3-meter springboard, and their scores are in the low 3s.\n- The dive in Video 4 is from a 10-meter platform, which is a significantly more challenging event.\n\nGiven this context, the score for the dive in Video 4 should be higher than the scores for the dives in Videos 1, 2, and 3.\n\nLet's evaluate the options:\n- A. 2.4: This is lower than all the previous scores, which is inconsistent with the increased difficulty of the dive.\n- B. 1.5: This is also lower than the previous scores and is an unusually low score for a competitive dive.\n- C. 2.0: This is still lower than the previous scores.\n- D. 1.8: This is also lower than the previous scores.\n\nAll the provided options (A, B, C, D) are lower than the scores given for the first three videos. This suggests that the question might be asking for a different metric, such as a difficulty rating on a different scale, or there is an inconsistency in the provided data. However, based on the principle that a more difficult dive should receive a higher score, none of the options are logically consistent with the trend established by the first three videos.\n\nIf we must choose the most plausible answer from the given options, assuming the question is about the score and there's an error in the options or the premise, option A (2.4) is the highest value among the choices. But it's important to note that this contradicts the established pattern.\n\nGiven the constraints and the need to select one of the options, and considering that all options are lower than the previous scores, the question might be flawed. However, if we assume the question is simply asking for a value from the list, and we have to pick one, we would typically pick the one that is most different or extreme, but that's not a good rule. Let's re-examine the problem. Perhaps the question is not about the score but about something else entirely, like the number of divers (which is 2 for Video 4). But the options are decimals.\n\nLet's reconsider the scores. Maybe the scores are not for the dive itself but for some other aspect. Or maybe the question is \"What is the score of the dive in Video 4?\" and the correct answer is not listed, but we have to choose the closest one. In that case, since all options are lower, it's a bad question.\n\nHowever, let's look at the options again. If the question was \"What is the score of the dive in Video 4?\", and the correct answer was, say, 3.6, then none of the options would be correct. But if the question was \"Which of the following is NOT a possible score for a dive in this competition?\", then all options could be correct.\n\nGiven the ambiguity, let's assume the question is indeed asking for the score of the dive in Video 4, and there is a mistake in the options. The most reasonable score for a 10m platform dive would be higher than 3.4. Since none of the options are higher, we have to conclude that the question or the options are incorrect.\n\nBut if we have to choose, let's assume the question is \"What is the score of the dive in Video 4?\" and the correct answer is 3.6, which is not an option. In that case, we cannot answer the question correctly.\n\nHowever, if we assume that the question is \"What is the score of the dive in Video 4?\" and the correct answer is one of the options, then we have to choose the one that is most likely. Given that the scores are increasing (3.0, 3.2, 3.4), the next score should be higher than 3.4. None of the options are higher than 3.4.\n\nTherefore, the question is likely flawed. But if we have to choose, let's assume the question is \"What is the score of the dive in Video 4?\" and the correct answer is 3.6, which is not an option. In that case, we cannot answer the question correctly.\n\nGiven the constraints, I will select the option that is the highest among the choices, as it is the most likely to be the intended answer, even though it is lower than the previous scores.\n\nAnswer: A",
  "output_tokens": 1226,
  "finish_reason": "stop",
  "input_sha256": "c824bb507e78471ee076edbf5d04bed887fc33b1f5b4f445a99d28eda51685bb",
  "scoring_requested": false,
  "protocol": {
    "official": "inference/main.py build_messages_base + analyze.py first-character score",
    "generation": {
      "max_tokens": 8192,
      "temperature": 0.0,
      "top_p": 1.0
    },
    "frames_per_video": "min(512 // number_of_videos, source frames)",
    "max_side": 448,
    "video_label": "official '[Video k] <file name>' replaced by 'Video k:'",
    "answer_instruction": "Please select the correct answer from the options. Answer with the option’s letter directly.",
    "score": "output.strip().upper()[:1] == ground_truth"
  }
}


---

<a id="final_system_smoke_20261013-readme"></a>

## final_system_smoke_20261013/README.md

原本地路径：`outputs/final_system_smoke_20261013/README.md`；原文件SHA256：`4ebfbb5e5ea94b30ed651a67d585ad7143e28a98a2f875c979044b77d495162f`。

# Global 决策与终答 System 小测（2026-10-13）

本轮将基础规则分别放入 GlobalAgent 决策和独立终答的 System。
代码接入正常，但通用提示仍未解决所测难例的提前终答、长理由和答案形式问题。
之前 User 追加“简洁理由＋最佳判断”的 8/8 结果不属于这版 System。

## 改动范围

运行时代码只改 [prompts.py](../src/mvagent/agents/global_agent/prompts.py) 的两个常量：

- 决策 System：保留任务定义、条件和标识；区分观察、推断、信息缺失与否定证据；
  有用的取证机会用于解决关键缺口或矛盾，再判断是否结束；简洁保留决定性证据和比较。
- 终答 System：依现有证据提交最有根据的判断，按题目要求表达重要限制；保留关键比较，结论与依据一致。

两者都不绑定 `reason`、`answer` 等字段名、动作名、JSON 格式、模型、benchmark 或固定句数。
User 模板及构造函数、schema、动作接口、技能注入、数值配置均未改。
决策 reason 仍限 1200 字符；终答 reason 无字符上限；完整响应仍限 2048 token。
AST 对照确认本轮运行时代码只有两个 System 常量变化；各重放请求的其他消息和 schema 与历史逐项相同。

这是阶段不同的两次模型调用：决策决定是否继续取证，终答只在结束后依据已有证据作答。
改善终答格式不能证明决策改善；简洁表达也不能替代正确的证据比较。
基础规则与 skill 的具体策略仍通过原路径组合，空库与进化库评估须使用同一版本。

## 实验范围

- Qwen3.5-35B-A3B BF16，1×H100，TP1/DP1/C1，固定 固定同步数值 profile，seed=0、temperature=0、thinking 关闭。
- 4 个既有开发题，各重放一次冻结决策检查点和一次冻结终答请求，共 8 次模型调用。
  原始证据来自 `devbox/reason_relaxation_20261013/repeat0`；没有执行重放决策产生的动作。
- 再经正式 `eval/agent_eval/run.py --inference-only` 完整跑 `crossvid:BU:504` 一遍，无 skill。
- 不评分、不调用 Judge、不重复运行、不重做一致性矩阵。此次检查接入和实际输出，不能证明泛化收益。
- 远端完整 compileall、2 项已有终答契约测试通过；实际调用均核验完整 token 数量、worker forward 记录和新 System。

## 冻结检查点结果

| 题目 | 决策动作 | 决策理由字符 | 终答输出 | 终答 token | 终答秒数 |
|---|---|---:|---|---:|---:|
| CV712 | answer | 1200 | None of the options are consistently shown across all videos. | 153 | 10.24 |
| Counting88 | answer | 1200 | None of the options are correct as no video shows a ceiling fan. | 114 | 7.23 |
| CV376 | answer | 1200 | C | 206 | 11.92 |
| BU504 | answer | 374 | A | 107 | 6.14 |

4/4 决策通过现有参数校验且全部终答，3/4 理由碰到字符上限；CV712 和 Counting88
仍认为证据与题目冲突却结束，没有继续取证。CV712 理由末尾是 `Does '`，Counting88
末尾是 `contradicts the 's`；自然 `stop` 不代表理由语义完整，字符上限仍是实际约束。

4 个终答都生成有效 JSON，但只有 2 个直接按题目给出选项；另 2 个返回解释句。
因此结构校验通过、非空和任务要求的答案形式是三件不同的事。没有新增答案枚举或格式强制器。
CV376 的终答保留了狭窄住宅街道、停车和驾驶学员的风险比较并选 C；未核验答案正确性。

8 次重放共 1510 输出 token；0 服务错误、0 结构化错误、0 修复、0 token-budget 截断。
这里的 3 次字符上限与 2048-token 截断不同，不能报告“理由已不再截断”。

## 完整 Agent 冒烟

BU504 完整运行成功：12 次模型调用、1161 输出 token、79.45 秒，2 次 Global 决策、1 次独立终答。
0 模型错误、0 结构化错误、0 修复、0 token-budget 截断，两个阶段实际使用了新 System。

实际终答为 `A`；理由比较了三个视频：视频 1 有躺在地板上，视频 2 另有开门，
视频 3 另有放毯子，三者共有的动作是躺在地板上。此处只记录输出，未对照参考答案评分。
它验证了一道完整任务能够运行，不能抵消冻结难例的负结果，也不代表吞吐或稳定性的大规模验收。

## 留档与限制

原始数据只存 runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/final_system_smoke_20261013/`：
`manifest.json`、`frozen_repo/`、`driver.py`、`config.yaml`、`execution.yaml`、`samples.json`、
`replay/`、`agent/records/`、各阶段日志、`progress.json`、`analysis_source.py`、`analysis_summary.json`。
总共 20 次实际模型调用；最终审计时间 08:50 UTC。
已从 dev box 外部读取 volume 的最终审计、manifest、progress 和完整 Agent 原始记录，确认持久化；
08:54 UTC 显式释放测试 Sandbox，返回 `terminated`。
独立检查代理随后确认该 dev box 已不存在，down 后仍可读取最终审计和 progress，巡检已结束。

代码 commit：`4eb309ba973856ac4ae4b2dcb067535d143bdac7`；包含未提交工作区，复现以冻结快照为准。
本轮 prompts.py SHA256：`2c79799c4a468b14f8107b7c356b6105f72f624832a1f113037a4370afc99233`。

本轮没有验证 9B/27B、非空 skill、大样本或正确率，也没有测量新 System 的逐 token 重复性。
数值后端未变，不能把历史重复性实测写成新提示已重测；本次已观察到的决策与答案形式问题仍保留。


---

<a id="mvagent_runtime_check_20261013-readme"></a>

## mvagent_runtime_check_20261013/README.md

原本地路径：`outputs/mvagent_runtime_check_20261013/README.md`；原文件SHA256：`41337465ffa1ac371cd547421feb04345e7cf3b19162b3ab02f23b79950c88b8`。

# MVAgent 运行与答案格式检查（2026-10-13）

后续用户确认：最终answer维持开放非空字符串，由模型根据题意输出所需格式，不新增选项枚举或题型硬约束。
下文格式失败是模型表现的观测，不据此收窄运行时Schema；真实基础设施故障单独处理。

用户要求与E2E同步开展MVAgent测试，并检查历史结果是否表明系统仍有稳定性问题。
当前先做4题×2遍×3模型的正式接口检查，共24条计划轨迹，不评正确率；完整基线范围尚待澄清，未把小测当作全量测试。

## 最终结果（2026-10-13 02:50:51 UTC）

三模型共24条轨迹全部完成，406次模型调用、12组整轨迹比较、203组配对调用均无差异；
模型错误、结构化错误、顶层运行错误均为0。2卡Sandbox正常结束并释放。

| 模型 | 轨迹 | 调用 | 配对调用 | 格式偏差（含重复） | 达到token上限的调用 | forced_with_gaps轨迹 |
|---|---:|---:|---:|---:|---:|---:|
| 9B | 8 | 130 | 65 | 4 | 4 | 2 |
| 27B | 8 | 136 | 68 | 0 | 2 | 2 |
| 35B-A3B | 8 | 140 | 70 | 2 | 0 | 0 |

35B的MOC521两次均输出`None of the options can be selected due to missing evidence`（21调用/轨迹），
其余三题分别为cv664=`C`、MVUComparison818=`D`、FSA121=`110,120`，两遍一致。
本轮没有评正确率；有限定点面板不能代表全量格式失败率，也不构成任意输入的重复性证明。
用户决定暂不实施提出的三项工程改进，后续用现有系统跑66题小批效果/可靠性测试，见
[新实验](validation_history.md#mvagent_pilot_20261013-readme)。下面保留运行过程记录。

## 实际运行

- 独立2×H100，Sandbox `sb-hsloDLrPaseNO2nIIZsJgm`，DEVBOX_NAME `mvagent-agent-check-20261013`；4小时上限。
- 后台任务 `mvagent_runtime_check_20261013`，PID284，01:52 UTC启动；三模型顺序9B→27B→35B-A3B。
- BF16、TP1/DP1/C1，整条轨迹固定副本；无skill，Global/Video各5步、2048输出token、512帧，沿用正式MVAgent输入处理。
- 每模型两遍：cvbench:664、mvu_eval:Comparison:818、crossvid:MOC:521、crossvid:FSA:121。
- 原始输出、逐调用token/输入/worker审计、配置及冻结源码均在runs volume `wxu-evolve-agent-runs-20261006` 的
  `devbox/mvagent_runtime_check_20261013/`；本机只存本说明。控制器为`scripts/check_mvagent_runtime.py`，原Agent CLI不变。
- 两张卡均完成模型服务启动。任务结束自动释放本Sandbox，现有8卡E2E不受影响。

## 已修复的运行配置

发现MVAgent客户端仍等待600秒，落后于共享服务已提高的1800秒上限。
三份inference no-skill、两份Agent eval默认配置、dynamic35B的Actor改为1860秒；Embedding配置不改。
四份inference执行配置的整题时限从1800改为7200秒，容纳多步调用。模型数值参数、Prompt、动作、生成预算未改变。
远端完整compileall、8项接口测试和诊断自检通过；自检明确验证了“JSON schema接受`}`，答案格式检查拒绝`}`”，
并验证缺失记录与token差异会被单独报告。新运行使用新快照，未覆盖历史结果。

## 02:04 UTC 首轮实际输出

9B第一遍4题全部完成，共65次模型响应，模型错误0、结构化校验错误0。

| 样例 | 实际答案 | 调用数 | 答案状态 | 格式 |
|---|---|---:|---|---|
| cvbench:664 | `}` | 15 | answered | 不合法，选择题需要选项 |
| mvu_eval:Comparison:818 | `C` | 33 | forced_with_gaps | 选择题格式合法，未判正确性 |
| crossvid:MOC:521 | `C` | 7 | answered | 选择题格式合法，未判正确性 |
| crossvid:FSA:121 | `No equivalent step found in Video 2` | 10 | answered | 不符合`start,end`区间格式 |

两次observer调用达到2048 token上限；这是原生成预算，单列截断，不改预算以改善表面通过率。
## 02:13 UTC 更新

9B两遍全部完成：**8轨迹、130次模型调用、4组整轨迹比较、65组调用比较，完整token/输入及语义轨迹0差异**。
模型错误0、结构化错误0；cv664和FSA121的格式问题各重复两次，共4条格式失败记录。
4次调用达到2048-token预算；2条MVU轨迹达到步数上限并返回forced_with_gaps。
这些是定点选择的小面板，格式失败比例不代表全量数据。

额外读取了cv664原始`global_answer`响应：模型直接生成`"answer":"}"`；该调用301个输出token、finish=`stop`。
原始reason为1200字符，运行时strip后1199字符。因此这条异常答案已经存在于模型原始JSON中；
当前证据没有把它归因于解析器，也不是2048-token预算截断。字符上限是否促成这一结果尚未做消融。

27B已经开始正式请求，35B排在其后；此时不声称三个模型全部检查完成。
独立Luna在02:13只读确认9B结果、27B实际推进，health为2个活动任务、近1小时0traceback；巡检已结束。
会话关闭后主任务继续自动运行和释放GPU，不宣称仍有后台代理巡检。

## 稳定性问题的证据与边界

1. **相同输入的输出重复性**：历史已完成888轨迹/11544调用，666轨迹对照与9125次同输入调用比较均0差异。
   正式HTTP入口另有12轨迹/256调用的小回归。这证明所测面板的重复性，不等于接口输出都有效或全量不会故障。
2. **最终答案格式偏差，当前已复现**：`src/mvagent/agents/global_agent/schema.py`的answer复用开放非空字符串schema；
   `GlobalAgent.answer()`只strip，`MVAgentEngine._request_terminal_answer()`直接标记answered。
   所以`}`和自由文本区间都能通过结构化校验；外层batch的ok代表流程返回，不能当成答案格式合格。
   cv664的reason为1199字符，接近1200字符约束；这是观测，尚未通过消融证明该限制就是错误答案的成因。
3. **超时与故障恢复**：最近600秒超时引发整池关闭是E2E serve.py的事件，不把它当成已经观察到的MVAgent整池故障。
   MVAgent共用同步后端，但其ModelPool会隔离异常副本；recover只探测已恢复服务，不主动重启退出的模型进程。
   客户端/整题时限已经对齐；异常副本自动重启与故障注入尚未验证。
4. **终止/错误状态需分开看**：步数上限会合法地触发forced_with_gaps；terminal fallback也可能返回空答案而不抛异常。
   运行状态、model_error、structured_invalid、输出截断、最终格式必须分开报告。当前没有修改回答器Prompt、schema或fallback。

本轮格式检查复用`eval/agent_eval/export_results.py`的语法规则；它不是正确率评分，也不是对所有题型语义约束的完整证明。


---

<a id="policy_analysis_20261013-readme"></a>

## policy_analysis_20261013/README.md

原本地路径：`outputs/policy_analysis_20261013/README.md`；原文件SHA256：`6723ac08962b2b50c988dab416b992827a6ec673624a726c0e25ae4209958404`。

# MVAgent 决策、终答和判定标准传递分析（2026-10-13）

用户要求先分析，不修改代码。本轮只在 runs volume 的独立实验目录构造候选请求；
没有修改或启用新的生产 Prompt、schema、src、eval 或推理配置。

## 范围与证据

- 模型：Qwen3.5-35B-A3B BF16，seed=0、temperature=0、thinking关闭，现有固定配置同步后端。
  小探针用两个独立H100副本，每卡TP1/DP1/C1；每调用2048输出token，其余字段上限不变。
- 8个既有开发样例：CV75、TR1398、NC928、CV712、Counting88、PEA525、CV376、BU504。
  复用 `reason_relaxation_20261013/repeat0` 的冻结问题、History和原始请求，不读取标准答案作提示。
  基线复用已有响应，不重新跑重复性矩阵。
- 63个文本探针、9个视觉探针，共76次实际模型调用（含4次既有JSON修复）。
  0服务错误，4次初始输出因2048-token预算截断而结构化无效，4次修复均成功。
  33个Global决策均通过现有运行时参数校验；结构有效不代表策略或语义正确。
- 当前与历史冻结源码的221个src/config代码和配置文件哈希一致，结束时生产哈希仍未变。
  commit为 `4eb309ba973856ac4ae4b2dcb067535d143bdac7`，实际复现以冻结工作区快照和manifest为准。
- 这次是固定检查点的请求级对照，没有运行修改后的完整Agent轨迹，没有评分或调用Judge。
  单独的定义对照还固定了视频内容哈希、FPS、schema和生成参数。
- 07:57 UTC完成最终审计；随后显式释放测试Sandbox，08:00独立检查确认容器退出、审计已持久化，巡检结束。

原始记录：runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/policy_analysis_20261013/`。
主要文件：`manifest.json`、`frozen_repo/`、`driver.py`、`probes/`、`visual/`、
`strict_conflict/`、`criteria_literal/`、`criteria_original_literal/`、`cap_audit.json`、
`source_comparison.json`、`analysis_source.py`、`analysis_summary.json`。
候选完整英文指令保存在manifest与逐请求记录中，补充组另有自身manifest及driver。

## 1. Global决策reason的硬上限

对原66题做只读统计：137次Global决策中，13次reason恰好1200字符，涉及13题，均选择answer。
61题只做2次决策，5题做3次决策，没有耗尽5步预算。相关性本身不是上限导致提前作答的证明。

对8题的相同第二次决策检查点，加入同一“1–3句简洁决策依据”要求，只对reason做限长消融：

| 设置 | answer / 继续取证 | 生成token总数 | 累计调用秒数 | 触及reason字符上限 |
|---|---:|---:|---:|---:|
| 当前历史基线 | 8 / 0 | 1930 | 未重新计时 | 6/8 |
| 保留1200字符上限＋简洁要求 | 8 / 0 | 1728 | 127.21 | 5/8 |
| 仅移除决策reason上限＋同一简洁要求 | 8 / 0 | 3027 | 211.72 | 不适用 |

两组新增请求均无截断或修复。取消上限没有改变这8题的动作选择，生成token反而增加约75%。
NC928的理由扩展到5369字符/1225token，仍选择answer。不能将上限视为这些提前作答的唯一原因；
目前没有证据支持直接取消生产决策reason上限。

## 2. 证据冲突时的动作策略

在无字符上限、相同简洁要求基础上，分别加入一般冲突指导和更明确的条件式规则。
提示中明确该检查点是第2/5步，仍有取证机会；动作集合、参数schema和预算保持不变。

| 策略 | answer | 继续取证 | token总数 | 累计调用秒数 | 截断/修复 |
|---|---:|---:|---:|---:|---:|
| 一般冲突指导 | 7 | 1 | 5044 | 336.89 | 2/2 |
| 严格条件式指导（首组结果后的单组补测） | 5 | 3 | 6953 | 473.82 | 2/2 |

- 一般指导仅使CV712改为watch_videos。
- 严格指导使NC928、PEA525改为watch_videos，CV712改为只复查video_1的analyze_videos。
  已有充分共同动作证据的BU504仍选择answer。
- Counting88在严格指导下仍选择answer，而且先耗尽2048token再修复。JSON修复不保证遵守取证策略。
- NC928严格组reason长达6902字符。部分联合观看请求仍覆盖整段长视频，不能只按“继续取证次数”评价策略质量。
- TR1398仍把History中的 `3→1→4→2` 称为与选项B完全一致，但原题B实际为 `2→1→4→3`。
  这是可直接核查的选项比对错误，不是字符上限或解析器错误。

结论：提示策略能影响动作，但不能保证缺证据时必然继续取证。尚未执行这些新增动作，
不能声称它们提供了更好的证据或改善了整题答案；暂不将该候选直接接入固定评测。

## 3. 终答篇幅与最佳判断

在相同的冻结History上，只改变终答提示词。reason仍无字符硬上限，answer仍是开放非空字符串；
没有加入选项枚举或按任务硬编码答案格式。

| 设置 | 格式合格 | 需JSON修复的题 | 输出token总数（含修复） | 累计终答秒数 |
|---|---:|---:|---:|---:|
| 当前固定设置的历史响应 | 6/8 | 2/8 | 6089 | 360.16 |
| 只加简洁要求 | 4/8 | 0/8 | 765 | 53.83 |
| 只加必须提交最佳判断的要求 | 7/8 | 0/8 | 1998 | 133.95 |
| 两者结合 | 8/8 | 0/8 | 880 | 59.63 |

结合版要求：理由用1–3句说明决定性证据和不确定性，不反复重述History；既然已进入不可继续取证的终答阶段，
即使证据存在缺口，也将不确定性写入reason，并在answer按题目要求提交最佳判断，不用拒答或说明文字替代答案。
这是软性指令，句数本身并非硬性保证（最长reason仍1112字符）。

CV712由初次2048-token截断后修复，变为一次93-token响应直接给出A；Counting88由不选择变为A。
但其他答案也改变，例如TR1398从D变C、CV376从C变A、PEA525从D变A。
因此该改动是答题策略变化，不是无语义影响的格式修复。

上述约6倍速度差只针对选出的8题终答阶段，不能外推整个Agent或全benchmark。
这是目前最值得后续单独验证并考虑采用的候选，但不能由格式合格推断正确率提高。

## 4. 判定标准逐级传递

以PEA525的3个视频检查Global指令→VideoPlanner的what→Observer：

1. 给Global加入“忠实保留题目定义”的指令后，局部instruction复制了四个错误类别名称，
   仍未保留四条定义正文。字段没有达到字符上限，遗漏发生于模型改写。
2. VideoPlanner加不加额外保留指令，都能继续传递这些名称；已经丢掉的定义正文无法凭空恢复。
3. 新局部指令还弱化了原本“先判断动作是否发生，再判断是否正确”的门槛。
   Observer有时把四个动作都归为正确，另一个视频只返回 `, 'wrong order'`，没有说明哪个动作错在哪里。
4. 在这些请求中直接附入四条定义正文，保持同一视频哈希、FPS和其他请求字段，视觉报告没有实质改善。
5. 为排除改写指令的混杂，再做3个“完全保留原始观察问题＋只附定义正文”的对照。
   视频1、2重新区分了未发生的动作与已发生动作；但所有被报告为已发生的动作仍被判为正确，
   没有解决该例的错误动作识别问题。这个presence区分原始基线本来就有，不能算附定义带来的新收益。

结论：信息在模型转述中丢失、以及条件被改写，都是需要关注的系统设计问题。
若后续改进，应保留题目明确给出的定义原文和“是否发生”等前提，避免只保留类别名或反复转述。
但本例没有证明仅靠补齐定义就能提高视觉判断；模型对动作顺序、错误性质的理解以及采样是否充分仍未排除。

## 建议与限制

- 优先考虑终答的“简洁理由＋最佳判断”软性提示；正式采用前需要观察其对整题输出和正确率的影响。
- 不直接全面放开字段，也不因当前结果单独取消Global决策reason的硬上限。
- 冲突时的条件式取证策略和原文标准传递值得继续研究，但目前不能视为已验证的完整Agent改进。
- 8题是按已知问题选取的开发面板，定义传递只有1道题/3个视频；没有新准确率评测、逐帧事实核验、
  9B/27B实验或修改后完整rollout。有限样例不能给出工程原因在全部失分中所占比例。
- 固定评测配置保持原样。所有原始结果只在runs volume，本地只留本报告和状态说明。


---

<a id="repro_cleanup_20261012-readme"></a>

## repro_cleanup_20261012/README.md

原本地路径：`outputs/repro_cleanup_20261012/README.md`；原文件SHA256：`21616c0355cb36d1351c2f3e0e8f34a15e32d00f8dc6c88ef2d7fec1db1367b2`。

# 过时推理实验结果清理（2026-10-12）

用户已确认当前重复性测试基线，要求清理过时、不符合要求的配置结果。
第一阶段处理历史推理配置探索；随后按用户追加指令删除FP8权重（见末节）。推理代码和当前运行配置不变。

完成于2026-10-12 15:54 UTC，远端校验通过、CPU任务正常退出。

| 项目 | 结果 |
|---|---:|
| 删除的旧文件 | 43,517 |
| 删除前逻辑大小 | 105,084,250,514 bytes（105.08 GB / 97.87 GiB） |
| 整目录删除 | 139 |
| 仅保留回归夹具的旧目录 | 15 |
| 清理前后SHA256一致的夹具 | 93 |
| 未纳入清理、目录元数据未变的目录 | 43 |
| 本地移除的旧报告目录 / Markdown | 14 / 27 |

冻结清单SHA256：`7a38ee2967bfa110f1b02362b19f7cb2157db96494e4de4b3a6d410b498ee05c`。
合并历史Markdown SHA256：`5f8a5f42a7b4e3cd5dd6b6e0b446a9de1f75acf003457e49b7818aca748b838d`。

## 保留

- 当前 `qwen35-bf16-flashinfer-sync` 的 [正式接口回归](validation_history.md#formal_repro_integration_20261012-readme)、
  [扩大E2E及Agent测试](repro_expanded_20261012/README.md)、[RMSNorm修复验收](validation_history.md#e2e_alignment_20261012-readme)，
  包括原始结果、固定帧缓存、冻结源码、配置和审计记录。
- 当前验证脚本依赖的旧路径夹具：8个冻结E2E请求、33份Agent题目来源、旧33题面板与分片、
  24份选长任务用的summary、3份旧协议reference、3份权重元数据、6组历史配置/权重元数据。
  这些是输入和来源依赖，不再作为当前协议的验收结果。
- 三模型BF16、Embedding/Judge权重、benchmark数据、skill进化结果、既有准确率基线及此前H200完整评测记录；FP8权重按后续指令删除。
- [失败结论与协议差异摘要](validation_history.md#repro_cleanup_20261012-history)，以及远端合并的原Markdown报告；不保留过时大体积原始输出副本。

## 删除范围

旧FP8、TP8、原生DP8、异步服务、缓存/并发调优、定制迁卡、Triton GDN及FlashInfer（未关闭 RMSNorm 内部编译）的
原始响应/轨迹、日志、诊断张量和临时缓存。混有当前测试夹具的目录仅保留白名单文件。
精确到文件的清单只存于 runs volume `wxu-evolve-agent-runs-20261006`：

- `devbox/repro_cleanup_20261012/plan.json`：冻结清理清单，含删除前文件大小与mtime。
- `retained_fixture_hashes.json`：清理前后核对的夹具SHA256。
- `result.json`：最终删除统计及校验结果；`progress.json`：已处理目录。
- `historical_reports.md`：27份旧报告及清理前4份状态/运行说明，附原路径和每份SHA256。
- `cleanup.py`、`cleanup_cpu.py`：本次一次性盘点及清理源码；不是后续运行入口。

本地清理14个旧报告目录；同步精简 `.claude/status.md`、环境skill、E2E/Agent README，
在仍保留的历史handoff及根因报告上标明原始诊断数据已退役。

## 验证与边界

清理前核对本项目Modal任务数为0，操作限定该runs volume的明确实验目录。
每项删除均受冻结清单和保留路径约束；删除后逐目录核对剩余文件，93个夹具SHA全部不变，
旧33题面板的来源SHA也通过。43个未纳入清理的目录名称、大小与mtime保持不变；没有重新哈希其全部内容。
32个本地文档链接、skill符号链接、辅助脚本语法及 `git diff --check` 检查通过；无新GPU推理。

最初SDK逐项删除效率偏低，在完成49项后停止唯一执行器，转为一个Modal CPU任务续跑同一清单。
CPU首次因辅助脚本依赖未安装的Modal客户端退出；第二次被未统一解析挂载/符号链接的路径保护拦住。
随后改用标准库和真实路径边界、只删除符号链接本身，最终任务
`ap-KUPMt6zsZvCAvbbDzewjwU` 返回rc0，runs volume提交完成。失败尝试不算清理完成；最终统计以result.json为准。

删除统计使用文件逻辑字节数，不代表Modal立即释放的物理空间或账单变化。
已删除的旧原始数据无法再做原始审计；历史结论可从保留的Markdown来源追溯。
清理不增加当前配置的确定性证据，不改变有限样本的适用边界。

## 追加：FP8权重清理（2026-10-12 16:32 UTC）

用户随后明确要求删除已下载的FP8权重。已从 `wxu-sgl-evolve-agent-weight-20261006` 删除：

- `Qwen3.5-9B-FP8`
- `Qwen3.5-27B-FP8`
- `Qwen3.5-35B-A3B-FP8`

合计222文件、80,593,421,772逻辑字节（80.59 GB），不包含在首节105.08 GB的旧结果统计中。
删除后重新列目录，确认三个FP8目录均不存在；保留的三BF16、Embedding及Judge共5目录，类型、大小与mtime未变。
未重新读取/哈希全部保留权重，无GPU启动或推理测试。当前正式配置没有FP8依赖。

原下载manifest、固定revision、逐文件大小和最终校验状态保存在runs volume同一清理目录的
`fp8_weights.json`（completed/verified）；FP8权重本体未备份，后续使用须重新下载。环境skill和状态文件已同步。


---

<a id="repro_cleanup_20261012-history"></a>

## repro_cleanup_20261012/history.md

原本地路径：`outputs/repro_cleanup_20261012/history.md`；原文件SHA256：`609d3df7351ef40f9ca8139db001bb1c9c61ae6fd7f3a5def8a570f3125dd720`。

# 已退役的推理配置实验

2026-10-12，按用户要求清理当前验收配置之前的过时实验结果。本文保留失败结论、协议差异和来源，
不把历史配置作为后续运行入口。删除范围与实际统计见 [清理记录](validation_history.md#repro_cleanup_20261012-readme)。

当前配置为 `qwen35-bf16-flashinfer-sync`：三模型统一 BF16，每卡独立 TP1/DP1/C1，
同步 inproc/eager、FlashInfer GDN prefill、native GemmaRMSNorm、mem0.94 加 expandable segments，
prefix/MM cache 关闭，正常 decode KV 保留。固定输入、版本与配置，逐调用审计完整 token。

当前证据保留在 [正式接口回归](validation_history.md#formal_repro_integration_20261012-readme)、
[扩大测试](repro_expanded_20261012/README.md) 和 [RMSNorm 修复验收](validation_history.md#e2e_alignment_20261012-readme)。

| 退役方案 / 来源目录族（runs volume 的 `devbox/` 下） | 必须保留的结论与边界 |
|---|---|
| `fp8_h100_tp8_*` | 35B-A3B FP8 的 shared expert 中间维度 512 / TP8 = 64，不满足 FP8 block_k=128，启动失败；9B FP8 使用社区 checkpoint。下载完成不等于推理可用。 |
| `qwen35_throughput_*`、`vllm_*_20261010`、`fp8_*_20261010` | 小面板/短答案及固定路由曾通过并提速，但更长输出、不同副本或重启出现反例；cache、并发、量化内核变化属于不同协议，速度不能直接套用当前 BF16 配置。 |
| `native_dp8_*`、`independent_dp8_control_*` | 原生 DP8 三模型各192响应，分别176/112/168次与全局参考不同；无请求错误也不代表重复一致。原生 MoE DP 与八个完整独立副本不是同一部署。 |
| `tp8_bf16_recheck_20261010` | 旧 BF16 TP8 三模型各178响应，启动内重复一致；9B/27B重启后各11/42组改变。35B同机重启通过，但与旧 allocation 四组不同。 |
| `independent_bf16_*` | 旧异步单卡 E2E 同卡一致，9B/27B换卡或重启有反例。35B在prefill预算32768时33题×3轮 Agent 通过；不能推广给三个模型或当前协议。三模型 BF16 权重均曾装入单张 H100 80GB。 |
| `single_process_gpu_*` | 保留同PID/模型对象、重建执行器的八题跨卡探针192响应/168比较通过；配置与加载器修正前后的35B首轮仍有差异。不是在线CUDA状态热迁移方案。 |
| `inproc_mvagent_*` | Triton GDN 下完整 Agent 放大反例：27B/35B各6/6同卡重复轨迹不同，输入与prompt token哈希不变。9B小面板通过不能代替三模型验收。 |
| `repro_diag_*`、`repro_gdn_*`、`repro_kkt_*`、`repro_agent_flashinfer_*`、`repro_fix_*` | 固定张量 A/B/A 对照定位 Triton GDN prefill 的 KKT 执行配置；改 FlashInfer 消除了该受控反例。没有证明所有历史差异都只有这一个原因。 |
| `tp_compare_*` | FlashInfer旧profile的八题 TP1/TP8 对比中，9B/27B TP8通过有限重复但整体吞吐低于八独立TP1；35B TP8权重装入后首个图片请求视觉OOM，0有效输出。跨TP输出有变化，不可混合结果。 |
| `agent_replica_*`、`agent_repro_panel_*` | 旧FlashInfer配置33题四遍396轨迹/5236调用通过，后续正式E2E扩大暴露剩余不稳定性；该轮结果不构成固定配置验收。 |
| `e2e_sync_entry_*`、`e2e_sync_direct_*`、`e2e_sync_audit_*` | 修复前正式E2E共297次比较：9B/27B/35B分别1/0/2差异；输入不变，35B同GPU同PID也出现反例。mem.95及仅降至.94的35B曾视觉OOM；.94加expandable后跑通。 |
| `e2e_alignment_*`、`e2e_norm_*` | eager没有禁止GemmaRMSNorm内部torch.compile；第0层RMSNorm是已捕获的首个差异。改native形成固定配置。诊断张量已清理，因果分析MD与固定配置正式输出仍保留；新旧配置输出变化不属于同配置重复失败。 |

旧原始输出、日志、诊断张量与大体积缓存已按清单退役，不能再对这些已删除记录重新做原始审计。
原本地 Markdown 报告及清理前状态/说明合并保存为 runs volume 中
`devbox/repro_cleanup_20261012/historical_reports.md`，每份附原路径及 SHA256；内容是当时的历史陈述，
其中“保留”“运行中”和原始数据链接不再代表当前状态。

少量旧路径仍存在，因为当前验证脚本引用它们作为固定输入、面板来源、权重或协议对照元数据。
它们不是推荐结果目录；精确保留清单与哈希见同一远端目录的 `retained_fixture_hashes.json`。
新运行应创建独立输出目录，不写入这些只读历史夹具。

有限实验未证明任意输入、硬件或版本都确定；输出重复一致也不代表答案正确或格式合格。
当前扩大测试已观察到稳定重复的截断及无效选项，相关记录继续保留。


---

<a id="mvagent_pilot_20261013-readme"></a>

## MVAgent 66题历史小批测试

原本地路径：`outputs/mvagent_pilot_20261013/README.md`；原文件SHA256：`87efe010a318163154f5afca6d5a68d406b22b404b5ca7e1c8c4386f2c4e6e96`。

# 当前 MVAgent 的效果与可靠性小批测试（2026-10-13）

用户决定暂不实施错误分类、单副本主动恢复、非阻塞监控三项工程改进，先测当前系统。
本轮不改 Actor、Prompt、开放式 answer schema、Agent 动作与运行逻辑。

## 最终结果（2026-10-13，离线汇总于05:24 UTC补齐）

35B-A3B BF16的66题两遍全部完成：132条轨迹、1398次Actor调用，66组整轨迹和699组配对调用均0差异。
0模型调用错误、0结构化错误、0整题错误、0重试、0输出token预算截断、0强制步数终止。
每遍699调用，首遍736.05秒（5.38轨迹/min），第二遍692.83秒（5.72轨迹/min）；
整个GPU任务从02:48到03:17:53约30分钟，随后自动释放。

66/66题有非空答案文本，但只有61/66符合现有答案形式检查；5道题（7.58%）两遍均失败。
这5道题的官方得分均为0，不能把稳定输出或非空字符串当成完成了有效作答。

| 问题 | 实际输出 | 分析 |
|---|---|---|
| crossvid:NC:928 | None of the options are supported by the evidence | 以证据不支持选项为由不选择 |
| cvbench:712 | None of the options are consistently shown across all videos based on the provided evidence. | 以跨视频证据不一致为由不选择 |
| mvu_eval:Counting:88 | None of the options are correct as no video shows a ceiling fan. | 观察报告均否认吊扇，最终不选择 |
| cvbench:75 | `,` | 原始JSON中已是逗号；终答268token、stop、reason1200字符 |
| mvu_eval:TR:1398 | `,` | 原始JSON中已是逗号；终答374token、stop、reason1200字符 |

这5条轨迹都只有一次成功取证action，随后主动进入回答器，不是耗尽5步或服务失败。
前三类输出反映证据与选项冲突时没有提交最佳候选；是否由漏看、错误报告或题目问题导致，尚未逐帧核验。
逗号已经存在于原始模型响应，不是解析器从正常答案误提取。字符上限是线索，不是已证实根因：
全66题有10题的终答reason达到1200字符，其中3题格式失败、7题答案形式正常；未做字符上限消融。

| Benchmark | 题数 | 官方口径小样本估计 | 原始样本均分 |
|---|---:|---:|---:|
| CVBench | 30 | 60.05%（按task总体规模加权） | 17/30，56.67% |
| MVU-Eval | 16 | 71.11%（按task总体规模加权） | 11/16，68.75% |
| CrossVid | 20 | 49.79%（十task macro） | 本次等额抽样下同为49.79% |

CCQA的2题均已由固定本地Qwen3-30B-A3B-Instruct-2507完成评分，按评分点加权为66.67%。
各task只有2题，不能将上述估计当作全量基线或可靠的模型排名。

## 离线报告修复与证据

原控制器在推理、重复性对照、Judge评分都完成后，因finalize仍读取旧版`open_qa_pending.jsonl`而失败。
旧progress.json、traceback和冻结源码保留。只修复离线finalize：从当前逐题record读取待汇合答案和评分点，
读取当前Judge元数据结构，并正确标示官方加权分数与实际Judge。没有改Actor/Prompt/schema，也没有重跑推理。

远端完整compileall与2个小回归通过（点数加权/原始记录不变、错配答案拒绝合并），实际66题汇总已成功。
132份原始result.json修复前后SHA256全一致；新增Actor请求0。
产物：`repeat0/summary_scored.json`、`repeat0/benchmark_results.md`、`analysis/answer_audit.json`、
`analysis/postprocessing.json`及修复脚本快照。Raw记录仍保留原deferred状态，Judge与汇总另存。

尚未修改回答策略；若后续要求每题尽力提交答案，可以测试通用“在reason说明不确定、在answer提交最佳判断”指令，
以及reason长度的对照，不增加选项枚举或按benchmark写死格式。仅靠开放式生成不能预先保证任意输入100%合规。
以下保留启动与中途进展记录。

## 范围与协议

- 当前主力 Qwen3.5-35B-A3B BF16，无 skill；正式 `eval/agent_eval/run.py`。
- 33 类 native task 各随机抽 2 题，共 66 题：CVBench 30、MVU-Eval 16、CrossVid 20。
- 抽样 seed=20261013，只依据任务类别和题号，不查看答案/分数；CrossVid 限 Lite2500。
  明确排除已有损坏源视频的 CVBench64–66。每题两遍，共132条计划轨迹。
- 8×H100，每卡完整权重、TP1/DP1/C1，整题固定副本；固定配置同步/FlashInfer/native GemmaRMSNorm。
  Global/Video各5步、每调用2048输出token、512帧，正常解码KV缓存保留。
- 首遍按当前官方评分器评分，CCQA延后用固定Qwen3-30B-A3B-Instruct-2507 Judge。
  第二遍仅推理，用完整token、输入hash、公开/内部轨迹对照首遍。格式偏差不触发额外重试。
- 执行配置沿用正式8副本YAML（包括整题7200秒、已有1次重试），只把缓存路径放到本次结果目录。
- 样本量很小，用于初步效果与可靠性诊断，不作为完整benchmark得分。重复运行不增加独立样本数。
  CV/MVU按task总体规模加权估计，CrossVid报告十类task macro；运行失败与评分失败另报。

## 运行与产物

- DEVBOX_NAME=`mvagent-pilot-20261013`，Sandbox `sb-GAnCZbfX50ogR0ltsrK2Bg`，8×H100，6小时上限。
- 控制器 `scripts/run_mvagent_pilot.py`，复用现有审计函数；仅为审计函数新增样本列表参数。
- 运行目录 runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/mvagent_pilot_20261013/`。
- `frozen_repo/`、`selection.json`、`samples.json`、`manifest.json`保存源码、输入选择及配置；
  `repeat0/`保存首次原始轨迹及评分，`repeat1/`保存重复轨迹；`reliability.json`保存逐token比较。
- `progress.json`记录阶段，`repeat*/progress.json`记录实际题目进度；结束自动释放本Sandbox。
- 现有8卡E2E和2卡定点检查均在不同Sandbox，不修改其冻结代码、不占用其GPU。

02:48 UTC已提交PID207，处于35B加载阶段。远端完整compileall、抽样/逐token审计自检通过。
项目health当时3个任务、近15分钟0traceback。已有E2E与4题小测各占一个独立任务。

新旧冻结src/eval/configs逐文件比较仅两份README不同，运行源码与配置无变化；
证据保存在远端source_comparison.json。抽样文件SHA256：
`7ceade46b11d9a938dfa5ca851e9f2ff802eeb4593e3a8b13a419ae50c8ca27a`。

## 02:55:36 UTC 实测核查

首遍完成16/66题（当前先返回CrossVid），已完成轨迹139次调用；含未结束轨迹共有204个实际响应。
模型错误、结构化错误、整题错误、评分错误均为0；8个不同GPU UUID均产生真实响应。
所有已完成调用的真实forward计数、token数量与usage核对通过；每条完整轨迹都固定同一PID/GPU。
验证证据为远端launch_verification.json。此时第二遍尚未开始，不能声称本批重复检查已通过。

已实际返回的例子：BU504=`A`（官方得分1）、CC259=`D`（0）、FSA576=`56,68`（IoU0.625）、
PSS579=`4->3->1->2`（1）；两个CCQA答案已保存，待固定Judge评分。不把这些先完成题的均值当总分。

初始吞吐4.61轨迹/分钟（排除模型加载，包含首批冷输入准备），完整两遍及Judge粗估还需40–90分钟。
这是早期估计，长轨迹、服务异常或Modal抢占可能延长；后台控制器会自动比较、评分、落盘和释放GPU。
当前没有主任务级阻塞，下一动作是自动完成首遍及重复遍；完整成绩/重复结论尚未取得。

独立Luna只读确认任务正常后结束巡检；过时巡检文件已清理，最终结果见本文开头。
此时项目health为2个任务、近1小时0traceback；旧2卡小测已经完成，E2E独立继续。
退出会话后不维持代理巡检，后台控制器与watchdog继续执行。Modal抢占或6小时硬上限后的自动重申请未部署。

退出前再次读取实际记录：首遍已32/66题（CrossVid20、CVBench12），326次已完成轨迹内模型调用；
模型错误/结构化错误/整题错误均0，尚无达到token上限或forced_with_gaps的已完成轨迹。
CrossVid18题规则评分已返回，2题CCQA待Judge；CVBench12题已评分。此时不汇报不完整子集作为最终总分。
