"""Small CPU contract checks for official prompts, input isolation and transport auditing."""
import copy
import json
from pathlib import Path

from agentcvr_eval import official_inputs, protocol_prompt
from agentcvr_worker import redact_images


def main():
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
