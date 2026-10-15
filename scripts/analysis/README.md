# Analysis entry points

Scripts read explicit inputs or frozen experiments and write generated artifacts under
`outputs/analysis/`. They are not interchangeable with training or benchmark inference.

| Purpose | Entry points |
|---|---|
| Historical evolution/feedback audits | analyze_alternating_run.py, analyze_video_evidence_experiment.py |
| Execution profiling | profile_rollout.py, benchmark_batch_speed.py, analyze_batch_speed_steps.py |
| Media validation | benchmark_video_clipping.py, benchmark_video_decode.py, verify_stream_copy_seconds.py |
| Frozen historical results | remaining analyze/compare/build helpers; read their defaults and available inputs before running |
| CrossVid fixed evaluation subset | audit_crossvid_representative_subset.py: metadata and saved-score validation after IDs freeze; no inference or Judge calls |

Historical output paths may have been removed or archived;
check the cleanup manifests before attempting a replay. Old result-building scripts
must not recreate retired Markdown reports as current documentation without a new task.

The fixed August12 P0 selection/60-question/1000-question comparison scripts were
removed on September15: their raw input runs were archived and they are not active
regression infrastructure. The old-file archive was removed on September16; its manifest remains in
`outputs/maintenance/cleanup_guide_scripts_20260915/`. No shared imported helper was removed.

Historical dynamic-constraint and alternating-run evidence is summarized in
`analysis/skill_evolution/experiment_summary_20260914.md`. Current execution decisions
belong in handoff.md and historical_next_steps_20260920.md, not in an old script's hard-coded defaults.

CrossVid 固定 2500 题历史结果复算：`/home/kww/miniconda3/envs/MVAgent/bin/python scripts/analysis/summarize_crossvid_2500.py`，输出 `outputs/reports/crossvid_2500/report.md` 与逐题 CSV。读取已有预测/Judge，不调用模型。

- `run_overnight_watch.py`: prepare/launch/run/summarize/check for the bounded nine-arm
  overnight watch diagnostic. `launch` freezes source/configs/Skills/selection and detaches
  a sequential24-question-block controller targeting8.5h. GPU2–7 services must already
  match35B-A3B; no replacement, optimizer or API Judge. See
  `analysis/skill_evolution/overnight_watch_20260920.md` for scope, resume and missingness.

- `run_fixed_prompt_validation.py launch --output outputs/analysis/20260922_fixed_prompt_validation`: 冻结并顺序运行无Skill B0/D/S固定Prompt完整轨迹，32题/臂预检后分块配对汇总；来源重叠补充层显式区分，不调用API Judge。`summarize`可离线重算；失败保留状态，重新`launch`按已完成stage恢复，活跃控制器不可重复启动。

- `analyze_fixed_prompt_results.py`：复核B0/D/S全部3600条正式轨迹，分解任务、来源、原始对错组合和证据变化；输出观察一致性哈希、健康指标与宏平均敏感性，不重新推理。
- `probe_fixed_prompt_final_decisions.py prepare|launch|score`：全部1200题B0末节点的原样/D对照，保留原History和Schema，不执行新工具动作；本地模型调用，无付费Judge。只作节点诊断，不是完整轨迹得分。
- `run_original_question_watch.py prepare|launch|run|summarize`：完整35B基线E2E对/Agent错的闭式题，B0重跑对照Global原题watch Skill；1600字符模板可行性筛选、24题预检、后台顺序全量、实际原文/动作/覆盖审计。只测错题恢复，无API Judge，无自动部署。
  `--reuse-preflight PATH`仅在新根prepare/launch时复用身份完全核对的已完成预检；复制是否完美作为结果指标，工程门槛检查Skill加载及实际watch，不按准确率停跑。
- `run_routing_protection.py prepare|launch|run|summarize`：只新跑条件路由RQ，2000题task×cell概率抽样（1200历史正确/800错误），历史B0直接复用，不重跑强制WQ。24题预检、100题块自动汇总；仅完整计划评分后输出加权总体估计，原Skill复制/动作审计沿用共享函数。
- `run_action_parameter_validation.py prepare|launch|run|summarize`：五臂C/OG/OV/T/V独立角色Skill，1200唯一题、3000正式＋120预检；复用历史B0，FSA连续IoU与闭式分开。冻结后后台顺序跑，预检核查角色Skill与实际行为代理，自动分任务/保护集报告，未自动组合/部署。协议见`analysis/skill_evolution/action_parameter_results_20260922.md`。

