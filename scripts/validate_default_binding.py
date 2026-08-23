#!/usr/bin/env python3
"""Keep the shipped bootstrap reusable and free of current-instance data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "bootstrap.json"
FORBIDDEN_KEYS = frozenset(
    {
        "goal_id",
        "master_thread_id",
        "task_local_dir",
        "master_filter_path",
        "master_filter_currentness",
        "goal_anchor_path",
        "goal_anchor_expected_sha256",
        "owner_goal_source",
        "owner_thread_source",
        "goal_topology_source",
        "goal_catalog_source",
        "current_correlation",
        "pressure_inbox",
        "current_holder",
        "actor_receipt_path",
        "stats_surface_path",
        "stats_registry_path",
        "historical_bootstrap",
    }
)
INSTANCE_PATH_RE = re.compile(
    r"(?:/home/|/srv/abyss-machine/tmp/|/\.codex/attachments/|master-return|\bgoal-[0-9a-f]{8}(?:-[0-9a-f]{4,})*)",
    re.IGNORECASE,
)


class DefaultBindingError(RuntimeError):
    """Raised when the default route accidentally regains instance authority."""


def _walk(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, str(key))
            if key in FORBIDDEN_KEYS:
                errors.append(".".join(child_path))
            errors.extend(_walk(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_walk(child, (*path, str(index))))
    elif isinstance(value, str) and INSTANCE_PATH_RE.search(value):
        errors.append(".".join(path))
    return errors


def validate_default_binding(path: Path = DEFAULT_PATH) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DefaultBindingError(f"cannot read default bootstrap: {exc}") from exc
    if not isinstance(payload, dict):
        raise DefaultBindingError("default bootstrap must be an object")
    if payload.get("schema_version") != "aoa_dashboard_bootstrap_config_v2":
        raise DefaultBindingError("default bootstrap schema is not reusable v2")
    if payload.get("profile") != "reusable-owner-backed":
        raise DefaultBindingError("default bootstrap profile is not reusable-owner-backed")
    selector = payload.get("runtime_binding")
    if not isinstance(selector, dict) or selector.get("required") is not True or selector.get("selection") != "explicit_process_input":
        raise DefaultBindingError("default bootstrap does not require explicit process binding")
    errors = _walk(payload)
    if errors:
        raise DefaultBindingError("current-instance fields in default bootstrap: " + ", ".join(errors))


def main() -> int:
    validate_default_binding()
    print(f"[ok] reusable default binding: {DEFAULT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DefaultBindingError as exc:
        print(f"[error] {exc}")
        raise SystemExit(1) from exc
