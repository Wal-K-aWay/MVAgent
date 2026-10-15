#!/usr/bin/env python3
"""Isolated full-Agent panel, paired with saved independent-answerer trajectories."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
from statistics import mean
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'eval/e2e_eval')]
MODELS = {'9B': '9b', '27B': '27b', '35B-A3B': '35b_a3b'}
HISTORY = Path('/runs/devbox/pro6000_alignment_20261015/r2')


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def measure(text, record, scorer):
    from harness.answers import (option_labels, leads_with_choice, read_choice,
                                 read_letters, read_yes_no, read_order, read_interval)
    text = str(text or '').strip()
    labels = option_labels(record.sample.options)
    task = record.native_task
    if task == 'FSA' and record.dataset == 'crossvid':
        try:
            bounds = [float(x) for x in text.split(',')]
            valid = len(bounds) == 2 and all(math.isfinite(x) for x in bounds)
        except ValueError:
            valid = False
        parsed = text if valid else read_interval(text)
    elif task == 'PSS' and record.dataset == 'crossvid':
        valid = bool(re.fullmatch(r'\d+(?:->\d+)+', text))
        parsed = text if valid else read_order(text)
    elif task == 'BU' and record.dataset == 'crossvid':
        valid = bool(re.fullmatch(rf'[{re.escape(labels)}]+', text))
        parsed = read_letters(text, labels)
    else:
        valid = (bool(re.fullmatch(rf'[{re.escape(labels)}]', text)) if record.dataset == 'crossvid'
                 else leads_with_choice(text, labels))
        parsed = read_choice(text, labels)
        if record.dataset == 'cvbench':
            valid = valid or bool(re.match(r'(?i:yes|no)\b', text))
            parsed = parsed or read_yes_no(text)
    return dict(prediction=text, empty=not text, brace_only=text == '}', format_ok=valid,
                extractable=parsed is not None,
                score=scorer.score_prediction(record.sample_id, text).score,
                robust_score=scorer.score_prediction(record.sample_id, parsed or '').score)


def choose_random(records, ids):
    groups = defaultdict(list)
    for sid in sorted(ids):
        r = records[sid]
        groups[r.dataset, r.native_task].append(sid)
    rng = random.Random(0)
    return [rng.choice(groups[key]) for key in sorted(groups)]


def prepare(output):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    assert not (output/'selection.json').exists(), 'Never reselect a prepared panel'
    snapshots = {m: read(HISTORY/f'{m}_current_compact.json') for m in MODELS}
    def eligible(sid, row):
        return row['status'] == 'ok' and row['task'] != 'CCQA' and sid != 'crossvid:NC:506'
    available = {m: {s for s,r in rows.items() if eligible(s,r)} for m,rows in snapshots.items()}
    common = set.intersection(*available.values())
    records = load_multibench_records('/assets', sorted(set.union(*available.values())))
    scorer, identity = build_official_scorer(records, {})
    choice = next(r for r in records.values() if r.dataset == 'mvu_eval')
    assert not measure('}', choice, scorer)['format_ok']
    assert not measure('}', choice, scorer)['extractable']
    assert measure('', choice, scorer)['empty']
    assert measure('A', choice, scorer)['format_ok']
    assert not measure('Final answer: A', choice, scorer)['format_ok']
    assert measure('Final answer: A', choice, scorer)['extractable']
    random_ids = choose_random(records, common)
    assert random_ids == choose_random(records, common)
    assert len(random_ids) == len(set(random_ids)) == 32
    assert dict(Counter(records[s].dataset for s in random_ids)) == dict(cvbench=15, mvu_eval=8, crossvid=9)
    selection = dict(created_at=now(), seed=0, inference_seed=0, random_ids=random_ids,
        common_available=len(common), historical_snapshot=str(HISTORY), models={}, scorer=identity,
        exclusions=['CCQA (requires a separate Judge)', 'crossvid:NC:506 (ambiguous reference)'],
        design='One question per closed native task from the three-model completed intersection; '
               'separate diagnostics include every saved empty answer and up to two nonempty format failures per benchmark/model.')
    for model, rows in snapshots.items():
        rng = random.Random(0)
        reasons = defaultdict(list)
        for sid in sorted(available[model]):
            if not rows[sid]['prediction'].strip():
                reasons[sid].append('historical_empty')
        for ds in ['cvbench', 'mvu_eval', 'crossvid']:
            failures = [sid for sid in sorted(available[model]) if records[sid].dataset == ds
                        and rows[sid]['prediction'].strip()
                        and not measure(rows[sid]['prediction'], records[sid], scorer)['format_ok']]
            for sid in rng.sample(failures, min(2, len(failures))):
                reasons[sid].append('historical_format')
        ids = random_ids + sorted(set(reasons)-set(random_ids))
        manifest = []
        for sid in ids:
            source = Path(rows[sid]['source_path'])
            raw = source.read_bytes()
            saved = json.loads(raw)
            assert saved['sample_id'] == sid and saved['prediction'] == rows[sid]['prediction']
            assert any(e.get('schema') == 'global_answer' for e in saved['events']) or not saved['prediction']
            target = output/'historical'/model/(sid+'.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            metrics = measure(saved['prediction'], records[sid], scorer)
            assert abs(metrics['score']-float(saved['score'])) < 1e-8, (model, sid, metrics, saved['score'])
            manifest.append(dict(sample_id=sid, dataset=records[sid].dataset, task=records[sid].native_task,
                task_population=records[sid].task_population, random_panel=sid in random_ids,
                diagnostic_reasons=reasons.get(sid, []), source=str(source), sha256=sha(target), baseline=metrics))
        write(output/model/'samples.json', ids)
        selection['models'][model] = manifest
    write(output/'selection.json', selection)
    write(output/'progress.json', dict(phase='prepared', at=now(), counts={m:len(v) for m,v in selection['models'].items()}))
    shutil.copy2(__file__, output/'preparation_source.py')
    print(json.dumps(dict(phase='prepared', common=len(common), random=len(random_ids),
        models={m: dict(n=len(v), empty=sum(r['baseline']['empty'] for r in v),
                       format_errors=sum(not r['baseline']['format_ok'] for r in v))
                for m,v in selection['models'].items()})), flush=True)


def event_stats(row):
    events = row.get('events') or []
    responses = [e for e in events if e['kind'] == 'model_response']
    assert all(len(e['token_ids']) == e['usage']['completion_tokens'] and e['worker']['forward_calls'] > 0 for e in responses)
    return dict(status=row['status'], seconds=(row.get('result') or {}).get('time'), calls=len(responses),
        tokens=sum(len(e['token_ids']) for e in responses),
        model_errors=sum(e['kind']=='model_error' for e in events),
        structured_invalid=sum(e['kind']=='structured_invalid' for e in events),
        repairs=sum(e['kind']=='structured_repair' for e in events),
        truncations=sum(e['finish_reason']=='length' for e in responses))


def aggregate(rows):
    result = dict(n=len(rows))
    for arm in ['old', 'new']:
        result[arm] = {field:sum(r[arm][field] for r in rows) for field in
                      ['empty', 'brace_only', 'model_errors', 'structured_invalid', 'repairs', 'truncations', 'calls']}
        timings = [r[arm]['seconds'] for r in rows if r[arm]['seconds'] is not None]
        result[arm].update(format_errors=sum(not r[arm]['format_ok'] for r in rows),
            unextractable=sum(not r[arm]['extractable'] for r in rows),
            errors=sum(r[arm]['status'] != 'ok' for r in rows),
            mean_seconds=mean(timings) if timings else None)
        groups = defaultdict(list)
        for row in rows:
            groups[row['task']].append(row)
        for field in ['score', 'robust_score']:
            result[arm][field] = mean(r[arm][field] for r in rows)
            weights = {t: 1 if v[0]['dataset']=='crossvid' else v[0]['task_population'] for t,v in groups.items()}
            result[arm]['official_aggregate_'+field] = sum(mean(r[arm][field] for r in v)*weights[t] for t,v in groups.items())/sum(weights.values())
    result['improved'] = sum(r['new']['score'] > r['old']['score']+1e-8 for r in rows)
    result['regressed'] = sum(r['new']['score'] < r['old']['score']-1e-8 for r in rows)
    return result


def analyze_model(output, model):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    selected = read(output/'selection.json')['models'][model]
    records = load_multibench_records('/assets', [r['sample_id'] for r in selected])
    scorer, _ = build_official_scorer(records, {})
    rows = []
    for item in selected:
        sid = item['sample_id']
        oldpath = output/'historical'/model/(sid+'.json')
        assert sha(oldpath) == item['sha256']
        old = read(oldpath)
        path = output/model/'run/records'/item['dataset']/sid/'result.json'
        if not path.exists():
            continue
        new = read(path)
        assert old['sample_id'] == new['sample_id'] == sid
        assert not any(e.get('schema') == 'global_answer' for e in new.get('events',[]))
        for e in new.get('events', []):
            if e['kind'] == 'model_response':
                assert e['usage']['prompt_tokens_details']['cached_tokens'] == 0
        if new['status'] == 'ok':
            assert old['result']['input']['question'] == new['result']['input']['question'], sid
        measures = {arm: {**measure(raw['prediction'], records[sid], scorer), **event_stats(raw)}
                    for arm,raw in [('old',old),('new',new)]}
        for arm,raw in [('old',old),('new',new)]:
            if raw.get('score') is not None:
                assert abs(measures[arm]['score']-raw['score']) < 1e-8, (sid, arm)
        rows.append(dict(**{k:item[k] for k in ['sample_id','dataset','task','task_population','random_panel','diagnostic_reasons']},
                         **measures, new_path=str(path), old_path=str(oldpath)))
    report = dict(model=model, completed=len(rows), expected=len(selected), updated_at=now(), panels={})
    for panel in ['random', 'diagnostic']:
        group = [r for r in rows if r['random_panel']] if panel=='random' else [r for r in rows if r['diagnostic_reasons']]
        report['panels'][panel] = {ds:aggregate([r for r in group if r['dataset']==ds])
                                 for ds in sorted({r['dataset'] for r in group})}
    write(output/model/'paired.json', rows)
    write(output/model/'comparison.json', report)
    return report


def run(output):
    import yaml
    frozen = output/'frozen_repo'
    if ROOT != frozen.resolve():
        assert not frozen.exists(), 'Run an existing experiment from its frozen source'
        frozen.mkdir()
        for name in ['src','scripts','eval','configs','.git']:
            shutil.copytree(ROOT/name, frozen/name, ignore=shutil.ignore_patterns('__pycache__','.cache'))
        for name in ['requirements.txt','demo.py']:
            shutil.copy2(ROOT/name, frozen/name)
        (frozen/'prelaunch.py').write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"',repr(str(frozen/'src'))))
        os.execv(sys.executable,[sys.executable,str(frozen/'scripts'/Path(__file__).name),'run','--output',str(output)])
    from models.vlm.local.sync_server import execution_profile
    from verify_direct_answer import command
    selection = read(output/'selection.json')
    state = dict(phase='starting',started_at=now(),models={})
    manifest = dict(started_at=now(),selection_sha256=sha(output/'selection.json'), profile=execution_profile(),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={str(p.relative_to(ROOT)):sha(p) for folder in ['src','scripts','configs','eval/agent_eval']
                       for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.yaml','.sh']},
        hardware=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True),
        seeds=dict(inference=0,sampling=0), repeats=1, skills=None, historical_results_reused=True,
        judge=False, protocol='Full current direct-answer Agent; same-question historical independent answers; evidence may differ.')
    write(output/'manifest.json', manifest)
    try:
        for model,suffix in MODELS.items():
            target=output/model
            cfg=yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{suffix}_no_skill.yaml').read_text())
            exname='modal_h200x8.yaml' if model=='35B-A3B' else f'modal_h200x8_qwen35_{suffix}.yaml'
            ex=yaml.safe_load((ROOT/'configs/inference/execution'/exname).read_text())
            cfg['runtime']['cache_dir']=str(target/'runtime_cache')
            ex['media_cache']['root']=str(output/'media')
            name=next(iter(cfg['models']))
            assert len(ex['model_pools'][name]['replicas'])==8
            for filename,value in [('config.yaml',cfg),('execution.yaml',ex)]:
                (target/filename).write_text(yaml.safe_dump(value,sort_keys=False))
            state.update(phase='loading',model=model);write(output/'progress.json',state)
            command([sys.executable,ROOT/'prelaunch.py','--replace',target/'config.yaml',target/'execution.yaml',name],target/'startup.log')
            state.update(phase='inference');write(output/'progress.json',state)
            command([sys.executable,'eval/agent_eval/run.py','--config',target/'config.yaml',
                '--execution-config',target/'execution.yaml','--dataset-root','/assets',
                '--sample-ids-file',target/'samples.json','--output',target/'run','--defer-open-qa-judge'],target/'run.log')
            state['models'][model]=analyze_model(output,model)
            assert state['models'][model]['completed']==len(selection['models'][model])
            write(output/'progress.json',state)
            print(json.dumps(state['models'][model],ensure_ascii=False),flush=True)
        state.update(phase='completed',finished_at=now())
    except Exception as exc:
        import traceback
        state.update(phase='failed',error=repr(exc),traceback=traceback.format_exc())
        raise
    finally:
        write(output/'progress.json',state)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','run','analyze'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    assert out.is_relative_to(Path('/runs').resolve())
    out.mkdir(parents=True,exist_ok=True)
    if args.mode=='analyze':
        for model in MODELS:
            print(json.dumps(analyze_model(out,model)),flush=True)
    else:
        {'prepare':prepare,'run':run}[args.mode](out)


if __name__=='__main__':
    main()
