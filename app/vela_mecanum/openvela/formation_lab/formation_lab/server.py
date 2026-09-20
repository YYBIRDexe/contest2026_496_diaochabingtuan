from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .llm_stub import create_chat_completion
from .simulator import FormationSimulator, LabError


LOG = logging.getLogger("formation-lab")


class LabHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], simulator: FormationSimulator, static_dir: Path):
        super().__init__(address, handler)
        self.simulator = simulator
        self.static_dir = static_dir


class Handler(BaseHTTPRequestHandler):
    server: LabHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        raw = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise LabError("invalid Content-Length") from exc
        if length <= 0 or length > 64 * 1024:
            raise LabError("request body must be 1..65536 bytes")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LabError("request body is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise LabError("JSON body must be an object")
        return value

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(self.server.static_dir / "index.html", "text/html; charset=utf-8")
        elif path == "/api/v1/health":
            self._send_json(200, {"ok": True, "service": "formation-lab", "version": "0.1.0"})
        elif path == "/api/v1/capabilities":
            self._send_json(200, {"ok": True, "capabilities": self.server.simulator.capabilities()})
        elif path == "/api/v1/state":
            self._send_json(200, {"ok": True, "experiment": self.server.simulator.snapshot()})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/v1/formation":
                response = self.server.simulator.handle_command(payload)
            elif path in ("/v1/chat/completions", "/chat/completions"):
                response = create_chat_completion(payload)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_json(200, response)
        except LabError as exc:
            self._send_json(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
        except Exception:
            LOG.exception("Unhandled request failure")
            self._send_json(500, {"ok": False, "error": {"code": "internal_error", "message": "internal service error"}})


def main() -> None:
    parser = argparse.ArgumentParser(description="Local openvela four-robot formation lab")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="var/experiments")
    parser.add_argument("--time-scale", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(__file__).resolve().parent.parent
    simulator = FormationSimulator((root / args.data_dir).resolve(), time_scale=args.time_scale)
    server = LabHTTPServer((args.host, args.port), Handler, simulator, root / "formation_lab" / "static")

    def stop_server(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    LOG.info("Formation Lab listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        simulator.close()
        server.server_close()


if __name__ == "__main__":
    main()
