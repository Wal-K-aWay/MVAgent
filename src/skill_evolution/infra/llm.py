"""Persist API evidence before validation; completed calls can be replayed on resume."""
from pathlib import Path
import json,time
from models.execution import execution_scope
from models.utils import validate_json_schema
from mvagent.utils.io import write_json


def call_json(client, messages, schema, directory, name):
    directory = Path(directory)
    request = {'messages': messages, 'schema': schema}
    request_path, response_path = directory / 'request.json', directory / 'response.json'
    secret = client.api_key
    if request_path.exists():
        if json.loads(request_path.read_text()) != request:
            raise ValueError('Recorded proposal request differs; start a new run')
        if not response_path.exists():
            raise RuntimeError('Interrupted API attempt has no saved response; it will not be repeated')
        raw = json.loads(response_path.read_text())['raw_response']
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    else:
        directory.mkdir(parents=True, exist_ok=True)
        write_json(request_path, request, redact=secret)
        events = []
        started = time.monotonic()
        with (directory / 'events.jsonl').open('w') as log:
            def emit(event):
                events.append(event)
                encoded = json.dumps(event, ensure_ascii=False) + '\n'
                log.write(encoded.replace(secret, '[REDACTED]') if secret else encoded)
                log.flush()
            with execution_scope(emit=emit):
                raw = client.chat(messages, json_schema=schema, schema_name=name)
            write_json(response_path, {'raw_response': raw}, redact=secret)
        write_json(directory / 'timing.json', {'seconds': time.monotonic() - started})
    if any(e.get('finish_reason') == 'length' for e in events if e['kind'] == 'model_response'):
        raise ValueError('Proposal was truncated')
    value = json.loads(raw)
    validate_json_schema(value, schema)
    return value
