"""Frozen, labeled text-only Skill selection checks. Never execute Agent actions."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import yaml
from selector_methods import METHODS, invoke

ROOT = Path(os.environ.get('MVAGENT_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src' if (Path(__file__).resolve().parent / 'src').is_dir() else ROOT / 'src'))
from skill_evolution.infra.store import write_json, file_fingerprint, tree_hash


def prepare(out, cases=None, learned_bank=None):
    from mvagent.utils.snapshot import ensure_source_snapshot
    from mvagent.skills.bank import _resolve_skill_path
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(cases or ROOT / 'tests/fixtures/skill_selector_cases.json', out / 'cases.json')
    shutil.copyfile(ROOT / 'configs/skill_evolution/runtime/dynamic_35b_embedding.yaml', out / 'runtime.yaml')
    shutil.copyfile(ROOT / 'configs/inference/execution/gpu2_7_single.yaml', out / 'execution.yaml')
    cfg = yaml.safe_load((out / 'runtime.yaml').read_text())
    shutil.copyfile(_resolve_skill_path(cfg['agents']['global_agent']['skill']['path']), out / 'authored.json')
    if learned_bank is None:
        raise ValueError('prepare requires --learned-bank pointing to a schema_version3 bank')
    from mvagent.skills.bank import SkillBank
    SkillBank.from_dict(json.loads(Path(learned_bank).read_text()))
    shutil.copyfile(learned_bank, out / 'learned.json')
    ensure_source_snapshot(out)
    shutil.copyfile(__file__, out / 'controller.py')
    shutil.copyfile(Path(__file__).with_name('selector_methods.py'), out / 'selector_methods.py')
    names = ['cases.json', 'runtime.yaml', 'execution.yaml', 'authored.json', 'learned.json', 'controller.py', 'selector_methods.py']
    write_json(out / 'manifest.json', dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_hash=tree_hash(out / 'src'), hashes={n:file_fingerprint(out/n) for n in names},
        labels=json.loads((out / 'cases.json').read_text())['protocol']))


def summarize(out, partition, mode, repeat, method='current'):
    target = out / f'{partition}_{mode}_{repeat}' / method
    jobs = {c['case_id']:c for c in json.loads((out / 'cases.json').read_text())['cases'] if c['partition'] == partition}
    counts = {}; details = []
    for p in sorted((target / 'results').glob('*.json')):
        r = json.loads(p.read_text()); c = jobs[r['case_id']]
        selected = r.get('selected', [])
        value = selected[0] if len(selected) == 1 else None
        ok = r['status'] == 'ok' and len(selected) <= 1
        match = ok and value in c['expected']
        row = dict(case_id=c['case_id'], role=c['role'], origin=c['origin'], ambiguous=c['ambiguous'],
                   expected=c['expected'], selected=selected, status=r['status'], match=match,
                   recalled=r.get('recalled', []))
        details.append(row)
        if c['ambiguous']:continue
        for group in ('all', c['role'], c['origin'], c['bank']):
            n = counts.setdefault(group, Counter()); n['n']+=1; n['correct']+=match; n['invalid']+=not ok
            positive = c['expected'] != [None]
            n['positive']+=positive; n['negative']+=not positive
            n['false_selection']+=bool(selected) and not positive
            n['false_abstention']+=not selected and positive and ok
            n['wrong_card']+=bool(selected) and positive and not match and ok
            n['recalled_positive']+=positive and any(s in r.get('recalled', []) for s in c['expected'])
    write_json(target / 'summary.json', dict(counts=counts, details=details,
        limits='Applicability agreement on development contexts; not end-to-end accuracy or human-independent gold.'))
    print(json.dumps(counts, ensure_ascii=False), flush=True)


def run(out, partition, mode, repeat, method='current'):
    import fcntl
    from models.pool import install_pools
    from models.factory import ModelFactory
    from models.execution import execution_scope
    from mvagent.configs import MVAgentConfig
    from mvagent.batch import BatchExecutor, ExecutionConfig
    from mvagent.engine import MVAgentEngine
    from mvagent.skills.selection import select_skills

    target = out / f'{partition}_{mode}_{repeat}' / method; target.mkdir(parents=True, exist_ok=True)
    lock = (out / 'run.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert tree_hash(out / 'src') == manifest['source_hash'], 'Frozen source changed'
    assert all(file_fingerprint(out/n)==h for n,h in manifest['hashes'].items()), 'Frozen input changed'
    cfg = MVAgentConfig.from_yaml(out / 'runtime.yaml')
    for settings in (cfg.global_agent.skill, cfg.video_agent.skill):
        if settings.selection_scope != 'task' or settings.selector != cfg.global_agent.model:
            raise ValueError('This audit requires task scope and the shared 35B selector profile')
    jobs = [c for c in json.loads((out / 'cases.json').read_text())['cases'] if c['partition']==partition]
    banks = {}
    for name in ('authored','learned'):
        settings = replace(cfg.global_agent.skill, path=str(out / (name+'.json')), sha256=file_fingerprint(out/(name+'.json')))
        b = MVAgentEngine._load_configured_skill(settings)
        banks[name] = b
    events = []; batch = BatchExecutor(ExecutionConfig.from_yaml(out / 'execution.yaml'), on_event=events.append)
    clients = []; local = threading.local(); started = time.time()
    try:
        batch.prepare(cfg.to_dict()); write_json(target / 'pool.json', events)
        prepared = next(e for e in events if e['kind']=='batch_prepared')
        if prepared['question_workers']!=6 or prepared['unavailable']:raise RuntimeError('Six healthy Actor replicas required')
        install_pools(batch.pools)
        def work(c):
            path = target / 'results' / (c['case_id']+'.json')
            if path.exists():return json.loads(path.read_text())['status']
            if not hasattr(local,'model'):
                local.model=ModelFactory.create_model(cfg.global_agent.model,cfg);clients.append(local.model)
            recorded=[]
            def decide(prompt, **kw):
                return invoke(local.model, prompt, bank=banks[c['bank']], method=method, **kw)
            begin=time.time()
            try:
                with execution_scope(emit=recorded.append,deadline=time.monotonic()+240):
                    result=select_skills(banks[c['bank']],role=c['role'],task=c['task'],state={k:v for k,v in c['state'].items()
                            if k in (('history','videos') if c['role']=='global' else ('history',))},
                        has_evidence=c['has_evidence'],decide=decide,selection_cache={})
                selection=next((e for e in reversed(recorded) if e['kind']=='skill_selection'),{})
                retrieval=next((e for e in recorded if e['kind']=='skill_retrieval'),{})
                row=dict(status=result['status'],selected=[v['id'] for v in selection.get('selected',[])],
                    selection=selection,recalled=[v['id'] for v in retrieval.get('candidates',[])])
            except Exception as exc:row=dict(status='error',error=str(exc),selected=[])
            write_json(path,dict(case_id=c['case_id'],seconds=time.time()-begin,events=recorded,**row));return row['status']
        counts=Counter()
        with ThreadPoolExecutor(max_workers=6) as executor:
            for future in as_completed([executor.submit(work,c) for c in jobs]):
                counts[future.result()]+=1
                write_json(target/'status.json',dict(stage='running',completed=sum(counts.values()),target=len(jobs),counts=counts))
        summarize(out,partition,mode,repeat,method)
        write_json(target/'status.json',dict(stage='completed',completed=len(jobs),counts=counts,seconds=time.time()-started))
    finally:
        for c in clients:c.close()
        batch.close();lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run','summarize'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--partition',choices=['dev','confirm'],default='dev')
    p.add_argument('--mode',choices=['hybrid'],default='hybrid');p.add_argument('--repeat',type=int,default=0)
    p.add_argument('--method', choices=METHODS, default='current')
    p.add_argument('--cases', type=Path, help='Pre-labeled panel for prepare only')
    p.add_argument('--learned-bank',type=Path,help='Schema3 bank required for prepare')
    a=p.parse_args();a.output=a.output.resolve()
    if a.command != 'prepare' and a.cases is not None:
        p.error('--cases is only accepted by prepare; run uses frozen cases')
    if a.command=='prepare':prepare(a.output,a.cases,a.learned_bank)
    elif a.command=='run':run(a.output,a.partition,a.mode,a.repeat,a.method)
    else:summarize(a.output,a.partition,a.mode,a.repeat,a.method)
