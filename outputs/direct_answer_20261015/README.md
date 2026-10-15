# GlobalAgent 直接回答集成

用户已采纳直接回答协议。正式代码由GlobalAgent在一次决策中提交`reason/action/parameters.answer`，Runtime直接返回原有`{answer, reason, status}`；不再发起独立回答请求。评测CLI和结果顶层格式不变。

## 改动

- 删除`GLOBAL_ANSWER_SYSTEM_PROMPT`、`GLOBAL_ANSWER_PROMPT_TEMPLATE`、`GLOBAL_ANSWER_SCHEMA`、`build_global_answer_prompt`、`GlobalAgent.answer()`及正常回答后的额外调用。
- answer参数为开放非空字符串，保留2400字符限额，不新增选项枚举。answer决策reason不设字符限额；analyze/watch决策reason仍1200字符，单次2048token预算不变。
- 步数耗尽时复用`decide(answer_only=True)`和同一System/模板，只允许answer。保留`forced_with_gaps`、`terminal_answer`轨迹标记及既有失败记录；普通服务异常仍向外传播。
- 公开轨迹显式展示提交的answer参数。同步optimizer动作契约、Localizer参数故障schema及中英文说明；证据已充分却提交错误参数属于参数故障，强制收尾仍不是可编辑故障目标。
- 删除主工作区两个仅测试旧独立回答器的脚本`test_final_reason.py`和`test_reason_relaxation.py`，由直接回答回归测试替代。旧实验的原始结果、冻结源码及离线历史分析保留在原位置。
- AGENTS、运行配置说明、Agent评测说明与scope历史设计的当前适用范围已同步。

仅代码采用新协议；既有两组全量任务继续使用原冻结源码，未热更新、重启或改写旧成绩。后续新运行须另建目录，空库/进化库必须使用相同回答协议。

## 验证

- Modal CPU：13项直接回答测试、2项既有结果汇总测试通过，完整`compileall`通过。覆盖开放答案/空串拒绝、按action区分reason预算、实际xgrammar编译、普通终答一次调用、强制终答、异常路径、skill可见性、Localizer与公开轨迹。
- CPU app：`ap-6dyTzuBUHk1de0CxE0LzzM`。末尾`git diff --check`因CPU镜像不含git未执行成功；同一检查已在本机隔离工作树通过，未因此安装依赖或重复模型测试。
- 独立H100!:1：`mvagent-direct-answer-smoke-20261015` / `sb-KuD9GkfwHrBDP5Ogh10kaG`，结果`devbox/direct_answer_smoke_20261015`，不连接生产端点。
- 冻结驱动`scripts/verify_direct_answer.py`，9B/CV664、27B/MVU Comparison818、35B-A3B/CrossVid MOC521，每模型两次完整Agent和两次固定证据强制收尾。记录输入hash、全token、轨迹、实际worker与错误；不启动Judge、不评准确率。
- 三模型均已完成，逐请求输入hash、完整输出token、文本与结束原因全部一致；完整轨迹与最终答案一致。

| 模型 | 样例 | 两次完整Agent答案 | 两次强制收尾答案 | 实际模型调用 | 配对比较 |
|---|---|---|---|---:|---:|
| Qwen3.5-9B | CVBench 664 | B / B | B / B | 8 | 4 |
| Qwen3.5-27B | MVU-Eval Comparison 818 | C / C | C / C | 84 | 42 |
| Qwen3.5-35B-A3B | CrossVid MOC 521 | C / C | C / C | 12 | 6 |

共6条完整Agent轨迹、6次固定证据强制收尾，104次实际模型调用、52组配对，差异0、模型错误0、结构化错误0、截断0。完整Agent分别经过2/4/3轮Global决策；27B包含多轮VideoAgent调用，并非只验证最终文本。

实际正常终答格式为`{"reason":"...","action":"answer","parameters":{"answer":"B"}}`；Runtime返回的顶层answer仍为`B`、status为`answered`。逐条核对最终答案来自最后一次decision参数，没有额外独立终答请求，也没有旧global_answer响应schema。强制收尾仍保留既有轨迹标记。

实际服务均为`qwen35-bf16-flashinfer-sync`、BF16、TP1、并发1、seed0、temperature0、2048输出token，prefix/MM cache关闭，FlashInfer GDN与原生GemmaRMSNorm；104次响应的实际cached_tokens均为0。三个模型依次在同一张H100加载，未测试跨卡或8卡调度变更。vLLM0.19.1、torch2.10.0、transformers4.57.6、xgrammar0.2.2、flashinfer0.6.6；服务源码SHA256为`30ec2146bba040c0db5ecb7b6ab3090aa1faec4b4f70ec12569bbe93dd5bd713`。

运行于2026-10-15 09:14:31至09:38:01 UTC。最终`audit.json`/`audit_source.py`、manifest、各模型report及原始轨迹保存在runs volume的`devbox/direct_answer_smoke_20261015/`；经外部Volume接口核对audit持久化后，09:44 UTC已释放该独立Sandbox。未释放或重启生产评测Sandbox。

模型调用相关的5个改动文件（engine、GlobalAgent agent/prompts/schema、共享schema）与实际冻结源码逐一SHA256相同。后续只涉及离线公开轨迹渲染与对应单测，不改变本次实测请求。原始结果留在Modal，本地仅此Markdown报告。

这个集成不是之前25题固定终答探针的逐字复制：正常Global仍可选择取证，保留视频元数据与已选skill。Prompt/契约变化可能改变取证路径；不能把旧探针60%准确率当作新完整Agent成绩。本次每模型仅1题重复两遍，skill保留路径由单测覆盖；未做新协议全量准确率评测，也不据有限样本声称任意输入绝对一致或永不出现格式错误。
