"""Search control: branch scheduling, Cal pool retention and atomic run state."""

import json
import random
from copy import deepcopy
from skill_evolution.infra.bank import BankStore
from skill_evolution.infra.store import write_json


class StateStore(BankStore):
    def initialize(self, seed, identity, *, resume):
        path = self.root / "state.json"
        if path.exists():
            value = self.read()
            if not resume or value["identity"] != identity:
                raise ValueError("Existing state or changed identity")
            for node in value["pool"]:
                self.load(node["hash"])
            self.load(value["best_hash"])
            return value
        if resume:
            raise ValueError("Resume requires initialized state")
        self.snapshot(seed)
        value = dict(
            identity=identity,
            next_round=0,
            best_hash=seed.skill_set_hash(),
            pool=[],
            versions={},
            decisions=[],
            gate_checked=[],
            gate_verdicts=[],
            train_errors=[],
            exploration_expansions=0,
            stagnant=0,
            finished=False,
            pending=None,
        )
        write_json(path, value)
        return value

    def save(self, value):
        write_json(self.root / "state.json", value)

    def reserve_task(
        self,
        key,
        identity,
        questions,
        limit,
        reserved=0,
        *,
        exploration=False,
        exploration_limit=0
    ):
        path = self.root / "tasks" / (key + ".json")
        if path.exists():
            row = json.loads(path.read_text())
            if row["identity"] != identity or row["questions"] != questions:
                raise ValueError("Task identity changed")
            return row
        spent = sum(
            json.loads(p.read_text())["questions"]
            for p in (self.root / "tasks").glob("*.json")
        )
        if spent + questions + reserved > limit:
            raise BudgetExhausted("Question evaluation budget exhausted")
        if exploration and self.exploration_consumed() + questions > exploration_limit:
            raise ExplorationBudgetExhausted("Exploration evaluation quota exhausted")
        row = dict(
            identity=identity,
            questions=questions,
            status="reserved",
            exploration=exploration,
        )
        write_json(path, row)
        return row

    def complete_task(self, key):
        path = self.root / "tasks" / (key + ".json")
        row = json.loads(path.read_text())
        row["status"] = "completed"
        write_json(path, row)

    def consumed(self):
        return sum(
            json.loads(p.read_text())["questions"]
            for p in (self.root / "tasks").glob("*.json")
        )

    def exploration_consumed(self):
        return sum(
            json.loads(p.read_text())["questions"]
            for p in (self.root / "tasks").glob("*.json")
            if json.loads(p.read_text()).get("exploration")
        )


class BudgetExhausted(RuntimeError):
    pass


class ExplorationBudgetExhausted(BudgetExhausted):
    pass


def select_parent(pool, exploration_expansions, exploration_limit):
    eligible = [
        n
        for n in pool
        if n["kind"] != "exploration"
        or (n["remaining"] > 0 and exploration_expansions < exploration_limit)
    ]
    if not eligible:
        return None
    return min(
        eligible, key=lambda n: (n["expanded"], -n["score"], n["created"], n["hash"])
    )


def select_batch(round_index, groups, train_ids, errors, batch_size, seed, error_every):
    if (round_index + 1) % error_every == 0 and errors:
        values = sorted(set(errors) & set(train_ids))
        if values:
            random.Random(seed + round_index).shuffle(values)
            return "global_errors", values[:batch_size]
    eligible = [(g[0], [sid for sid in g if sid in set(train_ids)]) for g in groups]
    eligible = [g for g in eligible if g[1]]
    index = round_index % len(eligible)
    label, values = eligible[index]
    values = list(values)
    cycle = round_index // len(eligible)
    random.Random(seed + index).shuffle(values)
    start = (cycle * batch_size) % len(values)
    return label, values[start : start + batch_size]


