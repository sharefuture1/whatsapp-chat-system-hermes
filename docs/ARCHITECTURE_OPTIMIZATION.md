# WhatsApp Chat System — 架构深度分析与优化全景规划

> **文档状态**：Active / Architecture Blueprint  
> **更新时间**：2026-09-06  
> **关联规格**：[`docs/sdd/README.md`](./sdd/README.md), [`docs/sdd/02-system-architecture.md`](./sdd/02-system-architecture.md), [`docs/sdd/09-performance-and-realtime.md`](./sdd/09-performance-and-realtime.md)

---

## 1. 项目全景与定位

WhatsApp Chat System 是面向出海与跨国客户关系管理的企业级多账号工作台。系统核心功能包含：
- **多账号 WhatsApp 会话收发与状态管理**（基于 Node.js / Baileys 6.7.22 桥接）；
- **智能化辅助与受控人设**（深度集成问鼎 AI `gpt-5.3-codex-spark` 与老挝语 LaoTalk 翻译保底）；
- **微信级跨端工作台交互**（React 18 + 微信式设计系统 + Tauri 2 跨平台桌面客户端）；
- **关系智能画像 CRM 数据模型**（支持 Claim 事实推理、人工锁定与 Snapshot 发布机制）。

---

## 2. 现有架构深度解构与瓶颈分析

当前项目正处于从过渡期 Legacy 架构向 Standalone 2.0 架构演进的收官阶段。

### 2.1 子系统解构与实现评估

| 模块 | 当前实现路径 | 技术亮点 | 核心痛点 / 架构隐患 |
| :--- | :--- | :--- | :--- |
| **控制面 API** | `standalone_api.py` + FastAPI | 路由规范模块化 (`/api/v1/*`)，CORS 严格白名单，支持 Session Token 与 RBAC | 历史遗留单体 `web_api.py` (81KB) 仍存留；后台任务直接以 `asyncio.to_thread` 跑在 FastAPI lifespan 内部 |
| **后台 Worker** | In-Process 协程循环 | Outbox 模式避免发信卡死；AutoReply 严格短事务解耦 (PERF-006) | 5 个 Worker 与 Web API 混跑单点故障，无法独立横向扩容，无任务背压机制 |
| **WhatsApp 桥接** | `bridge/` (Node.js 20 + Baileys) | `FileSpool` 事务日志落盘，每账号 `0700` 目录隔离，事件单调递增 sequence | 单 Node 进程承载所有账号 socket，多账号高并发可能引发 V8 OOM 或事件循环卡死 |
| **实时通信机制** | HTTP 轮询 (3~5s) | single-flight 防重叠，Tab 隐藏暂停轮询，引用稳定不重刷 (PERF-008) | 轮询对 DB 和网络开销巨大；新消息存在 3~5s 延迟；SSE (RT-001) 尚未接通客户端 |
| **前端状态层** | React 18 SPA + Vite | 微信端到端 UX，移动/桌面响应式，CSS 变量设计令牌，暗黑模式与四国 i18n | `App.jsx` (35KB) 与 `ChatPane.jsx` (51KB) 状态极重，缺少集中式状态管理 (如 Zustand/Query) |
| **桌面客户端** | Tauri 2 (`src-tauri/`) | 轻量薄客户端，内存缓存会话，防 Token 泄漏，GitHub Actions 全平台自动化构建 | 需持续对齐 WebView2 / WebKit 与原生浏览器的 CORS / CSP 行为 |

---

## 3. 架构痛点矩阵 (Risk Matrix)

```
高严重度 │ [P0] 进程内混跑后台 Worker      [P0] 依赖短轮询缺少 SSE 推送
         │
中严重度 │ [P1] Baileys 单进程多账号隔离不足 [P1] 前端超大组件状态耦合
         │
低严重度 │ [P2] 双轨 Legacy 代码债务        [P2] 媒体文件流式传输未接入
         └────────────────────────────────────────────────────────
           易于实施                                      复杂度高
```

1. **[P0] 实时性瓶颈**：当前轮询模式（3~5s/次）在高并发坐席场景下会导致大量的空请求和数据库开销，无法实现即时通讯的秒级直达。
2. **[P0] 单点进程脆弱性**：API 进程内混跑 Worker，一旦某次异步任务内存暴涨或死锁，将直接造成 Web 控制台服务不可用。
3. **[P1] Bridge 进程崩溃蔓延**：单个账号因 WhatsApp 协议突变或未捕获解密异常导致 Node.js 崩溃时，会拖累同进程下的其余全部账号。
4. **[P1] 前端维护成本高**：`ChatPane.jsx` 聚集了消息渲染、翻译调度、草稿保存、自动增高、人设选择等几十项职责，缺乏状态抽象。

---

## 4. 下一代目标架构蓝图 (Target Architecture 3.0)

目标是将系统彻底拆分为**无状态 API 控制面**、**独立事件分发总线**、**分布式任务 Worker** 与**沙箱化通信桥接集群**：

