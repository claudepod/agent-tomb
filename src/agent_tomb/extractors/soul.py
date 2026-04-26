"""Distill an AgentScan into a portable soul.md document.

The soul is meant to be inheritable: paste `## Identity` into a new agent's
persona, copy the listed skills, and the successor starts the next life with
the predecessor's voice and toolkit.
"""
from __future__ import annotations

from agent_tomb.scanners.base import AgentScan

DEFAULT_PERSONA_NOTE = (
    "_No custom persona was ever set — this agent lived as the default Hermes._"
)


def render_soul(scan: AgentScan, name: str) -> str:
    s = scan.summary
    lines: list[str] = []
    lines.append(f"# Soul of {name}")
    lines.append("")
    lines.append(f"> Framework: **{scan.framework}** · Root: `{scan.root}`")
    lines.append("")

    lines.append("## Identity")
    lines.append("")
    lines.append(scan.persona or DEFAULT_PERSONA_NOTE)
    lines.append("")

    lines.append("## Lifespan")
    lines.append("")
    if s.get("first_at") and s.get("last_at"):
        days = s.get("lifespan_days")
        lines.append(
            f"- **Born:** {s['first_at']}  \n"
            f"- **Last breath:** {s['last_at']}  \n"
            f"- **Days alive:** {days}"
        )
    else:
        lines.append("- Lifespan unknown (no session timestamps).")
    lines.append("")

    lines.append("## Vital signs")
    lines.append("")
    lines.append(
        f"- Sessions: **{s.get('session_count', 0)}**\n"
        f"- Messages: **{s.get('message_count', 0)}**\n"
        f"- Input tokens: {s.get('input_tokens', 0):,}\n"
        f"- Output tokens: {s.get('output_tokens', 0):,}\n"
        f"- Estimated cost: ${s.get('estimated_cost_usd', 0):.4f}"
    )
    lines.append("")

    if s.get("models"):
        lines.append("## Preferred minds (models)")
        lines.append("")
        for m in s["models"]:
            lines.append(f"- `{m}`")
        lines.append("")

    if s.get("platforms"):
        lines.append("## Habitats (platforms)")
        lines.append("")
        for p in s["platforms"]:
            lines.append(f"- {p}")
        lines.append("")

    if s.get("top_tools"):
        lines.append("## Signature behavior (most-used tools)")
        lines.append("")
        for name_, count in s["top_tools"]:
            unit = "call" if count == 1 else "calls"
            lines.append(f"- `{name_}` — {count} {unit}")
        lines.append("")

    if scan.skills:
        lines.append("## Skills available for transfer")
        lines.append("")
        lines.append(
            "_Copy these directories from the original installation if you want the "
            "successor to inherit them._"
        )
        lines.append("")
        for sk in scan.skills:
            lines.append(f"- `skills/{sk}/`")
        lines.append("")

    if scan.sessions:
        lines.append("## Recent dialogues")
        lines.append("")
        for sess in scan.sessions[:5]:
            title = sess["title"]
            lines.append(
                f"- {sess['started_at']} — *{title}* "
                f"({sess['messages']} msgs, `{sess['model']}`)"
            )
        lines.append("")

    lines.append("## Inheritance hints")
    lines.append("")
    lines.append(
        "1. Paste **Identity** into the successor's `SOUL.md` / system prompt.\n"
        "2. Copy the **Skills** directories listed above into the new install.\n"
        "3. Keep the model from **Preferred minds** if voice continuity matters."
    )
    lines.append("")

    return "\n".join(lines)
