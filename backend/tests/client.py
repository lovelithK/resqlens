"""Tiny HTTP client + live-server helper for integration tests (stdlib only)."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LiveServer:
    def __init__(self, app):
        self.port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


class Client:
    def __init__(self, base: str, token: str | None = None):
        self.base = base
        self.token = token

    def request(self, method: str, path: str, body=None, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read()
                status = resp.status
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            content, status, ctype = e.read(), e.code, e.headers.get("Content-Type", "")
        if raw or "json" not in ctype:
            return status, content
        return status, (json.loads(content) if content else None)

    def get(self, path, **kw): return self.request("GET", path, **kw)
    def post(self, path, body=None, **kw): return self.request("POST", path, body if body is not None else {}, **kw)
    def put(self, path, body=None, **kw): return self.request("PUT", path, body, **kw)
    def delete(self, path, **kw): return self.request("DELETE", path, **kw)
