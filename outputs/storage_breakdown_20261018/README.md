# runs / assets 容量来源与清理候选（2026-10-18）

**后续状态：02:34 UTC已按用户指令删除LensWalk/RSI五批4071个MP4、2.055TB，验证完成。下表容量与runs候选是清理前快照；assets重复候选未处理。见[清理与速度报告](../media_retirement_20261018/README.md)。**

本轮为只读检查媒体/结果；仅向runs写入审计清单。不删除、不压缩、不启动GPU。统计为普通文件逻辑字节，不跟随符号链接，不代表Modal底层物理计费量；运行中目录可能变化。

| 卷 | 普通文件逻辑大小 | 主要内容 |
|---|---:|---|
| runs | 2,417,110,143,484 B（2.417 TB） | MP4 2,138,897,419,287 B（88.49%）；其余约278 GB包含帧缓存、轨迹、请求/回答、归档、源码等 |
| assets | 842,371,433,448 B（842.37 GB） | 原始媒体/标注约376.85 GB，CrossVid派生视频465.52 GB；没有大体积zip/tar下载包残留 |
| weights | 260,108,245,089 B（260.11 GB） | 当前保留的8组模型权重；HF缓存仅小型元数据 |

## 为什么runs超过2 TB

以下均为`/runs/devbox/`下的`prepared/media`，互不包含；这里只列媒体，未叠加其父目录总量：

| 批次 | 媒体大小（GB，十进制） |
|---|---:|
| lenswalk_full_35b_audit_recovery_20261017 | 608.42 |
| lenswalk_full_35b_recovery_20261017 | 466.41 |
| lenswalk_full_35b_20261016 | 431.96 |
| rsi_full_35b_20261016 | 347.67 |
| rsi_full_35b_recovery_20261017 | 201.01 |

五组共约2.055 TB，是主要来源。另有固定E2E媒体缓存97.66 GB、重复性实验root约75.40 GB，后者包括agent轨迹及其他输入/诊断。

这些外部方法把多段视频按题目拼接成单视频。混合编码、时间戳/边界情况会触发原分辨率无损H.264（qp=0）；恢复实现使用ultrafast以节省编码时间。原视频已有有损压缩，转成无损后体积可大幅增加；不同批次还可能各保存同一输入的拼接文件。`runs`因而混入了大量派生输入，并非只存答案。

源码证据：`eval/external_methods/prepare.py`中的`normalize_lossless`与`prepare`；恢复版位于`.worktrees/lenswalk-recovery/eval/external_methods/prepare.py`及对应RSI工作树。正常完成会删除数字命名的临时分段，保留`concatenated.mp4`和`timeline.json`。

## assets内部

| 内容 | GB |
|---|---:|
| CrossVid原始videos | 287.18 |
| UAV原始帧与标注 | 28.09 |
| CVBench | 40.53 |
| MVU-Eval | 21.04 |
| CrossVid派生PEA视频 | 319.18 |
| 派生PSS视频 | 64.23 |
| UAV题目框渲染视频 | 53.15 |
| 派生PI视频 | 28.97 |

`prepare_multivideo_benchmarks.py`按题号和角色保存派生片段，而不是按原视频/时间段共享文件；重复题目输入会产生冗余副本。上述PEA/PI/PSS用原尺寸/原FPS、OpenCV mp4v写出，和runs的无损拼接是两种不同的加工。

## 清理候选

| 候选 | 容量 | 证据与限制 |
|---|---:|---|
| assets相同原视频/裁剪区间/文件大小的片段 | 274,795,567,879 B（274.80 GB） | 425组，保留每组一份后有2418份冗余候选；只抽样核验一对完整SHA，未对全量做内容校验 |
| runs相同媒体key/大小的拼接视频 | 414,622,225,276 B（414.62 GB） | 936组，941份冗余候选；只抽样核验一对完整SHA。相同key不保证不同预处理版本字节相同 |
| runs/prepared/media的数字命名中间MP4 | 218,109,357,930 B（218.11 GB） | 96文件；正常成功路径会删掉它们，需检查所属处理阶段、完整输出和引用，不能只按文件名直接删除 |

三类候选逻辑大小合计907.53 GB，**不是已经确认全部可释放，也不是本轮删除量**。候选之间按文件类型和volume区分，未叠加父目录总量。

建议先核实并清理停止/失败预处理留下的中间分段，再对重复媒体逐文件校验、选定长期保留的原件、保留原有路径可读取（例如指向保留件的链接），最后核对引用和实际读取。不能按目录旧/failed名称直接删除：旧批次媒体仍可能被恢复批次引用，当前数据清单也依赖assets的派生路径。新生成逻辑还需要避免按实验/题号重复落盘，否则整理后仍会增长。任何未来改动都不能热改当前实验的冻结源。

两对完整SHA抽样：

- assets：`crossvid/.mvagent_media/PEA/{595,596}/video_3.mp4`，每份67,331,470 B；SHA256均为`cdbabb43d23770a0330f8a71b57767eb453a027c54c70c8e9c795b7fd66c7749`。
- runs：`{rsi_full_35b_20261016,lenswalk_full_35b_20261016}/prepared/media/media_35996b174711cb4015370be5/concatenated.mp4`，每份67,189,073 B；SHA256均为`1f8be73090bf46c353aee46c768266332fc50ec6f751777e1188c95fae56aa3e`。

体积膨胀实例：LensWalk audit recovery的`media_bd97ee9a1dc17e47ca7ba323`，timeline记录4段原生尺寸无损H.264拼接；输入文件合计517,900,541 B，输出20,738,162,320 B，约40倍。另四个大文件样本同样标记无损处理，约40–43倍；这不是全部媒体的平均倍率。

本轮没有删除或合并任何媒体，也没有重编码/压缩。聚合计数自检、脚本AST与git diff --check通过；详细核查app `ap-tl2yZtat5c5Z6XBxpSRIPd`正常结束。首次补充检查因模块导入失败，已停止其CPU app并修正，不涉及数据修改。

详细inventory只保留在Modal：`devbox/storage_breakdown_20261018/{assets,weights,runs,candidates}.json`。容量检查app为`ap-34mqAFy1uWRbBqCaKdwS7j`，正常结束；目录项快照runs余71,279/500,000、assets余434,353/500,000。
