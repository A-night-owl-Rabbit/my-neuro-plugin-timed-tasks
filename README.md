# 定时任务（timed-tasks）| My Neuro 社区插件

为 **My Neuro / live-2d** 宿主提供 **可调度定时能力**：到点由 AI 以自然语气提醒、自动执行描述任务，或在指定时间触发某个已注册的 LLM 工具。

> 核心调度逻辑移植自 [kjqwer/astrbot_plugin_sy](https://github.com/kjqwer/astrbot_plugin_sy)，已去除 IM 机器人专用部分，改为基于 Python `plugin_sdk` 与宿主语音链路对接。

## 功能概览

- **三种动作**
  - **reminder（提醒）**：到点生成一条面向用户的提醒话术。
  - **task（任务）**：到点让 AI 主动完成描述中的事项（可走完整工具调用链路）。
  - **command（指令任务）**：到点要求调用指定工具名（例如天气类插件暴露的工具），并把结果说明给用户。
- **重复规则**：一次性 / 每天 / 每周 / 每月 / 每年，并可叠加「仅工作日」「仅法定节假日」。
- **节假日数据**：默认请求 `timor.tech` 公益接口，本地缓存约 30 天；失败时回退为「周末视作休、周一至周五视作工作日」的粗粒度判断。
- **持久化**：JSON 文件保存任务列表，进程重启后会重建未过期的调度项。
- **自然语言管理**：通过对话触发 LLM 工具完成增删改查。

## 安装

### 1. Python 依赖

在宿主项目自带的 Python 环境中安装：

```bash
pip install -r requirements.txt
```

或至少安装：`apscheduler`、`aiohttp`（版本见 `requirements.txt`）。

### 2. 启用插件

将本目录放到宿主项目的 `live-2d/plugins/community/timed-tasks/`，并在 `live-2d/plugins/enabled_plugins.json` 中加入：

```json
"community/timed-tasks"
```

重启宿主后，日志中出现插件加载成功信息即可。

## 使用说明（对话示例）

| 用户说法示例 | 工具 | 效果 |
| --- | --- | --- |
| 明天 15:00 提醒我开会 | `timed_add_reminder` | 一次性提醒 |
| 每天早上 8 点提醒我喝水 | `timed_add_reminder`（daily） | 每日重复 |
| 每个工作日 9 点提醒我打卡 | `timed_add_reminder`（daily + workday） | 跳过法定节假日，调休补班日会触发 |
| 每天中午汇总新闻 | `timed_add_task` | 到点由 AI 执行描述任务 |
| 每天 9 点查天气（需本机已有对应天气工具） | `timed_add_command_task` | 到点走指定工具名 |
| 我有哪些定时任务 | `timed_list` | 列出任务 |
| 把喝水改到 9 点 | `timed_update` | 按 id 修改 |
| 取消喝水提醒 | `timed_delete` | 按关键词或 id 删除 |

## 数据文件（高级）

默认数据路径由 `plugin_config.json` 的 `data_file` 决定（相对 `live-2d` 工作目录）。可直接编辑 JSON（建议在停服或了解格式前提下操作），字段说明见 `plugin_config.json` 内各键的 `description`。

## 配置项摘要

| 键 | 说明 |
| --- | --- |
| `data_file` | 任务 JSON 路径 |
| `enable_holiday` | 是否启用节假日接口与过滤 |
| `enable_context` | 提醒是否结合最近对话润色语气 |
| `max_context_count` | 使用的历史条数上限 |
| `reminder_prompt_template` / `task_prompt_template` / `command_prompt_template` | 各类触发的提示模板（占位符见 schema） |
| `max_tasks` | 全局任务数上限，`0` 表示不限制 |
| `holiday_api` | 节假日年份数据接口基址 |

## 仓库结构

```
metadata.json
plugin_config.json
requirements.txt
index.py
utils.py
scheduler.py
handlers.py
llm_tools.py
README.md
```

## 致谢

调度与节假日相关实现思路来自 [@kjqwer](https://github.com/kjqwer) 的 [astrbot_plugin_sy](https://github.com/kjqwer/astrbot_plugin_sy)，感谢原作者开源。

## 许可证与声明

若上游项目另有许可证要求，请同时遵守上游约定。使用节假日等第三方 HTTP 接口时请遵循对方服务条款与频率限制。
