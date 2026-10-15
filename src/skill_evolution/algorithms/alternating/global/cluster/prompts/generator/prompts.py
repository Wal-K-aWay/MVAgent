"""Complete card authoring."""
TASK = """# Skill Generation
Generate one supported reusable whole-question method.
Return exactly when_to_use, strategy. JSON only. Follow the shared CARD_CONTRACT for both fields. when_to_use must faithfully describe the resulting method and its necessary prerequisites.
Prefer concrete observable conditions, valid actions, parameters available from input or earlier results, and clear completion criteria. Do not assume correct ground truth is present in returned evidence. Do not add already-clear ignored rules as if missing. Domain-specific cues may be examples; retain their general evidence relationship. Do not rewrite unrelated steps or promise unsupported task classes. strategy uses numbered condition/action/parameter instructions.
The program assigns the reference number; no id is returned."""
GENERATOR = """## Train card-authoring input
{context}"""
