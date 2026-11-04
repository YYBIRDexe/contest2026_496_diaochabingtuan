"""WSGI HTTP API and same-origin static file server.

Only the standard library is used.  The API is deliberately explicit about
configuration failures: ``POST /api/chat`` returns 503 when no model is
configured and never fabricates an assistant reply.
"""

import hmac
import json
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from http import HTTPStatus
from pathlib import Path

from . import SERVICE_NAME, __version__
from .errors import CloudAgentError, ConfigurationError
from .util import isoformat, safe_join, utc_now

LOG = logging.getLogger("cloud_agent.http")

JSON_MAX_BYTES = 64 * 1024
STATIC_MAX_BYTES = 5 * 1024 * 1024
PROPOSAL_PATH_RE = re.compile(r"^/api/proposals/([A-Za-z0-9_\-]+)$")
DECISION_PATH_RE = re.compile(r"^/api/proposals/([A-Za-z0-9_\-]+)/decision$")
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")

MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


class FixedWindowLimiter(object):
    def __init__(self, limit=20, window_seconds=60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._buckets = {}

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0
            if count >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - window_start)))
                return False, retry_after
            self._buckets[key] = (window_start, count + 1)
            if len(self._buckets) > 4096:
                for bucket_key in list(self._buckets.keys()):
                    start, _ = self._buckets[bucket_key]
                    if now - start >= self.window_seconds:
                        self._buckets.pop(bucket_key, None)
            return True, 0


