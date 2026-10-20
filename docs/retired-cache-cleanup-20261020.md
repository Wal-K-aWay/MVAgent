# 旧媒体缓存与复现源码副本清理

用户于2026-10-20明确授权清理已列出的三个旧媒体缓存，以及复现实验重复源码副本。
只操作runs；不压缩，不删除assets/weights、正式原始答案、轨迹或评分，也不停止当前实验。

固定媒体范围：

- `devbox/external_upstream_nc80_20261015/prepared/media`
- `devbox/rsi_budget_20261015/prepared/media`
- `devbox/external_methods_20261014/media`

先检查全卷符号链接、Git alternates、当前两方法32卡任务的源码及输入元数据。
被引用的缓存保留，其余按精确清单删除；清单保存大小、模式、mtime。
所属历史实验的缓存之外文件做SHA256前后核验。旧媒体重跑需重新生成，不影响保存的答案与评分。

仅对`devbox/repro_expanded_session_20261012_r3`下的`driver_dependencies`及`runtime/src`目录去重：
逐文件内容、相对路径与模式完全相同的副本共用一份；有链接或外部引用的树不迁移。
旧路径用目录符号链接保持可读，每种不同内容各保留一份，不删除独有源码或配置。
历史设计和结论仍见`devbox/cache_repro_cleanup_20261019/documentation/`。

审计根：`devbox/retired_cache_cleanup_20261020`。
其中`shared_dependencies/`是保留的规范副本，后续不得当作普通清理日志删除。
`plan.json`保存删除清单、引用保护、去重前映射与保留文件SHA；
`completed.json`保存执行结果，独立新挂载的`verified.json`保存最终核验。

脚本：`scripts/cleanup_retired_caches_20261020.py`，复用前次清理的保护路径、清单和SHA实现。
已执行清理，内容净减少12,294,433,042字节（约12.29GB），26,594个文件/目录项。
净减少量已扣除两份保留的共享源码树，但不包括新增的小型审计记录，也不抵消其他实验同时写入的数据。

| 范围 | 实际操作 |
|---|---|
| `external_upstream_nc80_20261015/prepared/media` | 删除7,762,969,306字节 |
| `rsi_budget_20261015/prepared/media` | 删除4,421,766,311字节 |
| `external_methods_20261014/media` | 保留约2.94GB，存在历史链接及在用冻结源码引用 |
| 80份`driver_dependencies` | 内容相同，共用一份；旧路径保留为目录链接 |
| 80份`runtime/src` | 内容相同，共用一份；旧路径保留为目录链接 |
| 各rank的`input_config.yaml` | 存在真实差异，逐份原样保留 |

80份依赖目录的统一签名为`92624f2531cc16ad87500230432e66038325228f06e55c95aab8a804d0749335`，
80份源码目录为`8ee884dae3186fc8fda338f535fca032e0468f43b385aee6bfc850dae419815b`；
签名包含相对路径、文件模式和内容SHA，而不只比较目录大小。
此前复现实验设计与负结果文档保留不动；assets、weights、LensWalk正式原始结果及新任务继承原件均未删除。

准备任务`ap-dZfU1PKNxetZcEaFWJef2d`正常结束，并保存24,695份保留文件SHA；
保护/内容差异/符号链接测试`ap-7gN4aBGSwHNd4o8rN99NqZ`、`ap-0r9fdc77zjKb69XiEuDmOn`通过。
runtime/src核验`ap-g6x6TF2J6Xyq1Ub4nAKqIn`完成；apply任务
`ap-VAAND4VE5ni3wipwjBJPOf`于2026-10-20 13:52:48 UTC正常结束，执行源码`985abaf`。
执行前当前8个GPU容器的进程与打开文件检查未发现候选路径占用；再次核对引用和清单后才删除。
未启动新GPU、没有压缩、没有停止或重启原任务。

独立新挂载核验`ap-319PRx49s0hfrUVuRJUXnC`已正常结束，`verified=true`：
24,695份保留文件SHA全部一致，160个旧源码路径均链接到正确规范副本，源码签名不变，
清单内已删除路径均不存在。核验时目录项已用413,544/500,000（82.7088%），剩余86,456。
此前apply启动快照为440,378（88.08%）；其他实验同时新增/删除文件，因此配额差值不等同于本次净减少量。
审计原件及规范源码仅留Modal；本地状态/环境skill笔记不进入Git。其他会话未提交的源码未纳入本次备份。
