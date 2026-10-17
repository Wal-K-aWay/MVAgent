#!/usr/bin/env python3
"""Read the frozen pilot's raw records and save a post-run answer audit on /runs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(Path('/runs').resolve())
    frozen = output/'frozen_repo'
    sys.path[:0] = [str(frozen/'scripts'), str(frozen/'src')]
    from check_mvagent_runtime import analyze, records
    samples = json.loads((output/'samples.json').read_text())
    first, second = records(output/'repeat0'), records(output/'repeat1')
    assert set(first) == set(second) == set(samples)
    reliability = analyze(first, second, samples=samples)
    recorded = json.loads((output/'reliability.json').read_text())
    assert reliability == recorded, 'Raw records no longer agree with the saved repeatability report'
    invalid = {r['sample_id'] for r in reliability['answers'] if not r['format_syntax_valid']}
    details, timing, capped_reasons = [], [], []
    for sid in samples:
        row = first[sid]
        calls = [e for e in row['events'] if e['kind'] == 'model_response']
        finals = [e for e in calls if e.get('schema') == 'global_answer']
        answer = row['result'].get('answer', {})
        if finals and len(json.loads(finals[-1]['text']).get('reason', '')) == 1200:
            capped_reasons.append(sid)
        if sid in invalid or not row['prediction'].strip():
            last = finals[-1] if finals else {}
            raw = json.loads(last['text']) if last else {}
            details.append(dict(sample_id=sid, prediction=row['prediction'],
                reason=answer.get('reason'), raw_reason_chars=len(raw.get('reason', '')),
                final_tokens=last.get('usage', {}).get('completion_tokens'),
                finish_reason=last.get('finish_reason'), score=row.get('score'),
                reference=row.get('ground_truth'), question=row.get('judge_question'),
                input=row['result'].get('input'), actions=row['result'].get('action_history'),
                call_count=len(calls), final_raw=last.get('text')))
    for repeat in [0, 1]:
        directory = output/f'repeat{repeat}'
        events = [json.loads(line) for line in (directory/'execution_events.jsonl').read_text().splitlines()]
        start = min(e['time'] for e in events if e['kind'] == 'question_start')
        end = max(e['time'] for e in events if e['kind'] == 'question_done')
        kinds = Counter(e['kind'] for e in events)
        timing.append(dict(repeat=repeat, seconds=end-start, trajectories_per_minute=len(samples)*60/(end-start),
            retries=sum(e['kind']=='question_start' and e.get('attempt', 0)>0 for e in events),
            question_errors=kinds['question_error'], calls=kinds['model_response']))
    summary_path = output/'repeat0/summary_scored.json'
    summary = json.loads((summary_path if summary_path.exists() else output/'repeat0/summary.json').read_text())
    report = dict(samples=len(samples), nonempty_answers=sum(bool(r['prediction'].strip()) for r in first.values()),
        format_syntax_valid=len(samples)-len(invalid), bad_cases=details, timing=timing,
        final_reasons_at_1200_chars=capped_reasons,
        scoring_errors=[sid for sid,r in first.items() if r.get('scoring_error')],
        scores=summary, reliability={k:v for k,v in reliability.items() if k != 'answers'})
    analysis = output/'analysis'
    analysis.mkdir(exist_ok=True)
    shutil.copyfile(__file__, analysis/'source.py')
    (analysis/'answer_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['bad_cases','scores']}, ensure_ascii=False))
    print('SCORES', json.dumps({ds:{k:v for k,v in data.items() if k in
        ['expected','completed','errors','official_score','official_task_macro','accuracy','by_task']}
        for ds,data in summary['datasets'].items()}, ensure_ascii=False))
    print('BAD_CASES',json.dumps([{k:v for k,v in r.items() if k not in ['actions','input','final_raw']}
                                for r in details],ensure_ascii=False))
    print('FINALIZE_LOG', (output/'finalize.log').read_text()[-5000:])
    print('SCORE_LOG', (output/'score.log').read_text()[-1500:])
    print('ANSWERS',json.dumps([(sid,r['prediction']) for sid,r in first.items()],ensure_ascii=False))
    for case in details:
        print('ACTIONS',case['sample_id'],json.dumps(case['actions'],ensure_ascii=False)[:6500])


if __name__ == '__main__':
    main()