class VoiceInbox(object):
    """Latest wake-word transcript shared by the device bridge and the page.

    The bridge runs on the device and POSTs only to loopback; the page polls
    this small in-memory inbox.  A sequence number lets the page ignore the
    transcript that was already present when it loaded.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._seq = 0
        self._text = ""
        self._ts = 0.0

    def put(self, text):
        with self._lock:
            self._seq += 1
            self._text = text
            self._ts = time.time()
            return self._seq

    def latest(self):
        with self._lock:
            return {"seq": self._seq, "text": self._text, "ts": self._ts}


class Application(object):
    def __init__(self, config, registry, store, toolbox, agent, static_dir=None):
        self.config = config
        self.registry = registry
        self.store = store
        self.toolbox = toolbox
        self.agent = agent
        self.static_dir = Path(static_dir or config.static_dir or (config.root / "static"))
        self.limiter = FixedWindowLimiter(limit=20, window_seconds=60)
        self.voice_inbox = VoiceInbox()
        self.log = LOG

    def __call__(self, environ, start_response):
        started = time.monotonic()
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        path = environ.get("PATH_INFO") or "/"
        if not path.startswith("/"):
            path = "/" + path
        status_code = 500
        body = b""
        extra_headers = []
        try:
            if path == "/api" or path.startswith("/api/"):
                status_code, extra_headers, body = self._dispatch_api(environ, method, path)
            else:
                status_code, extra_headers, body = self._serve_static(environ, method, path)
        except CloudAgentError as exc:
            status_code = exc.http_status
            extra_headers = [("Content-Type", "application/json; charset=utf-8")]
            if status_code == 401:
                extra_headers.append(("WWW-Authenticate", 'Bearer realm="cloud-agent"'))
            if status_code == 405:
                allowed = (exc.details or {}).get("allowed") or []
                if allowed:
                    extra_headers.append(("Allow", ", ".join(allowed)))
            if status_code == 429:
                retry_after = (exc.details or {}).get("retry_after")
                if retry_after:
                    extra_headers.append(("Retry-After", str(retry_after)))
            body = self._encode_json(exc.to_dict())
        except Exception:
            self.log.exception("unhandled request failure: %s %s", method, path)
            status_code = 500
            extra_headers = [("Content-Type", "application/json; charset=utf-8")]
            body = self._encode_json(
                {
                    "ok": False,
                    "error": {
                        "code": "internal_error",
                        "message": "服务内部错误，请查看设备日志。",
                    },
                }
            )
        finally:
            self.log.info(
                "%s %s -> %s %.1fms", method, path, status_code, (time.monotonic() - started) * 1000
            )

        headers = self._base_headers(path, extra_headers)
        headers.append(("Content-Length", str(len(body))))
        if method == "HEAD":
            body = b""
        try:
            reason = HTTPStatus(status_code).phrase
        except ValueError:
            reason = "OK"
        start_response("%d %s" % (status_code, reason), headers)
        return [body]

    # ------------------------------------------------------------------ API
    def _dispatch_api(self, environ, method, path):
        if self.config.access_token and path != "/api/health":
            loopback_bridge = path == "/api/voice/transcript" and self._is_loopback(environ)
            if not loopback_bridge:
                self._require_token(environ)

        if path == "/api/health":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self._health())

        if path == "/api/voice/latest":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, dict({"ok": True}, **self.voice_inbox.latest()))

        if path == "/api/voice/transcript":
            self._require_method(method, ("POST",))
            if not self._is_loopback(environ):
                raise CloudAgentError(
                    "语音转写只接受设备本机桥接。",
                    code="forbidden",
                    http_status=403,
                )
            payload = self._read_json(environ)
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise CloudAgentError(
                    "text 必须是非空字符串。",
                    code="invalid_text",
                    http_status=400,
                )
            text = text.strip()
            if len(text) > 2000:
                raise CloudAgentError(
                    "text 最多 2000 字。",
                    code="text_too_long",
                    http_status=400,
                )
            seq = self.voice_inbox.put(text)
            return self._json(200, {"ok": True, "seq": seq})

        if path == "/api/tools":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self.toolbox.service_descriptor())

        if path == "/api/routes":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self.registry.public_routes())

        if path == "/api/fleet":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self.registry.fleet_snapshot())

        if path == "/api/capabilities":
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self.toolbox.call("get_capabilities", {}))

        if path == "/api/chat":
            self._require_method(method, ("POST",))
            return self._chat(environ)

        if path == "/api/missions/validate":
            self._require_method(method, ("POST",))
            payload = self._read_json(environ)
            result = self.toolbox.call("validate_mission", payload, source="api")
            return self._json(200 if result.get("ok") else 422, result)

        if path == "/api/proposals":
            if method in ("GET", "HEAD"):
                return self._list_proposals(environ)
            if method == "POST":
                payload = self._read_json(environ)
                result = self.toolbox.call("create_plan_proposal", payload, source="api")
                return self._json(201 if result.get("ok") else 422, result)
            self._require_method(method, ("GET", "HEAD", "POST"))

        match = PROPOSAL_PATH_RE.match(path)
        if match:
            self._require_method(method, ("GET", "HEAD"))
            return self._json(200, self.store.get(match.group(1)))

        match = DECISION_PATH_RE.match(path)
        if match:
            self._require_method(method, ("POST",))
            payload = self._read_json(environ)
            decision = payload.get("decision")
            actor = payload.get("actor")
            note = payload.get("note")
            if decision not in ("approve", "reject"):
                raise CloudAgentError(
                    "decision 必须是 approve 或 reject。",
                    code="invalid_decision",
                    http_status=400,
                )
            if actor is not None and (not isinstance(actor, str) or len(actor) > 80):
                raise CloudAgentError(
                    "actor 必须是不超过 80 字符的字符串。",
                    code="invalid_actor",
                    http_status=400,
                )
            if note is not None and (not isinstance(note, str) or len(note) > 500):
                raise CloudAgentError(
                    "note 必须是不超过 500 字符的字符串。",
                    code="invalid_note",
                    http_status=400,
                )
            return self._json(200, self.store.decide(match.group(1), decision, actor, note))

        raise CloudAgentError("接口不存在：%s" % path, code="not_found", http_status=404)

    def _chat(self, environ):
        # Validate the request body before reporting configuration state.  A
        # too-large or malformed request must be rejected as such even when the
        # model is not configured.
        payload = self._read_json(environ)
        if not self.config.configured:
            raise ConfigurationError(
                details={
                    "missing": self.config.missing_fields,
                    "config_errors": self.config.config_errors,
                }
            )
        remote = environ.get("REMOTE_ADDR") or "unknown"
        allowed, retry_after = self.limiter.allow("chat:" + remote)
        if not allowed:
            raise CloudAgentError(
                "聊天请求过于频繁，请稍后重试。",
                code="rate_limited",
                http_status=429,
                details={"retry_after": retry_after},
            )
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise CloudAgentError("message 必须是非空字符串。", code="invalid_message", http_status=400)
        conversation_id = payload.get("conversation_id")
        if conversation_id is not None:
            if not isinstance(conversation_id, str) or not CONVERSATION_ID_RE.match(conversation_id):
                raise CloudAgentError(
                    "conversation_id 格式不合法。",
                    code="invalid_conversation_id",
                    http_status=400,
                )
        result = self.agent.chat(message, conversation_id)
        return self._json(200, result)

    def _list_proposals(self, environ):
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING") or "", keep_blank_values=False)
        limit = 50
        if query.get("limit"):
            try:
                limit = int(query["limit"][0])
            except (TypeError, ValueError):
                raise CloudAgentError("limit 必须是整数。", code="invalid_limit", http_status=400)
        return self._json(200, self.store.list(limit))

    def _health(self):
        total = self.store.list(1).get("total", 0)
        return {
            "ok": True,
            "service": SERVICE_NAME,
            "version": __version__,
            "status": "ready" if self.config.configured else "unconfigured",
            "time": isoformat(utc_now()),
            "llm": self.config.public_status(),
            "execution": {
                "available": False,
                "executor": "none_v1",
                "reason": "首版没有运动执行器；计划确认不等于执行。",
            },
            "store": {
                "proposals": total,
                "persistent": bool(self.store.path),
                "load_warning": self.store.load_warning,
            },
            "data": {
                "routes_sha256": self.registry.routes_sha256,
                "fleet_sha256": self.registry.fleet_sha256,
                "routes_source": self.registry.routes_source,
                "fleet_source": self.registry.fleet_source,
            },
        }

    # --------------------------------------------------------------- helper
    def _require_method(self, method, allowed):
        if method not in allowed:
            raise CloudAgentError(
                "该接口不支持 %s。" % method,
                code="method_not_allowed",
                http_status=405,
                details={"allowed": list(allowed)},
            )

    @staticmethod
    def _is_loopback(environ):
        remote = (environ.get("REMOTE_ADDR") or "").strip()
        return remote in ("127.0.0.1", "::1") or remote.startswith("127.")

    def _require_token(self, environ):
        header = environ.get("HTTP_AUTHORIZATION") or ""
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        if not token:
            token = (environ.get("HTTP_X_CLOUD_AGENT_TOKEN") or "").strip()
        if not token or not hmac.compare_digest(token, self.config.access_token):
            raise CloudAgentError(
                "需要访问口令。请在页面“连接设置”中填入设备上配置的 CLOUD_AGENT_ACCESS_TOKEN。",
                code="unauthorized",
                http_status=401,
                details={"scheme": "Bearer"},
            )

    def _read_json(self, environ):
        content_type = (environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
        if content_type and content_type != "application/json":
            raise CloudAgentError(
                "请求体必须是 application/json。",
                code="unsupported_media_type",
                http_status=415,
            )
        length_header = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = int(length_header)
        except (TypeError, ValueError):
            raise CloudAgentError("Content-Length 不合法。", code="invalid_content_length", http_status=400)
        if length < 0:
            raise CloudAgentError("Content-Length 不合法。", code="invalid_content_length", http_status=400)
        if length > JSON_MAX_BYTES:
            raise CloudAgentError(
                "请求体过大，最多 64 KiB。",
                code="request_too_large",
                http_status=413,
            )
        if length == 0:
            return {}
        raw = environ["wsgi.input"].read(length)
        if len(raw) != length:
            raise CloudAgentError("请求体读取不完整。", code="incomplete_body", http_status=400)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise CloudAgentError("请求体不是合法 UTF-8 JSON。", code="invalid_json", http_status=400)
        if not isinstance(payload, dict):
            raise CloudAgentError("请求体必须是 JSON 对象。", code="invalid_json", http_status=400)
        return payload

    def _json(self, status, payload, extra_headers=None):
        headers = list(extra_headers or [])
        headers.append(("Content-Type", "application/json; charset=utf-8"))
        return status, headers, self._encode_json(payload)

    @staticmethod
    def _encode_json(payload):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _base_headers(self, path, extra_headers):
        # Only the isolated scene-v2 page may request the microphone. The rest of the
        # console keeps microphone=() so an accidental recorder cannot silently appear.
        mic_policy = "(self)" if path in ("/static/scene-v2/", "/static/scene-v2/index.html") else "()"
        headers = [
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
            ("Cross-Origin-Resource-Policy", "same-origin"),
            ("Permissions-Policy", "camera=(), microphone=%s, geolocation=()" % mic_policy),
            (
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "style-src 'self'; script-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'",
            ),
        ]
        if path == "/api" or path.startswith("/api/"):
            headers.append(("Cache-Control", "no-store"))
        elif path in ("/", "/index.html") or path.endswith(".html"):
            headers.append(("Cache-Control", "no-store"))
        else:
            headers.append(("Cache-Control", "public, max-age=300"))
        headers.extend(extra_headers or [])
        return headers

    # -------------------------------------------------------------- static
    def _serve_static(self, environ, method, path):
        if method not in ("GET", "HEAD"):
            raise CloudAgentError(
                "静态资源只支持 GET/HEAD。",
                code="method_not_allowed",
                http_status=405,
                details={"allowed": ["GET", "HEAD"]},
            )
        if "\x00" in path:
            raise CloudAgentError("路径不合法。", code="invalid_path", http_status=400)

        if path in ("/", "/index.html"):
            relative = "index.html"
        elif path.startswith("/static/"):
            relative = path[len("/static/") :]
        else:
            raise CloudAgentError("资源不存在。", code="not_found", http_status=404)

        target = safe_join(self.static_dir, relative)
        if target is not None and os.path.isdir(target):
            # Directory URLs such as /static/scene-v2/ serve their index.html.
            target = safe_join(self.static_dir, relative.rstrip("/") + "/index.html")
        if target is None or not os.path.isfile(target):
            raise CloudAgentError("资源不存在。", code="not_found", http_status=404)
        try:
            size = os.path.getsize(target)
            if size > STATIC_MAX_BYTES:
                raise CloudAgentError("资源过大。", code="static_too_large", http_status=413)
            with open(target, "rb") as handle:
                body = handle.read()
        except OSError:
            raise CloudAgentError("资源读取失败。", code="static_read_error", http_status=500)

        extension = os.path.splitext(target)[1].lower()
        content_type = MIME_OVERRIDES.get(extension)
        if not content_type:
            content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
        return 200, [("Content-Type", content_type)], body
