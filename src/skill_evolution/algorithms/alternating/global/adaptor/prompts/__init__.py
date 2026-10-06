"""Assemble stage prompts around readable evidence without changing its content."""
from mvagent.skills.prompts import render_skill_text
from .common import BACKGROUND, CARD_CONTRACT
from .localizer.prompts import TASK as LOCALIZER_TASK, LOCALIZER, build_localizer_prompt
from .linker.prompts import TASK as LINKER_TASK, LINKER
from .reviser.prompts import TASK as REVISER_TASK, REVISER
from .generator.prompts import TASK as GENERATOR_TASK, GENERATOR

STAGE_PROMPTS = dict(localizer=LOCALIZER, linker=LINKER, reviser=REVISER,
                     generator=GENERATOR)


STAGE_TASKS = dict(localizer=LOCALIZER_TASK, linker=LINKER_TASK, reviser=REVISER_TASK,
                   generator=GENERATOR_TASK)


def build_system_prompt(name):
    parts = [STAGE_TASKS[name], BACKGROUND]
    if name in ('reviser', 'generator'):
        parts.append(CARD_CONTRACT)
    return '\n\n'.join(parts)


def build_stage_prompt(name, context):
    if name == 'localizer':
        return build_localizer_prompt(context)
    return STAGE_PROMPTS[name].replace('{context}', render_skill_text(context, minimum_level=2 if name == 'linker' else 3))
