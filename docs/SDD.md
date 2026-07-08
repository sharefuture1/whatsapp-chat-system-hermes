# 软件设计文档（SDD）— Hermes WhatsApp 运营控制台

> Software Design Document
> 项目：`hermes-whatsapp-ops-console`（包名 `whatsapp_chat_system`）
> 版本：0.5.0（API）/ 0.2.0（打包）— 见「优化项 O-13」
> 状态：内部私有运营工具

---

## 1. 文档目的与范围

本文档描述该项目的整体设计：系统边界、模块职责、数据模型、接口契约、关键流程与安全模型，并在第 9 节给出一份**按优先级排序、可执行的优化清单**（含代码定位与建议方案）。

适用读者：维护该控制台的开发/运营人员，以及后续接手的工程师。

不在范围内：Hermes 本体网关的实现、WhatsApp 协议细节、模型服务（LLM）的内部实现。

---

## 2. 系统概览

该系统是叠加在既有 **Hermes WhatsApp 支持工作区** 之上的运营控制台。运营人员通过一个受密码保护的 Web 控制台查看对话、生成/翻译/直发回复，并把用户与助手的对话转发到管理员渠道。

三层结构：

| 层 | 组成 | 职责 |
| --- | --- | --- |
| Hermes 运行时 | WhatsApp 网关、`state.db`、`hermes send` 命令 | 消息收发与持久化（外部系统） |
| Python 应用层 | FastAPI + CLI 后台任务 | 读取会话状态、生成用户画像、路由/改写/转发、暴露受保护 API |
| React 控制台 | `web/src/App.jsx` | 登录、会话浏览、回复预览/发送、设置管理 |

```
WhatsApp 用户 ──► Hermes 网关 ──► state.db ──┐
                                             ├─► Python 应用层 (FastAPI/CLI) ─► React 控制台
管理员渠道 ◄── hermes send ◄── 应用层 ───────┘
```

---

## 3. 组件设计

### 3.1 后端模块（`src/whatsapp_chat_system/`）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `web_api.py` | 324 | FastAPI 应用：鉴权中间件、仪表盘、会话、回复预览/发送、设置、本地隐藏、任务触发 |
| `router.py` | 217 | 管理员出站路由：按别名/名称/ID 解析目标，加载记忆，选择改写策略，经 Hermes 发送 |
| `rewriter.py` | 170 | 智能改写 / 纯翻译 / 回退控制 / 输出校验与长度控制 |
| `profile.py` | 203 | 从用户消息合成软画像（语言、语气、话题、敏感点、回复偏好），渲染为 Markdown |
| `config.py` | 151 | Profile 感知配置：路径、密码记录、Web 设置、默认渠道 |
| `messaging.py` | 123 | Hermes `send` 封装、目标解析、别名生成 |
| `forwarder.py` | 103 | 把「用户消息 → 助手回复」成对转发给管理员渠道 |
| `memory_refresh.py` | 82 | 从 `state.db` 转录历史生成每用户 Markdown 记忆文件 |
| `storage.py` | 81 | SQLite 访问助手 + JSON 事件日志 |
| `language.py` | 76 | 语言/语气启发式（脚本区间检测、近似翻译、情绪概括） |
| `cli.py` | 45 | 子命令入口：`router` / `forward` / `refresh-memory` / `serve` |
| `parsing.py` | 35 | 管理员中文命令解析（`发给 X：内容`） |
| `constants.py` | 12 | 默认 profile、管理员 ID、管理员目标 |

### 3.2 前端（`web/`）

单文件 React 应用 `App.jsx`（550 行），Vite 开发服务器把 `/api` 代理到后端。组件：`LoginScreen`、`TopBar`、`SettingsPanel`、`ConversationList`、`ConversationDetail`、`ReplyPreview`、`MemorySummary`、`AliasPanel`。

---

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
| `web-settings.json` | 鉴权记录、reply/ui/message_ops 策略、`session_token`、`hidden_message_ids` |
| `user-aliases.json` | 联系人数字别名 |
| `user-memory-md/*.md` | 生成的每用户画像（命名 `{safe_name}__{user_id}.md`） |
| `.admin-command-router-state.json` | 路由游标 `last_message_id` + 已处理 ID |
| `.admin-forward-state.json` | 转发游标 + 已转发配对 |
| `channel_directory.json` | WhatsApp 目标目录 |

