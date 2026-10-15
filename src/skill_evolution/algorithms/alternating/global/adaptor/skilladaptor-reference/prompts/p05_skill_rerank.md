# p05_skill_rerank.md

调用：`rerank_skills_with_llm`；一条 `user` 消息，temperature `0.0`（经 `chat_temperature` 适配）。只在 `SkillAdaptor_LLM_RERANK` 未关闭时使用。

```text
# Skill rerank for agent injection

You rank which skills are most useful to inject for the task below.
Use only the candidate ids listed. Prefer skills that change verifier-visible
behavior for THIS task; demote unrelated skills.

## Task
{task_description[:1200]}

## Candidates (already filtered by embedding)
{for each of at most 10: "{rank}. id={id}\n   title={title}\n   embed_cosine={score:.4f}\n   when/desc={description_or_trigger[:180]}"}

## Output JSON only
{
  "ranked_ids": ["id_best", "id_second", ...],
  "reason": "one short sentence"
}
Return at most {max(top_k, len(pool))} ids, best first. Every id MUST appear in the candidate list.
```

解析后仅保留候选表中、去重后的 id，最多 `top_k`；空/非法 JSON 是错误。

