"""Minimal, single-purpose updater sidecar.

Exposes ONE internal endpoint — POST /update (X-Internal-Key gated) — that
pulls the latest n8n image and recreates ONLY the n8n container via
docker compose. It has the Docker socket, so it is deliberately:
  * internal-only (never published / never behind nginx),
  * hardcoded to the n8n service (no arbitrary command surface),
  * key-gated with the framework's internal key.

So even if the internet-facing api were compromised, the worst it can
trigger here is "update n8n" — not arbitrary Docker access.
"""
import http.server
import json
import os
import secrets
import subprocess

KEY = os.environ.get("INTERNAL_KEY", "")
PROJECT = os.environ.get("COMPOSE_PROJECT", "oof")
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", "/project/docker-compose.yml"]
SERVICE = "n8n"  # hardcoded — the only thing this sidecar may touch


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd="/project", capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout + p.stderr)[-4000:]


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # simple liveness
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/update":
            return self._send(404, {"error": "not found"})
        # Constant-time: a plain != leaks how many leading bytes matched,
        # which is enough to walk the key out of a service that sits on
        # the Docker socket.
        if not secrets.compare_digest(self.headers.get("X-Internal-Key", ""), KEY):
            return self._send(401, {"error": "unauthorized"})
        # n8n is a thin build wrapper over n8nio/n8n:latest → rebuild with
        # --pull to fetch the newest upstream base (a plain `pull` on a build
        # service is a no-op).
        rc1, log1 = _run(COMPOSE + ["build", "--pull", SERVICE])
        # --force-recreate: a bare `up -d` won't swap a running container to a
        # freshly-built image. --no-deps: recreate ONLY n8n, never its
        # depends_on (postgres) — would otherwise bounce the shared DB.
        rc2, log2 = _run(COMPOSE + ["up", "-d", "--force-recreate", "--no-deps", SERVICE]) if rc1 == 0 else (1, "")
        ok = rc1 == 0 and rc2 == 0
        return self._send(200 if ok else 500,
                          {"ok": ok, "log": (log1 + "\n" + log2)[-3500:]})

    def log_message(self, *args) -> None:  # quiet
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", 9999), Handler).serve_forever()
