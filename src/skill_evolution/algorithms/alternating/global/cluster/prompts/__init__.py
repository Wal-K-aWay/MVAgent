"""Cluster reflection plus unchanged card authoring prompts."""
from mvagent.skills.prompts import render_skill_text
from .common import BACKGROUND, CARD_CONTRACT
from .reflect.prompts import TASK as REFLECT_TASK, REFLECT
from .generator.prompts import TASK as GENERATOR_TASK, GENERATOR
from .reviser.prompts import TASK as REVISER_TASK, REVISER
STAGE_TASKS = dict(reflect=REFLECT_TASK, generator=GENERATOR_TASK, reviser=REVISER_TASK)

def build_system_prompt(name):
    parts = [STAGE_TASKS[name], BACKGROUND]
    if name in ('generator', 'reviser'):
        parts += [CARD_CONTRACT]
    return '\n\n'.join(parts)

def build_stage_prompt(name, context):
    text = render_skill_text(context, minimum_level=3)
    return dict(reflect=REFLECT, generator=GENERATOR, reviser=REVISER)[name].replace('{context}', text)
