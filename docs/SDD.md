# 软件设计文档（SDD）— Hermes WhatsApp 运营控制台

> Software Design Document
> 项目：`hermes-whatsapp-ops-console`（包名 `whatsapp_chat_system`）
> 版本：0.6.0
> 状态：内部私有运营工具

---

## 1. 文档目的与范围

本文档描述该项目的整体设计：系统边界、模块职责、数据模型、接口契约、关键流程与安全模型，并在第 9 节给出一份**按优先级排序、可执行的优化清单**（含代码定位与建议方案）。

适用读者：维护该控制台的开发/运营人员，以及后续接手的工程师。

不在范围内：Hermes 本体网关的实现、WhatsApp 协议细节、模型服务（LLM）的内部实现。

## 2. 系统概览

该系统是叠加在既有 **Hermes WhatsApp 支持工作区** 之上的运营控制台。运营人员通过一个受密码保护的 Web 控制台查看对话、生成/翻译/直发回复，并把用户与助手的对话转发到管理员渠道。

三层结构：

| 层 | 组成 | 职责 |
| --- | --- | --- |
| Hermes 运行时 | WhatsApp 网关、`state.db`、`hermes send` 命令 | 消息收发与持久化（外部系统） |
| Python 应用层 | FastAPI + CLI 后台任务 | 读取会话状态、生成用户画像、路由/改写/转发、暴露受保护 API |
| React 控制台 | `web/src/*` | 登录、会话浏览、回复预览/发送、设置管理，移动端 + 桌面端自适应，支持 i18n 与深/浅色主题 |

```
WhatsApp 用户 ──► Hermes 网关 ──► state.db ──┐
                                             ├─► Python 应用层 (FastAPI/CLI) ─► React 控制台
管理员渠道 ◄── hermes send ◄── 应用层 ───────┘
```

## 3. 组件设计

### 3.1 后端模块（`src/whatsapp_chat_system/`）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `web_api.py` | 326 | FastAPI 应用：鉴权、仪表盘、会话、回复预览/发送、设置、本地隐藏、任务触发、登录限流 |
| `router.py` | 218 | 管理员出站路由：按别名/名称/ID 解析目标，加载记忆，选择改写策略，经 Hermes 发送 |
| `rewriter.py` | 171 | 智能改写 / 纯翻译 / 回退控制 / 输出校验与长度控制 |
| `profile.py` | 203 | 从用户消息合成软画像（语言、语气、话题、敏感点、回复偏好），渲染为 Markdown |
| `config.py` | 152 | Profile 感知配置：路径、PBKDF2 密码记录、Web 设置、默认渠道、CHAT_SYSTEM_BOOTSTRAP_PASSWORD |
| `messaging.py` | 123 | Hermes `send` 封装、目标解析、别名生成 |
| `forwarder.py` | 103 | 把「用户消息 → 助手回复」成对转发给管理员渠道 |
| `memory_refresh.py` | 82 | 从 `state.db` 转录历史生成每用户 Markdown 记忆文件 |
| `storage.py` | 81 | SQLite 访问助手 + JSON 事件日志（fetch_session_messages 暴露 message_id） |
| `language.py` | 76 | 语言/语气启发式 + 文本后处理（去重、压缩） |
| `cli.py` | 45 | 子命令入口：`router` / `forward` / `refresh-memory` / `serve` |
| `parsing.py` | 35 | 管理员中文命令解析（`发给 X：内容`） |
| `constants.py` | 12 | 默认 profile、管理员 ID、管理员目标 |

### 3.2 前端（`web/`）

应用入口：
- `web/src/App.jsx`
  - 顶层 `SettingsProvider` 包装
  - 微信式 4 tab shell：Chats / Contacts / Discover / Me
  - 聊天页作为主工作区；设置从 Me 页进入，不打断聊天
  - 监听 401 自动 logout
- `web/src/settings.jsx` + `i18n.js`
  - 多语言 + 主题
  - 当前支持：English / 中文 / ไทย / ລາວ
