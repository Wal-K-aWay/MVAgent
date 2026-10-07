### Strategy
Keep the usual decision procedure described by the Task, Rules and action descriptions.

- Begin from the full question text, including any options, and keep its wording and qualifiers in mind for every step.
- Base every visual claim on what successful single-video summaries or completed watch results already state. Do not assume facts that no report has stated, and do not treat failed actions as evidence.
- Use the IDs under Videos exactly as written. Each request must be answerable from the video or clips it names, without relying on other videos or on sibling results from the same step.
- Select one available action per step and return only the fields that action defines. Respect the existing limits on steps, on videos per joint watch and on instruction length.
- Avoid asking again for information that History already contains in a successful result.
- Once the gathered evidence covers what the question asks for, answer. If it does not yet cover it, gather the part that is still missing.
- This note restates the existing workflow; it does not add new actions, outputs or evidence.
