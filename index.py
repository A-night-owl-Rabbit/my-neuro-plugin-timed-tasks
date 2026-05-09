"""
timed-tasks 插件主入口

肥牛 Python 插件 SDK 入口，粘合：
  - utils 持久化加载
  - scheduler 调度
  - handlers 触发执行
  - llm_tools LLM 工具暴露
"""

import logging
import os
import sys

# 把当前目录加入 sys.path，使同级文件可以绝对 import
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s %(message)s',
    stream=sys.stderr,  # plugin_sdk 用 stdout 通信，必须把日志走 stderr
)

from plugin_sdk import Plugin, run  # noqa: E402

from utils import (  # noqa: E402
    load_reminder_data,
    HolidayManager,
    save_reminder_data_sync,
)
from scheduler import ReminderScheduler  # noqa: E402
from handlers import ReminderHandlers  # noqa: E402
from llm_tools import TOOL_DEFS, TOOL_ROUTES  # noqa: E402


logger = logging.getLogger("timed-tasks.index")


class TimedTasksPlugin(Plugin):

    def __init__(self):
        super().__init__()
        self.cfg: dict = {}
        self.data_file: str = ""
        self.reminder_data: dict = {}
        self.scheduler: ReminderScheduler | None = None
        self.handlers: ReminderHandlers | None = None
        self.holiday_manager: HolidayManager | None = None

    # ============================================================
    # 生命周期
    # ============================================================

    async def on_init(self):
        # 读插件 plugin_config.json（已 flatten）
        self.cfg = self.context.get_plugin_config() or {}

        # 数据文件路径（相对 cwd = live-2d）
        data_file_rel = self.cfg.get("data_file", "AI记录室/定时任务.json")
        self.data_file = os.path.abspath(data_file_rel)

        # 加载持久化数据
        self.reminder_data = load_reminder_data(self.data_file)

        # 节假日管理器（关闭 enable_holiday 时也实例化，但不会被调度器调用）
        cache_dir = os.path.join(os.path.dirname(self.data_file), ".cache")
        cache_file = os.path.join(cache_dir, "holiday_cache.json")
        api_base = self.cfg.get("holiday_api", "http://timor.tech/api/holiday/year/")
        self.holiday_manager = HolidayManager(cache_file, api_base)

        # handlers
        self.handlers = ReminderHandlers(self.context, self.cfg)

        total = sum(len(rs) for rs in self.reminder_data.values())
        self.context.log("info", f"timed-tasks 初始化完成，已加载 {total} 项任务，数据文件: {self.data_file}")

    async def on_start(self):
        """关键：APScheduler 必须在 event loop 已运行的环境下启动"""
        try:
            self.scheduler = ReminderScheduler(
                reminder_data=self.reminder_data,
                data_file=self.data_file,
                handlers=self.handlers,
                holiday_manager=self.holiday_manager,
            )
            total = sum(len(rs) for rs in self.reminder_data.values())
            self.context.log("info", f"timed-tasks 调度器已启动，{total} 项任务正在监控")
        except Exception as e:
            self.context.log("error", f"timed-tasks 调度器启动失败: {e}")
            logger.exception("调度器启动失败")
            raise

    async def on_stop(self):
        if self.scheduler:
            try:
                self.scheduler.shutdown()
            except Exception as e:
                self.context.log("warn", f"timed-tasks 关闭异常: {e}")
        # 保存最新状态
        try:
            save_reminder_data_sync(self.data_file, self.reminder_data)
        except Exception as e:
            logger.warning(f"on_stop 保存数据失败: {e}")

    # ============================================================
    # LLM 工具
    # ============================================================

    def get_tools(self):
        return TOOL_DEFS

    async def execute_tool(self, name: str, params: dict):
        route = TOOL_ROUTES.get(name)
        if not route:
            return f"不支持的工具: {name}"
        try:
            return await route(self, params or {})
        except Exception as e:
            logger.exception(f"工具 {name} 执行异常")
            return f"工具 {name} 执行失败: {e}"


if __name__ == "__main__":
    run(TimedTasksPlugin)
