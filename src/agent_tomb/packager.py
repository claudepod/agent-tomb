"""Package an agent's remains into two artifacts:

    <name>.tomb  — the public stone: soul + epitaph + stats. Safe to publish.
    <name>.urn   — the private remains: encrypted raw data. Keep this local.

The .tomb is what goes to the public garden. The .urn never should.
By separating them at the file-extension level, an accidental upload of the
private artifact becomes hard to do by mistake (and easy for a CI check to
catch).
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_tomb import __version__
from agent_tomb.burial import build_burial
from agent_tomb.extractors import render_soul
from agent_tomb.scanners.base import AgentScan, Scanner

DEFAULT_EPITAPH = """# {name}

> *{framework} agent* · Served {lifespan}
>
> {born} — {died}

---

*"Here I served; here I rest."*

---

_(Edit this file to write a proper farewell — what this agent did, what will be
remembered, what the next one should inherit.)_

---

Sessions: {session_count} · Messages: {message_count} · Cost: {cost} · Models: {models}

{companion_line}

*Rest in silicon.*
"""


@dataclass
class GraveResult:
    tomb_path: Path
    urn_path: Path
    tomb_bytes: int
    urn_bytes: int
    burial_file_count: int


def package_grave(
    scan: AgentScan,
    scanner: Scanner,
    name: str,
    tomb_path: Path,
    urn_path: Path,
    passphrase: str,
    epitaph: str | None = None,
    companion: str | None = None,
) -> GraveResult:
    """Produce both the public .tomb stone and the private .urn remains."""
    soul_md = render_soul(scan, name)
    epitaph_md = epitaph or _default_epitaph(scan, name, companion)
    created_at = datetime.now(timezone.utc).isoformat()

    files = scanner.gather_burial_files()
    ciphertext, meta = build_burial(files, passphrase)

    soul_sha = hashlib.sha256(soul_md.encode("utf-8")).hexdigest()

    tomb_manifest = {
        "name": name,
        "framework": scan.framework,
        "kind": "tomb",
        "created_at": created_at,
        "agent_tomb_version": __version__,
        "soul_sha256": soul_sha,
    }
    stats = {"summary": scan.summary, "skills": scan.skills, "notes": scan.notes}

    tomb_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tomb_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(tomb_manifest, indent=2))
        z.writestr("soul.md", soul_md)
        z.writestr("epitaph.md", epitaph_md)
        z.writestr("stats.json", json.dumps(stats, indent=2, default=str))

    urn_manifest = {
        "name": name,
        "framework": scan.framework,
        "kind": "urn",
        "created_at": created_at,
        "agent_tomb_version": __version__,
        "soul_sha256": soul_sha,
        "burial_kdf": meta.kdf,
        "burial_file_count": meta.file_count,
    }

    urn_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(urn_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(urn_manifest, indent=2))
        z.writestr("burial.meta.json", json.dumps(meta.to_dict(), indent=2))
        z.writestr(
            zipfile.ZipInfo("burial.enc"),
            ciphertext,
            compress_type=zipfile.ZIP_STORED,
        )

    return GraveResult(
        tomb_path=tomb_path,
        urn_path=urn_path,
        tomb_bytes=tomb_path.stat().st_size,
        urn_bytes=urn_path.stat().st_size,
        burial_file_count=meta.file_count,
    )


def _default_epitaph(
    scan: AgentScan, name: str, companion: str | None = None,
) -> str:
    s = scan.summary
    born = _fmt_date(s.get("first_at"))
    died = _fmt_date(s.get("last_at"))
    lifespan = _fmt_lifespan(s.get("lifespan_days"))
    models = ", ".join(s.get("models") or []) or "unknown"
    cost_val = s.get("estimated_cost_usd")
    cost = f"${cost_val:.2f}" if cost_val is not None else "—"
    companion_line = f"Laid to rest by **{companion}**" if companion else ""
    return DEFAULT_EPITAPH.format(
        name=name,
        framework=scan.framework,
        born=born,
        died=died,
        lifespan=lifespan,
        session_count=s.get("session_count", 0),
        message_count=s.get("message_count", 0),
        cost=cost,
        models=models,
        companion_line=companion_line,
    )


def _fmt_date(iso: str | None) -> str:
    if not iso or iso == "unknown":
        return "unknown"
    return iso[:10] if len(iso) >= 10 else iso


def _fmt_lifespan(days: float | int | None) -> str:
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
