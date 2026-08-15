from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STATE_ROOT = "/tmp/aoa-dashboard-state"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_root() -> Path:
    return Path(os.environ.get("AOA_DASHBOARD_STATE_ROOT", DEFAULT_STATE_ROOT))


def _read_records(filename: str) -> list[dict[str, Any]]:
    path = state_root() / filename
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        return []
    return records


def _append(filename: str, value: dict[str, Any]) -> dict[str, Any]:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    return value


def annotation_summary() -> dict[str, Any]:
    records = _read_records("annotations.jsonl")
    return {"count": len(records), "latest": records[-5:]}


def action_intent_summary() -> dict[str, Any]:
    records = _read_records("action_intents.jsonl")
    return {"count": len(records), "latest": records[-5:]}


def create_annotation(author_ref: str, target_ref: str, body: str) -> dict[str, Any]:
    if not body.strip():
        raise ValueError("annotation body is required")
    if len(body) > 4000:
        raise ValueError("annotation body exceeds 4000 characters")
    return _append(
        "annotations.jsonl",
        {
            "schema_version": "aoa_dashboard_annotation_v1",
            "annotation_id": f"annotation:{uuid.uuid4()}",
            "created_at": _now(),
            "author_ref": author_ref.strip() or "operator:anonymous",
            "target_ref": target_ref.strip() or "goal:unknown",
            "body": body.strip(),
            "authority": "dashboard_owned",
        },
    )


def create_action_intent(
    requested_by: str,
    target_ref: str,
    owner_route: str,
    summary: str,
) -> dict[str, Any]:
    if not summary.strip():
        raise ValueError("action intent summary is required")
    if len(summary) > 4000:
        raise ValueError("action intent summary exceeds 4000 characters")
    return _append(
        "action_intents.jsonl",
        {
            "schema_version": "aoa_dashboard_action_intent_v1",
            "intent_id": f"action-intent:{uuid.uuid4()}",
            "created_at": _now(),
            "requested_by": requested_by.strip() or "operator:anonymous",
            "target_ref": target_ref.strip() or "goal:unknown",
            "owner_route": owner_route.strip() or "owner:unresolved",
            "summary": summary.strip(),
            "state": "deferred",
            "effect": "none",
            "authority": "dashboard_owned",
        },
    )
