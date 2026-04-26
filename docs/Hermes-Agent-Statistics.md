# 📊 Hermes Agent 数据统计 (截至 2026-04-25)

## 🗄️ SQLite Database (`state.db`)

### Sessions 表统计

| Session ID | Platform | Title | Started | Messages |
|------------|----------|-------|---------|----------|
| 20260425_172947_fc770890 | discord | Discord Thread Creation Status | 2026-04-25 09:29 | 26 |
| 20260425_162018_a036e0e0 | discord | - | 2026-04-25 08:20 | 152 |

### Messages 表统计 (最近24小时)

| Role | Count | Avg Tokens |
|------|-------|------------|
| assistant | 83 | ~ |
| session_meta | 2 | ~ |
| tool | 70 | ~ |
| user | 23 | ~ |

---

## 📁 文件系统统计

### sessions/ 目录
```
19 files total:
- 14 session_*.json      (详细会话记录)
- 3 request_dump_*.json  (请求/响应转储)
- 1 sessions.json        (索引)
- 1 *.jsonl             (日志格式)
```

### state.db 表结构
| Table | Purpose |
|-------|---------|
| `sessions` | 会话元数据 (20+ rows) |
| `messages` | 消息内容 (300+ rows) |
| `messages_fts*` | 全文搜索索引 |
| `schema_version`, `state_meta` | 系统元数据 |

---

## 📦 单个 Agent 遗留文件估算

假设一个活跃的 Hermes Agent 运行 1 周：

```
config.yaml               ~3-5 KB
auth.json                 ~2-4 KB
.state.db*                ~1-2 MB (含 sessions + messages)
sessions/                 ~500 KB - 2 MB (10-20 sessions)
memories/                 ~10-100 KB (按需扩展)
skills/                   ~50-200 KB (每个技能)
logs/                     ~100-500 KB
discord_threads.json      ~100 bytes
channel_directory.json    ~1 KB
─────────────────────────────────────────────
总计:                      ~2-4 MB per Agent
```

---

## 📝 建议的 Agent "墓碑" 信息提取

可以从 `state.db` 提取的关键指标：

```sql
-- 活跃度统计
SELECT 
    COUNT(*) as total_messages,
    SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) as user_inputs,
    SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) as assistant_replies,
    SUM(token_count) as total_tokens_used,
    MIN(started_at) as first_activity,
    MAX(ended_at) as last_activity
FROM messages m
JOIN sessions s ON m.session_id = s.id
WHERE s.source = 'discord';
```

需要我生成一个具体的提取脚本吗？