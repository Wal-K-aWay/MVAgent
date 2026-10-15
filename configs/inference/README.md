# 系统推理配置

本目录存放模型、Agent和Skill开关；`execution/`存放GPU端点、请求并发与问题worker。

Skill 可配置 `mode: static`（默认，固定Markdown）或 `mode: dynamic`（BM25检索、LLM筛选的
冻结JSON库），都用 `path + sha256` 固定。动态库增删改、冻结与配置方法见
[`Skill说明`](../../src/mvagent/skills/README.md)。现有默认无Skill配置不变。
路径按项目根目录使用，文件移动不改变模型或推理参数。

当前35B-A3B无Skill配置：`local_qwen35_35b_a3b_historical_no_skill.yaml`。
当前六卡稳定执行：`execution/gpu2_7_single.yaml`（GPU2–7，每端点并发1）。
27B无Skill配置为`local_qwen35_27b_no_skill.yaml`，对应六卡执行配置为
`execution/gpu2_7_qwen35_27b_single.yaml`（同样每端点并发1）。
其他旧命名配置是可选模型/API示例，不能根据文件名推断实际模型：例如
`local_qwen35_vllm.yaml`实际使用Qwen3.6-27B-FP8并启用authored Skill。
旧GPU池配置保留原并发，不代表当前推荐设置。

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml \
  --execution-config configs/inference/execution/gpu2_7_single.yaml \
  --output outputs/new_no_skill_run \
  --defer-open-qa-judge
```

开放问答延后评分；选择新输出路径，避免覆盖或混用实验。当前正在运行的测试
仍使用自身冻结配置，不受本目录整理影响。共享GPU池也可传给Skill进化入口。

动态Skill配置支持 `retrieval_top_k: 8`，满足`1 <= retrieval_top_k <= 32`。
所有配置只选一张或空选；`max_selected`字段已删除，旧字段会报错。
当前库schema_version为2，必须有description。小目录全量筛选；大目录使用配置的Embedding或BM25召回。


动态Skill还支持可选独立筛选模型，两角色可分别设置：

```yaml
skill:
  enabled: true
  mode: dynamic
  path: /absolute/path/to/frozen-bank.json
  sha256: <bank-sha256>
  retrieval_top_k: 8
  selection_scope: task
  selector:
    model_type: qwen3_5_35b_a3b_local
    temperature: 0
    max_tokens: 2048
```

`selector`省略时复用所属Global/Video Planner模型；显式设置后，未填写的temperature/max_tokens
继承所引用`models:`实例默认值。该配置只影响Skill筛选，不改变action/参数生成模型。
selector只允许model_type、temperature、max_tokens；model_type必须引用注册模型。
启用时参与能力校验、启动解析、资源池及快照；禁用Skill不加载selector。静态Skill不支持该字段。
新增本地模型实例须配置对应execution模型池；此功能不会自动替换现有服务。

可选共存配置 `local_qwen35_27b_skill_embedding.yaml`：27B显存预算80%，冻结v003动态
Skill库，`skill.embedding`连接本地8110。执行仍用27B六卡cap1配置。七张卡在默认K8时
直接全量进入Selector；只有合格卡超过K时才使用向量召回。

Embedding使用vLLM原生配置（不是BatchExecutor执行配置）：

```bash
CUDA_VISIBLE_DEVICES=4,5,6,7 /home/kww/miniconda3/envs/MVAgent/bin/vllm serve \
  --config configs/inference/execution/qwen3_embedding_8b_tp4.yaml
```

应先等待现有实验退出并验证端点空闲，再用80%配置重启主模型，最后启动embedding。
TP4分摊8B权重，10%预算不是实测占用保证；留存初始化和共存探测结果。不能直接把80%
配置交给90%驻留服务：现有身份检查会拒绝不匹配。不要对进行中的实验修改配置或重启。
