from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentScan:
    """Result of scanning an agent installation."""

    framework: str
    root: Path
    detected: bool
    summary: dict[str, Any] = field(default_factory=dict)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    secrets_found: list[Path] = field(default_factory=list)
    persona: str | None = None
    notes: list[str] = field(default_factory=list)


class Scanner:
    framework: str = "unknown"

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def detect(self) -> bool:
        raise NotImplementedError

    def scan(self) -> AgentScan:
        raise NotImplementedError

    def gather_burial_files(self) -> list[tuple[str, Path]]:
        """Return (archive_path, filesystem_path) pairs to seal in the urn.

        Subclasses must enumerate exactly the files that should be sealed in the
        encrypted urn — never the framework's source code, caches,
        node_modules, lockfiles, or anything in the secrets denylist.
        """
        raise NotImplementedError

    def gather_session_samples(self, max_sessions: int = 3, max_msgs_per_session: int = 8) -> list[dict]:
        """Return a few representative dialogue samples for LLM-assisted epitaph.

        Each sample is a dict: {"title": str, "messages": [{"role", "content"}, ...]}.
        Subclasses decide how to sample; defaults to empty.
        """
        return []

    def llm_endpoint_hint(self) -> dict | None:
        """Return a {base_url, api_key, model} hint discovered in the install,
        or None. Used as a fallback when --llm-* flags / env vars are absent.
        """
        return None

    def gather_cleanup_paths(self) -> list[Path]:
        """Filesystem paths that --cleanup may delete after a successful bury."""
        return [fs for _, fs in self.gather_burial_files()]