### 4.3 内存态数据结构

- `AppConfig` / `AppPaths`（`config.py`）：`slots=True` dataclass，集中所有路径与运行期配置。
- `RewriteResult(language, message, used_fallback)`。
- `SendResult(success, chat_id, stdout, stderr, payload)`。
- `UserProfile(...)`：软画像字段集合。

---

## 5. 接口契约（HTTP API）

基址 `/api`。除下列公开端点外，其余需请求头 `x-session-token`。

**公开**
- `GET /api/health` → `{ok, profile, ts, login_enabled}`
- `POST /api/login` `{password}` → `{success, session_token}`（401 表示密码错误）

**受保护**
- `GET /api/dashboard` → `{stats, recent_conversations[:8]}`
- `GET /api/conversations` → 会话摘要列表（按 `last_timestamp` 倒序）
- `GET /api/conversations/{user_id}` → 单会话详情（消息、记忆、画像摘要），无记录返回 404
- `POST /api/reply` `{target, message, mode, preview_only}` → 预览或发送结果
- `GET /api/settings` → `{channels, aliases, profile, web_settings}`（已剔除 `auth`/`session_token`）
- `PUT /api/settings` `{channels, web_settings?, password?}` → 保存并回显 channels
- `POST /api/messages/hide` `{message_ids[]}` → `{hidden_message_ids, remote_delete_supported:false}`
- `POST /api/jobs/run` `{job}` → 触发 `router` / `forward` / `refresh-memory`

### 5.1 回复模式（mode）
- `direct`：原样发送（截断 500 字）。
- `smart`：记忆 + 语言/语气启发式 + 模型改写，失败回退到 `rewriter._fallback`。
- `translate`：向检测/偏好语言翻译；语言未知时保持原文不强译。

---

## 6. 关键流程

### 6.1 登录鉴权
1. `POST /api/login` 用 `verify_password`（salt + SHA-256，`secrets.compare_digest`）校验。
2. 成功则 `secrets.token_urlsafe(24)` 生成 token，写入 `web-settings.json` 的 `session_token`。
3. 中间件 `auth_guard` 放行 `/api/health`、`/api/login`，其余比对请求头 token。

### 6.2 管理员出站路由（`router run`）
读取 `state.db` 中 `last_message_id` 之后、来自管理员的 `user` 消息 → 解析命令 → 解析目标（别名/名称/ID 模糊匹配）→ 加载记忆 → `rewriter.rewrite` → `hermes send` → 回执给管理员渠道 → 保存游标。

### 6.3 转发（`forward run`）
扫描全部新消息，配对「用户消息 → 下一条助手回复」→ 生成含原文/中文近似/情绪概括的转发文本 → 发送到 `conversation_forward` 类渠道 → 记录已转发配对。

### 6.4 记忆刷新（`refresh-memory run`）
按 `user_id` 归集消息 → `profile.summarize_user_messages` 合成画像 → `render_md` 渲染 → 写 `user-memory-md/{name}__{id}.md`。

---

## 7. 安全模型（现状）

- 应用层密码登录：salt + SHA-256 存于 `web-settings.json`。
- 登录签发全局单一 `session_token`，请求头 `x-session-token` 携带。
- 未配置 `auth` 时**默认放行**（fail-open）。

现状适合私有内部工具，但不满足企业级鉴权。已知缺口见第 9 节 S-1 ~ S-6。

---

## 8. 部署形态

- 开发：后端 `python -m whatsapp_chat_system.cli --profile ... serve`；前端 `npm run dev`，Vite 代理 `/api`。
- 生产建议：`npm run build` 出静态资源，Caddy/Nginx 托管并反代 `/api`，后端仅监听 localhost，隧道置于单一前端源之前。

---

## 9. 优化项清单（Optimization Backlog）

按严重度排序。每项含：定位、问题、建议。优先级 **P0 = 应尽快修**，**P1 = 重要**，**P2 = 改进**。

### 9.1 安全（Security）

**S-1 [P0] 密码哈希强度不足**
- 定位：`config.py:119-131` `build_password_record` / `verify_password`。
- 问题：使用一次 SHA-256（+salt），非慢速 KDF，离线爆破成本极低。
- 建议：改用 `bcrypt` / `argon2-cffi` / 至少 `hashlib.pbkdf2_hmac`（高迭代）。保留 salt，迁移时兼容旧记录格式。

