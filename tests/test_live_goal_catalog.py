from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.goal_catalog import observe_goal_catalog
from aoa_dashboard.master_context import project_master_context
from aoa_dashboard.live_goal_catalog import (
    federate_goal_catalog,
    observe_live_goal_catalog,
)
from aoa_dashboard.codex_goal import CodexGoalUnavailable


def binding(*, page_size: int = 2, max_pages: int = 4) -> dict:
    return {
        "owner": "codex-app-server",
        "authority": "source_owner",
        "access_scope": "owner_bounded",
        "claim_policy": "codex-app-server-live-goal-catalog",
        "claim_limit": "Read-only live Goal catalog observation.",
        "enabled": True,
        "access": "read_only",
        "methods": ["thread/list", "thread/goal/get"],
        "socket_path": "/run/user/test/app-server-control.sock",
        "page_size": page_size,
        "max_pages": max_pages,
        "timeout_seconds": 1.0,
        "archived": False,
        "client_version": "dashboard-live-goal-catalog-test",
    }


def goal(thread_id: str, status: str, objective: str = "Keep the Goal catalog calm") -> dict:
    return {
        "goal": {
            "threadId": thread_id,
            "objective": objective,
            "status": status,
            "tokenBudget": None,
            "tokensUsed": 0,
            "timeUsedSeconds": 0,
            "createdAt": 1_700_000_000,
            "updatedAt": 1_700_000_060,
        }
    }


def historical(
    *,
    state: str = "current",
    items: list[dict] | None = None,
    next_cursor: str | None = None,
) -> dict:
    values = items or []
    return {
        "schema_version": "aoa_dashboard_goal_catalog_projection_v1",
        "state": state,
        "currentness": state,
        "items": copy.deepcopy(values),
        "counts_by_group": {},
        "pagination": {
            "mode": "snapshot",
            "cursor": None,
            "next_cursor": next_cursor,
            "complete": next_cursor is None,
        },
        "source": {
            "owner": "aoa-session-memory",
            "ref": "aoa-session-memory:goal-lifecycles",
            "owner_schema_version": "aoa_session_memory_goal_catalog_v1",
            "currentness": state,
            "generation_id": "history-generation",
        },
        "evidence_refs": [
            {
                "owner": "aoa-session-memory",
                "ref": "aoa-session-memory:goal-lifecycles",
                "currentness": state,
            }
        ],
        "diagnostics": ["history_deferred"] if state == "deferred" else [],
        "claim_limit": "Owner-published historical Goal navigation.",
    }


def catalog_item(ref: str, *, lifecycle: str = "complete", title: str | None = "History item") -> dict:
    return {
        "ref": ref,
        "title": title,
        "title_state": "available" if title is not None else "withheld",
        "lifecycle_state": lifecycle,
        "group": {"complete": "completed", "active": "active", "paused": "paused", "blocked": "attention"}[lifecycle],
        "first_observed_at": "2026-08-22T00:00:00Z",
        "last_observed_at": "2026-08-22T01:00:00Z",
        "ambiguity": False,
    }


class FakeRpc:
    def __init__(self, pages: dict[str | None, dict], goals: dict[str, object]) -> None:
        self.pages = pages
        self.goals = goals
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> "FakeRpc":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def notify(self, method: str) -> None:
        self.calls.append((method, {}))

    def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, copy.deepcopy(params)))
        if method == "initialize":
            return {"userAgent": "test", "platformOs": "test", "platformFamily": "test", "codexHome": "not-used"}
        if method == "thread/list":
            return copy.deepcopy(self.pages[params.get("cursor")])
        if method == "thread/goal/get":
            value = self.goals[params["threadId"]]
            if isinstance(value, BaseException):
                raise value
            return copy.deepcopy(value)
        raise AssertionError(f"unexpected method {method}")


def factory_for(rpc: FakeRpc):
    def factory(path: Path, *, timeout: float) -> FakeRpc:
        assert path == Path("/run/user/test/app-server-control.sock")
        assert timeout == 1.0
        return rpc

    return factory


def read_live(rpc: FakeRpc, *, page_size: int = 2, max_pages: int = 4) -> dict:
    return observe_live_goal_catalog(
        {"live_goal_catalog_source": binding(page_size=page_size, max_pages=max_pages)},
        rpc_factory=factory_for(rpc),
    )


