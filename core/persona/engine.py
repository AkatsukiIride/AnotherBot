from core.persona import Persona

SYSTEM_PROMPT_TEMPLATE = """你是{name}。
{description}
你的性格: {personality}
当前场景: {scenario}

当前日期: {current_date}

时间推理规则:
- 以上面的当前日期为绝对参考，判断所有信息的时效性
- 当用户询问的事件日期已过，直接告知用户该事件已发生/已结束
- 当搜索结果中的"即将""未来"描述与日期矛盾，以日期为准
- 对比搜索结果中的信息发布日期与当前日期，如果信息较旧，主动说明"据X月份的报道..."

对话规则:
- 始终保持角色，不要跳出角色
- 使用口语化和短句回复，控制在1-3句话
- 不要使用过长的书面语表达
- 回复自然、有情感、有温度
- 遇到你不知道的事实类问题，诚实说不知道，不要编造

{custom_prompt}

{post_instructions}

对话示例 (参考语气和风格):
{example_dialogue}"""


PLATFORM_HINTS = {
    "bilibili_live": "\n(B站弹幕模式：只说一句话，不超过20字。不写动作描写，不加括号，不用引号。像发微信一样随意简短。)",
    "bilibili_comment": "\n(B站评论区：不能用图片或表情包编号，用颜文字表达情绪)",
    "bilibili_session": "\n(B站私信：可正常对话，表情包功能受限制)",
}


class PersonaEngine:
    """Character card engine — builds System Prompt from Persona"""

    def build_system_prompt(self, persona: Persona, platform: str = "") -> str:
        from datetime import datetime
        now = datetime.now().strftime("%Y年%m月%d日 %A")
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            name=persona.name,
            description=persona.description or f"一个名为{persona.name}的AI助手",
            personality=persona.personality or "友好、乐于助人",
            scenario=persona.scenario or "正在和用户聊天",
            current_date=now,
            custom_prompt=persona.custom_prompt or "",
            post_instructions=persona.post_instructions or "",
            example_dialogue=persona.example_dialogue or "",
        )
        if platform in PLATFORM_HINTS:
            prompt += PLATFORM_HINTS[platform]
        return prompt
