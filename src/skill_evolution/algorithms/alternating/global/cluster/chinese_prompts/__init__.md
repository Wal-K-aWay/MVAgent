# Prompt 拼接中文镜像
阶段只有reflect、generator、reviser。
reflect System=TASK+BACKGROUND；User为公开证据文本。
generator/reviser System=TASK+BACKGROUND+CARD_CONTRACT；User使用对应Train card-authoring input模板，{context}为动态公开材料。
CARD_CONTRACT两字段规范供完整卡作者使用，含strong example和weak example；无独立CARD_EXAMPLE或metadata作者。
