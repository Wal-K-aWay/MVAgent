# 手写程序卡P/S资源（2026-11-04）

建库冻结时未运行，下表保留该输入状态，实测进展见[研究记录](../../../../../docs/skill-nv-study-20261103.md)。Codex手写四个自包含证据程序（2 Global、2 Video），由同一私有草案确定性地产生两套完整库；建库没有optimizer调用。它们是显式选择的研究输入，不默认启用，也不作为自动进化种子。四方法不是固定题型或用户规定的六类。

|变体|完整库|四卡text总词数|状态|
|---|---|---:|---|
|P 连续段落|[bec6d95693324819b306865b58e4370278a810f6346d0162e938b82284088779](bec6d95693324819b306865b58e4370278a810f6346d0162e938b82284088779.json)|1943|未运行|
|S Purpose/Procedure/Evidence/Stop|[87ae199ca2336f5686272b724d62765c566938811be86836b6e6b25439e080c5](87ae199ca2336f5686272b724d62765c566938811be86836b6e6b25439e080c5.json)|1975|未运行|

每个文件是schema_version3、四卡整库，meta与when_to_use逐字相同。P用空格连接intro、原步骤1–4、Evidence句、原步骤5；S仅增加Purpose/Procedure/Evidence/Stop标题、1–4编号及换行。Evidence是本包唯一相对原草案新增的操作句，在两版同句同位置；其余原文字逐字保留。操作文字和顺序相同不保证模型解释或输出相同。

按项目word规则，S每卡比P多8词（4个标题词和4个数字），四卡共多32词。两版strategy每卡相差67字符/67 UTF-8字节；完整JSON字节数见计划。实际Actor tokenizer长度待远端已装环境测量，不能把字符、字节或词数称为token匹配；逐请求token仍按原runner记录。

固定原Train400成员与顺序不变，P/S各400新增、最多800；各版首40仅作执行/自然选卡诊断，仍包含于800内，随后固定完成余360，不按前缀成绩挑版本或停跑。已有匹配empty400只读复用，不补推理或Judge。Actor/Judge继续相同8ff冻结协议，7个9B Actor加1 Judge/8 H100，自然选一张或none，无强制注入、使用率配额或schema/runtime改动。本包不查询Cal/Gate/Test；原Gate已经确认并拒绝，不可复用。

主读数S−empty与P−empty，辅助S−P只描述这四程序的布局差别；不是所有skill风格或库粒度的因果结论。合法Train定性线索与完全虚构的换场景/标签/顺序正反例用于写作审阅，不以held案例设入口。范围重叠和none均合法，不能把激活率当效用。

[冻结计划](../../../../../configs/skill_evolution/manual_procedure_20261104.json)记录来源SHA、逐卡长度、预算与读取边界；[完整中文镜像](../../../../../docs/manual-procedure-skills-zh.md)包含两版每卡全文及通用性/重叠说明。SHA文件名对应含末尾换行的完整UTF-8 JSON字节，不是card内容哈希。
