"""Remote CPU self-check: retain actual IDs and reject missing/truncated audits."""
import copy
import hashlib

from models.vlm.api.client import ApiVLMError
from models.vlm.api.providers.openai_compatible import _token_audit_fields


def main():
    response = {'choices': [{'token_ids': [13, 99]}], 'prompt_token_ids': [4, 5],
                'usage': {'completion_tokens': 2}}
    audit = _token_audit_fields(response, b'exact request bytes')
    assert audit['token_ids'] == [13, 99]
    assert audit['request_sha256'] == hashlib.sha256(b'exact request bytes').hexdigest()
    assert audit['prompt_token_ids_sha256'] == hashlib.sha256(b'[4,5]').hexdigest()
    for kind in ['missing_output', 'missing_prompt', 'truncated', 'non_integer']:
        bad = copy.deepcopy(response)
        if kind == 'missing_output':
            bad['choices'][0].pop('token_ids')
        elif kind == 'missing_prompt':
            bad.pop('prompt_token_ids')
        elif kind == 'truncated':
            bad['usage']['completion_tokens'] = 3
        else:
            bad['choices'][0]['token_ids'][0] = True
        try:
            _token_audit_fields(bad, b'body')
        except ApiVLMError:
            pass
        else:
            raise AssertionError(kind)
    print('Token audit self-check passed: exact IDs/hashes and rejection of incomplete records')


if __name__ == '__main__':
    main()
