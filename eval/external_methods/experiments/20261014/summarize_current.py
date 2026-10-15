"""Summarize completed external-method smoke calls and timings without judging answers."""
import argparse
import json
from pathlib import Path
import sys


def main(root):
    sys.path[:0] = [str(root/'frozen_repo/src'), str(root/'frozen_repo/eval/external_methods')]
    from native_server import configure
    token_audit = configure().token_audit
    report = dict(methods={}, media=[])
    for item in json.loads((root/'prepared/items.json').read_text()):
        timeline = json.loads((Path(item['video_path']).parent/'timeline.json').read_text())
        report['media'].append(dict(sample_id=item['sample_id'], duration=item['duration'],
            segments=[{key: s[key] for key in ('video_id', 'start', 'end', 'processing', 'original_stream')}
                      for s in timeline['segments']]))
    for method in ('rsi', 'vam'):
        directory = root/method
        progress_path = directory/'progress.json'
        progress = json.loads(progress_path.read_text())
        assert progress['completed'] == progress['expected'], progress
        rows = []
        for row in progress['samples']:
            sample = directory/row['sample_id'].replace(':', '_')
            result_path = sample/'result.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            calls = prompt_tokens = output_tokens = cached_tokens = request_errors = 0
            call_seconds = []
            requests = sample/'requests.jsonl'
            if requests.exists():
                with requests.open() as stream:
                    for line in stream:
                        request = json.loads(line)
                        response = request['response']
                        if request.get('error') or not response or not response.get('choices'):
                            request_errors += 1
                            continue
                        # urllib and httpx serialize the same JSON differently.
                        wire = (json.dumps(request['request']).encode() if method == 'rsi' else
                                json.dumps(request['request'], ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
                        token_audit(response, wire)
                        usage = response['usage']
                        calls += 1
                        prompt_tokens += usage['prompt_tokens']
                        output_tokens += usage['completion_tokens']
                        cached_tokens += usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
                        if request.get('seconds') is not None:
                            call_seconds.append(request['seconds'])
            rows.append(dict(**row, model_calls=calls, prompt_tokens=prompt_tokens,
                output_tokens=output_tokens, cached_tokens=cached_tokens,
                model_http_seconds=sum(call_seconds) if len(call_seconds) == calls else None,
                agent_seconds=result.get('seconds'),
                index_seconds=result.get('index_seconds'), query_seconds=result.get('query_seconds'),
                request_errors=request_errors, provider_errors=result.get('usage', {}).get('provider_errors'),
                tool_errors=result.get('diagnostics', {}).get('tool_execution_errors')))
        report['methods'][method] = dict(successful=progress['successful'], expected=progress['expected'],
            batch_seconds=progress['batch_seconds'],
            samples=rows)
        score_path = directory/'scores.json'
        if score_path.exists():
            score = json.loads(score_path.read_text())
            report['methods'][method]['scoring'] = {k:v for k,v in score.items() if k not in ('rows','failed')}
    report['phase_timing'] = json.loads((root/'progress.json').read_text())
    (root/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
