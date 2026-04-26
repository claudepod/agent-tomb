# Hermes Agent 文件结构详解

## 📁 根目录 (`~/.hermes/`)

```
~/.hermes/
├── config.yaml              # 主配置文件 (YAML)
├── auth.json                # 认证信息 (API keys, tokens)
├── state.db                 # SQLite 数据库 (状态、会话)
│   ├── sessions             # 会话元数据表
│   └── messages             # 消息内容表
├── channel_directory.json   # Discord 频道/线程目录
├── discord_threads.json     # Discord 线程列表
├── gateway.*                # 网关相关文件 (PID, lock, state)
├── SOUL.md                  # Agent 的 SOUL 说明文档
├── .env                     # 环境变量
├── sessions/                # 所有会话记录
│   ├── sessions.json        # 会话索引
│   └── session_*.json       # 单个会话详细数据 (JSON)
│   └── request_dump_*.json  # 请求/响应转储
├── memories/                # 记忆存储
├── skills/                  # 已安装的技能 (可复用流程)
├── cron/                    # 定时任务配置
├── logs/                    # 运行日志
└── bin/                     # 可执行文件
```

---

## 🗄️ 核心数据结构

### 1. state.db (SQLite)

#### `sessions` 表 - 会话元数据
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,           -- 来源平台 (discord/telegram等)
    user_id TEXT,
    model TEXT,                     -- 使用的模型
    model_config TEXT,              -- 模型配置 JSON
    system_prompt TEXT,             -- 系统提示词
    parent_session_id TEXT,         -- 父会话ID (支持会话树)
    started_at REAL NOT NULL,       -- 开始时间戳
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    reasoning_tokens INTEGER,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count INTEGER
);
```

#### `messages` 表 - 消息内容
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,             -- user/assistant/system/tool
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,                -- 工具调用详情 (JSON)
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,                 -- 思考过程
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT
);
```

---

### 2. sessions/session_*.json (详细会话)

每个会话是一个完整的 JSON 文件，包含：

```json
{
  "session_id": "...",
  "model": "huihui-ai_qwen3-coder-next-abliterated",
  "base_url": "http://127.0.0.1:1234/v1",
  "platform": "discord",
  "session_start": "2026-04-25T17:39:18.346595",
  "last_updated": "...",
  "system_prompt": "# Hermes Agent Persona\n...",
  "tools": [
    {
      "type": "function",
      "function": { "name": "...", ... }
    }
  ],
  "message_count": N,
  "messages": [ ... ]  // 完整对话历史
}
```

---

### 3. memories/ (持久化记忆)

**两个主要存储区：**
- `user` - 用户信息（偏好、习惯、重要事实）
- `memory` - Agent 的知识库（环境 facts、项目约定、工具 quirks）

---

### 4. skills/ (可复用技能)

每个技能是一个独立目录：
```
skills/
└── some-skill/
    ├── SKILL.md          # 主文档 (YAML frontmatter + markdown)
    ├── references/         # 参考资料
    ├── templates/          # 模板文件
    ├── scripts/            # 脚本文件
    └── assets/             # 静态资源
```

---

## 📦 Agent "去世" 后需要打包的文件清单

### 必需文件 (Mandatory)
| 目录/文件 | 说明 |
|-----------|------|
| `config.yaml` | 模型、工具集等设置 |
| `auth.json` | API keys 和 tokens |
| `.env` | 环境变量 |
| `state.db*` | SQLite 数据库 (含 sessions + messages) |
| `sessions/` | 所有会话记录 |

### 可选文件 (Optional)
| 目录/文件 | 说明 |
|-----------|------|
| `memories/` | 持久化知识 |
| `skills/` | 学到的可复用流程 |
| `logs/` | 运行日志 |
| `channel_directory.json`, `discord_threads.json` | 平台特定元数据 |

---

## 📝 建议的 Memorial 打包结构

```
agent-memorial-<name>-<timestamp>.zip
├── metadata/
│   ├── manifest.json      # Agent 元数据（创建时间、平台、版本）
│   └── epitaph.md         # 碑文（Markdown 格式，可编辑）
├── config/                # 配置文件 (config.yaml, auth.json, .env)
├── data/
│   ├── sessions/          # 会话历史
│   ├── memories/          # 记忆库
│   └── skills/            # 技能包
├── logs/
└── platform-specific/     # Discord/Telegram 等特定数据
```

需要我详细展开某个部分吗？比如：
- `state.db` 的表结构和查询示例
- 会话 JSON 的完整 schema
- 如何提取记忆和技能用于传承