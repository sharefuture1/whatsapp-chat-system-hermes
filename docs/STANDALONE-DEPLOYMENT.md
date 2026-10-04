# Standalone 部署指南（前后端独立部署）

> 适用范围：Standalone API（`src/whatsapp_chat_system/`）+ `web/` 前端 + `bridge/`。
> 不涉及 Legacy Hermes profile 的启动方式（见 [`DEPLOYMENT.md`](./DEPLOYMENT.md)）。
> 本文描述**部署能力**，生产切流仍需走既有的迁移清单与审批。

---

## 1. 两种部署形态

前后端已完全解耦，按需二选一：

| 形态 | 后端 | 前端 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **分离部署**（推荐） | 纯 API，不托管静态文件 | 独立静态托管（Vercel / Nginx / 对象存储） | 前端可独立迭代、CDN 加速、后端可横向扩容 |
| **单进程** | 纯 API + 托管已构建前端 | 无独立部署 | 内网小规模、运维简单优先 |

关键点：后端**默认就是纯 API 模式**，`--web-dist` 是可选的。

---

## 2. 后端部署

### 2.1 环境准备

```bash
git clone <repo> && cd whatsapp-chat-system-hermes
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .              # PostgreSQL 驱动已包含在依赖中
```

要求 Python ≥ 3.11。

### 2.2 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填好以下两项
```

**必填**

| 变量 | 说明 |
| :--- | :--- |
| `WHATSAPP_BRIDGE_INTERNAL_TOKEN` | Bridge ↔ API 内部事件接口的共享令牌。缺失时该接口以 503 拒绝所有请求 |

**强烈建议**

| 变量 | 说明 |
| :--- | :--- |
| `WHATSAPP_BRIDGE_HMAC_SECRET` | 开启请求签名校验。与 Bridge 端必须配置**同一个值**。详见 §5 |
| `AI_SECRET_ENCRYPTION_KEY` | AI 密钥的加密主密钥。生产环境必须显式设置并备份，否则主密钥文件丢失后库中密文不可解密 |
| `CHAT_SYSTEM_ALLOWED_ORIGINS` | 前后端分离部署时**必须**填入前端域名，否则浏览器会拦截请求 |
| `DATABASE_URL` | 生产建议 PostgreSQL，见 §2.3 |

**首次启动专用**

| 变量 | 说明 |
| :--- | :--- |
| `CHAT_SYSTEM_BOOTSTRAP_PASSWORD` | 至少 12 位。仅用于初始化运行目录下的 `web-settings.json`，初始化完成后可从环境移除 |

> 已存在于进程环境中的变量优先于 `.env` 文件，因此 systemd / Windows 服务 /
> 平台面板注入的配置不会被仓库里的 `.env` 覆盖。首次初始化成功、`web-settings.json` 已生成后，应从持久环境文件移除 `CHAT_SYSTEM_BOOTSTRAP_PASSWORD`。

### 2.3 数据库

两种后端都受支持，且 URL 写法会自动归一（`postgres://` 与 `postgresql://`
都会指向已安装的 psycopg 3 驱动）：

```bash
# SQLite —— 单机、小规模。务必用绝对路径，避免不同工作目录各建一份库
DATABASE_URL=sqlite:////var/lib/whatsapp-chat-system/app.db

# PostgreSQL —— 服务器、多进程部署（推荐）
DATABASE_URL=postgresql://user:password@127.0.0.1:5432/whatsapp_chat
```

**为什么生产建议 PostgreSQL**：outbox 抢占依赖行级互斥。SQLite 不支持
`SELECT ... FOR UPDATE`，多进程下容易出现重复投递（本项目已改用条件 UPDATE
规避，但 PostgreSQL 的并发能力与运维工具仍明显更适合服务器场景）。

先执行迁移（启动时只校验 schema，从不自动建表）：

```bash
alembic upgrade head
```

### 2.4 启动

跨平台启动器（推荐，Linux / macOS / Windows 通用）：

```bash
python scripts/run_server.py --check              # 只做配置自检，不启动
python scripts/run_server.py --migrate            # 先迁移再启动
python scripts/run_server.py --web-dist web/dist  # 单进程模式，同时托管前端
```

也可以直接用 CLI：