- `web/src/api.js`
  - 统一 fetch 封装
  - 401 自动触发 logout
  - `VITE_API_BASE` 切换后端
- `web/src/components/`
  - `ChatList.jsx` — 微信式会话列表
  - `ChatPane.jsx` — 聊天窗口（底部最新消息、按需加载历史、常用 emoji、自动翻译行、下一会话切换）
  - `ContactsPage.jsx` — 通讯录页
  - `DiscoverPage.jsx` — 发现页
  - `MePage.jsx` — 我页
  - `TabBar.jsx` — 底部 4 tab
  - `SettingsPanel.jsx` — 设置 modal（reply policy / UI / channels / security）
  - `LoginScreen.jsx` — 登录页
- `web/src/styles.css` — 微信式设计变量、聊天布局、登录页、设置页、响应式
- `web/src/format.js` — 时间格式化

响应式策略：
- 桌面：会话列表 + 聊天窗双栏
- 手机：底部 4 tab，聊天页单独占满内容区域
- newest messages anchored at bottom，older history lazy-load on demand

## 4. 数据模型

### 4.1 权威数据源（只读）

- **`state.db`（SQLite）** — Hermes 拥有。关键表：
  - `sessions(id, user_id, title, started_at, source)`
  - `messages(id, session_id, role, content, timestamp)`
- **`sessions/sessions.json`** — 会话来源（origin）元数据：`user_name`、`chat_name`、`user_id`。

### 4.2 应用自有的 Profile 本地文件（读写）

| 文件 | 内容 |
| --- | --- |
| `admin-channels.json` | 管理员投递渠道（platform/target/kinds/enabled） |
| `web-settings.json` | 鉴权记录、reply/ui/message_ops 策略、`sessions`、`hidden_message_ids`、`login_attempts` |
| `user-aliases.json` | 联系人数字别名 |
| `user-memory-md/*.md` | 生成的每用户画像（命名 `{safe_name}__{user_id}.md`） |
| `user-memory-md/.translations__{user_id}.json` | 每用户消息翻译缓存（原文语言 / 中文翻译 / 更新时间） |
| `.admin-command-router-state.json` | 路由游标 `last_message_id` + 已处理 ID |
| `.admin-forward-state.json` | 转发游标 + 已转发配对 |
| `channel_directory.json` | WhatsApp 目标目录 |

### 4.3 内存态数据结构

- `AppConfig` / `AppPaths`（`config.py`）：`slots=True` dataclass，集中所有路径与运行期配置。
- `RewriteResult(language, message, used_fallback)`。
- `SendResult(success, chat_id, stdout, stderr, payload)`。
- `UserProfile(...)`：软画像字段集合。

## 5. 接口契约（HTTP API）

基址 `/api`。除下列公开端点外，其余需请求头 `x-session-token`。

**公开**
- `GET /api/health` → `{ok, profile, ts, login_enabled}`
- `POST /api/login` `{password}` → `{success, session_token, expires_in}`

**受保护**
- `POST /api/logout`
- `GET /api/dashboard` → `{stats, recent_conversations[:8]}`
- `GET /api/conversations` → 会话摘要列表（按 `last_timestamp` 倒序）
- `GET /api/conversations/{user_id}` → 单会话详情（含 `message_id`、`hidden`）
- `POST /api/reply` `{target, message, mode, preview_only}` → 预览或发送结果
- `GET /api/settings` → `{channels, aliases, profile, web_settings}`（已剔除 `auth`/`sessions`/`login_attempts`）
- `PUT /api/settings` `{channels, web_settings?, password?}` → 保存并回显 channels
- `POST /api/messages/hide` `{message_ids[]}` → `{hidden_message_ids, remote_delete_supported:false}`
- `POST /api/jobs/run` `{job}` → 触发 `router` / `forward` / `refresh-memory`

### 5.1 回复模式（mode）
- `direct`：原样发送（截断 500 字）。
- `smart`：记忆 + 语言/语气启发式 + 模型改写；输出 ≤ 48 字；失败回退到 `_fallback`。
- `translate`：向检测/偏好语言翻译；语言未知时保持原文不强译。

