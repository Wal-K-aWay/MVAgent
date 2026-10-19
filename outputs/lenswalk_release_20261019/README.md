# LensWalk精简结果下载

[GitHub Release：lenswalk-results-20261019](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019)

附件`lenswalk-results-compact-20261019.tar.gz`为68,458,441字节（68.46 MB），解压后368,776,097字节。包内只有五个文件：CVBench997题的`cvbench.jsonl`、MVU-Eval1824题的`mvu_eval.jsonl`、CrossVid2500题的`crossvid.jsonl`、239题的`ccqa_scores.jsonl`和纯统计表`statistics.md`。

每题字段为`id`、`gt`、`output`、`seconds`、`trajectory`。`output`原样保留框架返回值及类型，包括null；没有返回结果的9个工程失败记null并明确标记。`gt`保留评测用标注数组，CCQA包含参考答案和评分点。`seconds`为整题Agent耗时，视频准备耗时在`trajectory.prepared_seconds`中单列。

按用户要求，文本轨迹保留对话、工具调用/结果、请求耗时和token数量、终态/错误及源归档SHA；去掉图片Base64、完整token ID数组、重复HTTP请求/响应体及运行日志。没有代码、配置、视频或权重。此包可用于阅读轨迹、核对答案和统计耗时，不支持逐token重放；完整原件保留Modal。

```bash
gh release download lenswalk-results-20261019 --repo Wal-K-aWay/MVAgent --pattern '*.tar.gz' --dir lenswalk-results
cd lenswalk-results
sha256sum lenswalk-results-compact-20261019.tar.gz
mkdir -p results
tar -xzf lenswalk-results-compact-20261019.tar.gz -C results
```

SHA256应为`af4857b94b1354b66af002961b92b4ea47de371520d76d34e228c76d59b25d3d`。也可直接在Release的Assets下载；GitHub自动生成的Source code不是结果数据。

工程失败计零得分为CVBench55.37%、MVU-Eval33.72%、CrossVid十任务macro21.77%；保留3232正常终答、1669未收尾、411空答案、9工程失败。本次仅整理/发布，无新推理或Judge。

原始数据在runs `devbox/lenswalk_full_35b_parallel_media_20261018`；精简包、管理清单和全量核验在`devbox/lenswalk_release_compact_20261019`。导出源码`0ace77a`，前段由同一精简逻辑`273c718`生成；一次CPU平台回收后校验并保留3997条完整记录，仅补余1324条。5321份源归档/选用成员的SHA和五个压缩包成员的大小/SHA均已核验。

纯CPU全量检查确认5321题GT、原答案、耗时逐项一致；97762次调用的token计数与原记录一致；0图片编码、0token ID数组、0重复HTTP体。GitHub附件ID655417059，大小/digest与本地及Modal一致；经modal-gpu无凭据完整下载HTTP200，68,458,441字节/SHA再核对一致。Lightsail直连CDN遇到TLS EOF，未关闭证书校验，改由devbox完成验证。上传包和核验回执暂存Lightsail `outputs/lenswalk_release_20261019/`，数据不进入Git。AgentCVR和Qwen E2E的Release未修改。