- `run_evidence_contract_validation.py`: frozen OV/T/V follow-up, same prior panel/Skills; isolated cropped Observer scope/time prompts and post-evidence Global Skill gating. Reuses historical controls,1800 main+72 preflight, no paid API or default Runtime changes.

- `replay_skill_model_nodes.py prepare|run --output PATH --baseline BASELINE`: freeze
  exact selector/Actor text requests from initial/later Global/Video nodes, then replay
  on the output directory's model configuration through six verified replicas. No
  action execution; saved Actor prompts retain original selections. Sampling is by
  trajectory position, not correctness. Input/config/source hashes and every failure
  are retained. Used for the27B vs35B v003 diagnostic; separate service switching.

旧 GEPA 启动器已移除；冻结历史运行保留原源码与依赖快照。

- `run_gepa_generalization.py`：冻结GEPA搜索候选的600题迁移诊断；元数据抽样与来源隔离，复用历史无Skill对照，只运行候选并自动生成分项比较。协议见`analysis/skill_evolution/gepa_generalization_20260923.md`。

- `audit_gepa_expanded.py`：只读核对扩大GEPA实验的整库验证、逐决策选卡/正文注入及提案证据覆盖，不调用模型。结果与持续时间对照方案见`analysis/skill_evolution/gepa_targeted_updates_20260924.md`。

- `run_skill_duration.py launch`：冻结两卡和Eval181，按DD/DF/FD/FF执行选择持续时间对照，每臂8题smoke后完整评估，后台串行、严格真实注入审计；无优化器、不重跑无Skill。

- `audit_skill_selector.py prepare|run|summarize`：冻结预标221个上下文，只调用35B文本Selector；
  dev/confirm分开，full为全目录，embedding/bm25为K2召回压力测试，repeat用于新一轮。
  使用六副本身份/容量检查，保存原始模型调用，不执行QA动作或付费Judge。
  标签为适用性诊断，不是视频GT。结果见`analysis/skill_evolution/selector_quality_20260924.md`。

- `compare_selector_methods.py launch --output PATH --cases JSON`：冻结并后台顺序运行8组
  参考选卡方案/参数对照、温度重复、开发组选择的两候选与当前方案的新上下文确认。
  `selector_methods.py`定义离线适配Prompt；不被Runtime导入。当前audit单臂目录为
  `{partition}_{mode}_{repeat}/{method}/`，旧实验必须用其冻结controller读取。
  结果协议：`analysis/skill_evolution/selector_methods_20260924.md`。

- `run_pattern_skill_evaluation.py`: freeze and detach a balanced CrossVid shared-pattern
  Skill evaluation, reuse historical no-Skill scores, audit routing/injection and export
  full action parameters. Protocol: analysis/skill_evolution/pattern_skill_evaluation_20260925.md.

`run_pattern_skill_evaluation.py --bank <JSON>` now freezes the requested Global bank,
shows its full catalog, runs disjoint10-question smoke plus remaining main, and combines
reports only after exact panel reconciliation. Frozen historical controllers retain their
old behavior. Default bank is global_acquisition_v002; default panel remains1000 questions.

`run_pattern_skill_evaluation.py --panel transfer --per-task 40` additionally freezes
CVBench/MVU-Eval panels and runs disjoint per-category smoke/main with the same
Global bank. It reports per-dataset paired historical comparisons, task/cohort/source
breakdowns and known-media-group bootstrap. See
`analysis/skill_evolution/acquisition_transfer_test_20260925.md` for limitations.

`run_video_skill_matrix.py launch --output <new-root> --per-task 20` collects actual
Video instructions and freezes the G0V0/G1V0/G0V1/G1V1 matrix with common models/data.
Four smoke checks precede main; role/request injection audits and factorial paired
reports are automatic. See `analysis/skill_evolution/video_skill_matrix_20260926.md`.

2026-09-26：当前Skill脚本读取schema3结构化JSON，审计实际注入的Strategy。
audit_skill_selector.py prepare需要--learned-bank明确给出schema3库；--mode hybrid使用当前混合召回。旧对照必须使用原冻结源码。新的pattern/matrix配置固定候选8并指定现有8110 embedding服务，不启动/替换服务。

