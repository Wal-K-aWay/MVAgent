# E2E启动、超时恢复与巡检历史

本轮已于2026-10-13 07:57 UTC结束，三模型可测题与评分已齐。以下4份历史记录中的运行状态、ETA和后续动作均为当时描述，不是当前指令。最终结果见[分析报告](final_results.md)。

---

## 原记录：outputs/e2e_full_20261012/README.md

原文件SHA256：`17847360c038606417e39c2d261667083a834c23663375579c8f6a8230032124`。以下为历史记录。

# 三模型完整 E2E 重测（2026-10-12）

**最终结果已齐：9B沿用本目录，27B/35B恢复任务于2026-10-13 07:57 UTC完成。**
三模型各5321可测题，CCQA各239条全部评分；见[最终分析与限制](final_results.md)。

**2026-10-13 01:04 UTC更新：本任务已于10月12日23:36结束；9B的可测题全部完成，27B/35B因600秒请求超时未完成。**
GPU已释放，旧的10–16小时工期估计失效。已在独立目录重启两个未完成模型，见[超时恢复记录](run_history.md)。
下文17:40状态为当时的启动核查，不代表当前仍在运行。

本轮按用户要求后台运行；确认有效响应持续产生并估计剩余时间后结束会话，不等待整个矩阵完成。
结果和冻结源码只保存在 Modal runs volume `wxu-evolve-agent-runs-20261006`。

## 任务与输入

- 目录：`devbox/e2e_full_20261012/`。
- Sandbox：`sb-gOOQt5EwAP6HCPfQtcUkek`；devbox 名 `mvagent-e2e-full-20261012`；24 小时上限。
- App：`wxu-sglang-baseline-gpu-test-devbox`（`ap-lluPvOtRg7tYTpbvSVmWFd`）。
- 模型依次为 Qwen3.5-9B、27B、35B-A3B，全部官方 BF16。
- 8×H100，每卡独立 TP=1/DP=1、并发 1；共享已验收的 `qwen35-bf16-flashinfer-sync` 后端。
- 每模型 CVBench 1000、MVU-Eval 1824、CrossVid 固定 Lite2500，共 5324 题；三模型共 15972 题。
- CrossVid split：`configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json`，SHA 保存在运行 manifest。
- 512 帧上限、最长边 448；temperature=0、seed=0、thinking 关闭，保留各 benchmark 的输出预算与官方评分。
- MVU-Eval 已恢复官方答题指令：`Please select the correct answer from the options. Answer with the option’s letter directly.`
- 无 skill。CCQA 使用固定 Judge `Qwen3-30B-A3B-Instruct-2507`，Actor 全部完成后统一评分。

## 后台执行与结果

`scripts/run_full_e2e.py` 复用现有 `serve.py` 和 `run.py infer/score` 接口。每个模型按题型固定分为八个不重叠分片，
每卡一个串行 CLI；每个分片的帧缓存跨三个模型共用，第一次输入绑定 SHA，后续使用逐题核对。
正式推理代码与配置冻结在 `frozen_repo/`，运行从该快照执行，后续工作区改动不影响本任务。

- `progress.json`、`job.log`：阶段、逐模型/benchmark 成功数和错误数、实测平均题目耗时。
- `{9B,27B,35B-A3B}/rank0` … `rank7`：原始分片 manifest、输入审计、源码与逐题原始记录。
- `{9B,27B,35B-A3B}/raw/`：分片完成后汇合的标准原始结果，保留全部所选题号。
- 各模型根目录的 `manifest.json`、`selection.json`、`input_audit.json`、`source/`、`scores/`、`summary.json`：原接口的结果格式及汇合来源。
- `media/rankN/`：跨模型共用的冻结帧缓存和输入 SHA；`servers/`、`judge/`：实际模型和 Judge 日志。
- `report.md`：控制器结束时写出的最终状态，包括所有失败。

控制器脱离 SSH/会话运行，自动换模型、评分；服务加载失败或 30 分钟无题目完成时，每模型最多重启一次并续跑成功记录以外的题。
结束后控制器使已有 Sandbox watchdog 释放 GPU。若 Modal 抢占或达到 24 小时硬上限，结果保留在 volume，需从冻结源码续跑；
当前未设置跨 Sandbox 自动重新申请 GPU。

