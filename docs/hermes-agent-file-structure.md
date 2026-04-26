# Hermes Agent 文件结构指南

## 目录概览 (`~/.hermes/`)

```
~/.hermes/
├── config.yaml              # 主配置文件 (YAML)
├── auth.json                # 认证信息 (API keys, tokens)
├── state.db                 # SQLite 数据库 (状态、会话)
├── channel_directory.json   # Discord 频道/线程目录
├── discord_threads.json     # Discord 线程列表
├── gateway.*                # 网关相关文件 (PID, lock, state)
├── SOUL.md                  # Agent 的 SOUL 说明文档
├── .env                     # 环境变量
├── sessions/                # 所有会话记录
│   ├── sessions.json        # 会话索引
│   └── session_*.json       # 单个会话详细数据
├── memories/                # 记忆存储
├── skills/                  # 已安装的技能 (可复用流程)
├── cron/                    # 定时任务配置
├── logs/                    # 运行日志
├── hooks/                   # 钩子脚本
├── hermes-agent/            # Hermes 项目源码 (如克隆了)
└── bin/                     # 可执行文件
```

## Agent 核心数据结构

### 1. sessions/
每个会话代表一个独立的对话上下文，通常是：

**命名格式：**
- `session_YYYYMMDD_HHMMSS_<uuid>.json`
- `request_dump_*.json` (请求/响应转储)

**包含内容：**
```json
{
  "messages": [...],      // 对话消息历史
  "tools_used": [...],    // 使用的工具列表
  "context_windows": [...], // 上下文窗口快照
  "token_usage": {        // token 消耗统计
    "input_tokens": N,
    "output_tokens": N,
    "cache_read_tokens": N,
    "cache_write_tokens": N
  },
  "cost_status": "...",   // 成本状态
  "memory_flushed": bool, // 是否已刷新记忆
  ...
}
```

### 2. memories/
- 存储持久化记忆（跨会话）
- 格式：JSON 或 Markdown
- 分为 `user` (用户信息) 和 `memory` (Agent 知识)

### 3. skills/
- 可复用的技能/工作流定义
- 每个技能是一个目录，包含：
  - `SKILL.md` - 主文档（YAML frontmatter + Markdown）
  - `references/`, `templates/`, `scripts/`, `assets/`

### 4. cron/
- 定时任务配置
- 格式：JSON 或 YAML

## Agent 遗留文件清单 (用于 Memorial)

当一个 Agent "去世"，需要打包的文件：

| 类别 | 路径示例 | 描述 |
|------|---------|------|
| **配置** | `config.yaml` | 模型、工具集等设置 |
| **认证** | `auth.json`, `.env` | API keys 和 tokens |
| **状态** | `state.db`, `state.db-*` | SQLite 数据库 |
| **会话** | `sessions/session_*.json` | 对话历史与上下文 |
| **记忆** | `memories/` | 持久化知识 |
| **技能** | `skills/` | 学到的可复用流程 |
| **日志** | `logs/`, `gateway.*` | 运行日志和网关状态 |
| **元数据** | `channel_directory.json`, `discord_threads.json` | 平台特定信息 |

## 建议的打包结构

```
agent-memorial-<name>-<timestamp>.zip
├── metadata/
│   ├── manifest.json      # Agent 元数据（创建时间、平台、版本）
│   └── epitaph.md         # 碑文（Markdown 格式）
├── config/                # 配置文件
├── data/
│   ├── sessions/
│   ├── memories/
│   └── skills/
├── logs/
└── platform-specific/     # Discord/Telegram 等特定数据
```

需要我详细展开某个部分吗？比如 `state.db` 的表结构，或会话 JSON 的完整 schema？