# 普通服务器接续 Skill 研究

本指南供有权限使用新服务器的研究员执行。代码不要求 Modal；Actor、Judge、数据和结果均放在研究员控制的计算环境。
目标服务器有可机动分配的H20，以下使用 **Linux x86_64、Python 3.12** 和 Qwen3.5-9B，GPU数量由接手者按当时资源配置。
历史参考使用H100；H20上的安装、容量、推理行为和吞吐尚未验收，不声称与历史输出完全相同。
仓库名中遗留的 `modal_`/`h200` 配置名称不是平台依赖。

当前已实现一次生成和从空库开始的角色轮换闭环；跨轮经验累计、基于新事件表示的默认优化循环尚未实现。
当前没有稳定优于强一次生成的精度结论。方法、历史分数和未完成测量分别见
[设计](skill-evolution-design.md)、[探索结果](skill-exploration-results.md)、[反馈实验](skill-feedback-iteration-20261022.md)。

首次接手按以下顺序推进，不必先阅读全部历史报告：

| 阶段 | 最少需要什么 | 结束时检查什么 |
|---|---|---|
| 单题功能演示（第2节） | Actor权重、一个可用副本、两段自有视频 | `result.json`有非空答案和行动轨迹 |
| 十任务推理检查（第2节） | 处理好的CrossVid、Actor | 10题均成功、原始回答和调用事件完整；不评分 |
| 已有库评估（第3–4节） | 冻结清单、指定库、Actor、CCQA Judge | 全部题完成及官方macro，不只看进程退出 |
| 新的rolewise研究（第5节） | 明确实验计划、合法Train/Cal/Gate、optimizer | 候选、拒绝、Cal/Gate和最终库均留存 |

Actor是执行决策的模型；Observer读取视频并返回观察，Selector决定是否选卡（本配置均复用Actor模型）。
Judge只负责CCQA评分；optimizer负责写卡，不参与运行时回答。使用现成skill库不需要optimizer API密钥。

## 1. 获取代码并准备环境

```bash
git clone --depth 1 https://github.com/Wal-K-aWay/MVAgent.git
cd MVAgent
git rev-parse HEAD

uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt 'flashinfer-python==0.6.6' 'triton==3.6.0'
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
uv pip check
python -c 'from models.vlm.local.sync_server import execution_profile; print(execution_profile())'
```

