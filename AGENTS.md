# MVAgent Skill 自进化

本文件是 Codex 与 Claude Code 共用的项目规范。机器资源约束、Modal 访问入口和长实验检查遵循全局 `AGENTS.md`；
本机只做编辑、git、日志查看与轻量脚本，依赖安装、完整测试、构建和模型推理在远端执行。

MVAgent 多智能体架构已经冻结。当前主线是 GlobalAgent 与 VideoAgent 的
**免训练 skill 自进化**：从空库出发，为两个 skill 库各进化出一批 skill，让系统针对不同类型的问题选到
有针对性的 skill，更合理地选择 action 和参数，从而提高准确率。Actor 权重始终不变，只改 skill 文本。

- 主线代码：`src/skill_evolution/`（进化算法），`src/mvagent/skills/`（运行时 skill 加载与选择）。
- 入口：`scripts/run_skill_evolution.py --mode train|evaluate`；配置在 `configs/skill_evolution/`。

## 按需阅读

- 做 Modal、GPU、数据准备、模型服务相关工作前：使用
  [mvagent-environment](.agents/skills/mvagent-environment/SKILL.md) skill。
  Codex 入口 `.agents/skills/mvagent-environment` 是指向 `.claude/skills/mvagent-environment` 的相对符号链接，
  两者共用同一份说明和 devbox 工具；skill 是本地配置，不入 git，换机器时需单独保留整个源目录。
  若 skill 未出现在当前会话列表，直接读取上述 `SKILL.md`；若链接目标缺失，先恢复本地 skill 再开展依赖它的远端操作。
  每次 Modal 工作前仍须经 `ssh modal-gpu` 读取该机 `~/.agents/skills/modal/SKILL.md`。
- 查看当前进度、开放缺口、历史结论时：读 `.claude/status.md`（本地笔记，不入 git）。
- 设计 split、解读分数、按题型分析轨迹或 skill 效果时：读 `.claude/benchmarks.md`（三个 benchmark 的题型、答案格式、
  评分与聚合口径、基线分数、现有 split；本地，不入 git）。
- 修改或新建某个进化算法前：读该算法目录下的 `README.md`（`src/skill_evolution/algorithms/alternating/global/{adaptor,cluster,cluster_v2,scope}/`）。
  涉及 scope 时还要读 [设计文档](src/skill_evolution/algorithms/alternating/global/scope/docs/design.md) 和
  [组件探针结果](src/skill_evolution/algorithms/alternating/global/scope/docs/probe_results.md)，区分已实现组件、实测结论与待实现循环。
- 编写或修订 skill 卡片前：读 `src/skill_evolution/infra/global_skill_specification.md`；
  涉及检索、Selector 或注入细节时读 `src/mvagent/skills/README.md`。
- 借鉴外部 skill 进化方法时：读 `reference/SURVEY.md`（`reference/` 下是相关仓库的浅克隆，不入 git）。
- 跑或解读端到端（E2E）基线前：读 `eval/e2e_eval/README.md`（统一入口 `eval/e2e_eval/run.py`；每次调用的帧数上限 `--frames`
  默认 512、最长边 `--max-side` 默认 448；帧一律以图片输入，视频之间用 `Video k:` 标签分隔、不给文件名；
  其余与官方代码一致，偏差清单见该 README）。

## 路径规则

修改下列目录时，先读取对应的局部 `AGENTS.md`；即使从仓库根目录启动会话，也要遵守其中的路径条件。

| 修改范围（相对仓库根目录） | 局部说明 |
|---|---|
| `src/skill_evolution/algorithms/**` | [算法规则](src/skill_evolution/algorithms/AGENTS.md) |
| `src/mvagent/skills/**` | [运行时 skill 规则](src/mvagent/skills/AGENTS.md) |

