"""Three isolated frozen-source interventions on the retained OV/T/V panel."""
from __future__ import annotations
import argparse
from copy import deepcopy
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_action_parameter_validation as previous
from run_overnight_watch import read, save, sha
watch = previous.watch
REPO = previous.REPO
PARENT = REPO / 'outputs/analysis/20260922_action_parameter_validation'
ARMS = ['OV', 'T', 'V']
DEFAULT = REPO / 'outputs/analysis/20260922_evidence_contract_validation'

LOCAL_SCOPE = '''
## Scope of this individual observation
Only the supplied source interval is visible in this call. The evidence request may describe the full video or several intervals; answer only its part that is visible here. Describe the state and visible changes within this interval. "Beginning" and "end" below refer to this supplied interval unless the request explicitly identifies a source-video boundary. Do not refuse the visible part because another interval is absent, and do not invent that absent interval. Leave cross-interval ordering to the Planner that receives the separate observations.
'''

TIME_GROUNDING = '''
## Source-time check for this cropped observation
Every timestamp in text must be numeric seconds on the SOURCE video, never clip-local mm:ss. The first visible moment is {source_start_sec} source seconds; the last is {source_end_sec}. A visible event at clip-local 0 seconds is at source {source_start_sec}, not source 0. Convert any other clip-local t with source_time = {source_start_sec} + t. Before returning text, check that each reported visible event time falls inside [{source_start_sec}, {source_end_sec}]. If an action is already underway at the first visible moment, its onset is unknown before this interval; if it continues at the last visible moment, its end is unknown after this interval. State that limitation rather than claiming the crop boundary is the true action boundary. Do not infer exact boundaries from sparse frames.
'''


def patch_source(source, arm):
    """Only experimental copies change; assert the exact old edit site."""
    if arm == 'V':
        path = source / 'src/mvagent/agents/global_agent/agent.py'
        old = '            decision_skill=self.decision_skill,'
        new = ('            decision_skill=(self.decision_skill if '
               '(self.memory.reports or self.memory.watch_results) else ""),')
    else:
        path = source / 'src/mvagent/agents/video_agent/prompts.py'
        old = '    return with_text_limits(VISUAL_OBSERVATION_PROMPT_TEMPLATE).format('
        addition = LOCAL_SCOPE if arm == 'OV' else TIME_GROUNDING
        new = ('    template = VISUAL_OBSERVATION_PROMPT_TEMPLATE\n'
               '    if start_sec > 0.0 or end_sec < duration:\n'
               f'        template += {addition!r}\n'
               '    return with_text_limits(template).format(')
    before = path.read_text()
    if before.count(old) != 1:
        raise ValueError('Source edit anchor not unique: ' + str(path))
    after = before.replace(old, new)
    compile(after, str(path), 'exec')
    path.write_text(after)
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile=str(path.relative_to(source)), tofile=str(path.relative_to(source))))


def first_request(raw):
    return next(e for e in raw['events'] if e.get('kind') == 'structured_request' and e.get('agent') == 'GlobalAgent')


