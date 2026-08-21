#!/usr/bin/env python3
"""Advance one configured master-filter currentness lineage.

This is an explicit owner procedure. It reads the selected runtime binding,
derives the digest from the current filter bytes, and writes only the
current-head pointer plus append-only history. It never edits the filter or
bootstrap configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.currentness import advance_master_filter_currentness  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _config_values(config_path: Path) -> dict[str, Any]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("config is not readable JSON") from exc
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")

    correlation = config.get("current_correlation")
    if not isinstance(correlation, dict):
        raise ValueError("config.current_correlation is missing")
    binding = correlation.get("master_filter_currentness")
    if not isinstance(binding, dict):
        raise ValueError("config.current_correlation.master_filter_currentness is missing")

    filter_ref = binding.get("filter_ref")
    if filter_ref != correlation.get("master_filter_path"):
        raise ValueError("currentness filter_ref does not match master_filter_path")
    current_head_ref = binding.get("current_head_ref")
    history_ref = binding.get("history_ref")
    if not all(
        isinstance(value, str) and value.strip() for value in (filter_ref, current_head_ref, history_ref)
    ):
        raise ValueError("currentness binding refs are missing")
    master_thread_id = correlation.get("master_thread_id")
    goal_ref = config.get("goal_anchor_path")
    if not isinstance(master_thread_id, str) or not master_thread_id.strip():
        raise ValueError("config.current_correlation.master_thread_id is missing")
    if not isinstance(goal_ref, str) or not goal_ref.strip():
        raise ValueError("config.goal_anchor_path is missing")

    return {
        "filter_path": binding.get("filter_ref"),
        "current_head_path": current_head_ref,
        "history_path": history_ref,
        "master_thread_id": master_thread_id,
        "goal_ref": str(Path(goal_ref).resolve(strict=False)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance configured owner currentness from filter bytes")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--transition", choices=("initial", "advance", "rollback"), default="advance")
    parser.add_argument("--reviewed-at", default=None)
    args = parser.parse_args()

    try:
        values = _config_values(args.config.resolve(strict=False))
        receipt = advance_master_filter_currentness(
            **values,
            reviewed_at=args.reviewed_at or _utc_now(),
            transition=args.transition,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "aoa_dashboard_currentness_advancement_receipt_v1",
                    "status": "blocked",
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
