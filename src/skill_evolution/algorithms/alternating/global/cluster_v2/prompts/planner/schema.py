"""One justified edit or skip."""

from ..analyzer.schema import reference_schema


def build_schema():
    text = dict(type="string")
    strings = dict(type="array", items=text, uniqueItems=True)
    props = dict(
        status=dict(type="string", enum=["ready", "skip"]),
        reason=dict(type="string", minLength=1),
        operation=dict(
            anyOf=[
                dict(type="string", enum=["WHEN", "STRATEGY", "NEW"]),
                dict(type="null"),
            ]
        ),
        target_skill_id=dict(
            anyOf=[dict(type="string", minLength=1), dict(type="null")]
        ),
        evidence_refs=dict(type="array", items=reference_schema(), uniqueItems=True),
        checked_skill_ids=strings,
        goal=text,
        expected_benefit=text,
        preserved_behavior=strings,
        frozen_fields=strings,
    )
    return dict(
        type="object",
        additionalProperties=False,
        required=list(props),
        properties=props,
    )
