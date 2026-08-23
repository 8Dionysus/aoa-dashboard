"""Read-only projection of the Goal owned by the local Codex app-server.

The dashboard consumes the stable ``thread/goal/get`` method through the
managed app-server control socket.  It never reads Codex's SQLite store and it
never calls a Goal mutation method.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import stat
import struct
from pathlib import Path
from typing import Any, Callable


DASHBOARD_SCHEMA = "aoa_dashboard_codex_goal_projection_v1"
MAX_FRAME_BYTES = 1024 * 1024
MAX_HANDSHAKE_BYTES = 16 * 1024
WEBSOCKET_ACCEPT_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
GOAL_STATUSES = frozenset(
    {"active", "paused", "complete", "blocked", "usage_limited", "budgetLimited"}
)


class CodexGoalUnavailable(RuntimeError):
    """The owner Goal could not be read without weakening its contract."""


class UnixWebSocketRpc:
    """Bounded stdlib JSON-RPC client for Codex's local WebSocket socket."""

    def __init__(self, path: Path, *, timeout: float = 1.5) -> None:
        self.path = path
        self.timeout = timeout
        self.connection: socket.socket | None = None
        self.buffer = b""
        self.counter = 0

    def __enter__(self) -> "UnixWebSocketRpc":
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(str(self.path))
            self.connection = connection
            self._handshake()
        except (OSError, TimeoutError, CodexGoalUnavailable) as exc:
            connection.close()
            self.connection = None
            raise CodexGoalUnavailable("owner_transport_unavailable") from exc
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self.connection is None:
            return
        try:
            self._send_frame(0x8, b"")
        except (OSError, CodexGoalUnavailable):
            pass
        finally:
            self.connection.close()
            self.connection = None

    def _socket(self) -> socket.socket:
        if self.connection is None:
            raise CodexGoalUnavailable("owner_transport_disconnected")
        return self.connection

    def _read_exact(self, size: int) -> bytes:
        if size < 0 or size > MAX_FRAME_BYTES:
            raise CodexGoalUnavailable("owner_frame_invalid")
        chunks: list[bytes] = []
        if self.buffer:
            buffered = self.buffer[:size]
            self.buffer = self.buffer[len(buffered) :]
            chunks.append(buffered)
            size -= len(buffered)
        while size:
            chunk = self._socket().recv(size)
            if not chunk:
                raise CodexGoalUnavailable("owner_transport_closed")
            chunks.append(chunk)
            size -= len(chunk)
        return b"".join(chunks)

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self.buffer:
            chunk = self._socket().recv(4096)
            if not chunk:
                raise CodexGoalUnavailable("owner_handshake_closed")
            self.buffer += chunk
            if len(self.buffer) > MAX_HANDSHAKE_BYTES:
                raise CodexGoalUnavailable("owner_handshake_invalid")
        position = self.buffer.index(marker) + len(marker)
        result, self.buffer = self.buffer[:position], self.buffer[position:]
        return result

    def _handshake(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET /rpc HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._socket().sendall(request)
        raw = self._read_until(b"\r\n\r\n")
        lines = raw.decode("latin1").split("\r\n")
        if not lines or not lines[0].startswith("HTTP/1.1 101"):
            raise CodexGoalUnavailable("owner_handshake_rejected")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_ACCEPT_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise CodexGoalUnavailable("owner_handshake_digest_mismatch")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if len(payload) > MAX_FRAME_BYTES:
            raise CodexGoalUnavailable("owner_payload_too_large")
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        length = len(masked)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack(">H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack(">Q", length)
        self._socket().sendall(header + mask + masked)

    def _send_json(self, value: dict[str, object]) -> None:
        self._send_frame(0x1, json.dumps(value, separators=(",", ":")).encode())

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        if length > MAX_FRAME_BYTES:
            raise CodexGoalUnavailable("owner_frame_too_large")
        return final, opcode, self._read_exact(length)

    def _receive(self, request_id: int) -> dict[str, Any]:
        fragments: list[bytes] = []
        while True:
            final, opcode, payload = self._recv_frame()
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise CodexGoalUnavailable("owner_transport_closed")
            if opcode == 0x1:
                fragments = [payload]
            elif opcode == 0x0 and fragments:
                fragments.append(payload)
            else:
                continue
            if not final:
                continue
            try:
                value = json.loads(b"".join(fragments).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CodexGoalUnavailable("owner_response_invalid") from exc
            fragments = []
            if not isinstance(value, dict):
                raise CodexGoalUnavailable("owner_response_invalid")
            if isinstance(value.get("method"), str) and "id" in value:
                self._send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": value["id"],
                        "error": {"code": -32601, "message": "read-only client"},
                    }
                )
                continue
            if value.get("id") == request_id:
                return value

    def notify(self, method: str) -> None:
        self._send_json({"jsonrpc": "2.0", "method": method})

    def call(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        self.counter += 1
        request_id = self.counter
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        response = self._receive(request_id)
        if "error" in response or not isinstance(response.get("result"), dict):
            raise CodexGoalUnavailable(f"owner_method_failed:{method}")
        return response["result"]


def _empty(state: str, reason: str, *, thread_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "thread_id": thread_id,
        "goal": None,
        "source": None,
        "evidence_refs": [],
        "diagnostics": [reason],
        "claim_limit": "Read-only observation of Codex Goal state for one exact thread.",
    }


def discover_control_socket(config: dict[str, Any]) -> Path:
    binding = config.get("owner_goal_source")
    explicit = binding.get("socket_path") if isinstance(binding, dict) else None
    candidates: list[Path] = []
    for value in (explicit, os.environ.get("AOA_DASHBOARD_CODEX_SOCKET")):
        if isinstance(value, str) and value:
            candidates.append(Path(value))
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "app-server-control" / "app-server-control.sock")
    candidates.append(Path.home() / ".codex" / "app-server-control" / "app-server-control.sock")
    for candidate in candidates:
        try:
            metadata = candidate.lstat()
        except OSError:
            continue
        if candidate.is_absolute() and not candidate.is_symlink() and stat.S_ISSOCK(metadata.st_mode):
            return candidate
    raise CodexGoalUnavailable("owner_socket_missing")


def _human_title(objective: str) -> str:
    normalized = " ".join(objective.split())
    head = normalized.split(":", 1)[0].strip()
    if 12 <= len(head) <= 112:
        return head
    if len(normalized) <= 112:
        return normalized
    shortened = normalized[:112].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{shortened}…"


def _validate_goal(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    goal = result.get("goal")
    if not isinstance(goal, dict) or goal.get("threadId") != thread_id:
        raise CodexGoalUnavailable("owner_goal_identity_mismatch")
    objective = goal.get("objective")
    status_value = goal.get("status")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 20_000:
        raise CodexGoalUnavailable("owner_goal_objective_invalid")
    if status_value not in GOAL_STATUSES:
        raise CodexGoalUnavailable("owner_goal_status_invalid")
    for field in ("tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt"):
        value = goal.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CodexGoalUnavailable(f"owner_goal_{field}_invalid")
    token_budget = goal.get("tokenBudget")
    if token_budget is not None and (
        not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget <= 0
    ):
        raise CodexGoalUnavailable("owner_goal_tokenBudget_invalid")
    return {
        "thread_id": thread_id,
        "title": _human_title(objective),
        "objective": " ".join(objective.split()),
        "status": status_value,
        "token_budget": token_budget,
        "tokens_used": goal["tokensUsed"],
        "time_used_seconds": goal["timeUsedSeconds"],
        "created_at": goal["createdAt"],
        "updated_at": goal["updatedAt"],
    }


def observe_codex_goal(
    config: dict[str, Any],
    *,
    rpc_factory: Callable[[Path], Any] = UnixWebSocketRpc,
) -> dict[str, Any]:
    binding = config.get("owner_goal_source")
    if not isinstance(binding, dict) or binding.get("enabled") is not True:
        return _empty("missing", "owner_binding_disabled")
    correlation = config.get("current_correlation")
    thread_id = correlation.get("master_thread_id") if isinstance(correlation, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        return _empty("missing", "owner_thread_missing")
    try:
        endpoint = discover_control_socket(config)
        with rpc_factory(endpoint) as rpc:
            rpc.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "aoa_dashboard",
                        "title": "AoA Dashboard read-only Goal projection",
                        "version": "1",
                    },
                    "capabilities": {},
                },
            )
            rpc.notify("initialized")
            goal = _validate_goal(
                rpc.call("thread/goal/get", {"threadId": thread_id}), thread_id
            )
    except (OSError, TimeoutError, CodexGoalUnavailable) as exc:
        reason = str(exc) if str(exc).startswith("owner_") else "owner_transport_unavailable"
        return _empty("unknown", reason, thread_id=thread_id)
    source_ref = f"codex-app-server:thread/goal/get:{thread_id}"
    evidence = {
        "label": "Codex Goal",
        "kind": "owner_api_observation",
        "ref": source_ref,
        "owner": "codex-app-server",
        "method": "thread/goal/get",
        "currentness": "current_at_read",
        "claim_limit": "Exact Goal state returned for this thread at projection read time.",
    }
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": "bound",
        "currentness": "current_at_read",
        "thread_id": thread_id,
        "goal": goal,
        "source": {
            "owner": "codex-app-server",
            "ref": source_ref,
            "method": "thread/goal/get",
            "transport": "websocket_unix",
            "currentness": "current_at_read",
        },
        "evidence_refs": [evidence],
        "diagnostics": [],
        "claim_limit": "Read-only observation of Codex Goal state for one exact thread.",
    }
