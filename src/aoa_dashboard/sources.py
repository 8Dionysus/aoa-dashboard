from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .activity import observe_actor_activity
from .correlation import observe_current_correlation
from .runtime_binding import RuntimeBindingError, validate_goal_anchor_payload
from .source_binding import FileSnapshot, read_file_snapshot, snapshot_ref


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value:
        return value
    return None


def _stat(path: Path) -> dict[str, Any]:
    try:
        item = path.stat()
    except OSError as exc:
        return {"exists": False, "error": str(exc)}
    return {
        "exists": True,
        "size_bytes": item.st_size,
        "mtime": _iso_from_timestamp(item.st_mtime),
        "mtime_epoch": item.st_mtime,
    }


def _ref(label: str, path: str, claim_limit: str) -> dict[str, str]:
    return {"label": label, "kind": "source_path", "ref": path, "path": path, "claim_limit": claim_limit}


def _json_ref(label: str, ref: str, claim_limit: str) -> dict[str, str]:
    return {"label": label, "kind": "owner_ref", "ref": ref, "claim_limit": claim_limit}


def _error_source(source_id: str, owner: str, path: str, error: str) -> dict[str, Any]:
    return {
        "id": source_id,
        "owner": owner,
        "state": "invalid",
        "freshness": "invalid",
        "observation": f"Source could not be read: {error}",
        "metadata": {},
        "evidence_refs": [_ref("unreadable source", path, "The source is not available for a current claim.")],
        "claim_limit": "Invalid source input is not converted to zero, success, or owner truth.",
    }


def _missing_source(source_id: str, owner: str, path: str | None, observation: str) -> dict[str, Any]:
    ref = path or f"{owner}:unselected"
    return {
        "id": source_id,
        "owner": owner,
        "state": "missing",
        "freshness": "missing",
        "observation": observation,
        "metadata": {},
        "evidence_refs": [_ref("unselected source", ref, "No selected owner binding is available; no current fact is inferred.")],
        "claim_limit": "Missing source input is not converted to zero, success, or owner truth.",
    }


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "top-level JSON value is not an object"
    return value, None


def observe_goal(config: dict[str, Any], snapshot: FileSnapshot | None = None) -> dict[str, Any]:
    path_value = config.get("goal_anchor_path")
    if not isinstance(path_value, str) or not path_value:
        return _missing_source("goal-anchor", "goal-anchor", None, "No Goal Anchor is selected without an explicit runtime binding.")
    path = Path(path_value)
    stats = _stat(path)
    claim_limit = "Anchor binding and digest are source evidence; they do not prove execution, review, or acceptance."
    current_binding = config.get("runtime_binding_state") == "bound"
    snapshot = snapshot or read_file_snapshot(
        path,
        expected_digest=config.get("goal_anchor_expected_sha256"),
        parser="json" if current_binding else "text",
        reject_duplicate_keys=current_binding,
    )
    currentness = snapshot.currentness
    state = {
        "current_at_read": "bound",
        "stale": "stale",
        "deferred": "deferred",
        "unknown": "unknown",
        "missing": "missing",
        "invalid": "invalid",
    }.get(snapshot.currentness, "unknown")
    anchor_identity: dict[str, Any] | None = None
    observation_override: str | None = None
    if current_binding and state == "bound":
        selected = {
            "goal_id": config.get("goal_id"),
            "master_thread_id": (
                config.get("current_correlation", {}).get("master_thread_id")
                if isinstance(config.get("current_correlation"), dict)
                else None
            ),
        }
        if isinstance(config.get("title"), str) and config["title"]:
            selected["title"] = config["title"]
        try:
            anchor_identity = validate_goal_anchor_payload(snapshot.parsed, selected)  # type: ignore[arg-type]
        except (RuntimeBindingError, TypeError, KeyError) as exc:
            state = "invalid"
            currentness = "invalid"
            observation_override = f"Configured structured Goal Anchor is not bound to the selected Goal: {exc}."
    anchor_ref = snapshot_ref(
        snapshot,
        label="Goal Anchor",
        kind="goal_anchor",
        owner="goal-anchor",
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="source_owner_metadata",
        claim_limit="Goal Anchor ref and digest bind this projection; they do not prove execution, review, or acceptance.",
        currentness_override=currentness,
        freshness_override=currentness,
        extra_degradation=["goal_anchor_semantic_identity_invalid"] if currentness == "invalid" and state == "invalid" else None,
    )
    observation = observation_override or {
        "current_at_read": "The configured Goal Anchor is readable at projection time.",
        "stale": "The configured Goal Anchor bytes were read, but the configured expected digest does not match.",
        "missing": "Configured Goal Anchor path is absent.",
        "invalid": "Configured Goal Anchor cannot be treated as a valid current source snapshot.",
    }.get(currentness, "Goal Anchor currentness is not attested.")
    return {
        "id": "goal-anchor",
        "owner": "goal-anchor",
        "state": state,
        "freshness": currentness,
        "observation": observation,
        "metadata": {
            "goal_id": config.get("goal_id"),
            "title": config.get("title"),
            "anchor_digest": snapshot.digest,
            "anchor_expected_sha256": snapshot.expected_digest,
            "anchor_currentness": currentness,
            "semantic_identity": anchor_identity,
            "size_bytes": stats.get("size_bytes"),
            "mtime": stats.get("mtime"),
        },
        "evidence_refs": [anchor_ref],
        "claim_limit": claim_limit,
    }