def prepare(root):
    import yaml
    if root.exists() and any(root.iterdir()):
        raise ValueError('Output must be new/empty')
    if read(PARENT/'status.json')['stage'] != 'completed':
        raise ValueError('Prior experiment is not completed')
    old = watch.verify(PARENT)
    root.mkdir(parents=True, exist_ok=True)
    for name in ['panel.json', 'questions.json', 'historical_baseline.json', 'media_identity.json', 'execution.yaml', 'B0.yaml']:
        shutil.copy2(PARENT/name, root/name)
    shutil.copytree(PARENT/'frozen', root/'frozen', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    protocol = deepcopy(old)
    protocol.update(arms=ARMS, total_rollouts=1800, n=len(set(s for a in ARMS for s in old['arm_ids'][a])),
        parent=str(PARENT), source_roots={a:f'variants/{a}' for a in ARMS},
        controller_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        arm_ids={a:old['arm_ids'][a] for a in ARMS}, skill_specs={a:old['skill_specs'][a] for a in ARMS},
        stages=[s for s in old['stages'] if s.split('_')[-1] in ARMS],
        scope='Same development panel and exact prior Skills; OV/T change cropped Observer wrapper only, V gates Skill until usable evidence. Runtime/Prompt diagnostics, not pure Skill improvement.',
        stopping='All three24-question preflights, then six100-question blocks per arm. Fixed1800 main, no outcome-based stopping or deployment.',
        primary='Paired vs retained corresponding OV/T/V; historical B0 safety comparison separately. Binary and FSA IoU separate; selected development panel only.')
    protocol['stage_ids'] = {s:old['stage_ids'][s] for s in protocol['stages']}
    controls = {}
    prior = read(PARENT/'comparison.json')['arms']
    for arm in ARMS:
        shutil.copy2(PARENT/f'{arm}.md', root/f'{arm}.md')
        cfg = yaml.safe_load((PARENT/f'{arm}.yaml').read_text())
        cfg['agents'][protocol['skill_specs'][arm]['role']]['skill']['path'] = str(root/f'{arm}.md')
        (root/f'{arm}.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
        source = root/protocol['source_roots'][arm]
        shutil.copytree(root/'frozen', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (root/f'{arm}.patch').write_text(patch_source(source, arm))
        controls[arm] = prior[arm]['rows']
        if set(controls[arm]) != set(protocol['arm_ids'][arm]):
            raise ValueError('Prior control coverage mismatch')
        for sid, row in controls[arm].items():
            raw = read(row['artifact'])
            if previous.score(raw) != row['score'] or raw['sample_id'] != sid:
                raise ValueError('Prior control score mismatch')
            protocol['historical_source_sha256'][row['artifact']] = sha(row['artifact'])
    save(root/'prior_controls.json', controls)
    for name in protocol['stage_ids'].values():
        (root/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PARENT/name, root/name)
    for name in ['run_evidence_contract_validation.py','run_action_parameter_validation.py',
                 'run_original_question_watch.py','run_overnight_watch.py']:
        shutil.copy2(REPO/'scripts/analysis'/name, root/name)
    protocol['immutable_sha256'] = {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
    save(root/'protocol.json', protocol)
    watch.verify(root)
    print('Prepared three arms: 1800 main + 72 preflight, same prior panel/Skills.', flush=True)


def preflight(root, arm, out):
    previous.preflight(root, arm, out)
    baseline = read(root/'historical_baseline.json')
    checked = []
    for path in (out/'records').glob('*/*/result.json'):
        raw = read(path)
        old = read(baseline[raw['sample_id']]['artifact'])
        a, b = first_request(raw), first_request(old)
        # Preserve the complete initial request, not just action name.
        for key in ['messages', 'json_schema']:
            if a.get(key) != b.get(key):
                raise RuntimeError(f'{arm} initial Global {key} changed for {raw["sample_id"]}')
        checked.append(raw['sample_id'])
    if len(checked) != 24:
        raise RuntimeError('Incomplete engineering preflight')
    save(root/f'preflight_{arm}_initial_request.json', dict(matched=checked, expected=24))


def summarize(root):
    previous.summarize(root)
    current = read(root/'comparison.json')['arms']
    controls = read(root/'prior_controls.json')
    meta = {r['sample_id']:r for r in read(root/'panel.json')['samples']}
    protocol = read(root/'protocol.json')
    results = {}
    lines = ['# Evidence contract follow-up', '', 'Direct paired comparison against retained corresponding OV/T/V. Historical B0 in report.md. Development panel; no population gain claim.', '',
             '|Arm/scope|Scored/planned|Prior|New|Delta pp|', '|---|---:|---:|---:|---:|']
    for arm in ARMS:
        scopes = {}
        for scope in ['target_binary','target_fsa','protection_binary','protection_fsa']:
            ids = [s for s in protocol['arm_ids'][arm] if
                   (meta[s]['scope']=='protection') == scope.startswith('protection') and
                   bool(meta[s]['is_fsa']) == scope.endswith('fsa')]
            if not ids: continue
            p = previous.paired(ids,controls[arm],current[arm]['rows'],meta)
            scopes[scope] = p
            fmt = lambda x: '—' if x is None else f'{x:.3f}'
            lines.append(f'|{arm}/{scope}|{p["scored"]}/{p["expected"]}|{fmt(p["baseline_mean"])}|{fmt(p["candidate_mean"])}|{fmt(p["delta_pp"])}|')
        results[arm] = scopes
    save(root/'direct_comparison.json', results)
    (root/'direct_report.md').write_text('\n'.join(lines)+'\n')


def launch(root):
    if not (root/'protocol.json').exists(): prepare(root)
    watch.verify(root)
    import psutil
    if (root/'process.json').exists():
        pid = read(root/'process.json')['pid']
        if psutil.pid_exists(pid) and str(root) in ' '.join(psutil.Process(pid).cmdline()):
            raise RuntimeError('Controller already active')
    with (root/'controller.log').open('ab') as log:
        p = subprocess.Popen([watch.PYTHON,str(root/'run_evidence_contract_validation.py'),'run','--output',str(root)],
                             cwd=REPO,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    save(root/'process.json',dict(pid=p.pid,launched_at=time.time()))
    print('launched',p.pid,root,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','launch','run','summarize'])
    parser.add_argument('--output',type=Path,default=DEFAULT)
    args=parser.parse_args();root=args.output.resolve()
    try:
        if args.mode=='run': watch.run(root,summarizer=summarize,preflight_handler=preflight)
        else: globals()[args.mode](root)
    except BaseException as exc:
        if args.mode=='run': save(root/'status.json',dict(stage='failed',error=str(exc),pid=os.getpid(),updated_at=time.time()))
        raise
