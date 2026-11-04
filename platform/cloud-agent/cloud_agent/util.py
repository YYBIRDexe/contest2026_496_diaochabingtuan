"""Small helpers with no third-party dependencies."""

import datetime
import json
import re
import uuid

try:  # Python 3.8 compatibility: timezone.utc exists, datetime.UTC does not.
    from datetime import timezone
except ImportError:  # pragma: no cover
    timezone = None


SECRET_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")


def utc_now():
    return datetime.datetime.now(timezone.utc)


def isoformat(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso8601(value):
    """Parse an ISO-8601 timestamp and require an explicit timezone.

    A naive timestamp is rejected by the caller because the platform and the
    operator may be in different timezones; guessing UTC would hide mistakes.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("timestamp is not valid ISO-8601")
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit timezone (for example Z or +08:00)")
    return parsed.astimezone(timezone.utc)


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex)


def redact_url(url):
    """Keep scheme/host/path, drop credentials, query and fragment."""
    if not url:
        return ""
    text = str(url).strip()
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(text)
        host = parts.hostname or ""
        port = ""
        if parts.port:
            port = ":%d" % parts.port
        path = parts.path or ""
        return "%s://%s%s%s" % (parts.scheme or "http", host, port, path)
    except Exception:
        return text.split("?", 1)[0].split("#", 1)[0]


def redact_secrets(text, extra_secret=None):
    if text is None:
        return ""
    output = str(text)
    if extra_secret:
        output = output.replace(str(extra_secret), "***")
    output = SECRET_KEY_RE.sub("sk-***", output)
    return output


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value):
    return json.loads(value)


def truncate_text(value, limit=500):
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default, False
    if minimum is not None and parsed < minimum:
        return default, False
    if maximum is not None and parsed > maximum:
        return default, False
    return parsed, True


def parse_float(value, default, minimum=None, maximum=None):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default, False
    if minimum is not None and parsed < minimum:
        return default, False
    if maximum is not None and parsed > maximum:
        return default, False
    return parsed, True


def safe_join(base_dir, relative_path):
    """Resolve a URL path beneath base_dir, refusing traversal and absolute paths."""
    import os

    base = os.path.realpath(str(base_dir))
    cleaned = str(relative_path or "").replace("\\", "/").lstrip("/")
    target = os.path.realpath(os.path.join(base, cleaned))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except (ValueError, OSError):
        return None
    return target
