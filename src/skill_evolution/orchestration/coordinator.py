from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Protocol, Sequence

from ..evaluation.comparison_cases import (
    attach_paired_regressions,
    build_paired_feedback_cases,
    select_repair_cases,
)
from ..evaluation.planner_replay import PlannerReplayChecker, PlannerReplayReview
from ..strategy.contracts import (
    ComparisonResult,
    EditOp,
    EvidencePacket,
    EvaluationResult,
    Role,
    SkillDiagnosis,
    SkillSet,
    SkillUpdateProposal,
    SkillUpdateRequest,
    TraceCase,
    hash_json,
    sha256_text,
)
from ..strategy.reviewer import CandidateReview
from ..strategy.updater import SkillUpdater
from .evidence import EvidencePacketBuilder
from .optimizer_memory import (
    OptimizerLesson,
    OptimizerMemory,
    optimizer_hypothesis_key,
    sanitize_optimizer_text,
)
from .search_policy import is_repairable_candidate


class SkillPatcher(Protocol):
    def propose(self, request: SkillUpdateRequest) -> Sequence[SkillUpdateProposal]: ...


class StagedSkillPatcher(Protocol):
    workflow: str

    def diagnose(
        self,
        request: SkillUpdateRequest,
        *,
        audit_context: dict[str, object] | None = None,
    ) -> SkillDiagnosis | None: ...

    def patch(
        self,
        request: SkillUpdateRequest,
        diagnosis: SkillDiagnosis,
        *,
        audit_context: dict[str, object] | None = None,
    ) -> Sequence[SkillUpdateProposal]: ...


class CandidateReviewer(Protocol):
    def review(
        self,
        *,
        role: Role,
        parent_skill: str,
        candidate_skill: str,
    ) -> CandidateReview: ...


class Evaluator(Protocol):
    def evaluate(self, *, skill_set: SkillSet, label: str) -> EvaluationResult: ...

    def compare(
        self,
        *,
        role: Role,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> ComparisonResult: ...


@dataclass(frozen=True)
class SearchConfig:
    cycles: int = 2
    beam_size: int = 2
    children_per_parent: int = 2
    proposal_attempts_per_child: int = 3
    detail_max_chars: int = 25_000
    provisional_per_role: int = 1
    provisional_score_drop_max: float = 0.15
    train_score_drop_max_cases: int = 0
    train_reliability_tolerance_cases: int = 0
    repair_attempts: int = 2
    seed: int = 0
    local_preference_weight: float = 0.25
    lookahead_preference_weight: float = 0.25
    lock_target_to_seed_role: bool = False
    role_order: tuple[Role, ...] = (Role.VIDEO, Role.GLOBAL)

    def __post_init__(self) -> None:
        counts = (
            self.cycles,
            self.beam_size,
            self.children_per_parent,
            self.proposal_attempts_per_child,
            self.detail_max_chars,
        )
        if min(counts) < 1:
            raise ValueError(
                "Search cycles, Beam size, child/attempt counts, edits, and detail "
                "budget must be positive."
            )
        for name in (
            "train_score_drop_max_cases",
            "train_reliability_tolerance_cases",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer.")
        if min(self.provisional_per_role, self.repair_attempts) < 0:
            raise ValueError("Search retention/repair limits must be non-negative.")
        if self.repair_attempts not in {0, 1, 2}:
            raise ValueError("repair_attempts must be 0, 1, or 2.")
        if not isinstance(self.lock_target_to_seed_role, bool):
            raise ValueError("lock_target_to_seed_role must be true or false.")
        if not 0.0 <= float(self.provisional_score_drop_max) <= 1.0:
            raise ValueError("provisional_score_drop_max must be in [0, 1].")
        object.__setattr__(
            self,
            "provisional_score_drop_max",
            float(self.provisional_score_drop_max),
        )
        roles = tuple(Role(role) for role in self.role_order)
        if set(roles) != {Role.GLOBAL, Role.VIDEO} or len(roles) != 2:
            raise ValueError("role_order must contain global and video exactly once.")
        object.__setattr__(self, "role_order", roles)


@dataclass(frozen=True)
class BeamNode:
    role: Role
    skill: str
    partner_sha256: str
    training_evaluation: EvaluationResult
    evaluation: EvaluationResult
    generation: int
    search_score: float
    comparison: ComparisonResult | None = None
    proposal: SkillUpdateProposal | None = None
    stale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))

    @property
    def skill_sha256(self) -> str:
        return sha256_text(self.skill)

    def rank_key(self) -> tuple[float, ...]:
        metrics = self.evaluation.metrics
        return (
            metrics.official_score,
            -metrics.fatal_rate,
            -metrics.invalid_action_rate,
            -float(self.generation),
        )


@dataclass(frozen=True)
class _RepairResult:
    skill_set: SkillSet
    proposal: SkillUpdateProposal
    review: CandidateReview
    training_evaluation: EvaluationResult
    comparison: ComparisonResult
    update_budget: Mapping[str, int | None]
    attempt_index: int


@dataclass(frozen=True)
class _PreparedCandidate:
    child_index: int
    attempt_index: int
    proposal: SkillUpdateProposal
    evidence: EvidencePacket
    skill_set: SkillSet
    candidate_skill: str
    review: CandidateReview
    planner_replay: PlannerReplayReview | None = None
    update_budget: Mapping[str, int | None] = field(default_factory=dict)


@dataclass(frozen=True)
class EvolutionStep:
    cycle: int
    role: Role
    parent_skill_sha256: str
    selected_skill_sha256: str
    proposed_count: int
    valid_count: int
    changed: bool


@dataclass(frozen=True)
class EvolutionResult:
    initial_skill_set: SkillSet
    skill_set: SkillSet
    training_evaluation: EvaluationResult
    evaluation: EvaluationResult
    steps: tuple[EvolutionStep, ...]
    global_beam: tuple[BeamNode, ...]
    video_beam: tuple[BeamNode, ...]
    optimizer_memory: dict[Role, tuple[OptimizerLesson, ...]]
    cross_checked_count: int
    provisional_pairs_evaluated: int = 0


@dataclass(frozen=True)
class CoordinatorProgress:
    initial_skill_set: SkillSet
    active_skill_set: SkillSet
    next_cycle: int
    next_role_index: int
    steps: tuple[EvolutionStep, ...]
    global_beam: tuple[BeamNode, ...]
    video_beam: tuple[BeamNode, ...]
    optimizer_memory: dict[Role, tuple[OptimizerLesson, ...]]
    attempted_skill_sha256: dict[Role, tuple[str, ...]] = field(default_factory=dict)
    provisional_global: tuple[BeamNode, ...] = ()
    provisional_video: tuple[BeamNode, ...] = ()