## 已知限制与启动记录

CVBench 的 `125/RQorrnJIc2Q.mp4` 是已确认的官方损坏文件，实际大小 26214400 字节时，64/65/66 三题直接留下明确错误记录。
不静默删除这三题，也不将其当作模型错误或零分；预计可推理 997/1000，因此 CVBench 正式汇总会标记未完成，并单列已评分样本均分。
三模型预计可取得 15963 条有效响应，其余 9 条是上述数据缺陷。

第一次控制器启动在加载模型前因 `/runs` 符号链接反复跳转冻结入口，0 响应；已停止，源码保存在 `startup_path_failure_source/`。
修复为解析真实路径后比较，并加入符号链接自检。修复后的后台 PID 为 89，启动于 17:30 UTC。
分片覆盖、Lite2500、汇合身份校验和符号链接自检，以及远端完整 compileall 通过。

## 退出会话前核查（17:40 UTC）

9B 已取得 **104 条有效响应、0 请求错误**：CVBench 37、MVU-Eval 34、CrossVid 33。
17:36 的 14 条、17:38 的 54 条到本次 104 条持续增长；8 个 rank 均有实际输出。
8 个 manifest 确认八张不同 H100、每客户端 workers=1、同一 固定 profile；104 条记录的完整 token 数与 usage 一致，实际 forward 数大于零。
尚无完整模型/benchmark 单元完成，27B 和 35B-A3B 仍待自动启动，评分尚未开始。

| 首批 9B 数据 | 样本数 | 平均总秒/题 | 平均请求秒/题 | 平均输出 token |
|---|---:|---:|---:|---:|
| CVBench | 37 | 19.89 | 9.75 | 12.68 |
| MVU-Eval | 34 | 25.64 | 17.20 | 233.82 |
| CrossVid | 33 | 9.38 | 5.20 | 2.55 |

真实输出示例：`cvbench:7 → No.`（3 token，stop）、`crossvid:BU:60 → ACD`（3 token，stop）；
`mvu_eval:Counting:5` 输出以 `To determine which video shows the room with the most tables...` 开头，182 token、stop。
这里验证执行与落盘，不将输出示例当作答对的证据。

**剩余时间粗估 10–16 小时**，含切模型、加载与评分。按各 benchmark 剩余数量乘初期平均时间除以8，并参考此前
27B 比 9B 慢约1.53倍、35B接近9B的面板测量；后两模型会复用已生成的帧缓存。
该区间保留未覆盖题型、MVU官方指令长回答、尚未结束的慢请求和分片尾部等待的余量；
目前后两模型的完整数据吞吐未实测，不能把早期样本外推当成完成时限。

冻结控制器 SHA256：`8b03e5bcba441a90dd3a1d7b8a72e148723afbf814f972a74c4bc4743e541c81`。
Split SHA256：`5e1cf0e4a0967e365b85f3ad0f5eddb4871beaebd24f421a1b09daac62b8262f`。
远端另存 `launch_verification.md`。独立 Luna 巡检确认任务健康，已按结束会话要求停止；不会继续声称有后台代理巡检。
控制器每30秒更新进度、后台推理和已有 watchdog 继续工作；当前无主任务级阻塞，下一动作由控制器继续推进9B。

查看进度（在项目根目录，所有 Modal 访问仍经 modal-gpu）：

```bash
DEVBOX_NAME=mvagent-e2e-full-20261012 .agents/skills/mvagent-environment/devbox/devbox.sh exec 'cat /runs/devbox/e2e_full_20261012/progress.json'
DEVBOX_NAME=mvagent-e2e-full-20261012 .agents/skills/mvagent-environment/devbox/devbox.sh log e2e_full_20261012
```


---

## 原记录：outputs/e2e_full_20261012/progress_checks.md

原文件SHA256：`005f4e8c78357a8d33e9ca04ecd4641c9cb3fc79e7c8ce0fd02a04fe8ab7d8d6`。以下为历史记录。

# 只读巡检记录

## 2026-10-12 17:39 UTC