## 6. 关键流程

### 6.1 登录鉴权
1. `POST /api/login` 用 `verify_password`（PBKDF2-HMAC-SHA256 + salt，600k 迭代）校验。
2. 成功则生成 token（`secrets.token_urlsafe(24)`），写入 `web_settings.sessions[token]`，带 `expires_at`（默认 24h）。
3. 失败次数超阈值返回 429。
4. 中间件 `auth_guard` 放行 `/api/health`、`/api/login`，其余比对请求头 token。

### 6.2 管理员出站路由（`router run`）
读取 `state.db` 中 `last_message_id` 之后、来自管理员的 `user` 消息 → 解析命令 → 解析目标（别名/名称/ID 模糊匹配）→ 加载记忆 → `rewriter.rewrite` → `hermes send` → 回执给管理员渠道 → 保存游标。

### 6.3 转发（`forward run`）
扫描全部新消息，配对「用户消息 → 下一条助手回复」→ 生成含原文/中文近似/情绪概括的转发文本 → 发送到 `conversation_forward` 类渠道 → 记录已转发配对。

### 6.4 记忆刷新（`refresh-memory run`）
按 `user_id` 归集消息 → `profile.summarize_user_messages` 合成画像 → `render_md` 渲染 → 写 `user-memory-md/{name}__{id}.md`。

## 7. 安全模型（现状）

- 密码存储：PBKDF2-HMAC-SHA256 + 600k 迭代
- Session：多 token + TTL + 服务端失效
- 登录限流：IP 维度，5 次 / 5 分钟，超限 429
- CORS：显式 origin 白名单（http://127.0.0.1:38998 / 38999 / 5174，https://whats.future1.us）
- 默认密码仍可用 `CHAT_SYSTEM_BOOTSTRAP_PASSWORD` 覆盖（适合首启）

## 8. 部署形态

- 开发：后端 `python -m whatsapp_chat_system.cli --profile ... serve`；前端 `npm run dev`，Vite 代理 `/api`。
- 生产建议：`npm run build` 出静态资源，Caddy/Nginx 托管并反代 `/api`，后端仅监听 localhost，隧道置于单一前端源之前。
- Vercel 部署：`vercel.json` 只构建 `web/`，`/api/*` 重写至正式后端域名。

## 9. 优化项清单（Optimization Backlog）

按严重度排序。每项含：定位、问题、建议。优先级 **P0 = 应尽快修**，**P1 = 重要**，**P2 = 改进**。

### 9.1 安全（Security）

**S-1 [P0] 密码哈希强度不足** ✅ 已完成
- 状态：PBKDF2-HMAC-SHA256 + 600k 迭代；旧 `sha256` 格式仍可被 `verify_password` 兼容读取。

**S-2 [P0] CORS 通配 + 允许凭据的非法组合** ✅ 已完成
- 状态：显式 origin 白名单 + `allow_credentials=False`。

**S-3 [P0] Session token 无过期、无服务端失效** ✅ 已完成
- 状态：多 token + TTL + logout 服务端失效。

**S-4 [P1] 登录默认放行（fail-open）** ✅ 已完成
- 状态：`auth_required` 默认 true；缺配置时不再放行。

**S-5 [P1] `/api/login` 无速率限制** ✅ 已完成
- 状态：IP 维度的失败计数 + 429。

**S-6 [P1] 敏感默认值入库/入文档** ✅ 已完成
- 状态：默认密码可通过 `CHAT_SYSTEM_BOOTSTRAP_PASSWORD` 覆盖，避免写死到文档；README 只在 `Bootstrap password used in the current deployment` 段提示立即改密。

**S-7 [P2] token 存 localStorage（XSS 可窃取）**
- 定位：客户端将 token 写入 `localStorage`。
- 建议：条件允许时改用 `httpOnly` cookie + CSRF 防护。

### 9.2 正确性（Correctness）

**C-1 [P0] 消息级隐藏功能实际失效** ✅ 已完成
- 状态：`fetch_session_messages` SELECT `id AS message_id`；`web_api` 摘要与详情均以 `message_id` 为隐藏键。

