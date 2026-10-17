#!/usr/bin/env python3
"""Consolidate vLLM option probes and real evaluation timings on the runs volume."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screens", type=Path, nargs="+", required=True)
    parser.add_argument("--fixed", type=Path, nargs="+", required=True)
    parser.add_argument("--evaluations", type=Path, nargs="+", required=True)
    parser.add_argument("--confirmation", type=Path, nargs="+", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not str(args.output).startswith("/runs/"):
        raise SystemExit("Raw analysis belongs on the runs volume")
    args.output.mkdir(parents=True, exist_ok=True)
    screens = []
    for root in args.screens:
        for row in read(root / "summary.json"):
            row = {**row, "root": str(root)}
            pruned = root / row["variant"] / "pruned.json"
            row["pruned"] = read(pruned) if pruned.exists() else None
            screens.append(row)
    evaluations = []
    for root in args.evaluations:
        manifest = read(root / "manifest.json")
        for row in read(root / "summary.json"):
            evaluations.append({**row, "root": str(root), "routing": manifest["arguments"]["routing"],
                                "input_mode": ("prepared" if manifest["arguments"].get("prepared") else
                                               "cold_media" if manifest["arguments"].get("cold_media") else "media_cache"),
                                "full_validation": manifest["arguments"].get("restarts", 0) >= 1 and manifest["arguments"].get("passes", 0) >= 3,
                                "input_preparation_seconds": manifest.get("input_preparation_seconds")})
    fixed = []
    for root in args.fixed:
        manifest = read(root / "manifest.json")
        engine_mode = "sync/in-process" if manifest["config"].get("async_scheduling") is False else "async/multiprocess"
        fixed.extend({**row, "root": str(root), "engine_mode": engine_mode} for row in read(root / "summary.json"))
    confirmation = [{**row, "root": str(root)} for root in args.confirmation
                    for row in read(root / "summary.json")]
    result = {"screens": screens, "fixed_batch": fixed, "evaluations": evaluations,
              "confirmation": confirmation}
    baseline = next((r for r in evaluations if r["variant"] == "baseline"), None)
    if baseline:
        reference = read(Path(baseline["root"]) / "baseline/restart0/references.json")
        for row in evaluations:
            path = Path(row["root"]) / row["variant"] / "restart0/references.json"
            actual = read(path) if path.exists() else {}
            common = sorted(reference.keys() & actual.keys())
            row["vs_baseline"] = {"compared": len(common),
                "same_inputs": all(all(reference[k][f] == actual[k][f] for f in ["request_sha256", "prompt_token_ids_sha256"]) for k in common),
                "identical_outputs": sum(reference[k]["token_ids"] == actual[k]["token_ids"] for k in common)}
    for row in evaluations:
        native = next((r for r in evaluations if r['variant'] == row['variant'] and r['input_mode'] == 'media_cache'), None)
        if row['input_mode'] != 'prepared' or native is None:
            continue
        a = read(Path(native['root']) / native['variant'] / 'restart0/references.json')
        b = read(Path(row['root']) / row['variant'] / 'restart0/references.json')
        common = sorted(a.keys() & b.keys())
        row['vs_native_pipeline'] = {'compared': len(common),
            'identical_requests_and_tokens': sum(a[k] == b[k] for k in common)}
    lines = ["# vLLM 测评速度与逐 token 复现：扩展实验", "",
             "硬件：同一台8×H100 80GB；vLLM0.19.1 / torch2.10.0 / transformers4.57.6。",
             "模型：Qwen3.5-35B-A3B，除标明BF16的配置外均用官方FP8权重。每服务TP=1、DP=1。",
             "采样temperature=0、seed=0、thinking关闭；KV cache始终启用、dtype为BF16。",
             "没有使用输出响应缓存或请求去重代替推理。每个配置有自己的参考输出；不要求不同配置互相给出相同答案。", "",
             "单卡H100 80GB已实际装下两种精度，无须为装载35B而使用大TP。prepared实验server_0启动日志记录：", "",
             "| 单卡模型 | 权重加载显存 GiB | gpu_memory_utilization | 可用于KV cache GiB |",
             "|---|---:|---:|---:|", "| FP8 | 34.23 | 0.85 | 30.36 |", "| BF16 | 65.53 | 0.95 | 6.98 |", "",
             "这是本轮配置的运行时预算，不能当成任意长度或并发的容量证明；增大并发后的逐token反例见下。", "",
             "## 单卡方案筛选", "",
             "8组输入（文本、32/128/512帧及4个prompt变体），固定生成256 token。先建立冷参考，再两轮乱序C1和C2测量。",
             "不同配置分占GPU，且与CPU输入准备并行；这些速度只用于选候选，不外推为8卡吞吐。",
             f"完成 {sum(s['formal_samples'] for s in screens)} 次正式响应、{sum(s['warmup_samples'] for s in screens)} 次冷参考/预热。", "",
             "| 配置 | 每副本并发 | 正式样本 | token差异 | 两轮通过 | 单卡请求/min |",
             "|---|---:|---:|---:|---|---:|"]
    for row in screens:
        for level in row.get("levels", []):
            lines.append(f"| {row['variant']} | {level['concurrency']} | {level['samples']} | {level['mismatches']} | {level['stable']} | {level['requests_per_minute']:.2f} |")
    for row in screens:
        if row.get("pruned"):
            lines += ["", f"`{row['variant']}`按速度剪枝：{row['pruned']['reason']}。未完成的并发检查不视为通过。", ""]
    lines += ["", "`mm_cache`：4GiB shared-memory多模态预处理缓存；`prefix_cache`在此基础上启用Mamba align前缀缓存；",
              "`mtp1/mtp2`在MM缓存基础上分别推测1/2个token；`invariant_nochunk`关闭chunked prefill；`invariant_eager`关闭编译和CUDA graph。",
              "首次prefix探针因reset路由未开放而0样本失败；设置VLLM_SERVER_DEV_MODE=1后重试，保留两次记录。",
              "MTP1在并发2测试中有两次请求因EngineCore的Encoder cache miss断言故障失败；该并发未通过。", "",
              "## 固定batch探针", "",
              "离线LLM.chat，固定256 token；依次串行、固定两题组合、反转组内顺序、更换同组题目，每种模式两轮。",
              "下表的重复差异相对于同模式第一轮；串行差异相对于逐题单独运行的输出。", "",
              "| 引擎 | 模式 | 轮次 | 样本 | 同模式重复差异 | 与串行差异 | 单卡请求/min |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for row in fixed:
        lines.append(f"| {row['engine_mode']} | {row['mode']} | {row['repeat']} | {row['samples']} | {len(row['repeat_mismatches'])} | {len(row['serial_mismatches'])} | {row['requests_per_minute']:.2f} |")
    lines += ["", "同步单进程模式关闭VLLM_ENABLE_V1_MULTIPROCESSING与async_scheduling；固定分组可重放不等于单条请求独立于同组其他输入。"]
    lines += ["", "## 真实CVBench评测流程", "",
              "15题型各2题，共30题（开发面板），使用项目E2E原生prompt、512帧上限、最长边448和max_tokens128。",
              "media_cache模式计时包括媒体磁盘缓存读取、请求构建、模型推理及官方评分；首次解码/编码耗时单列。",
              "prepared模式一次性缓存输入请求字节，每次仍重新推理；首次载入/构建耗时单列，吞吐是复用输入后的每轮速度。两种模式都包含token/hash审计成本。",
              "sticky路由将每题固定到一个副本，重启后轮移到另一张GPU；dynamic路由使用下一个空闲副本。",
              "balanced路由按此前同面板热请求耗时做贪心负载均衡，之后仍固定副本且重启后轮移；它在开发面板上校准，不能视为未见题的加速证明。",
              "通常每次启动三轮、两次启动；首轮建立冷参考/检查重启，后两轮计吞吐。cold_media只跑一次启动两轮。所有轮次均比较完整token ID及请求、prompt哈希。", "",
              "| 配置 | 路由 | 输入模式 | 正式/冷参考 | token差异 | 所设轮次通过 | 题/min |",
              "|---|---|---|---:|---:|---|---:|"]
    for row in evaluations:
        rate = f"{row['questions_per_minute']:.2f}" if row['questions_per_minute'] is not None else "—"
        lines.append(f"| {row['variant']} | {row['routing']} | {row['input_mode']} | {row['formal_samples']}/{row['warmup_samples']} | {row['mismatches']} | {row['stable']} | {rate} |")
    for root in args.evaluations:
        manifest = read(root / "manifest.json")
        if manifest["arguments"].get("prepared"):
            lines += ["", f"`{root.name}`：首次输入载入/编码 {manifest['input_preparation_seconds']:.2f} 秒，随后共用这些输入请求字节。"]
    for row in evaluations:
        if row.get("error"):
            lines += ["", f"`{row['variant']}`：{row['error']}；目录 `{row['root']}/{row['variant']}`。", ""]
        if row.get('vs_native_pipeline'):
            match = row['vs_native_pipeline']
            lines += ['', f"`{row['variant']}`预编码前后请求hash、prompt token hash和完整输出token均相同：{match['identical_requests_and_tokens']}/{match['compared']}。"]
    if baseline:
        lines += ["", "跨配置输入与输出核对（取每题首次完整输出）：", ""]
        for row in evaluations:
            match = row["vs_baseline"]
            lines.append(f"- `{row['variant']}/{row['routing']}/{row['input_mode']}`：与基线输入字节及prompt token哈希相同 {match['same_inputs']}，"
                         f"输出逐token相同 {match['identical_outputs']}/{match['compared']}。")
    eligible = [r for r in evaluations if r["stable"] and r["full_validation"]]
    if eligible:
        best = max(eligible, key=lambda r: r["questions_per_minute"])
        result["best_evaluation"] = best
        lines += ["", f"实际评测中吞吐点估计最高的通过配置：`{best['variant']}`，路由 `{best['routing']}`，输入模式 `{best['input_mode']}`，{best['questions_per_minute']:.2f} 题/min。少量同机重复不构成显著性或全局最优证明。"]
    fp8_candidates = [r for r in eligible if r['variant'] == 'prefix_cache' and r['input_mode'] == 'prepared']
    fp8_prepared = max(fp8_candidates, key=lambda r: r['questions_per_minute']) if fp8_candidates else None
    if baseline and fp8_prepared:
        lines += ["", "### 可复用配置", "",
                  f"FP8 + MM/prefix缓存 + 预编码输入：{fp8_prepared['questions_per_minute']:.2f}题/min，相对本轮基线{fp8_prepared['questions_per_minute']/baseline['questions_per_minute']:.2f}×。",
                  "8个独立单卡服务，每服务TP=1、DP=1，客户端每副本并发1；按题固定路由以复用缓存。并非vLLM内置DP=8。",
                  "temperature=0、seed=0、thinking=false；max_num_seqs=8、max_num_batched_tokens=16384、max_model_len=131072；",
                  "mm_encoder_tp_mode=weights、mm_processor_cache_gb=4、mm_processor_cache_type=shm、enable_prefix_caching=true、mamba_cache_mode=align；",
                  "dtype=bfloat16、kv_cache_dtype=auto，FP8显存比例0.85，BF16显存比例0.95；CPU三个线程变量均1，TOKENIZERS_PARALLELISM=false，VLLM_BATCH_INVARIANT=0。",
                  "VLLM_SERVER_DEV_MODE=1仅用于本地回环端点的实验缓存清空接口。不要把它作为生产服务的必要条件。",
                  "30题冻结输入约776MiB；全量题库宜分片准备并复用媒体，不将全部base64请求无限保留在内存。4GiB缓存仅证明承载了本面板。",
                  "开启prefix或改变精度会改变部分输出；必须将配置视为新的固定评测协议。输入预编码前后则有独立的请求hash与token核对。",
                  "目前收益用于重复测评；skill文本改变会削弱prefix命中，媒体缓存仍可复用。尚未测完整skill进化循环。"]
        raw_path = Path(fp8_prepared['root']) / 'prefix_cache/restart0/raw.jsonl'
        with raw_path.open() as handle:
            example = json.loads(next(handle))
        lines += ['', '实际模型响应示例（原始记录中的一题）：', '',
                  f"`{example['sample_id']}`，输出 `{example['output']}`，token IDs `{example['request']['token_ids']}`。"]
    sticky = next((r for r in eligible if r['variant'] == 'prefix_cache' and r['input_mode'] == 'prepared' and r['routing'] == 'sticky'), None)
    balanced = next((r for r in eligible if r['variant'] == 'prefix_cache' and r['routing'] == 'balanced'), None)
    if sticky and balanced:
        rates = [p['questions_per_minute'] for p in balanced['passes'] if p['name'] != 'pass0']
        lines += ['', f"按实测耗时均衡路由为{balanced['questions_per_minute']:.2f}题/min，相对简单固定路由{sticky['questions_per_minute']:.2f}仅高{(balanced['questions_per_minute']/sticky['questions_per_minute']-1)*100:.2f}%；各热轮{min(rates):.2f}–{max(rates):.2f}，收益未稳定超出波动。",
                  '因此优先复用简单固定路由的FP8配置，保留更大的显存余量；BF16及均衡路由的少量速度差异不视为显著优势。']
    lines += ["", "### 各轮成绩与耗时", "",
              "这是30题开发面板，不能作为完整CVBench的准确率结论；分层估计按全集题型数量加权。", "",
              "| 配置/路由 | 启动编号 | 轮次 | 样本 | 秒 | 面板准确率 | 分层官方分估计 | 差异 |",
              "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in evaluations:
        for p in row["passes"]:
            acc = f"{p['panel_accuracy']:.4f}" if p["panel_accuracy"] is not None else "—"
            estimate = f"{p['estimated_official_accuracy']:.4f}" if p["estimated_official_accuracy"] is not None else "—"
            lines.append(f"| {row['variant']}/{row['routing']}/{row['input_mode']} | {p['restart']} | {p['name']} | {p['samples']} | {p['seconds']:.2f} | {acc} | {estimate} | {len(p['mismatches'])} |")
    cold = [r for r in evaluations if r["input_mode"] == "cold_media"]
    if cold:
        lines += ["", "### 首次处理新输入：含视频解码", "",
                  "每个配置从空应用层媒体缓存和新模型服务开始；操作系统页缓存未控制。首轮包含解码、请求构建、推理、审计和评分。", "",
                  "| 配置 | 题数 | 秒 | 首次题/min |", "|---|---:|---:|---:|"]
        for row in cold:
            p = row["passes"][0]
            lines.append(f"| {row['variant']} | {p['samples']} | {p['seconds']:.2f} | {p['questions_per_minute']:.2f} |")
    if confirmation:
        lines += ["", "## 长输出与冷/热缓存复核", "", "上限2048 token、正常EOS；8组输入、跨副本、乱序、服务重启及纯512帧负载。", ""]
        for row in confirmation:
            lines.append(f"- `{row['variant']}`：通过 {row['stable']}，正式 {row['formal_samples']}、冷参考 {row['warmup_samples']}、token差异 {row['mismatches']}；错误 {row['error']}。")
            rows = [json.loads(line) for p in (Path(row['root']) / row["variant"]).glob("restart*/records.jsonl") for line in p.read_text().splitlines()]
            lengths = [r["output_tokens"] for r in rows]
            lines.append(f"  输出长度{min(lengths) if lengths else 0}–{max(lengths) if lengths else 0}，结束原因：{dict(Counter(r['finish_reason'] for r in rows))}。")
            for phase in ["measure", "long512", "reset"]:
                ps = [p for p in row["passes"] if p["phase"] == phase]
                if ps:
                    count = sum(p["samples"] for p in ps)
                    lines.append(f"  {phase}：{count}次，{count*60/sum(p['seconds'] for p in ps):.2f} 请求/min。")
            for case in sorted({r['case'] for r in rows if r['phase'] == 'long512'}):
                tokens = sorted({r['output_tokens'] for r in rows if r['phase'] == 'long512' and r['case'] == case})
                lines.append(f"  `{case}` 的实际输出长度：{tokens} token。")
        lines += ['', '不同权重/推理配置会生成不同长度的回答；这里的正常EOS吞吐是实际负载成本，不能单独归因于FP8或BF16的计算速度。']
    lines += ["", "## 边界与留档", "",
              "所有通过只表示已测输入、版本、硬件和配置的重复一致；有限测试不能证明任意输入或任意长运行都确定。",
              "8组探针和30道CVBench题都已作为开发数据使用；未测完整MVAgent多步循环、CrossVid或全部benchmark。",
              "不同输出长度、单卡/整机、模型请求/整个评测流程的吞吐不能直接混比。",
              "每轮保留源码快照、版本、commit/源码hash、模型配置、启动命令、输入hash、完整输出token IDs和原始模型文本，原始数据仅在Modal runs volume。",
              "vLLM0.19.1的batch invariance文档未列出Qwen3.5：[版本说明](https://raw.githubusercontent.com/vllm-project/vllm/v0.19.1/docs/features/batch_invariance.md)。",
              "缓存与MTP设置参考[官方Qwen配方](https://raw.githubusercontent.com/vllm-project/recipes/main/Qwen/Qwen3.5.md)，采用前均以本轮实测验证。", "",
              "原始结果volume：`wxu-evolve-agent-runs-20261006`。本轮无skill库或Judge；冻结输入及其哈希界定开发面板。", ""]
    for root in [*args.screens, *args.fixed, *args.evaluations, *args.confirmation]:
        lines.append(f"- `{root}`")
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output / "report.md").write_text("\n".join(lines) + "\n")
    source = Path(__file__).read_bytes()
    (args.output / Path(__file__).name).write_bytes(source)
    print(json.dumps({"best": {k: v for k, v in result.get("best_evaluation", {}).items() if k not in {"passes", "traceback"}},
                      "report_source_sha256": hashlib.sha256(source).hexdigest()}))


if __name__ == "__main__":
    main()