- 阶段：9B 模型推理；Sandbox `sb-gOOQt5EwAP6HCPfQtcUkek`，Modal app `ap-lluPvOtRg7tYTpbvSVmWFd`。健康检查显示 `deployed`、1 个任务、近 1 小时 0 个 traceback。
- 已完成实验单元：尚无完整 benchmark/model 单元完成。9B 已有 63 条有效响应（CVBench 23、MVU-Eval 21、CrossVid 19），错误 0；27B 与 35B-A3B 尚未开始。已记录的已知不可用 CVBench 样本为 64–66，不计作模型错误。
- 实测进展：17:36:44 有 12 条，17:38:44 有 63 条；近期约 21 条/分钟。按进度文件给出的 benchmark 平均耗时和 8 个 rank 粗估，每模型推理约 3.1 小时，三模型约 9.5 小时，另加模型切换、加载与统一评分。此为早期吞吐估计，后续可随实测修正。
- 阻塞：当前没有阻止端到端测量的外部阻塞。已知首次启动的冻结路径问题在模型加载前触发，已修复并重启；该次 0 响应不属于模型失败。
- 下一项动作：主执行者继续让后台控制器推进，按需观察 9B 响应增长并更新 ETA；本巡检代理依主执行者要求停止定时检查。


---

## 原记录：outputs/e2e_full_20261013_timeout/README.md

原文件SHA256：`4df41a9f5a520cffc063a72ca5be72b1bfaae6c9b863949fefe415ae99377aef`。以下为历史记录。

# E2E 超时恢复（2026-10-13）

**最终更新：恢复任务已于07:57:07 UTC结束，27B/35B各5321可测题推理与评分完成。**
与旧目录9B合计15963有效结果；三模型各239条CCQA均已评分，无漏评。
仅CVBench64–66损坏视频缺失。最终分数、格式分析及35B两条共享Judge缓存差异见
[完整分析](final_results.md)与[逐题核对](audit.md)。下文为历史启动与中途记录。

## 原任务实际状态

01:04 UTC 经 runs volume 查询确认：`devbox/e2e_full_20261012` 已在 10月12日23:36:42 UTC 以
`completed_with_recorded_failures` 结束，GPU 已释放。该状态不代表完整测试矩阵完成。

| 模型 | CVBench 有效/所选 | MVU-Eval 有效/所选 | CrossVid 有效/所选 | 有效响应合计 |
|---|---:|---:|---:|---:|
| 9B | 997/1000 | 1824/1824 | 2500/2500 | 5321 |
| 27B | 251/1000 | 240/1824 | 237/2500 | 728 |
| 35B-A3B | 356/1000 | 340/1824 | 340/2500 | 1036 |

共7085/15963个可测的模型-题目组合完成（44.38%）；三模型各有CVBench64–66三个已知损坏视频题，另列失败。
已完成的9B推理与评分保留；其CVBench官方完整指标仍为null，997题评分均分不冒充1000题完整分数。
27B、35B只产生部分结果，不能作为完整benchmark分数。

## 已定位原因

两次27B服务池失败都发生在8101；35B第一次在8102、第二次在8101/8102。
对应五份server.log均有 `TimeoutError: Model request exceeded 600 seconds`，随后worker退出，serve父进程关闭整个池。
控制器每模型自动重启一次，第二次失败后继续下个模型、对已有记录评分并结束。原始错误与源码保持原样。
27B超时题为 `crossvid:BU:334`，两次600.468/600.469秒失败，官方内部重试使最终报错显示Connection refused。
35B明确记录超时题 `mvu_eval:TR:278`、`mvu_eval:TR:284`，约600.135秒；未观察到OOM或抢占作为这些退出的原因。
这些证据说明运行时限不足；尚须新的长请求成功记录证明延长后能通过原失败处。

## 修复与新的后台运行

- `src/models/vlm/local/sync_server.py`：请求超时600→1800秒。
- `eval/e2e_eval/run.py`：HTTP等待900→1860秒，避免客户端先于服务端放弃。
- `scripts/run_full_e2e.py`：支持指定模型，冻结入口保留模型参数；无完成题目等待1800→2400秒；watchdog登记名从输出目录推导。
- 权重、BF16、固定配置数值配置、TP1/DP1/C1、seed、提示词、帧缓存、采样与输出token预算均未改变。
  已逐字核对共享模型实现：除了超时常量和对应报错外，与旧冻结源码相同。
