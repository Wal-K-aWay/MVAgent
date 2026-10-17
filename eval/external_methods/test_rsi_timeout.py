"""Check the actual upstream transport receives only the approved timeout override."""
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import rsi


def main():
    source = Path(sys.argv[1])
    sys.path.insert(0, str(source))
    from solver_full_workspace.engine import runner
    original = json.loads((source/'config.example.json').read_text())
    timeouts = []

    def urlopen(request, timeout):
        if isinstance(request, str):
            value = {'data':[{'id':'local'}]}
        else:
            payload = json.loads(request.data)
            assert payload['max_tokens'] == 8192 and payload['temperature'] == 0
            timeouts.append(timeout)
            value = {'choices':[{'message':{'content':'ok'}}]}
        response = io.BytesIO(json.dumps(value).encode())
        response.status = 200
        return response

    def run_item(harness, item, services, config, check_only):
        assert config['solver'] == original['solver']
        assert config['services']['provider_retries'] == original['services']['provider_retries']
        for role in ('deepseek','qwen'):
            services.provider.chat(role, [{'role':'user','content':'probe'}])
        return {'status':'answered','answer':'A'}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root/'item.json').write_text(json.dumps({'video_path':'unused'}))
        args = ['rsi.py','--source',str(source),'--item',str(root/'item.json'),
                '--output',str(root/'output'),'--endpoint','http://local/v1']
        with patch.object(sys,'argv',args), patch.object(rsi,'validate_card'), \
             patch.object(runner,'run_item',run_item), patch('urllib.request.urlopen',urlopen):
            rsi.main()
        config = json.loads((root/'output/effective_config.json').read_text())['config']
        assert config['services']['timeout_seconds'] == 600
    assert timeouts == [600,600]
    print('Upstream HTTP timeout and generation settings checks passed')


if __name__ == '__main__':
    main()
