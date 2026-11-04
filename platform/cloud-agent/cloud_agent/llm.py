"""Minimal OpenAI-compatible ``/chat/completions`` client.

Only ``urllib`` is used.  The client is deliberately strict: a missing key, a
non-JSON body or an upstream auth failure is reported as an error, never
silently replaced by a fabricated assistant answer.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .errors import ConfigurationError, LLMError
from .util import redact_secrets, truncate_text

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _extract_error_message(document, fallback):
    if isinstance(document, dict):
        error = document.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail")
            if message:
                return str(message)
        message = document.get("message")
        if message:
            return str(message)
    return fallback


def _content_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


class OpenAIClient(object):
    def __init__(self, config, transport=None):
        self.config = config
        self._opener = self._build_opener(config.llm_proxy)
        self._transport = transport or self._urllib_transport

    @staticmethod
    def _build_opener(proxy_setting):
        """Build a proxy policy that does not inherit a dead device proxy.

        The platform has historically exported http_proxy/https_proxy values
        pointing at an unreachable host.  The default is therefore direct;
        operators can set CLOUD_AGENT_LLM_PROXY=env to honor the process
        environment, or a concrete proxy URL.
        """
        setting = (proxy_setting or "").strip()
        lowered = setting.lower()
        if lowered in ("", "direct", "none", "off"):
            handler = urllib.request.ProxyHandler({})
        elif lowered == "env":
            handler = urllib.request.ProxyHandler()
        else:
            handler = urllib.request.ProxyHandler({"http": setting, "https": setting})
        return urllib.request.build_opener(handler)

    @property
    def endpoint(self):
        base = (self.config.base_url or "").strip().rstrip("/")
        if not base:
            return ""
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def complete(self, messages, tools):
        if not self.config.configured:
            raise ConfigurationError(
                details={"missing": self.config.missing_fields, "config_errors": self.config.config_errors}
            )
        url = self.endpoint
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        # DeepSeek's thinking mode can require reasoning_content to be echoed
        # back across tool-call rounds.  This service only forwards standard
        # assistant/tool messages, so explicitly disable thinking on DeepSeek's
        # official endpoint.  Other OpenAI-compatible providers receive no
        # extra field.
        if self._is_deepseek_endpoint(url):
            body["thinking"] = {"type": "disabled"}
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": "Bearer " + self.config.api_key,
            "User-Agent": "velaguard-cloud-agent/0.1",
        }

        try:
            status, response_headers, raw = self._transport(
                url, headers, encoded, self.config.timeout_seconds
            )
        except LLMError:
            raise
        except (socket.timeout, TimeoutError):
            raise LLMError(
                "模型请求超时（%.0f 秒）。" % self.config.timeout_seconds,
                code="llm_timeout",
                http_status=504,
            )
        except urllib.error.URLError as exc:
            raise LLMError(
                "无法连接模型服务：%s" % redact_secrets(getattr(exc, "reason", exc), self.config.api_key),
                code="llm_unreachable",
                http_status=502,
            )
        except OSError as exc:
            raise LLMError(
                "模型网络请求失败：%s" % redact_secrets(exc, self.config.api_key),
                code="llm_unreachable",
                http_status=502,
            )

        if len(raw) > MAX_RESPONSE_BYTES:
            raise LLMError("模型响应过大，已拒绝处理。", code="llm_response_too_large", http_status=502)

        text = raw.decode("utf-8", "replace")
        try:
            document = json.loads(text)
        except ValueError:
            raise LLMError(
                "模型返回了非 JSON 响应（HTTP %s）。" % status,
                code="llm_invalid_response",
                http_status=502,
                details={"upstream_status": status},
            )

        if status < 200 or status >= 300:
            upstream_message = redact_secrets(
                _extract_error_message(document, text[:300]), self.config.api_key
            )
            if status in (401, 403):
                code = "llm_auth_failed"
                message = "模型服务拒绝认证（HTTP %s）；请检查设备上的 API key 与 base_url。" % status
            elif status == 404:
                code = "llm_endpoint_not_found"
                message = "模型端点不存在（HTTP 404）；请检查 base_url 是否需要包含 /v1。"
            elif status == 429:
                code = "llm_rate_limited"
                message = "模型服务限流（HTTP 429），请稍后重试。"
            elif status >= 500:
                code = "llm_upstream_error"
                message = "模型服务返回 HTTP %s。" % status
            else:
                code = "llm_http_error"
                message = "模型服务返回 HTTP %s。" % status
            details = {"upstream_status": status}
            if upstream_message:
                details["upstream_message"] = truncate_text(upstream_message, 300)
            raise LLMError(
                message,
                code=code,
                http_status=429 if status == 429 else 502,
                details=details,
            )

        choices = document.get("choices") if isinstance(document, dict) else None
        if not isinstance(choices, list) or not choices:
            raise LLMError(
                "模型响应缺少 choices。",
                code="llm_invalid_response",
                http_status=502,
            )
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMError(
                "模型响应缺少 message 对象。",
                code="llm_invalid_response",
                http_status=502,
            )
        tool_calls = message.get("tool_calls")
        if tool_calls is not None and not isinstance(tool_calls, list):
            raise LLMError(
                "模型响应的 tool_calls 不是数组。",
                code="llm_invalid_response",
                http_status=502,
            )
        normalized = {
            "role": "assistant",
            "content": _content_text(message.get("content")),
        }
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        usage = document.get("usage") if isinstance(document.get("usage"), dict) else {}
        return {
            "message": normalized,
            "usage": usage,
            "model": document.get("model") or self.config.model,
            "finish_reason": choice.get("finish_reason"),
            "upstream_status": status,
        }

    @staticmethod
    def _is_deepseek_endpoint(url):
        try:
            hostname = (urllib.parse.urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        return hostname == "api.deepseek.com"

    def _urllib_transport(self, url, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                payload = exc.read(MAX_RESPONSE_BYTES + 1)
            except Exception:
                payload = b""
            return exc.code, dict(exc.headers or {}), payload