保留commit、依赖清单和后续实际服务manifest。驱动、CUDA兼容性及安装注意事项见[安装说明](../README.md#installation)。
固定profile要求vLLM 0.19.1、torch 2.10.0、transformers 4.57.6、xgrammar 0.2.2、FlashInfer 0.6.6、Triton 3.6.0；
这些不是完整传递依赖锁。`decord==0.6.0` 的wheel可能有Python标签问题，不能把依赖安装失败跳过后称为成功复现。
本次交接没有连接或验收新服务器；安装检查通过也不等于已经完成模型推理。

以下路径是示例，首次配置时改成新服务器可写目录：

```bash
export DATA_ROOT=/srv/mvagent/data
export MODEL_ROOT=/srv/mvagent/models
export RUN_ROOT=/srv/mvagent/runs
export ACTOR_WEIGHTS="$MODEL_ROOT/Qwen3.5-9B"
export JUDGE_WEIGHTS="$MODEL_ROOT/Qwen3-30B-A3B-Instruct-2507"
mkdir -p "$RUN_ROOT" .local
```

做benchmark前，按[数据下载与准备](data-preparation.md)获取数据；若先做自有视频演示，可暂时跳过此命令：

```bash
python scripts/prepare_crossvid_data.py --root "$DATA_ROOT/crossvid" \
  --download-workers 4 --pea-jobs 4 --uav-jobs 4
```

它包含当前revision下载、历史2416个behavior视频恢复与核验、现有预处理。
需要 `$DATA_ROOT/crossvid/QA/*.json`、`qa.jsonl`、`qa.meta.json`、原始媒体与`.mvagent_media/`；
不要只下载问答JSON。模型目录需包含完整tokenizer、processor、config和safetensors。
模型名相同不等于权重相同；固定下载revision并保留文件哈希。

Actor可选择官方[9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[27B](https://huggingface.co/Qwen/Qwen3.5-27B)或[35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)，Judge为[Qwen3-30B-A3B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507)。下面以9B为例；先从模型仓库的Files and versions取得完整commit并填写两个revision，不能把未量化模型换成AWQ/FP8等版本。只做首次推理时仅下载Actor，Judge在评分前再下载：

```bash
hf download Qwen/Qwen3.5-9B \
  --revision "${ACTOR_REVISION:?Set the full Actor commit}" --local-dir "$ACTOR_WEIGHTS"
```

若开展新固定版本实验而不声称精确匹配历史权重，可以先用`HfApi().model_info('Qwen/Qwen3.5-9B').sha`和Judge对应repo解析当前commit，记录后下载；不要让重启时的`main`漂移。历史完整权重hash清单未随Git交付。离线服务器可在获准联网的环境下载完整目录与SHA清单，再按机构许可搬入；不需要把受限服务器开放给原作者。


## 2. 按实际资源配置 Actor 和 Judge

Actor是项目自己的同步服务，native runner会自动启动并验证；**不要用普通 `vllm serve` 替代Actor**。
Judge使用既有 `serve_ccqa_judge.sh`。两者不能占用相同GPU或端口。

先设置可独占使用的Actor GPU索引和端口。`ACTOR_GPU_IDS`、后续的`JUDGE_GPU_IDS`使用逗号分隔的索引列表，数量不限于历史配置；
索引使用当前主机/容器`nvidia-smi --query-gpu=index,uuid --format=csv`报告的物理索引，且只能选择调度器授权的GPU。
不要把`CUDA_VISIBLE_DEVICES`重映射后的逻辑0..N编号当作物理索引；服务启动器会设置子进程的可见设备。
两组不能重叠。角色轮换需要Actor和Judge同时可用，但不规定固定总卡数或角色配额。
示例端口起点可以修改；GPU列表由接手者根据资源填入环境变量，不在文档中固定：

```bash
: "${ACTOR_GPU_IDS:?Set available Actor GPU IDs, comma-separated}"
export ACTOR_GPU_IDS
export ACTOR_BASE_PORT=8100
```

下面只生成本地配置，不调用模型。`.local/` 已被Git忽略：

```bash
python - <<'PY'
import os
from pathlib import Path
import yaml

runtime = yaml.safe_load(Path('configs/inference/modal_qwen35_9b_no_skill.yaml').read_text())
runtime['models']['qwen3_5_9b_local']['model_name'] = os.environ['ACTOR_WEIGHTS']
execution = yaml.safe_load(Path('configs/inference/execution/modal_h200x8_qwen35_9b.yaml').read_text())
actor_gpus = [int(value) for value in os.environ['ACTOR_GPU_IDS'].split(',')]
assert min(actor_gpus) >= 0 and len(set(actor_gpus)) == len(actor_gpus), 'Invalid Actor GPUs'
actor_ports = list(range(int(os.environ['ACTOR_BASE_PORT']), int(os.environ['ACTOR_BASE_PORT']) + len(actor_gpus)))
assert min(actor_ports) > 1023 and max(actor_ports) < 65536
prototype = execution['model_pools']['qwen3_5_9b_local']['replicas'][0]
execution['model_pools']['qwen3_5_9b_local']['replicas'] = [
    {**prototype, 'gpus': [gpu], 'endpoint': f'http://127.0.0.1:{port}/v1'}
    for gpu, port in zip(actor_gpus, actor_ports)]
Path('.local/actor-9b.yaml').write_text(yaml.safe_dump(runtime, sort_keys=False))
Path('.local/execution-9b.yaml').write_text(yaml.safe_dump(execution, sort_keys=False))
PY
```

### 2.1 先让一道自有视频问题跑通

准备两段有权使用的短视频，用绝对路径传入，并把下面的问题改为确实需要比较这两段视频的问题。
无需数据集、Judge或API密钥。演示只用配置中的第一个Actor副本：

```bash
python - <<'PY'
from pathlib import Path
import yaml
execution = yaml.safe_load(Path('.local/execution-9b.yaml').read_text())
execution['model_pools']['qwen3_5_9b_local']['replicas'] = execution['model_pools']['qwen3_5_9b_local']['replicas'][:1]
Path('.local/demo-execution.yaml').write_text(yaml.safe_dump(execution, sort_keys=False))
PY
python demo.py --config .local/actor-9b.yaml \
  --execution-config .local/demo-execution.yaml \
  --video /absolute/path/to/first.mp4 --video /absolute/path/to/second.mp4 \
  --question 'What happens in both videos, and what differs between them?' \
  --output "$RUN_ROOT/first-demo"
```

使用新的output目录。成功后检查`first-demo/result.json`的`result.answer.answer`为非空，
`result.action_history`和`result.trajectory`保留动作/观察过程；检查视频内容是否真正进入观察结果。
看到答案只证明功能路径运行，不证明答案正确。
`demo.py`不保存正式批量入口的完整调用审计，也未绑定整题副本租约，因此这里只给单副本演示。
需要比较skill效果时使用下面的native入口，不把demo产物拼入正式成绩。

### 2.2 数据准备后，检查十任务推理路径

CrossVid预处理验收通过后，用正式批量入口每task运行1题，检查服务、媒体和结果保存：

```bash
python eval/agent_eval/run.py --config .local/actor-9b.yaml \
  --execution-config .local/execution-9b.yaml \
  --dataset-root "$DATA_ROOT" --benchmarks crossvid --limit 1 \
  --inference-only --output "$RUN_ROOT/first-crossvid-inference"
```

`--limit 1`在CrossVid上是十task各1题，共10题；这是按文件顺序取样的接入检查，不是随机评测。
预期`summary.json`为`inference_only: true, samples: 10, completed: 10`，
每份`records/crossvid/<sample_id>/result.json`为`status: ok`、`scoring_status: skipped`，有非空`prediction`与`events`。
`run_manifest.json`的completed状态本身不代替逐题成功检查。调用事件保留实际模型身份、输入哈希和token；
要测试选卡/注入，还需用第4节的带库配置在独立输出目录运行并检查`skill_selection`事件。
此命令不评分、不需要Judge；不要把它的summary当作准确率，也不能通过更改resume参数把它变成评分运行。
换成正式评测前另建output目录。遇到解码错误先核对数据准备验收，服务错误则查看`.cache/mvagent/`内服务日志。

### 2.3 做CCQA评分或rolewise前准备Judge

此时再固定Judge版本、下载权重并填写`JUDGE_GPU_IDS`。已有完整同版本权重时跳过下载：

```bash
hf download Qwen/Qwen3-30B-A3B-Instruct-2507 \
  --revision "${JUDGE_REVISION:?Set the full Judge commit}" --local-dir "$JUDGE_WEIGHTS"
```

以下仅生成端点清单，检查它与已有Actor配置不冲突：

```bash
: "${JUDGE_GPU_IDS:?Set available Judge GPU IDs, comma-separated}"
export JUDGE_GPU_IDS
export JUDGE_BASE_PORT=8200
python - <<'PY'
import os
from pathlib import Path
from urllib.parse import urlparse
import yaml
execution = yaml.safe_load(Path('.local/execution-9b.yaml').read_text())
actors = execution['model_pools']['qwen3_5_9b_local']['replicas']
actor_gpus = {gpu for replica in actors for gpu in replica['gpus']}
actor_ports = {urlparse(replica['endpoint']).port for replica in actors}
judge_gpus = [int(value) for value in os.environ['JUDGE_GPU_IDS'].split(',')]
assert min(judge_gpus) >= 0 and len(set(judge_gpus)) == len(judge_gpus), 'Invalid Judge GPUs'
assert not actor_gpus & set(judge_gpus), 'GPU conflict'
judge_ports = list(range(int(os.environ['JUDGE_BASE_PORT']), int(os.environ['JUDGE_BASE_PORT']) + len(judge_gpus)))
assert min(judge_ports) > 1023 and max(judge_ports) < 65536
assert not actor_ports & set(judge_ports), 'Port conflict'
Path('.local/judge-endpoints.txt').write_text(','.join(f'http://127.0.0.1:{port}/v1' for port in judge_ports))
PY
export JUDGE_ENDPOINTS="$(cat .local/judge-endpoints.txt)"
```

| 服务 | GPU索引 | endpoint | 启动方式 |
|---|---|---|---|
| Actor/Selector/Observer | `ACTOR_GPU_IDS`，每卡一个TP1副本 | 从`ACTOR_BASE_PORT`连续分配 | native runner自动准备 |
| CCQA Judge | `JUDGE_GPU_IDS`，每卡一个独立副本 | 从`JUDGE_BASE_PORT`连续分配 | 下方shell入口 |

```bash
export JUDGE_LOG_DIR="$RUN_ROOT/judge-logs"
bash eval/agent_eval/serve_ccqa_judge.sh "$JUDGE_GPU_IDS" "$JUDGE_BASE_PORT"
```

**要求命令成功返回后再运行rolewise。** 它在初始化Evaluator时就连接Judge，不支持完成全部Actor运行后才部署Judge。
每题固定在一个Actor副本，每副本并发1；实际副本数和GPU型号必须记录在新运行中。
固定Actor参数保持BF16、seed=0、temperature=0、thinking关闭、2048输出token、512帧、Global/Video各5步、prefix/MM processor cache关闭。
Actor接口只接受loopback；Actor客户端和模型服务须在同一主机/容器网络命名空间，不能直接改成跨服务器IP。
若已有兼容服务，可直接提供实际execution和`JUDGE_ENDPOINTS`并跳过启动：Actor必须通过本项目profile/权重校验，
Judge必须服务`Qwen3-30B-A3B-Instruct-2507`并采用官方配置。不要在同一Actor池上并行启动独立批处理器；
rolewise的资源数量必须在新运行前配置，未完成rolewise不能修改冻结execution。
独立native评估则允许中断后用相同输入/模型/评分配置加`--resume`，换GPU索引或副本数；每次execution会单独记录。
它也不支持运行中热扩缩，且不能借resume切换模型、数值profile、硬件协议或题目清单。

## 3. 选择冻结开发划分

接续已有结果时，优先使用随代码保存的原Train80/Cal40/Gate176清单，不重新抽样：

```bash
export STUDY_ROOT="$RUN_ROOT/new-skill-study"
mkdir "$STUDY_ROOT"
cp configs/skill_evolution/splits/research_train80_cal40_gate176.json "$STUDY_ROOT/split.json"
sha256sum "$STUDY_ROOT/split.json"
```

预期SHA256为 `794a66996f1e12fceea9e6c7f12fcd6416fb4704c6a96e573e715ae7a35b1a21`。
这296题已经反复用于开发，不能作为独立Test；365和400题的范围与来源重叠见[交接总表](research-handoff.md)。

只有实验计划明确需要**新的开发划分**时才使用下面的另选分支；输出到另一个文件，不覆盖原清单：

```bash
python scripts/prepare_crossvid_train_cal_gate_split.py \
  --qa-dir "$DATA_ROOT/crossvid/QA" \
  --exclude-panel configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json \
  --per-task 8,4,4 --seed 0 \
  --output "$STUDY_ROOT/new-split.json"
```

该配额得到Train80/Cal40/Gate40，每分区包含全部十task。它是接入开发规模，不能代替有统计功效的最终实验规模。
清单中 `train/cal/eval` 分别对应Train/Cal/Gate；不是把`eval`当成最终Test。
相同原视频/UAV序列经连通分组后只能进入一个分区；与Lite2500仅题号隔离，来源可能重叠并在输出中报告。
它也没有自动排除历轮296/365/400开发题，不能据此声称新的独立验证。需要独立确认时先确定合法来源及冻结清单。
当前按seed顺序贪心分配，配额无法满足会报错且不写输出；失败不证明其他分配一定不存在。
不要根据候选分数反复换seed。已有输出不可覆盖，历史九任务/date-seed清单保持原样。

## 4. 测量已有库与无反馈一次生成

重新生成不会复现某张历史卡。若目标是接续比较，先使用原字节发布的强一次生成库或首接受库：

```bash
export BANK_SHA=87c43278775a495f2d163356c8cefe73fce233b6f943c3734d1ae5d319345472
python - <<'PY'
import json
import os
from pathlib import Path
import yaml
from skill_evolution.infra.banks import BankSnapshot, runtime_with_bank

digest = os.environ['BANK_SHA']
bank = BankSnapshot((Path('src/mvagent/skills/skill_sets/research-20261022') / (digest + '.json')).absolute(), digest)
runtime = runtime_with_bank(yaml.safe_load(Path('.local/actor-9b.yaml').read_text()), bank)
path = Path(os.environ['STUDY_ROOT']) / ('runtime-' + digest + '.json')
with path.open('x') as stream:
    json.dump(runtime, stream, ensure_ascii=False, indent=2)
PY
```

首接受库SHA为 `4765323a0d13b5df3402a00b29fe242f0543dd6f82dc30377595e83668f2ad55`；换库时另建运行目录。
原始库通过SHA校验，完整库自然选卡，Video空库自动关闭。库用途与候选是否已验证见[交接总表](research-handoff.md)。

已有native evaluator可以直接运行，不新测空库：

```bash
python eval/agent_eval/run.py \
  --config "$STUDY_ROOT/runtime-$BANK_SHA.json" \
  --execution-config .local/execution-9b.yaml \
  --dataset-root "$DATA_ROOT" --benchmarks crossvid \
  --split-manifest "$STUDY_ROOT/split.json" \
  --defer-open-qa-judge --output "$STUDY_ROOT/gate-$BANK_SHA"
python eval/agent_eval/score_crossvid_ccqa.py \
  --output "$STUDY_ROOT/gate-$BANK_SHA" --qa-path "$DATA_ROOT/crossvid/QA/CCQA.json" \
  --endpoints "$JUDGE_ENDPOINTS"
python eval/agent_eval/finalize_results.py --output "$STUDY_ROOT/gate-$BANK_SHA"
```

native `--split-manifest`读取清单的`eval`部分，即这里的Gate176；没有`--split-name`参数。
最终分数读取`summary_scored.json`的`datasets.crossvid.official_task_macro`；检查十task覆盖和完成状态。
`summary.json`可能仍是CCQA deferred，不能当最终成绩。

### 4.1 复现CrossVid Lite2500

Gate176是研究开发面板，与历史全量比较使用的Lite2500不同。若要评测同一批2500题，保持前面的库配置和服务设置，改用以下明确清单：

```bash
python eval/agent_eval/run.py \
  --config "$STUDY_ROOT/runtime-$BANK_SHA.json" \
  --execution-config .local/execution-9b.yaml \
  --dataset-root "$DATA_ROOT" --benchmarks crossvid \
  --split-manifest configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json \
  --defer-open-qa-judge --output "$STUDY_ROOT/lite2500-$BANK_SHA"
python eval/agent_eval/score_crossvid_ccqa.py \
  --output "$STUDY_ROOT/lite2500-$BANK_SHA" --qa-path "$DATA_ROOT/crossvid/QA/CCQA.json" \
  --endpoints "$JUDGE_ENDPOINTS"
python eval/agent_eval/finalize_results.py --output "$STUDY_ROOT/lite2500-$BANK_SHA"
```

这是可选的完整评测，不是首次安装验收。预期2500题全部成功且239题CCQA评分完整；主分仍读`summary_scored.json`的十任务macro。
各任务题数和清单SHA见[split目录](../configs/skill_evolution/splits/README.md#crossvid-lite2500正式评测入口)。
不传清单时会运行全部CrossVid；不要用`--limit 2500`替代，也不要重新抽样或修改历史manifest。

### 4.2 生成一个新的对照库

由研究员使用自己的API凭据，通过环境变量注入 `DEEPSEEK_API_KEY` 或 `BIGMODEL_API_KEY`，不写入YAML、命令历史或Git。
默认DeepSeek-Flash配置是 `configs/skill_evolution/llm_generation.yaml`；GLM配置是 `glm_optimizer.yaml`，实际模型名为 `glm-5.3`。

```bash
python scripts/generate_skills.py \
  --config configs/skill_evolution/llm_generation.yaml \
  --runtime-config .local/actor-9b.yaml \
  --role both --max-cards 8 \
  --output-dir "$STUDY_ROOT/one-shot"
```

这条命令不调用Actor、Selector或Judge。每角色一次逻辑生成、最多8张卡，上限不是配额；不读取题目、轨迹或分数。
正常成功请求一次，客户端允许一次瞬时重试。输出目录必须不存在，无`--resume`。
完整成功后有`bank.json`、角色库、原始响应、源码/配置留存及`runtime_with_skills.json`。
后者保存库的绝对路径；移动库时需以原始库SHA重新生成新运行配置，不修改卡片正文或只搬旧部署JSON。
一次生成不自动送入rolewise作为初始库，也不保证准确率提升。

评测新生成库时，在前面的native命令中改用`$STUDY_ROOT/one-shot/runtime_with_skills.json`和新的output目录。
所有比较使用相同事前冻结清单；不要按中途成绩更换分区。

## 5. 从空库开始角色轮换

这是创建新实验的入口，不用于恢复父库4765或回放已结束的旧实验。
先确认Judge在线、数据预处理完成，并在第3节另选分支准备好新实验split。再运行：

```bash
python scripts/evolve_skills.py \
  --config configs/skill_evolution/evolution.yaml \
  --optimizer-config configs/skill_evolution/glm_optimizer.yaml \
  --runtime-config .local/actor-9b.yaml \
  --execution-config .local/execution-9b.yaml \
  --split-manifest "$STUDY_ROOT/new-split.json" \
  --dataset-root "$DATA_ROOT" \
  --judge-endpoints "$JUDGE_ENDPOINTS" \
  --output "$STUDY_ROOT/evolution"
```

默认2轮、每轮2候选：Global一轮、Video一轮。预算写在YAML，没有`--rounds`参数。
每个候选只能编辑一个角色的一张卡；伙伴库固定。Train可提供角色公开轨迹，Cal整库选优，Gate严格正增益才接受。
输出可能仍为空库。所有候选、拒绝和格式失败均保留，原始rollout先落盘，Judge错误报错而不记零分。

**fresh会先测空库Train/Cal/Gate。** 当前公开入口没有`--initial-bank`或`--reuse-baseline`，不能导入旧JSON冒充缓存命中。
已有同协议空库不应为试运行再测；如果目标只是比较已有两库，使用上一节native评估方式，不新建rolewise。
对新split/新环境是否需要新基线，应在实验计划中明确；本交接命令本身不授权在原开发面板重跑被排除的条件。

默认闭环仍使用`trajectory.examples()`的首尾截断；`infra.feedback.format_feedback()`已实现但仅用于诊断，尚未接入。
同轮后续提案可读取前一候选Train结果，跨轮失败经验尚未累计。不要把“反馈诊断运行完成”写成“新进化算法已实现”。

若不能访问外部API，rolewise可把optimizer配置替换为`configs/skill_evolution/local_optimizer.yaml`，并设置非空随机
`LOCAL_OPTIMIZER_API_KEY`环境值。它默认复用现有9B模型池的8100端口；若Actor端口起点不同，复制该配置到`.local/`并修改`api_base`。
入口会注册固定profile和grammar，不能添加独立未引用的小模型池。
一次生成入口没有这套本地池注册，不直接套用该配置。模型名、endpoint及runtime角色必须匹配，详见[方法README](../src/skill_evolution/README.md)。

## 6. 读取结果、恢复与结束

| rolewise目录内容 | 用途 |
|---|---|
| `manifest.json`、`configs/`、`frozen/src`、`frozen/eval` | 冻结身份、配置和实际运行源码 |
| `banks/<sha256>.json` | 每个完整候选库 |
| `rounds/*/proposal-*` | 输入、原始响应、格式校验与Train/Cal成绩 |
| `rounds/*/decision.json` | 接受/拒绝、父库和候选身份 |
| `evaluations/<bank>/<partition>/rollouts/records` | 原始逐题回答及轨迹 |
| `evaluations/<bank>/<partition>/evaluation.json` | 官方macro、逐题分数及raw哈希 |
| `judge_cache/`、`summary.json` | Judge留存与最终接受库/完整Gate得分 |

rolewise evaluator已逐分区完成CCQA评分，主分取`evaluation.json`的`score`（0–1），不是内层native尚deferred的summary。
一个运行成功只表示程序完成，不代表通过Gate或证明稳定收益；报告有效样本、全部尝试、官方macro、配对变化和分区来源。

同一未完成run在身份未变时：

```bash
python scripts/evolve_skills.py --output "$STUDY_ROOT/evolution" --resume
```

resume只接受上述参数，不接受新模型、split、execution。使用原run冻结源码，拒绝哈希变化；
缺少响应的中断API尝试不会自动重放。冻结记录包含数据、模型、库和endpoint等绝对路径，**没有自动路径重定位**。
换服务器时仅有Git源码不能恢复原run；需要完整原件、未改变的配置和可访问的原路径/等价挂载。
缺少这些条件时建立新run并记录协议差异，不修改manifest绕过检查。部分历史native源码曾归档，恢复前还需按原索引展开校验。
历史资源可用性以[本次交接总表](research-handoff.md)为准；旧[研究交接](skill-research-handoff-20261022.md)中的`/runs/devbox/...`是原环境路径，不能直接在新机照搬。

运行结束后，Actor服务通常仍驻留。只终止属于本实验的Actor/Judge进程，并用`nvidia-smi`确认内存释放；不要清理其他研究员的服务。
原始结果、媒体、权重和API凭据保存在新服务器的受控存储，不进入Git历史。代码、配置模板和可共享Markdown通过研究分支备份。

## 7. 新机最小验收

本次已完成的CPU检查见[交付核验](research-handoff.md#8-本次交付的核验与合并范围)。以下新硬件推理步骤仍由接手者执行；已有CPU检查无需因为日期变化重复。

先执行不调用模型的相关回归及语法检查，再运行事先确定的小规模十任务完整流程；不要为了交接重跑整个历史实验矩阵。

```bash
python -m compileall -q src scripts eval demo.py
python tests/test_crossvid_download.py
python tests/test_crossvid_split.py
PYTHONPATH=src:. python tests/test_agent_finalize.py
PYTHONPATH=src:. python tests/test_skill_evolution.py
PYTHONPATH=src:. python tests/test_skill_feedback.py
PYTHONPATH=src:. python tests/test_evolution_snapshot.py
```

需要复核真实服务profile、权重、输入哈希、选卡/注入事件、完整原始回答和CCQA评分。
不因新GPU上seed相同就假定输出与旧实验完全相同。新机实际输出尚未产生之前，这些步骤只能标记为操作指南，不能标记为已验收。