```bash
python -m whatsapp_chat_system.cli serve --host 0.0.0.0 --port 8792
```

健康检查：`GET /api/health`，返回 `ok: true` 及各后台 Worker 的心跳。

---

## 3. 各平台运行方式

### 3.1 Linux（systemd）

单元文件：`deploy/systemd/whatsapp-chat-system.service` / `whatsapp-chat-system-api-only.service`（API）与 `whatsapp-bridge-v2.service`（Bridge）。正式分离部署使用 API-only 单元，并以专用低权限账户 `whatsapp-chat-system` 运行 API/Bridge。

```bash
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin whatsapp-chat-system
sudo install -d -m 0750 /etc/whatsapp-chat-system
sudo install -m 0640 deploy/systemd/whatsapp-chat-system.service /etc/systemd/system/
sudo install -m 0640 deploy/systemd/whatsapp-bridge-v2.service /etc/systemd/system/

# /etc/whatsapp-chat-system/api.env 至少包含：
#   DATABASE_URL=postgresql://...
#   WHATSAPP_BRIDGE_INTERNAL_TOKEN=...
#   WHATSAPP_BRIDGE_HMAC_SECRET=...
#   AI_SECRET_ENCRYPTION_KEY=...
#   CHAT_SYSTEM_ALLOWED_ORIGINS=https://your-console.example.com
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-chat-system whatsapp-bridge-v2
```

迁移应在部署流程中单独执行一次，不要放进 `ExecStart`（多副本会并发执行迁移）：

```bash
sudo -u whatsapp-chat-system env $(cat /etc/whatsapp-chat-system/api.env | xargs) \
  /opt/whatsapp-chat-system/.venv/bin/alembic upgrade head
```

当前正式 API 域为 `https://whats.wending.ai`，Nginx 参考 `deploy/nginx/whats.wending.ai.conf`：只代理 `/api/*`，公网 `/internal/*` 必须拒绝，SSE 路径关闭 buffering。CSP 头由前端/Tauri 与 Nginx 各自约束。

### 3.2 Windows

后端本身不依赖 POSIX 特性（已处理密钥文件权限在 Windows 下的差异），
直接运行即可：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env    # 编辑 .env
.\.venv\Scripts\python.exe scripts\run_server.py --migrate
```

注册为 Windows 服务（需管理员 PowerShell）：

```powershell
# 用 NSSM 或 sc.exe 托管启动器；以下以 NSSM 为例
nssm install WhatsAppChatSystem "C:\apps\whatsapp-chat-system\.venv\Scripts\python.exe" `
  "scripts\run_server.py"
nssm set WhatsAppChatSystem AppDirectory "C:\apps\whatsapp-chat-system"
nssm set WhatsAppChatSystem AppEnvironmentExtra `
  "DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/whatsapp_chat" `
  "WHATSAPP_BRIDGE_INTERNAL_TOKEN=..." `
  "WHATSAPP_BRIDGE_HMAC_SECRET=..." `
  "CHAT_SYSTEM_ALLOWED_ORIGINS=https://your-console.example.com"
nssm start WhatsAppChatSystem
```

Windows 注意事项：

- 建议把 `CHAT_SYSTEM_RUNTIME_DIR` 与 SQLite 文件放在 `%PROGRAMDATA%` 下，并确保服务账户有写权限；
- 后端在 Windows 上不强制密钥文件权限位（`os.chmod` 语义不同），请改用 NTFS ACL 限制 `.ai_encryption_key` 的读取；
- Bridge 需要 Node.js 20.x。