Prompt 与中文镜像同步的完整规则统一保存在 [.claude/rules/prompt-mirrors.md](.claude/rules/prompt-mirrors.md)。
其中的 `paths:` 保留给 Claude Code 使用；Codex 通过本节与局部 `AGENTS.md` 显式读取同一规则，不能把它当作已自动加载。
适用范围仍是 optimizer 的 `prompts/**`、`chinese_prompts/**`，运行时 `src/mvagent/skills/prompts.py` 和 `src/mvagent/skills/authored/**`。

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
- scope 方案只用 CrossVid 迭代，CVBench/MVU-Eval 留作最终 Test；不向 optimizer 提供 task 代号、题号或预设题型分类。
- 候选只做整库评估；接受规则只看官方总分，不加入成本或步数目标。
- 原始 rollout 先落盘再评分；Judge 失败直接报错（不记为零分）。
- 实验结果只存在 Modal 的 runs volume（`wxu-evolve-agent-runs-20261006`）；Lightsail 只放代码和 md 报告，不把结果拷回本地
  （查看与分析方法见 `mvagent-environment` skill）。
  用户2026-10-13明确授权的例外：三模型最终E2E回答、评分、Judge缓存与配套元数据可保存在
  `outputs/e2e/`供本地轻量分析；迁入文件须核对大小与SHA256，媒体/权重/冻结运行环境仍留Modal。
  用户2026-10-15追加授权将MVU官方指令移后复测的原始回答、评分和配套元数据归入同总目录的对应模型目录（文件名标识提示位置）及analysis/reports；同样核对大小/SHA256并保留Modal原件。
- 复用过的开发数据称为"开发集"，结论要区分"已测到的"和"尚不能声称的"。
- 凭据（`BIGMODEL_API_KEY`、`DEEPSEEK_API_KEY`）只从环境变量或 Modal Secret 读取。
- 计算与模型推理都放在 Modal 上；使用 GPU 时，Modal app 名统一为 `wxu-sglang-baseline-gpu-test-*`，
  GPU 型号默认 `H200`；用户已确定的 Qwen3.5 固定评测使用 `H100!:8`，配置见下文。

## GitHub 仓库与账号

