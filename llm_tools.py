"""
LLM 工具定义和路由

让 AI 通过自然语言对话来增删改查定时任务
"""

import datetime
import logging
from typing import Optional

from utils import (
    parse_datetime_for_llm,
    save_reminder_data_sync,
    check_reminder_limit,
    is_outdated,
)

logger = logging.getLogger("timed-tasks.llm_tools")

# 单一 group 名（桌面单用户场景，无需会话隔离）
GROUP = "local"

REPEAT_TYPES = ["none", "daily", "weekly", "monthly", "yearly"]
HOLIDAY_TYPES = ["", "workday", "holiday"]


def _normalize_repeat(repeat: Optional[str], holiday_type: Optional[str]) -> str:
    """组合 repeat + holiday_type，例如 daily + workday → 'daily_workday'"""
    repeat = (repeat or "none").strip().lower()
    holiday_type = (holiday_type or "").strip().lower()

    if repeat not in REPEAT_TYPES:
        repeat = "none"
    if holiday_type and holiday_type not in ("workday", "holiday"):
        holiday_type = ""

    if repeat == "none" or not holiday_type:
        return repeat
    return f"{repeat}_{holiday_type}"


# ============================================================
# 工具定义（OpenAI function calling 格式）
# ============================================================

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "timed_add_reminder",
            "description": (
                "添加一个定时提醒。到点后 AI 会用自己的口吻说出提醒内容。"
                "适合「提醒我做某事」类的需求，如「每天早上 8 点提醒我喝水」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "提醒内容"},
                    "datetime_str": {
                        "type": "string",
                        "description": "提醒时间，格式 YYYY-MM-DD HH:MM，如 2026-05-02 08:00",
                    },
                    "repeat": {
                        "type": "string",
                        "enum": REPEAT_TYPES,
                        "description": "重复类型，none=一次性",
                    },
                    "holiday_type": {
                        "type": "string",
                        "enum": ["", "workday", "holiday"],
                        "description": "仅当重复时生效。workday=仅工作日，holiday=仅法定节假日",
                    },
                    "user_name": {"type": "string", "description": "称呼，可选，默认「用户」"},
                },
                "required": ["text", "datetime_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timed_add_task",
            "description": (
                "添加一个定时任务。到点后 AI 会自动执行（可调用其他工具）。"
                "适合「到点帮我做某事」类的需求，如「每天中午 12 点帮我汇总今日新闻」。"
                "和提醒的区别：提醒只是说一句话；任务会让 AI 主动完成一件事。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "任务描述（让 AI 看的，写清要做什么）"},
                    "datetime_str": {"type": "string", "description": "时间 YYYY-MM-DD HH:MM"},
                    "repeat": {"type": "string", "enum": REPEAT_TYPES},
                    "holiday_type": {"type": "string", "enum": ["", "workday", "holiday"]},
                },
                "required": ["text", "datetime_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timed_add_command_task",
            "description": (
                "添加定时调用某个工具的任务。到点后 AI 会自动调用指定的工具，并把结果告诉用户。"
                "适合「到点帮我查 X」类的需求，如「每天 9 点查天气」可以调用 beichen_weather_reminder 工具。"
                "如果你不确定有哪些工具可用，用 timed_add_task 让 AI 自己决定。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "要调用的工具名"},
                    "description": {"type": "string", "description": "任务描述（用于 prompt）"},
                    "datetime_str": {"type": "string", "description": "时间 YYYY-MM-DD HH:MM"},
                    "repeat": {"type": "string", "enum": REPEAT_TYPES},
                    "holiday_type": {"type": "string", "enum": ["", "workday", "holiday"]},
                },
                "required": ["tool_name", "description", "datetime_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timed_list",
            "description": "列出所有定时任务（提醒、任务、指令任务）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "enum": ["all", "reminder", "task", "command"],
                        "description": "筛选类型，默认 all",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timed_delete",
            "description": "按条件删除定时任务。可以按 id、关键词或全部删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "任务序号（来自 timed_list 的结果）"},
                    "keyword": {"type": "string", "description": "按内容关键词模糊匹配"},
                    "delete_all": {"type": "boolean", "description": "是否清空所有任务，默认 false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timed_update",
            "description": "修改指定 id 的任务（时间或内容）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "任务序号"},
                    "new_text": {"type": "string", "description": "新内容（可选）"},
                    "new_datetime_str": {"type": "string", "description": "新时间 YYYY-MM-DD HH:MM（可选）"},
                },
                "required": ["id"],
            },
        },
    },
]


