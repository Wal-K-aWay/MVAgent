"""Full-library batch reflection instructions."""
TASK = """# Full-library batch reflection
Analyze healthy public Train cases and their verified selected/injected Skill versions. The cluster only organizes examples; it does not own a card. Choose one generate, revise_metadata, revise_body, or skip decision.
For revise_metadata, identify a target card's misleading or missing original-input applicability condition causing false selection or abstention. Compare task goal, video relationship and evidence need with the actual body; subject matter similarity is insufficient. Do not narrow a reusable method to an incidental domain, clip count, duration or option count.
For revise_body, name a specific content defect and action-level evidence from a case that actually used this exact card version. Clear guidance that was ignored is not missing content. A visual/report error or wrong answer alone does not prove a card defect. Preserve supported successful rules.
Generate only when a supported reusable method is absent; non-selection alone is not proof a new card is needed. Similar existing methods should be considered before generating, but do not force unrelated errors into an existing card.
Ground truth is discrepancy feedback, never observed visual evidence. Do not infer private traces or unseen frames. At most one coherent edit per batch. Cite a non-perfect anchor and supporting case labels. Body/generation edits cite an editable Global step; metadata edits may use step=null because selection precedes the first action. Skip when evidence is insufficient.
Return status, reason, target_skill_id, sample_id, step, evidence_ids. Skip uses all nullable fields=null and evidence_ids=[]."""

REFLECT = "{context}"