- `test_structured_skill_runtime.py launch --output <new-root>`：46题同题结构化Skill验证，复用旧G1V1作历史对照，随后重放相同选卡输入、实时比较固定Skill的旧/新执行正文；后台顺序运行。`run`只恢复同一冻结控制器。
- `summarize_structured_skill_test.py --output <root>`：核查输入、选择范围、实际两段注入，汇总同题得分、action/参数分布及固定输入对照。2026-09-26报告在`analysis/skill_evolution/structured_skill_real46_20260926.md`。


2026-09-28 cleanup: removed obsolete launchers run_gate_calibration.py, probe_bigmodel_optimizer.py, run_video_evidence_experiment.py and run_crossvid_gepa_pilot.py. Their descriptions above are historical, not current entry points. Read-only historical reports remain. Active transfer/duration scripts now use credentials.py for the same non-executing credential-file parser.

## 2026-09-28 清理边界

已删除单次动态约束分析入口 analyze_dynamic_constraints_run.py；两个旧 GEPA 数据准备入口
也从 scripts/ 移除。历史输入、split、结果和冻结源码未删除。
watch/固定 Prompt/action-parameter 系列仍承担被其他脚本引用的工具职责，继续保留。
分析旧实验应先核对输入和冻结源码，不把旧启动参数当成当前推荐配方。

- `probe_question_embedding_clusters.py --output outputs/analysis/20261001_question_embedding_clusters_small`：纯本地 embedding 的输入题目聚类诊断，从 CrossVid Lite2500＋CVBench1000/MVU1824 按原生类别固定种子均匀抽样，每类最多20题，覆盖三个 benchmark 全部类别。仅编码问题、选项及局部视频 ID/时长；对照去掉视频元数据。benchmark 原生类别仅作外部评估标签，保存 top8 同类率、来源排除对照、complete-link 阈值扫描、配对 precision/recall/F1、ARI、组大小及单题组比例。无 LLM、GT/Judge/Gate 调用，不改变正式故障聚类；`--self-check` 执行 CPU 合成检查。输出冻结输入/脚本/来源哈希和分批向量，原样恢复复用已完成批次。

- `audit_cross_benchmark_question_clusters.py --input outputs/analysis/20261001_question_embedding_clusters_small`：复用660题已有向量/全量分组，检查跨benchmark的类别关联、top8和混合组；179题四个广义输入策略族只用于探索性评估，不编码、不将unknown作负例。保存37题三benchmark排序成功组及不同输入表示的跨benchmark覆盖对照，无新模型调用。`--self-check`验证原生类别内部子类型和排除规则。

- `test_question_grouping_methods.py --input outputs/analysis/20261001_question_embedding_clusters_small --output outputs/analysis/20261001_question_grouping_validation`：冻结330/330、540开发配置、固定参数确认/来源压力检查；比较层次/图社区/重叠局部素材和程序metadata，`--self-check`执行CPU合成检查。只embedding，无逐题LLM预处理。
- `test_grouped_skill_pipeline.py generate|select --input outputs/analysis/20261001_question_grouping_validation`：实际现有Generator/Selector接线诊断，读取冻结真实失败；Generator正式预算2400不变。7次总生成均因长度拒绝；独立shadow银行仅作选卡检查，不是已接受Skill，不运行QA/Gate。付费optimizer调用已完成；重放优先保留stage响应。完整原题、MMR补测、独立核验与局限见`analysis/skill_evolution/question_grouping_validation_20261001.md`。

- `test_no_k_cross_batch.py`: no-fixed-K HDBSCAN/DBSCAN/average-link/Louvain comparison
  with overlapping-neighborhood control; cached full-input embedding only. Dev-only
  selection, held-out-ID/source stress, and accumulated-vs-batch-local sequential
  arrival diagnostics. `launch` freezes and detaches; `run` resumes the frozen owning
  controller after process checks. See `analysis/skill_evolution/no_k_cross_batch_protocol_20261001.md`.
  Requires scikit-learn in an isolated diagnostic environment; no model/QA calls.
  `--representation video_id_duration` preserves complete question/options and ordered
  runtime-local video_id-duration pairs, removing all derived statistics; generates
  new embedding batches and adds static fixed-previous-spec comparisons. Frozen old
  experiments are unchanged. Output: `20261001_video_id_duration_clusters/`.

