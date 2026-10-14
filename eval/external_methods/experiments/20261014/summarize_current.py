"""Summarize completed external-method smoke calls and timings without judging answers."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root/'frozen_repo/src'))
    from models.vlm.local.sync_server import token_audit
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
        assert progress['completed'] == progress['expected'] == 3, progress
        rows = []
        for row in progress['samples']:
            sample = directory/row['sample_id'].replace(':', '_')
            result_path = sample/'result.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            calls = prompt_tokens = output_tokens = cached_tokens = 0
            requests = sample/'requests.jsonl'
            if requests.exists():
                with requests.open() as stream:
                    for line in stream:
                        request = json.loads(line)
                        response = request['response']
                        wire = json.dumps(request['request'], ensure_ascii=False).encode()
                        token_audit(response, wire)
                        usage = response['usage']
                        calls += 1
                        prompt_tokens += usage['prompt_tokens']
                        output_tokens += usage['completion_tokens']
                        cached_tokens += usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
            rows.append(dict(**row, model_calls=calls, prompt_tokens=prompt_tokens,
                output_tokens=output_tokens, cached_tokens=cached_tokens,
                index_seconds=result.get('index_seconds'), query_seconds=result.get('query_seconds')))
        report['methods'][method] = dict(successful=progress['successful'], expected=3,
            batch_seconds=progress_path.stat().st_mtime-datetime.fromisoformat(progress['started_at']).timestamp(),
            samples=rows)
    (root/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
