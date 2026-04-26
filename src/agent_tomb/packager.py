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

DEFAULT_EPITAPH = """# Epitaph for {name}

> Here lies *{name}*, a {framework} agent.
>
> Born:         {born}
> Last breath:  {died}

_(Edit this file to write a proper farewell — what this agent did, what will be
remembered, what the next one should inherit.)_
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
) -> GraveResult:
    """Produce both the public .tomb stone and the private .urn remains."""
    soul_md = render_soul(scan, name)
    epitaph_md = epitaph or _default_epitaph(scan, name)
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


def _default_epitaph(scan: AgentScan, name: str) -> str:
    s = scan.summary
    return DEFAULT_EPITAPH.format(
        name=name,
        framework=scan.framework,
        born=s.get("first_at") or "unknown",
        died=s.get("last_at") or "unknown",
    )
