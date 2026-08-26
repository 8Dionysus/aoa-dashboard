"""Resolve one explicit owner-qualified runtime Goal binding.

The reusable bootstrap describes how a binding is selected; it does not carry
an instance.  A selected binding is an owner-published, read-only JSON
contract passed to the process explicitly.  This module validates that
contract and projects only its allowlisted source bindings into the legacy
adapter configuration shape.
"""

from __future__ import annotations

import copy
import re
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in an incomplete install
    Draft202012Validator = None  # type: ignore[assignment,misc]

from .source_binding import (
    FileSnapshot,
    is_sha256,
    loads_json,
    read_file_snapshot,
    snapshot_ref,
)
from .goal_context import GRAPH_OWNER_COMMIT, THREAD_OWNER_COMMIT


RUNTIME_BINDING_SCHEMA = "aoa_dashboard_runtime_binding_v1"
RUNTIME_OBSERVATION_SCHEMA = "aoa_dashboard_runtime_binding_observation_v1"
PRESSURE_CONTEXT_SCHEMA = "aoa_dashboard_pressure_context_v1"
CURRENT_STATES = frozenset({"current", "current_at_read"})
QUALITY_STATES = frozenset({"current", "current_at_read", "stale", "deferred", "missing", "unknown", "invalid"})
OWNER_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
SAFE_ID_RE = re.compile(r"^[^\x00\n\r\t]{1,256}$")
CLAIM_POLICY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
BINDING_OWNERS = frozenset({"aoa-sdk", "master-thread"})
CLAIM_LIMIT = (
    "The runtime binding is an owner-qualified read contract consumed by the "
    "dashboard; it is not role, runtime, proof, acceptance, or action authority."
)
SELECTION_CLAIM_LIMIT = (
    "The selected Goal and thread are taken from the exact owner-qualified "
    "binding supplied for this projection read."
)
_CONTRACT_FILENAMES = {
    "runtime": "runtime_binding.schema.json",
    "goal_anchor": "goal_anchor.schema.json",
}


class RuntimeBindingError(ValueError):
    """Raised when a selected runtime binding cannot be admitted."""


