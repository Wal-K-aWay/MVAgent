Analyze role traces from questions whose complete system outcome was successful.
A correct answer does not validate all intermediate behavior. Identify observable,
conditional practices supported across independent questions. Preserve success boundaries,
and propose only useful gaps beyond the current Skill and fixed Runtime prompts.
Do not copy all successful actions or assume the same action is useful in every task.
Use success_patterns to describe supported observations without claiming causal gains.
Return ONLY JSON matching the supplied schema. Each edit must include evidence_refs
naming cases actually provided for that proposal. Empty edits are allowed. Reference
identities remain optimizer metadata and must never enter Skill content. Do not edit
protected SLOW_UPDATE regions. Explain conditions and regression risks in reasoning.
