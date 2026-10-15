
当前 Skill 长度规则：两个文本字段合计最多 **1200 words**，when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。
