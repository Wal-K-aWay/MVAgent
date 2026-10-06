"""Evidence references are validated against the stage's actual case view."""


def reference_schema():
    return dict(
        type="object",
        additionalProperties=False,
        required=["case_id", "step"],
        properties={
            "case_id": dict(type="string", minLength=1),
            "step": dict(anyOf=[dict(type="integer", minimum=1), dict(type="null")]),
        },
    )


def build_schema():
    text = dict(type="string")
    items = dict(type="array", items=text, uniqueItems=True)
    props = dict(
        status=dict(type="string", enum=["issue", "no_issue"]),
        task_requirement=text,
        failure=text,
        evidence_refs=dict(type="array", items=reference_schema(), uniqueItems=True),
        preserved_behavior=items,
        hypotheses=items,
        uncertainties=items,
    )
    return dict(
        type="object",
        additionalProperties=False,
        required=list(props),
        properties=props,
    )
