"""Small CPU contract checks for official prompts, input isolation and transport auditing."""
import copy
import json
import io
from pathlib import Path
import tempfile
from unittest.mock import patch

from agentcvr_eval import official_inputs, protocol_prompt
from agentcvr_worker import redact_images, prepare_request


def check_tool_error_transport():
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
    error = {'error': 'Missing observation_targets'}
    request = {'model': 'agentcvr-master', 'messages': [
        {'role': 'user', 'content': 'Inspect video 1.'},
        {'role': 'tool', 'content': [error]}], 'temperature': .5, 'max_tokens': 8192}
    original = copy.deepcopy(request)
    normalized = prepare_request(request)
    assert request == original
    content = normalized['messages'][-1]['content']
    assert content == [{'type': 'text', 'text': json.dumps(error, ensure_ascii=False)}]
    assert normalized['temperature'] == .5 and normalized['max_tokens'] == 8192
    validated = ChatCompletionRequest.model_validate(normalized)
    assert list(validated.messages[-1]['content'])[0]['type'] == 'text'
    valid = copy.deepcopy(normalized)
    assert prepare_request(valid) == valid


def check_recovery_preservation():
    import hashlib
    import agentcvr_eval as driver
    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / 'old', Path(directory) / 'new'
        items = [{'sample_id': sid, 'dataset': sid.split(':')[0]} for sid in
                 ['cvbench:1', 'mvu_eval:Counting:2', 'cvbench:3', 'mvu_eval:ICL:4']]
        for root in (source, target):
            driver.write(root / 'items.json', items)
            driver.write(root / 'assets_manifest.json', {'identity': 'same'})
            driver.write(root / 'private_labels.json', {})
            (root / 'agent_system.prompt').write_text('unchanged')
        driver.write(source / 'manifest.json', {'input_sha256': driver.sha256(source / 'items.json')})
        for index in (0, 2, 3):
            item = items[index]; sid = item['sample_id']; name = sid.replace(':', '_') + '.json'
            raw = source / 'raw' / name
            driver.write(raw, {'sample_id': sid, 'answer': 'A'})
            driver.write(source / 'records' / name, dict(sample_id=sid,
                status='infrastructure_error' if index == 3 else 'answered',
                input_sha256=hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest(),
                raw_sha256=driver.sha256(raw)))
        driver.inherit_results(target, source, items)
        assert {p.name for p in (target / 'records').glob('*.json')} == {'cvbench_3.json'}
        assert driver.read(target / 'smoke_ids.json') == [x['sample_id'] for x in (items[0], items[1], items[3])]
        assert driver.sha256(source / 'raw/cvbench_3.json') == driver.sha256(target / 'raw/cvbench_3.json')
        (source / 'raw/cvbench_3.json').write_text('corrupt')
        try:
            driver.inherit_results(target, source, items)
        except AssertionError:
            pass
        else:
            raise AssertionError('Recovery accepted a corrupt raw result')


def check_smoke_launch():
    import agentcvr_eval as driver
    class Process:
        def poll(self):
            return None
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        driver.write(output / 'items.json', [])
        driver.write(output / 'manifest.json', {'source_hashes': {},
                     'input_sha256': driver.sha256(output / 'items.json')})
        with patch.object(driver.subprocess, 'Popen', return_value=Process()), \
             patch.object(driver.subprocess, 'run') as launch, \
             patch.object(driver.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"data":[]}')), \
             patch.object(driver, 'summarize', return_value={}), patch.object(driver, 'stop'):
            driver.run(output, smoke_only=True)
        argv = launch.call_args.args[0]
        assert Path(argv[1]).name == 'agentcvr_worker.py', argv
        assert argv[-3:] == ['--rank', '0', '--smoke'], argv


def main():
    check_smoke_launch()
    check_tool_error_transport()
    check_recovery_preservation()
    items, labels = official_inputs()
    assert len(items) == 2821
    assert not any('answer' in x or 'ground_truth' in x or 'row' in x for x in items)
    yesno = [x for x in items if x['dataset'] == 'cvbench' and
             all(o.strip('.').lower() in ('yes', 'no') for o in labels[x['sample_id']]['row']['options'])]
    assert yesno and all("Answer with the option's word (YES or NO)" in x['query'] for x in yesno)
    instruction = 'Please select the correct answer from the options. Answer with the option’s letter directly.'
    for x in items:
        if x['dataset'] == 'mvu_eval':
            row = labels[x['sample_id']]['row']
            assert x['query'] == row['question']+'\n'+instruction+'\n'+'\n'.join(row['options'])
    protocol = protocol_prompt()
    assert 'MINIMUM 4 TOOL CALLS' in protocol and 'must contain only one uppercase letter' not in protocol
    assert 'culinary detail and process monitoring expert' not in protocol
    original = {'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,YQ=='}}]}
    saved = copy.deepcopy(original)
    cleaned = redact_images(original)
    assert original == saved and cleaned['content'][0]['image_url']['url']['encoded_bytes'] == 27
    assert 'YQ==' not in json.dumps(cleaned)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained('/weights/AgentCVR-8B-merged')
    messages = [{'role': 'user', 'content': 'Inspect video 1.'},
                {'role': 'assistant', 'content': '{"action":"observe"}'},
                {'role': 'tool', 'content': [{'type': 'text', 'text': 'Observed two objects.'}]}]
    before = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    messages[-1]['tool_call_id'] = 'observation_2'
    assert before == tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    print(json.dumps({'items': len(items), 'cv_yesno': len(yesno), 'official_prompts': 'passed',
                      'answer_isolation': 'passed', 'tool_call_id_token_equivalence': 'passed'}), flush=True)


if __name__ == '__main__':
    main()
