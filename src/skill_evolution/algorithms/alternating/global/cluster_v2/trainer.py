"""Cal search over complete banks, four optimizer stages, isolated Gate acceptance."""

from dataclasses import dataclass, asdict
from copy import deepcopy
import fcntl, json, math
from pathlib import Path
from mvagent.skills.bank import MAX_SKILL_WORDS
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import tree_hash, write_json
from .question_groups import QuestionGroups
from .evidence import EvidenceBudgetError
from .optimizer import Stages, StageValidationError
from .evaluation import Evaluator
from .search import StateStore, BudgetExhausted, ExplorationBudgetExhausted
from . import search


@dataclass(frozen=True)
class GlobalConfig:
    rounds: int = 30
    batch_size: int = 8
    history_size: int = 4
    seed: int = 20261006
    max_card_words: int = MAX_SKILL_WORDS
    max_context_chars: int = 100000
    pool_size: int = 3
    complement_support: int = 2
    exploration_steps: int = 2
    exploration_fraction: float = 0.25
    error_batch_every: int = 4
    candidates_per_round: int = 2
    max_candidates: int = 60
    max_question_evaluations: int = 20000
    evaluation_repeats: int = 2
    gate_every: int = 2
    stagnation_rounds: int = 12

    def __post_init__(self):
        for name in (
            "rounds",
            "batch_size",
            "max_card_words",
            "max_context_chars",
            "pool_size",
            "complement_support",
            "exploration_steps",
            "error_batch_every",
            "candidates_per_round",
            "max_candidates",
            "max_question_evaluations",
            "evaluation_repeats",
            "gate_every",
            "stagnation_rounds",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive integer")
        if type(self.history_size) is not int or self.history_size < 0:
            raise ValueError("history_size must be nonnegative")
        if type(self.seed) is not int:
            raise ValueError("seed must be integer")
        if self.candidates_per_round > 2:
            raise ValueError("At most two candidates")
        if self.max_card_words > MAX_SKILL_WORDS:
            raise ValueError("Card budget exceeds Runtime")
        if (
            type(self.exploration_fraction) not in (int, float)
            or not math.isfinite(self.exploration_fraction)
            or not 0 <= self.exploration_fraction < 1
        ):
            raise ValueError("exploration_fraction must be in [0,1)")


class GlobalTrainer:
    def __init__(
        self,
        *,
        config,
        initial_skill_set,
        train_context,
        cal_context,
        eval_context,
        executor,
        scorer,
        aggregator,
        projector,
        optimizer,
        embedding_config,
        sample_metadata,
        output_dir,
        episode_cache,
    ):
        self.config, self.initial = config, initial_skill_set
        self.train, self.cal, self.gate = train_context, cal_context, eval_context
        ids = [set(c.sample_ids) for c in (self.train, self.cal, self.gate)]
        if any(not x for x in ids) or any(
            ids[i] & ids[j] for i in range(3) for j in range(i)
        ):
            raise ValueError("Train/Cal/Gate must be nonempty and disjoint")
        if set(sample_metadata) != ids[0] | ids[1]:
            raise ValueError(
                "Optimizer metadata must contain exactly Train and Cal, never Gate/Test"
            )
        self.metadata = sample_metadata
        self.root = Path(output_dir)
        self.store = StateStore(self.root / "cluster_v2_evolution")
        self.stages = Stages(optimizer, config)
        self.matcher = QuestionGroups(embedding_config, self.root / "embeddings")
        self.identity = hash_json(
            dict(
                config=asdict(config),
                initial=initial_skill_set.to_dict(),
                train=train_context.context_hash,
                cal=cal_context.context_hash,
                gate=eval_context.context_hash,
                optimizer=optimizer.identity,
                embedding=embedding_config.to_dict(),
                metadata=sample_metadata,
                source=tree_hash(Path(__file__).parent),
            )
        )
        self.evaluation = Evaluator(
            config=config,
            train=self.train,
            cal=self.cal,
            gate=self.gate,
            executor=executor,
            scorer=scorer,
            aggregator=aggregator,
            projector=projector,
            metadata=sample_metadata,
            cache=episode_cache,
            root=self.root,
            store=self.store,
        )
        if (
            config.max_question_evaluations
            < (len(self.cal.sample_ids) + 2 * len(self.gate.sample_ids))
            * config.evaluation_repeats
        ):
            raise ValueError("Budget must cover initial Cal/Gate and final Gate")

    def run(self, *, resume=False):
        with (self.store.root / "training.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._run(resume)

    def _run(self, resume):
        state = self.store.initialize(self.initial, self.identity, resume=resume)
        path = self.root / "question_groups.json"
        if path.exists():
            grouping = json.loads(path.read_text())
        else:
            grouping = self.matcher.build(
                {sid: m["input"] for sid, m in self.metadata.items()}
            )
            write_json(path, grouping)
        grouping_hash = hash_json(grouping)
        if state.get("grouping_hash", grouping_hash) != grouping_hash:
            raise ValueError("Frozen question groups were modified")
        state["grouping_hash"] = grouping_hash
        self.store.save(state)
        self.evaluation.group_labels = {
            sid: group[0] for group in grouping["groups"] for sid in group
        }
        if not state["pool"]:
            cal = self.evaluation.cal_result(self.initial)
            self.evaluation.evaluate_panel(self.initial, "gate")
            node = dict(
                hash=self.initial.skill_set_hash(),
                score=cal["score"],
                expanded=0,
                created=0,
                kind="best",
                remaining=self.config.exploration_steps,
                justified=False,
                parent=None,
            )
            state.update(
                pool=[node], versions={node["hash"]: node}, gate_checked=[node["hash"]]
            )
            self.store.save(state)
        while state["pending"] is not None or (
            not state["finished"]
            and state["next_round"] < self.config.rounds
            and state["stagnant"] < self.config.stagnation_rounds
        ):
            candidate_count = sum(
                len(d.get("candidates", [])) for d in state["decisions"]
            )
            if (
                candidate_count >= self.config.max_candidates
                and state["pending"] is None
            ):
                break
            index = state["next_round"]
            directory = self.root / "rounds" / f"{index:04d}"
            if state["pending"] is None:
                parent_node = search.select_parent(
                    state["pool"],
                    state["exploration_expansions"],
                    int(self.config.rounds * self.config.exploration_fraction),
                )
                if parent_node is None:
                    break
                cluster, ids = search.select_batch(
                    index,
                    grouping["groups"],
                    self.train.sample_ids,
                    state["train_errors"],
                    self.config.batch_size,
                    self.config.seed,
                    self.config.error_batch_every,
                )
                state["pending"] = dict(
                    round=index,
                    parent=deepcopy(parent_node),
                    cluster=cluster,
                    ids=ids,
                    pool_before=deepcopy(state["pool"]),
                    known_versions=list(state["versions"]),
                    exploration_before=state["exploration_expansions"],
                    stagnant_before=state["stagnant"],
                )
                self.store.save(state)
            pending = state["pending"]
            parent_node = pending["parent"]
            parent = self.store.load(parent_node["hash"])
            self.evaluation.exploring = parent_node["kind"] == "exploration"
            decision = dict(
                round=index,
                parent_hash=parent_node["hash"],
                cluster=pending["cluster"],
                train_ids=pending["ids"],
                status="skip",
                candidates=[],
            )
            candidate_nodes = []
            try:
                cases, train_report = self.evaluation.collect(
                    parent, pending["ids"], index
                )
                state["train_errors"] = sorted(
                    (set(state["train_errors"]) - set(pending["ids"]))
                    | {sid for sid, s in train_report["scores"].items() if s.score < 1}
                )
                issue, plan = self.stages.diagnose(directory, cases, parent)
                if plan is not None:
                    if plan["status"] == "ready":
                        decision["operation"] = plan["operation"]
                        decision["target_skill_id"] = plan["target_skill_id"]
                        allowed = search.reserve_author(
                            state,
                            self.config,
                            self.store,
                            cal_size=len(self.cal.sample_ids),
                            final_reserve=self.evaluation.final_reserve,
                            candidate_count=candidate_count,
                            exploring=self.evaluation.exploring,
                        )
                        for variant, value, candidate in self.stages.author(
                            directory,
                            cases,
                            parent,
                            issue,
                            plan,
                            allowed,
                            pending["known_versions"],
                        ):
                            sha = candidate.skill_set_hash()
                            self.store.snapshot(candidate)
                            result = self.evaluation.cal_result(candidate)
                            self.evaluation.record_comparison(
                                parent,
                                result,
                                directory / f"cal_comparison_{variant}.json",
                            )
                            node = dict(
                                hash=sha,
                                parent=parent_node["hash"],
                                score=result["score"],
                                expanded=0,
                                created=index + 1,
                                kind="exploration",
                                remaining=(
                                    max(0, parent_node["remaining"] - 1)
                                    if parent_node["kind"] == "exploration"
                                    else self.config.exploration_steps
                                ),
                                justified=True,
                            )
                            candidate_nodes.append(node)
                            decision["candidates"].append(dict(hash=sha, change=value))
                        decision["status"] = (
                            "evaluated" if candidate_nodes else "no_candidate"
                        )
                    else:
                        decision.update(status="skip", reason=plan["reason"])
                else:
                    decision["status"] = "no_issue"
            except (StageValidationError, EvidenceBudgetError) as exc:
                decision.update(status="invalid_stage", reason=str(exc))
            except ExplorationBudgetExhausted as exc:
                decision.update(status="exploration_budget_stop", reason=str(exc))
            except BudgetExhausted as exc:
                decision.update(status="budget_stop", reason=str(exc))
                state["finished"] = True
            reports = {
                n["hash"]: self.evaluation.cal_result(self.store.load(n["hash"]))
                for n in pending["pool_before"] + candidate_nodes
            }
            search.record_expansion(
                state, decision, candidate_nodes, reports, self.config, self.store
            )
            self.evaluation.exploring = False
            if (index + 1) % self.config.gate_every == 0:
                self.evaluation.evaluate_gate(state)
            state["decisions"].append(decision)
            state["next_round"] += 1
            state["pending"] = None
            self.store.save(state)
        if not state["finished"] or not (self.root / "final_bank.json").exists():
            self.evaluation.evaluate_gate(state, final=True)
            state["finished"] = True
            self.store.save(state)
        best = self.store.load(state["best_hash"])
        write_json(self.root / "final_bank.json", best.to_dict())
        initial_gate = json.loads(
            (self.root / "gate" / (self.initial.skill_set_hash() + ".json")).read_text()
        )
        best_gate = json.loads(
            (self.root / "gate" / (state["best_hash"] + ".json")).read_text()
        )
        summary = dict(
            status="completed",
            algorithm="global-cluster-v2",
            rounds=state["next_round"],
            clusters=len(grouping["groups"]),
            skills=len(best.bank.cards),
            bank_hash=state["best_hash"],
            initial_gate=initial_gate["score"],
            final_gate=best_gate["score"],
            delta=best_gate["score"] - initial_gate["score"],
            accepted=sum(v["accepted"] for v in state["gate_verdicts"]),
            candidates_validated=sum(len(d["candidates"]) for d in state["decisions"]),
            question_evaluations=self.store.consumed(),
            pool=state["pool"],
        )
        write_json(self.root / "summary.json", summary)
        return summary