def update_pool(nodes, candidates, reports, *, capacity, support, exploration_allowed):
    indexed = {n["hash"]: dict(n) for n in nodes}
    for node in candidates:
        indexed.setdefault(node["hash"], dict(node))
    ranked = sorted(
        indexed.values(), key=lambda n: (-n["score"], n["created"], n["hash"])
    )
    if not ranked:
        return []
    selected = [dict(ranked[0], kind="best")]
    ids = list(reports[selected[0]["hash"]]["scores"])
    envelope = dict(reports[selected[0]["hash"]]["scores"])
    for node in ranked[1:]:
        if len(selected) >= capacity:
            break
        report = reports[node["hash"]]
        gains = [sid for sid in ids if report["scores"][sid] > envelope[sid]]
        weighted_gain = sum(
            report["weights"][sid] * (report["scores"][sid] - envelope[sid])
            for sid in gains
        )
        stable = all(
            sum(
                v[sid]
                > max(reports[n["hash"]]["repeat_vectors"][i][sid] for n in selected)
                for sid in ids
            )
            >= support
            for i, v in enumerate(report.get("repeat_vectors", []))
        )
        if len(gains) >= support and stable and weighted_gain > 0:
            selected.append(
                dict(
                    node,
                    kind="complement",
                    support_ids=gains,
                    weighted_gain=weighted_gain,
                )
            )
            for sid in ids:
                envelope[sid] = max(envelope[sid], report["scores"][sid])
    if exploration_allowed:
        for node in sorted(
            indexed.values(), key=lambda n: (-n["created"], -n["score"], n["hash"])
        ):
            if len(selected) >= capacity:
                break
            if any(n["hash"] == node["hash"] for n in selected):
                continue
            if node["remaining"] > 0 and node.get("justified", False):
                selected.append(dict(node, kind="exploration"))
    return selected


def reserve_author(
    state, config, store, *, cal_size, final_reserve, candidate_count, exploring
):
    """Persist the allowed candidate count once, including final Gate reservation."""
    pending = state["pending"]
    if "author_allowed" not in pending:
        cost = cal_size * config.evaluation_repeats
        available = config.max_question_evaluations - store.consumed() - final_reserve
        allowed = min(
            config.candidates_per_round,
            config.max_candidates - candidate_count,
            available // cost,
        )
        if exploring:
            quota = (
                int(config.max_question_evaluations * config.exploration_fraction)
                - store.exploration_consumed()
            )
            allowed = min(allowed, quota // cost)
            if allowed < 1:
                raise ExplorationBudgetExhausted(
                    "Insufficient exploration quota before authoring"
                )
        if allowed < 1:
            raise BudgetExhausted("Insufficient budget before authoring")
        pending["author_allowed"] = allowed
        store.save(state)
    return pending["author_allowed"]


def record_expansion(state, decision, candidates, reports, config, store):
    """Rebuild pool accounting from pending before the final round commit."""
    pending = state["pending"]
    parent_node = pending["parent"]
    # Reconstruct from the pending checkpoint so interruption never doubles
    # branch expansion, pool insertion or exploration consumption.
    previous = deepcopy(pending["pool_before"])
    for node in previous:
        if node["hash"] == parent_node["hash"]:
            node["expanded"] += 1
            if node["kind"] == "exploration":
                node["remaining"] = (
                    0
                    if decision["status"] == "exploration_budget_stop"
                    else max(0, node["remaining"] - 1)
                )
    state["exploration_expansions"] = pending["exploration_before"] + int(
        parent_node["kind"] == "exploration"
    )
    state["versions"].update({n["hash"]: deepcopy(n) for n in previous + candidates})
    before = max(n["score"] for n in previous)
    state["pool"] = update_pool(
        previous,
        candidates,
        reports,
        capacity=config.pool_size,
        support=config.complement_support,
        exploration_allowed=state["exploration_expansions"]
        < int(config.rounds * config.exploration_fraction)
        and store.exploration_consumed()
        < int(config.max_question_evaluations * config.exploration_fraction),
    )
    state["stagnant"] = (
        0
        if candidates and max(n["score"] for n in candidates) > before
        else pending["stagnant_before"] + 1
    )
    decision["pool"] = [
        dict(hash=n["hash"], kind=n["kind"], remaining=n["remaining"])
        for n in state["pool"]
    ]
