# p02_linker.md

调用：`Linker._attribute_with_llm`，一条 `user` 消息，temperature `0.2`。

```text
# Skill Attribution Analysis
You are an expert agent debugger analyzing which skill(s) contributed to a failure.

## Fault Type Context
Fault type: {fault_type}
- skill_wrong: A skill was used but gave incorrect guidance → attribute to that skill with HIGH weight
- skill_missing: No skill covered this situation → LOW weights across available skills (or empty)
- reasoning_wrong: Skills were adequate but agent chose wrong → MEDIUM weights

## Fault Context
**Task**: {task_id}; **Fault Step**: {step_index}
**Observation at Fault Step**: {observation[:600]}
**Wrong Action Taken**: {wrong_action[:200]}
**What Should Have Been Done**: {improvement_principle[:300]}

## Skills to Evaluate
{relevant skills: id, title, description[:200], body[:500]}

## Examples
{buy skill lacking attribute preconditions; repeated unrefined search}

## Attribution Guidelines
1. **Direct Instruction Match** (±0.3)
2. **Context Appropriateness** (±0.2)
3. **Omission** (±0.2)
4. **Misleading Description** (±0.2)

## Weight Scale
0.8-1.0 fully responsible; 0.5-0.7 partially; 0.2-0.4 tangential; 0.0-0.1 irrelevant.

## Output Format
```json
{"attributions": [{"skill_id": "skill_id_here", "weight": 0.75, "reason": "Explanation"}]}
```
If no skill shares meaningful responsibility, return empty: {"attributions": []}
**Important**: Do not assign weight >= 0.5 unless the skill directly caused or failed to prevent the wrong action. Skills with weight < 0.5 are ignored for revision.
```

源码会丢弃未知 id/非法 weight；但 `skill_wrong` 时低权重最高嫌疑仍可被修订，故最后一句不是严格运行时规则。