```mermaid
graph TB
    subgraph ClientLayer ["客户端接入层"]
        WebSPA["React 18 SPA"]
        DesktopTauri["Tauri 2 薄客户端"]
    end

    subgraph EdgeLayer ["反向代理与网关"]
        ReverseProxy["Nginx / Caddy 边缘反代"]
    end

    subgraph APILayer ["无状态控制面 (Stateless API)"]
        FastAPI_API["FastAPI Control Plane (:8792)<br/>仅响应 REST 接口与鉴权"]
        FastAPI_SSE["SSE Push Gateway (:8792/api/v1/events/stream)<br/>长连接实时推送"]
    end

    subgraph EventAndStorage ["数据与事件总线"]
        Postgres["PostgreSQL 16+<br/>主业务表 / Outbox / Analysis Jobs"]
        RedisBus["Redis 7.x (Pub/Sub + 分布式锁 + 任务队列)"]
    end

    subgraph WorkerCluster ["独立 Worker 进程组 (systemd/容器)"]
        OutboxWorker["whatsapp-chat-worker<br/>(Outbox 发信 / 状态对账)"]
        AIWorker["whatsapp-ai-worker<br/>(自动回复 / 批量翻译 / 关系画像)"]
    end

    subgraph BridgeCluster ["高可用桥接集群 (:3100)"]
        BridgeMaster["Bridge Master 调度进程"]
        AccountFork1["Worker Fork 1 (Account 1)"]
        AccountFork2["Worker Fork 2 (Account 2)"]
    end

    ClientLayer --> ReverseProxy
    ReverseProxy -->|REST API| FastAPI_API
    ReverseProxy -->|SSE Stream| FastAPI_SSE
    FastAPI_API --> Postgres
    FastAPI_API --> RedisBus
    FastAPI_SSE <--|Pub/Sub 广播| RedisBus
    WorkerCluster -->|SKIP LOCKED 消费| Postgres
    WorkerCluster -->|本地 Internal Token| BridgeMaster
    BridgeMaster --> AccountFork1 & AccountFork2
```

---

## 5. 核心专项优化落地指南

### 专项 1：SSE 实时事件通道落地 (终结 HTTP 短轮询)

- **核心目标**：实现 `GET /api/v1/events/stream`，消息延迟从 3~5 秒缩减至 200 毫秒以内。
- **实施要点**：
  1. 后端基于 `FastAPI.responses.StreamingResponse` 建立异步队列分发。
  2. 支持 HTTP 标头 `Last-Event-ID`，在网络重连时从内存环形缓冲区自动补发断线期间的事件。
  3. 前端基于 `EventSource` 精准分发：
     - `message.created`：直接向对应会话增量推入消息气泡；
     - `account.status`：仅更新该账号的在线 Badge，不全量重拉列表；
     - SSE 连接保持健康时，前端轮询自动降级为 60 秒一次的弱同步兜底。

### 专项 2：FastAPI 进程与 Worker 进程彻底解耦

- **核心目标**：将后台 Worker 移出 Web API lifespan，实现控制面纯粹无状态化。
- **实施要点**：
  1. 在 `whatsapp_chat_system.cli` 中增加 `worker` 子命令：
     ```bash
     python -m whatsapp_chat_system.cli worker --mode outbox,auto-reply
     ```
  2. 配置独立 systemd 服务单元 `deploy/systemd/whatsapp-chat-worker.service`。
  3. 任务调度依托 PostgreSQL `FOR UPDATE SKIP LOCKED` 语法，天然支持多 Worker 进程安全并发争抢任务，避免并发重复发信。

### 专项 3：Bridge V2 多账号沙箱化与内存/流媒体治理

- **核心目标**：杜绝单账号崩溃引发多账号雪崩，控制 V8 内存占用。
- **实施要点**：
  1. 使用 Node.js `child_process.fork()` 为每个活跃账号分配独立子进程。
  2. 主进程仅维护路由反代和心跳监控，单个子进程因 Baileys 异常退出时执行指数退避重启，其余账号连接不受干扰。
  3. 图片/语音/视频消息流式 Pipe 写入本地磁盘或对象存储，禁止在 Node.js 内存 Buffer 中全量缓存多媒体数据。

### 专项 4：前端模块化拆分与 Zustand 领域状态机

- **核心目标**：解耦 `App.jsx` 和 `ChatPane.jsx`，提升渲染性能与可维护性。
- **实施要点**：
  1. 引入轻量状态管理（如 `zustand`），将全局账号筛选、激活会话键、用户信息等提升至独立 Store。
  2. 拆解 `ChatPane.jsx` 为：
     - `ChatHeader`（会话信息、人设选择器、详情抽屉）
     - `ChatMessageList`（虚拟滚动容器、气泡渲染、译文展示，`React.memo` 隔离）
     - `ChatComposer`（自动增高输入框、直发/AI智能/翻译模式切换、Emoji工具栏）

### 专项 5：Legacy 彻底清退（MIG-8 收官）

- **核心目标**：清退 80KB+ 遗留死代码与历史 Hermes 配置文件。
- **实施要点**：
  1. 将生产网关流量 100% 切换至 `standalone_api.py`。
  2. 移除 `src/whatsapp_chat_system/web_api.py` 及单账号 Bridge 3000 相关逻辑。
  3. 全量依赖 PostgreSQL + Alembic 迁移作为系统单一真源。

---

## 6. 推进阶段与建议排期

```text
第一阶段：实时性飞跃与连接优化 (1~2 周)
  ├── [1] 实现 GET /api/v1/events/stream (SSE) 端点与心跳机制
  ├── [2] 前端接入 EventSource 实现增量精准推送与轮询降级
  └── [3] 验证多端同步秒级延迟与零丢包

第二阶段：系统服务解耦与弹性架构 (2 周)
  ├── [1] 剥离独立 worker 进程 (whatsapp-chat-worker.service)
  ├── [2] 数据库接入 SKIP LOCKED 任务抢占
  └── [3] 部署监控 metrics (Prometheus/健康检查告警)

第三阶段：前端组件化与 Legacy 全面收尾 (2 周)
  ├── [1] 拆解 ChatPane.jsx 与 App.jsx
  ├── [2] 清理遗留 web_api.py 与 3000 端口逻辑
  └── [3] 完成生产环境 MIG-8 正式切流
```