- 本项目仓库：[Wal-K-aWay/MVAgent](https://github.com/Wal-K-aWay/MVAgent)。
  `origin` 的 fetch/push 地址均为 `https://github.com/Wal-K-aWay/MVAgent`；沿用此仓库，不另建仓库或自行更换 remote。
- 现有 `gh` 账号不属于用户，不得用它管理本项目；不修改、切换或退出原有 `gh` 账号。
  GitHub 仓库、PR、Issue 等操作统一使用 `gh-kw`，涉及 GitHub 远端的 Git 操作（clone/fetch/pull/push）统一使用 `gh-kw git ...`。
  本地查看、暂存等无远端访问的操作可使用普通 `git`。
- 工具位于 `~/.local/bin/gh-kw`，使用说明位于 `~/.local/share/gh-kw/README.md`；
  登录配置保存在 `~/.config/gh-kw/`，工具使用的 Git 全局配置为 `~/.config/gh-kw/gitconfig`，均与原有账号隔离。
  本 Linux 工具禁用共享系统凭据存储，token 以明文保存在专用目录中（目录权限 700，凭据文件权限 600）；
  不打印、提交或分享凭据，也不从原账号复制 token。
- 每次会话首次 GitHub 操作前，运行 `gh-kw api user --jq .login` 核对已登录账号为用户本人账号；
  仓库 owner 不作为登录用户名的推断依据。未登录或无仓库权限时，报告实际错误，不回退到原有 `gh` 账号。
  首次登录需用户通过浏览器授权：

  ```bash
  gh-kw auth login --hostname github.com --git-protocol https --web
  gh-kw api user --jq .login
  ```

- 对本项目操作时显式指定仓库，例如 `gh-kw repo view Wal-K-aWay/MVAgent`、
  `gh-kw pr list --repo Wal-K-aWay/MVAgent`。在本项目目录中推送使用 `gh-kw git push -u origin HEAD`；
  推送前核对 remote、当前分支和提交内容，提交只包含当前工作项，保留其他已有未提交改动。
  新建分支默认使用 `codex/` 前缀，用户明确指定名称时遵循用户要求。
- 账号隔离只适用于 GitHub HTTPS 凭据；保持 HTTPS remote，不使用依赖共享 SSH 密钥的地址。
  用户指定的提交作者为 `kww <2568256289@qq.com>`；新环境使用该身份配置 `gh-kw` 的专用 Git 设置。
  提交作者独立于登录账号，提交前核对 `gh-kw git config user.name` 和 `gh-kw git config user.email`；
  需要设置时使用用户提供的身份，通过 `gh-kw git config --local ...` 或 `gh-kw git config --global ...` 写入仓库或专用配置。
  不猜测作者姓名、邮箱，不修改原有 Git 全局配置。

### 自动提交与远端备份（默认执行）

- 用户已授权：对当前工作项的代码、配置及可共享文档，主动完成 Git 提交和 GitHub 推送，无需逐次询问。
  目标是服务器不可用时仍能从上述 GitHub 仓库恢复已推送的工作；仅本地提交不算完成备份。
- 每完成一个可独立恢复的改动单元就提交并推送；活跃编辑期间，距上次成功推送达到15分钟时，
  在下一个可执行命令的机会保存当前进展；结束回复、handoff 或等待长时间远端任务前，也检查并推送尚未备份的当前工作。
  没有新改动时不创建空提交，不重复推送。此规则依赖会话执行，不代表已配置无人值守定时备份。
- 未完成或尚未通过测试的工作可在工作分支创建 `WIP` 检查点，提交说明写明未完成部分及验证状态；
  不为备份在本机启动重负载测试，也不把备份成功描述为功能或实验已完成。
- 使用当前工作项的 `codex/` 分支（或用户指定分支）；备份不要求合并到 `main`，不自动合并或强推。
  共享工作区存在其他会话时，不擅自切换其分支；需要隔离时使用独立 worktree。
- 暂存前检查改动及未跟踪文件，按文件或改动块选择当前工作项的源码、配置和文档；
  不盲目执行 `git add .` / `git add -A`，不夹带其他已有改动，不提交凭据、数据、权重、生成结果或明确约定仅本地保存的笔记。
  发现其他尚未备份的重要源码时明确报告范围，不能因为当前工作项已推送就声称整个工作区都已备份。
- 提交后用 `gh-kw git push -u origin HEAD` 推送，并通过 `gh-kw git ls-remote --exit-code origin refs/heads/<当前分支>`
  核对远端分支的 commit SHA 与本地 `HEAD` 一致，才报告备份成功。
  最终回复简要注明已推送的分支、短 SHA，以及仍只保存在本机的相关改动或材料。
- 登录、权限、网络、提交作者身份或远端冲突阻止备份时，保留本地改动与已有提交，明确报告“尚未完成远端备份”、
  实际阻塞及下一动作；不回退到他人账号，不覆盖远端历史。阻塞排除后补推，不把失败当成成功。

## 工程原则

- **固定 seed**：本地 Qwen3.5 的 E2E/MVAgent 推理统一沿用已验收的 `seed=0`，不随日期或运行次数改变。
  新建抽样与打乱也默认用 `0`；已有 split、面板和冻结实验沿用原 manifest，不为统一 seed 重新抽题。
  记录时区分推理 seed 与数据抽样 seed；历史日期型 seed 是固定抽样值，不是模型每天换 seed。
- **复用一致性验收**：固定评测配置已通过的范围可直接复用，不要求每批或每天重复双遍/全矩阵验证。
  正式入口只保留一种配置，不使用配置版本编号；prefix cache 关闭。既有任务及 resume 保持各自冻结源码。
  保留配置与模型身份校验、输入哈希和 token 日志；只有相关权重、数值配置、依赖版本、硬件型号、并发方式、
  媒体预处理或调用路径改变，出现新差异/故障，或用户明确要求时，才对受影响部分做小规模复核。
  新题目或新日期本身不触发重复测试；有限样本通过仍不等于任意输入的绝对保证。
- 最终 `answer` 保留开放的非空字符串，不新增合法选项枚举或按 benchmark/task 硬编码答案格式的约束。
  由模型根据题意遵循输出格式；模型正常返回的格式偏差与基础设施运行故障分别记录。
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
  - `answer`：在同一次决策的 `parameters.answer` 中直接提交最终答案；Runtime 不再额外调用回答器。
- **VideoAgent** 接收 instruction，返回对它的回应报告：
  - `observe`：给出观察内容（what）、有序的起止时间段和 FPS，有针对性地观看；
  - `finish`：若干轮观察后提交报告（至少要有一次成功观察）。
- **信息边界**：
  - VideoAgent 对 GlobalAgent 是黑盒：输入 instruction，输出报告。
  - VideoAgent 只看到自己的 instruction 和自己此前被调用时的内部轨迹（action+参数+结果）。
  - 达到步数上限时，Global 复用决策接口并只允许 answer，沿用决策 System、公开 History 与选中策略提交终答；Video 用已保留的证据做终止性总结。
- **Skill 运行时**：
  - 两个库都是 schema_version 3 的 JSON，每张卡为 `meta={id, role, stages}` + `when_to_use` + `strategy`，
    合计不超过 1200 words。
  - 选卡流程：按 role/stage 过滤；候选超过 8 张时，BM25 与 embedding 各取 8 张，用 RRF 融合成 8 张；
    Selector LLM 根据候选的 `when_to_use` 和本题输入，最多选一张，也可以不选。
  - 只把选中卡片的 `strategy` 注入 Actor。Global 在一道题内、Video 在一次请求内沿用首次选择。
  - Selector 默认用 Actor 同一个模型；`when_to_use` 只用于检索和选卡，执行所需的前提和排除条件要写进 `strategy`。
- **固定评测方案**：后续三模型正式 E2E 与 MVAgent 按 [配置总表](configs/inference/README.md#固定评测方案) 执行，
  共用 `src/models/vlm/local/sync_server.py` 的 `qwen35-bf16-flashinfer-sync` profile；8×H100、BF16、每卡独立 TP1/DP1、并发1（池级DP=8），
  `seed=0`、temperature 0、thinking 关闭、FlashInfer GDN 和原生 GemmaRMSNorm。Agent 整题固定副本，默认记录实际 token 与输入哈希；
  prefix/MM processor cache关闭、正常解码KV开启，整题sticky routing；保留逐请求缓存计数审计，关闭prefix时为0。
  启动后续新实验前读取`.claude/status.md`，核对远端实际服务manifest的profile、prefix关闭及8个单卡worker；
  本地配置不能替代远端生效证据。已有任务及resume只用其冻结源码，新运行另建结果目录。
  名称清理不改写历史manifest；新客户端不得连接旧冻结服务，也不为改名重启既有任务。
  E2E 复用固定帧缓存并核对输入清单。只测一致性时 Agent 加 `--inference-only`。
- **基线设置**：Actor Qwen3.5-35B-A3B，temperature 0，thinking 关闭，2048 输出 token，512 帧，
  Global/Video 各最多 5 步。基线分数见 `.claude/benchmarks.md`。
- **最终回答的理由长度**：终答 `reason` 不设字符硬上限，保留简洁、非空要求；每次完整响应仍受2048输出token预算限制。
  取证决策的reason仍限1200字符，analyze指令预算不变；answer决策直接携带终答。此改动会影响动作、答案与耗时；历史独立回答器成绩不能视作新协议成绩。
- **Global 基础提示**：本分支是隔离System对照，默认Global采用PRO6000简洁System；Video候选在冻结副本恢复原Global，详见 `outputs/system_ablation_20261017/README.md`。User 排布为 Question→Videos→Available actions→History；
  主动 answer 直接提交 `reason/action/parameters.answer`，循环耗尽时复用 `decide(answer_only=True)`，只允许 answer。
  取证阶段核实关键冲突，每次检查针对具体不确定点，一到两句说明决定性证据/缺口与行动目的，不重复论证。
  answer 动作依现有证据提交最佳判断，按题目要求表达结果，在 reason 中简洁保留重要限制；不靠选项枚举限制答案。
  强制终答继续使用决策 System、视频身份、公开 History 与既有 skill 策略，不调用独立回答器，不提供新取证动作。
  空库与进化库使用相同协议。2026-10-16按用户要求恢复900条面板对应的四个Global/Engine源码文件；
  历史History前置＋独立兜底及旧PRO源码结果仍保留各自协议，已有任务不热更新，新实验另建结果目录。
- **进化实验的运行时**（`configs/skill_evolution/runtime/dynamic_35b_embedding.yaml`）：Global 和 Video 共用同一个库文件，
  按 `meta.role` 区分；进化时由算法替换成当前候选库（runtime 配置中的 `dynamic-v003` 路径会被覆盖）。
  不传 `--skills` 时两类卡都为空，Video 卡保持不变（为空，或为 `--skills` 初始库中的 Video 卡）。

## 进化算法现状

`src/skill_evolution/algorithms/alternating/global/` 下已注册三个 Global 算法：`global-skilladaptor-v1`（adaptor）、
`global-cluster-v1`（cluster）、`global-cluster-v2`（cluster_v2，显式 Train/Cal/Gate）。
新方案 `global-scope-v1`（`scope/`，以运行时 Selector 的选择给题目分组，按选中题上的实测净收益迭代）
已有设计、轨迹视图、模式发现/方法编写 Prompt 及中文镜像、安慰剂文本和 K1–K5 组件探针；完整进化循环尚未实现。
探针没有证明所测 skill 存在超出安慰剂的净收益，回答器格式失败是已观察到的干扰；完整结论和限制见 `scope/docs/probe_results.md`。
`algorithms/alternating/video/` 尚未实现；目前 Video skill 冻结，Global/Video 交替调度也未实现。
共享基础设施在 `infra/`（数据划分、rollout、评分、轨迹投影、不可变库与持久化）；Runtime 不依赖 optimizer。

## 完成标准

- **文档、指令与 skill 入口改动**：检查引用路径、符号链接、适用范围及 `git diff --check`；不因此安装项目依赖或启动 GPU。
- **代码改动**：针对改动做语法检查；完整的 `python3 -m compileall -q src scripts eval/agent_eval demo.py` 与项目测试放在远端环境执行。
  涉及模型调用的改动，还要在 Modal 上跑一个小规模冒烟实验，并贴出实际输出作为证据；环境阻塞时明确标注尚未验证。
- **输出一致性与吞吐实验**：按用户要求只分析输出是否一致，不评估正确率、不启动 Judge。
  保留冻结源码、模型与推理配置、原始输出；核对输入哈希及完整 token ID 序列，MVAgent 还须覆盖每次中间调用、轨迹与最终答案。
  报告有效比较次数、差异数量、首次分歧位置、请求错误及耗时；有限样本通过不能写成通用确定性保证。
- **准确率评测与 skill 进化实验**完成时应具备：
  - 冻结源码快照，以及 commit、split、skill 库哈希、模型/Judge 与推理配置；
  - 原始 rollout 与评分结果；
  - 主指标（CrossVid 报十类任务 macro）与有效样本数；
  - 更新后的 `.claude/status.md`，写明结论、限制和下一步。
- **文档同步**：改动使本文件、局部 `AGENTS.md`、`.claude/rules/`、`mvagent-environment` skill、`.claude/benchmarks.md` 或
  `.claude/status.md` 失准时，在同一工作项内更新。每次会话都需要的规则写在本文件；路径规则由局部 `AGENTS.md` 指向共享规则。
  `CLAUDE.md` 只保留主说明入口，避免维护两份项目规范。
- **历史上下文**：旧会话摘要和状态笔记是历史证据，不是新的执行授权；其中的“运行中”“未提交”等描述须与当前 git、文件和远端状态核对。
  保留实验负结果、协议差异及来源信息，不能把组件探针、下载验证或语法检查写成完整实验已完成。
