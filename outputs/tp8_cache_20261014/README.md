# TP8、prefix cache 与16题并发（2026-10-14，北京时间）

**完整MVAgent测试已完成：TP8/C16能运行，但本次未提速，且逐token重复性失败。**
35B BF16、16道开发题覆盖三个benchmark；包括首次TP8测量，共80条完整轨迹、754次模型调用。
不评正确率，不运行Judge。正式运行配置与另一实例的全量评测未改变。
DEVBOX_NAME=`mvagent-tp8-cache-20261014`，8×H100。不修改/停止另一实例的完整评测。
初始Sandbox `sb-1deexgHAbQk6wvgFHhKt26`（3小时上限）已在r2结束后自动释放。
补测Sandbox `sb-OIcE4JXXv8vOmt7tmh9iLK`（2小时上限），任务`tp8_cache_20261014_r3`、PID46，
只补TP8连续两遍；对照沿用r2，不重跑。r3已完成并自动释放GPU。
两次分配同型号但GPU UUID不同，速度比较须保留此限制；r2中同一批GPU的初始对比也未显示TP8提速。
结果根为 runs volume `devbox/tp8_cache_20261014_r2`、`devbox/tp8_cache_20261014_r3`。
初次准备目录 `devbox/tp8_cache_20261014` 保留失败日志，控制器PID535及其子进程已停止，0推理结果。

当时使用`benchmark_mvagent_tp8_cache.py`测试基线Actor Qwen3.5-35B-A3B；用户随后恢复固定配置，已移除本地旧实验入口。
控制器完整源码仍在上述runs目录的`frozen_repo/scripts/benchmark_mvagent_tp8_cache.py`，历史结果不变。
从既有66题开发面板固定 seed0抽取16题：CVBench6、MVU5、CrossVid5，不按答案或成绩筛选。
原有空skill架构、Prompt、BF16、seed0、temperature0、thinking关闭、每调用2048输出token/512帧、双方最多5步保留。
只测性能与重复性，不评正确率、不运行Judge。

| 实验组 | 服务和并行 | Prefix cache | 显存比例 |
|---|---|---|---:|
| tp8_prefix_c16 | 标准vLLM API，TP8/DP1，16题并发，max_num_seqs16 | 开启 | 0.85 |
| tp1_v3_c8 | 开启 prefix cache 的实验配置同步服务，8个TP1/DP1/C1副本 | 开启 | 0.94 |

两组均保留 eager、FlashInfer GDN 与 native GemmaRMSNorm；TP8使用多进程执行器，但关闭异步调度。
TP8的并行请求必须使用可批处理服务，不能仅把原串行同步服务的线程数改为16。
显存比例0.85给视觉编码留空间，源于旧TP8视觉OOM证据。其他差异完整保存在manifest/启动命令中。
两组均用新冻结的开启 prefix cache 的实验配置源码；这是两套部署方案的整体效率比较，不是单独prefix cache或TP的因果消融。
开启 prefix cache 的实验配置自身仍需通过本次实际冷热缓存/Agent重复检查，不能继承固定配置验收。

两组各跑两遍相同16题，分别记录初始缓存状态和保留缓存的第二遍；每组媒体缓存独立。
首遍仍含服务就绪探针造成的短前缀预热，不能称绝对空缓存。启动耗时与推理CLI墙钟分别记录。
对比整题/中间调用/完整token与相同请求哈希，首次分歧单列；不得把不同输入轨迹的后继变化当成相同输入反例。

输出：`manifest.json`、`source_manifest.json`、`frozen_repo/`、`samples.json`、`progress.json`，
每组的`startup.log`、`runtime_cache`服务日志、`repeat0/1`原始轨迹和调用记录。
候选标准服务返回实际`usage.prompt_tokens_details.cached_tokens`；全局token命中率按token加权。
实验补丁只存在本实验冻结副本的服务启动命令，正式src/config未改；对照使用同一新冻结开启 prefix cache 的实验配置源码。

已通过本地AST/diff检查与远端面板、完整token审计小测试；控制器还会在冻结副本中执行完整compileall。
首轮PID506在加载前因Git safe.directory检查退出；已仅修正该命令，保留`freeze_setup_failed/`和错误日志，
同实例PID535重新冻结并通过compileall，01:17北京时间开始35B TP8服务加载。
标准API服务器随后因TMPDIR实际volume路径超过ZMQ的107字符socket路径限制退出，未推理。
停止该实验进程后，以新目录r2设置TMPDIR=/tmp并统一开启 prefix cache 的实验配置对照；旧日志/冻结副本保留，无推理数据被覆盖。
独立GPT-6-Luna每15分钟只读检查，见[巡检记录](progress_checks.md)。
独立巡检已完成并停止；原全量评测另有自己的后台控制器与巡检。

## 最终结论

