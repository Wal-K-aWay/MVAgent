"""Read-only CPU comparison of the author's released training text and CrossVid QA."""
import hashlib
import json
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import modal

DATASET_REVISION = '43cbd3bb7b9675202ee8a5cf966f8fff57282512'
DATASET_SHA256 = '1cf9422692eeeb392d38fc1066c08eeb7ff508ec29fbef6ff85d68317e5b2bba'
ROOT = '/runs/devbox/agentcvr_training_audit_20261017'
app = modal.App('wxu-evolve-agent-agentcvr-training-audit-20261017')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
assets = modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')
image = modal.Image.debian_slim(python_version='3.12').pip_install('pyarrow==21.0.0')


def norm(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def question(value):
    if isinstance(value, dict):
        return value.get('text', value.get('question', ''))
    if isinstance(value, str) and value.startswith('{'):
        try:
            return question(json.loads(value))
        except json.JSONDecodeError:
            pass
    return value or ''


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


@app.function(image=image, cpu=4, memory=16384, timeout=1200,
              volumes={'/runs': runs, '/assets': assets.with_mount_options(read_only=True)})
def audit():
    import pyarrow.parquet as pq

    assert norm('A—B!  Ｃ') == 'a b c'
    assert question('{"text":"Which?"}') == 'Which?'
    assert list(strings({'x': ['a', {'b': 'c'}]})) == ['a', 'c']
    root = Path(ROOT)
    root.mkdir(parents=True, exist_ok=True)
    data = root / 'crossvid_train.parquet'
    if not data.exists():
        url = ('https://huggingface.co/datasets/xiaohua616/crossvid_dataset/resolve/'
               + DATASET_REVISION + '/crossvid_train.parquet')
        with urllib.request.urlopen(url, timeout=120) as response, data.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    with data.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == DATASET_SHA256
    assert data.stat().st_size == 40359205
    training = pq.read_table(data).to_pylist()
    print('training rows', len(training), flush=True)
    selection_path = Path('/runs/devbox/e2e_full_20261012/9B/selection.json')
    lite = set(json.loads(selection_path.read_text())['crossvid'])
    assert len(lite) == 2500
    benchmark = []
    qa_hashes = {}
    for path in sorted(Path('/assets/crossvid/QA').glob('*.json')):
        if path.stem not in {'BU', 'CC', 'CCQA', 'FSA', 'MOC', 'MSR', 'NC', 'PEA', 'PI', 'PSS'}:
            continue
        qa_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in json.loads(path.read_text()):
            benchmark.append({'sample_id': f"crossvid:{path.stem}:{row['id']}", 'task': path.stem, 'row': row})
    assert len(benchmark) == 9015
    assert lite <= {b['sample_id'] for b in benchmark}
    q_index = defaultdict(list)
    for i, row in enumerate(training):
        q = question(row['extra_info']['original_question'])
        assert isinstance(q, str) and q.strip(), i
        q_index[norm(q)].append(i)
    exact, user_exact, missing, plot_matches = [], [], [], []
    user_index = defaultdict(list)
    plot_options = defaultdict(list)
    for i, row in enumerate(training):
        for message in row['prompt']:
            if message['role'] == 'user':
                user_index[norm(message['content'])].append(i)
                if row['data_source'] == 'crossvid_plot':
                    q = question(row['extra_info']['original_question'])
                    assert message['content'].startswith(q), i
                    plot_options[norm(message['content'][len(q):])].append(i)
    for b in benchmark:
        row = b['row']; q = question(row.get('question', ''))
        if not q:
            missing.append(b['sample_id'])
            if b['task'] == 'PI':
                matches = plot_options.get(norm('\n'.join(strings(row['options']))), [])
                if matches:
                    plot_matches.append({'sample_id': b['sample_id'], 'train_indices': matches})
            continue
        matches = q_index.get(norm(q), [])
        if matches:
            exact.append({'sample_id': b['sample_id'], 'lite2500': b['sample_id'] in lite,
                          'question': q, 'train_indices': matches})
        content = q + '\n' + '\n'.join(strings(row.get('options', [])))
        matches = user_index.get(norm(content), [])
        if matches:
            user_exact.append({'sample_id': b['sample_id'], 'lite2500': b['sample_id'] in lite,
                               'question': q, 'train_indices': matches})
    # Media identifiers are compared as exact string values, not generic numeric video labels.
    media = set()
    for b in benchmark:
        for key, value in b['row'].items():
            if key == 'vid' or any(word in key.lower() for word in ('video', 'path', 'frame')):
                media.update(s for s in strings(value) if len(s) >= 8)
    train_strings = set()
    script_examples = {}
    for row in training:
        videos = json.loads(row['extra_info']['videos'])
        train_strings.update(strings(videos))
        task = row['extra_info']['task_name']
        if task not in script_examples:
            script_examples[task] = {'question': question(row['extra_info']['original_question']),
                                     'script_excerpt': str(videos)[:1500]}
    result = {
        'verified_at': datetime.now(timezone.utc).isoformat(),
        'audit_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'dataset': 'xiaohua616/crossvid_dataset', 'revision': DATASET_REVISION,
        'sha256': DATASET_SHA256, 'bytes': data.stat().st_size,
        'training_rows': len(training), 'training_tasks': dict(Counter(r['data_source'] for r in training)),
        'training_prompt_roles': dict(Counter('/'.join(m['role'] for m in r['prompt']) for r in training)),
        'benchmark_rows': len(benchmark), 'lite2500_rows': len(lite),
        'missing_question_field': missing, 'question_matches': exact, 'question_options_matches': user_exact,
        'text_question_rows_checked': len(benchmark) - len(missing),
        'lite_text_question_rows_checked': len(lite - set(missing)),
        'PI_options_matches': plot_matches,
        'media_identifier_candidates': len(media), 'exact_media_value_matches': sorted(media & train_strings),
        'benchmark_schema': {b['task']: list(b['row']) for b in benchmark},
        'qa_sha256': qa_hashes, 'selection_sha256': hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        'script_examples': script_examples,
        'limits': 'Exact normalized text and media string comparison only. Generic question templates can match without sample leakage. No semantic paraphrase audit or proof that this file is the sole checkpoint training input.',
    }
    (root / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    runs.commit()
    return {k: v for k, v in result.items() if k not in {'script_examples', 'qa_sha256', 'question_matches', 'question_options_matches', 'missing_question_field'}} | {
        'missing_question_by_task': dict(Counter(s.split(':')[1] for s in missing)),
        'question_match_count': len(exact), 'question_options_match_count': len(user_exact),
        'lite_question_matches': sum(x['lite2500'] for x in exact),
        'lite_question_options_matches': sum(x['lite2500'] for x in user_exact),
        'examples': exact[:5], 'script_examples': script_examples,
    }


@app.local_entrypoint()
def main():
    print(json.dumps(audit.remote(), ensure_ascii=False, indent=2))