**S-2 [P0] CORS 通配 + 允许凭据的非法组合**
- 定位：`web_api.py:154-160`，`allow_origins=['*']` 且 `allow_credentials=True`。
- 问题：该组合被浏览器视为无效，也削弱同源保护。
- 建议：改为显式白名单 origin，或在纯 token 鉴权下关闭 `allow_credentials`。

**S-3 [P0] Session token 无过期、无服务端失效**
- 定位：`web_api.py:174-183` login；`_is_authenticated:137-143`。
- 问题：token 永不过期；登出仅前端清 localStorage，服务端仍有效；单一全局 token（新登录顶掉旧登录，无法多会话）。
- 建议：token 带签发时间/TTL，服务端保存多 token 集合并在登出时移除；可用 `itsdangerous` 或 JWT。

**S-4 [P1] 登录默认放行（fail-open）**
- 定位：`_is_authenticated:140-141`，`if not stored: return True`。
- 问题：一旦 `auth` 缺失，全部受保护端点开放。
- 建议：改为 fail-closed，缺配置时拒绝并记录告警。

**S-5 [P1] `/api/login` 无速率限制**
- 定位：`web_api.py:174`。
- 建议：加基于 IP 的登录节流（如 `slowapi`）或失败计数锁定。

**S-6 [P1] 敏感默认值入库/入文档**
- 定位：`config.py:98` 默认密码 `test?9`；`constants.py:6-11` 真实手机号/管理员 ID；`README.md` 明文密码。
- 建议：默认密码改为首启随机生成并要求改密；管理员 ID/target 移到环境变量或 profile 配置，不写死进仓库；文档移除明文口令。

**S-7 [P2] token 存 localStorage（XSS 可窃取）**
- 定位：`App.jsx:359,387`。
- 建议：条件允许时改用 `httpOnly` cookie + CSRF 防护。

### 9.2 正确性（Correctness）

**C-1 [P0] 消息级隐藏功能实际失效**
- 定位：`web_api.py:216-223` 使用 `row.get('message_id')`/`row.get('id')`，但 `storage.py:74-81 fetch_session_messages` 的 SELECT **不含 `id`**，且返回的是 `sqlite3.Row`（无 `.get` 方法）。因 `isinstance(row, dict)` 恒为 False，`message_id` 恒为 `None`、`hidden` 恒为 `False`。
- 连锁：前端 `App.jsx:297,484` 因 `message_id` 为 None，退化成用 `timestamp` 作 id 提交隐藏；而摘要侧 `web_api.py:107` 用 `row['session_id'] not in hidden` 与「时间戳集合」比较，永不命中。**结果：单条隐藏与「隐藏最新 N 条」在 UI 上都不会真正生效。**
- 建议：`fetch_session_messages` 增加 `m.id AS message_id`；统一以 `message_id` 作为隐藏键；摘要侧 `last_message` 的隐藏判断改为按 `message_id` 而非 `session_id`。补一条针对隐藏流程的测试。

**C-2 [P1] 配置的长度上限未真正生效**
- 定位：`router.py:115-117` 用 `smart_max_length*2` / `translate_max_length*2` 截断输入，但 `rewriter._validate_output:123` 硬编码 `len(msg) > 80` 校验输出。
- 问题：UI 上调 `smart_max_length` 不影响输出实际上限。
- 建议：把输出上限也由配置驱动（如 `max(smart_max_length, translate_max_length)` 或独立字段）。

**C-3 [P1] 存在从未被读取的「死配置」**
- 定位：`config.py:105-106` 的 `allow_fallback`、`prefer_detected_language` 在后端逻辑中无任何读取点。
- 建议：要么接线生效（fallback 开关应控制 `rewriter.rewrite` 是否回退；prefer_detected_language 应影响 `detect_preferred_language`），要么从设置中移除以免误导。

**C-4 [P1] 回退改写内含硬编码演示语料**
- 定位：`rewriter.py:150-170` `_fallback` 针对具体中文句子（如「你去那边旅游吗」）返回固定泰/老译文。
- 问题：测试夹具泄漏进生产逻辑，对真实输入几乎无覆盖，且难维护。
- 建议：移除逐句映射，回退统一走「简单前缀 + 原文」或最小规则；把这些样例挪到测试文件里。

