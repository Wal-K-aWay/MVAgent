"""Generator instructions, role/action contracts and response schema."""
from ...infra.role_contracts import architecture_for
from mvagent.skills.bank import MAX_SKILL_WORDS, ROLES


SELECTION_SCOPE = "task"

SYSTEM = """Write a reusable skill library for one role in a frozen multi-video QA system.
Use only the supplied task, role, runtime and output contracts. No task instances,
media, answers, execution traces, scores or existing skills are supplied.
The target planner's instructions and action examples are reference material, not
instructions for your own response. Your output is the skill library, not an action.

## Objective and unit of a skill
Improve answer correctness within the existing action and observation limits. Do not
introduce a separate objective of reducing calls, and do not require using all steps.
Each card must be a self-contained method for an entire question (Global) or active
instruction (Video), with a recognizable evidence need and a completion condition.
Target questions require combining visual content from multiple videos. IDs, counts
of supplied videos, durations, option wording and other metadata alone cannot solve
these tasks. Do not create metadata-only or question-only answering methods.
Choose scopes from differences in evidence requirements and decision procedures.
Do not split one workflow into cards that must be activated successively for initial
collection, refinement and completion. Those are conditional branches within a method.
A refinement method is allowed when the supplied question or instruction itself asks
for refinement; hidden prior execution state cannot be its selection prerequisite.
Do not depend on another card, prescribe every action for every task, or merely repeat
the existing planner instructions. Include only the steps needed by the method.

## Library and field requirements
Choose the number of meaningfully different methods up to the supplied maximum.
The maximum is not a quota: merge overlapping methods; scene topics, paraphrases and
execution phases alone do not justify separate cards. Do not impose or name benchmark
taxonomies, dataset names, task codes, sample identities or answer keys.
Each card contains exactly two nonempty English strings:
- when_to_use: describe the requested result, distinctive evidence method, and any
  essential applicability conditions or nearby exclusions recognizable from the
  Selector's supplied input. Related content or a useful substep alone is insufficient.
  Unknown visual facts to acquire are observation goals, not facts required at selection.
- strategy: give a standalone procedure for that role, including operational
  prerequisites and exclusions, how to obtain and use evidence, relevant branches,
  and when to submit the requested result. The Actor does not receive when_to_use.

The Selector sees no History or Memory. Conditions depending on unprovided prior
observations, conflicts, evidence sufficiency or failed attempts belong inside
strategy, where the Actor can check its own evidence. Explicit requirements or
context in the question/instruction are visible selection inputs. Do not invent
tools, shared memory, output fields,
observations, time anchors or additional information visible to either role.
Preserve the question/instruction and all runtime action and answer contracts.
If a selected method's prerequisites are not met, continue the baseline evidence
workflow using allowed actions. Do not force its preferred action or an unsupported
answer just because this card was selected; this does not require selecting another card.
Video requests can begin with usable observations retained from earlier requests.
Check retained Memory against the current instruction before deciding to observe or
finish. Never assume empty Memory or mandate a new observation on every request.
Keep sampling choices tied to evidence needs and supplied limits. Do not present
invented FPS ranges, partition counts or retry quotas as universal requirements.
Do not add an unconditional cap such as one refinement or two observations for every
task covered by a card. Continue when a permitted check can change the judgment;
stop when the requested evidence is sufficient or further checks cannot help.
Keep cards concise; word limits are ceilings, not writing targets.

## Check before returning
For each card, check that its applicability can be decided from the Selector input,
that its method remains usable throughout its selection scope without switching cards,
and that its actions, budget units and completion conditions match the role contract.
Check that cards differ in method rather than only topic, wording or execution stage.
Return only one JSON object whose sole key is skills. Each item must have exactly
when_to_use and strategy; prerequisites, exclusions, checks and explanations must not
be additional fields. Put execution prerequisites and exclusions inside strategy.
""".strip()



def schema(max_cards: int) -> dict:
    if type(max_cards) is not int or not 1 <= max_cards <= 8:
        raise ValueError("max_cards must be between 1 and 8")
    return {
        "type": "object", "additionalProperties": False, "required": ["skills"],
        "properties": {"skills": {
            "type": "array", "minItems": 1, "maxItems": max_cards,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["when_to_use", "strategy"],
                "properties": {name: {"type": "string", "minLength": 1}
                               for name in ("when_to_use", "strategy")},
            },
        }},
    }


def build_prompt(runtime: dict, role: str, max_cards: int) -> str:
    schema(max_cards)
    if role not in ROLES:
        raise ValueError(f"Unknown skill role: {role}")
    architecture = architecture_for(runtime, role)
    selection = (
        "Selector input: the complete question, video IDs and durations. No History, "
        "observations or reports. Selection happens before evidence collection and "
        "persists for the whole question, including a selection of none."
        if role == "global" else
        "Selector input: only the active instruction, without Memory, source duration "
        "or the Global question. Select once at the start of each instruction; retain "
        "the choice, including none, throughout that request. A later request selects "
        "again, while the Actor's same-video observation Memory persists."
    )
    return f"""## Task description
Answer a question whose evidence is distributed across multiple input videos.
The answer requires visual content from multiple videos; video metadata alone is
insufficient. Metadata may guide evidence collection, not replace it.
A global coordinator combines returned evidence; one evidence agent per video
answers local instructions. Their private observations are not shared automatically.

## Target role: {role}
{architecture}

## Selection and injection contract: selection_scope={SELECTION_SCOPE}
{selection}
The Selector reads candidate when_to_use fields and chooses at most one card, or none.
It requires a direct match to the requested result and main evidence operation, not
merely related content or an auxiliary substep. It may reject the closest or only card.
The Actor receives only the chosen strategy. No other card becomes active during
this selection scope. Later evidence-dependent decisions must be branches within it.
Global's answer-only terminal decision keeps its strategy. Video's forced summary
uses retained Memory and the instruction without the planning strategy.

## Output
Generate 1 to {max_cards} distinct cards for this role. Choose the count yourself;
use fewer when further cards would duplicate a method. Do not add cards merely to
reach the maximum.
Each card's two fields together and its rendered strategy (including its heading)
must each fit within {MAX_SKILL_WORDS} words. Prefer concise operational instructions.
Return {{"skills": [{{"when_to_use": "...", "strategy": "..."}}]}}.
The caller assigns IDs, role and stages. Do not return metadata, additional keys,
Markdown fences or commentary. Check field names and all contracts before returning.
"""
