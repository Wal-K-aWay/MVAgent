# Qwen3.5 三模型 E2E 结果下载

2026-10-17 按用户要求将已完成的结果发布到公开 GitHub Release：
https://github.com/Wal-K-aWay/MVAgent/releases/tag/qwen35-e2e-results-20261017

数据通过 Release 附件分发，不进入 Git 历史。Lightsail 分析副本和 Modal 原件保留。
Release 标签所指提交只用于发布文档，不是实验源码快照；实际运行身份见数据包内 manifest。

## 内容

完整包 `qwen35-e2e-results-20261017.tar` 为 62,545,920 字节，解包得到 `e2e/`。
包含 704 个文件（61,171,031 字节）：698 个迁入数据/元数据文件，以及本地报告和迁移记录。
698 个迁入文件逐一重新核对了原迁移清单的大小与 SHA256；归档内全部文件也逐一核对。

- `9B/`、`27B/`、`35B-A3B/`：逐题原始回答、输出 token、逐题评分、汇总、题目清单、运行 manifest 和 Judge 缓存。
- `analysis/`：汇总分析、Judge 缓存核查与 MVU 配对分析。
- `reports/final_results.md`：官方分、稳健分、分项、设置和已知限制。
- `transfer_*.json`：原始迁移来源及完整性记录。

原位置基线每模型 5,321 条有效回答，共 15,963 条；MVU 指令移后复测每模型 1,824 条，共 5,472 条。
总计 21,435 条有效回答，另保留 CVBench 损坏视频题的 9 条错误记录（三模型各 3 条）。

## 官方分数（%）

| 模型 | CVBench（997题） | MVU 原位置（1824题） | MVU 指令移后（1824题） | CrossVid Lite2500 |
|---|---:|---:|---:|---:|
| Qwen3.5-9B | 62.09 | 15.84 | 37.72 | 31.98 |
| Qwen3.5-27B | 68.10 | 46.22 | 44.46 | 42.01 |
| Qwen3.5-35B-A3B | 64.19 | 25.00 | 36.62 | 32.11 |

MVU 原位置为“问题→官方指令→选项”，移后为“问题→选项→同一句官方指令”。
`raw/mvu_eval.jsonl` 与 `scored/mvu_eval.json` 对应原位置；
`raw/mvu_eval_instruction_after.jsonl` 与 `scored/mvu_eval_instruction_after.json` 对应移后。
不要混合两套结果。稳健解析分单独列于总报告，不能当作官方分。

CVBench 排除损坏视频题 64–66，不能声称完成全部 1,000 题；CrossVid 是 Lite2500 子集，按十类任务宏平均。
CrossVid 35B-A3B 有两条历史 Judge 评分与当前共享缓存不一致，保留原评分；
若统一使用当前缓存，总分由 32.1111 变为 32.1375，详见总报告。本次发布未重新推理或评分。

## 在其他机器下载

可在 Release 页面直接下载全部 5 个附件；公开附件无需登录。
也可以在空目录运行：

```bash
curl -fL -o SHA256SUMS https://github.com/Wal-K-aWay/MVAgent/releases/download/qwen35-e2e-results-20261017/SHA256SUMS
for f in qwen35-e2e-results-20261017.tar file_manifest.json final_results.md README.md; do
  curl -fL -o "$f" "https://github.com/Wal-K-aWay/MVAgent/releases/download/qwen35-e2e-results-20261017/$f"
done
sha256sum -c SHA256SUMS
tar -xf qwen35-e2e-results-20261017.tar
```

macOS 可用 `shasum -a 256 -c SHA256SUMS` 替代 `sha256sum -c`。
`file_manifest.json` 额外提供归档内每个文件的路径、大小和 SHA256，以及逐模型/benchmark 的记录数。
仅 `git clone` 不会下载 Release 附件。

## 范围

不含视频、模型权重、冻结运行环境或服务日志。完整重跑仍需 Modal 冻结源码和媒体；
manifest 中的提交号不足以重建含未提交改动的历史运行。
发布前校验数据和归档，上传后核对 GitHub 返回的附件大小与 SHA256，并检查匿名下载。

发布验证：2026-10-17T13:33:58.396883+00:00，5 个附件全部为 uploaded，GitHub 大小/SHA256 与本地一致，匿名下载 HEAD 全部 HTTP 200。校验收据保存在 Lightsail 的 `outputs/e2e_release_20261017/release_verification.json`。
