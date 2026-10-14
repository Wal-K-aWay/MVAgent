#!/usr/bin/env python3
"""Repeat full MVU-Eval with the unchanged official instruction after the options.

Uses the previous run's frozen runtime, helpers, GPU shards and frame cache. Only
the experiment copy of the MVU adapter changes; the working checkout is untouched.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

BASE = Path('/runs/devbox/e2e_full_20261013_timeout')
OLD = {'9B': Path('/runs/devbox/e2e_full_20261012/9B'),
       '27B': BASE / '27B', '35B-A3B': BASE / '35B-A3B'}
ADAPTER = 'eval/e2e_eval/harness/mvu_eval.py'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def patch_adapter(source):
    replacements = [
        ('from .media import cached, image_sizes, source_identity',
         'from .media import cached, image_sizes, source_identity\n'
         'import os\nfrom pathlib import Path\nfrom models.vlm.local.sync_server import digest'),
        ('        self.frames = frames',
         '        self.original_inputs = read_json(Path(os.environ["MVU_ORIGINAL_INPUT_AUDIT"]))\n'
         '        self.frames = frames'),
        ('            "answer_instruction": OFFICIAL_INSTRUCTION,',
         '            "answer_instruction": OFFICIAL_INSTRUCTION,\n'
         '            "answer_instruction_position": "after options; original sentence unchanged",'),
        ('        messages = [{"role": "user", "content": content}]',
         '        original = digest(dict(messages=[{"role": "user", "content": content}],\n'
         '            generation={**self.generation, "seed": 0},\n'
         '            chat_template_kwargs={"enable_thinking": False}))\n'
         '        if original != self.original_inputs[item["sample_id"]]:\n'
         '            raise RuntimeError("Original input differs from the frozen baseline")\n'
         '        content.append(content.pop(instruction[0]))\n'
         '        messages = [{"role": "user", "content": content}]'),
        ('and the options.', 'and the options in the baseline; this experiment moves it after the options.'),
    ]
    for old, new in replacements:
        assert source.count(old) == 1, f'Unexpected frozen adapter: {old}'
        source = source.replace(old, new)
    compile(source, ADAPTER, 'exec')
    return source


def freeze(output):
    frozen = output / 'frozen_repo'
    if not frozen.exists():
        source = BASE / 'frozen_repo'
        temp = output / 'frozen_repo.tmp'
        if temp.exists():
            shutil.rmtree(temp)
        shutil.copytree(source, temp, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
        target = temp / ADAPTER
        target.write_text(patch_adapter(target.read_text()))
        shutil.copy2(__file__, temp / 'scripts' / Path(__file__).name)
        commit = subprocess.check_output(['git', '-C', str(Path(__file__).resolve().parents[1]),
            'rev-parse', 'HEAD'], text=True).strip()
        changed = []
        for path in source.rglob('*'):
            relative = path.relative_to(source)
            if path.is_file() and not set(relative.parts).intersection({'.git', '__pycache__', '.cache'}):
                if sha(path) != sha(temp / relative):
                    changed.append(str(relative))
        assert changed == [ADAPTER], changed
        write(output / 'source_provenance.json', dict(baseline=str(source), baseline_commit=read(BASE / 'manifest.json')['commit'],
            launcher_commit=commit, launcher_sha256=sha(Path(__file__)), changed_existing_files=changed,
            original_adapter_sha256=sha(source / ADAPTER), experiment_adapter_sha256=sha(target)))
        temp.rename(frozen)
    script = frozen / 'scripts' / Path(__file__).name
    if Path(__file__).resolve() != script.resolve():
        os.execv(sys.executable, [sys.executable, str(script), *sys.argv[1:]])
    return frozen


def prepare(output, runner):
    path = output / 'manifest.json'
    if path.exists():
        return read(path)
    info = read(BASE / 'manifest.json')
    ids = info['selection']['mvu_eval']
    assert len(ids) == len(set(ids)) == 1824
    audit = None
    for model, old in OLD.items():
        original = {sid: digest for sid, digest in read(old / 'input_audit.json')['input_sha256'].items() if sid in ids}
        assert set(original) == set(ids), model
        if audit is not None:
            assert original == audit, f'Baseline input hashes differ for {model}'
        audit = original
    write(output / 'original_input_sha256.json', audit)
    write(output / 'selection/mvu_eval.json', ids)
    selected = []
    for rank in range(8):
        shard = read(BASE / 'selection' / f'rank{rank}/mvu_eval.json')
        selected.extend(shard)
        write(output / 'selection' / f'rank{rank}/mvu_eval.json', shard)
        roots = list((BASE / 'media' / f'rank{rank}').glob('code-*'))
        assert len(roots) == 1, roots
        source = roots[0] / 'mvu_eval_frames'
        assert source.is_dir(), source
        target = output / 'media' / f'rank{rank}' / roots[0].name / 'mvu_eval_frames'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)
    assert len(selected) == len(set(selected)) == 1824 and set(selected) == set(ids)
    info.update(created_at=runner.now(), models=runner.MODELS, selection={'mvu_eval': ids},
        selection_counts={'mvu_eval': len(ids)}, unavailable=[], judge=None, split=None, split_sha256=None,
        source_provenance=read(output / 'source_provenance.json'), baseline_outputs={k: str(v) for k, v in OLD.items()},
        input_policy='Reuse fixed frame cache; verify original input hash before moving the original instruction; bind new hashes separately.',
        mvu_instruction_position='after options; original sentence unchanged')
    info['config'].update(benchmarks=['mvu_eval'], crossvid_tasks=[])
    sys.path.insert(0, str(runner.ROOT / 'eval/e2e_eval'))
    from run import source_hashes
    info['source'] = source_hashes()
    info['driver_sha256'] = sha(Path(__file__))
    write(path, info)
    return info


def compare(output, model):
    current = {r['sample_id']: r for r in read(output / model / 'scored/mvu_eval.json')}
    old = {r['sample_id']: r for r in read(OLD[model] / 'scored/mvu_eval.json')}
    assert current.keys() == old.keys() and len(current) == 1824
    result = {}
    for task in ['all', *sorted({r['task'] for r in current.values()})]:
        ids = [sid for sid, r in current.items() if task == 'all' or r['task'] == task]
        item = {'n': len(ids)}
        for key in ['score', 'robust_score', 'format_ok']:
            item[key] = dict(before=sum(old[sid][key] for sid in ids) / len(ids),
                after=sum(current[sid][key] for sid in ids) / len(ids),
                improved=sum(current[sid][key] > old[sid][key] for sid in ids),
                regressed=sum(current[sid][key] < old[sid][key] for sid in ids))
        result[task] = item
    write(output / 'comparison' / f'{model}.json', result)
    print(json.dumps({'model': model, 'comparison': result['all']}), flush=True)


def self_check(frozen):
    import ast
    import copy
    import re
    from types import SimpleNamespace
    from models.vlm.local.sync_server import digest
    tree = ast.parse((frozen / ADAPTER).read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'infer')
    instruction = read(BASE / 'manifest.json')['mvu_instruction']
    content = [{'type': 'text', 'text': text} for text in ['[Video 1] clip.mp4', 'question', instruction, 'A. one\nB. two']]
    original = copy.deepcopy(content)
    original[0]['text'] = 'Video 1:'
    generation = dict(max_tokens=8192, temperature=0.0, top_p=1.0)
    original_hash = digest(dict(messages=[{'role': 'user', 'content': original}],
        generation={**generation, 'seed': 0}, chat_template_kwargs={'enable_thinking': False}))
    def complete(messages, **kwargs):
        assert messages == [{'role': 'user', 'content': [*original[:2], original[3], original[2]]}]
        assert kwargs == generation
        return 'A', {}
    namespace = dict(re=re, digest=digest, OFFICIAL_INSTRUCTION=instruction,
        video_label=lambda k: f'Video {k}:', image_sizes=lambda messages: [(32, 32)])
    exec(compile(ast.Module(body=[method], type_ignores=[]), ADAPTER, 'exec'), namespace)
    obj = SimpleNamespace(frames=512, max_side=448, data_root=Path('/assets/mvu-eval'), generation=generation,
        original_inputs={'sample': original_hash},
        module=SimpleNamespace(build_messages_base=lambda *args: copy.deepcopy(content)))
    item = {'sample_id': 'sample', 'row': {'video_paths': ['clip.mp4']}}
    assert namespace['infer'](obj, item, SimpleNamespace(complete=complete))['output'] == 'A'
    obj.original_inputs['sample'] = 'incorrect'
    try:
        namespace['infer'](obj, item, SimpleNamespace(complete=complete))
    except RuntimeError as exc:
        assert 'Original input differs' in str(exc)
    else:
        raise AssertionError('Changed baseline inputs must be rejected')
    print('Instruction relocation and baseline input mismatch checks passed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.output
    assert output.is_relative_to('/runs')
    output.mkdir(parents=True, exist_ok=True)
    frozen = freeze(output)
    os.environ['MVU_ORIGINAL_INPUT_AUDIT'] = str(output / 'original_input_sha256.json')
    sys.path[:0] = [str(frozen / 'scripts'), str(frozen / 'src')]
    import run_full_e2e as runner
    runner.BENCHMARKS = ['mvu_eval']
    runner.MODELS = ['9B', '27B', '35B-A3B']
    info = prepare(output, runner)
    subprocess.run([sys.executable, '-m', 'compileall', '-q', 'src', 'scripts', 'eval/agent_eval', 'demo.py'], cwd=frozen, check=True)
    self_check(frozen)
    if args.prepare_only:
        print(json.dumps({'prepared': str(output), 'selection_counts': info['selection_counts'],
            'source_provenance': info['source_provenance']}), flush=True)
        return
    lock = (output / 'controller.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = dict(started_at=runner.now(), phase='preparing', models={}, selection_counts=info['selection_counts'],
                 target_responses_per_model=1824)
    try:
        inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
        assert len(inventory.splitlines()) == 8 and all('H100' in line for line in inventory.splitlines())
        (output / f'gpu_inventory_{time.time_ns()}.txt').write_text(inventory)
        for model in runner.MODELS:
            runner.infer_model(output, info, state, model)
            runner.merge(output, info, model)
            state.update(phase='scoring', model=model)
            runner.progress(output, state)
            subprocess.run([sys.executable, str(frozen / 'eval/e2e_eval/run.py'), 'score',
                            '--output', str(output / model)], cwd=frozen, check=True)
            summary = read(output / model / 'summary.json')
            assert not summary['failures'] and summary['mvu_eval']['complete'], summary['failures']
            state['models'][model]['scores'] = summary['mvu_eval']
            compare(output, model)
        state['phase'] = 'completed'
    except Exception as exc:
        state.update(phase='failed', last_error=repr(exc), traceback=traceback.format_exc())
        print(state['traceback'], flush=True)
    finally:
        state['finished_at'] = runner.now()
        runner.progress(output, state)
        (output / 'report.md').write_text('# MVU-Eval: official instruction after options\n\n```json\n' + json.dumps(state, indent=2) + '\n```\n')
        (Path('/work/jobs') / f'{output.name}.pid').unlink(missing_ok=True)
        os.utime('/work/heartbeat', (0, 0))
    if state['phase'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
