# 前端 Vercel 部署规格

> 状态：**Active / Mandatory**
> 基线日期：`2026-07-14`
> 上位需求：`NFR-OPS-001`、`NFR-OPS-002`、`MIG-7`、`MIG-8`
> 关联 backlog：`SDD-P1-13`

## 1. 目标拓扑

前端（React SPA）迁至 Vercel 托管，后端保持自托管：

```text
用户浏览器
  ├── https://<app-domain>            → Vercel（静态 SPA，web/dist）
  └── https://<api-domain>/api/v1/*  → 自托管 FastAPI（whats.future1.us，systemd）
                                        ├── Bridge V2 (loopback :3100)
                                        └── PostgreSQL / SQLite(dev)
```

原则：

- Vercel 只承载静态产物与 SPA 路由回退，**不承载任何后端逻辑、密钥或数据**；
- FastAPI 继续按 `02-system-architecture.md` §6 的 systemd 合同运行，并保留 `CHAT_SYSTEM_WEB_DIST` 自托管前端能力作为回滚路径；
- 域名规划推荐前后端同注册域（如 `app.future1.us` + `whats.future1.us`），为 SDD-P1-07 Cookie 认证升级预留 same-site 条件。

## 2. 需求

### VCL-001 构建与产物合同 [Approved]

- `vercel.json` 是 Vercel 侧构建/路由的唯一权威：`installCommand`/`buildCommand` 固定走 `npm --prefix web`，`outputDirectory: web/dist`。
- SPA 回退：除静态资源与 `/api/*` 外的所有路径 rewrite 到 `/index.html`。
- 构建产物必须与自托管部署使用同一份 `web/dist` 语义（同一 commit 构建结果等价），不允许 Vercel 专属源码分支。
- 验收：Vercel Preview 构建通过；直接访问深链（如 `/settings`）返回 SPA 而非 404。

### VCL-002 API 基址与访问模式 [Approved]

- 前端 API 基址由构建时环境变量 `VITE_API_BASE_URL` 控制；为空时回退相对路径 `/api`（兼容自托管同源部署与 Vercel rewrite 代理）。
- **权威模式：直连跨域** —— Vercel 生产环境设置 `VITE_API_BASE_URL=https://<api-domain>/api`，浏览器直连 API 域，不经 Vercel 代理。
- `vercel.json` 中 `/api/(.*) → https://whats.future1.us/api/$1` 的 rewrite 仅作为**过渡兼容**保留；SSE 上线（RT-001）后该模式不得用于生产，因为长连接经 Vercel 代理有缓冲与时长限制。
- `web/src/api.js` 必须统一读取该基址；任何组件不得硬编码绝对 API URL。
- 验收：`VITE_API_BASE_URL` 注入后所有请求（含 EventSource）指向 API 域；未设置时行为与当前自托管完全一致。

### VCL-003 CORS 与鉴权合同 [Approved]

- FastAPI CORS 维持显式 allowlist：仅生产前端域 + 明确批准的域；**禁止通配符**，禁止把 `*.vercel.app` 整域加入生产 allowlist。
- 现阶段鉴权为 `x-session-token` 请求头（非 Cookie），跨域直连仅需 allowlist + `OPTIONS` 放行（既有基线"CORS OPTIONS 不被 auth 拦截"不得回归）。
- SDD-P1-07 升级 HttpOnly Cookie 时：必须满足前后端同注册域（same-site），Cookie 取 `Secure; HttpOnly; SameSite=Lax`，CORS 开 `allow_credentials` 且 origin 精确匹配；如无法同域则必须退回 Vercel 同源代理模式并重新评审本节。
- 验收：跨域登录/会话/发送/翻译全链路回归；非 allowlist origin 被拒绝的自动化测试。

### VCL-004 SSE 与流式兼容 [Approved]

- `EventSource` 必须直连 `VITE_API_BASE_URL` 指向的 API 域（VCL-002 权威模式），不经 Vercel rewrite。
- API 域的反向代理（nginx）需为 `/api/v1/events/stream` 关闭缓冲（`proxy_buffering off`）并放宽读超时 ≥ 120s，配置纳入 `deploy/nginx`。
- 验收：Vercel 前端上 SSE 心跳稳定 ≥ 5 分钟无断流；断线重连走 RT-002 语义。

### VCL-005 环境隔离 [Approved]

- **Preview 部署禁止指向生产 API**：Preview 环境 `VITE_API_BASE_URL` 只能指向 staging API 或留空（无后端，仅 UI 冒烟）；`vercel.json` 的生产 rewrite 不得让 Preview 流量落到生产。
- 环境变量矩阵（Production/Preview/Development）在 Vercel 项目设置中显式维护，本文件记录键名与语义，值不入 Git。
- 前端构建产物中不得出现任何密钥；`VITE_*` 变量仅限公开配置（API 基址、构建标识）。
- 验收：Preview 部署的网络面板无生产域请求；构建产物 grep 无密钥形态字符串。

### VCL-006 缓存、版本与回滚 [Approved]

- 静态资源：带内容哈希的 `assets/*` 走 `Cache-Control: public, max-age=31536000, immutable`；`index.html` 走 `no-cache`（Vercel 默认满足，变更需回归验证）。
- 每次生产部署后验证：页面引用的 `index-*.js/css` 哈希与本次构建一致（沿用现有验证命令语义）。
- 回滚路径双保险：Vercel 侧 instant rollback 到上一 deployment；或 DNS/入口切回自托管 `CHAT_SYSTEM_WEB_DIST` 模式。回滚演练是 `Verified` 的前置条件。
- 验收：完成一次真实 rollback 演练并记录在 `CHANGELOG_AGENT.md`。

## 3. 上线步骤（衔接 MIG-7 / MIG-8）

1. `api.js` 接入 `VITE_API_BASE_URL`（VCL-002），自托管行为不变，全量测试通过；
2. API 域 CORS allowlist 加入 Vercel 生产域（VCL-003），nginx SSE 配置就位（VCL-004）；
3. Vercel 项目绑定仓库，配置环境变量矩阵（VCL-005），Preview 验收 UI 冒烟；
4. 生产域名切到 Vercel，运行 VCL-006 版本验证 + 主链路回归（登录/收发/翻译/SSE）；
5. 回滚演练；更新 `PROJECT_MEMORY.md` 与 backlog 状态。

## 4. 安全红线

- 密钥、内部 token、数据库连接串永不进入 Vercel 环境变量（前端不需要任何秘密）；
- 生产 API 不因 Vercel 接入放宽鉴权；`/internal/*` 与 Bridge 端口继续只绑定 loopback；
- 本规格不改变 `07-migration-and-rollout.md` 的切流窗口纪律：生产 DNS/域名切换只能在受控窗口执行。

## 5. 明确不采用

- Vercel Serverless/Edge Functions 承载业务 API（后端保持自托管 FastAPI）；
- 在 Vercel 上运行 Bridge 或任何长驻 Worker；
- Preview 环境共享生产数据库或生产 API。