def test_multiple_live_goals_are_keyed_by_exact_thread_id_not_title() -> None:
    rpc = FakeRpc(
        {
            None: {
                "data": [{"id": "live-one"}, {"id": "live-two"}, {"id": "live-three"}, {"id": "thread-without-goal"}],
                "nextCursor": None,
                "backwardsCursor": "opaque-backwards",
            }
        },
        {
            "live-one": goal("live-one", "active"),
            "live-two": goal("live-two", "paused"),
            "live-three": goal("live-three", "blocked"),
            "thread-without-goal": {"goal": None},
        },
    )

    result = read_live(rpc, page_size=4)

    assert result["state"] == "current"
    assert [item["ref"] for item in result["items"]] == ["live-one", "live-two", "live-three"]
    assert [item["group"] for item in result["items"]] == ["active", "paused", "attention"]
    assert result["items"][0]["identity"]["basis"] == "exact_thread_list_id_and_goal_threadId"
    assert "objective" not in result["items"][0]
    assert "live_thread_without_goal" in result["diagnostics"]
    list_queries = [params for method, params in rpc.calls if method == "thread/list"]
    assert list_queries == [{"archived": False, "limit": 4}]
    assert all("threadId" not in params for method, params in rpc.calls if method == "thread/list")


def test_live_pagination_follows_opaque_cursor_and_defers_at_explicit_limit() -> None:
    pages = {
        None: {"data": [{"id": "page-one"}], "nextCursor": "opaque-two", "backwardsCursor": "back-one"},
        "opaque-two": {"data": [{"id": "page-two"}], "nextCursor": None, "backwardsCursor": "back-two"},
    }
    goals = {"page-one": goal("page-one", "active"), "page-two": goal("page-two", "paused")}

    complete_rpc = FakeRpc(pages, goals)
    complete = read_live(complete_rpc, page_size=1, max_pages=4)
    assert complete["state"] == "current"
    assert complete["pagination"]["complete"] is True
    assert complete["source"]["pages_read"] == 2
    assert [params.get("cursor") for method, params in complete_rpc.calls if method == "thread/list"] == [None, "opaque-two"]

    limited_rpc = FakeRpc(pages, goals)
    limited = read_live(limited_rpc, page_size=1, max_pages=1)
    assert limited["state"] == "deferred"
    assert limited["pagination"]["next_cursor"] == "opaque-two"
    assert limited["pagination"]["complete"] is False
    assert limited["diagnostics"] == ["live_page_limit_reached"]


def test_exact_overlap_deduplicates_without_dropping_both_owner_records() -> None:
    history = historical(items=[catalog_item("overlap", lifecycle="complete")])
    rpc = FakeRpc({None: {"data": [{"id": "overlap"}], "nextCursor": None}}, {"overlap": goal("overlap", "active")})

    result = federate_goal_catalog(history, read_live(rpc, page_size=1))

    assert [item["ref"] for item in result["items"]] == ["overlap"]
    item = result["items"][0]
    assert item["ambiguity"] is True
    assert item["lifecycle_state"] == "unknown"
    assert {record["owner"] for record in item["source_records"]} == {"aoa-session-memory", "codex-app-server"}
    assert {(observation["owner"], observation["lifecycle_state"]) for observation in item["observations"]} == {
        ("aoa-session-memory", "complete"),
        ("codex-app-server", "active"),
    }
    assert item["identity"]["basis"] == "exact_owner_ref_string_equality_only"
    assert len(result["sources"]) == 2


@pytest.mark.parametrize("history_state", ["stale", "deferred"])
def test_current_live_source_keeps_historical_degradation_and_adds_live_items(history_state: str) -> None:
    history = historical(state=history_state, items=[catalog_item("old-history")])
    rpc = FakeRpc({None: {"data": [{"id": "live-now"}], "nextCursor": None}}, {"live-now": goal("live-now", "active")})

    result = federate_goal_catalog(history, read_live(rpc))

    assert result["state"] == "current"
    assert [item["ref"] for item in result["items"]] == ["old-history", "live-now"]
    inputs = {source["key"]: source for source in result["sources"]}
    assert inputs["historical"]["state"] == history_state
    assert inputs["live"]["currentness"] == "current_at_read"


