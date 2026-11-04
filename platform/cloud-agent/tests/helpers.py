"""Test helpers.  All tests use a fake LLM transport and never call a network."""

import copy
import datetime
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from wsgiref.util import setup_testing_defaults

from cloud_agent.agent import AgentService
from cloud_agent.config import Config
from cloud_agent.http_api import Application
from cloud_agent.registry import Registry
from cloud_agent.store import ProposalStore
from cloud_agent.tools import ToolBox

ROOT = Path(__file__).resolve().parent.parent
FIXED_NOW = datetime.datetime(2026, 10, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)


def fixed_now():
    return FIXED_NOW


def temp_dir(testcase):
    directory = tempfile.TemporaryDirectory()
    testcase.addCleanup(directory.cleanup)
    return Path(directory.name)


def make_config(tmpdir, configured=True, access_token="", **overrides):
    env = {
        "CLOUD_AGENT_ENV_FILE": "",
        "CLOUD_AGENT_STATE_DIR": str(Path(tmpdir) / "state"),
        "CLOUD_AGENT_ACCESS_TOKEN": access_token,
    }
    if configured:
        env.update(
            {
                "CLOUD_AGENT_LLM_BASE_URL": "https://example.test/v1",
                "CLOUD_AGENT_LLM_MODEL": "test-model",
                "CLOUD_AGENT_LLM_API_KEY": "test-secret-key",
            }
        )
    env.update({key: str(value) for key, value in overrides.items()})
    return Config.load(root=ROOT, environ=env, allow_default_env_file=False)


def make_registry():
    """Load the explicit test fixture, never the production data/ defaults."""
    return Registry(ROOT / "tests" / "fixtures", now_fn=fixed_now)


def make_store(tmpdir, persist=True):
    path = Path(tmpdir) / "proposals.json" if persist else None
    return ProposalStore(path, now_fn=fixed_now)


def make_toolbox(config, registry, store):
    return ToolBox(config, registry, store)


def text_response(text="这是最终答复。"):
    return {
        "message": {"role": "assistant", "content": text},
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "finish_reason": "stop",
    }


def tool_response(calls):
    tool_calls = []
    for index, (name, arguments) in enumerate(calls):
        if isinstance(arguments, str):
            arguments_text = arguments
        else:
            arguments_text = json.dumps(arguments, ensure_ascii=False)
        tool_calls.append(
            {
                "id": "call_test_%d" % index,
                "type": "function",
                "function": {"name": name, "arguments": arguments_text},
            }
        )
    return {
        "message": {"role": "assistant", "content": "", "tool_calls": tool_calls},
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        "finish_reason": "tool_calls",
    }


class FakeLLM(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
            }
        )
        if not self.responses:
            raise AssertionError("FakeLLM has no scripted response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_agent(tmpdir, responses, configured=True, access_token="", max_tool_iterations=6):
    config = make_config(
        tmpdir,
        configured=configured,
        access_token=access_token,
        CLOUD_AGENT_MAX_TOOL_ITERATIONS=max_tool_iterations,
    )
    registry = make_registry()
    store = make_store(tmpdir)
    toolbox = make_toolbox(config, registry, store)
    llm = FakeLLM(responses)
    agent = AgentService(config, toolbox, llm)
    return SimpleNamespace(
        config=config,
        registry=registry,
        store=store,
        toolbox=toolbox,
        llm=llm,
        agent=agent,
    )


def make_app(tmpdir, responses=None, configured=True, access_token=""):
    parts = make_agent(
        tmpdir,
        responses or [],
        configured=configured,
        access_token=access_token,
    )
    application = Application(
        parts.config,
        parts.registry,
        parts.store,
        parts.toolbox,
        parts.agent,
        static_dir=ROOT / "static",
    )
    return SimpleNamespace(
        app=application,
        config=parts.config,
        registry=parts.registry,
        store=parts.store,
        toolbox=parts.toolbox,
        agent=parts.agent,
        llm=parts.llm,
    )


def call_wsgi(app, method, path, body=None, headers=None, query="", remote="127.0.0.1"):
    if body is not None and not isinstance(body, (bytes, bytearray)):
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    body = body or b""
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["QUERY_STRING"] = query
    environ["REMOTE_ADDR"] = remote
    environ["wsgi.input"] = io.BytesIO(body)
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["CONTENT_TYPE"] = "application/json"
    for key, value in (headers or {}).items():
        if key.lower() == "content-type":
            environ["CONTENT_TYPE"] = value
        else:
            environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = response_headers

    captured["body"] = b"".join(app(environ, start_response))
    captured["status_code"] = int(captured["status"].split(" ", 1)[0])
    captured["header_map"] = {key.lower(): value for key, value in captured["headers"]}
    if captured["body"]:
        try:
            captured["json"] = json.loads(captured["body"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            captured["json"] = None
    else:
        captured["json"] = None
    return captured
