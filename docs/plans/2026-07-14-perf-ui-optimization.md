# 2026-07-14 性能与前端 UI 优化

## 关联 SDD

- SDD-P0-01（AI Provider 网络层可靠性/效率）
- SDD-P1-08（数据层性能，本轮先落连接池健康配置）
- SDD-P2-01（CSS 治理）
- SDD-P2-04（可访问性：focus-visible、reduced motion）
- SDD README 安全纪律：密码/凭据不得进入 Git

## 范围

### 后端性能

1. `ai/provider.py`：`WendingAIProvider.chat` 目前在未注入 session 时每次调用新建
   `requests.Session()` 并在调用后关闭——每次 AI 翻译/重写都重建 TCP+TLS 连接。
   改为 Provider 实例级持久 Session（懒加载、可注入、提供 `close()`），
   复用 urllib3 连接池，重试也复用同一连接。
2. `db/session.py`：`create_engine` 对非 SQLite 数据库（生产 PostgreSQL）
   增加 `pool_pre_ping=True`、`pool_recycle=1800`、显式 `pool_size/max_overflow`，
   防止长连接被网络设备掐断后出现间歇性连接错误。SQLite 行为不变。

### 前端性能

3. `TabBar.jsx`、`ChatList.jsx` 以 `React.memo` 包装：App 层轮询已保证
   数组引用稳定（chatStabilityLayout 回归），memo 可避免每次工作台
   轮询/无关 state 变化时整列表重渲染。

### 前端 UI（SDD-P2-04 可访问性）

4. `styles.css` 增加：
   - 全局 `:focus-visible` 可见焦点环（键盘导航可用，鼠标点击不干扰）；
   - `@media (prefers-reduced-motion: reduce)` 关闭过渡/动画。

### 安全与卫生

5. `docs/CHANGELOG_AGENT.md` 移除 2026-07-14 hotfix 记录中的明文生产密码
   （SDD 总纲明令禁止密码入 Git；密码本体需另行在生产轮换）。
6. 删除误提交的 `web/src/i18n.js.bak`；`.gitignore` 增加 `*.bak`。

## TDD

- RED：
  - `tests/test_ai_provider.py`：连续两次 `chat` 必须复用同一 Session、
    调用后不得关闭持久 Session；
  - `tests/test_db_session.py`：非 SQLite URL 的 engine kwargs 含
    `pool_pre_ping`；SQLite engine 不受影响；
  - `web/tests/uiPolishAccessibility.test.js`：静态断言 memo 化、
    focus-visible 与 prefers-reduced-motion 规则、`.bak` 不存在。
- GREEN：最小实现上述改动。
- 门禁：`pytest -q` 全量、`node --test web/tests/*.test.js`、
  `npm test --prefix bridge`、`vite build`、changed-files ruff check/format。

## 明确不做

- 不动 Legacy `web_api.py` / `messaging.py`（Hermes 路径冻结）；
- 不改 Bridge V2（已有 Session 复用与安全门禁）；
- 翻译 SSE/WebSocket 迁移为独立后续任务（SDD-P1-05 剩余验收）。
