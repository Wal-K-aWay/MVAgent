# 三模型统一PRO6000 9B src＋FFmpeg实验

状态：9B已完成；27B、35B-A3B正在运行，各330题（闭式300＋CCQA30），不是全量benchmark。

三模型使用同一旧9B src快照，只有media.py改用FFmpeg。105个src文件SHA与已完成9B实验完全相同。
固定BF16/H100/TP1/C1/seed0/temperature0/thinking关闭/FlashInfer GDN/native GemmaRMSNorm/prefix与MM缓存关闭。
每模型整题固定副本。27B/35B各8卡并行，9B此前16卡；总体墙钟不能直接用于比较模型速度。

追加源码位于codex/pro9-ffmpeg-large-20261016，冻结运行文件88c5aa8；主工作区及正式配置不替换。
旧src始于6b1e5641719e5e12202737ed66f218250a8b4bd6的9B source_snapshot，原PRO27B/35B结果来自各自当时源码，作为历史参照。

两模型沿用9B的300闭式题＋seed0抽取的30CCQA，不重抽题，不按新输出筛选。
实际3个Agent模型角色、历史同题输入、source/配置与服务身份逐项核对。
每模型先CV34/CCQA80各两遍：27B22响应/11对应调用，35B32响应/16对应调用，输入hash/完整输出token与除时间外结果均一致。
完整330题复用已验收数值配置，不再整批双跑；有限冒烟不等于任意输入的绝对保证。

结果仅保留Modal runs volume：
- 9B：devbox/pro9_ffmpeg_20261016。
- 27B：devbox/pro9_ffmpeg_27b_20261016。
- 35B-A3B：devbox/pro9_ffmpeg_35b_20261016。

每模型保存原始records、HTTP请求/响应与token、服务器manifest/身份、源码哈希、四组统一Judge与共享缓存、同题分数和诊断。
后续评分使用和9B相同的冻结官方评分器，CrossVid单列九闭式macro与含CCQA的十类macro；Judge失败不记零分。
当前仍待完整Actor、Judge、评分与最终核查，不把提交成功或冒烟通过当成准确率结果。
