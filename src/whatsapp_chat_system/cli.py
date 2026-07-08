from __future__ import annotations

import argparse

import uvicorn

from .config import AppConfig
from .forwarder import AdminForwarder
from .memory_refresh import MemoryRefresher
from .router import AdminRouter
from .web_api import build_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='whatsapp-chat-system')
    parser.add_argument('--profile', default='/root/.hermes/profiles/whatsapp-support')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('router', help='Process admin outbound routing commands')
    sub.add_parser('forward', help='Forward user/assistant chat summaries to the admin')
    sub.add_parser('refresh-memory', help='Refresh per-user memory markdown from state.db')
    serve = sub.add_parser('serve', help='Run FastAPI backend for web console')
    serve.add_argument('--host', default='0.0.0.0')
    serve.add_argument('--port', type=int, default=8787)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = AppConfig.from_profile(args.profile)
    if args.command == 'router':
        return AdminRouter(config).run()
    if args.command == 'forward':
        return AdminForwarder(config).run()
    if args.command == 'refresh-memory':
        return MemoryRefresher(config).run()
    if args.command == 'serve':
        uvicorn.run(build_app(args.profile), host=args.host, port=args.port)
        return 0
    parser.error(f'unknown command: {args.command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