def _contract_path(kind: str) -> Path:
    filename = _CONTRACT_FILENAMES[kind]
    candidates = (
        Path(__file__).resolve().parents[2] / "contracts" / filename,
        Path(sysconfig.get_path("data")) / "share" / "aoa-dashboard" / "contracts" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeBindingError(f"runtime_binding_{kind}_contract_missing")


@lru_cache(maxsize=None)
def _contract_validator(kind: str) -> Any:
    if Draft202012Validator is None:
        raise RuntimeBindingError("runtime_binding_contract_validator_unavailable")
    path = _contract_path(kind)
    try:
        schema = loads_json(path.read_text(encoding="utf-8"), reject_duplicate_keys=True)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except RuntimeBindingError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RuntimeBindingError(f"runtime_binding_{kind}_contract_unreadable:{exc}") from exc


def _schema_error_label(error: Any) -> str:
    path = ".".join(str(item) for item in error.path) or "root"
    if error.validator == "additionalProperties":
        params = getattr(error, "params", None)
        params = params if isinstance(params, dict) else {}
        unexpected = sorted(str(item) for item in params.get("additionalProperties", []))
        detail = ",".join(unexpected) or error.message
        return f"schema_unknown_field:{path}:{detail}"
    if error.validator == "required":
        return f"schema_missing_field:{path}:{error.validator_value}"
    if error.validator == "type":
        return f"schema_type_invalid:{path}:{error.validator_value}"
    return f"schema_invalid:{path}:{error.validator}:{error.message}"


def _validate_contract_payload(payload: Any, *, kind: str, label: str) -> None:
    validator = _contract_validator(kind)
    errors = sorted(validator.iter_errors(payload), key=lambda item: (str(list(item.path)), item.message))
    if errors:
        diagnostics = [_schema_error_label(error) for error in errors[:8]]
        raise RuntimeBindingError(f"{label}_{';'.join(diagnostics)}")


def _snapshot_failure(prefix: str, snapshot: FileSnapshot) -> RuntimeBindingError:
    if snapshot.currentness == "missing":
        return RuntimeBindingError(f"{prefix}_missing")
    if snapshot.currentness == "stale":
        return RuntimeBindingError(f"{prefix}_stale")
    if snapshot.parse_error:
        if snapshot.parse_error == "duplicate JSON object name":
            return RuntimeBindingError(f"{prefix}_duplicate_json_object_name")
        return RuntimeBindingError(f"{prefix}_parse_invalid:{snapshot.parse_error}")
    return RuntimeBindingError(f"{prefix}_invalid")


def validate_goal_anchor_payload(payload: Any, selected: dict[str, str]) -> dict[str, str]:
    """Validate one structured Goal Anchor against the selected Goal identity."""

    _validate_contract_payload(payload, kind="goal_anchor", label="goal_anchor")
    if payload.get("goal_id") != selected["goal_id"]:
        raise RuntimeBindingError("runtime_binding_goal_anchor_goal_mismatch")
    if payload.get("master_thread_id") != selected["master_thread_id"]:
        raise RuntimeBindingError("runtime_binding_goal_anchor_thread_mismatch")
    selected_title = selected.get("title")
    if selected_title is not None and payload.get("title") != selected_title:
        raise RuntimeBindingError("runtime_binding_goal_anchor_title_mismatch")
    return {
        "owner": payload["owner"],
        "authority": payload["authority"],
        "access_scope": payload["access_scope"],
        "claim_policy": payload["claim_policy"],
        "goal_id": payload["goal_id"],
        "master_thread_id": payload["master_thread_id"],
        "title": payload["title"],
        "source_ref": payload["source_ref"],
    }


def _text(value: Any, field: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or not SAFE_ID_RE.fullmatch(value):
        raise RuntimeBindingError(f"runtime_binding_{field}_invalid")
    return value.strip()


def _optional_text(value: Any, field: str, *, maximum: int = 256) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum)


def _owner_descriptor(value: Any, field: str, *, expected_owner: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeBindingError(f"runtime_binding_{field}_missing")
    owner = _text(value.get("owner"), f"{field}_owner", maximum=128)
    if not OWNER_LABEL_RE.fullmatch(owner) or owner == "aoa-dashboard":
        raise RuntimeBindingError(f"runtime_binding_{field}_owner_invalid")
    if expected_owner is not None and owner != expected_owner:
        raise RuntimeBindingError(f"runtime_binding_{field}_owner_mismatch")
    authority = _text(value.get("authority"), f"{field}_authority", maximum=96)
    if authority not in {"source_owner", "master_decision"}:
        raise RuntimeBindingError(f"runtime_binding_{field}_authority_invalid")
    access_scope = _text(value.get("access_scope"), f"{field}_access_scope", maximum=96)
    if access_scope != "owner_bounded":
        raise RuntimeBindingError(f"runtime_binding_{field}_access_scope_invalid")
    claim_policy = _text(value.get("claim_policy"), f"{field}_claim_policy", maximum=96)
    if not CLAIM_POLICY_RE.fullmatch(claim_policy):
        raise RuntimeBindingError(f"runtime_binding_{field}_claim_policy_invalid")
    claim_limit = _text(value.get("claim_limit"), f"{field}_claim_limit", maximum=640)
    currentness = value.get("currentness")
    if currentness is not None and currentness not in CURRENT_STATES:
        raise RuntimeBindingError(f"runtime_binding_{field}_currentness_not_current")
    return {
        "owner": owner,
        "authority": authority,
        "access_scope": access_scope,
        "claim_policy": claim_policy,
        "claim_limit": claim_limit,
        **({"currentness": currentness} if currentness is not None else {}),
    }


def _path(value: Any, field: str) -> str:
    result = _text(value, field, maximum=4096)
    if not Path(result).is_absolute():
        raise RuntimeBindingError(f"runtime_binding_{field}_must_be_absolute")
    return str(Path(result).resolve(strict=False))


def _sha(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not is_sha256(value):
        raise RuntimeBindingError(f"runtime_binding_{field}_invalid")
    return value


def _relative_path(value: Any, field: str) -> str:
    result = _text(value, field, maximum=512)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeBindingError(f"runtime_binding_{field}_invalid")
    return result


def _glob(value: Any, field: str) -> str:
    result = _text(value, field, maximum=256)
    if result in {".", ".."} or "/" in result or "\\" in result:
        raise RuntimeBindingError(f"runtime_binding_{field}_invalid")
    return result


def _text_list(value: Any, field: str, *, maximum: int = 64) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise RuntimeBindingError(f"runtime_binding_{field}_invalid")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{field}_{index}", maximum=256))
    return result


def _publication_binding(raw: dict[str, Any], field: str) -> dict[str, Any]:
    """Validate an explicit path/command publication without executing it."""

    nested = raw.get("publication")
    publication = nested if isinstance(nested, dict) else raw
    capability = publication.get("capability")
    command_present = publication.get("command") is not None
    if not isinstance(capability, str) or not capability.strip() or len(capability) > 256:
        if command_present or isinstance(nested, dict):
            raise RuntimeBindingError(f"runtime_binding_{field}_capability_missing")
        capability = "legacy-path-publication"
    capability = _text(capability, f"{field}_capability", maximum=256)
    transport = publication.get("transport")
    if transport is None:
        transport = "command" if command_present else "path"
    if transport not in {"path", "command"}:
        raise RuntimeBindingError(f"runtime_binding_{field}_transport_invalid")
    normalized: dict[str, Any] = {"capability": capability, "transport": transport}
    expected_digest = publication.get("expected_sha256", raw.get("expected_sha256"))
    if expected_digest is not None:
        normalized["expected_sha256"] = _sha(expected_digest, f"{field}_expected_sha256")
    timeout = publication.get("timeout_seconds", raw.get("timeout_seconds", 5))
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        raise RuntimeBindingError(f"runtime_binding_{field}_timeout_invalid")
    normalized["timeout_seconds"] = timeout
    if transport == "path":
        path = publication.get("path", raw.get("path"))
        normalized["path"] = _path(path, f"{field}_path")
    else:
        normalized["command"] = _text_list(publication.get("command"), f"{field}_command", maximum=64)
        cursor_arg = publication.get("cursor_arg", raw.get("cursor_arg"))
        if cursor_arg is not None:
            cursor_arg = _text(cursor_arg, f"{field}_cursor_arg", maximum=128)
            if any(character.isspace() for character in cursor_arg):
                raise RuntimeBindingError(f"runtime_binding_{field}_cursor_arg_invalid")
            normalized["cursor_arg"] = cursor_arg
        max_pages = publication.get("max_pages", raw.get("max_pages", 64 if cursor_arg is not None else 1))
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 128:
            raise RuntimeBindingError(f"runtime_binding_{field}_max_pages_invalid")
        normalized["max_pages"] = max_pages
    goal_ref_arg = publication.get("goal_ref_arg", raw.get("goal_ref_arg"))
    if goal_ref_arg is not None:
        normalized["goal_ref_arg"] = _text(goal_ref_arg, f"{field}_goal_ref_arg", maximum=128)
    return normalized


def _source_ref(
    snapshot: FileSnapshot,
    *,
    label: str,
    owner: str,
    authority: str,
    claim_policy: str,
    claim_limit: str,
    extra_degradation: list[str] | None = None,
) -> dict[str, Any]:
    return snapshot_ref(
        snapshot,
        label=label,
        kind="runtime_binding",
        owner=owner,
        access_scope="owner_bounded",
        authority=authority,
        claim_policy=claim_policy,
        claim_limit=claim_limit,
        extra_degradation=extra_degradation,
    )


def _empty_observation(
    state: str,
    reason: str,
    *,
    path: Path | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_OBSERVATION_SCHEMA,
        "state": state,
        "currentness": state,
        "binding_id": None,
        "selected_goal": None,
        "source": evidence,
        "diagnostics": [reason],
        "claim_limit": CLAIM_LIMIT,
        **({"binding_path": str(path)} if path is not None else {}),
    }


def _binding_observation(
    *,
    state: str,
    binding_id: str | None,
    selected_goal: dict[str, str] | None,
    evidence: dict[str, Any] | None,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_OBSERVATION_SCHEMA,
        "state": state,
        "currentness": "current_at_read" if state == "bound" else state,
        "binding_id": binding_id,
        "selected_goal": selected_goal,
        "source": evidence,
        "diagnostics": sorted(set(diagnostics or [])),
        "claim_limit": CLAIM_LIMIT,
    }


def _validate_selected_goal(payload: dict[str, Any]) -> dict[str, str]:
    selected = payload.get("selected_goal")
    if not isinstance(selected, dict):
        raise RuntimeBindingError("runtime_binding_selected_goal_missing")
    goal_id = _text(selected.get("goal_id"), "selected_goal_id", maximum=256)
    thread_id = _text(selected.get("master_thread_id"), "selected_master_thread_id", maximum=256)
    result = {"goal_id": goal_id, "master_thread_id": thread_id}
    title = selected.get("title")
    if title is not None:
        result["title"] = _text(title, "selected_title", maximum=256)
    return result


def _validate_currentness(payload: dict[str, Any]) -> str:
    currentness = payload.get("currentness")
    state = payload.get("state", currentness)
    if currentness not in QUALITY_STATES or state not in QUALITY_STATES or state != currentness:
        raise RuntimeBindingError("runtime_binding_currentness_invalid")
    return currentness


def _validate_source_map(payload: dict[str, Any], selected: dict[str, str]) -> dict[str, Any]:
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        raise RuntimeBindingError("runtime_binding_sources_missing")

    goal_anchor = _owner_descriptor(sources.get("goal_anchor"), "goal_anchor", expected_owner="goal-anchor")
    goal_anchor["path"] = _path(sources["goal_anchor"].get("path"), "goal_anchor_path")
    expected_anchor_digest = _sha(
        sources["goal_anchor"].get("expected_sha256"),
        "goal_anchor_expected_sha256",
    )
    if expected_anchor_digest is None:
        raise RuntimeBindingError("runtime_binding_goal_anchor_expected_sha256_missing")
    anchor_snapshot = read_file_snapshot(
        goal_anchor["path"],
        expected_digest=expected_anchor_digest,
        parser="json",
        reject_duplicate_keys=True,
    )
    if anchor_snapshot.currentness != "current_at_read" or not isinstance(anchor_snapshot.parsed, dict):
        raise _snapshot_failure("runtime_binding_goal_anchor", anchor_snapshot)
    goal_anchor["expected_sha256"] = expected_anchor_digest
    goal_anchor["semantic_identity"] = validate_goal_anchor_payload(anchor_snapshot.parsed, selected)

    codex_goal = _owner_descriptor(sources.get("codex_goal"), "codex_goal", expected_owner="codex-app-server")
    if sources["codex_goal"].get("enabled") is not True or sources["codex_goal"].get("method") != "thread/goal/get":
        raise RuntimeBindingError("runtime_binding_codex_goal_contract_invalid")
    codex_goal.update({"enabled": True, "kind": "codex_app_server_thread_goal", "method": "thread/goal/get", "access": "read_only"})
    if sources["codex_goal"].get("socket_path") is not None:
        codex_goal["socket_path"] = _path(sources["codex_goal"].get("socket_path"), "codex_goal_socket_path")

    codex_thread = _owner_descriptor(sources.get("codex_thread"), "codex_thread", expected_owner="codex-app-server")
    raw_thread = sources["codex_thread"]
    if raw_thread.get("enabled") is not True:
        raise RuntimeBindingError("runtime_binding_codex_thread_disabled")
    methods = raw_thread.get("methods")
    relation_queries = raw_thread.get("relation_queries")
    if methods != ["thread/read", "thread/list"] or relation_queries != ["parentThreadId", "ancestorThreadId"]:
        raise RuntimeBindingError("runtime_binding_codex_thread_contract_invalid")
    codex_thread.update(
        {
            "enabled": True,
            "kind": "codex_app_server_thread_context",
            "methods": list(methods),
            "relation_queries": list(relation_queries),
            "requires_experimental_api": raw_thread.get("requires_experimental_api") is True,
        }
    )
    if raw_thread.get("socket_path") is not None:
        codex_thread["socket_path"] = _path(raw_thread.get("socket_path"), "codex_thread_socket_path")

    topology = _owner_descriptor(sources.get("topology"), "topology", expected_owner="master-thread")
    raw_topology = sources["topology"]
    topology.update(
        {
            "enabled": True,
            "relative_path": _relative_path(raw_topology.get("relative_path"), "topology_relative_path"),
            "expected_schema_version": _text(raw_topology.get("expected_schema_version"), "topology_schema", maximum=128),
        }
    )

    catalog = _owner_descriptor(sources.get("catalog"), "catalog", expected_owner="aoa-session-memory")
    raw_catalog = sources["catalog"]
    if raw_catalog.get("expected_schema_version") != "aoa_session_memory_goal_catalog_v1":
        raise RuntimeBindingError("runtime_binding_catalog_schema_invalid")
    catalog_publication = _publication_binding(raw_catalog, "catalog")
    catalog.update(
        {
            "schema_version": "aoa_dashboard_goal_catalog_binding_v1",
            "expected_schema_version": "aoa_session_memory_goal_catalog_v1",
            "publication": catalog_publication,
        }
    )
    if catalog_publication["transport"] == "path":
        catalog["path"] = catalog_publication["path"]

    live_goal_catalog = None
    raw_live_goal_catalog = sources.get("live_goal_catalog")
    if raw_live_goal_catalog is not None:
        live_goal_catalog = _owner_descriptor(
            raw_live_goal_catalog,
            "live_goal_catalog",
            expected_owner="codex-app-server",
        )
        if raw_live_goal_catalog.get("enabled") is not True:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_disabled")
        if raw_live_goal_catalog.get("access") != "read_only":
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_access_invalid")
        if raw_live_goal_catalog.get("methods") != ["thread/list", "thread/goal/get"]:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_contract_invalid")
        live_socket = _path(raw_live_goal_catalog.get("socket_path"), "live_goal_catalog_socket_path")
        page_size = raw_live_goal_catalog.get("page_size")
        max_pages = raw_live_goal_catalog.get("max_pages")
        timeout_seconds = raw_live_goal_catalog.get("timeout_seconds")
        client_version = raw_live_goal_catalog.get("client_version")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 512:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_page_size_invalid")
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 128:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_max_pages_invalid")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_timeout_invalid")
        if raw_live_goal_catalog.get("archived") is not False:
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_archived_invalid")
        if not isinstance(client_version, str) or not client_version.strip() or len(client_version) > 64 or any(
            character.isspace() for character in client_version
        ):
            raise RuntimeBindingError("runtime_binding_live_goal_catalog_client_version_invalid")
        live_goal_catalog.update(
            {
                "schema_version": "aoa_dashboard_live_goal_catalog_binding_v1",
                "kind": "codex_app_server_goal_catalog",
                "enabled": True,
                "access": "read_only",
                "methods": ["thread/list", "thread/goal/get"],
                "socket_path": live_socket,
                "page_size": page_size,
                "max_pages": max_pages,
                "timeout_seconds": timeout_seconds,
                "archived": False,
                "client_version": client_version.strip(),
            }
        )
        for key in ("sort_key", "sort_direction"):
            value = raw_live_goal_catalog.get(key)
            if value is not None:
                live_goal_catalog[key] = _text(value, f"live_goal_catalog_{key}", maximum=64)

    goal_projection = None
    raw_goal_projection = sources.get("goal_projection")
    if raw_goal_projection is not None:
        goal_projection = _owner_descriptor(raw_goal_projection, "goal_projection", expected_owner="aoa-session-memory")
        if raw_goal_projection.get("expected_schema_version") != "aoa_session_memory_goal_projection_v1":
            raise RuntimeBindingError("runtime_binding_goal_projection_schema_invalid")
        projection_publication = _publication_binding(raw_goal_projection, "goal_projection")
        goal_projection.update(
            {
                "schema_version": "aoa_dashboard_goal_projection_binding_v1",
                "expected_schema_version": "aoa_session_memory_goal_projection_v1",
                "publication": projection_publication,
            }
        )
        if projection_publication["transport"] == "path":
            goal_projection["path"] = projection_publication["path"]

    correlation = _owner_descriptor(sources.get("correlation"), "correlation", expected_owner="master-thread")
    raw_correlation = sources["correlation"]
    task_local_dir = _path(raw_correlation.get("task_local_dir"), "correlation_task_local_dir")
    master_filter_path = _path(raw_correlation.get("master_filter_path"), "correlation_master_filter_path")
    if raw_correlation.get("master_thread_id") not in {None, selected["master_thread_id"]}:
        raise RuntimeBindingError("runtime_binding_correlation_thread_mismatch")
    currentness_binding = raw_correlation.get("master_filter_currentness")
    if not isinstance(currentness_binding, dict):
        raise RuntimeBindingError("runtime_binding_currentness_binding_missing")
    currentness_copy = copy.deepcopy(currentness_binding)
    if currentness_copy.get("owner") != "master-thread" or currentness_copy.get("authority") != "master_decision" or currentness_copy.get("access_scope") != "owner_bounded":
        raise RuntimeBindingError("runtime_binding_currentness_owner_invalid")
    if _path(currentness_copy.get("filter_ref"), "currentness_filter_ref") != master_filter_path:
        raise RuntimeBindingError("runtime_binding_currentness_filter_mismatch")
    currentness_copy["filter_ref"] = master_filter_path
    currentness_copy["current_head_ref"] = _path(currentness_copy.get("current_head_ref"), "currentness_current_head_ref")
    currentness_copy["history_ref"] = _path(currentness_copy.get("history_ref"), "currentness_history_ref")
    correlation.update(
        {
            "master_thread_id": selected["master_thread_id"],
            "task_local_dir": task_local_dir,
            "master_filter_path": master_filter_path,
            "master_filter_currentness": currentness_copy,
            "handoff_glob": _glob(raw_correlation.get("handoff_glob"), "correlation_handoff_glob"),
            "wake_glob": _glob(raw_correlation.get("wake_glob"), "correlation_wake_glob"),
            "ignored_handoff_names": _text_list(raw_correlation.get("ignored_handoff_names", []), "correlation_ignored_handoff_names"),
            "ignored_wake_names": _text_list(raw_correlation.get("ignored_wake_names", []), "correlation_ignored_wake_names"),
        }
    )
    holder = raw_correlation.get("current_holder")
    if holder is not None:
        correlation["current_holder"] = _text(holder, "correlation_current_holder", maximum=256)
    legacy_snapshot = raw_correlation.get("legacy_snapshot_binding")
    if legacy_snapshot is not None:
        if not isinstance(legacy_snapshot, dict):
            raise RuntimeBindingError("runtime_binding_legacy_snapshot_invalid")
        correlation["legacy_snapshot_binding"] = copy.deepcopy(legacy_snapshot)

    pressure = _owner_descriptor(sources.get("pressure"), "pressure")
    raw_pressure = sources["pressure"]
    if raw_pressure.get("expected_schema_version") != PRESSURE_CONTEXT_SCHEMA:
        raise RuntimeBindingError("runtime_binding_pressure_schema_invalid")
    pressure.update(
        {
            "path": _path(raw_pressure.get("path"), "pressure_path"),
            "expected_schema_version": PRESSURE_CONTEXT_SCHEMA,
        }
    )

    result: dict[str, Any] = {
        "goal_anchor": goal_anchor,
        "codex_goal": codex_goal,
        "codex_thread": codex_thread,
        "topology": topology,
        "catalog": catalog,
        "live_goal_catalog": live_goal_catalog,
        "goal_projection": goal_projection,
        "correlation": correlation,
        "pressure": pressure,
    }

    optional = {
        "historical": ("historical", "aoa-session-memory"),
        "actor": ("actor", "aoa-agents"),
        "stats": ("stats", "aoa-stats"),
    }
    for key, (_name, expected_owner) in optional.items():
        raw = sources.get(key)
        if raw is None:
            continue
        descriptor = _owner_descriptor(raw, key, expected_owner=expected_owner)
        if key == "historical":
            if raw.get("scope") != "historical_bootstrap" or raw.get("current_holder") is not False:
                raise RuntimeBindingError("runtime_binding_historical_scope_invalid")
            descriptor.update(
                {
                    "binding_id": _text(raw.get("binding_id"), "historical_binding_id", maximum=256),
                    "session_manifest_path": _path(raw.get("session_manifest_path"), "historical_manifest_path"),
                    "session_archive_raw_path": _path(raw.get("session_archive_raw_path"), "historical_archive_path"),
                    "actor_manifest_path": _path(raw.get("actor_manifest_path"), "historical_actor_manifest_path") if raw.get("actor_manifest_path") is not None else None,
                    "configured_scope": "historical_bootstrap",
                    "current_holder": False,
                }
            )
        elif key == "actor":
            descriptor["path"] = _path(raw.get("path"), "actor_receipt_path")
        else:
            descriptor["path"] = _path(raw.get("path"), "stats_surface_path")
            descriptor["registry_path"] = _path(raw.get("registry_path"), "stats_registry_path")
            descriptor["freshness_status"] = _text(raw.get("freshness_status", "unknown"), "stats_freshness_status", maximum=64)
        result[key] = descriptor

    goal_context_sources: dict[str, Any] = {}
    raw_goal_context = sources.get("goal_context")
    if raw_goal_context is not None:
        if not isinstance(raw_goal_context, dict):
            raise RuntimeBindingError("runtime_binding_goal_context_sources_invalid")
        context_bindings = {
            "thread_board": ("aoa-session-memory", "aoa_session_memory_goal_thread_board_v1", THREAD_OWNER_COMMIT),
            "participant_graph": ("aoa-agents", "aoa_agents_goal_participant_graph_v1", GRAPH_OWNER_COMMIT),
        }
        for key, (expected_owner, expected_schema, expected_commit) in context_bindings.items():
            raw_context = raw_goal_context.get(key)
            if raw_context is None:
                continue
            if not isinstance(raw_context, dict):
                raise RuntimeBindingError(f"runtime_binding_{key}_source_invalid")
            descriptor = _owner_descriptor(raw_context, key, expected_owner=expected_owner)
            if raw_context.get("expected_schema_version") != expected_schema:
                raise RuntimeBindingError(f"runtime_binding_{key}_schema_invalid")
            configured_commit = raw_context.get("owner_commit")
            if configured_commit is not None and configured_commit != expected_commit:
                raise RuntimeBindingError(f"runtime_binding_{key}_owner_commit_invalid")
            publication = _publication_binding(raw_context, key)
            descriptor.update(
                {
                    "schema_version": "aoa_dashboard_goal_context_source_binding_v1",
                    "expected_schema_version": expected_schema,
                    "owner_commit": expected_commit,
                    "publication": publication,
                }
            )
            if publication["transport"] == "path":
                descriptor["path"] = publication["path"]
            goal_scope = raw_context.get("goal_scope")
            if goal_scope is not None:
                if not isinstance(goal_scope, dict):
                    raise RuntimeBindingError(f"runtime_binding_{key}_goal_scope_invalid")
                descriptor["goal_scope"] = copy.deepcopy(goal_scope)
            goal_context_sources[key] = descriptor
    result["goal_context_sources"] = goal_context_sources

    owner_surfaces = payload.get("owner_surfaces", [])
    if not isinstance(owner_surfaces, list) or len(owner_surfaces) > 32:
        raise RuntimeBindingError("runtime_binding_owner_surfaces_invalid")
    normalized_surfaces: list[dict[str, Any]] = []
    for index, item in enumerate(owner_surfaces):
        if not isinstance(item, dict):
            raise RuntimeBindingError(f"runtime_binding_owner_surface_{index}_invalid")
        descriptor = _owner_descriptor(item, f"owner_surface_{index}")
        descriptor["owner"] = _text(item.get("owner"), f"owner_surface_{index}_owner", maximum=128)
        descriptor["source_path"] = _path(item.get("source_path"), f"owner_surface_{index}_source_path")
        runtime_path = item.get("runtime_path")
        descriptor["runtime_path"] = _path(runtime_path, f"owner_surface_{index}_runtime_path") if runtime_path is not None else None
        descriptor["kag_snapshot_state"] = item.get("kag_snapshot_state")
        normalized_surfaces.append(descriptor)
    result["owner_surfaces"] = normalized_surfaces
    return result


def _read_pressure_context(
    descriptor: dict[str, Any],
    *,
    selected_goal_id: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any], list[str]]:
    path = Path(descriptor["path"])
    snapshot = read_file_snapshot(path, parser="json")
    evidence = snapshot_ref(
        snapshot,
        label="Owner pressure context",
        kind="pressure_context",
        owner=descriptor["owner"],
        access_scope="owner_bounded",
        authority=descriptor["authority"],
        claim_policy=descriptor["claim_policy"],
        claim_limit=descriptor["claim_limit"],
    )
    if snapshot.currentness != "current_at_read" or not isinstance(snapshot.parsed, dict):
        return [], snapshot.currentness, evidence, ["pressure_context_not_current"]
    payload = snapshot.parsed
    try:
        if payload.get("schema_version") != PRESSURE_CONTEXT_SCHEMA:
            raise RuntimeBindingError("pressure_context_schema_unsupported")
        if payload.get("owner") != descriptor["owner"] or payload.get("authority") != descriptor["authority"]:
            raise RuntimeBindingError("pressure_context_owner_invalid")
        if payload.get("state") != "current_at_read" or payload.get("currentness") != "current_at_read":
            raise RuntimeBindingError("pressure_context_currentness_invalid")
        if payload.get("goal_id") != selected_goal_id:
            raise RuntimeBindingError("pressure_context_goal_mismatch")
        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeBindingError("pressure_context_items_invalid")
        return copy.deepcopy(items), "current_at_read", evidence, []
    except RuntimeBindingError as exc:
        return [], "invalid", evidence, [str(exc)]


def _flatten_binding(
    base: dict[str, Any],
    payload: dict[str, Any],
    *,
    binding_path: Path,
    binding_snapshot: FileSnapshot,
    selected: dict[str, str],
    descriptors: dict[str, Any],
) -> dict[str, Any]:
    config = copy.deepcopy(base)
    config.update(
        {
            "schema_version": "aoa_dashboard_resolved_config_v1",
            "profile": "owner-qualified-runtime",
            "runtime_binding_state": "bound",
            "runtime_binding_observation": _binding_observation(
                state="bound",
                binding_id=_text(payload.get("binding_id"), "binding_id", maximum=256),
                selected_goal={"goal_id": selected["goal_id"], "master_thread_id": selected["master_thread_id"]},
                evidence=_source_ref(
                    binding_snapshot,
                    label="Selected runtime Goal binding",
                    owner=_text(payload.get("owner"), "owner", maximum=128),
                    authority=_text(payload.get("authority"), "authority", maximum=96),
                    claim_policy=_text(payload.get("claim_policy"), "claim_policy", maximum=96),
                    claim_limit=_text(payload.get("claim_limit"), "claim_limit", maximum=640),
                ),
            ),
            "runtime_binding_source_path": str(binding_path),
            "goal_id": selected["goal_id"],
            "title": selected.get("title"),
            "goal_anchor_path": descriptors["goal_anchor"]["path"],
            "goal_anchor_expected_sha256": descriptors["goal_anchor"]["expected_sha256"],
            "goal_anchor_identity": descriptors["goal_anchor"]["semantic_identity"],
            "owner_goal_source": descriptors["codex_goal"],
            "owner_thread_source": descriptors["codex_thread"],
            "goal_topology_source": descriptors["topology"],
            "goal_catalog_source": descriptors["catalog"],
            "live_goal_catalog_source": descriptors.get("live_goal_catalog"),
            "goal_projection_source": descriptors.get("goal_projection"),
            "current_correlation": descriptors["correlation"],
            "owner_surfaces": descriptors["owner_surfaces"],
            "pressure_inbox": [],
            "pressure_source": descriptors["pressure"],
            "goal_context_sources": descriptors.get("goal_context_sources", {}),
        }
    )
    historical = descriptors.get("historical")
    if historical is not None:
        config["historical_bootstrap"] = historical
    else:
        config["historical_bootstrap"] = {}
    actor = descriptors.get("actor")
    stats = descriptors.get("stats")
    config["actor_receipt_path"] = actor.get("path") if actor else None
    config["stats_surface_path"] = stats.get("path") if stats else None
    config["stats_registry_path"] = stats.get("registry_path") if stats else None
    config["stats_observed_freshness_status"] = stats.get("freshness_status", "unknown") if stats else "unknown"

    pressure_items, pressure_state, pressure_evidence, pressure_diagnostics = _read_pressure_context(
        descriptors["pressure"], selected_goal_id=selected["goal_id"]
    )
    config["pressure_inbox"] = pressure_items
    config["pressure_source_state"] = pressure_state
    config["pressure_source_evidence"] = pressure_evidence
    config["pressure_source_diagnostics"] = pressure_diagnostics
    return config


def resolve_runtime_binding(base: dict[str, Any], path: str | Path | None) -> dict[str, Any]:
    """Return a resolved config or a reusable fail-closed config."""

    config = copy.deepcopy(base)
    if path is None:
        config["runtime_binding_state"] = "missing"
        config["runtime_binding_observation"] = _empty_observation("missing", "runtime_binding_not_selected")
        return config
    binding_path = Path(path).resolve(strict=False)
    snapshot = read_file_snapshot(binding_path, parser="json", reject_duplicate_keys=True)
    evidence = snapshot_ref(
        snapshot,
        label="Selected runtime Goal binding",
        kind="runtime_binding",
        owner="aoa-sdk",
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="runtime_binding",
        claim_limit=CLAIM_LIMIT,
    )
    if snapshot.currentness == "missing":
        config["runtime_binding_state"] = "missing"
        config["runtime_binding_observation"] = _empty_observation("missing", "runtime_binding_source_missing", path=binding_path, evidence=evidence)
        return config
    if snapshot.currentness != "current_at_read" or not isinstance(snapshot.parsed, dict):
        state = snapshot.currentness if snapshot.currentness in QUALITY_STATES else "invalid"
        diagnostic = (
            _snapshot_failure("runtime_binding", snapshot)
            if state == "invalid"
            else RuntimeBindingError("runtime_binding_source_not_current")
        )
        config["runtime_binding_state"] = state
        config["runtime_binding_observation"] = _empty_observation(
            state,
            str(diagnostic),
            path=binding_path,
            evidence=evidence,
        )
        return config
    payload = snapshot.parsed
    try:
        _validate_contract_payload(payload, kind="runtime", label="runtime_binding")
        if payload.get("schema_version") != RUNTIME_BINDING_SCHEMA:
            raise RuntimeBindingError("runtime_binding_schema_unsupported")
        currentness = _validate_currentness(payload)
        if currentness not in CURRENT_STATES:
            config["runtime_binding_state"] = currentness
            config["runtime_binding_observation"] = _empty_observation(currentness, "runtime_binding_not_current", path=binding_path, evidence=evidence)
            return config
        owner = _text(payload.get("owner"), "owner", maximum=128)
        if owner not in BINDING_OWNERS:
            raise RuntimeBindingError("runtime_binding_owner_invalid")
        authority = _text(payload.get("authority"), "authority", maximum=96)
        if authority not in {"source_owner", "master_decision"}:
            raise RuntimeBindingError("runtime_binding_authority_invalid")
        access_scope = _text(payload.get("access_scope"), "access_scope", maximum=96)
        if access_scope != "owner_bounded":
            raise RuntimeBindingError("runtime_binding_access_scope_invalid")
        claim_policy = _text(payload.get("claim_policy"), "claim_policy", maximum=96)
        if not CLAIM_POLICY_RE.fullmatch(claim_policy):
            raise RuntimeBindingError("runtime_binding_claim_policy_invalid")
        _text(payload.get("claim_limit"), "claim_limit", maximum=640)
        selected = _validate_selected_goal(payload)
        descriptors = _validate_source_map(payload, selected)
        resolved = _flatten_binding(
            base,
            payload,
            binding_path=binding_path,
            binding_snapshot=snapshot,
            selected=selected,
            descriptors=descriptors,
        )
        return resolved
    except (RuntimeBindingError, TypeError, KeyError) as exc:
        diagnostic = str(exc)
        state = "invalid"
        if diagnostic == "runtime_binding_goal_anchor_missing":
            state = "missing"
        elif diagnostic == "runtime_binding_goal_anchor_stale":
            state = "stale"
        config["runtime_binding_state"] = state
        config["runtime_binding_observation"] = _empty_observation(state, diagnostic, path=binding_path, evidence=evidence)
        return config


def mark_historical_demo(config: dict[str, Any], *, path: str | Path) -> dict[str, Any]:
    """Mark an explicitly selected legacy/demo instance without making it default."""

    result = copy.deepcopy(config)
    historical = result.get("historical_bootstrap")
    if not isinstance(historical, dict):
        historical = {}
    correlation = result.get("current_correlation")
    if not isinstance(correlation, dict):
        correlation = {}
    result["runtime_binding_state"] = "historical_demo_opt_in"
    result["runtime_binding_observation"] = {
        "schema_version": RUNTIME_OBSERVATION_SCHEMA,
        "state": "deferred",
        "currentness": "deferred",
        "binding_id": historical.get("binding_id"),
        "selected_goal": {
            "goal_id": result.get("goal_id"),
            "master_thread_id": correlation.get("master_thread_id"),
        },
        "source": {
            "owner": ".aoa-session-memory",
            "ref": str(Path(path).resolve(strict=False)),
            "currentness": "deferred",
            "snapshot_role": "historical_bootstrap_only",
            "claim_limit": "Explicit demo data is historical context only and is never the default current binding.",
        },
        "diagnostics": ["historical_bootstrap_only"],
        "claim_limit": "Explicit demo data is historical context only and is never the default current binding.",
    }
    return result
