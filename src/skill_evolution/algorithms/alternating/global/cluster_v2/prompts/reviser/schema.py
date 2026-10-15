"""Expose exactly the field the plan allows the author to edit."""


def build_schema(operation):
    field = {"WHEN": "when_to_use", "STRATEGY": "strategy"}[operation]
    props = dict(
        status=dict(type="string", enum=["edit", "skip"]),
        summary=dict(type="string", minLength=1),
    )
    props[field] = dict(anyOf=[dict(type="string", minLength=1), dict(type="null")])
    return dict(
        type="object",
        additionalProperties=False,
        required=list(props),
        properties=props,
    )
