"""Normal rollout, paired panels and isolated Gate."""

from collections import Counter
from dataclasses import replace
import json
from skill_evolution.infra.data import EvaluationRequest
from skill_evolution.infra.evaluation import evaluate_batch, compact_report
from skill_evolution.infra.trajectory import routing_audit, role_routing
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import write_json
from .evidence import training_case
from .search import BudgetExhausted


class Evaluator:
    """Execution/scoring only; never calls optimizer models or edits card text."""

    def __init__(
        self,
        *,
        config,
        train,
        cal,
        gate,
        executor,
        scorer,
        aggregator,
        projector,
        metadata,
        cache,
        root,
        store,
    ):
        self.config = config
        self.train, self.cal, self.gate = train, cal, gate
        self.executor, self.scorer, self.aggregator = executor, scorer, aggregator
        self.projector, self.metadata, self.cache = projector, metadata, cache
        self.root, self.store = root, store
        self.cal_reports = {}
        self.exploring = False

    @property
    def final_reserve(self):
        return len(self.gate.sample_ids) * self.config.evaluation_repeats

    def raw_rollout(self, bank, context, ids, label, *, final=False):
        identity = dict(
            bank=bank.skill_set_hash(), context=context.context_hash, ids=list(ids)
        )
        key = hash_json(identity)
        self.store.reserve_task(
            key,
            identity,
            len(ids),
            self.config.max_question_evaluations,
            0 if final else self.final_reserve,
            exploration=self.exploring and not final,
            exploration_limit=int(
                self.config.max_question_evaluations * self.config.exploration_fraction
            ),
        )
        print(
            json.dumps(dict(phase=label, samples=len(ids), bank=bank.skill_set_hash())),
            flush=True,
        )
        report = evaluate_batch(
            self.executor,
            self.cache,
            self.scorer,
            self.aggregator,
            EvaluationRequest(bank, context, tuple(ids), label),
        )
        write_json(
            self.root / "evaluations" / (label + ".json"), compact_report(report)
        )
        # Persist actual routing separately; it is not observation evidence.
        audit = routing_audit(
            bank,
            report,
            {sid: self.metadata.get(sid, {}).get("source_group", sid) for sid in ids},
        )
        write_json(self.root / "routing" / (label + ".json"), audit)
        self.store.complete_task(key)
        return report

    def cal_result(self, bank):
        sha = bank.skill_set_hash()
        if sha in self.cal_reports:
            return self.cal_reports[sha]
        path = self.root / "cal" / (sha + ".json")
        if path.exists():
            report = json.loads(path.read_text())
            if set(report["scores"]) != set(self.cal.sample_ids):
                raise ValueError("Incomplete frozen Cal")
            self.cal_reports[sha] = report
            return report
        return self.evaluate_panel(bank, "cal")

    def cases(self, bank, context, ids, label):
        report = self.raw_rollout(bank, context, ids, label)
        rows = []
        for sid in ids:
            if report["health"][sid]["fatal"] or report["health"][sid]["invalid"]:
                continue
            case = training_case(
                report, sid, bank, self.projector, self.metadata[sid]["reference"]
            )
            case["routing"] = role_routing(report["episodes"][sid], "global")
            case.update(
                sample_id=sid,
                source_sample_id=sid,
                source_group=self.metadata[sid].get("source_group", sid),
                partition="train" if sid in self.train.sample_ids else "cal",
            )
            rows.append(case)
        return rows, report

    def collect(self, bank, ids, round_index):
        rows, report = self.cases(bank, self.train, ids, f"r{round_index}_train")
        # Only current-parent evidence is supplied: relevant Cal success/failure is
        # verified under this parent, never borrowed as current from another bank.
        if self.config.history_size:
            summary = self.cal_result(bank)
            query = (
                " ".join(self.metadata[s]["input"]["question"] for s in ids)
                .lower()
                .split()
            )
            query = set(query)
            ranked = sorted(
                self.cal.sample_ids,
                key=lambda s: (
                    self.group_labels[s] not in {self.group_labels[sid] for sid in ids},
                    -len(
                        query
                        & set(self.metadata[s]["input"]["question"].lower().split())
                    ),
                    s,
                ),
            )
            failures = [s for s in ranked if summary["scores"][s] < 1]
            successes = [s for s in ranked if summary["scores"][s] == 1]
            references = []
            while (failures or successes) and len(
                references
            ) < self.config.history_size:
                for choices in (failures, successes):
                    if choices and len(references) < self.config.history_size:
                        references.append(choices.pop(0))
            if references:
                repeated = replace(
                    self.cal, repeat_id=self.cal.repeat_id + "/cluster_v2/cal/0"
                )
                extra, _ = self.cases(
                    bank, repeated, references, f"r{round_index}_verified_cal_history"
                )
                rows += extra
        return rows, report

    def record_comparison(self, parent, result, path):
        parent_result = self.cal_result(parent)
        improved = [
            sid
            for sid in self.cal.sample_ids
            if result["scores"][sid] > parent_result["scores"][sid]
        ]
        regressed = [
            sid
            for sid in self.cal.sample_ids
            if result["scores"][sid] < parent_result["scores"][sid]
        ]
        write_json(
            path,
            dict(
                parent_hash=parent.skill_set_hash(),
                candidate_hash=result["bank_hash"],
                delta=result["score"] - parent_result["score"],
                improved_ids=improved,
                regressed_ids=regressed,
                gain_source_groups=dict(
                    Counter(
                        self.metadata[sid].get("source_group", sid) for sid in improved
                    )
                ),
                loss_source_groups=dict(
                    Counter(
                        self.metadata[sid].get("source_group", sid) for sid in regressed
                    )
                ),
            ),
        )

    def evaluate_panel(self, bank, kind, *, final=False):
        context = {"cal": self.cal, "gate": self.gate}[kind]
        vectors = []
        reports = []
        for repeat in range(self.config.evaluation_repeats):
            repeated = replace(
                context, repeat_id=context.repeat_id + f"/cluster_v2/{kind}/{repeat}"
            )
            report = self.raw_rollout(
                bank,
                repeated,
                context.sample_ids,
                kind + "_" + bank.skill_set_hash() + f"_r{repeat}",
                final=final,
            )
            vectors.append({sid: s.score for sid, s in report["scores"].items()})
            reports.append(report)
        summary = compact_report(reports[0])
        summary["score"] = sum(r["score"] for r in reports) / len(reports)
        summary["scores"] = {
            sid: sum(v[sid] for v in vectors) / len(vectors)
            for sid in context.sample_ids
        }
        summary["bucket_scores"] = {
            k: sum(r["bucket_scores"][k] for r in reports) / len(reports)
            for k in reports[0]["bucket_scores"]
        }
        summary["repeat_vectors"] = vectors
        summary["repeat_health"] = [r["health"] for r in reports]
        if kind == "cal":
            buckets = {sid: e.bucket for sid, e in reports[0]["episodes"].items()}
            summary["weights"] = next(iter(self.cal_reports.values()), {}).get(
                "weights"
            ) or {
                sid: self.aggregator.aggregate(
                    sample_ids=context.sample_ids,
                    scores={s: float(s == sid) for s in context.sample_ids},
                    buckets=buckets,
                ).official_score
                for sid in context.sample_ids
            }
            self.cal_reports[bank.skill_set_hash()] = summary
        write_json(self.root / kind / (bank.skill_set_hash() + ".json"), summary)
        return summary

    def evaluate_gate(self, state, *, final=False):
        ranked = sorted(
            state["pool"], key=lambda n: (-n["score"], n["created"], n["hash"])
        )
        for node in ranked:
            sha = node["hash"]
            if sha in state["gate_checked"]:
                continue
            best = json.loads(
                (self.root / "gate" / (state["best_hash"] + ".json")).read_text()
            )
            if (
                node["score"]
                < self.cal_result(self.store.load(state["best_hash"]))["score"]
            ):
                continue
            try:
                result = self.evaluate_panel(self.store.load(sha), "gate", final=final)
            except BudgetExhausted:
                if final:
                    raise
                return
            accepted = result["score"] > best["score"]
            state["gate_checked"].append(sha)
            state["gate_verdicts"].append(dict(bank_hash=sha, accepted=accepted))
            write_json(
                self.root / "gate" / (sha + "_verdict.json"),
                dict(
                    accepted=accepted,
                    parent_hash=state["best_hash"],
                    parent_score=best["score"],
                    candidate_score=result["score"],
                ),
            )
            if accepted:
                state["best_hash"] = sha
            self.store.save(state)
            return  # at most one version at each predeclared checkpoint