### 3.3 macOS

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env
python scripts/run_server.py --migrate
```

需要常驻时用 `launchd`（`~/Library/LaunchAgents/*.plist`），
`ProgramArguments` 指向 `.venv/bin/python` 与 `scripts/run_server.py`。

---

## 4. 前端独立部署

前端在构建期通过 `VITE_API_BASE_URL` 决定后端地址（SDD VCL-002，见 `web/.env.example`）：

```bash
cd web
npm ci
VITE_API_BASE_URL=https://api.example.com/api npm run build
```

在 Vercel / Netlify 等平台，把 `VITE_API_BASE_URL` 配到「环境变量」里即可，
无需修改任何配置文件。**留空则回退为相对路径 `/api`**，此时必须在静态托管
上自行配置到后端的同源反向代理（仓库内的 `vercel.json` 已不再硬编码任何
后端地址）。

同时必须把前端域名加入后端的跨域白名单：

```bash
CHAT_SYSTEM_ALLOWED_ORIGINS=https://console.example.com,http://localhost:5173
```

通配符 `*` 会被显式拒绝（控制台请求携带操作员会话令牌）。后端启动日志会
打印最终生效的白名单，跨域问题优先看这一行。

---

## 5. 内部事件接口的签名校验

Bridge → API 的事件投递支持 HMAC-SHA256 签名，用于防御 token 泄露后的
伪造注入与抓包重放。

启用方式：在**两侧**配置同名变量，值相同且不得与 `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 相同。

```bash
# API 侧（.env / api.env）
WHATSAPP_BRIDGE_HMAC_SECRET=<随机值>

# Bridge 侧（bridge.env / 服务环境变量）
WHATSAPP_BRIDGE_HMAC_SECRET=<同一个随机值>
```

签名口径（两侧实现必须一致，已用黄金向量锁定）：

```
X-Internal-Signature = hex(hmac_sha256(secret, f"{X-Internal-Timestamp}.{raw_body}"))
```

| 请求头 | 说明 |
| :--- | :--- |
| `X-Internal-Token` | 共享令牌（原有机制，始终校验） |
| `X-Internal-Timestamp` | Unix 秒。超出 ±300s 窗口即拒绝 |
| `X-Internal-Signature` | 见上方口径 |
| `X-Internal-Nonce` | 可选。窗口内重复即判为重放 |

逐步启用建议：先在 API 侧保持不配置（或配置后观察），确认 Bridge 已升级到
带签名的版本后再同步开启。API 侧未配置该变量时会保持旧的「仅静态 token」
行为，但启动日志会给出告警。

---

## 6. 部署后验收清单

```bash
# 1) 配置自检（不启动服务）
python scripts/run_server.py --check

# 2) 健康检查
curl -s http://127.0.0.1:8792/api/health

# 3) 内部事件接口必须拒绝未鉴权请求（期望 401）
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8792/internal/events/whatsapp \
  -H 'Content-Type: application/json' -d '{"event_id":"probe"}'

# 4) 跨域白名单是否生效（期望返回 access-control-allow-origin: <你的前端域名>）
curl -s -D - -o /dev/null -X OPTIONS http://127.0.0.1:8792/api/v1/me \
  -H 'Origin: https://console.example.com' -H 'Access-Control-Request-Method: GET'

# 5) PostgreSQL 后端专项验证（需一个专用测试库，会 TRUNCATE 本表）
TEST_DATABASE_URL='postgresql://user:pass@host:5432/whatsapp_test' \
  pytest tests/test_postgres_backend.py -v
```

---

## 7. 常见问题

| 现象 | 原因与处理 |
| :--- | :--- |
| 浏览器报 CORS 错误 | `CHAT_SYSTEM_ALLOWED_ORIGINS` 未包含前端域名。对照启动日志里的白名单 |
| 前端请求打到错误的后端 | 构建时未设置 `VITE_API_BASE_URL`（旧名 `VITE_API_BASE` 仍兼容但会告警），回退成了相对路径 `/api`。检查构建日志与平台环境变量 |
| 内部事件接口全部 503 | 缺少 `WHATSAPP_BRIDGE_INTERNAL_TOKEN` |
| 内部事件接口全部 401 且 code 为 `missing_signature` | API 侧启用了 `WHATSAPP_BRIDGE_HMAC_SECRET` 但 Bridge 未配置或未升级 |
| 启动报 schema not ready | 未执行 `alembic upgrade head` |
| 启动报需要 `CHAT_SYSTEM_BOOTSTRAP_PASSWORD` | 首次初始化运行目录，设置后重启 |
| 提示 `ModuleNotFoundError: psycopg` | 未执行 `pip install -e .`（PostgreSQL 驱动在依赖里） |
| AI 密钥解不开（`api_key_configured` 为 false） | `AI_SECRET_ENCRYPTION_KEY` 变了或密钥文件丢失。密文无法恢复，需重新录入 |
