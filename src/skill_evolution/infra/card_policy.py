"""Shared authoring guidance; obvious marker checks do not prove semantic portability."""
import re


PORTABILITY_RULES = """Transfer check for every card:
Define one evidence procedure by the problem's information requirements, not by a
dataset, scene topic, answer format alone, or a particular backbone. Applicability
must be recognizable from the target role's supplied selection input. A specialist
method may be inapplicable to many inputs; keep none legal rather than broadening it
into a universal playbook.
Derive object identities, label meanings, option mappings, time anchors and ordering
from the current question or instruction. Do not assume a dataset's default camera
count, synchronized clocks, marker convention, motion, or numeric sampling recipe.
Keep necessary scope, exclusions, evidence-dependent branches and stopping conditions
inside strategy, without adding tools, output fields or hidden role information.
Before returning, check synthetic inputs with different scenes, labels or input
orders that preserve the intended evidence problem, and a nearby non-applicable
input. Do not use held-out evaluation cases for this check or output extra fields.
Textual generality and format validity are not evidence of transfer or accuracy;
those require frozen-library evaluation."""

_BENCHMARK_MARKER = re.compile(
    r"(?<![A-Za-z0-9])(?:cross[\s_-]*vid|cv[\s_-]*bench|mvu(?:[\s_-]*eval)?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def require_portable_text(when_to_use, strategy):
    # Semantic scope and case-specific shortcuts still require the authoring review.
    for field, text in (("when_to_use", when_to_use), ("strategy", strategy)):
        if _BENCHMARK_MARKER.search(text):
            raise ValueError(f"{field} contains a benchmark marker; keep provenance outside skill text")