**C-5 [P2] 优先级判定依赖脆弱字符串匹配**
- 定位：`web_api.py:118`（`'不舒服' in memory_markdown or 'emotionally vulnerable' in ...`）、`:234-235` 语言提示同理。
- 建议：在记忆生成阶段输出结构化字段（如 YAML front-matter / JSON 侧车），后端读结构化字段而非全文 substring。

### 9.3 性能（Performance）

**P-1 [P1] 每次请求全表扫描 + 全量 JSON 重载，无缓存**
- 定位：`storage.py:74-81 fetch_session_messages`（拉取全部 whatsapp 消息）被 `dashboard`、`conversations`、`conversations/{id}` 反复调用；`_load_origins` 每次重读 `sessions.json`。
- 建议：加带 TTL 的内存缓存或按 `last_timestamp` 增量；`conversations/{id}` 用 `WHERE session_id IN (...)` 只取该用户消息，而非全表过滤。

**P-2 [P1] 前端每次写操作后全量 `loadBase()`** ✅ 已完成
- 定位：`App.jsx`，回复/隐藏/任务后都重拉 dashboard+conversations+settings。
- 处理：拆分为 `refreshWorkspace()`（dashboard+conversations+当前详情）与 `refreshSettings()`；隐藏消息只刷新会话详情；保存设置只刷新设置；health 只在启动时拉取。

**P-3 [P2] 读路径产生写副作用**
- 定位：`messaging.py:72-95 refresh_aliases` 每次都 `save_json` 写别名文件，即使由只读的 `prepare_reply` 触发。
- 建议：仅在别名实际变化时落盘。

**P-4 [P2] 无分页**
- 会话列表与消息历史全量返回。数据增长后应加分页/游标。

**P-5 [P2] 每查询新建 SQLite 连接**
- 定位：`storage.py:38-41`。可复用连接或用连接池；只读路径可加只读打开模式。

### 9.4 可维护性 / 架构（Maintainability）

**M-1 [P1] origin/session 归集逻辑三处重复**
- 定位：`web_api.py:50-57`、`forwarder.py:39-44`、`memory_refresh.py:26-31` 各自实现「从 sessions.json 建 session→origin 映射」。
- 建议：抽到 `storage.py` 或新 `origins.py` 的单一函数。

**M-2 [P1] 测试依赖真实 profile 路径，不可自包含**
- 定位：`tests/test_web_api.py:6` 硬编码 `/root/.hermes/profiles/whatsapp-support`。
- 建议：用 `tmp_path` fixture 构造最小 profile（空 db + 默认设置），使测试无外部依赖、可在 CI 跑。

**M-3 [P2] 版本号不一致**
- `pyproject.toml` `0.2.0` vs `web_api.py:153` `0.5.0`。统一为单一来源。

**M-4 [P2] 文档路径与仓库名不一致**
- `README.md` / `docs/DEPLOYMENT.md` 反复用 `/root/whatsapp-chat-system`，与仓库 `hermes-whatsapp-ops-console` 不符；`cli.py:16` 默认 profile 也是 `/root/...` 硬编码。建议改为相对路径/环境变量并统一。

**M-5 [P2] 函数内局部 import**
- `web_api.py:179 import secrets`、`rewriter.py:118/151 import re`。移到模块顶部。

**M-6 [P2] 前端单文件 550 行** ✅ 已完成
- 已拆分为 `web/src/components/`（LoginScreen/TopBar/SettingsPanel/ConversationList/ConversationDetail/ReplyPreview/MemorySummary/AliasPanel/StatCard），并新增 `api.js`（统一 fetch、token 注入、`res.ok` 校验、401 自动登出）与 `format.js`。附带修复：token 不再经 settings 对象透传给预览请求；写操作错误不再被静默吞掉，改为可关闭的错误横幅；登录框占位符不再泄漏默认密码；实现了此前从未生效的 `ui.auto_refresh_seconds` 自动刷新；登录支持回车提交。

**M-7 [P2] Web 层缺乏结构化错误处理与日志**
- 后端任务有 `EventLogger`，但 HTTP 层异常直接冒泡。建议加统一异常处理与访问日志。

### 9.5 优化项索引

| ID | 优先级 | 主题 | 一句话 |
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
