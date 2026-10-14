#!/usr/bin/env python3
"""Audit the completed instruction-position experiment and write its paired report."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import statistics


def read(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def signature(request):
    return json.dumps({k: request[k] for k in ['request_sha256', 'input_sha256',
        'prompt_token_ids_sha256', 'worker', 'token_ids', 'finish_reason']}, sort_keys=True)


def metrics(rows, scores):
    assert rows.keys() == scores.keys() and rows
    n = len(rows)
    return dict(n=n, accuracy=sum(r['score'] for r in scores.values()) / n,
        robust_accuracy=sum(r['robust_score'] for r in scores.values()) / n,
        format_rate=sum(r['format_ok'] for r in scores.values()) / n,
        single_letter_rate=sum(scores[sid]['format_ok'] and len(r['output'].strip()) == 1 for sid, r in rows.items()) / n,
        mean_output_tokens=statistics.mean(r['request']['usage']['completion_tokens'] for r in rows.values()),
        mean_request_seconds=statistics.mean(r['request']['seconds'] for r in rows.values()),
        finish_reasons=dict(Counter(r['request']['finish_reason'] for r in rows.values())))


def self_check():
    row = lambda text: dict(output=text, request=dict(usage={'completion_tokens': len(text)}, seconds=1, finish_reason='stop'))
    result = metrics({'a': row('A'), 'b': row('B. explanation'), 'c': row('Based on ...')},
        {'a': dict(score=1, robust_score=1, format_ok=True), 'b': dict(score=0, robust_score=0, format_ok=True),
         'c': dict(score=1, robust_score=0, format_ok=False)})
    assert result['accuracy'] == result['format_rate'] == 2/3
    assert result['robust_accuracy'] == result['single_letter_rate'] == 1/3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    self_check()
    output = args.output
    state = read(output / 'progress.json')
    assert state['phase'] == 'completed', state['phase']
    info = read(output / 'manifest.json')
    expected = set(info['selection']['mvu_eval'])
    assert len(expected) == 1824
    results = {}
    for model, old_path in info['baseline_outputs'].items():
        target, old = output / model, Path(old_path)
        rows_list, old_list = jsonl(target / 'raw/mvu_eval.jsonl'), jsonl(old / 'raw/mvu_eval.jsonl')
        rows = {r['sample_id']: r for r in rows_list}
        before = {r['sample_id']: r for r in old_list}
        scores = {r['sample_id']: r for r in read(target / 'scored/mvu_eval.json')}
        old_scores = {r['sample_id']: r for r in read(old / 'scored/mvu_eval.json')}
        assert len(rows_list) == len(old_list) == len(rows) == len(before) == 1824
        assert rows.keys() == before.keys() == scores.keys() == old_scores.keys() == expected
        identity = read(target / 'manifest.json')['identity']['model']
        old_identity = read(old / 'manifest.json')['identity']['model']
        assert identity['weights_manifest'] == old_identity['weights_manifest']
        # The 9B baseline predates the service-timeout increase; numerical settings are identical.
        assert {k: v for k, v in identity['execution'].items() if k != 'source_sha256'} == {
            k: v for k, v in old_identity['execution'].items() if k != 'source_sha256'}
        execution = identity['execution']
        assert execution['profile'] == 'qwen35-bf16-flashinfer-sync-v2'
        assert execution['config']['enable_prefix_caching'] is False
        assert execution['config']['tensor_parallel_size'] == execution['config']['max_num_seqs'] == 1
        cards = [read(p) for p in target.glob('servers/*/*/manifest.json')]
        assert len(cards) >= 8 and all(card['execution'] == execution for card in cards)
        assert len({r['request']['worker']['gpu_uuid'] for r in rows.values()}) == 8
        input_audit = read(target / 'input_audit.json')['input_sha256']
        for sid, row in rows.items():
            req = row['request']
            assert row['status'] == before[sid]['status'] == 'ok'
            assert req['generation'] == before[sid]['request']['generation']
            assert row['media'] == before[sid]['media']
            assert req['input_sha256'] == input_audit[sid] != before[sid]['request']['input_sha256']
            assert len(req['token_ids']) == req['usage']['completion_tokens'] and req['worker']['forward_calls'] > 0
            assert 'H100' in req['worker']['gpu_name']
            for key in ['answer', 'task']:
                assert scores[sid][key] == old_scores[sid][key]
        server_requests = [r for p in target.glob('servers/*/*/requests.jsonl') for r in jsonl(p)]
        client_signatures = Counter(signature(r['request']) for r in rows.values())
        server_signatures = Counter(signature(r) for r in server_requests)
        assert not client_signatures - server_signatures, 'Successful output missing from server log'
        attempts = [r for p in target.glob('rank*/raw/mvu_eval.jsonl') for r in jsonl(p)]
        results[model] = dict(before=metrics(before, old_scores), after=metrics(rows, scores),
            paired=read(output / 'comparison' / f'{model}.json'),
            audit=dict(valid_responses=len(rows), server_logged_requests=len(server_requests),
                unmatched_server_requests=sum((server_signatures-client_signatures).values()),
                error_attempts=sum(r['status'] != 'ok' for r in attempts),
                baseline_input_checks=len(rows), full_token_logs_checked=len(rows),
                physical_gpu_count=8, profile=execution['profile'], prefix_caching=False))
    path = output / 'analysis'
    path.mkdir(exist_ok=True)
    (path / 'analysis.json').write_text(json.dumps(results, indent=2) + '\n')
    shutil.copy2(__file__, path / 'analysis_source.py')
    lines = ['# MVU-Eval：官方指令移至选项后', '',
        '三模型各1824题，共5472条有效响应。官方原句一字未改，只从问题与选项之间移至选项之后。', '',
        '沿用上一轮固定帧缓存、BF16/v2、8×H100、TP1/DP1/每卡并发1、seed0、temperature0、thinking关闭、512帧/448像素、8192输出token。', '',
        '| 模型 | 官方准确率：前→后 | 变化(pp) | 格式合格率：前→后 | 稳健准确率：前→后 |',
        '|---|---:|---:|---:|---:|']
    pct = lambda x: f'{100*x:.2f}%'
    for model, result in results.items():
        a, b = result['before'], result['after']
        lines.append(f'| {model} | {pct(a["accuracy"])} → {pct(b["accuracy"])} | {100*(b["accuracy"]-a["accuracy"]):+.2f} | '
                     f'{pct(a["format_rate"])} → {pct(b["format_rate"])} | {pct(a["robust_accuracy"])} → {pct(b["robust_accuracy"])} |')
    for model, result in results.items():
        lines += ['', f'## {model}', '', '| Task | 题数 | 官方分：前→后 | 格式合格：前→后 | 稳健分：前→后 |', '|---|---:|---:|---:|---:|']
        for task, item in result['paired'].items():
            if task == 'all':
                continue
            cells = [f'{pct(item[key]["before"])} → {pct(item[key]["after"])}' for key in ['score', 'format_ok', 'robust_score']]
            lines.append(f'| {task} | {item["n"]} | ' + ' | '.join(cells) + ' |')
        a, b = result['before'], result['after']
        lines += ['', f'严格单字母率：{pct(a["single_letter_rate"])} → {pct(b["single_letter_rate"])}；'
            f'平均输出token：{a["mean_output_tokens"]:.1f} → {b["mean_output_tokens"]:.1f}；'
            f'平均请求秒数：{a["mean_request_seconds"]:.2f} → {b["mean_request_seconds"]:.2f}。',
            f'结束原因：{a["finish_reasons"]} → {b["finish_reasons"]}。',
            f'核查：{result["audit"]}。']
    lines += ['', '## 核查与限制', '',
        '每题推理前校验移动前的完整输入哈希与旧记录一致；实际服务manifest、权重、生成参数、帧数尺寸、完整输出token和服务端请求日志均核对。新旧整条请求哈希不同，符合文字顺序变化。', '',
        '官方分按首字符评分；格式合格允许选项后的附加文本，严格单字母率另报；稳健分读取明确的最终选项。三者不可混为准确率改善。', '',
        '这是复用开发集上的提示位置对照，不代表未见数据泛化，也没有重新执行重复性矩阵。9B旧基线采用600秒服务超时，新轮沿用1800秒恢复版；正常响应的数值配置相同，截断与基础设施错误另列。', '',
        f'原始数据与冻结源码：{output}（Modal runs volume）；本地只保留代码和Markdown报告。']
    report = '\n'.join(lines) + '\n'
    (path / 'report.md').write_text(report)
    print(report)


if __name__ == '__main__':
    main()
