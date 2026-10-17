# 在其他设备获取AgentCVR结果

结果通过GitHub Release附件分发，数据不进入Git提交历史。仓库与Release均公开。

Release页面：https://github.com/Wal-K-aWay/MVAgent/releases/tag/agentcvr-results-20261017

- `cvbench.answers.jsonl`：997题原始答案、参考答案和官方评分。
- `mvu-eval.answers.jsonl`：1824题原始答案、参考答案和官方评分。
- `official-scores.json`、`summary.json`：逐题及最终汇总结果。
- `agentcvr-results-20261017.tar.gz`：完整5658文件，含2821份raw JSON、2821份records、答案表、配置/输入/评分/审计元数据和逐文件校验清单；解压约1.80GB。
- `SHA256SUMS`：所有发布的数据与报告附件校验值。
- Markdown报告：评测设置、分数及本地副本说明。

只看逐题答案可下载两个JSONL；需要模型轨迹和token记录时下载完整包。在其他设备可用普通GitHub CLI：

```bash
gh release download agentcvr-results-20261017 --repo Wal-K-aWay/MVAgent --dir agentcvr-download
cd agentcvr-download
sha256sum -c SHA256SUMS --ignore-missing
mkdir -p results
tar -xzf agentcvr-results-20261017.tar.gz -C results
```

未安装GitHub CLI时，在Release页面Assets直接下载即可。`git clone`和GitHub自动生成的Source code压缩包不包含结果附件。

CVBench567/997=56.87%，MVU-Eval803/1824=44.02%。这是作者公开版本的跨benchmark适配评测，完整差异见final_results.md和official_settings_audit.md；未搬运媒体、权重或冻结执行环境。Lightsail与Modal原件保留。
