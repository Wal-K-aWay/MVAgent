# p07_step_attribution.md

调用：`StepSkillTracker`。system message 为 `You are a precise skill attribution analyzer. Return only valid JSON.`；user message temperature `0.1`、max tokens `256`。

```text
# Skill Usage Analysis

You are analyzing which skills an AI agent used to complete a task.

## Available Skills

{for every bank skill: "- {id}:\n  Title: {title}\n  Purpose: {description[:150]}\n  When to use: {when[:100]}"}

## Current Step to Analyze

{up to previous three actions and optional thoughts}

**Current Observation**:
```
{observation[:500]}
```

**Action Taken**:
```
{action[:200]}
```

**Agent's Thinking** (if available):
```
{thinking[:300]}
```

## Analysis Guidelines

Determine which skills from the list above were actually USED or FOLLOWED in this step:

1. **Direct Application** (strong signal): Action clearly follows skill instructions
2. **Pattern Match** (medium signal): Behavior aligns with skill's "When to use" condition
3. **Conceptual Influence** (weak signal): Thinking references skill concepts
4. **No Usage**: Action is generic or unrelated to any skill

## Output Format

Return a JSON object with skill IDs that were used:

```json
{
  "skills_used": ["skill_001", "skill_003"],
  "reasoning": "Brief explanation of why these skills were used",
  "confidence": "high|medium|low"
}
```

If no skills were clearly used, return empty: `{"skills_used": [], "reasoning": "Generic action", "confidence": "high"}`
```

