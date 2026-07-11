# 2026-07-11 前端轮询与翻译调度性能优化计划

## Objective

在不改变现有聊天业务语义的前提下，降低后台轮询、慢网重叠请求、自动翻译并发和发送后重复刷新带来的网络与渲染压力。

## 关联规格

- `NFR-PERF-002`：账号状态和新消息使用可控增量轮询。
- `NFR-REL-002`：外部请求具有明确取消/超时边界。
- `SDD-P1-05`：翻译异步化的迁移期前端并发治理。
- `SDD-P2-06`：浏览器主链路性能回归。

## Task 1：轮询单飞与后台暂停

**Files**
- Modify: `web/src/App.jsx`
- Modify: `web/src/accounts/useAccountsController.js`
- Test: `web/tests/performanceScheduling.test.js`

**RED**
- Workspace 不得继续使用可重叠的 `setInterval`。
- 账号轮询不得继续使用可重叠的 `setInterval`。
- 页面 hidden 时不得调度常规刷新；visible 后只恢复一次。
- 同一轮刷新只能有一个 in-flight promise。

**GREEN**
- 使用完成后递归 `setTimeout`。
- 增加 single-flight promise ref。
- 监听 `visibilitychange`，隐藏时暂停、恢复时立即单次刷新。

## Task 2：自动翻译单 worker

**Files**
- Modify: `web/src/components/ChatPane.jsx`
- Test: `web/tests/performanceScheduling.test.js`

**RED**
- 自动翻译 effect 不得因每条译文回填而创建多个并行循环。
- 同一时刻只允许一个前端翻译 worker；切换会话后旧 worker 停止继续排队。

**GREEN**
- 使用 worker-running ref 和 generation ref。
- 每轮只处理限定消息，串行执行；完成后由最新消息状态决定是否继续。

## Task 3：发送后刷新去重

**Files**
- Modify: `web/src/App.jsx`
- Modify: `web/src/components/ChatPane.jsx`
- Test: `web/tests/performanceScheduling.test.js`

**RED**
- 发送成功不得同时触发完整 Workspace 刷新和 450ms 当前聊天全量刷新。

**GREEN**
- 保留乐观消息真实 ID 合并。
- 仅调度一次轻量 Workspace 刷新；移除 ChatPane 裸定时全量刷新。

## Task 4：门禁与生产验收

- `node --test web/tests/*.test.js`
- `npm --prefix web run build`
- `./.venv/bin/pytest -q`
- 390×844 与 1440×900 浏览器检查
- 生产 health、资源 hash、控制台与 15 秒请求采样
