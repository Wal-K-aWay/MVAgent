# PRO6000完整9B源码＋FFmpeg：同题实验

状态：运行中，结果待330题完成后汇总。本分支不替换共享主工作区。

## 范围与溯源

用户要求先9B，使用两组8×H100共16卡；每卡TP1/并发1，整题固定副本。
恢复PRO6000 9B全部105个src文件，只有视频分段函数改为FFmpeg；旧Prompt、schema、memory、
直接回答和独立兜底均保留。来源提交6b1e5641719e5e12202737ed66f218250a8b4bd6，
具体SHA与配置见[实验说明](../../experiments/pro9_ffmpeg/README.md)。

复用原300题面板（CVBench、MVU-Eval、CrossVid闭式各100），再从已完成239道CCQA中seed0抽30道。
本次、PRO旧答案、独立回答器、E2E的30道CCQA使用同一个冻结Qwen Judge和共享缓存评分。
原始记录、完整请求/响应token、Judge缓存、源码与配置只保存于Modal runs volume：
`devbox/pro9_ffmpeg_20261016`。

仍使用固定H100数值服务：BF16、seed0、temperature0、thinking关闭、FlashInfer GDN、原生GemmaRMSNorm、
prefix/MM缓存关闭。外部桥仅转换旧JSON-schema接口，不添加新grammar或字段字符上限。
这是旧src＋FFmpeg在固定H100环境的系统测试，不是原PRO6000软硬件逐位复刻，也不是裁剪器单因素消融。

## 已完成检查

- 旧src105个文件逐哈希校验；唯一差异media.py。
- 远端编译、接口转换、FFmpeg正常分段/短片段补帧/空区间检查通过。
- CV34和CCQA80各两遍完整Agent，28实际响应、14对应调用，输入hash和完整输出token均一致。
- 烟测HTTP日志通过独立archive及SHA清单保留；两组挂载的新文件可见性延迟通过传递已校验结果解除，未改模型/Actor源码。

## 待完整结果

准确率采用冻结官方评分器；CV/MVU按题型总体权重估计，Cross按任务macro。
同题比较PRO历史、旧独立回答器和前一轮直接回答协议，另报E2E；它们不能冒充最新正式History＋独立兜底配置的全量成绩。

已观察到的负例CV824：视觉观察器在同一235.73秒视频上反复列举细节，2048 token仍未完成JSON，
VideoAgent没有取得有效观察。三个已核验调用具有同一输入hash和完全相同的输出token；这是可重复的失败，
不能把输出确定性等同于有效答案。完整频率、最终答案及影响待本轮结束后补充。

这些题属于复用开发面板。有限样本一致不构成任意输入的确定性保证；准确率差异也不能单独归因于某一项Prompt或schema修改。
