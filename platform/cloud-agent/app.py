#!/usr/bin/env python3
"""Entry point for the VelaGuard cloud agent.

Usage:
    python3 app.py --host 0.0.0.0 --port 8130
    python3 app.py --print-status

The service starts even when the model is not configured.  In that state the
UI and read-only tools work, while ``POST /api/chat`` returns 503 with an
explicit configuration message.
"""

import argparse
import json
import logging
import os
import sys
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from cloud_agent import SERVICE_NAME, __version__
from cloud_agent.agent import AgentService
from cloud_agent.config import Config
from cloud_agent.errors import RegistryError
from cloud_agent.http_api import Application
from cloud_agent.llm import OpenAIClient
from cloud_agent.registry import Registry
from cloud_agent.store import ProposalStore
from cloud_agent.tools import ToolBox
from cloud_agent.util import isoformat, utc_now

LOG = logging.getLogger("cloud_agent")


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class RequestHandler(WSGIRequestHandler):
    def log_message(self, format_string, *args):
        LOG.debug("%s - %s", self.address_string(), format_string % args)


def build_application(config, llm=None, now_fn=None):
    registry = Registry(config.data_dir, now_fn=now_fn)
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("无法创建状态目录 %s: %s" % (config.state_dir, exc))
    store = ProposalStore(config.state_dir / "proposals.json", now_fn=now_fn)
    if store.load_warning:
        LOG.warning("%s", store.load_warning)
    toolbox = ToolBox(config, registry, store)
    llm_client = llm or OpenAIClient(config)
    agent = AgentService(config, toolbox, llm_client)
    if config.static_dir is None:
        config.static_dir = config.root / "static"
    return Application(config, registry, store, toolbox, agent, static_dir=config.static_dir)


def _safe_status(config):
    return {
        "service": SERVICE_NAME,
        "version": __version__,
        "time": isoformat(utc_now()),
        "status": "ready" if config.configured else "unconfigured",
        "host": config.host,
        "port": config.port,
        "llm": config.public_status(),
        "execution": {
            "available": False,
            "executor": "none_v1",
            "reason": "首版没有运动执行器；计划确认不等于执行。",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="VelaGuard cloud agent")
    parser.add_argument("--host", default=None, help="监听地址（默认读取 CLOUD_AGENT_HOST 或 127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认读取 CLOUD_AGENT_PORT 或 8130）")
    parser.add_argument("--root", default=None, help="服务根目录，默认为本文件所在目录")
    parser.add_argument("--print-status", action="store_true", help="打印不含密钥的配置状态后退出")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    parser.add_argument("--log-level", default="INFO", help="日志级别，默认 INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, (args.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.version:
        print(__version__)
        return 0

    root = args.root or os.path.dirname(os.path.abspath(__file__))
    config = Config.load(root=root)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if config.port < 1 or config.port > 65535:
        print("端口不合法：%s" % config.port, file=sys.stderr)
        return 2

    if args.print_status:
        print(json.dumps(_safe_status(config), ensure_ascii=False, indent=2))
        return 0

    for warning in config.config_warnings:
        LOG.warning("%s", warning)
    for error in config.config_errors:
        LOG.error("%s", error)

    try:
        application = build_application(config)
    except RegistryError as exc:
        LOG.error("注册表加载失败：%s", exc.message)
        return 2
    except RuntimeError as exc:
        LOG.error("%s", exc)
        return 2

    LOG.info("%s %s starting on %s:%s", SERVICE_NAME, __version__, config.host, config.port)
    LOG.info("env_file=%s state_dir=%s", config.env_file or "(none)", config.state_dir)
    if config.configured:
        LOG.info("LLM configured: model=%s base_url=%s", config.model, config.public_status()["base_url"])
    else:
        LOG.warning(
            "LLM is NOT configured. /api/chat will return 503; no mock reply will be generated. missing=%s",
            ",".join(config.missing_fields) or "(config errors)",
        )
    if config.host not in ("127.0.0.1", "localhost", "::1") and not config.access_token:
        LOG.warning(
            "Listening on a non-loopback address without CLOUD_AGENT_ACCESS_TOKEN; anyone on the LAN can call the API."
        )

    try:
        server = make_server(
            config.host, config.port, application, server_class=ThreadingWSGIServer, handler_class=RequestHandler
        )
    except OSError as exc:
        LOG.error("无法监听 %s:%s：%s", config.host, config.port, exc)
        return 2

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        LOG.info("interrupted, shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