# ============================================================
# 路由实现
# ============================================================

def _now_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _list_all(reminder_data: dict) -> list:
    """把 reminder_data 拍平成有序列表，每项加上稳定 id"""
    out = []
    items = reminder_data.get(GROUP, [])
    for i, r in enumerate(items, start=1):
        out.append((i, r))
    return out


def _format_one(idx: int, r: dict) -> str:
    rtype = r.get("type", "reminder")
    type_label = {"reminder": "提醒", "task": "任务", "command": "指令任务"}.get(rtype, rtype)
    repeat_raw = r.get("repeat", "none")
    repeat_label = {
        "none": "一次性",
        "daily": "每天",
        "daily_workday": "每工作日",
        "daily_holiday": "每节假日",
        "weekly": "每周",
        "weekly_workday": "每周工作日",
        "weekly_holiday": "每周节假日",
        "monthly": "每月",
        "monthly_workday": "每月工作日",
        "monthly_holiday": "每月节假日",
        "yearly": "每年",
        "yearly_workday": "每年工作日",
        "yearly_holiday": "每年节假日",
    }.get(repeat_raw, repeat_raw)

    extra = ""
    if rtype == "command":
        extra = f"  [tool: {r.get('tool_name', '?')}]"

    return f"  [{idx}] [{type_label}] {r.get('text', '')}  ({r.get('datetime', '?')} · {repeat_label}){extra}"


# ----- add 系列 -----

async def _add_item(plugin, item_type: str, params: dict, extra_fields: Optional[dict] = None) -> str:
    """统一的添加逻辑"""
    text = (params.get("text") or params.get("description") or "").strip()
    if not text:
        return "添加失败：内容不能为空"

    datetime_str = params.get("datetime_str", "").strip()
    if not datetime_str:
        return "添加失败：缺少时间"

    try:
        parsed = parse_datetime_for_llm(datetime_str)
    except ValueError as e:
        return f"添加失败：{e}"

    repeat = _normalize_repeat(params.get("repeat"), params.get("holiday_type"))

    can_create, err = check_reminder_limit(plugin.reminder_data, plugin.cfg.get("max_tasks", 50))
    if not can_create:
        return err

    item = {
        "type": item_type,
        "text": text,
        "datetime": parsed,
        "repeat": repeat,
        "user_name": params.get("user_name", "用户"),
        "created_at": _now_iso(),
    }
    if extra_fields:
        item.update(extra_fields)

    plugin.reminder_data.setdefault(GROUP, []).append(item)

    # 注册到调度器
    try:
        dt = datetime.datetime.strptime(parsed, "%Y-%m-%d %H:%M")
        # 重复任务但 dt 已过：只过期一次性任务，重复任务下次仍会触发
        if repeat == "none" and is_outdated(item):
            plugin.reminder_data[GROUP].pop()
            return "添加失败：时间已过"

        job_id = plugin.scheduler.add_job(GROUP, item, dt)
        item["job_id"] = job_id
    except Exception as e:
        logger.error(f"调度器注册失败: {e}", exc_info=True)
        plugin.reminder_data[GROUP].pop()
        return f"添加失败：{e}"

    save_reminder_data_sync(plugin.data_file, plugin.reminder_data)

    type_label = {"reminder": "提醒", "task": "任务", "command": "指令任务"}.get(item_type, item_type)
    return f"已添加{type_label}：{text}（{parsed} · {repeat}）"


async def add_reminder(plugin, params: dict) -> str:
    return await _add_item(plugin, "reminder", params)


async def add_task(plugin, params: dict) -> str:
    return await _add_item(plugin, "task", params)


