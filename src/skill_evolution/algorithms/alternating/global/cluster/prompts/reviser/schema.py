"""Complete four-field revision with unchanged identity."""
from ..generator.schema import FIELDS
def build_schema(max_words, target_skill_id=None):
    text = dict(type='string', minLength=1)
    properties = {field: dict(anyOf=[text, dict(type='null')]) for field in FIELDS}
    properties.update(status=dict(type='string', enum=['edit','skip']), revision_summary=text)
    return dict(type='object', additionalProperties=False, required=['status','revision_summary', *FIELDS], properties=properties)
