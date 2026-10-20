"""Check answer fidelity, inline media omission and archive integrity without inference."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from lenswalk_export import export_row, redact_media, read_trace, saved_prefix, encode, export_score, score_with_failures, source_metadata


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
        row = dict(sample_id='cvbench:0', task='choice', answer=None, seconds=12.5, terminal='empty_answer',
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
        partial = Path(directory)/'partial.jsonl'
        original = encode(output)
        partial.write_bytes(original+b'{"incomplete":')
        assert saved_prefix(partial, [row], {'cvbench:0': label}) == 1
        assert partial.read_bytes() == original
        wrong = dict(output, output='changed')
        partial.write_bytes(encode(wrong))
        try:
            saved_prefix(partial, [row], {'cvbench:0': label})
        except AssertionError:
            pass
        else:
            raise AssertionError('Changed saved answer was accepted')
        row['raw_archive']['sha256'] = 'corrupt'
        try:
            read_trace(row)
        except AssertionError:
            pass
        else:
            raise AssertionError('Corrupt source archive was accepted')


def test_rsi_trace():
    for status, answer in [('answered', 'A -> B\nOriginal answer.'),
                           ('invalid_decision', None), ('engineering_error', None)]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'attempt-1.tar'
            payload = {'question': 'Multi-video question'}
            if status == 'answered': payload = {'item': payload}
            result = dict(sample_id='crossvid:CCQA:1', status=status, answer=answer,
                          trace=[{'decision_attempts': [{'raw_response': 'Unmodified model response'}]}],
                          service_trace=[dict(service='deepseek', arguments={'messages': [
                              {'role': 'system', 'content': 'original system'},
                              {'role': 'user', 'content': json.dumps(payload)}]},
                              result={'text': 'data:image/jpeg;base64,YWJj'})])
            raw = json.dumps(result).encode()
            with tarfile.open(path, 'w') as archive:
                info = tarfile.TarInfo('attempt-1/result.json'); info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            row = dict(sample_id=result['sample_id'], task='CCQA', answer=answer or '', seconds=19.2,
                       terminal='finish' if status=='answered' else status,
                       infrastructure_error=status=='engineering_error', raw_archive=dict(path=str(path),
                       sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                       files={'result.json': hashlib.sha256(raw).hexdigest()}))
            label = dict(sample={'ground_truth': ['first point']}, reference_answer='reference')
            value = export_row(row, label)
            assert value['output'] == answer and value['gt'] == dict(answer='reference', scoring_points=['first point'])
            assert value['trajectory']['question'] == 'Multi-video question'
            assert value['trajectory']['steps'] == result['trace']
            assert 'YWJj' not in json.dumps(value)
            saved = Path(directory)/'results.jsonl'; saved.write_bytes(encode(value))
            assert saved_prefix(saved, [row], {row['sample_id']: label}) == 1


def test_partition_sources_and_failed_ccqa():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)/'merged';root.mkdir()
        ids=['crossvid:CCQA:1','crossvid:CCQA:2']
        labels={ids[0]:dict(sample={'ground_truth':['a','b','c']}),
                ids[1]:dict(sample={'ground_truth':['d']})}
        children=[]
        for i,sid in enumerate(ids):
            child=Path(directory)/f'part{i}';(child/'prepared').mkdir(parents=True)
            for name,value in [('manifest.json',{}),('samples.json',[sid]),
                               ('prepared/private_labels.json',labels),
                               ('expected_service.json',dict(execution={'profile':'qwen35-bf16-lenswalk-tools'}))]:
                (child/name).write_text(json.dumps(value))
            children.append(dict(root=str(child)))
        for name,value in [('manifest.json',dict(children=children)),('samples.json',ids),('summary.json',{})]:
            (root/name).write_text(json.dumps(value))
        found,paths,hashes=source_metadata(root,'lenswalk')
        assert found==labels and len(hashes)==11
        assert paths[ids[1]]==Path(children[1]['root'])/'judgements/crossvid_CCQA_2.json'
        rows=[dict(sample_id=ids[0],task='CCQA',answer='raw',score=.5,infrastructure_error=False),
              dict(sample_id=ids[1],task='CCQA',answer=None,score=None,infrastructure_error=True)]
        judge=dict(sample_id=ids[0],status='ok',prediction='raw',score=3,coverage=[1,1,0],
                   correctness=[1,0,0],response_model='judge')
        assert export_score(rows[0],labels[ids[0]],judge)['score']==.5
        failed=export_score(rows[1],labels[ids[1]],None)
        assert failed['status']=='infrastructure_error' and failed['score'] is None
        assert score_with_failures(rows,labels)==.375
        try:export_score(rows[0],labels[ids[0]],dict(judge,status='error'))
        except AssertionError:pass
        else:raise AssertionError('Judge error was accepted')
        (Path(children[1]['root'])/'samples.json').write_text(json.dumps([ids[0]]))
        try:source_metadata(root,'lenswalk')
        except AssertionError:pass
        else:raise AssertionError('Overlapping owners were accepted')


if __name__ == '__main__':
    test_saved_trace()
    test_rsi_trace()
    test_partition_sources_and_failed_ccqa()
    text = 'Keep the full answer, including repeated instructions.'
    assert redact_media(text) == text
    print('LensWalk and RSI export checks passed')
