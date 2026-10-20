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

仅对`devbox/repro_expanded_session_20261012_r3`下的`driver_dependencies`目录去重：
逐文件内容、相对路径与模式完全相同的副本共用一份；有链接或外部引用的树不迁移。
旧路径用目录符号链接保持可读，每种不同内容各保留一份，不删除独有源码或配置。
历史设计和结论仍见`devbox/cache_repro_cleanup_20261019/documentation/`。

审计根：`devbox/retired_cache_cleanup_20261020`。
其中`shared_dependencies/`是保留的规范副本，后续不得当作普通清理日志删除。
`plan.json`保存删除清单、引用保护、去重前映射与保留文件SHA；
`completed.json`保存执行结果，独立新挂载的`verified.json`保存最终核验。

脚本：`scripts/cleanup_retired_caches_20261020.py`，复用前次清理的保护路径、清单和SHA实现。
当前阶段：准备检查，尚未删除。
