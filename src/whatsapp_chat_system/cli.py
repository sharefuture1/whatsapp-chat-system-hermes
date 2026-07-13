from __future__ import annotations

import argparse

import uvicorn

from .standalone_api import build_standalone_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whatsapp-chat-system")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("router", "Process admin outbound routing commands"),
        ("forward", "Forward user/assistant chat summaries to the admin"),
        ("refresh-memory", "Refresh per-user memory markdown from state.db"),
    ):
        legacy = sub.add_parser(command, help=help_text)
        legacy.add_argument("--profile", required=True)
    serve = sub.add_parser("serve", help="Run FastAPI backend for web console")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument(
        "--web-dist",
        default=None,
        help="Optional built frontend directory to mount at /",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "router":
        from .config import AppConfig
        from .router import AdminRouter

        config = AppConfig.from_profile(args.profile)
        return AdminRouter(config).run()
    if args.command == "forward":
        from .config import AppConfig
        from .forwarder import AdminForwarder

        config = AppConfig.from_profile(args.profile)
        return AdminForwarder(config).run()
    if args.command == "refresh-memory":
        from .config import AppConfig
        from .memory_refresh import MemoryRefresher

        config = AppConfig.from_profile(args.profile)
        return MemoryRefresher(config).run()
    if args.command == "serve":
        uvicorn.run(
            build_standalone_app(web_dist=args.web_dist), host=args.host, port=args.port
        )
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