def _record_summary(path: Path, goal_id: str | None = None) -> dict[str, Any]:
    payload_types: Counter[str] = Counter()
    top_level_types: Counter[str] = Counter()
    payload_schema_versions: Counter[str] = Counter()
    timestamps: list[str] = []
    valid = 0
    invalid = 0
    matching_goal = 0

    def contains_goal(value: Any) -> bool:
        if isinstance(value, dict):
            return any(contains_goal(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_goal(item) for item in value)
        return goal_id is not None and value == goal_id

    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except (UnicodeError, json.JSONDecodeError):
                    invalid += 1
                    continue
                if not isinstance(item, dict):
                    invalid += 1
                    continue
                valid += 1
                value_type = item.get("type") or item.get("event_kind")
                if isinstance(value_type, str):
                    top_level_types[value_type] += 1
                payload = item.get("payload")
                if isinstance(payload, dict):
                    payload_type = payload.get("type")
                    if isinstance(payload_type, str):
                        payload_types[payload_type] += 1
                    schema_version = payload.get("schema_version")
                    if isinstance(schema_version, str):
                        payload_schema_versions[schema_version] += 1
                timestamp = item.get("timestamp")
                if timestamp is None and isinstance(payload, dict):
                    timestamp = payload.get("timestamp")
                if timestamp is None:
                    timestamp = item.get("observed_at")
                if isinstance(timestamp, str) and timestamp:
                    timestamps.append(timestamp)
                if contains_goal(item):
                    matching_goal += 1
    except (OSError, UnicodeError) as exc:
        return {"valid_records": 0, "invalid_records": 0, "error": str(exc)}

    return {
        "valid_records": valid,
        "invalid_records": invalid,
        "payload_types": dict(payload_types),
        "payload_schema_versions": dict(payload_schema_versions),
        "top_level_types": dict(top_level_types),
        "latest_timestamp": max(timestamps) if timestamps else None,
        "matching_goal_records": matching_goal,
    }


def observe_session(config: dict[str, Any]) -> dict[str, Any]:
    historical = config.get("historical_bootstrap")
    if not isinstance(historical, dict):
        # Legacy configs are accepted only as historical bindings. The default
        # config never uses this fallback as the current holder surface.
        historical = {
            "session_manifest_path": config.get("session_manifest_path"),
            "session_archive_raw_path": config.get("session_archive_raw_path"),
        }
    manifest_value = historical.get("session_manifest_path")
    archive_value = historical.get("session_archive_raw_path")
    if not isinstance(manifest_value, str) or not manifest_value or not isinstance(archive_value, str) or not archive_value:
        return _missing_source("aoa-session-memory", ".aoa/session-memory", None, "No historical session binding is selected.")
    manifest_path = Path(manifest_value)
    archive_path = Path(archive_value)
    manifest, error = _read_json(manifest_path)
    manifest_ref = _ref(
        "session manifest",
        str(manifest_path),
        "Manifest metadata and refs do not establish live process health or semantic completion.",
    )
    archive_ref = _ref(
        "archived raw session",
        str(archive_path),
        "Archived raw evidence is only current when its recorded source snapshot matches the live source.",
    )
    if error or manifest is None:
        return _error_source("aoa-session-memory", ".aoa/session-memory", str(manifest_path), error or "unknown error")

    raw = manifest.get("raw") if isinstance(manifest.get("raw"), dict) else {}
    live_path_value = raw.get("source_path")
    live_path = Path(live_path_value) if isinstance(live_path_value, str) and live_path_value else None
    live_stats = _stat(live_path) if live_path else {"exists": False, "error": "manifest has no live source_path"}
    archive_stats = _stat(archive_path)
    refs = [manifest_ref, archive_ref]
    if live_path:
        refs.insert(
            0,
            _ref(
                "live rollout source",
                str(live_path),
                "Live transcript metadata is not a runtime health check and raw bodies are not projected.",
            ),
        )

    if not live_stats.get("exists"):
        return {
            "id": "aoa-session-memory",
            "owner": ".aoa/session-memory",
            "state": "missing",
            "freshness": "missing",
            "runtime_state": "unknown",
            "observation": "The configured historical bootstrap manifest is readable but its live source is missing.",
            "metadata": {
                "manifest_event_count": manifest.get("latest_event_count"),
                "binding_scope": "historical_bootstrap",
                "current_holder": False,
            },
            "evidence_refs": refs,
            "claim_limit": "Historical bootstrap evidence is not the current holder and is not interpreted as zero events, completion, or runtime health.",
        }

    live_summary = _record_summary(live_path, config["goal_id"])
    archive_summary = _record_summary(archive_path, config["goal_id"]) if archive_stats.get("exists") else {}
    live_changed_since_archive = False
    if archive_stats.get("exists"):
        live_changed_since_archive = (
            live_stats.get("size_bytes") != archive_stats.get("size_bytes")
            or float(live_stats.get("mtime_epoch", 0)) > float(archive_stats.get("mtime_epoch", 0))
        )
    archive_state = "deferred" if live_changed_since_archive else "current_at_read"
    if live_summary.get("invalid_records", 0):
        source_state = "invalid"
        freshness = "invalid"
        observation = "The historical bootstrap session source contains malformed records; metadata is partial."
    else:
        source_state = "deferred" if live_changed_since_archive else "running"
        freshness = archive_state
        observation = (
            "Historical bootstrap session metadata is readable; the archive is deferred while the live source advances."
            if live_changed_since_archive
            else "Historical bootstrap session metadata and archive snapshot are aligned at read time."
        )
    return {
        "id": "aoa-session-memory",
        "owner": ".aoa/session-memory",
        "state": source_state,
        "freshness": freshness,
        "runtime_state": "running",
        "observation": observation + " This binding is historical and is not the current holder.",
        "metadata": {
            "binding_scope": "historical_bootstrap",
            "current_holder": False,
            "manifest_event_count": manifest.get("latest_event_count"),
            "live_size_bytes": live_stats.get("size_bytes"),
            "archive_size_bytes": archive_stats.get("size_bytes"),
            "live_latest_timestamp": live_summary.get("latest_timestamp"),
            "archive_latest_timestamp": archive_summary.get("latest_timestamp"),
            "live_payload_types": live_summary.get("payload_types", {}),
            "archive_payload_types": archive_summary.get("payload_types", {}),
            "live_records": live_summary.get("valid_records", 0),
            "archive_records": archive_summary.get("valid_records", 0),
            "matching_goal_records": live_summary.get("matching_goal_records", 0),
            "archive_state": archive_state,
        },
        "evidence_refs": refs,
        "claim_limit": "The historical `.aoa` source proves only bounded transcript-source observations; it is not the current holder and is not proof of return, review, acceptance, or runtime health.",
    }


def observe_actor_receipts(config: dict[str, Any]) -> dict[str, Any]:
    path_value = config.get("actor_receipt_path")
    if not isinstance(path_value, str) or not path_value:
        return _missing_source("actor-responsibility-receipts", "aoa-agents", None, "No actor publisher is selected by the runtime binding.")
    path = Path(path_value)
    stats = _stat(path)
    claim_limit = "An actor receipt belongs to its owning actor route; it cannot be reassigned to this Goal without a goal-scoped match."
    ref = _ref("aoa-agents live responsibility receipts", str(path), claim_limit)
    if not stats.get("exists"):
        return {
            "id": "actor-responsibility-receipts",
            "owner": "aoa-agents",
            "state": "missing",
            "freshness": "missing",
            "publisher_status": "optional-missing",
            "observation": "Optional actor publisher is absent; no actor count is inferred.",
            "metadata": {"records": 0, "goal_match_records": 0},
            "evidence_refs": [ref],
            "claim_limit": claim_limit,
        }
    summary = _record_summary(path, config["goal_id"])
    if summary.get("error") or summary.get("invalid_records", 0):
        return {
            "id": "actor-responsibility-receipts",
            "owner": "aoa-agents",
            "state": "invalid",
            "freshness": "invalid",
            "publisher_status": "invalid",
            "observation": "Actor publisher exists but its feed is not fully parseable.",
            "metadata": summary,
            "evidence_refs": [ref],
            "claim_limit": claim_limit,
        }
    matched = summary.get("matching_goal_records", 0)
    return {
        "id": "actor-responsibility-receipts",
        "owner": "aoa-agents",
        "state": "bound" if matched else "unknown",
        "freshness": "current_at_read",
        "publisher_status": "present",
        "observation": (
            "A goal-scoped actor receipt is present."
            if matched
            else "Publisher is present, but no receipt matches this Goal; another actor is not conflated with Luna."
        ),
        "metadata": {
            "records": summary.get("valid_records", 0),
            "goal_match_records": matched,
            "latest_timestamp": summary.get("latest_timestamp"),
            "payload_types": summary.get("payload_types", {}),
        },
        "evidence_refs": [ref],
        "claim_limit": claim_limit,
    }


def observe_stats(config: dict[str, Any], actor_source: dict[str, Any]) -> dict[str, Any]:
    path_value = config.get("stats_surface_path")
    registry_value = config.get("stats_registry_path")
    if not isinstance(path_value, str) or not path_value or not isinstance(registry_value, str) or not registry_value:
        return _missing_source("aoa-stats-source-coverage", "aoa-stats", None, "No aoa-stats publisher is selected by the runtime binding.")
    path = Path(path_value)
    registry_path = Path(registry_value)
    value, error = _read_json(path)
    claim_limit = "This is an aoa-stats derived surface; source authority, freshness, and owner acceptance remain outside the dashboard."
    refs = [
        _ref("aoa-stats source coverage", str(path), claim_limit),
        _ref("aoa-stats live receipt registry", str(registry_path), "Registry compatibility is not proof that a publisher is fresh."),
    ]
    if error or value is None:
        return _error_source("aoa-stats-source-coverage", "aoa-stats", str(path), error or "unknown error")
    registry, registry_error = _read_json(registry_path)
    if registry_error or registry is None:
        return _error_source("aoa-stats-source-coverage", "aoa-stats", str(registry_path), registry_error or "unknown error")
    generated = value.get("generated_from") if isinstance(value.get("generated_from"), dict) else {}
    owner_counts = value.get("owner_repo_counts")
    if not isinstance(owner_counts, dict):
        owner_counts = value.get("owner_counts") if isinstance(value.get("owner_counts"), dict) else {}
    expected = value.get("expected_owner_repos") if isinstance(value.get("expected_owner_repos"), list) else []
    missing = value.get("missing_owner_repos") if isinstance(value.get("missing_owner_repos"), list) else []
    sources = registry.get("sources") if isinstance(registry.get("sources"), list) else []
    actor_registered = any(
        isinstance(item, dict)
        and (
            item.get("owner_repo") == "aoa-agents"
            or item.get("repo") == "aoa-agents"
            or "actor-responsibility" in str(item.get("path", ""))
            or "actor_responsibility" in str(item.get("relative_path", ""))
        )
        for item in sources
    )
    return {
        "id": "aoa-stats-source-coverage",
        "owner": "aoa-stats",
        "state": "unknown",
        "freshness": config.get("stats_observed_freshness_status", "unknown"),
        "observation": "Source coverage is readable, but the owner surface reports freshness as not_attested; recent generation is not promoted to current.",
        "metadata": {
            "schema_version": value.get("schema_version"),
            "total_receipts": generated.get("total_receipts", value.get("active_receipt_total")),
            "latest_observed_at": generated.get("latest_observed_at"),
            "owner_counts": owner_counts,
            "expected_owner_repos": expected,
            "missing_owner_repos": missing,
            "thin_signal_flags": value.get("thin_signal_flags", []),
            "event_kind_counts": value.get("event_kind_counts", {}),
            "actor_source_registered": actor_registered,
            "actor_publisher_state": actor_source.get("state"),
        },
        "evidence_refs": refs,
        "claim_limit": claim_limit,
    }


def observe_kag(config: dict[str, Any]) -> dict[str, Any]:
    claim_limit = "KAG is derived navigation evidence; this snapshot cannot establish current owner truth, proof, deployment, or acceptance."
    digest = config.get("kag_projection_digest")
    if not isinstance(digest, str) or not digest:
        return _missing_source("aoa-kag-projection", "aoa-kag", None, "No KAG projection binding is selected by the runtime binding.")
    return {
        "id": "aoa-kag-projection",
        "owner": "aoa-kag",
        "state": "stale",
        "freshness": "stale",
        "observation": "The configured KAG projection is a readable 2026-08-08 navigation snapshot; owner digests are not all current.",
        "metadata": {
            "projection_digest": digest,
            "updated_at": config.get("kag_projection_updated_at"),
            "retrieval_eval": "missing",
        },
        "evidence_refs": [
            _json_ref("KAG projection", f"aoa-kag://projections/{digest}", claim_limit),
            _ref("KAG owner checkout", "/srv/AbyssOS/aoa-kag", claim_limit),
        ],
        "claim_limit": claim_limit,
    }


def observe_unconnected_owner(owner: str, path: str, note: str, state: str = "deferred") -> dict[str, Any]:
    claim_limit = f"No owner-specific publisher is connected for {owner}; dashboard absence is not a domain zero."
    return {
        "id": f"{owner}-surface",
        "owner": owner,
        "state": state,
        "freshness": state,
        "observation": note,
        "metadata": {},
        "evidence_refs": [_ref(f"{owner} owner root", path, claim_limit)],
        "claim_limit": claim_limit,
    }


def _git_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path_exists": False, "state": "missing"}
    result: dict[str, Any] = {"path_exists": True, "state": "bound"}
    try:
        root = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if root.returncode != 0:
            result["vcs"] = "not_git"
            return result
        branch = subprocess.run(
            ["git", "-C", str(path), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        head = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        result.update(
            {
                "vcs": "git",
                "branch": branch.stdout.strip() or "detached",
                "head": head.stdout.strip() or None,
                "dirty": bool(status.stdout.strip()),
            }
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result.update({"vcs": "git", "state": "unknown", "error": str(exc)})
    return result


def observe_owner_surfaces(config: dict[str, Any]) -> list[dict[str, Any]]:
    surfaces: list[dict[str, Any]] = []
    for item in config.get("owner_surfaces", []):
        if not isinstance(item, dict) or not isinstance(item.get("source_path"), str) or not item.get("source_path"):
            continue
        source_path = Path(item["source_path"])
        source_snapshot = _git_snapshot(source_path)
        runtime_path = item.get("runtime_path")
        runtime_snapshot = _git_snapshot(Path(runtime_path)) if runtime_path else None
        surfaces.append(
            {
                "owner": item["owner"],
                "authority": item["authority"],
                "source_path": str(source_path),
                "runtime_path": runtime_path,
                "source_snapshot": source_snapshot,
                "runtime_snapshot": runtime_snapshot,
                "kag_snapshot_state": item.get("kag_snapshot_state"),
                "claim_limit": "Filesystem/VCS presence is an observation of a binding, not owner acceptance or runtime health.",
            }
        )
    return surfaces


def observe_all(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    goal_path = config.get("goal_anchor_path")
    goal_snapshot = (
        read_file_snapshot(
            Path(goal_path),
            expected_digest=config.get("goal_anchor_expected_sha256"),
            parser="json" if config.get("runtime_binding_state") == "bound" else "text",
            reject_duplicate_keys=config.get("runtime_binding_state") == "bound",
        )
        if isinstance(goal_path, str) and goal_path
        else None
    )
    goal = observe_goal(config, goal_snapshot)
    session = observe_session(config)
    correlation = observe_current_correlation(config, goal_anchor_snapshot=goal_snapshot)
    activity = observe_actor_activity(config, correlation)
    actor = observe_actor_receipts(config)
    stats = observe_stats(config, actor)
    sources = [
        goal,
        session,
        correlation,
        activity,
        stats,
        actor,
        observe_kag(config),
        observe_unconnected_owner(
            "aoa-evals",
            "/srv/AbyssOS/aoa-evals",
            "No independent proof/eval packet for this Goal is connected to the read model.",
            "missing",
        ),
        observe_unconnected_owner(
            "aoa-memo",
            "/srv/AbyssOS/aoa-memo",
            "Reviewed memory is available as an owner surface but no current memo is admitted as Goal evidence.",
            "deferred",
        ),
        observe_unconnected_owner(
            "abyss-stack",
            "/srv/AbyssOS/abyss-stack",
            "No runtime health publisher is connected in this first read-mostly slice.",
            "deferred",
        ),
    ]
    index = {item["id"]: item for item in sources}
    # Short aliases keep adapter call sites readable while the public source
    # ids remain the stable drill-down keys.
    index.update({"goal": goal, "session": session, "correlation": correlation, "activity": activity, "actor": actor, "stats": stats})
    return sources, index
