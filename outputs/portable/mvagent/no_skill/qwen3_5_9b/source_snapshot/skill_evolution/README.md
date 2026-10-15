# MVAgent offline Skill evolution

`skill_evolution` is the offline optimization package beside the online
`mvagent` Runtime. The online answer path never imports this package, scans
candidates, or changes published Skill files.

```text
models <- mvagent
models <- skill_evolution -> frozen mvagent Runtime / benchmark scorers
mvagent Runtime -X-> skill_evolution
```

## Canonical implementation

The current operator uses the fixed upstream
[Microsoft SkillOpt](https://github.com/microsoft/SkillOpt) `ReflACTTrainer`
directly. The dependency is pinned to package `0.2.0`, commit
`e7014cd18a18e11e6f6c10b897f7a009960d2e1b`, in
`requirements-skill-evolution.txt`.

Install the offline-only dependency in the experiment environment with
`pip install -r requirements-skill-evolution.txt`; it is not required by the
online MVAgent answer path.

MVAgent does not reimplement SkillOpt's optimization loop. In particular, the
following mechanisms remain owned and executed by the stock Trainer:

1. split trajectories into failure and success pools;
2. reflect over every minibatch;
3. hierarchically merge failure patches and success patches independently;
4. perform the failure-first final merge;
5. rank edits and apply the scheduler-selected top-L patch;
6. evaluate the candidate on the frozen selection split and retain rejected
   steps in the upstream buffer;
7. compare adjacent epochs on the same tasks and write the protected Slow
   Update guidance block.

`src/skill_evolution/skillopt/adapter.py` is the only project module allowed to
import `skillopt`. It uses only the public `flatten_config`,
`BaseDataLoader` / `BatchSpec`, `EnvAdapter`, and `ReflACTTrainer` interfaces.
No project module calls the upstream Reflect, Merge, Ranking, Apply, scheduler,
Gate, or Slow Update helpers by itself.

The old `strategy/`, `orchestration/`, and local `prompts/` implementation is
retained only as a historical experimental comparison and for reusable neutral
contracts such as `SkillSet`, trajectory projection, benchmark scoring, and the
MVAgent promotion Gate. The current operator does not run the old Patcher,
EvidencePacket, reviewer, Planner replay, optimizer memory, custom Beam, repair,
or pairwise search loop.

## Multi-Agent adaptation

Upstream SkillOpt optimizes one Skill string. MVAgent therefore wraps complete
Trainer runs in a small block-coordinate scheduler:

```text
current (Global Skill, Video Skill)
  |
  +-- Global role session
  |     target = Global Skill
  |     frozen partner = Video Skill
  |     stock ReflACTTrainer runs all epochs, updates, gates, and Slow Update
  |     MVAgent complete-system Eval Gate accepts or rejects the result
  |
  +-- Video role session
        target = Video Skill
        frozen partner = the accepted current Global Skill
        stock ReflACTTrainer runs all epochs, updates, gates, and Slow Update
        MVAgent complete-system Eval Gate accepts or rejects the result
```

The partner is immutable for the **entire** role session, not merely one
minibatch or one epoch. This matters because Slow Update compares adjacent
epochs: the comparison would be invalid if the other Agent changed between
them. A role change is allowed only after the completed Trainer session and the
outer MVAgent Gate.

The default order is `global -> video`; `coordination.rounds` may repeat that
two-session schedule. At each boundary the coordinator atomically records the
committed two-role `SkillSet`. A rejected candidate leaves the current SkillSet
unchanged before the next role starts.

## Data and evidence boundary

Only two disjoint partitions are used:

- **Train** supplies update rollouts to SkillOpt reflection and Slow Update.
- **Eval** is the upstream selection split and the outer complete-system
  promotion boundary.

There is no active Test split. `evaluation.eval_test` must be `false`.

For every candidate, `MVAgentRoleRolloutBackend` runs the complete MVAgent
question from the beginning and scores the final answer with the configured
benchmark scorer. It then projects the result to the target role:

- Global receives one question-level trajectory containing only its public
  question, video inventory, public History, decisions, results, and answer.
- Video receives the invoked same-video Planner runs, including their local
  instruction, Memory, Observe/Finish decisions, and local results. Multiple
  requests in one question are joined as one target-role training record, but
  this offline join does not change what an online VideoAgent can see.
- A question that never invokes the target Video Planner still contributes its
  complete-system selection score, but does not create a fake Video
  `conversation.json` for reflection.

The rendered role trajectory is stored as the assistant content in upstream
`conversation.json`. SkillOpt then applies its standard `Trajectory` wrapper,
including the task, task type, failure reason, step count, optional hidden
reference, target system Prompt, and conversation. MVAgent does not patch this
formatter or any upstream optimization Prompt.

The official normalized sample score is returned unchanged as SkillOpt's soft
score. The MVAgent adapter derives the binary reflection label by normalized
task type:

- `choice` and `ordering`: success only when exactly correct;
- `temporal_localization`: success when interval IoU is at least `0.5`;
- `open_qa`: success when at least two thirds of the Judge scoring points have
  `correctness: true`.

OpenQA coverage flags and its aggregate coverage/correctness soft score do not
determine reflection success. A qualifying temporal/OpenQA trajectory can
therefore enter the success reflection pool while retaining a soft score below
`1.0`. This binary label is SkillOpt's `hard` field: it separates the
success/failure reflection pools and supplies Slow Update's hard outcome
categories. The canonical upstream selection Gate still uses `gate_metric:
soft`; the label does not change the official soft score, benchmark
aggregation, or complete-system MVAgent Gate.
The upstream SkillOpt implementation and Prompts remain unchanged. Global
Train receives reference text through SkillOpt's separate Hidden Reference
field. Video Train receives no answer/GT text because a question-level answer
is not a valid same-video Planner reference; it receives the complete-system
score and its own local trajectory instead. Eval answers are not exposed to
the optimizer.

Runtime-owned terminal Answer/Finish calls are excluded from the role Planner
trajectory because their fixed blocks are not controlled by either planning
Skill. The final answer/reason or Video summary remains visible as output.
Ordinary Planner-selected `answer` and `finish` actions are unchanged.

## Package layout

```text
skill_evolution/
|-- skillopt/
|   |-- adapter.py      # only import boundary to the upstream package
|   |-- backend.py      # complete MVAgent rollout -> target-role result
|   |-- config.py       # validates the canonical upstream recipe
|   |-- coordinator.py  # complete Global/Video role-session schedule
|   `-- engine.py       # composition and complete-system Eval Gate
|-- benchmarks/         # CrossVid, CVBench, MVU-Eval adapters and scorers
|-- evaluation/         # split, rollout cache, projection, and MVAgent Gate
|-- operators/          # frozen Runtime execution
|-- strategy/           # shared SkillSet/trajectory contracts; legacy optimizer
|-- orchestration/      # legacy comparison implementation
`-- prompts/            # OpenQA Judge plus legacy comparison Prompts
```

The two current operator scripts import `SkillOptEvolutionConfig` and
`SkillOptEvolutionEngine`:

- `scripts/run_multibench_skill_evolution.py`
- `scripts/run_crossvid_choice_skill_evolution.py`

They do not construct the historical `SkillEvolutionEngine`.

## Configuration

The canonical mixed-benchmark profile is
`configs/skill_evolution/skillopt_multibench_35ba3b_deepseek.yaml`.
Its `skillopt` mapping is passed as a structured configuration to the upstream
package, which remains responsible for flattening and consuming it.

```yaml
runtime:
  mvagent_config: configs/local_qwen35_35b_a3b_vllm_deepseek_optimizer_minimax_judge_gpu6.yaml
  output_dir: outputs/skill_evolution/skillopt_multibench_35ba3b_deepseek
  cache_dir: outputs/skill_evolution/skillopt_multibench_35ba3b_deepseek/cache

skillopt:
  train:
    num_epochs: 4
    # 0 is a sentinel; the adapter supplies the frozen role-eligible pool.
    train_size: 0
    batch_size: 40
    accumulation: 1
  gradient:
    minibatch_size: 8
    merge_batch_size: 8
    analyst_workers: 16
  optimizer:
    learning_rate: 4
    min_learning_rate: 2
    lr_scheduler: cosine
    lr_control_mode: fixed
    skill_update_mode: patch
    use_slow_update: true
    slow_update_samples: 20
    slow_update_gate_with_selection: true
  evaluation:
    use_gate: true
    gate_metric: soft
    sel_env_num: 70
    eval_test: false

coordination:
  rounds: 1
  role_order: [global, video]

gate:
  required_references:
    eval: [parent]
```

Canonical validation deliberately rejects settings that bypass the required
SkillOpt mechanisms: fewer than two epochs, non-patch updates, autonomous
learning-rate control, disabled Slow Update, disabled selection Gate, or an
active Test split.

Set optimizer credentials only through the environment; never store them in
the YAML. For the supplied DeepSeek profile:

```bash
export OPTIMIZER_AZURE_OPENAI_API_KEY='<your-key>'
```

The experiment scripts still require their benchmark dataset roots and frozen
Train/Eval manifest arguments; use `--help` for the exact operator-specific
paths.

## Selection and promotion

There are two nested but distinct gates:

1. the **upstream SkillOpt selection Gate** operates inside one frozen role
   session and determines that session's `best_skill.md` and
   `runtime_state.json`;
2. the **MVAgent complete-system Eval Gate** compares the resulting two-role
   SkillSet against its role-session parent after the Trainer has finished.

The outer gate requires a strict official Eval-score improvement in addition
to the configured fatal, invalid-action, bucket, Observe, and watch-call
guardrails. An Eval tie is not accepted. The final run report evaluates the
committed SkillSet on both Train and Eval and applies the same complete-system
promotion policy relative to the initial SkillSet. No result is automatically
published into `src/mvagent/skills/skill_sets/`.

Both gates intentionally use the same Eval partition. It is disjoint from
Train, but it is not a second held-out Test set. The stock Trainer selection
objective remains its upstream mean of per-sample hard/soft scores. For the
mixed-benchmark operator, the outer MVAgent Gate additionally applies the
configured dataset/task macro aggregator as the final complete-system
guardrail.

## Artifacts and resume

```text
<output_dir>/
|-- skillopt_sessions/
|   |-- global/<session_identity>/  # stock Trainer artifacts
|   `-- video/<session_identity>/
|-- state/coordinator.json          # atomic role-boundary checkpoint
`-- audit/role_sessions/
    `-- session_NNNN.json           # outer Eval Gate evidence
```

Each SkillOpt adapter/coordinator session identity includes the role, target
parent hash, frozen partner hash, reflection-label policy, complete upstream
config, Train/Eval IDs, and run metadata; the official scorer identity remains
unchanged because official scores did not change. Different parents, partners,
or reflection policies cannot share
`skill_init`, output state, or resume files. Sessions created with the former
exact-score-only reflection policy are incompatible and must be started as a
new output run rather than resumed. Resume otherwise occurs only after an
atomically completed role boundary; interrupted state inside one Trainer run
remains owned by upstream SkillOpt.

## Verification boundary

`tests/test_skillopt_upstream_contract.py` pins the complete installed upstream
Python/Prompt tree in addition to behavior-critical source hashes, and exercises
one real blank-seed `ReflACTTrainer` run through failure/success minibatches,
hierarchical/final merge, ranking, scheduler/top-L, apply, an accepted and a
rejected selection step with rejected-edit buffer, and Slow Update; only the
external optimizer-model call is mocked. Adapter, backend, coordinator, and
engine tests cover deterministic
Train/Eval loading, target-role evidence boundaries, partner freezing,
role-boundary resume, Runtime Skill-size rejection, and complete-system Gate
acceptance. These checks are intended to fail if a dependency update silently
changes the optimization flow.

The fixed reference checkout and dependency policy are recorded in
`references/skills_self_evolve/SOURCE_MANIFEST.md`.
