from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from aoa_dashboard import state_store


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("AOA_DASHBOARD_STATE_ROOT", raising=False)
    monkeypatch.delenv("AOA_DASHBOARD_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_durable_notes_are_user_and_workspace_scoped(isolated_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = isolated_state / "first" / "binding.json"
    second = isolated_state / "second" / "binding.json"
    record = state_store.create_annotation("operator:test", "goal:test", "Keep this note", binding_path=first)
    root = state_store.state_root(first)
    assert root != state_store.state_root(second)
    assert root.is_relative_to(isolated_state / "state")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "annotations.jsonl").stat().st_mode) == 0o600
    assert state_store.annotation_summary(first)["latest"] == [record]
    assert state_store.annotation_summary(second)["availability"] == "missing"
    with monkeypatch.context() as other:
        other.setattr(state_store.os, "getuid", lambda: os.geteuid() + 1)
        assert state_store.state_root(first) != root


def test_workspace_profile_is_stable_across_binding_files(isolated_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AOA_DASHBOARD_WORKSPACE_ROOT", str(isolated_state / "workspace"))
    assert state_store.state_root("/one/binding.json") == state_store.state_root("/two/binding.json")


@pytest.mark.parametrize("substitution", ["root_link", "parent_link", "file_link", "hardlink", "public_root", "fifo"])
def test_state_writes_reject_unsafe_path_substitution(isolated_state: Path, monkeypatch: pytest.MonkeyPatch, substitution: str) -> None:
    root = isolated_state / "notes"
    target = isolated_state / "unchanged"
    target.write_text("do not change\n")
    if substitution == "parent_link":
        actual = isolated_state / "actual"
        actual.mkdir(mode=0o700)
        root.symlink_to(actual, target_is_directory=True)
        root = root / "child"
    elif substitution == "root_link":
        root.symlink_to(isolated_state, target_is_directory=True)
    else:
        root.mkdir(mode=0o700)
        file = root / "annotations.jsonl"
        if substitution == "file_link":
            file.symlink_to(target)
        elif substitution == "hardlink":
            os.link(target, file)
        elif substitution == "public_root":
            root.chmod(0o777)
        elif substitution == "fifo":
            os.mkfifo(file)
    monkeypatch.setenv("AOA_DASHBOARD_STATE_ROOT", str(root))
    with pytest.raises(OSError):
        state_store.create_annotation("operator:test", "goal:test", "must fail")
    assert target.read_text() == "do not change\n"
    assert state_store.annotation_summary()["state"] == "unknown"


def test_explicit_migration_preserves_source_and_refuses_overwrite(isolated_state: Path) -> None:
    legacy = isolated_state / "legacy"
    legacy.mkdir(mode=0o755)
    source = legacy / "annotations.jsonl"
    text = '{"annotation_id":"old-note","body":"preserved"}\n'
    source.write_text(text)
    assert state_store.annotation_summary()["availability"] == "missing"
    assert state_store.migrate_legacy_state(legacy) == {"annotations.jsonl": "copied_source_preserved"}
    assert source.read_text() == text
    assert state_store.annotation_summary()["count"] == 1
    assert state_store.migrate_legacy_state(legacy) == {"annotations.jsonl": "already_present"}
    state_store.create_annotation("operator:test", "goal:test", "new durable note")
    with pytest.raises(FileExistsError):
        state_store.migrate_legacy_state(legacy)
    assert source.read_text() == text
    assert state_store.annotation_summary()["count"] == 2


def test_action_intent_stays_non_executing(isolated_state: Path) -> None:
    intent = state_store.create_action_intent("operator:test", "goal:test", "owner:test", "review")
    assert intent["effect"] == "none"
    assert intent["state"] == "deferred"
    assert state_store.action_intent_summary()["latest"] == [intent]
