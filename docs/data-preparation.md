# 数据获取与预处理：普通服务器交接

本文从官方数据下载到 MVAgent 可读取的输入，命令均在**接手研究员有权限的计算服务器**运行，不依赖 Modal、旧 `/assets` 路径或原作者的私有启动器。先按[根 README](../README.md#installation)安装项目环境，在仓库根目录执行命令。

继续 skill 研究只需先准备 **CrossVid**。CVBench 与 MVU-Eval 留作最终跨 benchmark 评估，不向 skill optimizer 提供它们的轨迹。下载、解压和视频预处理需要网络、CPU、磁盘与编解码器，但不调用模型、不需要 GPU。

## 1. 官方来源、版本和容量

2026-10-22 核对了以下官方仓库链接、Hugging Face 文件树及只读 API。三个数据仓库当时均为公开、未设访问申请门槛；网络限流时可使用接手者自己的 Hugging Face 账号。遵循数据卡及原始视频来源的使用条款，不将媒体重新上传至本项目 GitHub。

| 数据 | 官方入口 | 固定下载 revision | 上游标示体积 |
|---|---|---|---:|
| CrossVid，9015 题、十任务 | [官方代码](https://github.com/chuntianli666/CrossVid)、[数据文件](https://huggingface.co/datasets/Chuntianli/CrossVid/tree/4cc98eee034e6f3950c19803485402661f54c1f8) | `4cc98eee034e6f3950c19803485402661f54c1f8`，另须下节历史 BU 补全 | 当前约 312 GB，加恢复媒体 3.44 GB |
| **多视频** CVBench，1000 题、15 子任务 | [官方代码](https://github.com/Hokhim2/CVBench)、[数据文件](https://huggingface.co/datasets/Dongyh35/CVBench/tree/81dfee5940506da256e3d52b76087307d2fe20f7) | `81dfee5940506da256e3d52b76087307d2fe20f7` | `CVBench.zip` 约 40.4 GB |
| MVU-Eval，1824 题、八任务 | [官方代码](https://github.com/NJU-LINK/MVU-Eval)、[数据文件](https://huggingface.co/datasets/MVU-Eval-Team/MVU-Eval-Data/tree/e449b251501e2d4f46efc3f7e3d1e0dc6e8644c7) | `e449b251501e2d4f46efc3f7e3d1e0dc6e8644c7` | 约 21 GB |

这里的 CVBench 是 *Evaluating Cross-Video Synergies for Complex Multimodal Understanding and Reasoning*，不是图像 CV-Bench，也不是其他同名跨视角或视频生成 benchmark。

**这些 revision 是本次交接核实的固定下载点，尚未证明与历史 Modal 数据逐字节一致。** 要复现历史分数，仍须核对旧数据/媒体哈希；若旧清单不可取，记录为新服务器上的固定协议复测，不能声称精确重现原输入。CVBench 标注继续使用仓库已冻结的 `eval/agent_eval/metadata/CVBench.json`，来源 commit 见[元数据说明](../eval/agent_eval/metadata/README.md)。不要无声替换成最新标注。

上述体积不包括 ZIP 解压副本、CrossVid 衍生片段、模型权重、缓存和实验轨迹。历史 CrossVid 衍生媒体约 **464 GB**；完整原始加衍生约 **780 GB**，再加其他 benchmark、权重、实验结果及空间余量。不要按当前 Hub 的 312 GB 准备磁盘。开始前同时检查字节容量和 inode：

```bash
export DATA_ROOT=/srv/mvagent/data
export DOWNLOAD_ROOT=/srv/mvagent/downloads
mkdir -p "$DATA_ROOT" "$DOWNLOAD_ROOT"
df -h "$DATA_ROOT"
df -i "$DATA_ROOT"
hf --help
ffmpeg -version
```

`hf` 是 [Hugging Face 官方 CLI](https://huggingface.co/docs/huggingface_hub/guides/cli)。如未安装，在计算服务器按其官方安装说明配置独立下载工具；不要为了下载升级项目已固定的模型依赖。本文使用的 `--repo-type dataset`、`--revision`、`--include`、`--local-dir` 均为官方参数。下载中断后重复**同 revision、同目标目录**的命令，可复用已下载文件；不要用普通 Git 克隆只得到媒体的 LFS 指针。

## 2. CrossVid：先准备研究主线

### 必须补全的上游缺口

**直接下载当前 CrossVid `main` 不完整。** 对固定当前版本与历史版本做全文件名差集，确认缺失的原始媒体是 `videos/behavior/` 下 **2416 个 MP4，共 3,441,176,514 字节**，影响 BU。`QA/`、`uav/` 和其他三类 `videos/` 没有删路径；另外删除的 `eval/`、`results/` 不属于 MVAgent 必需输入，不恢复它们。

恢复来源为同一个官方数据仓库的历史 commit：

```text
repo: Chuntianli/CrossVid
revision: 136f2c09694cc20378f32a9d1a7c3727d7db9879
prefix: videos/behavior/
```

[历史文件树](https://huggingface.co/datasets/Chuntianli/CrossVid/tree/136f2c09694cc20378f32a9d1a7c3727d7db9879/videos/behavior)和该 revision 的 Hub 元数据共同提供每个文件的大小及 LFS SHA256。例如：

| 文件（相对 `videos/behavior/`） | 字节数 | 上游 LFS SHA256 |
|---|---:|---|
| `00HFP.mp4` | 1,593,232 | `12c089d054fc984162ccb7af948c120166d4adafabb17073a39521b703b011fd` |
| `00SL4.mp4` | 265,106 | `8b395408d85ffbd03e9b9deb116b74524e9f86c4072bb1ed69ce3b36a61f1b9b` |

历史恢复文件仍属于其原始视频来源；此处从作者公开保留的历史 revision 下载，不自行镜像或替换成其他视频。

### 一条命令完成下载、补全、核验、预处理

配置好项目 Python 环境和存储后，推荐直接执行：

```bash
python scripts/prepare_crossvid_data.py \
  --root "$DATA_ROOT/crossvid" \
  --download-workers 4 --pea-jobs 4 --uav-jobs 4
```

该入口复用 `huggingface_hub` 的成熟下载能力，依次：

1. 从固定当前 revision 下载 `QA/`、`videos/`、`uav/` 和数据说明。
2. 从上述历史 revision **只补** `videos/behavior/`。
3. 对历史 2416 个文件逐一核对大小与 LFS SHA256，检查当前 BU 的视频引用全部被覆盖；失败立即停止。
4. 保存 `.mvagent_download/sources.json`，其中包含两套 revision、2416 条完整路径/字节数/SHA256 清单和核验范围。
5. 调用 `eval/data_preparation/crossvid_batch.py`，生成完整 `qa.jsonl`、派生媒体与 `validation.json`。

相同命令可以续跑；不会仅因旧文件存在就跳过历史媒体的 SHA 检查。其他原始媒体由固定 revision 的 Hub 下载流程负责下载完整性，再由既有预处理检查引用；该入口没有对全部约 312 GB 原始文件额外做一次本地 SHA 扫描，也不保证所有媒体解码无误。网络或校验失败不会继续到模型推理。

### 分步操作与排查

先下载标注，检查来源和题目数量；这一步没有下载数百 GB 媒体：

```bash
export CROSSVID_REVISION=4cc98eee034e6f3950c19803485402661f54c1f8
hf download Chuntianli/CrossVid --repo-type dataset \
  --revision "$CROSSVID_REVISION" \
  --include 'QA/*' 'README.md' \
  --local-dir "$DATA_ROOT/crossvid"

python - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ['DATA_ROOT']) / 'crossvid' / 'QA'
expected = {'BU': 848, 'CC': 798, 'CCQA': 872, 'FSA': 2248,
            'MOC': 566, 'MSR': 594, 'NC': 1221, 'PEA': 953,
            'PI': 251, 'PSS': 664}
actual = {task: len(json.loads((root / f'{task}.json').read_text()))
          for task in expected}
assert actual == expected, (actual, expected)
print(actual, 'total=', sum(actual.values()))
PY
```

确认服务器容量后，分两条命令下载原始媒体；第二条恢复不可省略：

```bash
hf download Chuntianli/CrossVid --repo-type dataset \
  --revision "$CROSSVID_REVISION" \
  --include 'QA/*' 'videos/*' 'uav/*' 'README.md' \
  --local-dir "$DATA_ROOT/crossvid"

hf download Chuntianli/CrossVid --repo-type dataset \
  --revision 136f2c09694cc20378f32a9d1a7c3727d7db9879 \
  --include 'videos/behavior/*' \
  --local-dir "$DATA_ROOT/crossvid"
```

以上分步 `hf` 命令没有生成本项目的历史文件 SHA 核验回执；需要该回执时运行一键入口，它会复用下载缓存并完成核验。

数据目录必须保持上游相对路径与大小写：

```text
DATA_ROOT/crossvid/
├── QA/                   # BU/CC/CCQA/FSA/MOC/MSR/NC/PEA/PI/PSS.json
├── videos/
│   ├── assembly/
│   ├── behavior/
│   ├── cook/
│   └── movie/
└── uav/
    ├── bbox/1/、bbox/2/   # 标注 JSON
    └── frames/1/、frames/2/  # 按序列分目录的原始帧
```

然后运行已有的可续跑包装器：

```bash
python eval/data_preparation/crossvid_batch.py \
  --root "$DATA_ROOT/crossvid" \
  --pea-jobs 4 --uav-jobs 4
```

`4 + 4` 是两个媒体任务组的并行 worker 数，应按服务器 CPU/RAM 下调。它会先并行生成装配片段和 UAV 带框视频，再串行生成完整 manifest。需要观察进度时读取 `crossvid/.mvagent_prepare/crossvid_qa/status.json` 和 `logs/`。中断后确认旧任务已经停止，再重复同一条命令，已完成的非空衍生媒体会被复用。

**成功条件是本次准备命令退出码为 0，且本次状态为 `complete`。** 仅看到 `validation.json` 或 `qa.jsonl` 存在不够：复跑失败可能留下上一次成功的文件；下载阶段失败甚至还未更新预处理状态。命令成功返回后，在同一环境检查：

```bash
python - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ['DATA_ROOT']) / 'crossvid'
state_dir = root / '.mvagent_prepare' / 'crossvid_qa'
status = json.loads((state_dir / 'status.json').read_text())
assert status['state'] == status['phase'] == 'complete', status
validation = json.loads((state_dir / 'validation.json').read_text())
assert status['validation'] == validation
assert validation['sample_count'] == 9015 and len(validation['task_counts']) == 10
metadata = json.loads((root / 'qa.meta.json').read_text())
assert metadata['scope'] == 'full'
assert metadata['sample_count'] == validation['sample_count']
assert metadata['manifest_sha256'] == validation['manifest_sha256']
print('Completed:', status['completed_at'])
print('Samples:', validation['sample_count'], 'Tasks:', validation['task_counts'])
print('Manifest SHA256:', validation['manifest_sha256'])
PY
```

确认打印的完成时间对应本次运行，并保存该时间、题数和哈希。若状态为 `failed`，先看 `status.json` 的 `error` 以及 `logs/` 中对应 worker 或 `finalize.log`；未完成时不要启动评测。以上只读取已有验收记录，不重新扫描媒体或计算 manifest 哈希。

输出及其用途：

| 路径（相对 `crossvid/`） | 内容 |
|---|---|
| `qa.jsonl` | 9015 个规范样本；ID 为 `crossvid:<task>:<id>`，媒体路径相对本目录 |
| `qa.meta.json` | manifest 哈希、输入协议、题数和任务计数 |
| `.mvagent_media/PEA/` | 按题目给定区间截取的装配视频 |
| `.mvagent_media/PI/`、`.mvagent_media/PSS/` | 电影开头/结尾与打乱步骤对应片段 |
| `.mvagent_media/uav_question_boxes/` | MOC/MSR 两视角视频，按题目标记对象 |
| `.mvagent_prepare/crossvid_qa/validation.json` | 完整 manifest、必需字段、引用文件非空及元数据一致性验收 |

预处理保留当前固定 `mvagent_question_boxes` 协议：UAV 按 **10 FPS**、最长边 **960** 生成视频，所指对象在**首次可见的一秒内**显示彩框与编号，视频 ID 为 `view_A`、`view_B`。首次可见不等于整段视频最开始的一秒。PEA/PI/PSS 根据各自标注截取，不将所有原视频统一重编码。模型每次调用的 **512 帧/448 最长边**属于另外一层推理限制，不要与这里的衍生媒体参数混淆。

下层 CLI `eval/data_preparation/crossvid.py crossvid` 可按 `--tasks`、`--ids` 准备局部输入；其输出带局部 scope，不能替代正式完整 manifest。它及帧编码、标框、协议实现在`eval/data_preparation/`，一键入口会调用，无需逐个执行。复现旧分数时不要换成 `current_text_bbox` 或自行改帧率。更换上游数据或处理协议应使用新的数据派生目录，因为当前续跑逻辑主要复用“文件存在且非空”的结果，不会自动证明旧衍生文件适配新输入。

验收通过说明字段、文件引用和 manifest 一致；**不等于每个视频所有帧都已成功解码，也不等于与旧服务器媒体字节一致。** 目标服务器的实际模型小实验应按交接运行指南另行验收。

## 3. 最终评估时再准备 CVBench 与 MVU-Eval

### CVBench

下载官方 ZIP；标注已在本仓库冻结，无需安装或复制 CVBench/Video-R1 的训练、推理代码：

```bash
hf download Dongyh35/CVBench CVBench.zip --repo-type dataset \
  --revision 81dfee5940506da256e3d52b76087307d2fe20f7 \
  --local-dir "$DOWNLOAD_ROOT/cvbench"
mkdir -p "$DATA_ROOT/cvbench"
unzip -q "$DOWNLOAD_ROOT/cvbench/CVBench.zip" -d "$DATA_ROOT/cvbench"
test -f "$DATA_ROOT/cvbench/0/0Hd95ulYOT8.mp4"
```

当前 ZIP 的视频使用数字目录加文件名，例如 `0/0Hd95ulYOT8.mp4`。本次仅只读检查了 ZIP 尾部中央目录，没有下载/解压完整包；下载后以最后一行及下方全引用校验确认布局。若解压工具额外套了一级目录，应让 `DATA_ROOT/cvbench` 对应实际包含数字目录的一层，不要修改标注中的所有视频路径来适配错误的根目录。

历史官方包中 `125/RQorrnJIc2Q.mp4` 在 26,214,400 字节处截断，影响 `cvbench:64`、`65`、`66`，过去报告基于 997 道可测题。新下载时核对该文件；不要把“文件存在”当成可完整解码，也不要自动改写/裁短视频或删除这三条标注来掩盖失败。保留原始 1000 题清单，报告真实成功数及工程失败；若采用与历史相同的 997 题比较，明确列出排除项。另有 `cvbench:431` 原选项标签缺陷，沿用原题并披露，不静默修题后与历史分数对比。历史来源见[实验记录](experiments.md)。

### MVU-Eval

官方媒体已经按 QA 所需的相对路径提供，不需要重新从原视频网站抓取。只取输入文件，不下载上游推理代码：

```bash
hf download MVU-Eval-Team/MVU-Eval-Data --repo-type dataset \
  --revision e449b251501e2d4f46efc3f7e3d1e0dc6e8644c7 \
  --include '*.mp4' 'MVU_Eval_QAs.json' 'README.md' \
  --local-dir "$DATA_ROOT/mvu-eval"
```

`*.mp4` 的 Hub 文件匹配包含子目录。保留 `temp_cap_filling-videos/`、`temp_grounding-videos/`、`temp_ordering-videos/`、`video_editing-video/` 等原目录，不把所有视频拍平成一层。原始 `MVU_Eval_QAs.json` 是按 ID 索引的对象，不能直接改名成 MVAgent 的 `QAs.json`。

### 生成两套 `QAs.json`

两套媒体都准备好后运行：

```bash
python scripts/prepare_cvbench_mvu_qas.py \
  --mvu-source "$DATA_ROOT/mvu-eval/MVU_Eval_QAs.json" \
  --cvbench-output "$DATA_ROOT/cvbench/QAs.json" \
  --mvu-output "$DATA_ROOT/mvu-eval/QAs.json" \
  --cvbench-media-root "$DATA_ROOT/cvbench" \
  --mvu-media-root "$DATA_ROOT/mvu-eval"
```

预期打印 CVBench **1000 rows**、MVU-Eval **1824 rows**。脚本转换官方字段，不调用模型；检查 ID 不重复、存在视频/选项以及每个媒体引用的文件存在。它**不检查完整视频解码**，也不会修复上述 CVBench 媒体。当前 CLI 一次生成两套清单；仅推进 CrossVid 时无需调用它。

最终布局：

```text
DATA_ROOT/
├── crossvid/
│   ├── QA/、videos/、uav/
│   ├── .mvagent_media/
│   └── qa.jsonl、qa.meta.json
├── cvbench/
│   ├── QAs.json
│   └── 0/、1/、10/、.../      # 直接是数字媒体目录
└── mvu-eval/
    ├── MVU_Eval_QAs.json、QAs.json
    ├── *.mp4
    └── temp_*-videos/、video_editing-video/
```

CVBench/MVU 的 `QAs.json` 中视频路径均相对其 benchmark 根目录，**不是再拼一层 `videos/`**。运行时传 `--dataset-root "$DATA_ROOT"`，不要传某一套 benchmark 的子目录。

按需要准备各数据集：CrossVid使用前文的完整验收，CVBench/MVU使用转换器的引用检查。不再保留要求三套数据同时齐全的重复批量包装器。

## 4. 题目划分与后续实验的边界

- 复现 Lite2500 使用[冻结manifest](../configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json)，十任务配额和SHA见[清单说明](../configs/skill_evolution/splits/README.md#crossvid-lite2500正式评测入口)。它与`eval/crossvid_2500.json`的题号集合一致、顺序不同；新评测统一用manifest，不重新抽样。Lite2500已用于开发，不能包装成新的盲Test。
- 角色轮换研究以十任务 macro 为主指标。本次交接已将 `prepare_crossvid_train_cal_gate_split.py` 修正为抽取**全部十任务（含 CCQA）**、默认 seed 为 0，并拒绝覆盖现有输出；旧版本仅抽九类闭式任务。默认 `--per-task 8,4,4` 生成新的 80/40/40 开发划分，不是历史 80/40/176。它按原始文件或 UAV 序列建立连通组，隔离新 Train/Cal/Gate，排除 Lite2500 题号但只报告与 Lite2500 的来源重叠。具体命令见[新服务器运行指南](server-runbook.md)；不能把旧九任务 manifest 改名冒充十任务划分。
- 旧题号池与九任务划分只保留为历史产物；它们不是当前进化器要求的十任务Train/Cal/Gate，不再提供重建这些旧条件的脚本。
- 历史 Train80/Cal40/Gate176、补充365及最新400的实际题号、来源重叠与可获取状态，见[研究交接](skill-research-handoff-20261022.md)和[后续反馈实验](skill-feedback-iteration-20261022.md)。不能根据题数重新抽出另一批题后仍称历史面板。
- 新划分默认抽样 seed 为 0，已有冻结划分保留原 seed。来源共享的题不能只靠题号去重就声称视频独立；用统一完整来源图检查，并分别披露 ID 重叠和来源重叠。

本指南核实了官方链接、固定版本、代码接口与 ZIP 局部目录。没有在新服务器下载全部媒体、重做预处理或运行推理；其后续验收结果需由接手研究员追加到运行记录。


## 本次交接的实际验证

纯CPU任务已实际读取历史2416项清单，核对总大小3441176514字节，下载`00HFP.mp4`并按上表大小/SHA校验；当前BU的848题引用全部被恢复清单覆盖。十类真实QA也已读入，新split入口成功生成80/40/40。测试没有启动GPU、模型或Judge。

完整数据下载与衍生媒体预处理尚未在新服务器执行，不能把这个单文件烟测当成约780GB输入链路全部验证。对应CPU回归与限制见[交付核验](research-handoff.md#8-本次交付的核验与合并范围)。
