"""Four independently authored optimizer stages with a shared card contract."""

from importlib import import_module
from mvagent.skills.prompts import render_skill_text
from .common import BACKGROUND, CARD_CONTRACT


def build_system_prompt(name):
    module = import_module(__name__ + "." + name + ".prompts")
    return "\n\n".join(
        [module.TASK, BACKGROUND]
        + ([CARD_CONTRACT] if name in ("generator", "reviser") else [])
    )


def build_stage_prompt(name, context):
    module = import_module(__name__ + "." + name + ".prompts")
    return module.TEMPLATE.replace(
        "{context}", render_skill_text(context, minimum_level=3)
    )