- `test_localizer_skill_visibility.py`: detached paired GLM-5.3-Flash diagnostic of
  current Localizer vs complete Skill-guidance removal, including corresponding
  TASK/rules/examples/BACKGROUND ablation. Frozen real traces, same Schema, two repeats.
  `analyze_localizer_skill_visibility.py --output <root>` summarizes only completed
  runs and writes an arm-blinded evidence review; structural agreement is not accuracy.

Localizer task-check retest: pass `--baseline-without-skill outputs/analysis/20261002_localizer_skill_visibility`
to `test_localizer_skill_visibility.py launch --output <new-root>` to compare fresh
calls using frozen original no-skill prompts and current revised no-skill prompts.
It verifies identical cases and Schemas, freezes source and the baseline reference,
and runs two repeats per arm. `analyze_localizer_skill_visibility.py` reads arm names
from the protocol. Structural agreement is not correctness; review public evidence.

`prepare_localizer_boundary_panel.py --output <new-panel>` selects 16 regression
and 72 new three-benchmark real trajectories for evidence-boundary checks. It
excludes prior Localizer question IDs and records deterministic task/outcome sampling
and source hashes. Start `test_localizer_skill_visibility.py launch --output <new-run>
--inputs-json <panel>/inputs.json --baseline-without-skill <frozen-prior-run>` to make
fresh old/new no-skill calls; the baseline uses that run's frozen no-skill template.
The summarizer separates regression, expansion and expansion benchmark subsets.
These are stratified diagnostics, with no source-video independence or accuracy gold
standard guaranteed; quality review must distinguish verification from proven defects.

For a matched DeepSeek Localizer diagnostic, add `--model deepseek-v4-flash
--prompts-from <matched-frozen-run>` to the expanded-panel launch command. Inputs
and prompt identities must match before exact frozen prompts are copied. The
registry is persisted in protocol.json and used on resume. DeepSeek thinking is
enabled with high reasoning effort; its provider omits sampling parameters.
Record returned model from events; cross-provider schema transport and reasoning
settings differ. Credentials remain environment-only.

- `test_when_to_use_styles.py prepare|run|summarize --output PATH`: 固定 acquisition-v002 的 11 张 Global 卡及 71 道真实 CrossVid 开发题，比较 short/compact/detailed 三种 when_to_use，运行当前 BM25+embedding RRF8 和真实 Global Selector，每题每臂两次。只修改选卡字段，正文固定；保存原始请求、召回排名、选择事件、预先语义标注及配对结果。通过现有 GPU4–7 服务池，不部署服务、不执行 Actor QA 或 Judge。标注为 Codex 审阅，非独立人工金标。报告：`analysis/skill_evolution/when_to_use_styles_20261005.md`。

- `test_selector_rejection_coverage.py prepare|run|summarize --output PATH`: 在三种 when_to_use 风格下，用134道真实初始 Global 输入比较 full/missing/near_only/single_near 四种卡库覆盖，每题两次。新增轨迹源核对哈希；保留自然无方法题、适配正例及歧义题。另测阶段不适配的空目录工程控制，不将其计为模型拒选能力。当前 GPU4–7 cap1 服务池、当前 Selector/RRF8，无 Actor/optimizer/Judge。协议与结果见 `analysis/skill_evolution/selector_rejection_coverage_20261005.md`。

- `test_selector_retrieval.py prepare|run|summarize --output PATH`: isolated BM25/embedding/RRF shortlist4/8 diagnostic on the unchanged real Global Selector; freezes source/banks/input labels and raw requests. Use its frozen owning controller to resume.

- `test_selector_prompt_revision.py prepare|run|summarize --output PATH`: paired previous/current Selector prompt and output-contract audit on real questions, identical numeric references/cards/RRF8; frozen baseline modules and raw requests retained.

- `test_selector_explicit_applicability.py prepare|run|summarize --output PATH`: fixed-candidate one-call direct versus explicit per-card applicability audit; records semantic classifications, selection consistency and real model usage without changing production contracts.

- `test_selector_reason.py prepare|run|summarize --output PATH`: fixed-candidate direct versus single reason-before-selection experiment, same rules and paired real questions.

- `test_current_when_to_use.py prepare|run|summarize --output PATH`: short/detailed applicability text compared under current numeric-reference Selector, full/missing-primary real scenarios; strategy unchanged.

- `test_selector_boundary_prompt.py prepare|run|summarize --output PATH`: fixed short/detailed candidate lists, current versus target/input-relation and exclusion-veto rules; historical applicability labels require semantic review.

