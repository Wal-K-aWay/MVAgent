"""Read-only hybrid lexical and embedding recall, then state-aware LLM selection."""
from __future__ import annotations

from contextlib import closing
from functools import lru_cache
import json
import re
import sqlite3
from typing import Callable

from models.execution import emit_event, event_scope
from models.embeddings import EmbeddingConfig, embed
from mvagent.utils.tools import validate_json_schema
from .bank import SkillBank, SkillCard, digest

from .prompts import build_selector_system_prompt, selection_input

EMBEDDING_INSTRUCTION = 'Retrieve agent skills whose when_to_use describes a method and applicability that address the current task and unresolved evidence needs.'


@lru_cache(maxsize=16)
def _embedding_index(cards: tuple[SkillCard, ...], config: EmbeddingConfig):
    # Immutable content + endpoint/model identity invalidate the per-process cache.
    return embed(config, tuple(c.when_to_use for c in cards))


def retrieve_embedding(cards: tuple[SkillCard, ...], query: str, top_k: int,
                       config: EmbeddingConfig) -> list[tuple[SkillCard, float]]:
    documents = _embedding_index(cards, config)
    vector = embed(config, (f'Instruct: {EMBEDDING_INSTRUCTION}\nQuery: {query}',))[0]
    if documents.shape[1] != vector.shape[0]:
        raise ValueError('Embedding document/query dimension mismatch')
    scores = documents @ vector
    return sorted(zip(cards, map(float, scores)), key=lambda row: (-row[1], row[0].id))[:top_k]


def tokens(text: str) -> list[str]:
    # CJK characters are separated so SQLite's Unicode tokenizer can match Chinese queries.
    return re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", text.casefold())


@lru_cache(maxsize=16)
def _index(cards: tuple[SkillCard, ...]) -> bytes:
    """Cache immutable SQLite images, never thread-bound connections or query state."""
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE VIRTUAL TABLE skills USING fts5(applicability, tokenize='porter unicode61')")
        db.executemany("INSERT INTO skills(rowid, applicability) VALUES (?, ?)",
                       [(i + 1, " ".join(tokens(c.when_to_use))) for i, c in enumerate(cards)])
        db.commit()
        return db.serialize()


def retrieve(cards: tuple[SkillCard, ...], query: str, top_k: int) -> list[tuple[SkillCard, float]]:
    """Applicability-only lexical recall. Small catalogs are fully exposed to the LLM."""
    terms = list(dict.fromkeys(tokens(query)))[:256]
    scores = {}
    if cards and terms:
        with closing(sqlite3.connect(":memory:")) as db:
            db.deserialize(_index(cards))
            match = " OR ".join('"' + term + '"' for term in terms)
            scores = {cards[rowid - 1].id: -score for rowid, score in db.execute(
                "SELECT rowid, bm25(skills) FROM skills WHERE skills MATCH ?", (match,))}
    ranked = sorted(cards, key=lambda c: (-scores.get(c.id, 0.0), c.id))
    # Zero-score entries are not arbitrarily admitted when the library exceeds the recall budget.
    if len(cards) > top_k:
        ranked = [c for c in ranked if scores.get(c.id, 0.0) > 0][:top_k]
    return [(c, scores.get(c.id, 0.0)) for c in ranked]


def retrieve_candidates(cards: tuple[SkillCard, ...], query: str,
                        embedding: EmbeddingConfig | None) -> tuple[list, str]:
    """Full small catalogs; otherwise reciprocal-rank fusion of metadata-only recall."""
    if len(cards) <= 8:
        return [(c, None) for c in sorted(cards, key=lambda c: c.id)], 'full-catalog-v1'
    if embedding is None:
        raise ValueError('More than 8 eligible Skills requires an embedding configuration for hybrid retrieval')
    lexical = retrieve(cards, query, 8)
    semantic = retrieve_embedding(cards, query, 8, embedding)
    scores, by_id = {}, {c.id: c for c in cards}
    for ranking in (lexical, semantic):
        for rank, (card, _) in enumerate(ranking, 1):
            scores[card.id] = scores.get(card.id, 0.0) + 1.0 / (60 + rank)
    ids = sorted(scores, key=lambda sid: (-scores[sid], sid))[:8]
    return [(by_id[sid], scores[sid]) for sid in ids], 'bm25-embedding-rrf-v1'


