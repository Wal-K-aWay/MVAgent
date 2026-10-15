"""Complete new card, excluding program-owned metadata."""


def build_schema():
    content = dict(anyOf=[dict(type="string", minLength=1), dict(type="null")])
    props = dict(
        status=dict(type="string", enum=["edit", "skip"]),
        summary=dict(type="string", minLength=1),
        when_to_use=content,
        strategy=content,
    )
    return dict(
        type="object",
        additionalProperties=False,
        required=list(props),
        properties=props,
    )
