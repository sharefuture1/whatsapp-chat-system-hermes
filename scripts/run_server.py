#!/usr/bin/env python3
"""跨平台启动器：Linux / macOS / Windows 通用。

为什么要单独写一个 Python 启动器，而不是 bash 脚本：
`start-server.sh` 依赖 POSIX shell 与硬编码的绝对路径，在 Windows 上无法运行，
换台机器也会直接失败。本启动器只用标准库，自动推导仓库根目录，
因此三种系统上都是同一条命令。

用法::

    python scripts/run_server.py                     # 前台启动 API
    python scripts/run_server.py --migrate           # 先执行数据库迁移再启动
    python scripts/run_server.py --web-dist web/dist # 同时托管已构建前端（单进程模式）
    python scripts/run_server.py --check             # 只做配置自检，不启动

环境变量可通过仓库根目录下的 `.env` 文件提供（参见 `.env.example`）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
IS_POSIX = os.name == "posix"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8792
DEFAULT_RUNTIME_DIRNAME = ".runtime"
DEFAULT_DATA_DIRNAME = "data"
DEFAULT_DB_FILENAME = "whatsapp-chat-system.db"


def load_env_file(path: Path) -> int:
    """把 KEY=VALUE 形式写入 os.environ。

    已存在的环境变量优先（与 docker-compose/系统服务的行为一致），
    因此从平台面板注入的配置不会被本地 .env 覆盖。
    """

    if not path.is_file():
        return 0
    loaded = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value
        loaded += 1
    return loaded


def ensure_directory(path: Path, *, private: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if private and IS_POSIX:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def resolve_settings(args: argparse.Namespace) -> dict[str, str]:
    """推导运行所需配置，并把默认值写回 os.environ。"""

    runtime_dir = Path(
        os.environ.get("CHAT_SYSTEM_RUNTIME_DIR")
        or (Path(args.runtime_dir) if args.runtime_dir else ROOT / DEFAULT_RUNTIME_DIRNAME)
    ).expanduser()
    ensure_directory(runtime_dir, private=True)
    os.environ["CHAT_SYSTEM_RUNTIME_DIR"] = str(runtime_dir)

    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        data_dir = ensure_directory(ROOT / DEFAULT_DATA_DIRNAME)
        # 用绝对路径，避免不同工作目录下的服务进程各自创建一份数据库
        db_file = (data_dir / DEFAULT_DB_FILENAME).resolve()
        database_url = f"sqlite:///{db_file.as_posix()}"
        os.environ["DATABASE_URL"] = database_url

    return {
        "runtime_dir": str(runtime_dir),
        "database_url": database_url,
        "internal_token": (os.environ.get("WHATSAPP_BRIDGE_INTERNAL_TOKEN") or "").strip(),
        "hmac_secret": (os.environ.get("WHATSAPP_BRIDGE_HMAC_SECRET") or "").strip(),
        "allowed_origins": (os.environ.get("CHAT_SYSTEM_ALLOWED_ORIGINS") or "").strip(),
        "bridge_url": (os.environ.get("WHATSAPP_BRIDGE_V2_URL") or "").strip(),
        "web_dist": Path(args.web_dist).expanduser() if args.web_dist else None,
    }


def describe(settings: dict[str, str]) -> list[str]:
    """生成自检报告；同时用于启动日志。"""

    from whatsapp_chat_system.db.url import (
        database_backend,
        describe_database_url,
        sqlite_file_path,
    )

    lines = [
        f"运行目录      : {settings['runtime_dir']}",
        f"数据库后端    : {database_backend(settings['database_url'])}",
        f"数据库连接    : {describe_database_url(settings['database_url'])}",
    ]
    sqlite_path = sqlite_file_path(settings["database_url"])
    if sqlite_path:
        lines.append(f"SQLite 文件   : {sqlite_path}")
    lines.append(
        "Bridge 地址   : " + (settings["bridge_url"] or "http://127.0.0.1:3100 (默认)")
    )
    lines.append(
        "跨域白名单    : "
        + (settings["allowed_origins"] or "内置默认值（生产环境建议显式配置）")
    )
    lines.append(
        "事件签名      : "
        + ("已启用 HMAC" if settings["hmac_secret"] else "未启用（建议设置 WHATSAPP_BRIDGE_HMAC_SECRET）")
    )
    lines.append(
        "内部事件 token: " + ("已配置" if settings["internal_token"] else "缺失")
    )
    return lines


def validate(settings: dict[str, str]) -> list[str]:
    """返回阻塞性问题的说明列表。"""

    problems: list[str] = []
    if not settings["internal_token"]:
        problems.append(
            "缺少 WHATSAPP_BRIDGE_INTERNAL_TOKEN：Bridge 与 API 之间的内部事件接口"
            "会以 503 拒绝所有请求。请在 .env 中设置一个足够随机的值。"
        )
    elif len(settings["internal_token"]) < 16:
        problems.append(
            "WHATSAPP_BRIDGE_INTERNAL_TOKEN 长度不足 16 位，建议改用更长的随机值。"
        )
    if settings["hmac_secret"] and settings["hmac_secret"] == settings["internal_token"]:
        problems.append(
            "WHATSAPP_BRIDGE_HMAC_SECRET 不得与 WHATSAPP_BRIDGE_INTERNAL_TOKEN 相同。"
        )

    # 首次启动需要一次性引导密码来初始化运行时配置。
    # 底层 RuntimeError 信息不易自查，这里提前给出可操作提示。
    web_settings_file = Path(settings["runtime_dir"]) / "web-settings.json"
    if not web_settings_file.is_file():
        bootstrap = (os.environ.get("CHAT_SYSTEM_BOOTSTRAP_PASSWORD") or "").strip()
        if len(bootstrap) < 12:
            problems.append(
                f"首次启动需要设置 CHAT_SYSTEM_BOOTSTRAP_PASSWORD（至少 12 位）"
                f"以初始化 {web_settings_file.parent} 下的运行时配置。"
                "该密码仅在首次初始化时使用，后续启动可移除该项。"
            )

    # 单进程模式：--web-dist 必须真的指向已构建的前端
    web_dist = settings.get("web_dist")
    if web_dist is not None and not (web_dist / "index.html").is_file():
        problems.append(
            f"--web-dist 指向的目录缺少 index.html：{web_dist}。"
            "请先在 web/ 执行 npm ci && npm run build，或去掉 --web-dist 改用纯 API 模式。"
        )
    return problems


def run_migrations() -> int:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    return 0


def _env_int(name: str, fallback: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        print(f"[!] 环境变量 {name}={raw!r} 不是合法整数，回退为 {fallback}")
        return fallback


def main(argv: list[str] | None = None) -> int:
    # 必须先载入 .env，再构造 parser：否则 argparse 的默认值（端口、host、
    # web-dist）会在 .env 生效之前就求值，导致 .env 里的配置被静默忽略。
    loaded = load_env_file(ENV_FILE)

    parser = argparse.ArgumentParser(
        prog="run_server.py",
        description="跨平台启动 Standalone API（Linux / macOS / Windows）。",
    )
    parser.add_argument(
        "--host", default=(os.environ.get("CHAT_SYSTEM_HOST") or DEFAULT_HOST).strip()
    )
    parser.add_argument(
        "--port", type=int, default=_env_int("CHAT_SYSTEM_PORT", DEFAULT_PORT)
    )
    parser.add_argument(
        "--web-dist",
        default=os.environ.get("CHAT_SYSTEM_WEB_DIST") or None,
        help="可选：已构建前端目录。不传则为纯 API 模式，前端可独立部署。",
    )
    parser.add_argument("--runtime-dir", default=None, help="覆盖运行目录")
    parser.add_argument(
        "--migrate", action="store_true", help="启动前执行 alembic upgrade head"
    )
    parser.add_argument(
        "--check", action="store_true", help="只打印配置自检结果并退出"
    )
    args = parser.parse_args(argv)

    settings = resolve_settings(args)

    print("=" * 68)
    print("WhatsApp Chat System — Standalone API")
    print("=" * 68)
    if loaded:
        print(f"已从 {ENV_FILE.name} 载入 {loaded} 个环境变量")
    for line in describe(settings):
        print(line)

    problems = validate(settings)
    if problems:
        print("-" * 68)
        for problem in problems:
            print(f"[!] {problem}")
        return 2

    if args.check:
        print("-" * 68)
        print("[ok] 配置自检通过")
        return 0

    if args.migrate:
        print("-" * 68)
        print("执行数据库迁移 ...")
        run_migrations()

    # web-dist 的有效性已在 validate() 中检查，这里只做模式说明
    web_dist_path = settings.get("web_dist")
    if web_dist_path is not None:
        web_dist = str(web_dist_path.resolve())
        print(f"单进程模式：同时托管前端 {web_dist}")
    else:
        web_dist = None
        print("纯 API 模式：前端请独立部署，并通过 VITE_API_BASE 指向本服务")

    print("-" * 68)
    print(f"监听 http://{args.host}:{args.port}")
    sys.stdout.flush()

    # 延迟导入：让 --check 在未装依赖时也能给出可读报错
    import uvicorn

    from whatsapp_chat_system.standalone_api import build_standalone_app

    uvicorn.run(
        build_standalone_app(web_dist=web_dist),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