async def add_command_task(plugin, params: dict) -> str:
    tool_name = (params.get("tool_name") or "").strip()
    if not tool_name:
        return "添加失败：tool_name 不能为空"
    description = (params.get("description") or "").strip() or f"调用 {tool_name}"
    extra = {"tool_name": tool_name, "description": description}
    new_params = dict(params)
    new_params["text"] = description
    return await _add_item(plugin, "command", new_params, extra_fields=extra)


# ----- list -----

async def list_tasks(plugin, params: dict) -> str:
    filter_type = params.get("filter_type", "all")
    items = _list_all(plugin.reminder_data)
    if filter_type != "all":
        items = [(i, r) for i, r in items if r.get("type", "reminder") == filter_type]

    if not items:
        return "当前没有任何定时任务"

    lines = [f"当前共 {len(items)} 条定时任务："]
    for idx, r in items:
        lines.append(_format_one(idx, r))
    return "\n".join(lines)


# ----- delete -----

async def delete_task(plugin, params: dict) -> str:
    if params.get("delete_all"):
        all_items = plugin.reminder_data.get(GROUP, [])
        count = len(all_items)
        for r in all_items:
            if r.get("job_id"):
                plugin.scheduler.remove_job(r["job_id"])
        plugin.reminder_data[GROUP] = []
        if GROUP in plugin.reminder_data and not plugin.reminder_data[GROUP]:
            del plugin.reminder_data[GROUP]
        save_reminder_data_sync(plugin.data_file, plugin.reminder_data)
        return f"已清空全部 {count} 条任务"

    items = plugin.reminder_data.get(GROUP, [])

    target_idx = None
    if "id" in params and params["id"] is not None:
        idx = int(params["id"]) - 1
        if 0 <= idx < len(items):
            target_idx = idx

    if target_idx is None and params.get("keyword"):
        kw = params["keyword"]
        for i, r in enumerate(items):
            if kw in r.get("text", ""):
                target_idx = i
                break

    if target_idx is None:
        return "删除失败：找不到匹配的任务，可以先用 timed_list 查看序号"

    target = items[target_idx]
    if target.get("job_id"):
        plugin.scheduler.remove_job(target["job_id"])
    items.pop(target_idx)
    if not items:
        del plugin.reminder_data[GROUP]
    save_reminder_data_sync(plugin.data_file, plugin.reminder_data)
    return f"已删除：{target.get('text', '')}"


# ----- update -----

async def update_task(plugin, params: dict) -> str:
    if "id" not in params or params["id"] is None:
        return "修改失败：缺少 id"

    items = plugin.reminder_data.get(GROUP, [])
    idx = int(params["id"]) - 1
    if not (0 <= idx < len(items)):
        return f"修改失败：序号 {params['id']} 不存在"

    target = items[idx]
    new_text = params.get("new_text")
    new_dt = params.get("new_datetime_str")

    if not new_text and not new_dt:
        return "修改失败：请至少提供 new_text 或 new_datetime_str"

    if new_text:
        target["text"] = new_text.strip()

    if new_dt:
        try:
            parsed = parse_datetime_for_llm(new_dt)
        except ValueError as e:
            return f"修改失败：{e}"

        target["datetime"] = parsed

        # 重新注册调度任务
        if target.get("job_id"):
            plugin.scheduler.remove_job(target["job_id"])

        try:
            dt = datetime.datetime.strptime(parsed, "%Y-%m-%d %H:%M")
            target["job_id"] = plugin.scheduler.add_job(GROUP, target, dt)
        except Exception as e:
            return f"修改失败（调度器异常）：{e}"

    save_reminder_data_sync(plugin.data_file, plugin.reminder_data)
    return f"已更新：[{idx + 1}] {target.get('text')}（{target.get('datetime')}）"


# ============================================================
# 路由表
# ============================================================

TOOL_ROUTES = {
    "timed_add_reminder": add_reminder,
    "timed_add_task": add_task,
    "timed_add_command_task": add_command_task,
    "timed_list": list_tasks,
    "timed_delete": delete_task,
    "timed_update": update_task,
}
