# Qwen3.5 三模型 E2E 精简结果

本 Release 已按用户要求替换为精简结果，覆盖 **9B、35B-A3B、27B**；不含代码、token ID、运行日志、媒体或权重。
下载 `qwen35-e2e-results-compact.tar.gz`，解压后直接得到三个模型目录。每个目录仅有：

- `cvbench.jsonl`
- `mvu_eval.jsonl`：官方指令原位置
- `mvu_eval_instruction_after.jsonl`：官方指令移到选项后
- `crossvid.jsonl`
- `crossvid_ccqa_scores.jsonl`：239题的历史评分、coverage/correctness、评分点数及Judge身份
- `results.md`：仅含benchmark统计表（官方分、稳健分、有效题数及平均整题用时）

逐题字段：`id`、`gt`、`raw_output`、`seconds`、`status`。原始输出全文保留，不提取或改写为选项字母。
`seconds`为原记录顶层整题耗时，包含预处理等开销，不是纯模型推理时间；失败记录的输出为null。
GT来自原评分记录；三道损坏CVBench题的GT来自原题库。

共18文件、13,533,713字节；21,435条有效回答，另保留9条坏视频失败记录。MVU两种提示位置分开保存，不应混合统计。

| 模型 | CVBench官方分（997题） | MVU原位置 → 移后（各1824题） | CrossVid Lite2500官方macro |
|---|---:|---:|---:|
| 9B | 62.09 | 15.84 → 37.72 | 31.98 |
| 35B-A3B | 64.19 | 25.00 → 36.62 | 32.11 |
| 27B | 68.10 | 46.22 → 44.46 | 42.01 |

CrossVid按十类任务等权宏平均，CCQA按评分点加权。CVBench排除损坏视频题64–66，不能声称完成全部1000题。
35B-A3B两条历史CCQA评分与当前共享缓存不一致，本包保留原评分；若替换为当前缓存，CrossVid由32.1111变为32.1375。
稳健解析分不是官方分。本包是已有结果的字段精简，没有新增推理或评分。

用`sha256sum -c SHA256SUMS`校验附件；macOS使用`shasum -a 256 -c SHA256SUMS`。
完整原始回答、token和运行元数据仍保留在Lightsail及Modal，精简包不用于完整运行追溯或重建历史环境。
原完整附件已由本精简包替换；Release标签仍是历史发布标签，不是本次数据整理的源码快照。

发布入口：https://github.com/Wal-K-aWay/MVAgent/releases/tag/qwen35-e2e-results-20261017

精简归档2,644,734字节；SHA256：`b835ca2e60d5d4169db29e9cbd2e4e28b8636fc081d8bea74757cb9e8c311751`。
