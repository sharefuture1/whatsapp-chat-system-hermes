# Deployment Notes — Legacy Only

> **阻断：本文件和 `deploy/apply-production.sh` 仅适用于 Legacy Hermes/profile 服务，绝不得用于 Standalone 切换或生产切流。**
> Standalone API 必须通过独立运行目录、`DATABASE_URL` 和 `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 启动；实际切换步骤在独立迁移清单完成后另行批准。

## Legacy development and rollback only

这些历史命令保留给回滚/兼容诊断，仍依赖 Hermes profile：

```bash
./.venv/bin/python -m whatsapp_chat_system.cli router --profile /root/.hermes/profiles/whatsapp-support
```

不要将旧 `--profile ... serve` 命令、旧 systemd 服务或 `deploy/apply-production.sh` 用于 Standalone 环境。

## Standalone preflight contract

Standalone `serve` 只接受独立环境配置：

- `CHAT_SYSTEM_RUNTIME_DIR`：绝对路径，保存 API 运行态设置；
- `DATABASE_URL`：必须明确设置，禁止默认相对 SQLite；
- `WHATSAPP_BRIDGE_INTERNAL_TOKEN`：Bridge 内部事件认证 token；
- `CHAT_SYSTEM_BOOTSTRAP_PASSWORD`：首次初始化认证密码，**至少 12 个字符**；
- `AI_SECRET_ENCRYPTION_KEY`：仅在启用 AI 功能或写入 AI Provider secret 前必须设置，用于运行时密钥加密；不是 Standalone API 的通用启动前置条件。

生产前置检查（**不是**切流说明）：

```bash
# 在目标独立数据库、且正确 DATABASE_URL 已导出的环境中执行
alembic upgrade head
```

Standalone 启动时只检查既有 schema，绝不自动建表；未执行迁移会拒绝启动。不要在文档、命令历史或仓库中填入真实 token、密码或加密密钥。独立迁移清单、Bridge/Worker 验收和正式切流仍处于 **In Progress**，本节仅定义 preflight 合同，不构成生产 cutover 指令。
