"""Audit saved request timing and repetition on Modal CPU; never issue model requests."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys


def repetition(tokens):
    grams = Counter(tuple(tokens[i:i+8]) for i in range(max(0, len(tokens)-7)))
    blocks = Counter(tuple(tokens[i:i+32]) for i in range(max(0, len(tokens)-31)))
    return dict(repeated_8gram_fraction=1-len(grams)/sum(grams.values()) if grams else 0,
                most_common_32token_block_count=max(blocks.values(), default=0))


def stats(values):
    values = sorted(values)
    if not values:
        return dict(n=0)
    return dict(n=len(values), total=sum(values), mean=statistics.mean(values),
                median=statistics.median(values), p90=values[int((len(values)-1)*.9)],
                p95=values[int((len(values)-1)*.95)], maximum=values[-1])


def analyze(root):
    report = dict(at=datetime.now(timezone.utc).isoformat(), root=str(root), methods={})
    for method in ('rsi', 'vam'):
        rows, questions, duplicates = [], [], []
        progress = json.loads((root/method/'progress.json').read_text())
        for sample in progress['samples']:
            folder = root/method/sample['sample_id'].replace(':', '_')
            result_path = folder/'result.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            actions = Counter(json.dumps(t['decision'], sort_keys=True) for t in result.get('trace', [])
                              if t.get('decision', {}).get('type') == 'tool')
            observations = Counter(t.get('observation', {}).get('perception', {}).get('status', 'unspecified')
                                   for t in result.get('trace', []) if isinstance(t.get('observation'), dict))
            questions.append(dict(sample=sample['sample_id'], seconds=sample['seconds'],
                answer=sample.get('answer'), success=sample['success'], steps=len(result.get('trace', [])),
                repeated_actions=[dict(action=json.loads(a),count=n) for a,n in actions.items() if n>1],
                observation_statuses=dict(observations), diagnostics=result.get('diagnostics'),
                index_seconds=result.get('index_seconds'), query_seconds=result.get('query_seconds')))
            fingerprints = Counter()
            path = folder/'requests.jsonl'
            if not path.exists():
                continue
            with path.open() as stream:
                for index, line in enumerate(stream):
                    raw = json.loads(line)
                    request, response = raw['request'], raw.get('response') or {}
                    fingerprints[raw['request_sha256']] += 1
                    choices = response.get('choices') or [{}]
                    choice, usage = choices[0], response.get('usage', {})
                    text = choice.get('message', {}).get('content') or ''
                    tokens = choice.get('token_ids', [])
                    repeated = repetition(tokens)
                    sentences = Counter(s.strip() for s in re.split(r'(?<=[.!?。！？])\s+|\n+', text)
                                        if len(s.strip()) >= 30)
                    sentence, count = sentences.most_common(1)[0] if sentences else ('',0)
                    kinds = Counter(c.get('type') for msg in request.get('messages', [])
                                    if isinstance(msg.get('content'), list) for c in msg['content'])
                    inference = response.get('audit', {}).get('inference_seconds')
                    row = dict(sample=sample['sample_id'], call=index, request_sha256=raw['request_sha256'],
                        seconds=raw.get('seconds'), inference_seconds=inference,
                        input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens',0),
                        max_tokens=request.get('max_tokens'), finish_reason=choice.get('finish_reason'),
                        error=raw.get('error'), http_status=raw.get('http_status'),
                        kind='visual' if kinds.get('image_url') or kinds.get('video_url') else 'text',
                        images=kinds.get('image_url',0), videos=kinds.get('video_url',0),
                        output_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        repeated_sentence_count=count, repeated_sentence=sentence[:240],
                        first_text=text[:350], last_text=text[-350:], **repeated)
                    row['strong_repetition_flag'] = (len(tokens)>=1024 and
                        repeated['repeated_8gram_fraction']>=.6 and repeated['most_common_32token_block_count']>=5)
                    rows.append(row)
            duplicates += [dict(sample=sample['sample_id'], request_sha256=h, count=n)
                           for h,n in fingerprints.items() if n>1]
        good = [r for r in rows if r['inference_seconds'] is not None]
        capped = [r for r in good if r['finish_reason']=='length']
        repeated = [r for r in good if r['strong_repetition_flag']]
        long = [r for r in good if r['output_tokens']>=1000]
        groups = {}
        for name, group in [('all',good),('text',[r for r in good if r['kind']=='text']),
                            ('visual',[r for r in good if r['kind']=='visual']),('length',capped),
                            ('strong_repetition',repeated),('output_1000_plus',long)]:
            sec = sum(r['inference_seconds'] for r in group)
            groups[name] = dict(http_seconds=stats([r['seconds'] for r in group]),
                inference_seconds=stats([r['inference_seconds'] for r in group]),
                output_tokens=stats([r['output_tokens'] for r in group]),
                output_tokens_per_inference_second=sum(r['output_tokens'] for r in group)/sec if sec else None)
        thresholds = {str(t):dict(calls=sum(r['seconds']>t for r in good),
            questions=sorted({r['sample'] for r in good if r['seconds']>t}),
            beyond_threshold_seconds=sum(max(0,r['seconds']-t) for r in good))
            for t in (240,360,480,600,900,1860)}
        report['methods'][method] = dict(expected=progress['expected'], successful=progress['successful'],
            failed=progress['failed'], batch_seconds=progress['batch_seconds'],
            question_seconds=stats([q['seconds'] for q in questions]),
            http_errors=[r for r in rows if r['error'] or (r['http_status'] or 200)>=400],
            groups=groups, threshold_counterfactual=thresholds, duplicate_requests=duplicates,
            questions=questions, calls=rows)
    output = root/'latency_audit_20261015'
    output.mkdir(exist_ok=True)
    (output/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for method, data in report['methods'].items():
        compact = {k:v for k,v in data.items() if k not in ('calls','questions')}
        print(method,json.dumps(compact,ensure_ascii=False,indent=2))


def refine(root):
    """Replay the original visual-response parser and audit exact duplicate requests."""
    output = root/'latency_audit_20261015'
    report = json.loads((output/'analysis.json').read_text())
    sys.path.insert(0,str(root/'frozen_repo/external_sources/Video-RSI/artifacts/final_harness'))
    from tools import _bound_visual_response
    visual, repeats = [], {}
    for q in report['methods']['rsi']['questions']:
        result = json.loads((root/'rsi'/q['sample'].replace(':','_')/'result.json').read_text())
        frames = {}
        for entry in result['service_trace']:
            if entry['service']=='sample_frames' and isinstance(entry.get('result'),list):
                frames.update({f['id']:f for f in entry['result']})
            if (entry['service']!='qwen' or 'result' not in entry or
                    '"observations"' not in entry['arguments'].get('prompt','')):
                continue
            parsed = _bound_visual_response(entry['result'], [frames[f] for f in entry['arguments']['frames']])
            digest = hashlib.sha256(entry['result'].get('text','').encode()).hexdigest()
            matches = [r for r in report['methods']['rsi']['calls']
                       if r['sample']==q['sample'] and r['kind']=='visual' and r['output_sha256']==digest]
            assert matches, (q['sample'],digest)
            for r in matches:
                key=(r['sample'],r['call'])
                if not any((x['sample'],x['call'])==key for x in visual):
                    visual.append(dict(sample=r['sample'],call=r['call'],status=parsed['status'],
                        seconds=r['inference_seconds'],finish_reason=r['finish_reason'],tokens=r['output_tokens']))
    for method, data in report['methods'].items():
        repeats[method]=[]
        for duplicate in data['duplicate_requests']:
            calls = [r for r in data['calls'] if r['sample']==duplicate['sample'] and
                     r['request_sha256']==duplicate['request_sha256']]
            repeats[method].append(dict(**duplicate, calls=[r['call'] for r in calls],
                output_variants=len({r['output_sha256'] for r in calls}),
                total_model_seconds=sum(r['inference_seconds'] for r in calls),
                repeat_model_seconds=sum(r['inference_seconds'] for r in calls[1:])))
    summary = dict(analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        visual_parser_counts=dict(Counter(r['status'] for r in visual)),
        capped_visual=[r for r in visual if r['finish_reason']=='length'],
        unusable_visual_model_seconds=sum(r['seconds'] for r in visual if r['status']!='grounded'),
        duplicated_requests=repeats,
        limitation='Historical counterfactuals are not reruns or measured speedups. Repetition flags are heuristic; exact duplicate outputs are checked separately.')
    (output/'evidence.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (output/'analyze_latency.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    assert repetition([])['repeated_8gram_fraction']==0
    assert repetition(list(range(100)))['repeated_8gram_fraction']==0
    assert repetition(list(range(32))*50)['most_common_32token_block_count']==50
    analyze(Path(sys.argv[1]))
    refine(Path(sys.argv[1]))
