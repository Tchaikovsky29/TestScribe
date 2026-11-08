"""Compact, stable results for agents and editor integrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compact_report(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    """Keep tool output bounded; detailed evidence stays in report.json."""
    artifacts: dict[str, str | list[str]] = {}
    for name, value in report.get("artifacts", {}).items():
        if isinstance(value, str):
            artifacts[name] = str(Path(value).resolve())
        elif isinstance(value, list):
            artifacts[name] = [str(Path(item).resolve()) for item in value if isinstance(item, str)]
    return {
        "schema_version": 1,
        "run_id": report.get("run_id"),
        "status": report["status"],
        "passed": report["passed"],
        "reason": report["reason"],
        "start_url": report["start_url"],
        "final_url": report["final_url"],
        "checks": report["checks"],
        "steps": report["steps"],
        "model_calls": report["model_calls"],
        "elapsed_seconds": report["elapsed_seconds"],
        "report_path": str(report_path.resolve()),
        "artifacts": artifacts,
    }
