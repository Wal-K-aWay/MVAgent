#!/usr/bin/env python3
"""Exercise the public E2E CLI, HTTP replicas, restart/resume, and exact tokens on Modal."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'eval/e2e_eval'))
import httpx
from harness.backends import VLLMBackend
from harness.common import load_jsonl, read_json, sha256_file, write_json
from models.vlm.local.sync_server import ENGINE_CONFIG, digest
from benchmark_qwen35_fp8 import event
from confirm_single_process_gpu import prepare_cases, difference

MODELS = ['35B-A3B', '9B', '27B']
PANEL = Path('/runs/devbox/agent_replica_repro_20261011/panel/inputs.json')


def records(directory):
    rows = [row for name in ['cvbench', 'mvu_eval', 'crossvid']
            for row in load_jsonl(directory / 'raw' / (name+'.jsonl'))]
    if any(row['status'] != 'ok' for row in rows):
        raise RuntimeError(f'{directory}: failed records: {[r["sample_id"] for r in rows if r["status"] != "ok"]}')
    assert len(rows) == len({row['sample_id'] for row in rows})
    return {row['sample_id']: row for row in rows}


def compare_rows(before, after):
    if set(before) != set(after):
        raise ValueError('Repeated selections differ')
    changed = []
    for sid, row in after.items():
        a, b = before[sid]['request'], row['request']
        delta = difference(dict(input_sha256=a['input_sha256'], prompt_sha256=a['prompt_token_ids_sha256'], token_ids=a['token_ids']),
                           dict(input_sha256=b['input_sha256'], prompt_sha256=b['prompt_token_ids_sha256'], token_ids=b['token_ids']))
        if any(delta.values()) or before[sid]['output'] != row['output'] or a['finish_reason'] != b['finish_reason']:
            changed.append(dict(sample_id=sid, **delta, text_changed=before[sid]['output'] != row['output'],
                                finish_changed=a['finish_reason'] != b['finish_reason']))
    return changed


def raw_hashes(directory):
    return {p.name: sha256_file(p) for p in (directory / 'raw').glob('*.jsonl')}


def audit_run(directory):
    rows = records(directory)
    manifest = read_json(directory / 'manifest.json')
    identity = manifest['identity']
    assert identity['model']['execution']['config'] == ENGINE_CONFIG
    assert identity['protocol'] == {'frames_per_call': 512, 'max_side': 448}
    for relative, sha in identity['source']['files'].items():
        assert sha256_file(directory / 'source' / relative) == sha
    replicas = manifest['runs'][0]['backend']['replicas']
    expected_max = {'cvbench': 128, 'mvu_eval': 8192, 'crossvid': 8192}
    for sid, row in rows.items():
        req = row['request']
        for key, value in replicas[req['endpoint']].items():
            assert req['worker'][key] == value
        assert req['worker']['forward_calls'] > 0
        assert len(req['token_ids']) == req['usage']['completion_tokens']
        assert req['generation']['max_tokens'] == expected_max[sid.split(':')[0]]
        assert req['generation']['seed'] == req['generation']['temperature'] == 0
        assert req['generation']['chat_template_kwargs'] == {'enable_thinking': False}
    return rows


def report(output):
    runs = read_json(output / 'runs.json')
    metadata = read_json(output / 'manifest.json')
    count = metadata['case_count']
    prepared_inputs = None
    if metadata.get('prepared_media_cache'):
        audit_file = Path(metadata['prepared_media_cache']) / 'input_audit.json'
        assert sha256_file(audit_file) == metadata['prepared_input_audit_sha256']
        prepared_inputs = read_json(audit_file)['input_sha256']
    lines = ['# 正式 E2E 同步执行入口验收', '',
        '使用原 run.py infer / --endpoints / --ids 接口，每调用最多512帧/最长边448，原benchmark提示与输出预算保持不变。不评分、不调用Judge。',
        '8个独立BF16/TP1/DP1/C1/uni进程，同步eager、FlashInfer GDN，prefix/MM缓存关闭；HTTP处理和实际forward均在同一个进程主线程串行执行。', '',
        '| 模型 | 正式CLI响应 | 重复比较 | 不一致 | 曾换到其他GPU的题目 | 全池GPU覆盖 |',
        '|---|---:|---:|---:|---:|---:|']
    metrics, details = [], []
    for model in MODELS:
        stages = [r for r in runs if r['model'] == model and r['kind'] == 'panel']
        assert len(stages) == 4
        stages.sort(key=lambda r: (r['phase'], r['repeat']))
        panels = [audit_run(Path(s['output'])) for s in stages]
        assert all(len(rows) == count for rows in panels)
        if prepared_inputs is not None:
            assert all(row['request']['input_sha256'] == prepared_inputs[sid] for rows in panels for sid, row in rows.items())
        differences = [dict(stage=i, **change) for i, rows in enumerate(panels[1:], 1)
                       for change in compare_rows(panels[0], rows)]
        crossed = sum(len({rows[sid]['request']['worker']['gpu_uuid'] for rows in panels}) > 1 for sid in panels[0])
        coverage = {row['request']['worker']['gpu_uuid'] for rows in panels for row in rows.values()}
        assert len(coverage) == 8
        row = dict(model=model, responses=4*count, comparisons=3*count, differences=differences,
                   crossed_questions=crossed, gpu_count=len(coverage),
                   finish_reasons=dict(Counter(r['request']['finish_reason'] for rows in panels for r in rows.values())),
                   prompt_max=max(r['request']['usage']['prompt_tokens'] for rows in panels for r in rows.values()),
                   seconds=sum(s['seconds'] for s in stages))
        metrics.append(row)
        lines.append(f'| {model} | {4*count} | {3*count} | {len(differences)} | {crossed}/{count} | 8/8 |')
        bridge = read_json(output / model / 'bridge.json')
        assert len(bridge) == 8
        smoke = audit_run(output / model / 'p1_smoke0')
        row['smoke_differences'] = compare_rows({sid: panels[0][sid] for sid in smoke}, smoke)
        row['bridge_differences'] = [dict(case=r['case'], **r['differences']) for r in bridge if r['differences']]
        details.append(f'{model}：另有3个冒烟响应，与面板同题比较{len(row["smoke_differences"])}个差异；'
                       f'与旧进程内探针对照8个冻结输入，{len(row["bridge_differences"])}个差异；'
                       f'端到端四轮总墙钟{row["seconds"]:.2f}秒（含解码/HTTP/推理/落盘，不含服务加载），'
                       f'结束原因{row["finish_reasons"]}。')
        for change in differences:
            details.append(f'面板反例：{model} 第{change["stage"]+1}遍 {change["sample_id"]}，{change}。')
        resumed = read_json(output / model / 'resume.json')
        assert resumed['raw_unchanged'] and resumed['server_calls_unchanged']
    prepared_cache = metadata.get('prepared_media_cache')
    media_protocol = (f'四轮使用预先独立准备并核验输入哈希的帧缓存 `{prepared_cache}`；视频准备的重复性单独报告，上述墙钟不含预生成缓存。'
                      if prepared_cache else '每模型两轮关闭媒体缓存并重新解码；整池重启并轮换GPU后，再跑冷缓存和热缓存各一轮。')
    lines += ['', *details, '', media_protocol + ' 重复请求均重新推理，不缓存模型输出。',
        '服务重启后对旧输出目录执行相同infer命令，已完成记录被跳过，raw文件及服务请求计数不变。',
        '所有模型的同进程及重启比较均按实际输出逐个token、输入/输入token哈希、文本和结束原因核对；动态端点分配的换卡覆盖按表中实际数统计。',
        f'只验收这{count}道开发题；未跑全题库，不构成任意输入、软件版本或硬件上的保证。CVBench维持128输出token上限，截断单列，不改官方生成预算。',
        f'原始记录、服务日志、源码快照：`{output}`。',
        f'源码快照SHA256：`{sha256_file(output / "source.tar.gz")}`。']
    write_json(output / 'metrics.json', metrics)
    (output / 'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(responses=12*count, comparisons=9*count, differences=sum(len(r['differences']) for r in metrics),
        report_sha256=sha256_file(output / 'report.md'))), flush=True)


def run(output, panel_path=PANEL, prepared_media_cache=None):
    assert not (output / 'runs.json').exists()
    if prepared_media_cache is not None:
        assert prepared_media_cache.is_relative_to('/runs') and prepared_media_cache.is_dir()
    output.mkdir(parents=True, exist_ok=True)
    panel = read_json(panel_path)
    count = len(panel)
    assert count == len({r['name'] for r in panel}) and count >= 33
    prepared_inputs = None
    if prepared_media_cache is not None:
        prepared = read_json(prepared_media_cache / 'input_audit.json')
        prepared_inputs = prepared['input_sha256']
        assert prepared['independent_decode_comparisons'] == count and prepared['differences'] == 0
        assert set(prepared_inputs) == {r['name'] for r in panel}
    write_json(output / 'panel.json', panel)
    selection = output / 'selection'
    for name in ['cvbench', 'mvu_eval', 'crossvid']:
        write_json(selection / (name+'.json'), [r['name'] for r in panel if r['dataset'] == name])
    smoke = {'cvbench': ['cvbench:664'], 'mvu_eval': ['mvu_eval:ICL:713'], 'crossvid': ['crossvid:FSA:121']}
    for name, ids in smoke.items():
        write_json(output / 'smoke_selection' / (name+'.json'), ids)
    subprocess.run(['tar', '-czf', str(output / 'source.tar.gz'), '--exclude=__pycache__',
                    'src', 'eval', 'scripts', 'configs', 'requirements.txt', 'demo.py'], cwd=ROOT, check=True)
    write_json(output / 'manifest.json', dict(panel_sha256=digest(panel), engine_config=ENGINE_CONFIG,
        models=MODELS, case_count=count, planned_responses=12*count, planned_comparisons=9*count,
        prepared_media_cache=str(prepared_media_cache) if prepared_media_cache else None,
        prepared_input_audit_sha256=sha256_file(prepared_media_cache / 'input_audit.json') if prepared_media_cache else None,
        scoring_requested=False))
    runs, pool, pool_stream = [], None, None

    def stop_pool():
        nonlocal pool, pool_stream
        if pool is not None:
            if pool.poll() is None:
                pool.terminate()
                try:
                    pool.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(pool.pid, signal.SIGKILL)
                    pool.wait()
            pool_stream.close()
            pool, pool_stream = None, None

    def cli(model, phase, repeat, kind, target=None):
        destination = target or output / model / f'{phase}_{kind}{repeat}'
        ids = output / 'smoke_selection' if kind == 'smoke' else selection
        media_cache = str(prepared_media_cache) if prepared_media_cache else ('' if phase == 'p1' else str(output / 'media_cache'))
        if target:
            media_cache = ''
        command = [sys.executable, 'eval/e2e_eval/run.py', 'infer', '--output', str(destination),
            '--endpoints', '8100-8107', '--frames', '512', '--max-side', '448', '--retries', '1',
            '--media-cache-dir', media_cache]
        for name in ['cvbench', 'mvu_eval', 'crossvid']:
            command += ['--ids', f'{name}={ids / (name+".json")}']
        event(output, 'running_cli', model=model, phase_name=phase, repeat=repeat, kind=kind)
        started = time.monotonic()
        log_path = output / model / f'{phase}_{kind}{repeat}.log'
        with log_path.open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1500)
        rows = audit_run(destination)
        if prepared_inputs is not None:
            assert all(row['request']['input_sha256'] == prepared_inputs[sid] for sid, row in rows.items())
        row = dict(model=model, phase=phase, repeat=repeat, kind=kind, output=str(destination),
                   responses=0 if kind == 'resume' else len(rows), seconds=time.monotonic()-started)
        if kind == 'panel' and (phase, repeat) != ('p1', 0):
            row['differences'] = compare_rows(records(output / model / 'p1_panel0'), rows)
        runs.append(row)
        write_json(output / 'runs.json', runs)
        event(output, 'cli_finished', phase_name=phase, **{k: v for k, v in row.items() if k != 'phase'})
        return destination

    try:
        signal.signal(signal.SIGTERM, signal.default_int_handler)
        for model in MODELS:
            model_root = output / model
            model_root.mkdir()
            for phase, devices in [('p1', '0-7'), ('p2', '1-7,0')]:
                logs = model_root / (phase+'_servers')
                pool_stream = (model_root / (phase+'_pool.log')).open('w')
                pool = subprocess.Popen([sys.executable, 'eval/e2e_eval/serve.py', '--model', '/weights/Qwen3.5-'+model,
                    '--gpus', devices, '--port', '8100', '--log-dir', str(logs)], cwd=ROOT,
                    stdout=pool_stream, stderr=subprocess.STDOUT, start_new_session=True)
                event(output, 'loading', model=model, phase_name=phase, pid=pool.pid)
                endpoints = [f'http://127.0.0.1:{port}/v1' for port in range(8100, 8108)]
                ready = set()
                deadline = time.monotonic()+1200
                with httpx.Client(timeout=2, trust_env=False) as client:
                    while len(ready) < 8:
                        if pool.poll() is not None:
                            raise RuntimeError(f'{model} {phase}: pool exited; inspect {logs}')
                        if time.monotonic() > deadline:
                            raise TimeoutError('Eight HTTP replicas did not start within 20 minutes')
                        for endpoint in endpoints:
                            if endpoint in ready:
                                continue
                            try:
                                result = client.get(endpoint+'/models')
                                result.raise_for_status()
                                assert result.json()['data'][0]['id'] == '/weights/Qwen3.5-'+model
                                ready.add(endpoint)
                            except httpx.HTTPError:
                                pass
                        time.sleep(1)
                if phase == 'p1':
                    cli(model, phase, 0, 'smoke')
                else:
                    target = model_root / 'p1_panel0'
                    before = raw_hashes(target)
                    calls_before = sum(len(load_jsonl(p)) for p in logs.glob('*/requests.jsonl'))
                    cli(model, 'p1', 0, 'resume', target=target)
                    calls_after = sum(len(load_jsonl(p)) for p in logs.glob('*/requests.jsonl'))
                    resumed = dict(raw_unchanged=before == raw_hashes(target), server_calls_unchanged=calls_before == calls_after)
                    write_json(model_root / 'resume.json', resumed)
                    assert all(resumed.values())
                for repeat in range(2):
                    cli(model, phase, repeat, 'panel')
                    if phase == 'p1' and repeat == 0:
                        bridge_root = model_root / 'bridge_inputs'
                        bridge_root.mkdir()
                        cases = prepare_cases(bridge_root)
                        tag = {'9B': '9b', '27B': '27b', '35B-A3B': '35b'}[model]
                        previous = read_json(Path(f'/runs/devbox/tp_compare_{tag}_tp1_single_20261011/references.json'))
                        backend = VLLMBackend(endpoints, model=None, timeout=900, retries=1, enable_thinking=False)
                        bridge = []
                        for case in cases:
                            generation = {k: v for k, v in case['generation'].items() if k != 'seed'}
                            text, request = backend.complete(case['messages'], **generation)
                            delta = difference(previous[case['name']], dict(input_sha256=request['input_sha256'],
                                prompt_sha256=request['prompt_token_ids_sha256'], token_ids=request['token_ids']))
                            bridge.append(dict(case=case['name'], text=text, request=request,
                                               differences=delta if any(delta.values()) else {}))
                            write_json(model_root / 'bridge.json', bridge)
                        event(output, 'bridge_finished', model=model, responses=8,
                              differences=sum(bool(r['differences']) for r in bridge))
                stop_pool()
            event(output, 'model_finished', model=model)
        report(output)
        event(output, 'finished', models=3, responses=12*count)
    except BaseException as exc:
        event(output, 'failed', error=repr(exc))
        raise
    finally:
        stop_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--panel', type=Path, default=PANEL)
    parser.add_argument('--prepared-media-cache', type=Path, help='Existing independently audited frame cache; every response still runs inference')
    args = parser.parse_args()
    assert args.output.is_relative_to('/runs')
    run(args.output, args.panel, args.prepared_media_cache)
