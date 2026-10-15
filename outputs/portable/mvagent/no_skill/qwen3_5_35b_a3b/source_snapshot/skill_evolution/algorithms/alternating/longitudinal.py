"""Pure SkillOpt slow/meta helpers; MVAgent supplies role views and model calls.

Functions below are copied from SkillOpt commit e7014cd18a18e11e6f6c10b897f7a009960d2e1b,
optimizer/{slow_update,meta_skill}.py (MIT; see prompts/SkillOpt-LICENSE.txt).
No SkillOpt runtime dependency or reference-tree imports.
"""
import json


SLOW_UPDATE_START = "<!-- SLOW_UPDATE_START -->"
SLOW_UPDATE_END = "<!-- SLOW_UPDATE_END -->"


def extract_slow_update_field(skill: str) -> str:
    start = skill.find(SLOW_UPDATE_START)
    end = skill.find(SLOW_UPDATE_END)
    if start == -1 or end == -1:
        return ""
    inner_start = start + len(SLOW_UPDATE_START)
    return skill[inner_start:end].strip()

def _strip_all_slow_update_fields(skill: str) -> str:
    """Remove every SLOW_UPDATE_START/END pair (and content between) from *skill*."""
    while True:
        start = skill.find(SLOW_UPDATE_START)
        if start == -1:
            break
        end = skill.find(SLOW_UPDATE_END, start)
        if end == -1:
            # Orphan start marker — remove it
            skill = skill[:start] + skill[start + len(SLOW_UPDATE_START):]
            break
        skill = skill[:start] + skill[end + len(SLOW_UPDATE_END):]
    # Clean up stray end markers
    skill = skill.replace(SLOW_UPDATE_END, "")
    # Collapse excess blank lines left behind
    while "\n\n\n" in skill:
        skill = skill.replace("\n\n\n", "\n\n")
    return skill.rstrip()

def replace_slow_update_field(skill: str, new_content: str) -> str:
    # Remove all existing slow update regions first to guarantee exactly one.
    skill = _strip_all_slow_update_fields(skill)
    block = (
        f"\n\n{SLOW_UPDATE_START}\n"
        f"{new_content.strip()}\n"
        f"{SLOW_UPDATE_END}\n"
    )
    return skill + block

def format_comparison_text(pairs: list[dict]) -> str:
    """Format structured comparison pairs into optimizer-readable text."""
    by_cat: dict[str, list[dict]] = {
        "regressed": [],
        "persistent_fail": [],
        "improved": [],
        "stable_success": [],
    }
    for p in pairs:
        by_cat.setdefault(p["category"], []).append(p)

    total = len(pairs)
    parts = [
        f"## Longitudinal Comparison Summary\n"
        f"Total samples: {total}\n"
        f"- Improved (wrong→right): {len(by_cat['improved'])}\n"
        f"- Regressed (right→wrong): {len(by_cat['regressed'])}\n"
        f"- Persistent failures (wrong→wrong): {len(by_cat['persistent_fail'])}\n"
        f"- Stable successes (right→right): {len(by_cat['stable_success'])}\n"
    ]

    categories = [
        ("regressed", "Regressions (right→wrong) — HIGHEST PRIORITY", True),
        ("persistent_fail", "Persistent Failures (wrong→wrong)", True),
        ("improved", "Improvements (wrong→right)", True),
        ("stable_success", "Stable Successes (right→right)", False),
    ]

    for cat_key, label, show_traj in categories:
        entries = by_cat[cat_key]
        if not entries:
            parts.append(f"### {label}\n(none)\n")
            continue

        lines = [f"### {label}"]
        for e in entries:
            prev = e["prev"]
            curr = e["curr"]
            lines.append(
                f"\n#### Task {e['id']}: {e['task']}\n"
                f"- Prev epoch: {'PASS' if prev['hard'] else 'FAIL'} "
                f"(soft={prev['soft']:.2f}) — answer: {str(prev['predicted_answer'])}\n"
                f"- Curr epoch: {'PASS' if curr['hard'] else 'FAIL'} "
                f"(soft={curr['soft']:.2f}) — answer: {str(curr['predicted_answer'])}"
            )
            if curr.get("fail_reason"):
                lines.append(f"- Curr fail reason: {curr['fail_reason']}")
            if prev.get("fail_reason") and not prev["hard"]:
                lines.append(f"- Prev fail reason: {prev['fail_reason']}")

            if show_traj:
                if e.get("prev_trajectory"):
                    lines.append(
                        f"\n**Previous epoch trajectory:**\n```\n{e['prev_trajectory']}\n```"
                    )
                if e.get("curr_trajectory"):
                    lines.append(
                        f"\n**Current epoch trajectory:**\n```\n{e['curr_trajectory']}\n```"
                    )

        parts.append("\n".join(lines))

    return "\n\n".join(parts)

