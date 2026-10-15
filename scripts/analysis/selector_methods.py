"""Invoke the current Runtime selector unchanged; old ablations use frozen sources."""

METHODS = ('current',)


def invoke(model, prompt, *, system_prompt, json_schema, schema_name, bank, method):
    if method != 'current':
        raise ValueError('Historical selector ablations require their frozen sources')
    return model.json_chat(messages=[dict(role='system', content=system_prompt),
        dict(role='user', content=prompt)], json_schema=json_schema, schema_name=schema_name,
        temperature=0.0, top_p=1, max_tokens=2048)
