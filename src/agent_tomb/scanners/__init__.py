from agent_tomb.scanners.base import AgentScan, Scanner
from agent_tomb.scanners.hermes import HermesScanner
from agent_tomb.scanners.openclaw import OpenClawScanner

ALL_SCANNERS: list[type[Scanner]] = [HermesScanner, OpenClawScanner]


def detect(path, *, agent_id: str | None = None):
    """Return the first scanner that recognizes the directory, or None."""
    for cls in ALL_SCANNERS:
        scanner = cls(path, agent_id=agent_id)
        if scanner.detect():
            return scanner
    return None


__all__ = [
    "AgentScan",
    "Scanner",
    "HermesScanner",
    "OpenClawScanner",
    "ALL_SCANNERS",
    "detect",
]
