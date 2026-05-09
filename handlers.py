"""
触发执行器：到点后实际"做事"的地方

三种类型，全部通过 plugin_sdk 的 send_message 触发宿主应用 voiceChat 完整链路
（LLM 推理 + 工具调用 + TTS 播报），让 AI 用人格化的口吻说出来
"""

import datetime
import logging
import random
from typing import Optional

logger = logging.getLogger("timed-tasks.handlers")

# 默认提醒文案（用户没填模板 / 不启用上下文时备用）
_DEFAULT_REMINDER_STYLES = [
    "嘿，{user_name}！这是你设置的提醒：{text}",
    "提醒时间到了：{text}",
    "别忘了：{text}",
    "温馨提醒，{user_name}：{text}",
    "时间到啦，{text}",
    "叮咚！{text}",
]


class ReminderHandlers:
    """三个执行器合一的轻量类（不必拆三个 class，逻辑都很短）"""

    def __init__(self, context, config: dict):
        """
        Args:
            context: plugin_sdk PluginContext 实例
            config: 插件配置（已 flatten 的 dict）
        """
        self.context = context
        self.config = config

    # ============================================================
    # reminder：到点用 AI 口吻提醒
    # ============================================================

    async def execute_reminder(self, reminder: dict):
        text = reminder.get("text", "")
        user_name = reminder.get("user_name", "用户")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        logger.info(f"触发提醒: {text}")

        prompt = await self._build_reminder_prompt(reminder, text, user_name, now_str)
        self.context.send_message(prompt)

    async def _build_reminder_prompt(self, reminder: dict, text: str, user_name: str, now_str: str) -> str:
        # 启用上下文：拿最近 N 条对话拼自然语境
        if self.config.get("enable_context", True):
            try:
                messages = await self.context.get_messages()
                max_n = int(self.config.get("max_context_count", 5))
                recent = [m for m in messages[-max_n * 2:] if m.get("role") in ("user", "assistant")]

                if len(recent) >= 2:
                    return (
                        f"你现在需要向 {user_name} 发送一条预设提醒。\n"
                        f"当前时间是 {now_str}\n"
                        f"提醒内容：{text}\n\n"
                        f"考虑到刚才的对话，请用你平时的语气自然地说出这条提醒。"
                        f"如果与刚才的话题有关联可以衔接；无关就用过渡语带入。"
                        f"直接说提醒内容，不要解释这是预设。"
                    )
            except Exception as e:
                logger.warning(f"获取对话历史失败，回退模板: {e}")

        # 不启用上下文 / 上下文太短：用模板
        template = self.config.get("reminder_prompt_template")
        if template:
            try:
                return template.format(
                    user_name=user_name, reminder_text=text, current_time=now_str
                )
            except Exception:
                pass

        sample = random.choice(_DEFAULT_REMINDER_STYLES).format(user_name=user_name, text=text)
        return (
            f"你需要提醒用户「{text}」。"
            f"请用你平时的口吻自然地说出来，可以参考但不限于这种说法：「{sample}」。"
            f"直接说提醒，不要解释这是预设。"
        )

    # ============================================================
    # task：到点让 AI 自动执行（可调任意工具）
    # ============================================================

    async def execute_task(self, reminder: dict):
        text = reminder.get("text", "")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        logger.info(f"触发任务: {text}")

        template = self.config.get("task_prompt_template")
        if template:
            try:
                prompt = template.format(task_text=text, current_time=now_str)
            except Exception:
                prompt = f"[定时任务触发] 请执行：{text}"
        else:
            prompt = f"[定时任务触发] 请执行：{text}。直接执行并把结果用你的口吻告诉用户。"

        self.context.send_message(prompt)

    # ============================================================
    # command：到点调用某个 LLM 工具
    # ============================================================

    async def execute_command_task(self, reminder: dict):
        """
        reminder 期望字段：
            text:        描述（用于 prompt 给 AI 看的解释）
            tool_name:   要调用的 LLM 工具名（必填）
            description: 任务描述（可选，备用 text）
        """
        tool_name = reminder.get("tool_name", "").strip()
        if not tool_name:
            logger.error(f"指令任务缺少 tool_name: {reminder}")
            return

        description = reminder.get("description") or reminder.get("text", "")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        logger.info(f"触发指令任务: tool={tool_name}, desc={description}")

        template = self.config.get("command_prompt_template")
        if template:
            try:
                prompt = template.format(
                    tool_name=tool_name, description=description, current_time=now_str
                )
            except Exception:
                prompt = f"请调用工具 {tool_name} 完成：{description}"
        else:
            prompt = (
                f"[定时任务触发] 请调用工具 {tool_name} 完成「{description}」，"
                f"并把结果用你的口吻自然地告诉用户。"
            )

        self.context.send_message(prompt)
