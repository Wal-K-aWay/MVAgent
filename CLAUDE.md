# MVAgent Skill 自进化

MVAgent 多智能体架构已经冻结（实现与基线实验均已完成）。当前主线是 GlobalAgent 与 VideoAgent 的
**免训练 skill 自进化**：从空库出发，为两个 skill 库各进化出一批 skill，让系统针对不同类型的问题选到
有针对性的 skill，更合理地选择 action 和参数，从而提高准确率。Actor 权重始终不变，只改 skill 文本。

- 主线代码：`src/skill_evolution/`（进化算法），`src/mvagent/skills/`（运行时 skill 加载与选择）。
- 入口：`scripts/run_skill_evolution.py --mode train|evaluate`；配置在 `configs/skill_evolution/`。

## 按需阅读

- 做 Modal、GPU、数据准备、模型服务相关工作前：使用 `mvagent-environment` skill（本地，不入 git）。
- 查看当前进度、开放缺口、历史结论时：读 `.claude/status.md`（本地笔记，不入 git）。
- 设计 split、解读分数、按题型分析轨迹或 skill 效果时：读 `.claude/benchmarks.md`（三个 benchmark 的题型、答案格式、
  评分与聚合口径、基线分数、现有 split；本地，不入 git）。
- 修改或新建某个进化算法前：读该算法目录下的 `README.md`（`src/skill_evolution/algorithms/alternating/global/{adaptor,cluster,cluster_v2}/`）。
- 编写或修订 skill 卡片前：读 `src/skill_evolution/infra/global_skill_specification.md`；
  涉及检索、Selector 或注入细节时读 `src/mvagent/skills/README.md`。
- 借鉴外部 skill 进化方法时：读 `reference/SURVEY.md`（`reference/` 下是相关仓库的浅克隆，不入 git）。
- 跑或解读端到端（E2E）基线前：读 `eval/e2e_eval/README.md`（统一入口 `eval/e2e_eval/run.py`；每次调用的帧数上限 `--frames`
  默认 512、最长边 `--max-side` 默认 448，其余与官方代码一致）。

## 术语

- **Train**：optimizer 可以读取轨迹的数据。**Cal**：只用于候选打分和筛选的数据。
  **Gate**：用于正式接受候选库的数据。**Test**：只用于独立评估的数据。
- **公开轨迹**：GlobalAgent 视角下的问题、action、参数和返回报告（VideoAgent 内部轨迹按角色单独投影）。
- **整库评估**：候选以完整 skill 库为单位跑完整 rollout，运行时自然选卡，按官方总分比较。
- **官方总分**：逐题评分与各 benchmark 官方评测一致；子集上按 task 分层估计全集官方总分（口径见 `.claude/benchmarks.md`）。
  pass/partial/fail 标签只用于给 optimizer 选样例和做逐题对比，不进入总分。
- **冻结源码**：每次运行开始时保存的源码与配置快照；resume 只用该快照。

## 硬性规则

- optimizer 的输入只包含 Train 的公开轨迹；Gate 和 Test 的细节只用于接受判定与报告。
- 候选只做整库评估；接受规则只看官方总分，不加入成本或步数目标。
- 原始 rollout 先落盘再评分；Judge 失败直接报错（不记为零分）。
- 复用过的开发数据称为"开发集"，结论要区分"已测到的"和"尚不能声称的"。
- 凭据（`BIGMODEL_API_KEY`、`DEEPSEEK_API_KEY`）只从环境变量或 Modal Secret 读取。
- 计算与模型推理都放在 Modal 上；使用 GPU 时，Modal app 名统一为 `wxu-sglang-baseline-gpu-test-*`，
  GPU 型号默认 `H200`（除非用户明确指定其他型号）。

## 工程原则

- 过时的代码和配置直接删除，不加兼容层、迁移或 fallback。
- 选择满足当前需求的最简实现；分层但保持浅；先跑通最小端到端，再叠加功能。
- 先复用项目已有能力和成熟库，再考虑新增依赖或自己实现。
- 选择长期可维护的方案。

## MVAgent 架构（冻结，供实验设计参考）

- 一个 **GlobalAgent** 加上每个视频一一对应的 **VideoAgent**：`src/mvagent/engine.py` 负责编排（Global 循环、
  动作执行、终止性回答），`agents/{global_agent,video_agent}/` 下各有 `agent.py`、`prompts.py`、`schema.py`、`memory.py`；
  共享模型层在 `src/models/`。单独跑推理的入口是 `eval/agent_eval/run.py`。
