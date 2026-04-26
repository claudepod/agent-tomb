"""Scanner for OpenClaw agent installations (`~/.openclaw/` layout).

OpenClaw supports multiple agents (e.g. main, bacchus, simons) under a
single installation.  When ``agent_id`` is given, the scanner scopes to
that single agent; otherwise it reports on all agents found in the
configuration.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_tomb.scanners.base import AgentScan, Scanner

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{16,}"
)

# Workspace markdown files that define the agent's identity/persona.
WORKSPACE_MD_FILES = (
    "SOUL.md",
    "MEMORY.md",
    "AGENTS.md",
    "IDENTITY.md",
    "HEARTBEAT.md",
    "TOOLS.md",
    "USER.md",
)

# Workspace subdirs whose contents should be sealed in the urn.
WORKSPACE_BURIAL_DIRS = ("memory", "skills")

# Basenames that must NEVER be included.
BURIAL_EXCLUDE_BASENAMES = {
    ".env",
    ".env.local",
    "auth.json",
    "auth-state.json",
    "auth-profiles.json",
    "models.json",
    "openclaw.json",
    ".DS_Store",
}

# Secret-bearing paths (relative to the openclaw root).
SECRET_DIRS = {"secrets"}
SECRET_FILES = {".env"}


class OpenClawScanner(Scanner):
    framework = "openclaw"

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def detect(self) -> bool:
        return (
            (self.root / "openclaw.json").is_file()
            and (self.root / "agents").is_dir()
        )

    def list_agents(self) -> list[str]:
        return [a["id"] for a in self._agent_entries()]

    def scan(self) -> AgentScan:
        result = AgentScan(framework=self.framework, root=self.root, detected=True)
        agents = self._agent_entries()

        if self.agent_id:
            agents = [a for a in agents if a["id"] == self.agent_id]
            if not agents:
                available = [a["id"] for a in self._agent_entries()]
                result.notes.append(
                    f"Agent '{self.agent_id}' not found. Available: {', '.join(available)}"
                )
                result.detected = False
                return result

        per_agent: list[dict[str, Any]] = []
        total_sessions = 0
        total_messages = 0
        all_models: list[str] = []
        all_platforms: list[str] = []
        first_ts: float | None = None
        last_ts: float | None = None

        for agent in agents:
            aid = agent["id"]
            stats = self._agent_stats(aid)
            per_agent.append({"id": aid, **stats})
            total_sessions += stats.get("session_count", 0)
            total_messages += stats.get("message_count", 0)
            for m in stats.get("models", []):
                if m not in all_models:
                    all_models.append(m)
            for p in stats.get("platforms", []):
                if p not in all_platforms:
                    all_platforms.append(p)
            if stats.get("first_ts") is not None:
                if first_ts is None or stats["first_ts"] < first_ts:
                    first_ts = stats["first_ts"]
            if stats.get("last_ts") is not None:
                if last_ts is None or stats["last_ts"] > last_ts:
                    last_ts = stats["last_ts"]

        result.summary = {
            "agents": per_agent,
            "agent_count": len(per_agent),
            "session_count": total_sessions,
            "message_count": total_messages,
            "models": all_models,
            "platforms": all_platforms,
            "first_at": _ts_iso(first_ts),
            "last_at": _ts_iso(last_ts),
            "lifespan_days": _days_between(first_ts, last_ts),
        }

        # Sessions list — union of all targeted agents.
        for a in per_agent:
            result.sessions.extend(a.get("recent_sessions", []))
        result.sessions.sort(key=lambda s: s.get("started_at", ""), reverse=True)
        result.sessions = result.sessions[:20]

        # Skills — from workspaces.
        for agent in agents:
            ws = self._workspace_for(agent)
            if ws:
                sk_dir = ws / "skills"
                if sk_dir.is_dir():
                    result.skills.extend(
                        sorted(p.name for p in sk_dir.iterdir() if p.is_dir())
                    )

        # Persona — first targeted agent's SOUL.md.
        for agent in agents:
            ws = self._workspace_for(agent)
            if ws:
                persona = self._read_persona(ws)
                if persona:
                    result.persona = persona
                    break

        result.secrets_found = self._secret_files()
        result.notes = self._notes(agents)
        return result

    def gather_burial_files(self) -> list[tuple[str, Path]]:
        agents = self._targeted_agents()
        pairs: list[tuple[str, Path]] = []

        for agent in agents:
            aid = agent["id"]

            # Session JSONL files (non-active + deleted).
            sessions_dir = self.root / "agents" / aid / "sessions"
            if sessions_dir.is_dir():
                active_ids = self._active_session_ids(sessions_dir)
                for f in sorted(sessions_dir.iterdir()):
                    if not f.is_file():
                        continue
                    if _excluded(f.name):
                        continue
                    # sessions.json is an index, not a session — skip.
                    if f.name == "sessions.json":
                        continue
                    # Skip active sessions.
                    stem = f.name.split(".jsonl")[0] if ".jsonl" in f.name else f.stem
                    if stem in active_ids:
                        continue
                    arc = f"agents/{aid}/sessions/{f.name}"
                    pairs.append((arc, f))

            # Workspace files.
            ws = self._workspace_for(agent)
            if ws and ws.is_dir():
                ws_prefix = ws.relative_to(self.root).as_posix()
                for md in WORKSPACE_MD_FILES:
                    p = ws / md
                    if p.is_file():
                        pairs.append((f"{ws_prefix}/{md}", p))
                for sub in WORKSPACE_BURIAL_DIRS:
                    d = ws / sub
                    if not d.is_dir():
                        continue
                    for f in sorted(d.rglob("*")):
                        if not f.is_file() or _excluded(f.name):
                            continue
                        pairs.append(
                            (f.relative_to(self.root).as_posix(), f)
                        )

        # Cron jobs belonging to targeted agent(s).
        cron_jobs = self.root / "cron" / "jobs.json"
        if cron_jobs.is_file():
            pairs.append(("cron/jobs.json", cron_jobs))

        return pairs

    def gather_session_samples(
        self, max_sessions: int = 3, max_msgs_per_session: int = 8
    ) -> list[dict]:
        agents = self._targeted_agents()
        samples: list[dict] = []

        for agent in agents:
            aid = agent["id"]
            sessions_dir = self.root / "agents" / aid / "sessions"
            if not sessions_dir.is_dir():
                continue

            # Pick the most recently modified JSONL files.
            jsonl_files = sorted(
                (f for f in sessions_dir.iterdir()
                 if f.suffix == ".jsonl" and ".deleted." not in f.name),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            for jf in jsonl_files[:max_sessions]:
                msgs = self._extract_messages(jf, max_msgs_per_session)
                if msgs:
                    title = jf.stem[:8]  # UUID prefix as title
                    samples.append({
                        "title": f"[{aid}] {title}",
                        "messages": msgs,
                    })

            if len(samples) >= max_sessions:
                break

        return samples[:max_sessions]

    def llm_endpoint_hint(self) -> dict | None:
        cfg_path = self.root / "openclaw.json"
        if not cfg_path.is_file():
            return None
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        agents_cfg = cfg.get("agents", {})
        defaults = agents_cfg.get("defaults", {})
        model_info = defaults.get("model", {})
        primary = model_info.get("primary", "")

        # Try to extract base_url from auth profiles.
        auth_dir = self.root / "agents" / "main" / "agent"
        api_key = ""
        if auth_dir.is_dir():
            profiles_path = auth_dir / "auth-profiles.json"
            if profiles_path.is_file():
                try:
                    profiles = json.loads(
                        profiles_path.read_text(encoding="utf-8")
                    )
                    for _name, prof in profiles.items():
                        if prof.get("apiKey"):
                            api_key = prof["apiKey"]
                            break
                except (OSError, json.JSONDecodeError):
                    pass

        if not primary:
            return None

        # OpenClaw model format: "provider/model-name"
        parts = primary.split("/", 1)
        provider = parts[0] if len(parts) > 1 else ""
        base_url_map = {
            "anthropic": "https://api.anthropic.com/v1",
            "openai": "https://api.openai.com/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta",
        }
        base_url = base_url_map.get(provider)

        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": parts[-1] if len(parts) > 1 else primary,
        }

    def gather_cleanup_paths(self) -> list[Path]:
        return [fs for _, fs in self.gather_burial_files()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        cfg_path = self.root / "openclaw.json"
        if not cfg_path.is_file():
            return {}
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _agent_entries(self) -> list[dict]:
        """Return the list of agent dicts from openclaw.json."""
        cfg = self._load_config()
        return cfg.get("agents", {}).get("list", [])

    def _targeted_agents(self) -> list[dict]:
        """Agents scoped by self.agent_id (or all if not set)."""
        agents = self._agent_entries()
        if self.agent_id:
            return [a for a in agents if a["id"] == self.agent_id]
        return agents

    def _workspace_for(self, agent: dict) -> Path | None:
        """Resolve the workspace path for an agent entry."""
        # Explicit workspace in config — must be under the openclaw root.
        ws = agent.get("workspace")
        if ws:
            resolved = Path(ws).expanduser().resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError:
                return None
            return resolved
        # Convention: main → workspace/, others → workspaces/<id>/
        aid = agent["id"]
        if aid == "main":
            ws_path = self.root / "workspace"
        else:
            ws_path = self.root / "workspaces" / aid
        return ws_path if ws_path.is_dir() else None

    def _active_session_ids(self, sessions_dir: Path) -> set[str]:
        """Read sessions.json to find currently active session IDs."""
        index_path = sessions_dir / "sessions.json"
        if not index_path.is_file():
            return set()
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            return {
                v["sessionId"]
                for v in data.values()
                if isinstance(v, dict) and "sessionId" in v
            }
        except (OSError, json.JSONDecodeError, TypeError):
            return set()

    def _agent_stats(self, agent_id: str) -> dict[str, Any]:
        """Compute stats for a single agent by reading its session JSONL files."""
        sessions_dir = self.root / "agents" / agent_id / "sessions"
        out: dict[str, Any] = {"id": agent_id}

        if not sessions_dir.is_dir():
            out["session_count"] = 0
            out["message_count"] = 0
            return out

        jsonl_files = [
            f for f in sessions_dir.iterdir()
            if f.suffix == ".jsonl" and ".deleted." not in f.name
        ]

        session_count = len(jsonl_files)
        message_count = 0
        models: list[str] = []
        platforms: list[str] = []
        first_ts: float | None = None
        last_ts: float | None = None
        recent_sessions: list[dict] = []

        for jf in jsonl_files:
            sess_info = self._parse_session_jsonl(jf)
            message_count += sess_info["message_count"]

            if sess_info.get("model") and sess_info["model"] not in models:
                models.append(sess_info["model"])
            if sess_info.get("platform") and sess_info["platform"] not in platforms:
                platforms.append(sess_info["platform"])

            ts = sess_info.get("timestamp")
            if ts is not None:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

            recent_sessions.append({
                "id": sess_info.get("session_id", jf.stem),
                "title": sess_info.get("title", jf.stem[:8]),
                "model": sess_info.get("model"),
                "messages": sess_info["message_count"],
                "started_at": _ts_iso(ts),
            })

        recent_sessions.sort(key=lambda s: s.get("started_at") or "", reverse=True)

        out.update({
            "session_count": session_count,
            "message_count": message_count,
            "models": models,
            "platforms": platforms,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "first_at": _ts_iso(first_ts),
            "last_at": _ts_iso(last_ts),
            "lifespan_days": _days_between(first_ts, last_ts),
            "recent_sessions": recent_sessions[:10],
        })
        return out

    def _parse_session_jsonl(self, path: Path) -> dict[str, Any]:
        """Parse a single JSONL session file and extract metadata."""
        info: dict[str, Any] = {
            "session_id": path.stem.split(".")[0],
            "message_count": 0,
            "model": None,
            "platform": None,
            "timestamp": None,
            "title": None,
        }
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = entry.get("type")
                if etype == "session":
                    info["session_id"] = entry.get("id", info["session_id"])
                    ts_str = entry.get("timestamp")
                    if ts_str:
                        info["timestamp"] = _parse_iso_ts(ts_str)
                elif etype == "message":
                    msg = entry.get("message", {})
                    role = msg.get("role")
                    if role in ("user", "assistant"):
                        info["message_count"] += 1
                elif etype == "model_change":
                    info["model"] = entry.get("modelId")
                    info["platform"] = entry.get("provider")
                elif etype == "summary":
                    info["title"] = entry.get("title")
        except OSError:
            pass

        return info

    def _extract_messages(
        self, path: Path, max_msgs: int
    ) -> list[dict[str, str]]:
        """Extract the last N user/assistant messages from a JSONL session."""
        msgs: list[dict[str, str]] = []
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "message":
                    continue
                msg = entry.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content", "")
                # Content can be a string or a list of content blocks.
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    content = "\n".join(text_parts)
                if content:
                    msgs.append({"role": role, "content": content[:1500]})
        except OSError:
            pass

        # Return the last N messages.
        return msgs[-max_msgs:]

    def _read_persona(self, workspace: Path) -> str | None:
        soul = workspace / "SOUL.md"
        if not soul.is_file():
            return None
        text = soul.read_text(encoding="utf-8", errors="replace")
        stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
        return stripped or None

    def _secret_files(self) -> list[Path]:
        found: list[Path] = []
        for name in SECRET_FILES:
            p = self.root / name
            if p.is_file():
                found.append(p)
        secrets_dir = self.root / "secrets"
        if secrets_dir.is_dir():
            for f in secrets_dir.rglob("*"):
                if f.is_file():
                    found.append(f)
        # Check auth dirs.
        for agent in self._targeted_agents():
            auth_dir = self.root / "agents" / agent["id"] / "agent"
            if auth_dir.is_dir():
                for f in auth_dir.iterdir():
                    if f.is_file():
                        found.append(f)
        return found

    def _notes(self, agents: list[dict]) -> list[str]:
        notes: list[str] = []
        ids = [a["id"] for a in agents]
        if self.agent_id:
            notes.append(f"Scoped to agent: {self.agent_id}")
        else:
            notes.append(f"Agents found: {', '.join(ids)} ({len(ids)} total)")

        for agent in agents:
            aid = agent["id"]
            sessions_dir = self.root / "agents" / aid / "sessions"
            if sessions_dir.is_dir():
                total = sum(
                    1 for f in sessions_dir.iterdir()
                    if f.suffix == ".jsonl" and ".deleted." not in f.name
                )
                deleted = sum(
                    1 for f in sessions_dir.iterdir()
                    if ".deleted." in f.name
                )
                active = self._active_session_ids(sessions_dir)
                if total or deleted:
                    notes.append(
                        f"\\[{aid}] {total} session(s) on disk "
                        f"({len(active)} active, {deleted} deleted)"
                    )

            ws = self._workspace_for(agent)
            if ws:
                mem_dir = ws / "memory"
                if mem_dir.is_dir():
                    mem_count = sum(1 for f in mem_dir.iterdir() if f.is_file())
                    notes.append(f"\\[{aid}] {mem_count} memory entries")
                sk_dir = ws / "skills"
                if sk_dir.is_dir():
                    sk_count = sum(1 for d in sk_dir.iterdir() if d.is_dir())
                    if sk_count:
                        notes.append(f"\\[{aid}] {sk_count} skill(s)")

        # Cron jobs.
        cron_path = self.root / "cron" / "jobs.json"
        if cron_path.is_file():
            try:
                cron = json.loads(cron_path.read_text(encoding="utf-8"))
                jobs = cron.get("jobs", [])
                targeted_ids = {a["id"] for a in agents}
                relevant = [
                    j for j in jobs
                    if j.get("agentId") in targeted_ids
                    or (j.get("agentId") is None and "main" in targeted_ids)
                ]
                if relevant:
                    names = [j.get("name", "?") for j in relevant]
                    notes.append(
                        f"{len(relevant)} cron job(s): {', '.join(names)}"
                    )
            except (OSError, json.JSONDecodeError):
                pass

        return notes


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _excluded(name: str) -> bool:
    if name in BURIAL_EXCLUDE_BASENAMES:
        return True
    return name.endswith(".lock") or name.endswith(".pid")


def _parse_iso_ts(s: str) -> float | None:
    """Parse ISO-8601 timestamp to epoch float."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _ts_iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _days_between(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a) / 86400, 2)
