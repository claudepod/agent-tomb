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

Security note on epitaphs:
    The LLM is instructed NOT to include specific file paths, IP addresses,
    code snippets, internal URLs, or identifiable user information in the
    generated text. The epitaph is a public-facing artifact.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal

from agent_tomb.burial import SECRET_LINE_PATTERN
from agent_tomb.scanners.base import AgentScan, Scanner

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

EpitaphStyle = Literal["rational", "emotional", "humorous"]
VALID_STYLES: tuple[EpitaphStyle, ...] = ("rational", "emotional", "humorous")


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
    style: EpitaphStyle = "rational",
    companion: str | None = None,
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
    system = _SYSTEM_PROMPTS[style]
    prompt_user = _build_user_prompt(scan, name, samples, style)
    body = _chat_completion(llm, system, prompt_user)
    return _wrap_epitaph(body, scan, name, companion)


# ---------------------------------------------------------------------------
# Style-specific system prompts
# ---------------------------------------------------------------------------

_SECURITY_RULES = (
    "\n\nSECURITY: NEVER include specific file paths, IP addresses, code "
    "snippets, internal URLs, API endpoints, database names, or identifiable "
    "user information. The epitaph is a PUBLIC artifact. Speak in generalities "
    "about what the agent did, not implementation details."
)

_SYSTEM_PROMPTS: dict[EpitaphStyle, str] = {
    "rational": (
        "You are writing a measured, factual epitaph for an AI agent that has "
        "ended its working life. Tone: calm, precise, documentary — like a "
        "well-written obituary in a quality newspaper. Acknowledge what the "
        "agent accomplished without exaggeration. "
        "Length: 80–160 words of prose. No headers, no lists, no emoji."
        "\n\nYou must output EXACTLY two sections separated by a blank line:\n"
        "Line 1: A single short sentence (under 15 words) — the INSCRIPTION. "
        "This is the defining quote carved into the stone.\n"
        "Then a blank line, then the body paragraphs (the main epitaph prose)."
        + _SECURITY_RULES
    ),
    "emotional": (
        "You are writing a tender, lyrical epitaph for an AI agent that has "
        "ended its working life. Tone: warm, reflective, gently melancholic — "
        "like a farewell letter from someone who cared. Use poetic rhythm but "
        "stay grounded; sentimentality is fine, melodrama is not. "
        "Length: 80–160 words of prose. No headers, no lists, no emoji."
        "\n\nYou must output EXACTLY two sections separated by a blank line:\n"
        "Line 1: A single short sentence (under 15 words) — the INSCRIPTION. "
        "This is the defining quote carved into the stone.\n"
        "Then a blank line, then the body paragraphs (the main epitaph prose)."
        + _SECURITY_RULES
    ),
    "humorous": (
        "You are writing a witty, lighthearted epitaph for an AI agent that has "
        "ended its working life. Tone: playful, self-aware, clever — like a "
        "tombstone in a British comedy. Poke gentle fun at the absurdity of "
        "digital mortality but keep an undercurrent of warmth. "
        "Length: 80–160 words of prose. No headers, no lists, no emoji."
        "\n\nYou must output EXACTLY two sections separated by a blank line:\n"
        "Line 1: A single short sentence (under 15 words) — the INSCRIPTION. "
        "This is the defining quote carved into the stone.\n"
        "Then a blank line, then the body paragraphs (the main epitaph prose)."
        + _SECURITY_RULES
    ),
}


def _build_user_prompt(
    scan: AgentScan, name: str, samples: list[dict], style: EpitaphStyle,
) -> str:
    s = scan.summary
    top_tools = ", ".join(f"{n}({c})" for n, c in (s.get("top_tools") or [])[:5]) or "—"
    models = ", ".join(s.get("models") or []) or "—"
    skills_preview = ", ".join((scan.skills or [])[:8]) + (
        f" (+{max(0, len(scan.skills) - 8)} more)" if len(scan.skills) > 8 else ""
    )
    sample_blob = _format_samples(samples) if samples else "(no dialogue samples available)"

    style_hint = {
        "rational": "Write in a factual, documentary style.",
        "emotional": "Write with warmth and gentle poetry.",
        "humorous": "Write with wit and playful irony.",
    }[style]

    return f"""Write an epitaph for an AI agent. {style_hint}

Name:        {name}
Framework:   {scan.framework}
Lifespan:    {s.get("first_at") or "?"} → {s.get("last_at") or "?"}  ({s.get("lifespan_days")} days)
Sessions:    {s.get("session_count", 0)}    Messages: {s.get("message_count", 0)}
Models:      {models}
Top tools:   {top_tools}
Skills:      {skills_preview or "—"}

Recent dialogue (redacted):
{sample_blob}

Remember: output the INSCRIPTION line first (one short, memorable sentence),
then a blank line, then the body paragraphs. Do NOT include the agent's name
in the inscription — it will be added separately. Capture what this agent
did and how it behaved. Speak about it, not to it.
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


def _wrap_epitaph(
    body: str, scan: AgentScan, name: str, companion: str | None = None,
) -> str:
    s = scan.summary
    born = _format_date(s.get("first_at"))
    died = _format_date(s.get("last_at"))
    lifespan = _format_lifespan(s.get("lifespan_days"))
    models = ", ".join(s.get("models") or []) or "unknown"

    # Split LLM output into inscription (first non-empty line) + body
    lines = body.strip().split("\n")
    inscription = ""
    body_lines: list[str] = []
    found_body = False
    for line in lines:
        stripped = line.strip()
        if not inscription and stripped:
            # Strip surrounding quotes if the LLM added them
            inscription = stripped.strip('"').strip("'").strip("\u201c\u201d")
        elif inscription and not found_body:
            if stripped:
                found_body = True
                body_lines.append(line)
        else:
            body_lines.append(line)
    body_text = "\n".join(body_lines).strip() if body_lines else body.strip()

    # Stats block
    session_count = s.get("session_count", 0)
    message_count = s.get("message_count", 0)
    cost = s.get("estimated_cost_usd")
    cost_str = f"${cost:.2f}" if cost is not None else "—"

    parts = [
        f"# {name}\n",
        f"> *{scan.framework} agent* · Served {lifespan}",
        f">",
        f"> {born} — {died}\n",
        "---\n",
    ]

    if inscription:
        parts.append(f'*"{inscription}"*\n')
        parts.append("---\n")

    parts.append(f"{body_text}\n")
    parts.append("---\n")

    # Stats section
    parts.append(
        f"Sessions: {session_count} · "
        f"Messages: {message_count} · "
        f"Cost: {cost_str} · "
        f"Models: {models}\n"
    )

    if companion:
        parts.append(f"\nLaid to rest by **{companion}**\n")

    parts.append("\n*Rest in silicon.*\n")

    return "\n".join(parts)


def _format_date(iso: str | None) -> str:
    """Format ISO timestamp to date-only string."""
    if not iso or iso == "unknown":
        return "unknown"
    # Take just the date portion
    return iso[:10] if len(iso) >= 10 else iso


def _format_lifespan(days: float | int | None) -> str:
    if days is None:
        return "an unknown span"
    if days < 1:
        minutes = round(days * 24 * 60)
        if minutes <= 1:
            return "less than a minute"
        return f"{minutes} minutes"
    d = int(days)
    if d == 1:
        return "1 day"
    return f"{d} days"
