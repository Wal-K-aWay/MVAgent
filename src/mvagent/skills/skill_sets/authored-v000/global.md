### Establish the answer requirements

Identify the required answer form and every explicit facet it must cover. From public per-video summaries and joint-watch results, distinguish resolved facts, conflicts, material limitations, and missing evidence. For multi-part, exhaustive, or difference-description tasks, do not treat one salient fact as completion.

### Choose the action for the evidence gap

Prefer `analyze_videos` when an independently visible per-video fact or its useful source region remains unknown. Prefer `watch_videos` when useful clips are known and direct cross-video viewing can resolve a relationship that separate summaries may not preserve, including conflicting or differently calibrated reports. Prefer `answer` when every requested facet that could change the conclusion is supported and material conflicts or limitations are accounted for.

### Delegate coherent evidence goals

Select videos whose unresolved evidence can still change the answer. For candidate-search or whole-set comparison tasks, include each plausible video not reliably excluded. Make each single-video instruction self-contained and target one coherent evidence goal. Combine related attributes visible in the same context; split unrelated goals or goals requiring different regions or detail. Include the grounded entities, actions, times, state changes, or criteria needed to interpret the request.

### Compare with sufficient context

Prefer focused video sets and clips when they preserve the needed context. Expand them when surrounding sequence or broader coverage is answer-critical. If one joint batch would become too broad or sparse, compare focused subsets and retain an anchor video when useful for consistent visual calibration.

Choose clip boundaries from question-provided times, current evidence, or the useful portion of a short video. Use the complete duration when a short video needs full-context comparison.

### Reuse, recover, and stop

Reuse successful evidence and avoid equivalent completed calls. After a failure, change the cause-relevant parameters or action rather than repeating the same call unchanged. Before answering, check every explicit answer facet and still-plausible video. Gather more evidence when an unresolved fact, conflict, or limitation could change the answer, not merely to increase the number of calls.
