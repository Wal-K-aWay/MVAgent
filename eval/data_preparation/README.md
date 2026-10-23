# 媒体预处理实现

公开下载入口是[`scripts/prepare_crossvid_data.py`](../../scripts/prepare_crossvid_data.py)，
具体数据来源、参数、续跑与验收见[数据指南](../../docs/data-preparation.md)。

```text
scripts/prepare_crossvid_data.py
  → crossvid_batch.py       并发处理、续跑、完整manifest验收
    → crossvid.py          按题生成qa.jsonl、元数据和衍生媒体
      → frames.py          帧序列编码
      → question_boxes.py  问题指定的UAV对象标框
      → crossvid_protocol.py  输入文本与协议
```

这些是同一条数据准备链的内部实现，不是需要依次手动执行的五个工具。
已有完整原始数据时可直接运行`python eval/data_preparation/crossvid_batch.py --root /path/to/crossvid`，
跳过下载。不要与一键入口并发处理同一目录。
当前数据准备与模型推理分离，不被Actor/skill算法导入；推理run保存预处理后的数据身份。
历史源文件名和旧入口仍可从Git历史恢复，未保留转发兼容脚本。
