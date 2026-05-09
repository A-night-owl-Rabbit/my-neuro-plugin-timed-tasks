"""
调度器：基于 APScheduler 的 cron-like 定时调度

改自 https://github.com/kjqwer/astrbot_plugin_sy 原版 scheduler.py
- 移除：AstrBot 框架引用、wechat_platforms、unique_session、平台识别相关
- 保留：12 种 cron 触发器分支（一次性 / daily / weekly / monthly / yearly × workday/holiday）
       过期一次性任务自动清理、重启续约、节假日过滤
- 修改：触发回调改为调用 handlers，使用 plugin_sdk 的 send_message 出口
"""

import datetime
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import JobLookupError

from utils import is_outdated, save_reminder_data_sync, HolidayManager

logger = logging.getLogger("timed-tasks.scheduler")


# 全局调度器单例（hot reload 时复用同一个 AsyncIOScheduler，避免重复启动）
if not hasattr(sys, "_TIMED_TASKS_SCHEDULER"):
    sys._TIMED_TASKS_SCHEDULER = {"scheduler": None}


class ReminderScheduler:
    """统一调度入口

    一个 scheduler 实例对应一份 reminder_data + 一个 handlers
    """

    def __init__(self, reminder_data: dict, data_file: str, handlers, holiday_manager: HolidayManager):
        self.reminder_data = reminder_data
        self.data_file = data_file
        self.handlers = handlers
        self.holiday_manager = holiday_manager

        # 复用全局调度器实例
        if sys._TIMED_TASKS_SCHEDULER["scheduler"] is None:
            sys._TIMED_TASKS_SCHEDULER["scheduler"] = AsyncIOScheduler()
            logger.info("创建全局 AsyncIOScheduler")
        self.scheduler = sys._TIMED_TASKS_SCHEDULER["scheduler"]

        # 清理之前实例残留的任务
        self._clear_jobs()
        # 重新注册所有任务
        self._init_scheduler()

        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("启动 AsyncIOScheduler")

    # ============================================================
    # 生命周期
    # ============================================================

    def _clear_jobs(self):
        for job in self.scheduler.get_jobs():
            if job.id.startswith("tt_"):
                try:
                    self.scheduler.remove_job(job.id)
                except JobLookupError:
                    pass

    def shutdown(self):
        """优雅关闭：清理本插件的任务，但不停掉全局调度器（hot reload 友好）"""
        self._clear_jobs()
        logger.info("Scheduler shutdown：已清空本插件任务")

    # ============================================================
    # 注册任务
    # ============================================================

    def _init_scheduler(self):
        """从 reminder_data 重建所有定时任务"""
        total = sum(len(rs) for rs in self.reminder_data.values())
        logger.info(f"开始注册定时任务，总计 {total} 项")

        for group in list(self.reminder_data.keys()):
            for i, reminder in enumerate(list(self.reminder_data[group])):
                if not reminder.get("datetime"):
                    continue

                # 处理只有 HH:MM 格式的旧数据
                datetime_str = reminder["datetime"]
                try:
                    if ":" in datetime_str and len(datetime_str.split(":")) == 2 and "-" not in datetime_str:
                        today = datetime.datetime.now()
                        hour, minute = map(int, datetime_str.split(":"))
                        dt = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if dt < today:
                            dt += datetime.timedelta(days=1)
                        reminder["datetime"] = dt.strftime("%Y-%m-%d %H:%M")
                    dt = datetime.datetime.strptime(reminder["datetime"], "%Y-%m-%d %H:%M")
                except ValueError as e:
                    logger.error(f"无法解析时间 '{reminder['datetime']}': {e}，跳过")
                    continue

                # 一次性任务过期跳过
                repeat_type = reminder.get("repeat", "none")
                if (repeat_type == "none" or
                    not any(k in repeat_type for k in ["daily", "weekly", "monthly", "yearly"])
                ) and is_outdated(reminder):
                    logger.info(f"跳过已过期任务: {reminder.get('text')}")
                    continue

                # 唯一 job_id
                ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
                job_id = f"tt_{group}_{i}_{ts}"
                self._register_job(job_id, group, reminder, dt)
                reminder["job_id"] = job_id

        # 同步保存（job_id 写回）
        save_reminder_data_sync(self.data_file, self.reminder_data)

    def add_job(self, group: str, reminder: dict, dt: datetime.datetime) -> str:
        """运行时新增任务"""
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
        idx = len(self.reminder_data.get(group, [])) - 1
        job_id = f"tt_{group}_{idx}_{ts}"
        self._register_job(job_id, group, reminder, dt)
        return job_id

    def _register_job(self, job_id: str, group: str, reminder: dict, dt: datetime.datetime):
        """根据 reminder['repeat'] 选择合适的 cron 触发器"""
        repeat = reminder.get("repeat", "none")
        common = dict(args=[group, reminder], misfire_grace_time=60, id=job_id)

        # ===== 每天 =====
        if repeat == "daily":
            self.scheduler.add_job(self._reminder_callback, 'cron',
                                   hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"daily {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        elif repeat == "daily_workday":
            self.scheduler.add_job(self._check_workday, 'cron',
                                   hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"daily_workday {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        elif repeat == "daily_holiday":
            self.scheduler.add_job(self._check_holiday, 'cron',
                                   hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"daily_holiday {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        # ===== 每周 =====
        elif repeat == "weekly":
            self.scheduler.add_job(self._reminder_callback, 'cron',
                                   day_of_week=dt.weekday(),
                                   hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"weekly {dt.weekday()} {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        elif repeat == "weekly_workday":
            self.scheduler.add_job(self._check_workday, 'cron',
                                   day_of_week=dt.weekday(),
                                   hour=dt.hour, minute=dt.minute, **common)

        elif repeat == "weekly_holiday":
            self.scheduler.add_job(self._check_holiday, 'cron',
                                   day_of_week=dt.weekday(),
                                   hour=dt.hour, minute=dt.minute, **common)

        # ===== 每月 =====
        elif repeat == "monthly":
            self.scheduler.add_job(self._reminder_callback, 'cron',
                                   day=dt.day, hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"monthly day={dt.day} {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        elif repeat == "monthly_workday":
            self.scheduler.add_job(self._check_workday, 'cron',
                                   day=dt.day, hour=dt.hour, minute=dt.minute, **common)

        elif repeat == "monthly_holiday":
            self.scheduler.add_job(self._check_holiday, 'cron',
                                   day=dt.day, hour=dt.hour, minute=dt.minute, **common)

        # ===== 每年 =====
        elif repeat == "yearly":
            self.scheduler.add_job(self._reminder_callback, 'cron',
                                   month=dt.month, day=dt.day,
                                   hour=dt.hour, minute=dt.minute, **common)
            logger.info(f"yearly {dt.month}-{dt.day} {dt.hour}:{dt.minute:02d} - {reminder.get('text')}")

        elif repeat == "yearly_workday":
            self.scheduler.add_job(self._check_workday, 'cron',
                                   month=dt.month, day=dt.day,
                                   hour=dt.hour, minute=dt.minute, **common)

        elif repeat == "yearly_holiday":
            self.scheduler.add_job(self._check_holiday, 'cron',
                                   month=dt.month, day=dt.day,
                                   hour=dt.hour, minute=dt.minute, **common)

        # ===== 一次性 =====
        else:
            self.scheduler.add_job(self._reminder_callback, 'date',
                                   run_date=dt, args=[group, reminder],
                                   misfire_grace_time=60, id=job_id)
            logger.info(f"once {dt.strftime('%Y-%m-%d %H:%M')} - {reminder.get('text')}")

    def remove_job(self, job_id: str):
        """运行时移除指定任务"""
        try:
            self.scheduler.remove_job(job_id)
            return True
        except JobLookupError:
            return False
        except Exception as e:
            logger.warning(f"移除任务失败 {job_id}: {e}")
            return False

    # ============================================================
    # 回调
    # ============================================================

    async def _check_workday(self, group: str, reminder: dict):
        today = datetime.datetime.now()
        if await self.holiday_manager.is_workday(today):
            logger.info(f"今天是工作日，触发: {reminder.get('text')}")
            await self._reminder_callback(group, reminder)
        else:
            logger.info(f"今天非工作日，跳过: {reminder.get('text')}")

    async def _check_holiday(self, group: str, reminder: dict):
        today = datetime.datetime.now()
        if await self.holiday_manager.is_holiday(today):
            logger.info(f"今天是节假日，触发: {reminder.get('text')}")
            await self._reminder_callback(group, reminder)
        else:
            logger.info(f"今天非节假日，跳过: {reminder.get('text')}")

    async def _reminder_callback(self, group: str, reminder: dict):
        """统一触发入口：根据 type 分发到 handlers"""
        rtype = reminder.get("type", "reminder")
        try:
            if rtype == "task":
                await self.handlers.execute_task(reminder)
            elif rtype == "command":
                await self.handlers.execute_command_task(reminder)
            else:
                await self.handlers.execute_reminder(reminder)
        except Exception as e:
            logger.error(f"执行任务出错 ({reminder.get('text')}): {e}", exc_info=True)

        # 一次性任务执行后从数据中移除
        if reminder.get("repeat", "none") == "none":
            self._remove_one_shot(group, reminder)

    def _remove_one_shot(self, group: str, reminder: dict):
        """从持久化数据中删掉一次性任务"""
        if group not in self.reminder_data:
            return
        for i, r in enumerate(self.reminder_data[group]):
            if (r.get("text") == reminder.get("text")
                and r.get("datetime") == reminder.get("datetime")
                and r.get("created_at") == reminder.get("created_at")):
                # 移除 scheduler job
                if r.get("job_id"):
                    self.remove_job(r["job_id"])
                self.reminder_data[group].pop(i)
                if not self.reminder_data[group]:
                    del self.reminder_data[group]
                save_reminder_data_sync(self.data_file, self.reminder_data)
                logger.info(f"一次性任务执行完毕，已删除: {reminder.get('text')}")
                return