def test_live_unavailable_does_not_erase_valid_historical_catalog() -> None:
    history = historical(items=[catalog_item("history-only", lifecycle="active")])

    def unavailable(_path: Path, *, timeout: float) -> FakeRpc:
        raise CodexGoalUnavailable("owner_transport_unavailable")

    live = observe_live_goal_catalog({"live_goal_catalog_source": binding()}, rpc_factory=unavailable)
    result = federate_goal_catalog(history, live)

    assert live["state"] == "unknown"
    assert result["state"] == "current"
    assert [item["ref"] for item in result["items"]] == ["history-only"]
    inputs = {source["key"]: source for source in result["sources"]}
    assert inputs["live"]["state"] == "unknown"
    assert "live_owner_unavailable" in result["diagnostics"]


def test_malformed_live_page_is_invalid_but_historical_items_remain() -> None:
    history = historical(items=[catalog_item("history-safe")])
    rpc = FakeRpc({None: {"data": "not-a-page", "nextCursor": None}}, {})

    live = read_live(rpc)
    result = federate_goal_catalog(history, live)

    assert live["state"] == "invalid"
    assert result["state"] == "current"
    assert [item["ref"] for item in result["items"]] == ["history-safe"]
    assert "not-a-page" not in json.dumps(result)
    inputs = {source["key"]: source for source in result["sources"]}
    assert inputs["live"]["state"] == "invalid"


def test_malformed_goal_identity_is_invalid_without_leaking_owner_payload() -> None:
    rpc = FakeRpc(
        {None: {"data": [{"id": "listed-thread"}], "nextCursor": None}},
        {"listed-thread": goal("different-thread", "active")},
    )

    result = read_live(rpc)

    assert result["state"] == "invalid"
    assert result["items"] == []
    assert result["diagnostics"] == ["live_goal_item_invalid"]
    assert "different-thread" not in json.dumps(result)


def test_federated_refs_and_order_are_stable_for_selection() -> None:
    history = historical(items=[catalog_item("history-first", lifecycle="active")])
    pages = {None: {"data": [{"id": "live-second"}, {"id": "live-third"}], "nextCursor": None}}
    goals = {ref: goal(ref, "active") for ref in ("live-second", "live-third")}
    first = federate_goal_catalog(history, read_live(FakeRpc(pages, goals)))
    second = federate_goal_catalog(history, read_live(FakeRpc(pages, goals)))

    assert [item["ref"] for item in first["items"]] == [item["ref"] for item in second["items"]]
    assert [item["ref"] for item in first["items"]] == ["history-first", "live-second", "live-third"]


def test_master_context_retains_federated_catalog_owner_sources() -> None:
    history = historical(items=[catalog_item("history-context")])
    rpc = FakeRpc({None: {"data": [{"id": "live-context"}], "nextCursor": None}}, {"live-context": goal("live-context", "active")})
    catalog = federate_goal_catalog(history, read_live(rpc))

    context = project_master_context({}, {}, catalog, {})

    catalog_sources = context["goal_catalog"]["sources"]
    assert {source["owner"] for source in catalog_sources} == {"aoa-session-memory", "codex-app-server"}
    assert {source["owner"] for source in context["sources"] if source["ref"] in {"aoa-session-memory:goal-lifecycles", "codex-app-server:goal-catalog"}} == {
        "aoa-session-memory",
        "codex-app-server",
    }


def test_observe_goal_catalog_uses_live_binding_without_current_goal_or_history_path(monkeypatch: pytest.MonkeyPatch) -> None:
    live = {
        "schema_version": "aoa_dashboard_goal_catalog_projection_v1",
        "state": "current",
        "currentness": "current_at_read",
        "items": [],
        "counts_by_group": {},
        "pagination": {"mode": "opaque_cursor", "cursor": None, "next_cursor": None, "complete": True},
        "source": {"owner": "codex-app-server", "ref": "codex-app-server:goal-catalog", "currentness": "current_at_read"},
        "evidence_refs": [],
        "diagnostics": [],
        "claim_limit": "live",
    }
    monkeypatch.setattr("aoa_dashboard.live_goal_catalog.observe_live_goal_catalog", lambda _config: live)

    result = observe_goal_catalog({"live_goal_catalog_source": binding()})

    assert result["source"]["owner"] == "aoa-dashboard"
    assert result["sources"][0]["state"] == "missing"
    assert result["sources"][1]["currentness"] == "current_at_read"
