"""
工具模块：时间解析、节假日 API + 缓存、数据持久化

改自 https://github.com/kjqwer/astrbot_plugin_sy 原版 utils.py
- 移除：AstrBot 框架引用、平台识别、会话隔离兼容处理、QQ 白名单
- 保留：时间字符串解析（多格式）、节假日 API 客户端 + 30 天本地缓存、数据加载/保存、过期判断
"""

import datetime
import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger("timed-tasks.utils")


# ============================================================
# 时间解析
# ============================================================

def parse_datetime_for_llm(datetime_str: str) -> str:
    """专门给 LLM 工具用的标准格式时间解析（YYYY-MM-DD HH:MM）"""
    try:
        s = datetime_str.strip().replace('：', ':')

        try:
            dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"):
                try:
                    dt = datetime.datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"无法解析时间格式: {s}，请使用 YYYY-MM-DD HH:MM 格式")

        now = datetime.datetime.now()
        if dt < now and dt.date() < now.date() and dt.year == now.year:
            dt = dt.replace(year=now.year + 1)
            logger.info(f"时间已过，自动调整为明年: {dt.strftime('%Y-%m-%d %H:%M')}")

        return dt.strftime("%Y-%m-%d %H:%M")

    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"时间格式错误: {e}")


def parse_datetime(datetime_str: str) -> str:
    """通用时间解析，支持多种格式

    支持：HH:MM、HHMM、YYYYMMDDHHII、YYYY-MM-DD-HH:MM、MM-DD-HH:MM、MMDDHHII
    """
    original_input = datetime_str
    try:
        today = datetime.datetime.now()
        s = datetime_str.strip().replace('：', ':')

        if '-' in s and ':' in s:
            try:
                parts = s.split('-')
                if len(parts) == 4:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    time_part = parts[3]
                    hour, minute = map(int, time_part.split(':'))
                    dt = datetime.datetime(year, month, day, hour, minute)
                    if dt.year < today.year:
                        dt = dt.replace(year=today.year)
                    if dt < today and dt != today.replace(second=0, microsecond=0):
                        dt = dt.replace(year=today.year + 1)
                    return dt.strftime("%Y-%m-%d %H:%M")
                elif len(parts) == 3:
                    month, day = int(parts[0]), int(parts[1])
                    hour, minute = map(int, parts[2].split(':'))
                    dt = datetime.datetime(today.year, month, day, hour, minute)
                    if dt < today and dt != today.replace(second=0, microsecond=0):
                        dt = dt.replace(year=today.year + 1)
                    return dt.strftime("%Y-%m-%d %H:%M")
                else:
                    raise ValueError(f"分割段数不对: {len(parts)}")
            except ValueError as e:
                raise ValueError(f"全连字符格式错误: {e}")

        if len(s) == 12 and s.isdigit():
            year, month, day = int(s[:4]), int(s[4:6]), int(s[6:8])
            hour, minute = int(s[8:10]), int(s[10:12])
            dt = datetime.datetime(year, month, day, hour, minute)
            if dt.year < today.year:
                dt = dt.replace(year=today.year)
            if dt < today and dt != today.replace(second=0, microsecond=0):
                dt = dt.replace(year=today.year + 1)
            return dt.strftime("%Y-%m-%d %H:%M")

        if len(s) == 8 and s.isdigit():
            month, day = int(s[:2]), int(s[2:4])
            hour, minute = int(s[4:6]), int(s[6:8])
            dt = datetime.datetime(today.year, month, day, hour, minute)
            if dt < today and dt != today.replace(second=0, microsecond=0):
                dt = dt.replace(year=today.year + 1)
            return dt.strftime("%Y-%m-%d %H:%M")

        if ':' in s:
            parts = s.split(':')
            if len(parts) == 2:
                hour, minute = map(int, parts)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("时间超出范围")
                dt = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if dt < today and dt != today.replace(second=0, microsecond=0):
                    dt += datetime.timedelta(days=1)
                return dt.strftime("%Y-%m-%d %H:%M")

        if len(s) == 4 and s.isdigit():
            hour, minute = int(s[:2]), int(s[2:])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("时间超出范围")
            dt = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt < today and dt != today.replace(second=0, microsecond=0):
                dt += datetime.timedelta(days=1)
            return dt.strftime("%Y-%m-%d %H:%M")

        raise ValueError("时间格式错误")

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"parse_datetime 异常 ({original_input}): {e}")
        raise ValueError(f"时间格式错误，支持格式：HH:MM / HHMM / YYYY-MM-DD-HH:MM / MM-DD-HH:MM / YYYYMMDDHHII / MMDDHHII")


def is_outdated(reminder: dict) -> bool:
    """检查一次性提醒是否已过期"""
    if not reminder.get("datetime"):
        return False
    try:
        return datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M") < datetime.datetime.now()
    except ValueError:
        logger.error(f"提醒日期格式错误: {reminder.get('datetime')}")
        return False


