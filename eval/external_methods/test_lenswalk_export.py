"""Check answer fidelity, inline media omission and archive integrity without inference."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from lenswalk_export import export_row, redact_media, read_trace


def test_saved_trace():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'attempt-1.tar.gz'
        call = dict(request={'messages': [{'content': 'data:image/jpeg;base64,YWJj'}]},
                    response={'text': 'A, because ...', 'token_ids': [4, 8, 15],
                              'usage': {'prompt_tokens': 12, 'completion_tokens': 3}}, error=None)
        data = {'result.json': json.dumps(dict(sample_id='cvbench:0', answer=None)).encode(),
                'all_conversations.jsonl': b'{"answer":null,"chat_history":[]}\n',
                'requests.jsonl': (json.dumps(call)+'\n{"interrupted":').encode(),
                'effective_config.json': b'{}'}
        with tarfile.open(path, 'w:gz') as archive:
            for name, value in data.items():
                info = tarfile.TarInfo('attempt-1/'+name); info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
        row = dict(sample_id='cvbench:0', task='choice', answer=None, seconds=12.5,
                   infrastructure_error=False, raw_archive=dict(path=str(path),
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   files={name: hashlib.sha256(value).hexdigest() for name, value in data.items()}))
        label = dict(sample={'ground_truth': ['B']})
        output = export_row(row, label)
        assert set(output) == {'id', 'gt', 'output', 'seconds', 'trajectory'}
        assert output['output'] is None and output['gt'] == ['B'] and output['seconds'] == 12.5
        calls = output['trajectory']['calls']
        assert calls[0]['input_tokens'] == 12 and calls[0]['output_tokens'] == 3
        assert 'request' not in calls[0] and 'response' not in calls[0]
        assert calls[1]['error'] == 'malformed_saved_jsonl'
        assert not any(s in json.dumps(output) for s in ('YWJj', 'token_ids'))
        redacted = redact_media('prefix data:image/jpeg;base64,YWJj suffix')
        assert hashlib.sha256(b'data:image/jpeg;base64,YWJj').hexdigest() in redacted
        assert redacted.startswith('prefix ') and redacted.endswith(' suffix')
        row['raw_archive']['sha256'] = 'corrupt'
        try:
            read_trace(row)
        except AssertionError:
            pass
        else:
            raise AssertionError('Corrupt source archive was accepted')


if __name__ == '__main__':
    test_saved_trace()
    text = 'Keep the full answer, including repeated instructions.'
    assert redact_media(text) == text
    print('LensWalk export checks passed')
