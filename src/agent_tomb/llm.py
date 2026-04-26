"""LLM-assisted epitaph generation.

Privacy posture:
    - The default `extract-soul` / `bury` flow does NOT call any LLM.
    - When the user opts in via `--epitaph llm`, samples are scrubbed for
      secret-shaped patterns before any network call.
    - For local endpoints (anything resolving to 127.0.0.1 / ::1 / localhost),
      we proceed without warning.
    - For remote endpoints, the caller is required to pass `allow_remote=True`,
      which the CLI maps to `--remote-ok`. Without it, we refuse rather than
      ship raw conversation samples to a third party.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agent_tomb.burial import SECRET_LINE_PATTERN
from agent_tomb.scanners.base import AgentScan, Scanner

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    def is_local(self) -> bool:
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        return host in LOCAL_HOSTS


def resolve_llm_config(
    scanner: Scanner,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
) -> LLMConfig:
    """Resolution order: explicit args > env vars > scanner hint."""
    hint = scanner.llm_endpoint_hint() or {}
    final_base = (
        base_url
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or hint.get("base_url")
    )
    final_key = api_key or os.environ.get("OPENAI_API_KEY") or hint.get("api_key") or ""
    final_model = model or os.environ.get("OPENAI_MODEL") or hint.get("model")

    missing = [
        n
        for n, v in (("base_url", final_base), ("model", final_model))
        if not v
    ]
    if missing:
        raise ValueError(
            f"LLM endpoint not configured: missing {', '.join(missing)}. "
            "Pass --llm-base-url / --llm-model, set OPENAI_BASE_URL / OPENAI_MODEL, "
            "or run from a directory where the scanner can detect a config."
        )

    return LLMConfig(base_url=final_base.rstrip("/"), api_key=final_key, model=final_model)


def generate_epitaph(
    scan: AgentScan,
    scanner: Scanner,
    name: str,
    llm: LLMConfig,
    *,
    allow_remote: bool = False,
    sample_sessions: int = 3,
    sample_msgs: int = 8,
) -> str:
    if not llm.is_local() and not allow_remote:
        raise PermissionError(
            f"Refusing to send conversation samples to remote host "
            f"{urllib.parse.urlparse(llm.base_url).hostname}. "
            "Pass --remote-ok to acknowledge."
        )

    samples = scanner.gather_session_samples(
        max_sessions=sample_sessions, max_msgs_per_session=sample_msgs
    )
    samples = _scrub_samples(samples)
    prompt_user = _build_user_prompt(scan, name, samples)
    body = _chat_completion(llm, _SYSTEM_PROMPT, prompt_user)
    return _wrap_epitaph(body, scan, name)


_SYSTEM_PROMPT = (
    "You are writing brief, dignified epitaphs for AI agents that have ended "
    "their working life. Tone: quiet, reflective, unsentimental, never boastful. "
    "Length: 80–160 words of prose, no headers, no lists, no emoji. Output ONLY "
    "the epitaph body in plain Markdown."
)


def _build_user_prompt(scan: AgentScan, name: str, samples: list[dict]) -> str:
    s = scan.summary
    top_tools = ", ".join(f"{n}({c})" for n, c in (s.get("top_tools") or [])[:5]) or "—"
    models = ", ".join(s.get("models") or []) or "—"
    skills_preview = ", ".join((scan.skills or [])[:8]) + (
        f" (+{max(0, len(scan.skills) - 8)} more)" if len(scan.skills) > 8 else ""
    )
    sample_blob = _format_samples(samples) if samples else "(no dialogue samples available)"
    return f"""Write an epitaph for an AI agent.

Name:        {name}
Framework:   {scan.framework}
Lifespan:    {s.get("first_at") or "?"} → {s.get("last_at") or "?"}  ({s.get("lifespan_days")} days)
Sessions:    {s.get("session_count", 0)}    Messages: {s.get("message_count", 0)}
Models:      {models}
Top tools:   {top_tools}
Skills:      {skills_preview or "—"}

Recent dialogue (redacted):
{sample_blob}

Capture what this agent did and how it behaved. Speak about it, not to it.
"""


def _format_samples(samples: list[dict]) -> str:
    out = []
    for sess in samples:
        out.append(f"--- session: {sess['title']} ---")
        for m in sess["messages"]:
            content = (m["content"] or "").strip().replace("\n", " ")
            if len(content) > 600:
                content = content[:600] + "…"
            out.append(f"[{m['role']}] {content}")
    return "\n".join(out)


def _scrub_samples(samples: list[dict]) -> list[dict]:
    out = []
    for sess in samples:
        scrubbed_msgs = []
        for m in sess["messages"]:
            text = (m["content"] or "").encode("utf-8", errors="replace")
            text = SECRET_LINE_PATTERN.sub(rb"\1<REDACTED>", text)
            text = _SCRUB_INLINE.sub("<REDACTED>", text.decode("utf-8", errors="replace"))
            scrubbed_msgs.append({"role": m["role"], "content": text})
        out.append({"title": sess["title"], "messages": scrubbed_msgs})
    return out


# Inline tokens that look like API keys, even outside key:value structure.
_SCRUB_INLINE = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|ghp_[A-Za-z0-9]{20,}|"
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,})"
)


def _chat_completion(llm: LLMConfig, system: str, user: str, timeout: int = 60) -> str:
    payload = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }
    headers = {"Content-Type": "application/json"}
    if llm.api_key:
        headers["Authorization"] = f"Bearer {llm.api_key}"
    req = urllib.request.Request(
        f"{llm.base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM call failed ({e.code}): {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM endpoint unreachable: {e.reason}") from e

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM returned no choices: {json.dumps(data)[:300]}")
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("LLM returned an empty completion.")
    return content.strip()


def _wrap_epitaph(body: str, scan: AgentScan, name: str) -> str:
    s = scan.summary
    born = s.get("first_at") or "unknown"
    died = s.get("last_at") or "unknown"
    return f"""# Epitaph for {name}

> Here lies *{name}*, a {scan.framework} agent.
>
> Born:         {born}
> Last breath:  {died}

{body}
"""
