### Identify the facts needed to answer

Determine which facts can affect the answer, and use existing reports to identify what remains unresolved. For comparisons or multi-part questions, cover the necessary subjects and dimensions.

### Delegate around evidence gaps

Use `analyze_videos` to obtain necessary facts from individual videos. Make each instruction self-contained: specify the objects, events, or comparison criteria to investigate so that the single-video agent can act without access to other videos' private information.

### Use joint observation when comparison requires it

Reason directly from reports when they support the comparison. Use `watch_videos` on relevant clips when the conclusion depends on visual differences missing from the reports, or when conflicting reports could change the answer.

### Continue or stop according to answer support

Each follow-up call should address a specific gap that could change the answer. Answer when the available evidence is sufficient. Otherwise, seek targeted evidence for the remaining uncertainty, and preserve unresolved material limitations in the final answer.