class JointSkillCoordinator:
    """Alternate one shared update/evaluate path across the two role Skills."""

    def __init__(
        self,
        *,
        patcher: SkillPatcher,
        training_evaluator: Evaluator,
        selection_evaluator: Evaluator,
        updater: SkillUpdater | None = None,
        reviewer: CandidateReviewer | None = None,
        planner_replay_checker: PlannerReplayChecker | None = None,
        config: SearchConfig | None = None,
        optimizer_memory: dict[Role, Sequence[OptimizerLesson]] | None = None,
        evidence_builder: EvidencePacketBuilder | None = None,
        on_step: Callable[[EvolutionStep, SkillSet], None] | None = None,
        on_checkpoint: Callable[[CoordinatorProgress], None] | None = None,
        on_attempt: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.patcher = patcher
        self.training_evaluator = training_evaluator
        self.selection_evaluator = selection_evaluator
        self.config = config or SearchConfig()
        self.updater = updater or SkillUpdater()
        if self.updater.max_edits != 1:
            raise ValueError("Skill evolution supports exactly one edit per candidate.")
        self.reviewer = reviewer
        self.planner_replay_checker = planner_replay_checker
        raw_memory = optimizer_memory or {}
        self.optimizer_memory = OptimizerMemory(
            item
            for role in Role
            for item in raw_memory.get(role, ())
        )
        self.on_step = on_step
        self.on_checkpoint = on_checkpoint
        self.on_attempt = on_attempt
        self.evidence_builder = evidence_builder or EvidencePacketBuilder(
            failure_size=6,
            success_size=2,
            detail_max_chars=self.config.detail_max_chars,
            seed=self.config.seed,
        )

    def evolve(
        self,
        initial_skill_set: SkillSet | None = None,
        *,
        resume: CoordinatorProgress | None = None,
    ) -> EvolutionResult:
        if resume is None:
            initial = initial_skill_set or SkillSet.zero()
            active = initial
            initial_training = self.training_evaluator.evaluate(
                skill_set=active,
                label="train-initial",
            )
            initial_evaluation = self.selection_evaluator.evaluate(
                skill_set=active,
                label="eval-initial",
            )
            beams = {
                role: [
                    BeamNode(
                        role=role,
                        skill=active.get(role),
                        partner_sha256=active.skill_sha256(self._other(role)),
                        training_evaluation=initial_training,
                        evaluation=initial_evaluation,
                        generation=0,
                        search_score=0.0,
                    )
                ]
                for role in Role
            }
            steps: list[EvolutionStep] = []
            provisional = {role: [] for role in Role}
            attempted_skill_sha256 = {
                role: {active.skill_sha256(role)} for role in Role
            }
            start_cycle = 1
            start_role_index = 0
            provisional_pairs_evaluated = 0
        else:
            if initial_skill_set is not None and initial_skill_set != resume.initial_skill_set:
                raise ValueError("Explicit initial SkillSet does not match the checkpoint.")
            initial = resume.initial_skill_set
            active = resume.active_skill_set
            beams = {
                Role.GLOBAL: list(resume.global_beam),
                Role.VIDEO: list(resume.video_beam),
            }
            steps = list(resume.steps)
            provisional = {
                Role.GLOBAL: list(resume.provisional_global),
                Role.VIDEO: list(resume.provisional_video),
            }
            attempted_skill_sha256 = {
                role: set(resume.attempted_skill_sha256.get(role, ()))
                | {active.skill_sha256(role)}
                for role in Role
            }
            self.optimizer_memory = OptimizerMemory(
                lesson
                for role in Role
                for lesson in resume.optimizer_memory.get(role, ())
            )
            start_cycle = resume.next_cycle
            start_role_index = resume.next_role_index
            provisional_pairs_evaluated = 0

        for cycle in range(start_cycle, self.config.cycles + 1):
            role_offset = start_role_index if cycle == start_cycle else 0
            if role_offset == 0:
                provisional = {role: [] for role in Role}
            for role_index in range(role_offset, len(self.config.role_order)):
                source_role = self.config.role_order[role_index]
                for item_role in Role:
                    beams[item_role] = self._refresh_beam(
                        item_role,
                        active,
                        beams[item_role],
                        cycle,
                    )
                baseline_training = self.training_evaluator.evaluate(
                    skill_set=active,
                    label=f"train-cycle-{cycle}-slot-{role_index}-parent",
                )
                baseline_evaluation = self.selection_evaluator.evaluate(
                    skill_set=active,
                    label=f"eval-cycle-{cycle}-slot-{role_index}-parent",
                )
                active_source_nodes = [
                    node
                    for node in beams[source_role]
                    if node.skill == active.get(source_role)
                    and node.partner_sha256
                    == active.skill_sha256(self._other(source_role))
                    and not node.stale
                ]
                active_source_node = max(
                    active_source_nodes,
                    key=lambda node: node.generation,
                    default=None,
                )
                source_node = BeamNode(
                    role=source_role,
                    skill=active.get(source_role),
                    partner_sha256=active.skill_sha256(self._other(source_role)),
                    training_evaluation=baseline_training,
                    evaluation=baseline_evaluation,
                    generation=(
                        active_source_node.generation
                        if active_source_node is not None
                        else 0
                    ),
                    search_score=0.0,
                    comparison=(
                        active_source_node.comparison
                        if active_source_node is not None
                        else None
                    ),
                )
                proposed_count = valid_count = 0
                eligible: list[tuple[BeamNode, SkillSet]] = []
                packets = self._select_evidence_packets(source_node, cycle=cycle)
                prepared: Sequence[_PreparedCandidate] = ()
                if packets:
                    prepared, proposed_count = self._prepare_candidates(
                        cycle=cycle,
                        role=source_role,
                        parent_index=0,
                        parent_node=source_node,
                        parent_set=active,
                        packets=packets,
                        attempted_skill_sha256=attempted_skill_sha256,
                        role_generations={
                            item_role: max(
                                (
                                    node.generation
                                    for node in beams[item_role]
                                    if node.skill == active.get(item_role)
                                ),
                                default=0,
                            )
                            for item_role in Role
                        },
                    )
                    valid_count = len(prepared)

                for candidate in prepared:
                        child_index = candidate.child_index
                        proposal_attempt_index = candidate.attempt_index
                        proposal = candidate.proposal
                        target_role = proposal.role
                        candidate_skill_set = candidate.skill_set
                        candidate_skill = candidate.candidate_skill
                        review = candidate.review
                        planner_replay = candidate.planner_replay
                        update_budget = candidate.update_budget
                        attempt_phase = "proposal"
                        target_parent_node = BeamNode(
                            role=target_role,
                            skill=active.get(target_role),
                            partner_sha256=active.skill_sha256(
                                self._other(target_role)
                            ),
                            training_evaluation=baseline_training,
                            evaluation=baseline_evaluation,
                            generation=max(
                                (
                                    node.generation
                                    for node in beams[target_role]
                                    if node.skill == active.get(target_role)
                                ),
                                default=0,
                            ),
                            search_score=0.0,
                        )
                        training_evaluation = self._evaluate_role_candidate(
                            self.training_evaluator,
                            skill_set=candidate_skill_set,
                            reference_skill_set=active,
                            changed_role=target_role,
                            label=(
                                f"train-cycle-{cycle}-{target_role.value}-"
                                f"slot-{role_index}-child-{child_index}"
                            ),
                        )
                        comparison = self.training_evaluator.compare(
                            role=target_role,
                            reference=baseline_training,
                            candidate=training_evaluation,
                        )
                        training_evaluation = attach_paired_regressions(
                            role=target_role,
                            reference=baseline_training,
                            candidate=training_evaluation,
                            comparison=comparison,
                        )
                        if is_repairable_candidate(
                            baseline_training,
                            training_evaluation,
                        ):
                            reason = (
                                "repairable: train score improved but action cost "
                                "regressed; one train-only repair is required"
                            )
                            self._remember_evaluation(
                                target_role,
                                proposal,
                                reason=reason,
                                training_reference=baseline_training,
                                training_candidate=training_evaluation,
                                comparison=comparison,
                            )
                            self._emit_attempt(
                                cycle=cycle,
                                role=target_role,
                                parent_index=0,
                                child_index=child_index,
                                attempt_index=proposal_attempt_index,
                                proposal=proposal,
                                candidate_skill=candidate_skill,
                                review=review,
                                training_reference=baseline_training,
                                training_candidate=training_evaluation,
                                planner_replay=planner_replay,
                                status="repairable",
                                reason=reason,
                                update_budget=update_budget,
                            )
                            repair = self._attempt_repair(
                                cycle=cycle,
                                role=target_role,
                                parent_index=0,
                                child_index=child_index,
                                parent_node=target_parent_node,
                                candidate_skill_set=candidate_skill_set,
                                candidate_proposal=proposal,
                                candidate_training=training_evaluation,
                                candidate_comparison=comparison,
                            )
                            if repair is None:
                                continue
                            proposed_count += 1
                            valid_count += 1
                            candidate_skill_set = repair.skill_set
                            proposal = repair.proposal
                            review = repair.review
                            training_evaluation = repair.training_evaluation
                            comparison = repair.comparison
                            candidate_skill = repair.skill_set.get(target_role)
                            planner_replay = None
                            update_budget = repair.update_budget
                            proposal_attempt_index = repair.attempt_index
                            attempt_phase = "repair"
                        if not self._passes_train_screen(
                            reference=baseline_training,
                            candidate=training_evaluation,
                        ):
                            reason = "rejected by train screen"
                            self._remember_evaluation(
                                target_role,
                                proposal,
                                reason=reason,
                                training_reference=baseline_training,
                                training_candidate=training_evaluation,
                                comparison=comparison,
                            )
                            self._emit_attempt(
                                cycle=cycle,
                                role=target_role,
                                parent_index=0,
                                child_index=child_index,
                                attempt_index=proposal_attempt_index,
                                proposal=proposal,
                                candidate_skill=candidate_skill,
                                review=review,
                                training_reference=baseline_training,
                                training_candidate=training_evaluation,
                                planner_replay=planner_replay,
                                status="train_rejected",
                                reason=reason,
                                update_budget=update_budget,
                            )
                            continue
                        evaluation = self._evaluate_role_candidate(
                            self.selection_evaluator,
                            skill_set=candidate_skill_set,
                            reference_skill_set=active,
                            changed_role=target_role,
                            label=(
                                f"eval-cycle-{cycle}-{target_role.value}-"
                                f"slot-{role_index}-child-{child_index}"
                            ),
                        )
                        node = BeamNode(
                            role=target_role,
                            skill=candidate_skill,
                            partner_sha256=active.skill_sha256(
                                self._other(target_role)
                            ),
                            training_evaluation=training_evaluation,
                            evaluation=evaluation,
                            generation=target_parent_node.generation + 1,
                            search_score=self._search_score(
                                training_evaluation,
                                comparison,
                            ),
                            comparison=comparison,
                            proposal=proposal,
                        )
                        if self._improves_on_eval(
                            reference=baseline_evaluation,
                            candidate=evaluation,
                        ):
                            eligible.append((node, candidate_skill_set))
                            status = "committed_eligible"
                            reason = "strict eval improvement with no reliability regression"
                        elif is_repairable_candidate(
                            baseline_evaluation,
                            evaluation,
                        ):
                            status = "eval_rejected"
                            reason = (
                                "rejected: eval exposed a reliability regression; eval "
                                "case details are hidden from the optimizer"
                            )
                        elif self._eligible_provisional(
                            reference=baseline_evaluation,
                            candidate=evaluation,
                        ):
                            provisional[target_role].append(node)
                            provisional[target_role] = self._select_provisional(
                                provisional[target_role]
                            )
                            status = "provisional"
                            reason = "held for Global/Video joint evaluation"
                        else:
                            status = "eval_rejected"
                            reason = "rejected: outside provisional eval limits"
                        self._remember_evaluation(
                            target_role,
                            proposal,
                            reason=reason,
                            training_reference=baseline_training,
                            training_candidate=training_evaluation,
                            evaluation_reference=baseline_evaluation,
                            evaluation_candidate=evaluation,
                            comparison=comparison,
                        )
                        self._emit_attempt(
                            cycle=cycle,
                            role=target_role,
                            parent_index=0,
                            child_index=child_index,
                            attempt_index=proposal_attempt_index,
                            proposal=proposal,
                            candidate_skill=candidate_skill,
                            review=review,
                            training_reference=baseline_training,
                            training_candidate=training_evaluation,
                            evaluation_reference=baseline_evaluation,
                            evaluation_candidate=evaluation,
                            planner_replay=planner_replay,
                            status=status,
                            reason=reason,
                            phase=attempt_phase,
                            update_budget=update_budget,
                        )

                for node, _skill_set in eligible:
                    beams[node.role] = self._select_beam(
                        [*beams[node.role], node]
                    )
                previous_active = active
                if eligible:
                    selected_node, selected_set = max(
                        eligible,
                        key=lambda item: self._eval_rank_key(item[0].evaluation),
                    )
                    step_role = selected_node.role
                    active = selected_set
                else:
                    step_role = source_role
                    selected_node = BeamNode(
                        role=step_role,
                        skill=active.get(step_role),
                        partner_sha256=active.skill_sha256(self._other(step_role)),
                        training_evaluation=baseline_training,
                        evaluation=baseline_evaluation,
                        generation=source_node.generation,
                        search_score=0.0,
                    )
                changed = previous_active != active
                if changed:
                    if selected_node.proposal is not None:
                        self._remember(
                            selected_node.role,
                            selected_node.proposal,
                            "promoted after strict eval improvement; "
                            + self._split_delta(
                                "eval",
                                selected_node.role,
                                baseline_evaluation,
                                selected_node.evaluation,
                            ),
                            kind="promoted",
                        )
                    provisional = {item_role: [] for item_role in Role}

                for item_role in Role:
                    partner_sha = active.skill_sha256(self._other(item_role))
                    beams[item_role] = [
                        replace(node, stale=node.partner_sha256 != partner_sha)
                        for node in beams[item_role]
                    ]
                step = EvolutionStep(
                    cycle=cycle,
                    role=step_role,
                    parent_skill_sha256=previous_active.skill_sha256(step_role),
                    selected_skill_sha256=active.skill_sha256(step_role),
                    proposed_count=proposed_count,
                    valid_count=valid_count,
                    changed=changed,
                )
                steps.append(step)
                if role_index + 1 < len(self.config.role_order):
                    next_cycle, next_role_index = cycle, role_index + 1
                else:
                    (
                        active,
                        beams,
                        joint_changed,
                        joint_count,
                    ) = self._try_joint_provisional(
                        cycle=cycle,
                        active=active,
                        beams=beams,
                        provisional=provisional,
                    )
                    provisional_pairs_evaluated += joint_count
                    if joint_changed:
                        for index, previous in enumerate(steps):
                            if previous.cycle != cycle:
                                continue
                            selected_hash = active.skill_sha256(previous.role)
                            steps[index] = replace(
                                previous,
                                selected_skill_sha256=selected_hash,
                                changed=(
                                    previous.parent_skill_sha256 != selected_hash
                                ),
                            )
                    provisional = {item_role: [] for item_role in Role}
                    next_cycle, next_role_index = cycle + 1, 0
                if self.on_step is not None:
                    self.on_step(steps[-1], active)
                if self.on_checkpoint is not None:
                    self.on_checkpoint(
                        CoordinatorProgress(
                            initial_skill_set=initial,
                            active_skill_set=active,
                            next_cycle=next_cycle,
                            next_role_index=next_role_index,
                            steps=tuple(steps),
                            global_beam=tuple(beams[Role.GLOBAL]),
                            video_beam=tuple(beams[Role.VIDEO]),
                            optimizer_memory=self.optimizer_memory.snapshot(),
                            provisional_global=tuple(provisional[Role.GLOBAL]),
                            provisional_video=tuple(provisional[Role.VIDEO]),
                            attempted_skill_sha256={
                                item_role: tuple(sorted(items))
                                for item_role, items in attempted_skill_sha256.items()
                            },
                        )
                    )

        active, final_evaluation, cross_checked_count = self._cross_check(
            active=active,
            beams=beams,
        )
        final_training_evaluation = self.training_evaluator.evaluate(
            skill_set=active,
            label="train-final",
        )
        return EvolutionResult(
            initial_skill_set=initial,
            skill_set=active,
            training_evaluation=final_training_evaluation,
            evaluation=final_evaluation,
            steps=tuple(steps),
            global_beam=tuple(beams[Role.GLOBAL]),
            video_beam=tuple(beams[Role.VIDEO]),
            optimizer_memory=self.optimizer_memory.snapshot(),
            cross_checked_count=cross_checked_count,
            provisional_pairs_evaluated=provisional_pairs_evaluated,
        )

    def _cross_check(
        self,
        *,
        active: SkillSet,
        beams: dict[Role, list[BeamNode]],
    ) -> tuple[SkillSet, EvaluationResult, int]:
        combinations: dict[str, tuple[SkillSet, EvaluationResult]] = {
            active.skill_set_hash(): (
                active,
                self.selection_evaluator.evaluate(
                    skill_set=active,
                    label="eval-cross-active",
                ),
            )
        }
        for global_index, global_node in enumerate(beams[Role.GLOBAL]):
            for video_index, video_node in enumerate(beams[Role.VIDEO]):
                skill_set = SkillSet(
                    global_skill=global_node.skill,
                    video_skill=video_node.skill,
                )
                evaluation = self.selection_evaluator.evaluate(
                    skill_set=skill_set,
                    label=f"eval-cross-global-{global_index}-video-{video_index}",
                )
                combinations[skill_set.skill_set_hash()] = (skill_set, evaluation)
        selected_set, selected_evaluation = max(
            combinations.values(),
            key=lambda item: self._eval_rank_key(item[1]),
        )
        return selected_set, selected_evaluation, len(combinations)

    def _refresh_beam(
        self,
        role: Role,
        active: SkillSet,
        nodes: list[BeamNode],
        cycle: int,
    ) -> list[BeamNode]:
        partner_sha = active.skill_sha256(self._other(role))
        refreshed: list[BeamNode] = []
        for index, node in enumerate(nodes):
            if not node.stale and node.partner_sha256 == partner_sha:
                refreshed.append(node)
                continue
            skill_set = active.replace(role, node.skill)
            training_evaluation = self._evaluate_role_candidate(
                self.training_evaluator,
                skill_set=skill_set,
                reference_skill_set=active,
                changed_role=role,
                label=f"train-cycle-{cycle}-{role.value}-refresh-{index}",
            )
            evaluation = self._evaluate_role_candidate(
                self.selection_evaluator,
                skill_set=skill_set,
                reference_skill_set=active,
                changed_role=role,
                label=f"eval-cycle-{cycle}-{role.value}-refresh-{index}",
            )
            refreshed.append(
                replace(
                    node,
                    partner_sha256=partner_sha,
                    training_evaluation=training_evaluation,
                    evaluation=evaluation,
                    search_score=0.0,
                    comparison=None,
                    stale=False,
                )
            )
        return self._select_beam(refreshed)

    def _select_evidence_packets(
        self,
        node: BeamNode,
        *,
        cycle: int,
    ) -> tuple[EvidencePacket, ...]:
        misalignment_ids = (
            node.comparison.misalignment_ids if node.comparison is not None else ()
        )
        return self.evidence_builder.build(
            role=node.role,
            cases=node.training_evaluation.cases,
            cycle=cycle,
            max_batches=self.config.children_per_parent,
            min_support_cases=self.updater.min_edit_evidence,
            min_support_groups=2,
            misalignment_ids=misalignment_ids,
            allow_unattributed=node.role is Role.VIDEO,
        )

    def _changed_char_budget(
        self,
        *,
        parent: str,
        evidence: EvidencePacket,
        generation: int,
    ) -> int | None:
        cases = {case.case_id: case for case in evidence.cases}
        support_group_count = len(
            {
                cases[case_id].source_group or case_id
                for case_id in evidence.support_ids
            }
        )
        return self.updater.changed_char_budget(
            parent=parent,
            support_group_count=support_group_count,
            generation=generation,
        )

    def _update_budget_audit(
        self,
        *,
        parent: str,
        candidate: str | None,
        evidence: EvidencePacket,
        generation: int,
        allowed_changed_chars: int | None,
    ) -> dict[str, int | None]:
        by_id = {case.case_id: case for case in evidence.cases}
        independent_groups = len(
            {
                by_id[case_id].source_group or case_id
                for case_id in evidence.support_ids
            }
        )
        return {
            "allowed_changed_chars": allowed_changed_chars,
            "actual_changed_chars": (
                self.updater.changed_chars(parent, candidate)
                if candidate is not None
                else None
            ),
            "independent_support_groups": independent_groups,
            "target_generation": generation,
        }

    def _role_max_chars(self, parent_set: SkillSet, role: Role) -> int:
        parent = parent_set.get(role)
        if not parent:
            return self.updater.initial_max_chars
        return min(
            self.updater.max_chars,
            len(parent) + self.updater.max_net_growth,
        )

    def _prepare_candidates(
        self,
        *,
        cycle: int,
        role: Role,
        parent_index: int,
        parent_node: BeamNode,
        parent_set: SkillSet,
        packets: Sequence[EvidencePacket],
        attempted_skill_sha256: dict[Role, set[str]],
        role_generations: Mapping[Role, int] | None = None,
    ) -> tuple[list[_PreparedCandidate], int]:
        """Turn each child slot into at most one unique, rollout-ready candidate."""
        if isinstance(attempted_skill_sha256, set):
            # Compatibility for direct component callers; the coordinator itself owns
            # one deduplication set per model-selected target role.
            attempted_skill_sha256 = {
                item_role: attempted_skill_sha256 if item_role is role else set()
                for item_role in Role
            }
        slot_packets = list(packets[: self.config.children_per_parent])
        prepared: list[_PreparedCandidate] = []
        proposed_count = 0
        common_max_chars = min(
            self._role_max_chars(parent_set, item_role) for item_role in Role
        )
        generations = {
            item_role: int(
                (role_generations or {}).get(item_role, parent_node.generation)
            )
            for item_role in Role
        }
        staged = getattr(self.patcher, "workflow", "single_stage") == (
            "diagnose_then_patch"
        )

        def current_optimizer_memory(
            target_role: Role | None = None,
        ) -> tuple[str, ...]:
            return self.optimizer_memory.render(target_role)
        for child_index, evidence in enumerate(slot_packets):
            frozen_diagnosis: SkillDiagnosis | None = None
            staged_evidence: EvidencePacket | None = None
            retry_feedback: list[str] = []
            source_generation = generations[role]
            source_changed_budget = self._changed_char_budget(
                parent=parent_node.skill,
                evidence=evidence,
                generation=source_generation,
            )
            unlocked_changed_budgets = {
                item_role: self._changed_char_budget(
                    parent=parent_set.get(item_role),
                    evidence=evidence,
                    generation=generations[item_role],
                )
                for item_role in Role
            }
            source_budget_without_candidate = self._update_budget_audit(
                parent=parent_node.skill,
                candidate=None,
                evidence=evidence,
                generation=source_generation,
                allowed_changed_chars=source_changed_budget,
            )
            source_max_chars = (
                self._role_max_chars(parent_set, role)
                if self.config.lock_target_to_seed_role
                else common_max_chars
            )

            if staged:
                staged_patcher = self.patcher
                for diagnosis_attempt in range(
                    self.config.proposal_attempts_per_child
                ):
                    diagnosis_request = SkillUpdateRequest(
                        role=role,
                        parent_skill=parent_node.skill,
                        evidence=evidence,
                        cycle=cycle,
                        candidate_number=child_index + 1,
                        candidate_count=self.config.children_per_parent,
                        seed=(
                            self.config.seed
                            + cycle * 10_000
                            + parent_index * 1_000
                            + child_index * 100
                            + diagnosis_attempt
                        ),
                        max_chars=source_max_chars,
                        max_changed_chars=source_changed_budget,
                        changed_char_budgets=(
                            {role: source_changed_budget}
                            if self.config.lock_target_to_seed_role
                            else unlocked_changed_budgets
                        ),
                        generation=source_generation,
                        target_role_lock=(
                            role if self.config.lock_target_to_seed_role else None
                        ),
                        optimizer_memory=(
                            *current_optimizer_memory(),
                            *retry_feedback,
                        ),
                        parent_skill_set=parent_set,
                    )
                    frozen_diagnosis = staged_patcher.diagnose(  # type: ignore[attr-defined]
                        diagnosis_request,
                        audit_context={
                            "phase": "discover",
                            "seed_role": role.value,
                            "parent_index": parent_index,
                            "child_index": child_index,
                            "stage_attempt": diagnosis_attempt,
                        },
                    )
                    if frozen_diagnosis is not None:
                        break
                    diagnosis_reason = (
                        "rejected: diagnosis did not satisfy the structured output "
                        "contract"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=diagnosis_attempt,
                        proposal=None,
                        status="invalid",
                        reason=diagnosis_reason,
                        phase="diagnosis",
                        update_budget=source_budget_without_candidate,
                    )
                    retry_feedback.append(
                        "[format_static] The previous diagnosis did not satisfy the "
                        "structured output contract."
                    )
                if frozen_diagnosis is None:
                    continue
                if frozen_diagnosis.target_role is None:
                    proposal = SkillUpdateProposal(
                        role=role,
                        parent_sha256=parent_set.skill_sha256(role),
                        diagnosis=frozen_diagnosis,
                        case_assessments=evidence.case_assessments,
                    )
                    proposed_count += 1
                    reason = f"no change: {frozen_diagnosis.pattern}"
                    self._remember(role, proposal, reason, kind="no_change")
                    self._emit_attempt(
                        cycle=cycle,
                        role=role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=diagnosis_attempt,
                        proposal=proposal,
                        status="no_change",
                        reason=reason,
                        update_budget=self._update_budget_audit(
                            parent=parent_node.skill,
                            candidate=parent_node.skill,
                            evidence=evidence,
                            generation=source_generation,
                            allowed_changed_chars=source_changed_budget,
                        ),
                    )
                    continue
                target_role = frozen_diagnosis.target_role
                staged_evidence = self._retarget_evidence(
                    evidence=evidence,
                    role=target_role,
                    all_cases=parent_node.training_evaluation.cases,
                    min_support_cases=diagnosis_request.min_support_cases,
                    min_support_groups=diagnosis_request.min_support_groups,
                )
                if staged_evidence is None:
                    proposal = SkillUpdateProposal(
                        role=target_role,
                        parent_sha256=parent_set.skill_sha256(target_role),
                        diagnosis=frozen_diagnosis,
                        case_assessments=evidence.case_assessments,
                    )
                    reason = (
                        "rejected: complete episodes do not contain enough independent "
                        f"{target_role.value} Planner cases for the selected attribution"
                    )
                    self._remember(
                        target_role, proposal, reason, kind="format_static"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=target_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=diagnosis_attempt,
                        proposal=proposal,
                        status="invalid",
                        reason=reason,
                        update_budget=source_budget_without_candidate,
                    )
                    continue
                frozen_diagnosis = replace(
                    frozen_diagnosis,
                    support_ids=staged_evidence.support_ids,
                    contrast_ids=staged_evidence.contrast_ids,
                )
                retry_feedback.clear()

            for attempt_index in range(self.config.proposal_attempts_per_child):
                if staged:
                    assert frozen_diagnosis is not None
                    assert frozen_diagnosis.target_role is not None
                    assert staged_evidence is not None
                    request_role = frozen_diagnosis.target_role
                    request_evidence = staged_evidence
                    request_parent = parent_set.get(request_role)
                    request_generation = generations[request_role]
                    request_max_chars = self._role_max_chars(
                        parent_set,
                        request_role,
                    )
                    request_changed_budget = self._changed_char_budget(
                        parent=request_parent,
                        evidence=request_evidence,
                        generation=request_generation,
                    )
                else:
                    request_role = role
                    request_evidence = evidence
                    request_parent = parent_node.skill
                    request_generation = source_generation
                    request_max_chars = source_max_chars
                    request_changed_budget = source_changed_budget
                request = SkillUpdateRequest(
                    role=request_role,
                    parent_skill=request_parent,
                    evidence=request_evidence,
                    cycle=cycle,
                    candidate_number=child_index + 1,
                    candidate_count=self.config.children_per_parent,
                    seed=(
                        self.config.seed
                        + cycle * 10_000
                        + parent_index * 1_000
                        + child_index * 100
                        + attempt_index
                    ),
                    max_chars=request_max_chars,
                    max_changed_chars=request_changed_budget,
                    changed_char_budgets=(
                        {request_role: request_changed_budget}
                        if staged or self.config.lock_target_to_seed_role
                        else unlocked_changed_budgets
                    ),
                    generation=request_generation,
                    target_role_lock=(
                        role if self.config.lock_target_to_seed_role else None
                    ),
                    optimizer_memory=(
                        *current_optimizer_memory(
                            request_role if staged else None
                        ),
                        *retry_feedback,
                    ),
                    parent_skill_set=parent_set,
                )
                request_budget_without_candidate = self._update_budget_audit(
                    parent=request_parent,
                    candidate=None,
                    evidence=request_evidence,
                    generation=request_generation,
                    allowed_changed_chars=request.max_changed_chars,
                )
                if staged:
                    proposals = tuple(
                        self.patcher.patch(  # type: ignore[attr-defined]
                            request,
                            frozen_diagnosis,
                            audit_context={
                                "phase": "discover",
                                "seed_role": role.value,
                                "parent_index": parent_index,
                                "child_index": child_index,
                                "stage_attempt": attempt_index,
                            },
                        )
                    )
                else:
                    proposals = tuple(self.patcher.propose(request))
                proposed_count += len(proposals)
                if not proposals:
                    proposal_reason = (
                        "rejected: update did not satisfy the structured output "
                        "contract"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=request_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=None,
                        status="invalid",
                        reason=proposal_reason,
                        update_budget=request_budget_without_candidate,
                    )
                    retry_feedback.append(
                        "[format_static] The previous update did not satisfy the "
                        "structured output contract."
                    )
                    continue
                proposal = proposals[0]
                if (
                    self.config.lock_target_to_seed_role
                    and proposal.edits
                    and proposal.role is not role
                ):
                    reason = (
                        "rejected: proposal changed the role locked to this "
                        f"{role.value} evidence slot"
                    )
                    self._remember(
                        proposal.role,
                        proposal,
                        reason,
                        kind="format_static",
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=proposal.role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        status="invalid",
                        reason=reason,
                        update_budget=request_budget_without_candidate,
                    )
                    retry_feedback.append(f"[format_static] {reason}")
                    continue
                if not proposal.edits:
                    reason = f"no change: {proposal.diagnosis.pattern}"
                    self._remember(
                        proposal.role, proposal, reason, kind="no_change"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=proposal.role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        status="no_change",
                        reason=reason,
                        update_budget=self._update_budget_audit(
                            parent=request_parent,
                            candidate=request_parent,
                            evidence=request_evidence,
                            generation=request_generation,
                            allowed_changed_chars=request.max_changed_chars,
                        ),
                    )
                    break
                if not self._matches_evidence_packet(proposal, request):
                    reason = (
                        "rejected: proposal altered the system-selected evidence packet"
                    )
                    self._remember(
                        proposal.role, proposal, reason, kind="format_static"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=proposal.role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        status="invalid",
                        reason=reason,
                        update_budget=request_budget_without_candidate,
                    )
                    retry_feedback.append(f"[format_static] {reason}")
                    continue
                target_role = proposal.role
                if staged:
                    assert staged_evidence is not None
                    target_evidence = staged_evidence
                else:
                    target_evidence = self._retarget_evidence(
                        evidence=evidence,
                        role=target_role,
                        all_cases=parent_node.training_evaluation.cases,
                        min_support_cases=request.min_support_cases,
                        min_support_groups=request.min_support_groups,
                    )
                    if target_evidence is None:
                        reason = (
                            "rejected: complete episodes do not contain enough independent "
                            f"{target_role.value} Planner cases for the selected attribution"
                        )
                        self._remember(
                            target_role, proposal, reason, kind="format_static"
                        )
                        self._emit_attempt(
                            cycle=cycle,
                            role=target_role,
                            parent_index=parent_index,
                            child_index=child_index,
                            attempt_index=attempt_index,
                            proposal=proposal,
                            status="invalid",
                            reason=reason,
                            update_budget=request_budget_without_candidate,
                        )
                        retry_feedback.append(f"[format_static] {reason}")
                        continue
                    proposal = replace(
                        proposal,
                        diagnosis=replace(
                            proposal.diagnosis,
                            support_ids=target_evidence.support_ids,
                            contrast_ids=target_evidence.contrast_ids,
                        ),
                        case_assessments=target_evidence.case_assessments,
                    )
                target_generation = generations[target_role]
                target_changed_budget = self._changed_char_budget(
                    parent=parent_set.get(target_role),
                    evidence=target_evidence,
                    generation=target_generation,
                )
                target_budget_without_candidate = self._update_budget_audit(
                    parent=parent_set.get(target_role),
                    candidate=None,
                    evidence=target_evidence,
                    generation=target_generation,
                    allowed_changed_chars=target_changed_budget,
                )
                hypothesis_key = optimizer_hypothesis_key(
                    role=target_role,
                    failure_source=proposal.diagnosis.failure_source,
                    expected_behavior_change=(
                        proposal.diagnosis.expected_behavior_change
                    ),
                )
                if self.optimizer_memory.blocks(target_role, hypothesis_key):
                    reason = (
                        "rejected: the same normalized hypothesis already caused an "
                        "eval regression; narrow the Runtime-visible trigger or test a "
                        "different behavior change"
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=target_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        status="hypothesis_blocked",
                        reason=reason,
                        update_budget=target_budget_without_candidate,
                    )
                    retry_feedback.append(f"[eval_regression] {reason}")
                    continue
                update = self.updater.apply(
                    parent_set,
                    proposal,
                    allowed_case_ids={case.case_id for case in target_evidence.cases},
                    min_edit_evidence=request.min_support_cases,
                    max_changed_chars=target_changed_budget,
                )
                if not update.accepted:
                    if update.errors:
                        reason = "rejected: " + "; ".join(update.errors)
                        status = "invalid"
                    else:
                        reason = f"no change: {proposal.diagnosis.pattern}"
                        status = "no_change"
                    self._remember(
                        target_role,
                        proposal,
                        reason,
                        kind="format_static" if update.errors else "no_change",
                    )
                    self._emit_attempt(
                        cycle=cycle,
                        role=target_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        status=status,
                        reason=reason,
                        update_budget=(
                            target_budget_without_candidate
                            if update.errors
                            else self._update_budget_audit(
                                parent=parent_set.get(target_role),
                                candidate=parent_set.get(target_role),
                                evidence=target_evidence,
                                generation=target_generation,
                                allowed_changed_chars=target_changed_budget,
                            )
                        ),
                    )
                    if not update.errors:
                        break
                    retry_feedback.append(f"[format_static] {reason}")
                    continue
                assert update.skill_set is not None
                candidate_skill = update.skill_set.get(target_role)
                candidate_update_budget = self._update_budget_audit(
                    parent=parent_set.get(target_role),
                    candidate=candidate_skill,
                    evidence=target_evidence,
                    generation=target_generation,
                    allowed_changed_chars=target_changed_budget,
                )
                candidate_sha256 = sha256_text(candidate_skill)
                if candidate_sha256 in attempted_skill_sha256[target_role]:
                    reason = (
                        "rejected: duplicate candidate already attempted for this role"
                    )
                    self._remember(target_role, proposal, reason, kind="duplicate")
                    self._emit_attempt(
                        cycle=cycle,
                        role=target_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        candidate_skill=candidate_skill,
                        status="duplicate",
                        reason=reason,
                        update_budget=candidate_update_budget,
                    )
                    retry_feedback.append(f"[duplicate] {reason}")
                    continue
                attempted_skill_sha256[target_role].add(candidate_sha256)
                review = CandidateReview(True)
                if self.reviewer is not None:
                    review = self.reviewer.review(
                        role=target_role,
                        parent_skill=parent_set.get(target_role),
                        candidate_skill=candidate_skill,
                    )
                if not review.passed:
                    reason = "rejected by generality review: " + "; ".join(
                        review.reasons
                    )
                    self._remember(target_role, proposal, reason, kind="semantic_review")
                    self._emit_attempt(
                        cycle=cycle,
                        role=target_role,
                        parent_index=parent_index,
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        candidate_skill=candidate_skill,
                        review=review,
                        status="review_rejected",
                        reason=reason,
                        update_budget=candidate_update_budget,
                    )
                    retry_feedback.append(f"[semantic_review] {reason}")
                    continue
                planner_replay = None
                if self.planner_replay_checker is not None:
                    planner_replay = self.planner_replay_checker.check(
                        role=target_role,
                        parent_skill_set=parent_set,
                        candidate_skill_set=update.skill_set,
                        evidence=target_evidence,
                    )
                    if not planner_replay.passed:
                        reason = "rejected by Planner replay: " + planner_replay.reason
                        self._remember(
                            target_role,
                            proposal,
                            reason,
                            kind="planner_replay",
                        )
                        self._emit_attempt(
                            cycle=cycle,
                            role=target_role,
                            parent_index=parent_index,
                            child_index=child_index,
                            attempt_index=attempt_index,
                            proposal=proposal,
                            candidate_skill=candidate_skill,
                            review=review,
                            planner_replay=planner_replay,
                            status="planner_replay_rejected",
                            reason=reason,
                            update_budget=candidate_update_budget,
                        )
                        retry_feedback.append(f"[planner_replay] {reason}")
                        continue
                prepared.append(
                    _PreparedCandidate(
                        child_index=child_index,
                        attempt_index=attempt_index,
                        proposal=proposal,
                        evidence=target_evidence,
                        skill_set=update.skill_set,
                        candidate_skill=candidate_skill,
                        review=review,
                        planner_replay=planner_replay,
                        update_budget=candidate_update_budget,
                    )
                )
                break
        return prepared, proposed_count

    def _retarget_evidence(
        self,
        *,
        evidence: EvidencePacket,
        role: Role,
        all_cases: Sequence[TraceCase],
        min_support_cases: int,
        min_support_groups: int,
    ) -> EvidencePacket | None:
        """Map selected complete episodes onto the Planner role chosen by the model."""

        role = Role(role)
        if evidence.role is role:
            support_by_id = {
                case.case_id: case
                for case in evidence.cases
                if case.case_id in evidence.support_ids
            }
            if len(support_by_id) < min_support_cases:
                return None
            if (
                len(
                    {
                        case.source_group or case.case_id
                        for case in support_by_id.values()
                    }
                )
                < min_support_groups
            ):
                return None
            return evidence
        selected_by_id = {case.case_id: case for case in evidence.cases}
        support_episodes = tuple(
            dict.fromkeys(
                selected_by_id[case_id].episode_id
                or selected_by_id[case_id].case_id
                for case_id in evidence.support_ids
            )
        )
        contrast_episodes = tuple(
            dict.fromkeys(
                selected_by_id[case_id].episode_id
                or selected_by_id[case_id].case_id
                for case_id in evidence.contrast_ids
            )
        )
        def representatives(
            episode_ids: Sequence[str],
            *,
            limit: int,
            label: str,
            excluded_groups: set[str] | None = None,
        ) -> tuple[TraceCase, ...]:
            selected: list[TraceCase] = []
            seen_episodes: set[str] = set()
            seen_groups = set(excluded_groups or ())
            episode_rank = {
                episode_id: index for index, episode_id in enumerate(episode_ids)
            }
            ordered = sorted(
                (
                    case
                    for case in all_cases
                    if case.role is role
                    and (case.episode_id or case.case_id) in episode_ids
                ),
                key=lambda case: (
                    episode_rank[case.episode_id or case.case_id],
                    hash_json(
                        {
                            "packet": evidence.signature,
                            "role": role.value,
                            "bucket": label,
                            "case_id": case.case_id,
                        }
                    ),
                    case.case_id,
                ),
            )
            for case in ordered:
                episode_id = case.episode_id or case.case_id
                group = case.source_group or case.case_id
                if episode_id in seen_episodes or group in seen_groups:
                    continue
                selected.append(case)
                seen_episodes.add(episode_id)
                seen_groups.add(group)
                if len(selected) >= limit:
                    break
            return tuple(selected)

        support = representatives(
            support_episodes,
            limit=self.evidence_builder.failure_size,
            label="failure",
        )
        support_groups = {
            case.source_group or case.case_id for case in support
        }
        contrasts = representatives(
            contrast_episodes,
            limit=self.evidence_builder.success_size,
            label="success",
            excluded_groups=support_groups,
        )
        bounded = self.evidence_builder.fit_detail_budget(support, contrasts)
        support_case_ids = {case.case_id for case in support}
        contrast_case_ids = {case.case_id for case in contrasts}
        support = tuple(
            case for case in bounded if case.case_id in support_case_ids
        )
        contrasts = tuple(
            case for case in bounded if case.case_id in contrast_case_ids
        )
        support_groups = {
            case.source_group or case.case_id for case in support
        }
        if len(support) < min_support_cases or not contrasts:
            return None
        if len(support_groups) < min_support_groups:
            return None
        cases = (*support, *contrasts)
        return EvidencePacket(
            role=role,
            cases=cases,
            support_ids=tuple(case.case_id for case in support),
            contrast_ids=tuple(case.case_id for case in contrasts),
            signature=hash_json(
                {
                    "source_signature": evidence.signature,
                    "target_role": role.value,
                    "episodes": sorted(
                        set(support_episodes) | set(contrast_episodes)
                    ),
                }
            )[:16],
        )

    def _search_score(
        self,
        evaluation: EvaluationResult,
        comparison: ComparisonResult,
    ) -> float:
        score = 0.0
        if comparison.local_preference is not None:
            score += self.config.local_preference_weight * comparison.local_preference
        if comparison.lookahead_preference is not None:
            score += self.config.lookahead_preference_weight * comparison.lookahead_preference
        return score

    @staticmethod
    def _matches_evidence_packet(
        proposal: SkillUpdateProposal,
        request: SkillUpdateRequest,
    ) -> bool:
        """Ensure injected/fake patchers cannot replace deterministic evidence."""
        if not proposal.edits:
            return True
        evidence = request.evidence
        return (
            proposal.diagnosis.support_ids == evidence.support_ids
            and proposal.diagnosis.contrast_ids == evidence.contrast_ids
            and dict(proposal.case_assessments) == evidence.case_assessments
        )

    def _passes_train_screen(
        self,
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> bool:
        """Avoid spending eval rollouts on a clearly regressed role candidate."""
        reference_metrics = reference.metrics
        candidate_metrics = candidate.metrics
        one_sample = 1.0 / max(reference_metrics.sample_count, 1)
        score_tolerance = self.config.train_score_drop_max_cases * one_sample
        reliability_tolerance = (
            self.config.train_reliability_tolerance_cases * one_sample
        )
        if (
            candidate_metrics.official_score
            < reference_metrics.official_score - score_tolerance
        ):
            return False
        if candidate_metrics.fatal_rate > reference_metrics.fatal_rate:
            return False
        if (
            candidate_metrics.invalid_action_rate
            > reference_metrics.invalid_action_rate + reliability_tolerance
        ):
            return False
        return self._within_call_regression(
            reference=reference,
            candidate=candidate,
        )

    @classmethod
    def _passes_strict_train_screen(
        cls,
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> bool:
        """Require a repair to remove every score and reliability regression."""

        reference_metrics = reference.metrics
        candidate_metrics = candidate.metrics
        if candidate_metrics.official_score < reference_metrics.official_score:
            return False
        if any(
            candidate_value > reference_value
            for candidate_value, reference_value in (
                (candidate_metrics.fatal_rate, reference_metrics.fatal_rate),
                (
                    candidate_metrics.invalid_action_rate,
                    reference_metrics.invalid_action_rate,
                ),
            )
        ):
            return False
        return cls._within_call_regression(
            reference=reference,
            candidate=candidate,
        )

    @staticmethod
    def _within_call_regression(
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> bool:
        reference_metrics = reference.metrics
        candidate_metrics = candidate.metrics
        one_sample = 1.0 / max(reference_metrics.sample_count, 1)
        for candidate_value, reference_value in (
            (
                candidate_metrics.observe_calls_per_sample,
                reference_metrics.observe_calls_per_sample,
            ),
            (
                candidate_metrics.watch_calls_per_sample,
                reference_metrics.watch_calls_per_sample,
            ),
        ):
            limit = max(reference_value * 1.25, one_sample)
            if candidate_value > limit:
                return False
        return True

    @staticmethod
    def _within_limited_regression(
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
        score_drop_max: float,
    ) -> bool:
        reference_metrics = reference.metrics
        candidate_metrics = candidate.metrics
        if (
            candidate_metrics.official_score
            < reference_metrics.official_score - score_drop_max
        ):
            return False
        one_sample = 1.0 / max(reference_metrics.sample_count, 1)
        if any(
            candidate_value > reference_value + one_sample
            for candidate_value, reference_value in (
                (candidate_metrics.fatal_rate, reference_metrics.fatal_rate),
                (
                    candidate_metrics.invalid_action_rate,
                    reference_metrics.invalid_action_rate,
                ),
            )
        ):
            return False
        return JointSkillCoordinator._within_call_regression(
            reference=reference,
            candidate=candidate,
        )

    def _eligible_provisional(
        self,
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> bool:
        if self.config.provisional_per_role <= 0:
            return False
        return self._within_limited_regression(
            reference=reference,
            candidate=candidate,
            score_drop_max=self.config.provisional_score_drop_max,
        )

    def _select_provisional(self, nodes: Sequence[BeamNode]) -> list[BeamNode]:
        by_skill = {node.skill_sha256: node for node in nodes}
        return sorted(
            by_skill.values(),
            key=lambda node: (
                node.evaluation.metrics.rank_key(),
                node.training_evaluation.metrics.rank_key(),
                node.search_score,
            ),
            reverse=True,
        )[: self.config.provisional_per_role]

    def _try_joint_provisional(
        self,
        *,
        cycle: int,
        active: SkillSet,
        beams: dict[Role, list[BeamNode]],
        provisional: dict[Role, list[BeamNode]],
    ) -> tuple[SkillSet, dict[Role, list[BeamNode]], bool, int]:
        if not provisional[Role.GLOBAL] or not provisional[Role.VIDEO]:
            return active, beams, False, 0
        global_node = provisional[Role.GLOBAL][0]
        video_node = provisional[Role.VIDEO][0]
        if (
            global_node.partner_sha256 != active.skill_sha256(Role.VIDEO)
            or video_node.partner_sha256 != active.skill_sha256(Role.GLOBAL)
        ):
            return active, beams, False, 0

        joint = SkillSet(
            global_skill=global_node.skill,
            video_skill=video_node.skill,
        )
        parent_training = self.training_evaluator.evaluate(
            skill_set=active,
            label=f"train-cycle-{cycle}-joint-parent",
        )
        parent_evaluation = self.selection_evaluator.evaluate(
            skill_set=active,
            label=f"eval-cycle-{cycle}-joint-parent",
        )
        joint_training = self.training_evaluator.evaluate(
            skill_set=joint,
            label=f"train-cycle-{cycle}-joint-provisional",
        )
        joint_evaluation = self.selection_evaluator.evaluate(
            skill_set=joint,
            label=f"eval-cycle-{cycle}-joint-provisional",
        )
        improved = self._improves_on_eval(
            reference=parent_evaluation,
            candidate=joint_evaluation,
        )
        reason = (
            "accepted: provisional Global+Video pair strictly improved eval"
            if improved
            else "rejected: provisional Global+Video pair did not strictly improve eval"
        )
        for node in (global_node, video_node):
            if node.proposal is not None:
                self._remember_evaluation(
                    node.role,
                    node.proposal,
                    reason=reason,
                    training_reference=parent_training,
                    training_candidate=joint_training,
                    evaluation_reference=parent_evaluation,
                    evaluation_candidate=joint_evaluation,
                )
        self._emit_joint_attempt(
            cycle=cycle,
            global_node=global_node,
            video_node=video_node,
            skill_set=joint,
            training_reference=parent_training,
            training_candidate=joint_training,
            evaluation_reference=parent_evaluation,
            evaluation_candidate=joint_evaluation,
            status="joint_accepted" if improved else "joint_rejected",
            reason=reason,
        )
        if not improved:
            return active, beams, False, 1

        for node in (global_node, video_node):
            if node.proposal is not None:
                self._remember(
                    node.role,
                    node.proposal,
                    "promoted as part of a jointly improving Global/Video pair; "
                    + self._split_delta(
                        "eval",
                        node.role,
                        parent_evaluation,
                        joint_evaluation,
                    ),
                    kind="promoted",
                )

        refreshed: dict[Role, list[BeamNode]] = {}
        for node in (global_node, video_node):
            comparison = self.training_evaluator.compare(
                role=node.role,
                reference=parent_training,
                candidate=joint_training,
            )
            committed = replace(
                node,
                partner_sha256=joint.skill_sha256(self._other(node.role)),
                training_evaluation=joint_training,
                evaluation=joint_evaluation,
                comparison=comparison,
                stale=False,
            )
            refreshed[node.role] = self._select_beam(
                [*beams[node.role], committed]
            )
        return joint, refreshed, True, 1

    def _attempt_repair(
        self,
        *,
        cycle: int,
        role: Role,
        parent_index: int,
        child_index: int,
        parent_node: BeamNode,
        candidate_skill_set: SkillSet,
        candidate_proposal: SkillUpdateProposal,
        candidate_training: EvaluationResult,
        candidate_comparison: ComparisonResult,
    ) -> _RepairResult | None:
        """Try one bounded train-only repair without exposing eval examples."""

        if self.config.repair_attempts == 0:
            return None
        paired = build_paired_feedback_cases(
            role=role,
            reference=parent_node.training_evaluation,
            candidate=candidate_training,
            comparison=candidate_comparison,
        )
        cases = select_repair_cases(
            paired_cases=paired,
            candidate_cases=candidate_training.cases,
            role=role,
            failure_limit=min(3, self.evidence_builder.failure_size),
            success_limit=min(2, self.evidence_builder.success_size),
        )
        regressions = [case for case in cases if case.outcome in {"fail", "partial"}]
        successes = [case for case in cases if case.outcome == "pass"]
        if not regressions or not successes:
            reason = (
                "repair unavailable: train-only paired feedback did not contain both a "
                "causal regression and a successful contrast"
            )
            self._remember(
                role,
                candidate_proposal,
                reason,
                kind="train_reliability",
            )
            return None

        evidence = self.evidence_builder.build_repair(
            role=role,
            cases=cases,
            cycle=cycle,
        )
        if evidence is None:
            self._remember(
                role,
                candidate_proposal,
                "repair unavailable: paired evidence could not fit the detail budget",
                kind="train_reliability",
            )
            return None

        current_skill = candidate_skill_set.get(role)
        repair_generation = parent_node.generation + 1
        repair_changed_budget = self._changed_char_budget(
            parent=current_skill,
            evidence=evidence,
            generation=repair_generation,
        )
        repair_budget_without_candidate = self._update_budget_audit(
            parent=current_skill,
            candidate=None,
            evidence=evidence,
            generation=repair_generation,
            allowed_changed_chars=repair_changed_budget,
        )
        retry_feedback: list[str] = []
        prepared_repair: tuple[
            SkillUpdateProposal,
            SkillSet,
            str,
            CandidateReview,
            int,
        ] | None = None
        for attempt_index in range(self.config.repair_attempts):
            request = SkillUpdateRequest(
                role=role,
                parent_skill=current_skill,
                evidence=evidence,
                cycle=cycle,
                candidate_number=1,
                candidate_count=1,
                seed=(
                    self.config.seed
                    + cycle * 10_000
                    + parent_index * 100
                    + child_index
                    + 50_000
                    + attempt_index
                ),
                max_chars=min(
                    self.updater.max_chars,
                    len(current_skill) + self.updater.max_net_growth,
                ),
                max_changed_chars=repair_changed_budget,
                changed_char_budgets={role: repair_changed_budget},
                generation=repair_generation,
                target_role_lock=role,
                optimizer_memory=(
                    *self.optimizer_memory.render(role),
                    *retry_feedback,
                ),
                parent_skill_set=candidate_skill_set,
                mode="repair",
                min_support_cases=1,
                min_support_groups=1,
            )
            if getattr(self.patcher, "workflow", "single_stage") == (
                "diagnose_then_patch"
            ):
                if candidate_proposal.diagnosis.target_role is not role:
                    self._remember(
                        role,
                        candidate_proposal,
                        "repair unavailable: frozen diagnosis role does not match "
                        "the candidate role",
                        kind="train_reliability",
                    )
                    return None
                repair_diagnosis = replace(
                    candidate_proposal.diagnosis,
                    support_ids=evidence.support_ids,
                    contrast_ids=evidence.contrast_ids,
                )
                proposals = tuple(
                    self.patcher.patch(  # type: ignore[attr-defined]
                        request,
                        repair_diagnosis,
                        audit_context={
                            "phase": "repair",
                            "seed_role": role.value,
                            "parent_index": parent_index,
                            "child_index": child_index,
                            "stage_attempt": attempt_index,
                        },
                    )
                )
            else:
                proposals = tuple(self.patcher.propose(request))
            if not proposals:
                repair_reason = (
                    "repair rejected: update did not satisfy the structured output "
                    "contract"
                )
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=None,
                    status="repair_invalid",
                    reason=repair_reason,
                    phase="repair",
                    update_budget=repair_budget_without_candidate,
                )
                retry_feedback.append(
                    "[format_static] The previous repair did not satisfy the JSON output contract."
                )
                continue
            proposal = proposals[0]
            if proposal.role is not role or not self._matches_evidence_packet(
                proposal,
                request,
            ):
                reason = (
                    "repair rejected: proposal altered the paired train evidence packet"
                )
                self._remember(role, proposal, reason, kind="format_static")
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=proposal,
                    status="repair_invalid",
                    reason=reason,
                    phase="repair",
                    update_budget=repair_budget_without_candidate,
                )
                retry_feedback.append(f"[format_static] {reason}")
                continue
            if not proposal.edits:
                reason = "repair made no safe change"
                self._remember(role, proposal, reason, kind="no_change")
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=proposal,
                    status="repair_no_change",
                    reason=reason,
                    phase="repair",
                    update_budget=self._update_budget_audit(
                        parent=current_skill,
                        candidate=current_skill,
                        evidence=evidence,
                        generation=repair_generation,
                        allowed_changed_chars=repair_changed_budget,
                    ),
                )
                return None
            integrated_replace = (
                len(proposal.edits) == 1
                and proposal.edits[0].op is EditOp.REPLACE
                and proposal.edits[0].target == current_skill
            )
            if not integrated_replace:
                reason = (
                    "repair rejected: use one replace whose target is the complete "
                    "current Decision strategy"
                )
                self._remember(role, proposal, reason, kind="format_static")
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=proposal,
                    status="repair_invalid",
                    reason=reason,
                    phase="repair",
                    update_budget=repair_budget_without_candidate,
                )
                retry_feedback.append(f"[format_static] {reason}")
                continue

            update = self.updater.apply(
                candidate_skill_set,
                proposal,
                allowed_case_ids={case.case_id for case in request.cases},
                min_edit_evidence=1,
                max_changed_chars=request.max_changed_chars,
            )
            if not update.accepted:
                reason = (
                    "repair rejected: " + "; ".join(update.errors)
                    if update.errors
                    else "repair made no change"
                )
                self._remember(
                    role,
                    proposal,
                    reason,
                    kind="format_static" if update.errors else "no_change",
                )
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=proposal,
                    status="repair_invalid" if update.errors else "repair_no_change",
                    reason=reason,
                    phase="repair",
                    update_budget=(
                        repair_budget_without_candidate
                        if update.errors
                        else self._update_budget_audit(
                            parent=current_skill,
                            candidate=current_skill,
                            evidence=evidence,
                            generation=repair_generation,
                            allowed_changed_chars=repair_changed_budget,
                        )
                    ),
                )
                retry_feedback.append(f"[format_static] {reason}")
                continue
            assert update.skill_set is not None
            repaired_skill = update.skill_set.get(role)
            review = CandidateReview(True)
            if self.reviewer is not None:
                review = self.reviewer.review(
                    role=role,
                    parent_skill=current_skill,
                    candidate_skill=repaired_skill,
                )
            if not review.passed:
                reason = "repair rejected by generality review: " + "; ".join(
                    review.reasons
                )
                self._remember(role, proposal, reason, kind="semantic_review")
                self._emit_attempt(
                    cycle=cycle,
                    role=role,
                    parent_index=parent_index,
                    child_index=child_index,
                    attempt_index=attempt_index,
                    proposal=proposal,
                    candidate_skill=repaired_skill,
                    review=review,
                    status="repair_review_rejected",
                    reason=reason,
                    phase="repair",
                    update_budget=self._update_budget_audit(
                        parent=current_skill,
                        candidate=repaired_skill,
                        evidence=evidence,
                        generation=repair_generation,
                        allowed_changed_chars=repair_changed_budget,
                    ),
                )
                return None
            prepared_repair = (
                proposal,
                update.skill_set,
                repaired_skill,
                review,
                attempt_index,
            )
            break

        if prepared_repair is None:
            return None
        (
            proposal,
            repaired_skill_set,
            repaired_skill,
            review,
            repair_attempt_index,
        ) = prepared_repair

        training = self._evaluate_role_candidate(
            self.training_evaluator,
            skill_set=repaired_skill_set,
            reference_skill_set=candidate_skill_set,
            changed_role=role,
            label=(
                f"train-cycle-{cycle}-{role.value}-parent-{parent_index}-"
                f"child-{child_index}-repair"
            ),
        )
        comparison = self.training_evaluator.compare(
            role=role,
            reference=parent_node.training_evaluation,
            candidate=training,
        )
        training = attach_paired_regressions(
            role=role,
            reference=parent_node.training_evaluation,
            candidate=training,
            comparison=comparison,
        )
        lost_candidate_gain = (
            training.metrics.official_score
            < candidate_training.metrics.official_score
        )
        if (
            lost_candidate_gain
            or is_repairable_candidate(parent_node.training_evaluation, training)
            or not self._passes_strict_train_screen(
                reference=parent_node.training_evaluation,
                candidate=training,
            )
        ):
            reason = (
                "repair rejected: it lost the candidate gain, retained a paired train "
                "regression, or regressed against the committed parent"
            )
            self._remember_evaluation(
                role,
                proposal,
                reason=reason,
                training_reference=parent_node.training_evaluation,
                training_candidate=training,
                comparison=comparison,
            )
            self._emit_attempt(
                cycle=cycle,
                role=role,
                parent_index=parent_index,
                child_index=child_index,
                attempt_index=repair_attempt_index,
                proposal=proposal,
                candidate_skill=repaired_skill,
                review=review,
                training_reference=parent_node.training_evaluation,
                training_candidate=training,
                status="repair_train_rejected",
                reason=reason,
                phase="repair",
                update_budget=self._update_budget_audit(
                    parent=current_skill,
                    candidate=repaired_skill,
                    evidence=evidence,
                    generation=repair_generation,
                    allowed_changed_chars=repair_changed_budget,
                ),
            )
            return None
        return _RepairResult(
            skill_set=repaired_skill_set,
            proposal=proposal,
            review=review,
            training_evaluation=training,
            comparison=comparison,
            update_budget=self._update_budget_audit(
                parent=current_skill,
                candidate=repaired_skill,
                evidence=evidence,
                generation=repair_generation,
                allowed_changed_chars=repair_changed_budget,
            ),
            attempt_index=repair_attempt_index,
        )

    def _select_beam(self, nodes: list[BeamNode]) -> list[BeamNode]:
        by_skill: dict[str, BeamNode] = {}
        for node in nodes:
            current = by_skill.get(node.skill_sha256)
            if current is None or node.rank_key() > current.rank_key():
                by_skill[node.skill_sha256] = node
        return sorted(by_skill.values(), key=lambda node: node.rank_key(), reverse=True)[
            : self.config.beam_size
        ]

    @staticmethod
    def _evaluate_role_candidate(
        evaluator: Evaluator,
        *,
        skill_set: SkillSet,
        reference_skill_set: SkillSet,
        changed_role: Role,
        label: str,
    ) -> EvaluationResult:
        role_evaluate = getattr(evaluator, "evaluate_role_candidate", None)
        if callable(role_evaluate):
            return role_evaluate(
                skill_set=skill_set,
                reference_skill_set=reference_skill_set,
                changed_role=changed_role,
                label=label,
            )
        return evaluator.evaluate(skill_set=skill_set, label=label)

    @staticmethod
    def _improves_on_eval(
        *,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> bool:
        """Require a real eval-score gain and no reliability regression."""
        if candidate.metrics.official_score <= reference.metrics.official_score:
            return False
        return all(
            candidate_value <= reference_value
            for candidate_value, reference_value in (
                (candidate.metrics.fatal_rate, reference.metrics.fatal_rate),
                (
                    candidate.metrics.invalid_action_rate,
                    reference.metrics.invalid_action_rate,
                ),
            )
        )

    @staticmethod
    def _eval_rank_key(evaluation: EvaluationResult) -> tuple[float, ...]:
        metrics = evaluation.metrics
        return (
            metrics.official_score,
            -metrics.fatal_rate,
            -metrics.invalid_action_rate,
        )

    def _remember_evaluation(
        self,
        role: Role,
        proposal: SkillUpdateProposal,
        *,
        reason: str,
        training_reference: EvaluationResult,
        training_candidate: EvaluationResult,
        evaluation_reference: EvaluationResult | None = None,
        evaluation_candidate: EvaluationResult | None = None,
        comparison: ComparisonResult | None = None,
    ) -> None:
        parts = [reason]
        parts.append(
            self._split_delta(
                "train",
                role,
                training_reference,
                training_candidate,
            )
        )
        if evaluation_reference is not None and evaluation_candidate is not None:
            parts.append(
                self._split_delta(
                    "eval",
                    role,
                    evaluation_reference,
                    evaluation_candidate,
                )
            )
        if comparison is not None and comparison.misalignment_ids:
            self._remember(
                role,
                proposal,
                "Pairwise comparison found "
                f"{len(comparison.misalignment_ids)} role-local improvement(s) whose "
                "immediate downstream effect regressed.",
                kind="misalignment",
            )
        self._remember(
            role,
            proposal,
            "; ".join(parts),
            kind=self._evaluation_memory_kind(
                training_reference=training_reference,
                training_candidate=training_candidate,
                evaluation_reference=evaluation_reference,
                evaluation_candidate=evaluation_candidate,
            ),
        )

    @staticmethod
    def _evaluation_memory_kind(
        *,
        training_reference: EvaluationResult,
        training_candidate: EvaluationResult,
        evaluation_reference: EvaluationResult | None,
        evaluation_candidate: EvaluationResult | None,
    ) -> str:
        if evaluation_reference is not None and evaluation_candidate is not None:
            reference = evaluation_reference.metrics
            candidate = evaluation_candidate.metrics
            if (
                candidate.official_score < reference.official_score
                or candidate.fatal_rate > reference.fatal_rate
                or candidate.invalid_action_rate > reference.invalid_action_rate
            ):
                return "eval_regression"
            if candidate.official_score == reference.official_score:
                return "eval_tie"
            return "eval_result"
        reference = training_reference.metrics
        candidate = training_candidate.metrics
        if any(
            candidate_value > reference_value
            for candidate_value, reference_value in (
                (candidate.fatal_rate, reference.fatal_rate),
                (candidate.invalid_action_rate, reference.invalid_action_rate),
                (
                    candidate.observe_calls_per_sample,
                    reference.observe_calls_per_sample,
                ),
                (
                    candidate.watch_calls_per_sample,
                    reference.watch_calls_per_sample,
                ),
            )
        ):
            return "train_reliability"
        return "train_result"

    @staticmethod
    def _split_delta(
        label: str,
        role: Role,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> str:
        ref = reference.metrics
        cand = candidate.metrics
        wins, losses = JointSkillCoordinator._paired_flips(
            role,
            reference,
            candidate,
        )
        return (
            f"{label}: score {cand.official_score - ref.official_score:+.4f}, "
            f"wins/losses {wins}/{losses}, "
            f"fatal {cand.fatal_rate - ref.fatal_rate:+.4f}, "
            f"invalid {cand.invalid_action_rate - ref.invalid_action_rate:+.4f}, "
            f"observe {cand.observe_calls_per_sample - ref.observe_calls_per_sample:+.2f}, "
            f"watch {cand.watch_calls_per_sample - ref.watch_calls_per_sample:+.2f}"
        )

    @staticmethod
    def _paired_flips(
        role: Role,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> tuple[int, int]:
        def scores(result: EvaluationResult) -> dict[str, float]:
            by_group: dict[str, float] = {}
            for case in result.cases:
                if case.role is not role or case.official_score is None:
                    continue
                group = case.source_group or case.case_id
                by_group[group] = case.official_score
            return by_group

        reference_scores = scores(reference)
        candidate_scores = scores(candidate)
        shared = set(reference_scores) & set(candidate_scores)
        wins = sum(candidate_scores[key] > reference_scores[key] for key in shared)
        losses = sum(candidate_scores[key] < reference_scores[key] for key in shared)
        return wins, losses

    def _emit_attempt(
        self,
        *,
        cycle: int,
        role: Role,
        parent_index: int,
        child_index: int,
        attempt_index: int,
        proposal: SkillUpdateProposal | None,
        status: str,
        reason: str,
        candidate_skill: str = "",
        review: CandidateReview | None = None,
        planner_replay: PlannerReplayReview | None = None,
        training_reference: EvaluationResult | None = None,
        training_candidate: EvaluationResult | None = None,
        evaluation_reference: EvaluationResult | None = None,
        evaluation_candidate: EvaluationResult | None = None,
        phase: str = "proposal",
        update_budget: Mapping[str, int | None] | None = None,
    ) -> None:
        if self.on_attempt is None:
            return
        identity = {
            "cycle": cycle,
            "role": role.value,
            "parent_index": parent_index,
            "child_index": child_index,
            "attempt_index": attempt_index,
            "phase": phase,
            "proposal": proposal.to_dict() if proposal is not None else None,
            "status": status,
            "reason": reason,
        }
        self.on_attempt(
            {
                "attempt_id": "attempt-" + hash_json(identity)[:16],
                **identity,
                "candidate_skill": candidate_skill,
                "candidate_skill_sha256": sha256_text(candidate_skill),
                "review": (
                    {
                        "passed": review.passed,
                        "reasons": list(review.reasons),
                    }
                    if review is not None
                    else None
                ),
                "planner_replay": (
                    planner_replay.to_dict()
                    if planner_replay is not None
                    else None
                ),
                "update_budget": (
                    dict(update_budget) if update_budget is not None else None
                ),
                "train": self._evaluation_pair_dict(
                    training_reference,
                    training_candidate,
                ),
                "eval": self._evaluation_pair_dict(
                    evaluation_reference,
                    evaluation_candidate,
                ),
            }
        )

    def _emit_joint_attempt(
        self,
        *,
        cycle: int,
        global_node: BeamNode,
        video_node: BeamNode,
        skill_set: SkillSet,
        training_reference: EvaluationResult,
        training_candidate: EvaluationResult,
        evaluation_reference: EvaluationResult,
        evaluation_candidate: EvaluationResult,
        status: str,
        reason: str,
    ) -> None:
        if self.on_attempt is None:
            return
        payload = {
            "cycle": cycle,
            "role": "joint",
            "global_proposal": (
                global_node.proposal.to_dict()
                if global_node.proposal is not None
                else None
            ),
            "video_proposal": (
                video_node.proposal.to_dict()
                if video_node.proposal is not None
                else None
            ),
            "candidate_skill_set_hash": skill_set.skill_set_hash(),
        }
        self.on_attempt(
            {
                "attempt_id": "attempt-" + hash_json(payload)[:16],
                **payload,
                "status": status,
                "reason": reason,
                "global_skill": skill_set.global_skill,
                "video_skill": skill_set.video_skill,
                "train": self._evaluation_pair_dict(
                    training_reference,
                    training_candidate,
                ),
                "eval": self._evaluation_pair_dict(
                    evaluation_reference,
                    evaluation_candidate,
                ),
            }
        )

    @staticmethod
    def _evaluation_pair_dict(
        reference: EvaluationResult | None,
        candidate: EvaluationResult | None,
    ) -> dict[str, object] | None:
        if reference is None or candidate is None:
            return None
        return {
            "reference": reference.metrics.to_dict(),
            "candidate": candidate.metrics.to_dict(),
            "candidate_reused_sample_ids": list(candidate.reused_sample_ids),
        }

    def _remember(
        self,
        role: Role,
        proposal: SkillUpdateProposal,
        reason: str,
        *,
        kind: str = "feedback",
    ) -> None:
        reusable_by_outcome = {
            "eval_regression": (
                "Do not retry this hypothesis by paraphrasing it. A future update must "
                "materially narrow its Runtime-visible trigger."
            ),
            "promoted": (
                "Preserve the Runtime-visible boundary that produced this gain when "
                "testing later hypotheses."
            ),
            "train_reliability": (
                "A future update may keep the useful direction only if it removes the "
                "new reliability or action-cost regression."
            ),
            "misalignment": (
                "Prefer a causal role-local change whose local effect agrees with its "
                "immediate downstream effect."
            ),
            "semantic_review": (
                "Narrow the rule to the target role's Runtime-visible state and preserve "
                "the fixed action and evidence boundaries."
            ),
            "planner_replay": (
                "A future update must change the supported Planner states without making "
                "valid states invalid or disturbing successful preservation cases."
            ),
            "eval_tie": (
                "Do not lengthen the strategy in the same direction without a distinct, "
                "measurable behavior change."
            ),
            "no_change": (
                "Do not force an edit when the available failures do not establish one "
                "shared Planner-controllable rule."
            ),
        }
        if kind not in reusable_by_outcome:
            return
        diagnosis = proposal.diagnosis
        fallback_hypothesis = (
            f"{diagnosis.failure_source} attribution targeting the "
            f"{Role(role).value} Planner."
        )
        case_ids = (
            *proposal.case_assessments,
            *diagnosis.support_ids,
            *diagnosis.contrast_ids,
        )
        edit_fragments = tuple(
            fragment
            for edit in proposal.edits
            for fragment in (edit.target, edit.content)
            if fragment
        )
        hypothesis = sanitize_optimizer_text(
            diagnosis.expected_behavior_change or diagnosis.pattern,
            fallback=fallback_hypothesis,
            forbidden_case_ids=case_ids,
            forbidden_fragments=edit_fragments,
        )
        generic_effects = {
            "semantic_review": "The generality reviewer rejected the candidate.",
            "planner_replay": "Planner replay rejected the candidate.",
            "no_change": "The optimizer returned no change because attribution was unsafe.",
        }
        observed_effect = sanitize_optimizer_text(
            generic_effects.get(kind, reason),
            fallback=f"The candidate ended with {kind}.",
            forbidden_case_ids=case_ids,
            forbidden_fragments=edit_fragments,
        )
        hypothesis_key = optimizer_hypothesis_key(
            role=role,
            failure_source=diagnosis.failure_source,
            expected_behavior_change=diagnosis.expected_behavior_change,
        )
        self.optimizer_memory.add(
            OptimizerLesson(
                role=role,
                outcome=kind,
                hypothesis=hypothesis,
                observed_effect=observed_effect,
                reusable_lesson=reusable_by_outcome[kind],
                hypothesis_key=hypothesis_key,
            )
        )

    @staticmethod
    def _other(role: Role) -> Role:
        return Role.VIDEO if role is Role.GLOBAL else Role.GLOBAL


__all__ = [
    "BeamNode",
    "CoordinatorProgress",
    "Evaluator",
    "EvolutionResult",
    "EvolutionStep",
    "JointSkillCoordinator",
    "SearchConfig",
    "SkillPatcher",
]