def format_meta_skill_context(meta_skill_content: str) -> str:
    """Render optimizer memory into a prompt-ready context block."""
    content = (meta_skill_content or "").strip()
    if not content:
        return ""
    return (
        "## Optimizer Meta Skill\n"
        "This is optimizer-side memory distilled from prior epoch transitions in "
        "this environment. Use it to improve how you propose, merge, and rank "
        "skill edits. Prefer it when the current evidence is ambiguous, but do "
        "not force it if the current trajectories clearly contradict it.\n\n"
        f"{content}"
    )

def protected_region(skill):
    """Validate and return the exact protected region for fast/joint edit checks."""
    starts, ends = skill.count(SLOW_UPDATE_START), skill.count(SLOW_UPDATE_END)
    if not starts and not ends:
        return ""
    if starts != 1 or ends != 1 or skill.index(SLOW_UPDATE_END) < skill.index(SLOW_UPDATE_START):
        raise ValueError("Skill must contain exactly one well-formed slow-update region")
    return skill[skill.index(SLOW_UPDATE_START):skill.index(SLOW_UPDATE_END) + len(SLOW_UPDATE_END)]


def user_prompt(stage, context):
    """Upstream user sections; the actual panel size replaces the hard-coded 20."""
    role = context['target_role']
    previous = context['previous_skills'][role + '_skill']
    current = context['current_skills'][role + '_skill']
    comparison = format_comparison_text(context['comparison_pairs'])
    comparison += (
        "\n\n## Epoch Update Outcomes\n"
        "These are attempted policy edits and measured whole-question Gate outcomes, not "
        "local correctness labels. Content previews are incomplete proposal excerpts, not evidence. "
        "Only accepted edits were deployed. A rejected or invalid proposal is not an unexecuted "
        "recommendation to deploy later. No-change epochs may contain rejected attempts; do not "
        "infer that the optimizer never tried, or demand acceptance regardless of the Gate. "
        "Rows marked after_comparison_snapshot occurred after the frozen longitudinal comparison; "
        "their Gate results do not change that comparison. Missing scores mean no Gate result.\n"
        + json.dumps(context['epoch_update_feedback'], ensure_ascii=False, indent=2))
    if stage == 'slow_update':
        guidance = extract_slow_update_field(current) or '(No previous guidance — this is the first slow update.)'
        return (
            f"## Previous Epoch's Skill\n{previous}\n\n"
            f"## Current Epoch's Skill\n{current}\n\n"
            "## Previous Slow Update Guidance\n"
            "The following guidance was active during the current epoch. "
            "Reflect on its effectiveness before writing the new version.\n\n"
            f"{guidance}\n\n"
            f"## Longitudinal Comparison (same {len(context['comparison_pairs'])} tasks, two skill versions)\n"
            f"{comparison}"
        )
    memory = context.get('meta_skill', '') or '(No previous optimizer meta skill — this is the first update.)'
    return (
        f"## Previous Epoch Last-Step Skill\n{previous}\n\n"
        f"## Current Epoch Last-Step Skill\n{current}\n\n"
        "## Previous Optimizer Meta Skill\n"
        "The following optimizer memory was available during the current epoch. "
        "Reflect on whether it improved or harmed the quality of edits.\n\n"
        f"{memory}\n\n"
        f"## Longitudinal Comparison (same tasks, two last-step skills)\n{comparison}"
    )
