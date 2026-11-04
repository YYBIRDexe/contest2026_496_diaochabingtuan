"""Error types shared by the cloud agent modules.

Every error carries a stable machine-readable ``code`` and an HTTP status so
the transport layer can map failures without string matching.
"""


class CloudAgentError(Exception):
    code = "internal_error"
    http_status = 500

    def __init__(self, message, code=None, http_status=None, details=None):
        super(CloudAgentError, self).__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details or {}

    def to_dict(self):
        payload = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class ConfigurationError(CloudAgentError):
    code = "llm_not_configured"
    http_status = 503

    def __init__(self, message=None, details=None):
        if message is None:
            message = (
                "模型尚未配置，聊天接口不会返回模拟结果。请在设备上配置 "
                "CLOUD_AGENT_LLM_BASE_URL、CLOUD_AGENT_LLM_MODEL 和 "
                "CLOUD_AGENT_LLM_API_KEY（或 CLOUD_AGENT_LLM_API_KEY_FILE）后重启服务。"
            )
        super(ConfigurationError, self).__init__(
            message, code="llm_not_configured", http_status=503, details=details
        )


class AgentLoopError(CloudAgentError):
    code = "tool_loop_limit"
    http_status = 502

    def __init__(self, message, details=None):
        super(AgentLoopError, self).__init__(
            message, code="tool_loop_limit", http_status=502, details=details
        )


class RegistryError(CloudAgentError):
    code = "registry_invalid"
    http_status = 500

    def __init__(self, message, details=None):
        super(RegistryError, self).__init__(
            message, code="registry_invalid", http_status=500, details=details
        )


class StoreError(CloudAgentError):
    def __init__(self, message, code, http_status=409, details=None):
        super(StoreError, self).__init__(
            message, code=code, http_status=http_status, details=details
        )


class LLMError(CloudAgentError):
    def __init__(self, message, code="llm_upstream_error", http_status=502, details=None):
        super(LLMError, self).__init__(
            message, code=code, http_status=http_status, details=details
        )
