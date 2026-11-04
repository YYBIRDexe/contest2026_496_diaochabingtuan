"""Configuration loading.

Secrets are read from the process environment or from a protected file *on the
platform*.  They are never copied into the workspace by the deployment script,
never logged, and never returned by an HTTP endpoint.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .util import parse_float, parse_int, redact_url

ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path):
    """Parse a simple ``KEY=VALUE`` file.  Returns (values, errors)."""
    values = {}
    errors = []
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        return values, ["无法读取环境文件 %s: %s" % (path, exc.strerror or exc)]
    for lineno, line in enumerate(raw.splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].lstrip()
        if "=" not in text:
            errors.append("环境文件第 %d 行缺少 '='；该行被忽略" % lineno)
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not ENV_KEY_RE.match(key):
            errors.append("环境文件第 %d 行变量名不合法；该行被忽略" % lineno)
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values, errors


@dataclass
class Config:
    root: Path
    host: str = "127.0.0.1"
    port: int = 8130
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    api_key_source: str = "none"
    llm_proxy: str = "direct"
    timeout_seconds: float = 45.0
    max_tokens: int = 900
    temperature: float = 0.1
    max_tool_iterations: int = 6
    access_token: str = field(default="", repr=False)
    env_file: str = ""
    static_dir: Path = None
    data_dir: Path = None
    state_dir: Path = None
    config_errors: list = field(default_factory=list)
    config_warnings: list = field(default_factory=list)

    @property
    def configured(self):
        return bool(self.base_url and self.model and self.api_key) and not self.config_errors

    @property
    def missing_fields(self):
        missing = []
        if not self.base_url:
            missing.append("CLOUD_AGENT_LLM_BASE_URL")
        if not self.model:
            missing.append("CLOUD_AGENT_LLM_MODEL")
        if not self.api_key:
            missing.append("CLOUD_AGENT_LLM_API_KEY")
        return missing

    def public_status(self):
        """A safe projection that can be returned to a browser or log."""
        return {
            "configured": self.configured,
            "api_style": "openai_chat_completions",
            "base_url": redact_url(self.base_url),
            "model": self.model,
            "api_key_source": self.api_key_source,
            "proxy_mode": (
                "direct"
                if (self.llm_proxy or "").strip().lower() in ("", "direct", "none", "off")
                else ("env" if (self.llm_proxy or "").strip().lower() == "env" else "custom")
            ),
            "missing": self.missing_fields,
            "config_errors": list(self.config_errors),
            "config_warnings": list(self.config_warnings),
            "env_file": self.env_file,
            "access_token_required": bool(self.access_token),
        }

    @classmethod
    def load(cls, root=None, environ=None, allow_default_env_file=True):
        root_path = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        env = dict(os.environ if environ is None else environ)
        config = cls(root=root_path)
        config.static_dir = root_path / "static"
        config.data_dir = root_path / "data"
        config.state_dir = Path(env.get("CLOUD_AGENT_STATE_DIR") or (root_path / "var"))

        explicit_env_file = env.get("CLOUD_AGENT_ENV_FILE", "").strip()
        env_file = ""
        if explicit_env_file:
            env_file = explicit_env_file
            if not Path(env_file).is_file():
                config.config_errors.append(
                    "CLOUD_AGENT_ENV_FILE 指向的文件不存在或不可读；为避免误用其它凭据，服务不会进入已配置状态。"
                )
        elif allow_default_env_file:
            candidates = [
                root_path / "config" / "cloud-agent.env",
                root_path / ".env",
                Path.home() / ".config" / "velaguard-cloud-agent" / "cloud-agent.env",
            ]
            for candidate in candidates:
                if candidate.is_file():
                    env_file = str(candidate)
                    break

        if env_file:
            file_values, errors = parse_env_file(env_file)
            config.env_file = env_file
            config.config_errors.extend(errors)
            for key, value in file_values.items():
                env.setdefault(key, value)

        config.host = env.get("CLOUD_AGENT_HOST", "127.0.0.1").strip() or "127.0.0.1"
        config.port, ok = parse_int(env.get("CLOUD_AGENT_PORT", "8130"), 8130, 1, 65535)
        if not ok:
            config.config_errors.append("CLOUD_AGENT_PORT 不是 1-65535 的整数，已回退到 8130。")

        config.base_url = env.get("CLOUD_AGENT_LLM_BASE_URL", "").strip().rstrip("/")
        config.model = env.get("CLOUD_AGENT_LLM_MODEL", "").strip()

        if config.base_url and not re.match(r"^https?://", config.base_url, re.IGNORECASE):
            config.config_errors.append("CLOUD_AGENT_LLM_BASE_URL 必须以 http:// 或 https:// 开头。")

        key_file = env.get("CLOUD_AGENT_LLM_API_KEY_FILE", "").strip()
        direct_key = env.get("CLOUD_AGENT_LLM_API_KEY", "").strip()
        if not direct_key and env.get("OPENAI_API_KEY", "").strip():
            direct_key = env.get("OPENAI_API_KEY", "").strip()
            config.api_key_source = "env:OPENAI_API_KEY"
        elif direct_key:
            config.api_key_source = "env:CLOUD_AGENT_LLM_API_KEY"

        # A protected key file is the deployment contract.  It must win over an
        # empty or stale CLOUD_AGENT_LLM_API_KEY inherited from an old systemd
        # EnvironmentFile.  Otherwise saving a key would appear to work while
        # the service kept using the legacy value.
        if key_file:
            try:
                key_path = Path(key_file)
                config.api_key = key_path.read_text(encoding="utf-8").strip()
                config.api_key_source = "file"
                try:
                    mode = key_path.stat().st_mode & 0o777
                    if mode & 0o077:
                        config.config_warnings.append(
                            "API key 文件权限为 %o，建议仅所有者可读（chmod 600）。" % mode
                        )
                except OSError:
                    pass
            except OSError as exc:
                config.config_errors.append(
                    "无法读取 CLOUD_AGENT_LLM_API_KEY_FILE: %s" % (exc.strerror or "unknown error")
                )
        elif direct_key:
            config.api_key = direct_key

        config.llm_proxy = env.get("CLOUD_AGENT_LLM_PROXY", "direct").strip() or "direct"

        config.timeout_seconds, ok = parse_float(
            env.get("CLOUD_AGENT_LLM_TIMEOUT_SECONDS", "45"), 45.0, 5.0, 300.0
        )
        if not ok:
            config.config_errors.append("CLOUD_AGENT_LLM_TIMEOUT_SECONDS 不合法，已回退到 45 秒。")
        config.max_tokens, ok = parse_int(env.get("CLOUD_AGENT_LLM_MAX_TOKENS", "900"), 900, 64, 8192)
        if not ok:
            config.config_errors.append("CLOUD_AGENT_LLM_MAX_TOKENS 不合法，已回退到 900。")
        config.temperature, ok = parse_float(
            env.get("CLOUD_AGENT_LLM_TEMPERATURE", "0.1"), 0.1, 0.0, 2.0
        )
        if not ok:
            config.config_errors.append("CLOUD_AGENT_LLM_TEMPERATURE 不合法，已回退到 0.1。")
        config.max_tool_iterations, ok = parse_int(
            env.get("CLOUD_AGENT_MAX_TOOL_ITERATIONS", "6"), 6, 1, 12
        )
        if not ok:
            config.config_errors.append("CLOUD_AGENT_MAX_TOOL_ITERATIONS 不合法，已回退到 6。")
        config.access_token = env.get("CLOUD_AGENT_ACCESS_TOKEN", "").strip()

        if config.base_url and config.base_url.lower().startswith("http://"):
            config.config_warnings.append(
                "模型 base_url 使用 http://，API key 会以明文经过网络；生产环境应使用 https://。"
            )
        return config