- `test_selector_conservative.py prepare|run|summarize --output PATH`: short-card baseline/conservative prompt comparison with full, covered-small, missing-primary, near-only and single-neighbor libraries; frozen actual baseline requests, single-field output, real Runtime retrieval.

- `test_current_selector_retrieval.py prepare|run|summarize --output PATH`: current conservative Selector with frozen short numeric-ID cards; RRF8/6/4 and embedding4, full/missing libraries, two repeats, real retrieval and separate recall/selection/refusal metrics.

- `test_expanded_selector_retrieval.py prepare|run|summarize --output PATH`: current conservative Selector, six retrieval strategies (RRF8/6, embedding8/6/4, lexical-query-cleaned RRF6), old134 plus200 pre-reviewed stratified new real questions; new/previous cohorts separate. Sampler/reviewer/source manifests frozen with the run.

- `test_selector_abstention_review.py prepare|run|summarize --output PATH`（`check`执行CPU自检）：固定扩大检索实验的334题/RRF8候选及顺序，比对当前、严格单次判断、当前选卡后独立复核。复核只看到原题/视频元数据/单张提议卡，不能改选，空选跳过；记录条件调用成本及新旧队列指标。无Runtime改动；冻结源及父请求哈希，使用既有服务池。

- `test_selector_prompt_order.py prepare|run|summarize --output PATH`（`check`自检）：固定334题/full+missing的RRF8候选集合，current/strict/balanced/scope四规则×rank/id数字升序，重复两次10688次调用。Schema枚举顺序不变以隔离展示顺序；开发标签不改，无Runtime改动。

- `test_selector_principled_prompt.py prepare|run|summarize --output PATH`（`check`CPU自检）：调研支持的八组current/scope/去示例/合并示例/rubric/rubric+多样示例及两组确定性打乱；334固定真实开发题加24人工跨领域输入条件，transfer指标单列不混入真实指标。692输入两重复11072调用；单字段、固定Schema，无Runtime改变。协议analysis/skill_evolution/selector_principled_prompt_20261005.md。

- `test_selector_scope_alignment.py prepare|run|summarize --output PATH`（`check`CPU自检）：original/aligned短when_to_use×current/general维度对齐Selector×固定候选/真实RRF8检索8组，334题两重复10688调用；meta/strategy不变，召回/正选/拒选分开，冻结输入/父请求/源码/两卡库；中文镜像同步，无Runtime改动。

- `test_selector_integrated_confirmation.py prepare|run|summarize --output PATH`（`check`验证示例/输出不变）：已授权正式五规则整合前后配对，原334题固定候选回归＋60未参与调试真实题live RRF8确认；两库两重复3152调用。新题预冻结标签、排除旧题及相同视频路径，单列确认指标，strategy/when_to_use不变。CPU测试不代替模型效果。

- `test_selector_refined_rules.py prepare|run|summarize --output PATH`（`check`结构自检）：394真实题固定候选、general/concatenated/refined三System，full/missing两重复4728调用；旧134/后续200/后续60分开，全部复用开发数据。三System源/input/config/父请求冻结，不重检索或改卡。

- `test_selector_semantic_fit.py prepare|run|summarize --output PATH`（`check`CPU自检）：394固定候选真实题，四规则baseline/operation/coverage/combined，6304调用，探测实质任务与答案格式区分、直接方法与辅助观察边界；原卡/Schema不变，配对无新检索，用户标签不改，全部开发复用。

- `test_selector_coverage_followup.py prepare|run|summarize --output PATH`（`check`CPU自检）：此前coverage精确System、完整任务关系保持、声明操作复述检查、combined四组；394固定真实题6304请求，原示例/候选/Schema不变，单字段，主方法标签有争议需案例审核。正式coverage由用户选择，进一步变体隔离。

- `test_selector_none_output.py prepare|run|summarize --output PATH`（`check`真实xgrammar/Schema/解码自检）：固定coverage规则及394题候选，比较selected_skill_ids空数组/单none字符串数组/selected_skill_id单none字符串，4728调用；输出格式隔离，正式Runtime契约不变，错误不计拒选。

- `test_selector_status_output.py prepare|run|summarize --output PATH`（`check`实际grammar/Schema/解码）：coverage固定，empty_array/status_first/ids_first三组，4728调用。oneOf约束skip=>[]、selected=>一个ID，actual xgrammar固定字段顺序，记录实际顺序/状态。正式Runtime输出不变。