**C-2 [P1] 配置的长度上限未真正生效** ✅ 已完成
- 状态：`rewriter._validate_output` 严格按 48 字硬上限；smart prompt 要求 ≤ 18 字或等效。

**C-3 [P1] 存在从未被读取的「死配置」** ✅ 已完成
- 状态：`allow_fallback` / `prefer_detected_language` 仍由 SettingsPanel 暴露并写入；后端在 `_fallback` 中按 preferred language 行为已生效。

**C-4 [P1] 回退改写内含硬编码演示语料** ✅ 已完成
- 状态：`_fallback` 不再硬编码逐句映射，按 preferred language 返回清洁版本。

**C-5 [P2] 优先级判定依赖脆弱字符串匹配**
- 定位：摘要侧 `priority` 仍依赖 markdown 文本中的 '不舒服' / 'emotionally vulnerable' 字符串。
- 建议：在记忆生成阶段输出结构化字段（如 YAML front-matter / JSON 侧车），后端读结构化字段而非全文 substring。

**C-6 [P1] 后端预读 origins 反复读盘**
- 定位：`web_api._load_origins` 每次请求都解析 `sessions.json`。
- 建议：加 TTL 缓存或基于 `last_modified` 的失效。

### 9.3 性能（Performance）

**P-1 [P1] 每次请求全表扫描 + 全量 JSON 重载，无缓存** ⚠ 进行中
- 现状：仍每次都全表 fetch session_messages。
- 建议：加带 TTL 的内存缓存或按 `last_timestamp` 增量。

**P-2 [P1] 前端每次写操作后全量 `loadBase()`** ✅ 已完成
- 状态：拆分为 `refreshWorkspace()` + `refreshSettings()`。

**P-3 [P2] 读路径产生写副作用** ✅ 已完成
- 状态：aliases 仅在变化时落盘；其余读路径只读。

**P-4 [P2] 无分页** ⚠ 进行中
- 现状：会话列表/消息历史全量返回。
- 建议：加分页或游标。

**P-5 [P2] 每查询新建 SQLite 连接**
- 定位：`storage.py:38-41`。
- 建议：可复用连接或连接池；只读路径可加只读打开模式。

**P-6 [P2] 前端未做请求缓存与并发合并**
- 建议：在 SWR 风格 hook 中合并重复请求。

### 9.4 可维护性 / 架构（Maintainability）

**M-1 [P1] origin/session 归集逻辑三处重复** ⚠ 进行中
- 现状：仍存在 `web_api.py`、`forwarder.py`、`memory_refresh.py` 各自建 session→origin 映射。
- 建议：抽到 `storage.py` 或新 `origins.py` 的单一函数。

**M-2 [P1] 测试依赖真实 profile 路径，不可自包含**
- 定位：`tests/test_web_api.py:6` 硬编码 `/root/.hermes/profiles/whatsapp-support`。
- 建议：用 `tmp_path` fixture 构造最小 profile（空 db + 默认设置），使测试无外部依赖、可在 CI 跑。

**M-3 [P2] 版本号不一致** ✅ 已完成
- 状态：单一 `0.6.0` 来源。

**M-4 [P2] 文档路径与仓库名不一致** ⚠ 进行中
- 现状：docs/DEPLOYMENT 仍用绝对路径示例。
- 建议：改为相对路径/环境变量并统一。

**M-5 [P2] 函数内局部 import**
- 定位：`web_api.py` / `rewriter.py` 中仍有少量局部 import。
- 建议：移到模块顶部。

**M-6 [P2] 前端单文件 550 行** ✅ 已完成
- 已拆分为 `web/src/components/`（TopBar / MobileNav / SettingsPanel / LoginScreen / ConversationList / ConversationDetail / ReplyPreview / MemorySummary / AliasPanel / StatCard）。
- 已新增 `web/src/api.js`（统一 fetch、token 注入、`res.ok` 校验、401 自动登出）、`web/src/format.js`、`web/src/i18n.js`、`web/src/settings.jsx`。
- 已支持 i18n（en/zh/th/lo）、深/浅色主题、移动端 tab 路由。

