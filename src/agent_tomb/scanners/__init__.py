from agent_tomb.scanners.base import AgentScan, Scanner
from agent_tomb.scanners.hermes import HermesScanner

ALL_SCANNERS: list[type[Scanner]] = [HermesScanner]


def detect(path):
    """Return the first scanner that recognizes the directory, or None."""
    for cls in ALL_SCANNERS:
        scanner = cls(path)
        if scanner.detect():
            return scanner
    return None


__all__ = ["AgentScan", "Scanner", "HermesScanner", "ALL_SCANNERS", "detect"]