下表采用包含CLI准备/退出的完整运行墙钟，排除服务启动；两组prefix均开启：

| 完整MVAgent方案 | 首遍16题 | 保留缓存的第二遍16题 | 逐token加权cache命中率 | 重复轨迹 |
|---|---:|---:|---:|---|
| 8个TP1/DP1/C1，开启 prefix cache 的实验配置 | 219.17秒 | 207.41秒 | 7.53% → 16.42% | 16/16一致 |
| TP8/DP1，16题并发，r3 | 312.86秒 | 255.96秒 | 10.68% → 45.61% | 16/16发生变化 |

TP8的实际运行请求峰值为16，不是只设置了16个CPU线程；两遍各153/158次模型调用，输入751503/627309 token，
输出17515/18183 token，均无整题错误、模型错误、结构化错误、repair或token截断，最终答案均非空。
TP1两遍各152次调用、输入546587/输出15364 token，亦均无上述错误。

- TP1 开启 prefix cache 的实验配置：16条配对轨迹一致；157次相同请求与prompt token哈希的比较，0输出差异。
- TP8同一服务进程两遍：16条轨迹全部变化，8条最终答案变化；24次相同请求与prompt token哈希比较，18次输出不同，最早第4个输出token分歧。
  这里的相同输入比较也包含遍内重复请求，不能称为24道题。
  18个差异中14个属于纯文本决策（13个Global决策、1个Video Planner），所以不能仅用视频解码差异解释这一结果。
- TP8跨两次GPU分配（r2首遍与r3首遍）：14/16轨迹变化、4/16最终答案变化；28次同输入比较有15次不同。
- 具体最终答案变化：`cvbench:552`从C到B；`crossvid:PSS:579`从`4->1->2->3`到`3->1->2->4`；
  `mvu_eval:KIR:352`从C到B。终答所见的历史已可能不同，这些是整题轨迹结果，不当作终答器相同输入的独立反例。

结论：本次不采用TP8/C16替代TP1。提高cache命中并未带来更高整批吞吐，更不能替代重复性验收。
TP8、批处理/多进程服务和显存预算同时变化，未做因果消融，不能把不一致归因于prefix cache单独一个因素。
TP1 开启 prefix cache 的实验配置的通过仅覆盖本轮35B、16道复用开发题；9B/27B和E2E尚未在开启 prefix cache 的实验配置复核，不作任意输入保证。

`r3/final_analysis.json`保存五个批次的逐请求cache数、按schema聚合、完整比较及首次分歧，
`analysis.py`和`post_audit.py`为CPU分析来源；r2/r3全部src哈希一致，实验统计修复没有改变模型运行代码。
补充核验8个TP1服务manifest均为开启 prefix cache 的实验配置、prefix=true、TP1/max_num_seqs1/seed0，8个GPU UUID互异。
同步服务不提供标准vLLM的running-request gauge，分析中该项记为null，不把未提供指标解释成零并发。
解码器在两组均出现少量跳过不可读帧的警告，完整记录见final_analysis；0请求错误不意味着没有解码警告。
标准API没有记录内部视觉embedding哈希，不能据此声称内部视觉张量全相同。

## 已完成的r2实测

三个批次均为完整MVAgent轨迹，首题分发到末题落盘的墙钟如下（不含服务启动、CLI准备/退出）：

| 组别 | 完成 | 批次墙钟 | 题/分钟 | 调用数 | 输入token | 输出token | cache token命中率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| TP8首遍 | 16/16 | 252.50秒 | 3.802 | 139 | 597792 | 17039 | 5.96% |
| TP1 开启 prefix cache 的实验配置首遍 | 16/16 | 215.25秒 | 4.460 | 152 | 546587 | 15364 | 7.53% |
| TP1 开启 prefix cache 的实验配置第二遍 | 16/16 | 203.08秒 | 4.727 | 152 | 546587 | 15364 | 16.42% |

TP1包含CLI准备/退出的对应墙钟为219.165、207.407秒。此前口头TP8约257秒也是该较宽口径，
其精确计时未在汇总器异常前落盘；统一按执行事件重算的252.50秒用于同GPU比较，源文件`recovered_measurements.json`。
三批均0模型错误、0结构化错误、0repair、0输出token截断。
TP1两遍16条完整轨迹、157次相同请求/输入token哈希比较，输出全部一致。
TP8与TP1的行为/输出工作量不同，吞吐对比是系统级测量，不是等token计算量的内核加速比。

TP8首遍正常推理完成后，统计器未处理标准API在零命中时返回null而报错，控制器进入TP1组，
没有进行原计划的TP8第二遍。原始16条轨迹未丢失，已按vLLM0.19.1实际serving代码核对null语义并离线恢复统计。
修复只涉及实验统计（新增零命中/非零命中小测试），不修改模型调用。r3用于连续两遍TP8测量，r2保留独立跨进程参考。