# ============================================================
# 数据持久化
# ============================================================

def load_reminder_data(data_file: str) -> dict:
    """加载持久化数据，文件不存在时初始化"""
    os.makedirs(os.path.dirname(os.path.abspath(data_file)), exist_ok=True)
    if not os.path.exists(data_file):
        with open(data_file, "w", encoding='utf-8') as f:
            f.write("{}")
    try:
        with open(data_file, "r", encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载数据失败 ({data_file}): {e}")
        return {}


def save_reminder_data_sync(data_file: str, reminder_data: dict):
    """同步保存（带过期清理）"""
    for group in list(reminder_data.keys()):
        reminder_data[group] = [
            r for r in reminder_data[group]
            if r.get("datetime") and not (r.get("repeat", "none") == "none" and is_outdated(r))
        ]
        if not reminder_data[group]:
            del reminder_data[group]

    os.makedirs(os.path.dirname(os.path.abspath(data_file)), exist_ok=True)
    with open(data_file, "w", encoding='utf-8') as f:
        json.dump(reminder_data, f, ensure_ascii=False, indent=2)


async def save_reminder_data(data_file: str, reminder_data: dict):
    """异步保存（实际是 sync 包一层，写文件本身不耗时）"""
    save_reminder_data_sync(data_file, reminder_data)


def check_reminder_limit(reminder_data: dict, max_tasks: int) -> tuple:
    """检查总任务数限制

    Returns:
        (can_create, error_msg)
    """
    if max_tasks <= 0:
        return True, None
    total = sum(len(rs) for rs in reminder_data.values())
    if total >= max_tasks:
        return False, f"已达到最大任务数限制 ({max_tasks})，请先删除一些旧任务"
    return True, None


# ============================================================
# 节假日 API + 本地缓存
# ============================================================

class HolidayManager:
    """法定节假日数据管理器

    数据源：http://timor.tech/api/holiday/year/{year}
    本地缓存 30 天，避免频繁调用
    """

    def __init__(self, cache_file: str, api_base: str = "http://timor.tech/api/holiday/year/"):
        self.cache_file = cache_file
        self.api_base = api_base.rstrip('/') + '/'
        os.makedirs(os.path.dirname(os.path.abspath(cache_file)), exist_ok=True)
        self.holiday_data = self._load_cache()

    def _load_cache(self) -> dict:
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding='utf-8') as f:
                data = json.load(f)
            if "last_update" in data:
                last = datetime.datetime.fromisoformat(data["last_update"])
                if (datetime.datetime.now() - last).days > 30:
                    logger.info("节假日缓存超过 30 天，清空")
                    return {}
            return data
        except Exception as e:
            logger.error(f"加载节假日缓存失败: {e}")
            return {}

    async def _save_cache(self):
        try:
            self.holiday_data["last_update"] = datetime.datetime.now().isoformat()
            with open(self.cache_file, "w", encoding='utf-8') as f:
                json.dump(self.holiday_data, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存节假日缓存失败: {e}")

    async def fetch_holiday_data(self, year: Optional[int] = None) -> dict:
        """拉取指定年份节假日数据，命中缓存则直接返回

        Returns:
            {"MM-DD": True/False}
            True  = 法定节假日
            False = 调休工作日（需要补班的周末）
        """
        if year is None:
            year = datetime.datetime.now().year

        year_key = str(year)
        if year_key in self.holiday_data and "data" in self.holiday_data[year_key]:
            return self.holiday_data[year_key]["data"]

        url = f"{self.api_base}{year}"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"节假日 API 返回 {response.status}")
                        return {}
                    json_data = await response.json()

            if json_data.get("code") != 0:
                logger.error(f"节假日 API 错误: {json_data.get('msg')}")
                return {}

            holiday_data = {}
            for date_str, info in json_data.get("holiday", {}).items():
                holiday_data[date_str] = info.get("holiday")

            self.holiday_data.setdefault(year_key, {})["data"] = holiday_data
            await self._save_cache()
            return holiday_data

        except Exception as e:
            logger.error(f"拉取节假日数据出错: {e}")
            return {}

    async def is_holiday(self, date: Optional[datetime.datetime] = None) -> bool:
        """是否为法定节假日（含放假调休后真正放假的日期）"""
        if date is None:
            date = datetime.datetime.now()
        short = date.strftime("%m-%d")
        data = await self.fetch_holiday_data(date.year)

        if short in data:
            return data[short] is True
        return date.weekday() >= 5  # 周末

    async def is_workday(self, date: Optional[datetime.datetime] = None) -> bool:
        """是否为工作日（含调休补班的周末）"""
        if date is None:
            date = datetime.datetime.now()
        short = date.strftime("%m-%d")
        data = await self.fetch_holiday_data(date.year)

        if short in data:
            return data[short] is False
        return date.weekday() < 5  # 工作日 0-4