- 远端完整compileall、8项接口测试、分片/汇合/符号链接自检通过。

新任务：`devbox/e2e_full_20261013_timeout`，01:09 UTC启动，PID231；
Sandbox `sb-9T3GTBJozEQvlOmsaBOg7p`，8×H100，24小时上限，仍使用DEVBOX_NAME `mvagent-e2e-full-20261012`。
后台依次重跑27B和35B-A3B，全部模型测量均从新的冻结源码执行；9B已完成结果不重跑。
`media/` 指向旧任务的完整缓存，每题输入SHA继续核对。原目录不覆写；新目录保留实际源码和完整原始输出。
这是对两个未完成模型的完整重跑，包含原来成功的1764题；不会将新旧记录伪装成同一冻结源码下的断点续跑。

新任务完成后，三模型最终数据由旧目录9B、新目录27B/35B组成；输入协议相同，运行超时及源码哈希不同且显式记录。
## 01:28:54 UTC 恢复核查

27B已有 **458题成功、0错误**。其中446题与旧成功记录的输入SHA、prompt token SHA、完整输出token、文本和finish reason全部相同；
全部458条的输出token数与usage一致，实际forward数为正。相比旧部分结果，新增12个有效模型-题目组合；旧两模型的部分成功记录仍保留。

原失败题 **crossvid:BU:334已返回**：总耗时444.071秒，请求441.935秒，8192 token，finish_reason=`length`，达到原官方生成预算；
不是自然stop，也未更改输出预算。实际输出开头为 `Based on the analysis of the three video clips:`。
本次同题用时小于600秒，所以只能声称原失败输入在新运行中成功，不能声称已实测超过600秒的成功请求，或将变快归因于超时改动。

**预计剩余6–10小时**（从本次核查起），含两个模型余下推理、换模型和评分。估计结合旧9B完整服务耗时
（CV平均7.25秒、MVU22.38秒、Cross8.41秒）、此前模型速度差异、当前27B吞吐与长尾，后两模型复用完整视频缓存。
35B尚未启动，30分钟时限对其全部长请求的覆盖未实测，工期会受长回答和分片尾部等待影响。

远端证据：`recovery_verification.md`；冻结runtime SHA256 `90dc9280a3e3416288a302ff0c33a8e8ed02c93781631fb080991360281086f4`，
控制器 SHA256 `b53d8957cb683fd44f5d9cbf968eaeb1bc4dd033665dc3ee6389998695ab2a82`。
01:25独立Luna检查正常后已结束，本会话退出后不宣称仍有代理巡检；主控制器和watchdog继续后台运行，自动换模型、评分和释放GPU。

```bash
DEVBOX_NAME=mvagent-e2e-full-20261012 .agents/skills/mvagent-environment/devbox/devbox.sh exec 'cat /runs/devbox/e2e_full_20261013_timeout/progress.json'
```


---

## 原记录：outputs/e2e_full_20261013_timeout/progress_checks.md

原文件SHA256：`d834fbfa4670035bb61a42ae9ffe66fdb7f99f690591906de3532ab98139e2ae`。以下为历史记录。

# Progress checks

## 2026-10-13 01:25 UTC

- Phase: inference; the run was active. `progress.json` last updated at 01:23:36 UTC and reported 27B 292 successful / 0 errors; 35B-A3B had not started.
- `crossvid:BU:334` is assigned to rank1 in `selection.json`, but it had no completed record in rank1's `raw/crossvid.jsonl` at this check. The latest completed CrossVid record visible there was BU229 at 01:17:51 UTC.
- The latest 8101 request entry had no completion timing fields, consistent with an unfinished request. Its sample ID was not recorded there, so this check cannot establish that the in-flight request was BU334 or that BU334 succeeded after 600 seconds.
- Health check: 1 active task; 0 tracebacks in the preceding hour. No failure or service-pool exit was observed.
- Conclusion: overall inference was progressing; the requested long-request recovery evidence for BU334 was not yet available.
