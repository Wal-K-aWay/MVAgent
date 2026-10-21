"""Role/action contracts shared by one-shot generation and feedback-based methods."""
from mvagent.agents.global_agent.prompts import (
    GLOBAL_AGENT_SYSTEM_PROMPT, build_global_action_prompt_blocks,
)
from mvagent.agents.video_agent.prompts import (
    VIDEO_PLANNER_SYSTEM_PROMPT, build_planner_action_blocks,
)

ROLE_CONTRACTS = {
    "global": """The Global Planner is text-only. It sees the complete question,
exact video IDs and durations, and public History. It never sees a VideoAgent's private
Observe calls or intermediate observations. analyze_videos sends independent,
self-contained instructions to single-video agents; a later action may pass returned
facts into new instructions. watch_videos makes a joint visual-model call on at least
two distinct videos and returns text evidence. answer submits parameters.answer.
The Global strategy is not automatically passed to VideoAgents or the visual model;
necessary task context must be conveyed through the action's instruction.
Decisions repeat across ordinary rounds; no remaining-step count is supplied.""",
    "video": """The Video Planner is text-only and owns one video. It sees the active
local instruction, source duration and chronological same-video Memory. It does not
see the complete Global question, sibling videos, Global History or video pixels.
It can observe with one visual question, ordered source ranges and one planned FPS,
and finish with a summary after usable observations exist. Same-video observations
persist across requests, but the current instruction defines the task to solve.
Decisions repeat across ordinary rounds; no remaining-step count is supplied.""",
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
    """Reuse the target planners' real system instructions and action descriptions."""
    return {
        "global": (
            ROLE_CONTRACTS["global"]
            + f"\nConfigured maximum ordinary decision steps: {global_max_steps}."
            + f"\nEach watch_videos action makes one joint visual call: its selected clips share a total limit of {max_video_frames_per_request} frames. Runtime allocates that capacity and chooses sampling; do not assign a separate full frame budget to each selected clip."
            + "\n\n### Existing planner system instructions\n" + GLOBAL_AGENT_SYSTEM_PROMPT
            + "\n\n### Available actions\n"
            + build_global_action_prompt_blocks(
                ("answer", "analyze_videos", "watch_videos"),
                max_videos_per_watch=max_videos_per_watch,
                max_video_inputs_per_request=max_video_inputs_per_request,
            )
        ),
        "video": (
            ROLE_CONTRACTS["video"]
            + f"\nConfigured maximum ordinary decision steps per instruction: {video_max_steps}."
            + f"\nAn observe action executes each requested range in a separate visual-model call. Each range has its own limit of {max_video_frames_per_request} frames; ranges do not share that limit. There is no {max_video_frames_per_request}-frame total budget for the whole observe action or instruction."
            + " One planned FPS is supplied for all ranges in an action; Runtime adjusts the effective FPS for each range to fit its own capacity. Use ranges and FPS to preserve the evidence needed, rather than dividing one frame budget by the sum of all requested durations."
            + "\n\n### Existing planner system instructions\n" + VIDEO_PLANNER_SYSTEM_PROMPT
            + "\n\n### Available actions\n"
            + build_planner_action_blocks(
                ("observe", "finish"), duration_sec=1.0,
                max_video_frames_per_request=max_video_frames_per_request,
                max_ranges_per_action=max_ranges_per_action,
            )
        ),
    }



def architecture_for(runtime, role):
    global_config = runtime['agents']['global_agent']
    video_config = runtime['agents']['video_agent']
    observer = runtime['models'][video_config['observer']['model_type']]
    return build_role_architectures(
        max_videos_per_watch=global_config['max_videos_per_watch'],
        max_video_inputs_per_request=observer['max_videos_per_request'],
        max_video_frames_per_request=observer['max_video_frames_per_request'],
        max_ranges_per_action=video_config['max_ranges_per_action'],
        global_max_steps=global_config['max_steps'], video_max_steps=video_config['max_steps'],
    )[role]