**M-7 [P2] Web 层缺乏结构化错误处理与日志**
- 后端任务有 `EventLogger`，但 HTTP 层异常直接冒泡。
- 建议：加统一异常处理与访问日志。

**M-8 [P2] i18n key 集中校验**
- 建议：测试期加一条脚本扫描组件，识别缺失 key 早于运行时。

### 9.5 优化项索引

| ID | 优先级 | 主题 | 状态 |
| --- | --- | --- | --- |
| S-1 | P0 | 密码哈希 | ✅ |
| S-2 | P0 | CORS | ✅ |
| S-3 | P0 | Session TTL | ✅ |
| S-4 | P1 | Fail-closed | ✅ |
| S-5 | P1 | 登录限流 | ✅ |
| S-6 | P1 | 默认密码 | ✅ |
| S-7 | P2 | HttpOnly cookie | TODO |
| C-1 | P0 | 隐藏功能 | ✅ |
| C-2 | P1 | 长度上限 | ✅ |
| C-3 | P1 | 死配置 | ✅ |
| C-4 | P1 | 回退硬编码 | ✅ |
| C-5 | P2 | 结构化画像 | TODO |
| C-6 | P1 | origins 缓存 | TODO |
| P-1 | P1 | 缓存 | TODO |
| P-2 | P1 | 写后全量 | ✅ |
| P-3 | P2 | 写副作用 | ✅ |
| P-4 | P2 | 分页 | TODO |
| P-5 | P2 | 连接池 | TODO |
| P-6 | P2 | SWR 合并 | TODO |
| M-1 | P1 | origins 抽函数 | TODO |
| M-2 | P1 | 测试自包含 | TODO |
| M-3 | P2 | 版本号 | ✅ |
| M-4 | P2 | 文档路径 | TODO |
| M-5 | P2 | 局部 import | TODO |
| M-6 | P2 | 前端拆组件 | ✅ |
| M-7 | P2 | HTTP 异常处理 | TODO |
| M-8 | P2 | i18n key 校验 | TODO |
| R-1 | P1 | 测试去外部依赖 | TODO |
| R-2 | P1 | 会话状态机 | TODO |
| R-3 | P2 | UI 自动刷新统一 | TODO |
| R-4 | P2 | 后台 hide 真正撤回 | TODO |
| R-5 | P2 | smart reply prompt 进一步人味化 | TODO |

| --- | --- | --- | --- |
| S-1 | P0 | 安全 | 密码换 KDF |
| S-2 | P0 | 安全 | 修正 CORS 通配+凭据 |
| S-3 | P0 | 安全 | token 过期与服务端失效 |
| C-1 | P0 | 正确性 | 修复消息隐藏失效 |
| S-4 | P1 | 安全 | 鉴权 fail-closed |
| S-5 | P1 | 安全 | 登录限流 |
| S-6 | P1 | 安全 | 敏感默认值出仓 |
| C-2 | P1 | 正确性 | 长度上限接线 |
| C-3 | P1 | 正确性 | 清理死配置 |
| C-4 | P1 | 正确性 | 移除硬编码语料 |
| P-1 | P1 | 性能 | 查询缓存/增量 |
| P-2 | P1 | 性能 | 前端局部刷新 ✅ |
| M-1 | P1 | 架构 | 抽取 origin 归集 |
| M-2 | P1 | 测试 | 自包含测试 |
| S-7/C-5/P-3~5/M-3~7 | P2 | 各类 | 见上文 |

---

## 10. 建议实施顺序（Roadmap）

1. **第一轮（安全+正确性 P0）**：S-1、S-2、S-3、C-1。
2. **第二轮（P1 硬化）**：S-4~S-6、C-2~C-4、M-2（先让测试自包含以支撑回归）。
3. **第三轮（性能与架构 P1/P2）**：P-1、P-2、M-1，再逐步清理 P2。

每轮完成后运行 `pytest -q` 与 `npm run build` 验证，并更新本文档「优化项索引」的状态。
