"""EIS Procurement Radar orchestration layer."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path


radar_version = "0.6.0-r4h-source-resilience"
historical_result_extraction_version = "0.3.4-r3a-result-extraction"
opportunity_intelligence_version = "0.3.5-r3b-opportunities"


@lru_cache(maxsize=1)
def build_identity() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    identity = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    return identity or "unknown"
