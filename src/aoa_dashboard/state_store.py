from __future__ import annotations

import json
import hashlib
import os
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECORD_FILES = ("annotations.jsonl", "action_intents.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_root(binding_path: str | os.PathLike[str] | None = None) -> Path:
    """Durable user/workspace state; an explicit legacy override stays exact."""
    configured = os.environ.get("AOA_DASHBOARD_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().absolute()
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    if not base.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    workspace = os.environ.get("AOA_DASHBOARD_WORKSPACE_ROOT")
    scope = Path(workspace).expanduser() if workspace else (
        Path(binding_path).absolute().parent if binding_path is not None else Path.cwd()
    )
    namespace = hashlib.sha256(os.fsencode(str(scope.resolve()))).hexdigest()[:24]
    return base / "aoa-dashboard" / f"user-{os.getuid()}" / "workspaces" / namespace


def _directory_fd(root: Path, *, create: bool, private: bool = True) -> int:
    """Walk with dirfds so a linked or concurrently substituted path is not followed."""
    fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        forbidden = 0o077 if private else 0o022
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & forbidden:
            raise PermissionError("dashboard state directory must be user-owned with safe permissions")
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _record_stream(root: Path, filename: str, *, append: bool = False, private: bool = True):
    directory = _directory_fd(root, create=append, private=private)
    try:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT if append else os.O_RDONLY
        fd = os.open(filename, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
                raise PermissionError("dashboard state file must be a user-owned unlinked regular file")
            stream = os.fdopen(fd, "a" if append else "r", encoding="utf-8", newline="")
        except BaseException:
            os.close(fd)
            raise
        with stream:
            yield stream
    finally:
        os.close(directory)


def _read_records(filename: str, binding_path: str | os.PathLike[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    try:
        with _record_stream(state_root(binding_path), filename) as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except FileNotFoundError:
        return "missing", []
    except (OSError, UnicodeError, ValueError):
        return "unavailable", []
    return "present", records


def _record_summary(filename: str, binding_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    availability, records = _read_records(filename, binding_path)
    if availability == "missing":
        return {"state": "missing", "availability": "missing", "count": None, "latest": []}
    if availability == "unavailable":
        return {"state": "unknown", "availability": "unavailable", "count": None, "latest": []}
    return {"state": "bound", "availability": "present", "count": len(records), "latest": records[-5:]}


def _append(filename: str, value: dict[str, Any], binding_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    with _record_stream(state_root(binding_path), filename, append=True) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return value


def annotation_summary(binding_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    return _record_summary("annotations.jsonl", binding_path)


def action_intent_summary(binding_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    return _record_summary("action_intents.jsonl", binding_path)


def create_annotation(author_ref: str, target_ref: str, body: str, *, binding_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
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
        binding_path,
    )


def create_action_intent(
    requested_by: str,
    target_ref: str,
    owner_route: str,
    summary: str,
    *,
    binding_path: str | os.PathLike[str] | None = None,
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
        binding_path,
    )


def migrate_legacy_state(source: Path, *, binding_path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Explicit copy into an empty destination. Never remove or overwrite records."""
    source = source.expanduser().absolute()
    payloads = {}
    for filename in RECORD_FILES:
        try:
            with _record_stream(source, filename, private=False) as stream:
                payloads[filename] = stream.read()
        except FileNotFoundError:
            continue
    root = state_root(binding_path)
    directory = _directory_fd(root, create=True)
    results = {}
    try:
        for filename, payload in payloads.items():
            try:
                with _record_stream(root, filename) as stream:
                    existing = stream.read()
            except FileNotFoundError:
                continue
            if existing != payload:
                raise FileExistsError(f"destination {filename} already has different records; explicit reconciliation required")
        for filename, payload in payloads.items():
            try:
                fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            except FileExistsError:
                with _record_stream(root, filename) as stream:
                    if stream.read() != payload:
                        raise FileExistsError(f"destination {filename} changed during migration")
                results[filename] = "already_present"
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            results[filename] = "copied_source_preserved"
        os.fsync(directory)
    finally:
        os.close(directory)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Explicitly copy legacy dashboard notes without deleting the source.")
    parser.add_argument("command", choices=["migrate"])
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--binding", type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate_legacy_state(args.source, binding_path=args.binding), sort_keys=True))
