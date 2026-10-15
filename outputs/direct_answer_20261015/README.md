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
- 9B已完成：两次完整Agent及两次强制收尾均B；8实际调用、4配对均一致，0服务/结构错误、0截断。其余模型正在运行，最终结果待补。

这个集成不是之前25题固定终答探针的逐字复制：正常Global仍可选择取证，保留视频元数据与已选skill。Prompt/契约变化可能改变取证路径；不能把旧探针60%准确率当作新完整Agent成绩。
