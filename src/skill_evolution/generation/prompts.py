"""Generator instructions, role/action contracts and response schema."""
from mvagent.agents.global_agent.prompts import build_global_action_prompt_blocks
from mvagent.agents.video_agent.prompts import build_planner_action_blocks
from mvagent.skills.bank import MAX_SKILL_WORDS, ROLES


SYSTEM = """You write reusable skills for a frozen multi-video question-answering system.
Use only the supplied task description, runtime contract, and skill format. No task
instances, media, answers, execution traces, scores, or existing skills are supplied.
Create complementary procedures for the requested role. Choose their scopes yourself;
do not invent a benchmark taxonomy or fill the card quota with redundant procedures.
Each card has exactly two nonempty English text fields:
- when_to_use: applicability recognizable from the selector's available input.
- strategy: a self-contained procedure using only the role's actions and visible evidence.
The selector chooses at most one card, or none. It reads only when_to_use; the Actor
receives only strategy. Include execution prerequisites and exclusions in strategy.
Do not rely on another skill. Put conditions depending on future observations inside
strategy. Preserve all action, memory, and answer contracts; do not invent tools,
extra output fields, or hidden information. Do not encode dataset names, task codes,
sample identities, or answer keys. A skill guides a reusable method, not one question.
Keep each card concise. Its two fields together, and the rendered strategy with its
heading, must each fit within the supplied word limit. Return only the requested JSON.
""".strip()


ROLE_CONTRACTS = {
    "global": """The Global Planner is text-only. It sees the complete question,
exact video IDs and durations, and public History. It never sees a VideoAgent's private
Observe calls or intermediate observations. It may choose `analyze_videos`,
`watch_videos` when available, or `answer`. `analyze_videos` sends independent
self-contained instructions to selected single-video agents. `watch_videos` selects at
least two distinct video clips for one joint visual comparison. `answer` directly submits
the final response in `parameters.answer`. Its strategy can improve action choice, video/clip selection,
single-video instructions, use of returned evidence, and answer timing. Available
actions and their parameter schemas are fixed by Runtime. Decisions repeat across
ordinary rounds and each completed action result enters public History, so a later
decision may refine an earlier call; no remaining-step count is visible.""",
    "video": """The Video Planner is text-only and owns one video. It sees one local
instruction, source duration, and chronological same-video Memory. It does not see the
complete question, sibling videos, Global History, or the visual clip directly. It may
choose `observe` with one focused visual question, ordered source ranges, and one FPS,
then may choose `finish` with a grounded summary after usable evidence exists. Available
actions, parameter validation, Observer execution, and summary publication are fixed by
Runtime. Its strategy can improve WHAT/range/FPS selection, broad-to-focused search,
use of retained Memory, re-observation after weak evidence, and Finish timing. Decisions
repeat across ordinary rounds and each usable Observe enters Memory, so a later decision
may refine an earlier call; no remaining-step count is visible.""",
}


def build_role_architectures(
    *,
    max_videos_per_watch: int = 4,
    max_video_inputs_per_request: int = 8,
    max_video_frames_per_request: int = 512,
    max_ranges_per_action: int = 8,
    global_max_steps: int = 5,
    video_max_steps: int = 5,
) -> dict[str, str]:
    """Render each target Planner's fixed contract for skill generation."""

    return {
        "global": (
            ROLE_CONTRACTS["global"]
            + f"\nConfigured maximum decision steps: {global_max_steps}."
            + "\n\n### Available actions\n"
            + build_global_action_prompt_blocks(
                ("answer", "analyze_videos", "watch_videos"),
                max_videos_per_watch=max_videos_per_watch,
                max_video_inputs_per_request=max_video_inputs_per_request,
            )
        ),
        "video": (
            ROLE_CONTRACTS["video"]
            + f"\nConfigured maximum decision steps: {video_max_steps}; visual frame limit per request: {max_video_frames_per_request}."
            + "\n\n### Available actions\n"
            + build_planner_action_blocks(
                ("observe", "finish"),
                duration_sec=1.0,
                max_video_frames_per_request=max_video_frames_per_request,
                max_ranges_per_action=max_ranges_per_action,
            )
        ),
    }


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
    global_config = runtime["agents"]["global_agent"]
    video_config = runtime["agents"]["video_agent"]
    observer = runtime["models"][video_config["observer"]["model_type"]]
    architecture = build_role_architectures(
        max_videos_per_watch=global_config["max_videos_per_watch"],
        max_video_inputs_per_request=observer["max_videos_per_request"],
        max_video_frames_per_request=observer["max_video_frames_per_request"],
        max_ranges_per_action=video_config["max_ranges_per_action"],
        global_max_steps=global_config["max_steps"],
        video_max_steps=video_config["max_steps"],
    )[role]
    selection = (
        "The selector sees the complete question, video IDs and durations. Selection "
        "occurs once at the beginning of the question and persists, including none."
        if role == "global" else
        "The selector sees the active instruction, not retained Memory or the global "
        "question. Selection occurs once per request and persists during that request. "
        "A new request selects again; same-video observation Memory persists."
    )
    return f"""## Task description
Answer a question whose evidence is distributed across multiple input videos.
The system has a global coordinator and one evidence agent per video. Each evidence
agent receives a local instruction and returns a report; its internal observations
remain private. The coordinator may also obtain joint visual observations.

## Target role: {role}
{architecture}

## Skill selection
{selection}
All generated cards will be eligible at initial and evidence stages. Stage eligibility
does not schedule future selection. The selected strategy guides ordinary decisions.
The Global answer-only terminal decision retains its strategy. The Video forced
summary receives retained Memory and the instruction, without the planning strategy.

## Output
Generate 1 to {max_cards} cards for this role, without forcing the maximum count.
Maximum per-card text and rendered-body length: {MAX_SKILL_WORDS} words.
Return {{"skills": [{{"when_to_use": "...", "strategy": "..."}}]}}.
The caller assigns IDs, role, and stages; do not return metadata or commentary.
"""