def select_skills(bank: SkillBank, *, role: str, has_evidence: bool, task: str,
                  state: dict, decide: Callable, selection_cache: dict | None = None) -> dict:
    """Return status/value(text); invalid selection is propagated before any action decision."""
    stage = "evidence" if has_evidence else "initial"
    task_scope = selection_cache is not None
    if selection_cache is not None and selection_cache:
        if selection_cache['bank_sha256'] != bank.sha256 or selection_cache['role'] != role:
            raise ValueError('Persistent Skill selection cannot change bank or role within a task')
        emit_event('skill_reuse', role=role, stage=stage, bank_sha256=bank.sha256,
                   activated_stage=selection_cache['stage'], status='ok',
                   selected=selection_cache['selected'],
                   rendered_sha256=digest(selection_cache['text']),
                   rendered_chars=len(selection_cache['text']), selection_scope='task')
        return dict(status='ok', value=selection_cache['text'])
    eligible = bank.eligible(role=role, stage=stage)
    query = task[:3000] + '\nRecent evidence/history:\n' + str(state.get('history', ''))[-3000:]
    candidates, retriever = retrieve_candidates(eligible, query, bank.embedding)
    ids = [c.id for c, _ in candidates]
    audit = dict(role=role, stage=stage, bank_sha256=bank.sha256, query=query,
                 selection_scope='task' if task_scope else 'decision',
                 retriever=retriever, retrieval_top_k=bank.retrieval_top_k,
                 embedding=bank.embedding.to_dict() if bank.embedding is not None else None,
                 max_selected=1, eligible_ids=[c.id for c in eligible],
                 candidates=[dict(id=c.id, score=score) for c, score in candidates],
                 state_sha256=digest(json.dumps(dict(task=task, **state), ensure_ascii=False, sort_keys=True)))
    emit_event("skill_retrieval", **audit)
    selected = []
    if candidates:
        schema = dict(type="object", additionalProperties=False,
            required=["selected_skill_ids"], properties={
                "selected_skill_ids": dict(type="array", items=dict(type="string", enum=ids),
                                          uniqueItems=True, maxItems=1),
            })
        prompt = selection_input(task, state, [c for c, _ in candidates], role=role)
        try:
            with event_scope(skill_phase="selection"):
                result = decide(prompt, system_prompt=build_selector_system_prompt(role), json_schema=schema,
                                schema_name="skill_selection")
            if result.get("status") != "ok":
                emit_event("skill_selection", **audit, status="invalid", selected=[],
                           error=result.get("error", "Invalid selector output"))
                return {**result, "error": "Skill selection: " + str(result.get("error", "Invalid output"))}
            value = result["value"]
            validate_json_schema(value, schema)
            selected = value["selected_skill_ids"]
            text = bank.render(selected)
        except (ValueError, KeyError, TypeError) as exc:
            emit_event("skill_selection", **audit, status="invalid", selected=[], error=str(exc))
            return dict(status="invalid", value=None, error=f"Skill selection: {exc}")
        except Exception as exc:
            emit_event("skill_selection", **audit, status="error", selected=[], error=str(exc))
            raise
    else:
        text = ""
    by_id = {c.id: c for c in bank.cards}
    emit_event("skill_selection", **audit, status="ok",
               selected=[dict(id=sid, sha256=by_id[sid].sha256) for sid in selected],
               excluded=[dict(id=c.id, reason="role" if c.role != role else
                              "stage" if stage not in c.stages else "retrieval" if c.id not in ids else "llm")
                         for c in bank.cards if c.id not in selected],
               rendered_sha256=digest(text), rendered_chars=len(text))
    if selection_cache is not None:
        selection_cache.update(bank_sha256=bank.sha256, role=role, stage=stage, text=text,
                               selected=[dict(id=sid, sha256=by_id[sid].sha256) for sid in selected])
    return dict(status="ok", value=text)
