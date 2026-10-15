"""Complete card author; program supplies role and stages."""
FIELDS = ('when_to_use', 'strategy')
def build_schema(max_words):
    properties = {field: dict(type='string', minLength=1) for field in FIELDS}
    return dict(type='object', additionalProperties=False, required=list(FIELDS), properties=properties)
