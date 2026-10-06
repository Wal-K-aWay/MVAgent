You are asked to score the output of a model, given the following information:
- Question: {question}
- Standard Answer: {reference_answer}
- Scoring Points: {scoring_points}
- Model's Output: {prediction}

Please perform the following two-part scoring:
Part 1: Coverage of Scoring Points
- For each scoring point, determine whether it is covered by the Model's Output.
- Mark as covered (true) **only if** the scoring point is addressed **explicitly, independently, and clearly**.
- If the mention is vague, partial, or ambiguous, consider it **not covered**.

Part 2: Accuracy of Details
- For each covered scoring point, compare the details in the Model's Output to the Standard Answer.
- Mark as correct (true) **only if** the details are **fully accurate and consistent** with the Standard Answer, without any error, omission, or ambiguity.
- If the answer is partially correct, too broad/narrow, or not strictly consistent, mark it as **not correct** (false).
- For scoring points not covered, mark as incorrect.

Return exactly one JSON object in the following form:
{"coverage": [true, false, true], "correctness": [true, false, false]}
The length of the `coverage` and `correctness` lists must match the number of scoring points. Do not add tags, Markdown fences, or prose.
