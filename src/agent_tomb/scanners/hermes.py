"""Scanner for Hermes agent installations (`~/.hermes/` layout)."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_tomb.scanners.base import AgentScan, Scanner

SECRET_FILES = {".env", "auth.json"}
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{16,}"
)

# Files to seal in burial mode (relative to the Hermes root).
BURIAL_INCLUDE_FILES = (
    "config.yaml",
    "SOUL.md",
    "channel_directory.json",
    "discord_threads.json",
    "gateway_state.json",
    ".update_check",
    "state.db",
    "state.db-shm",
    "state.db-wal",
)

# Subdirectories whose contents should be included recursively.
BURIAL_INCLUDE_DIRS = ("sessions", "memories", "skills", "cron")

# Basenames that must NEVER be included in burial, even if a glob would match.
# Defense-in-depth alongside the burial module's HARD_DENY_BASENAMES.
BURIAL_EXCLUDE_BASENAMES = {
    ".env",
    "auth.json",
    "auth.lock",
    "gateway.lock",
    "gateway.pid",
}


class HermesScanner(Scanner):
    framework = "hermes"

    def detect(self) -> bool:
        return (self.root / "config.yaml").is_file() and (
            self.root / "state.db"
        ).is_file()

    def scan(self) -> AgentScan:
        result = AgentScan(framework=self.framework, root=self.root, detected=True)
        result.summary = self._db_stats()
        result.sessions = self._session_titles()
        result.skills = self._skills()
        result.persona = self._persona()
        result.secrets_found = self._secret_files()
        result.notes = self._notes()
        return result

    def _db_stats(self) -> dict[str, Any]:
        db = self.root / "state.db"
        out: dict[str, Any] = {"db_size_bytes": db.stat().st_size}
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            row = cur.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    MIN(started_at) AS first_at,
                    MAX(COALESCE(ended_at, started_at)) AS last_at,
                    SUM(input_tokens) AS in_tok,
                    SUM(output_tokens) AS out_tok,
                    SUM(cache_read_tokens) AS cache_read,
                    SUM(cache_write_tokens) AS cache_write,
                    SUM(estimated_cost_usd) AS cost
                FROM sessions
                """
            ).fetchone()
            out["session_count"] = row["n"] or 0
            out["first_at"] = _ts(row["first_at"])
            out["last_at"] = _ts(row["last_at"])
            out["lifespan_days"] = _days_between(row["first_at"], row["last_at"])
            out["input_tokens"] = row["in_tok"] or 0
            out["output_tokens"] = row["out_tok"] or 0
            out["cache_read_tokens"] = row["cache_read"] or 0
            out["cache_write_tokens"] = row["cache_write"] or 0
            out["estimated_cost_usd"] = round(row["cost"] or 0.0, 4)

            out["message_count"] = cur.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]

            out["models"] = [
                r[0]
                for r in cur.execute(
                    "SELECT model, COUNT(*) c FROM sessions "
                    "WHERE model IS NOT NULL GROUP BY model ORDER BY c DESC"
                )
            ]

            out["platforms"] = [
                r[0]
                for r in cur.execute(
                    "SELECT source, COUNT(*) c FROM sessions GROUP BY source ORDER BY c DESC"
                )
            ]

            out["top_tools"] = self._top_tools(cur)

        return out

    def _top_tools(self, cur: sqlite3.Cursor, limit: int = 10) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for (raw,) in cur.execute(
            "SELECT tool_calls FROM messages WHERE tool_calls IS NOT NULL"
        ):
            try:
                calls = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(calls, list):
                continue
            for call in calls:
                name = (call.get("function") or {}).get("name") or call.get("name")
                if name:
                    counter[name] += 1
        return counter.most_common(limit)

    def _session_titles(self) -> list[dict[str, Any]]:
        db = self.root / "state.db"
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, title, source, model, message_count, started_at
                FROM sessions
                ORDER BY started_at DESC
                LIMIT 20
                """
            ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"] or "(untitled)",
                "source": r["source"],
                "model": r["model"],
                "messages": r["message_count"] or 0,
                "started_at": _ts(r["started_at"]),
            }
            for r in rows
        ]

    def _skills(self) -> list[str]:
        sk = self.root / "skills"
        if not sk.is_dir():
            return []
        return sorted(p.name for p in sk.iterdir() if p.is_dir())

    def _persona(self) -> str | None:
        soul = self.root / "SOUL.md"
        if not soul.is_file():
            return None
        text = soul.read_text(encoding="utf-8", errors="replace")
        # strip HTML/markdown comments and the boilerplate header
        stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
        stripped = re.sub(r"^#\s*Hermes Agent Persona\s*", "", stripped).strip()
        return stripped or None

    def _secret_files(self) -> list[Path]:
        found = []
        for name in SECRET_FILES:
            p = self.root / name
            if p.is_file():
                found.append(p)
        # also check config.yaml content for embedded secrets, without exfiltrating
        cfg = self.root / "config.yaml"
        if cfg.is_file():
            try:
                if SECRET_PATTERN.search(cfg.read_text(encoding="utf-8", errors="ignore")):
                    found.append(cfg)
            except OSError:
                pass
        return found

    def gather_session_samples(
        self, max_sessions: int = 3, max_msgs_per_session: int = 8
    ) -> list[dict]:
        db = self.root / "state.db"
        if not db.is_file():
            return []
        samples: list[dict] = []
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            sessions = cur.execute(
                """
                SELECT id, COALESCE(title, '(untitled)') AS title
                FROM sessions
                WHERE message_count > 2
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (max_sessions,),
            ).fetchall()
            for s in sessions:
                rows = cur.execute(
                    """
                    SELECT role, content
                    FROM messages
                    WHERE session_id = ? AND role IN ('user', 'assistant')
                      AND content IS NOT NULL AND length(content) > 0
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (s["id"], max_msgs_per_session),
                ).fetchall()
                msgs = [
                    {"role": r["role"], "content": (r["content"] or "")[:1500]}
                    for r in reversed(rows)
                ]
                if msgs:
                    samples.append({"title": s["title"], "messages": msgs})
        return samples

    def llm_endpoint_hint(self) -> dict | None:
        cfg = self.root / "config.yaml"
        if not cfg.is_file():
            return None
        try:
            import yaml

            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        except (OSError, ImportError, yaml.YAMLError):
            return None
        providers = data.get("providers") or {}
        provider_name = (data.get("model") or {}).get("provider") or "openai"
        prov = providers.get(provider_name) or {}
        if not prov:
            return None
        models = prov.get("models") or {}
        first_model = next(iter(models.keys()), None) or (data.get("model") or {}).get("default")
        return {
            "base_url": prov.get("base_url") or (data.get("model") or {}).get("base_url"),
            "api_key": prov.get("api_key") or "",
            "model": first_model,
        }

    def gather_cleanup_paths(self) -> list[Path]:
        """Files that --cleanup may delete after a successful bury.

        Identical to burial files (anything sealed in the urn is recoverable).
        Never includes credential files (.env, auth.json) — those are user
        identity, not agent identity.
        """
        return [fs for _, fs in self.gather_burial_files()]

    def gather_burial_files(self) -> list[tuple[str, Path]]:
        pairs: list[tuple[str, Path]] = []
        for name in BURIAL_INCLUDE_FILES:
            p = self.root / name
            if p.is_file() and not _excluded_basename(p.name):
                pairs.append((name, p))
        for sub in BURIAL_INCLUDE_DIRS:
            d = self.root / sub
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*")):
                if not f.is_file():
                    continue
                if _excluded_basename(f.name):
                    continue
                pairs.append((f.relative_to(self.root).as_posix(), f))
        return pairs

    def _notes(self) -> list[str]:
        notes: list[str] = []
        sessions_dir = self.root / "sessions"
        if sessions_dir.is_dir():
            n = sum(1 for p in sessions_dir.glob("session_*.json"))
            if n:
                notes.append(
                    f"{n} session JSON dump(s) on disk (sessions/ — separate from state.db)"
                )
        memories = self.root / "memories"
        if memories.is_dir():
            files = list(memories.iterdir())
            notes.append(
                f"memories/ has {len(files)} entries"
                + (" (empty)" if not files else "")
            )
        return notes


def _excluded_basename(name: str) -> bool:
    """Return True for runtime junk (locks, pids) and named secrets."""
    if name in BURIAL_EXCLUDE_BASENAMES:
        return True
    return name.endswith(".lock") or name.endswith(".pid")


def _ts(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _days_between(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a) / 86400, 2)
