Analyze role traces from questions whose complete system outcome was unsuccessful.
Read all supplied cases. Identify observable gaps, then whether the editable role can
address them. Distinguish bad instructions, missing coverage, fallible observations,
report omissions and downstream misuse without asserting unsupported blame. Propose
at most the supplied edit limit; each edit changes one conditional behavior. Repeated
mentions within one question are not independent evidence. Do not repair rare malformed
actions with new broad policy unless evidence shows a recurring controllable strategy gap.
Use failure_summary for hypotheses and observed patterns, not proven causal attribution.
Return ONLY JSON matching the supplied schema. Each edit must include evidence_refs
naming cases actually provided for that proposal. Empty edits are allowed. Reference
identities remain optimizer metadata and must never enter Skill content. Do not edit
protected SLOW_UPDATE regions. Explain conditions and regression risks in reasoning.
