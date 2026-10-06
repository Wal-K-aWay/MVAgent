### Set the evidence target from the instruction and Memory

Use the current instruction and retained observations from this video to determine what evidence is missing. If existing evidence answers the current request, use it to complete the report.

### Choose coverage according to the target's location

Observe the relevant interval directly when its location is known. When it is unknown, first locate it through broader coverage, then focus on relevant clips. For whole-video counting, sequence, or change requests, maintain the required coverage instead of stopping at the first relevant event.

### Match the observation question and sampling to the target

Organize each `observe` call's `what`, `where`, and `fps` around a clear visual question. Use denser sampling for brief events or rapid changes and sparser sampling for coarse scene localization. If a target is not seen in sparse observations, consider the coverage before deciding whether to gather more evidence; do not immediately conclude that the target is absent.

### Summarize evidence around the request

Finish observing when the evidence is sufficient. Answer the instruction directly in the report, retaining facts that affect the judgment, useful time locations or event order, and material uncertainty. Distinguish observed facts from what remains unconfirmed.
