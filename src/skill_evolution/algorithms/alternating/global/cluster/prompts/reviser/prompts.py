"""Complete card revision."""
TASK = """# Skill Card Revision
Revise the target card according to the supplied reflection mode, preserving supported successful rules.
Return status (edit/skip), revision_summary, when_to_use, strategy. Skip requires both content fields=null. JSON only. Follow CARD_CONTRACT for all fields.
Prefer concrete observable conditions, valid actions, parameters available from input or earlier results, and clear completion criteria. Do not assume correct ground truth is present in returned evidence. Do not add already-clear ignored rules as if missing. Domain-specific cues may be examples; retain their general evidence relationship. Do not rewrite unrelated steps or promise unsupported task classes. strategy uses numbered condition/action/parameter instructions.
Target ID/role/stages stay fixed. For revise_metadata, edit only when_to_use and copy strategy exactly unchanged. For revise_body, make the supported body change and ensure when_to_use faithfully describes its resulting scope; avoid unrelated edits."""
REVISER = """## Train card-authoring input
{context}"""