- **GlobalAgent** 接收问题和视频（只看到 video_id 与时长），每步输出 `reason/action/parameters`：
  - `analyze_videos`：并发调用若干 VideoAgent，每个视频给一条 instruction；
  - `watch_videos`：直接观看若干视频的指定片段并做比较；
  - `answer`：参数为空，由 Runtime 把问题和公开 History 交给独立回答器生成答案。
- **VideoAgent** 接收 instruction，返回对它的回应报告：
  - `observe`：给出观察内容（what）、有序的起止时间段和 FPS，有针对性地观看；
  - `finish`：若干轮观察后提交报告（至少要有一次成功观察）。
- **信息边界**：
  - VideoAgent 对 GlobalAgent 是黑盒：输入 instruction，输出报告。
  - VideoAgent 只看到自己的 instruction 和自己此前被调用时的内部轨迹（action+参数+结果）。
  - 达到步数上限时，Runtime 用已保留的证据做终止性总结。
- **Skill 运行时**：
  - 两个库都是 schema_version 3 的 JSON，每张卡为 `meta={id, role, stages}` + `when_to_use` + `strategy`，
    合计不超过 1200 words。
  - 选卡流程：按 role/stage 过滤；候选超过 8 张时，BM25 与 embedding 各取 8 张，用 RRF 融合成 8 张；
    Selector LLM 根据候选的 `when_to_use` 和本题输入，最多选一张，也可以不选。
  - 只把选中卡片的 `strategy` 注入 Actor。Global 在一道题内、Video 在一次请求内沿用首次选择。
  - Selector 默认用 Actor 同一个模型；`when_to_use` 只用于检索和选卡，执行所需的前提和排除条件要写进 `strategy`。
- **基线设置**：Actor Qwen3.5-35B-A3B，temperature 0，thinking 关闭，2048 输出 token，512 帧，
  Global/Video 各最多 5 步。基线分数见 `.claude/benchmarks.md`。
- **进化实验的运行时**（`configs/skill_evolution/runtime/dynamic_35b_embedding.yaml`）：Global 和 Video 共用同一个库文件，
  按 `meta.role` 区分；进化时由算法替换成当前候选库（runtime 配置中的 `dynamic-v003` 路径会被覆盖）。
  不传 `--skills` 时两类卡都为空，Video 卡保持不变（为空，或为 `--skills` 初始库中的 Video 卡）。

## 进化算法现状

`src/skill_evolution/algorithms/alternating/global/` 下已注册三个 Global 算法：`global-skilladaptor-v1`（adaptor）、
`global-cluster-v1`（cluster）、`global-cluster-v2`（cluster_v2，显式 Train/Cal/Gate）。
新方案 `global-scope-v1`（`scope/`，以运行时 Selector 的选择给题目分组，按选中题上的实测净收益迭代）目前只有设计文档 `scope/docs/design.md`，尚未实现。
`algorithms/alternating/video/` 尚未实现；目前 Video skill 冻结，Global/Video 交替调度也未实现。
共享基础设施在 `infra/`（数据划分、rollout、评分、轨迹投影、不可变库与持久化）；Runtime 不依赖 optimizer。

## 完成标准

- **代码改动**：`python3 -m compileall -q src scripts eval/agent_eval demo.py` 通过（Lightsail 本机即可，约 1 s）；
  涉及模型调用的改动，还要在 Modal 上跑一个小规模冒烟实验，并贴出实际输出作为证据。
- **一次实验**完成时应具备：
  - 冻结源码快照，以及 commit、split、skill 库哈希、模型/Judge 与推理配置；
  - 原始 rollout 与评分结果；
  - 主指标（CrossVid 报十类任务 macro）与有效样本数；
  - 更新后的 `.claude/status.md`，写明结论、限制和下一步。
- **文档同步**：改动使本文件、`.claude/rules/`、`mvagent-environment` skill、`.claude/benchmarks.md` 或 `.claude/status.md` 失准时，
  在同一工作项内更新。每次会话都需要的规则写在本文件；只在编辑特定路径时需要的规则写在 `.claude/rules/`，
  用 `paths:` 限定范围。
