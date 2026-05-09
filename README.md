# 定时任务（timed-tasks）

让肥牛拥有 **真正的定时触发能力** —— 到点了 AI 用自己的口吻提醒你、自动调用工具完成任务。

> 移植自 [kjqwer/astrbot_plugin_sy](https://github.com/kjqwer/astrbot_plugin_sy)，保留了原版的核心调度引擎（APScheduler + 节假日 API + cron 表达式构造），删除了 QQ/微信机器人专用的部分，改为用肥牛的 plugin SDK 让 AI 主动说话。

---

## 功能

- **三种触发动作**：
  - **提醒（reminder）**：到点 AI 用人格化语气说出来，例如「该喝水啦」
  - **任务（task）**：到点 AI 自动完成某件事（可调用其他工具）
  - **指令任务（command）**：到点直接调某个具体工具（如 `beichen_weather_reminder`）
- **重复模式**：一次性 / 每天 / 每周 / 每月 / 每年
- **节假日过滤**：可叠加「仅工作日」「仅法定节假日」（数据来源 `timor.tech/api/holiday`，本地缓存 30 天）
- **持久化**：JSON 文件，重启后自动续约所有未过期任务
- **自然语言交互**：通过 AI 对话直接增删改查

---

## 安装

> **开箱即用说明**：本插件目录若带有 `vendor/*.whl`，从 **插件市场 / 内置 ZIP 安装流程** 安装时，宿主会自动执行 `pip install` 并**优先仅从 `vendor` 离线安装**（无需访问 PyPI、无需再开终端手敲命令）。若你是手动复制文件夹到 `plugins/community/`，仍须在宿主使用的 **同一个 Python** 里执行一次下方「方式 A」或「方式 B」（与原先一致）。

### 1. 装依赖

**方式 A：使用插件目录内 `vendor/`（离线 / 不访问 PyPI）**

先进入本插件目录，再用宿主项目自带的 Python 安装：

```powershell
cd <你的项目>\live-2d\plugins\community\timed-tasks
<宿主自带的 python.exe> -m pip install --no-index --find-links=./vendor -r requirements.txt
```

仓库中的 `vendor/` 由 `pip download` 生成。当前附带包为 **Windows amd64 + Python 3.13** 环境下载；若你的宿主 Python 版本或操作系统不同导致无法安装，请改用方式 B，或在本机用与宿主相同的解释器执行方式 C 重新生成 `vendor/`。

**方式 B：在线安装（需能访问 PyPI）**

```powershell
<宿主自带的 python.exe> -m pip install -r <本插件目录>\requirements.txt
```

**方式 C：在本机重新生成 `vendor/`**

```powershell
cd <本插件目录>
<与宿主相同的 python.exe> -m pip download -r requirements.txt -d .\vendor
```

> `aiohttp` 部分宿主环境可能已自带；`apscheduler` 通常需要安装。

### 2. 启用插件

`live-2d/plugins/enabled_plugins.json` 里加入这一行（已自动添加）：

```json
"community/timed-tasks"
```

重启肥牛即可生效。日志里出现 `✅ 插件已加载: 定时任务 v1.0.0` 就 OK。

---

## 使用示例

### 通过对话添加

直接说就行，AI 会调用对应工具：

| 你说什么 | 触发的工具 | 效果 |
|---|---|---|
| "明天下午 3 点提醒我开会" | `timed_add_reminder`（一次性） | 明天 15:00 AI 主动提醒 |
| "每天早上 8 点提醒我喝水" | `timed_add_reminder`（daily） | 每天 8:00 触发 |
| "每个工作日 9 点提醒我打卡" | `timed_add_reminder`（daily + workday） | 法定节假日跳过，调休补班日触发 |
| "每天中午 12 点帮我汇总今天的新闻" | `timed_add_task` | 到点 AI 自动联网搜索后说出来 |
| "每天 9 点查一下天气" | `timed_add_command_task`（调用 `beichen_weather_reminder`） | 到点直接调天气工具 |
| "我有什么定时任务" | `timed_list` | AI 念出所有任务 |
| "把喝水那个改到 9 点" | `timed_update` | 修改时间 |
| "不用提醒喝水了" | `timed_delete` | 按关键词删除 |

### 通过文件直接加（高级）

数据文件在 `live-2d/AI记录室/定时任务.json`。可以直接编辑（重启生效）：

```json
{
  "local": [
    {
      "type": "reminder",
      "text": "喝水",
      "datetime": "2026-05-02 08:00",
      "repeat": "daily",
      "user_name": "老板",
      "created_at": "2026-05-01 18:22"
    }
  ]
}
```

支持的字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `reminder` / `task` / `command` |
| `text` | 是 | 内容描述 |
| `datetime` | 是 | `YYYY-MM-DD HH:MM` |
| `repeat` | 否 | `none` / `daily` / `weekly` / `monthly` / `yearly`，可叠加 `_workday` 或 `_holiday` |
| `user_name` | 否 | 称呼，默认「用户」 |
| `tool_name` | 当 `type=command` 时必填 | 要调用的工具名 |
| `description` | 当 `type=command` 时填 | 给 AI 的任务描述 |

---

## 配置项

`plugin_config.json` 字段说明：

| 字段 | 默认 | 说明 |
|---|---|---|
| `data_file` | `AI记录室/定时任务.json` | 数据文件路径 |
| `enable_holiday` | `true` | 启用节假日过滤 |
| `enable_context` | `true` | 用最近对话生成更自然的提醒 |
| `max_context_count` | `5` | 用多少条上下文 |
| `reminder_prompt_template` | (内置) | 不用上下文时的模板。占位符：`{user_name}` `{reminder_text}` `{current_time}` |
| `task_prompt_template` | (内置) | 任务模板。占位符：`{task_text}` `{current_time}` |
| `command_prompt_template` | (内置) | 指令任务模板。占位符：`{tool_name}` `{description}` `{current_time}` |
| `max_tasks` | `50` | 全局最大任务数（防失控）。0 = 不限 |
| `holiday_api` | `http://timor.tech/api/holiday/year/` | 节假日数据源 |

---

## 工作原理

```
用户说"每天 8 点提醒我喝水"
       ↓
LLM function_call → timed_add_reminder
       ↓
写入 定时任务.json + 注册 APScheduler cron
       ↓
       … 等待 …
       ↓
8:00 到了 → cron 触发 → handlers.execute_reminder
       ↓
context.send_message(prompt)
       ↓
肥牛 voiceChat.sendToLLM（聚合所有插件 tools）
       ↓
LLM 用人格化语气生成 "诶~该喝水啦~"
       ↓
TTS 朗读
```

**和已有插件的协同**：`task` 和 `command` 类型会触发完整 LLM + tools 流程，所以**任何已有插件的工具都能被定时调用**：
- `weather-reminder` → 定时查天气
- `kimi-search` → 定时搜业内新闻
- `memos` → 定时整理记忆
- `screen-narrator` → 定时瞄一眼屏幕

---

## 文件结构

```
plugins/community/timed-tasks/
├── metadata.json          插件元数据
├── plugin_config.json     用户配置（schema 格式）
├── requirements.txt       Python 依赖清单
├── vendor/                预下载的 wheel（离线安装，见上文「方式 A」）
├── index.py               主入口（生命周期 + 路由）
├── utils.py               时间解析 + 节假日 API + 持久化
├── scheduler.py           APScheduler 调度器
├── handlers.py            三种触发动作的执行器
├── llm_tools.py           6 个 LLM 工具定义和路由实现
└── README.md              本文档
```

---

## 故障排查

**问：启用后日志报 `ModuleNotFoundError: No module named 'apscheduler'`**

答：优先在本插件目录下用宿主自带的 Python 做离线安装，例如：

```powershell
<你的python.exe> -m pip install --no-index --find-links=./vendor -r requirements.txt
```

将 `<你的python.exe>` 换成实际解释器路径。若可访问 PyPI，也可在线执行：`pip install apscheduler`。

**问：节假日判断失败**
答：检查能否访问 `http://timor.tech/api/holiday/year/2026`。失败时插件会回退到「周末算节假日，工作日算工作日」。

**问：到点了没触发**
答：检查 `live-2d/AI记录室/定时任务.json` 里有没有这条数据，再看终端日志里有没有 `Added job ...`。如果是工作日/节假日类型，确认今天确实符合条件。

**问：重启后任务还在吗？**
答：在。启动时 `_init_scheduler` 会从 JSON 重建所有未过期的 cron 任务。

---
## 想邀请你，做这只小牛的"云饲养员"

做这个桌宠的初衷，其实是因为自己一个人工作学习的时候，总觉得屏幕里空落落的。看到大家都在使用，我就觉得熬夜写代码、调教 AI 的日子都亮闪闪的。

不过，肥牛现在还在长身体（其实是我想给它做更多有趣的插件），养一只数字小牛其实也挺"费草"的哈哈。

如果你在这只小肥牛这里获得过哪怕一秒钟的治愈，或者觉得它算个合格的桌面搭子，要不要考虑成为它的"云饲养员"呀？

你的每一次充电，都不是在打赏我，而是在给这只肥牛注入一点点魔法值。让它能变得更聪明、更通人性、能听懂你更多的碎碎念。

不用有压力哦！你愿意打开它，就是对我最大的鼓励啦。如果刚好有余力，就请肥牛喝瓶快乐水叭，它会记住你的味道的！

爱发电 [https://ifdian.net/a/0923A](https://ifdian.net/a/0923A)

---

## 许可证

本项目采用 **CC BY-NC-SA 4.0** 许可证。
