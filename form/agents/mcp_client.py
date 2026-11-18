"""A small synchronous MCP client over stdio, for the API agents (form/agents/api.py).

An API agent has no CLI to launch Form Studio's MCP server for it, so it launches the same `form-mcp --no-bench`
process the CLI agents get, with the same environment (data folder, the conversation's ask_user folder), and calls
its tools. Everything a tool does therefore reaches the app exactly as it does for a CLI agent.

Messages are JSON-RPC 2.0, one per line (the MCP stdio transport).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

PROTOCOL = "2025-06-18"           # the server answers with the version it speaks; any it accepts is fine here


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, command: str, args: list, env: dict | None = None, cwd: str | None = None):
        self.proc = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, cwd=cwd, env=dict(os.environ, **(env or {})))
        self._next = 0
        self._wait: dict[int, dict | None] = {}
        self._cv = threading.Condition()
        self._wlock = threading.Lock()
        self.stderr: list[str] = []
        self.instructions = ""
        threading.Thread(target=self._read, daemon=True, name="form-mcp-client").start()
        threading.Thread(target=lambda: self.stderr.extend(self.proc.stderr), daemon=True).start()

    # -- transport -----------------------------------------------------------
    def _send(self, msg: dict) -> None:
        with self._wlock:
            try:
                self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise MCPError(f"Form Studio's tool server stopped ({e}).")

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue
            if "method" in m and "id" in m:              # the server asks the client something
                res = {"jsonrpc": "2.0", "id": m["id"]}
                if m["method"] == "ping":
                    res["result"] = {}
                else:
                    res["error"] = {"code": -32601, "message": "Not supported by this client"}
                try:
                    self._send(res)
                except MCPError:
                    pass
                continue
            if "id" in m:
                with self._cv:
                    if m["id"] in self._wait:
                        self._wait[m["id"]] = m
                        self._cv.notify_all()
        with self._cv:                                    # the process ended: wake everyone who waits
            self._cv.notify_all()

    def request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        with self._cv:
            self._next += 1
            rid = self._next
            self._wait[rid] = None
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        with self._cv:
            while self._wait.get(rid) is None:
                left = end - time.monotonic()
                if left <= 0:
                    self._wait.pop(rid, None)
                    raise MCPError(f"Form Studio's tool server did not answer {method} within {int(timeout)} s.")
                if self.proc.poll() is not None:
                    self._wait.pop(rid, None)
                    tail = "".join(self.stderr)[-400:].strip()
                    raise MCPError("Form Studio's tool server stopped." + (f" {tail}" if tail else ""))
                self._cv.wait(min(left, 0.5))
            m = self._wait.pop(rid)
        if m.get("error"):
            e = m["error"]
            raise MCPError(str(e.get("message", e)) if isinstance(e, dict) else str(e))
        return m.get("result") or {}

    # -- MCP -----------------------------------------------------------------
    def initialize(self, timeout: float = 60.0) -> dict:
        r = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                        "clientInfo": {"name": "form-studio-api-agent", "version": "1"}}, timeout)
        self.instructions = str(r.get("instructions") or "")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r

    def tools(self) -> list[dict]:
        out, cursor = [], None
        while True:
            r = self.request("tools/list", {"cursor": cursor} if cursor else {})
            out += r.get("tools") or []
            cursor = r.get("nextCursor")
            if not cursor:
                return out

    def call(self, name: str, arguments: dict, timeout: float = 1200.0) -> dict:
        """{"content": [...], "isError": bool}. A tool error is a result, not an exception."""
        try:
            return self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout)
        except MCPError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        for pipe in (self.proc.stdout, self.proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass
