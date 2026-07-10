# SDD 强制开发流程

## 1. 每次任务的固定顺序

### Step 1：读取规格

必须读取：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/sdd/README.md`
4. 与任务相关的 SDD 文件
5. `docs/PROJECT_MEMORY.md`
6. `docs/TODO_AGENT.md`
7. `docs/DECISIONS.md`
8. `docs/CHANGELOG_AGENT.md`

### Step 2：识别需求 ID

每项开发必须绑定至少一个 `FR/NFR/SEC/DATA/API/UX/MIG/QA` ID。

若没有对应需求：

1. 先补 SDD；
2. 写清状态和验收标准；
3. 再开始代码。

### Step 3：写实施任务

复杂改动必须在 `docs/plans/YYYY-MM-DD-*.md` 建立实施计划，包含：

- Objective；
- 精确文件路径；
- 失败测试；
- 运行命令和预期失败；
- 最小实现；
- 运行命令和预期通过；
- 单任务提交；
- 对应 SDD ID。

### Step 4：TDD

代码任务固定执行：

```text
RED：先写失败测试并确认确实失败
GREEN：做最小实现并确认测试通过
REFACTOR：清理实现，保持测试通过
```

禁止先写实现再补一个只会通过的测试。

### Step 5：双阶段审查

复杂任务使用 subagent-driven-development：

1. 规格符合性审查：是否满足 SDD，不多做、不漏做；
2. 代码质量审查：正确性、可靠性、安全、可维护性和测试质量。

规格审查未通过，不进入代码质量审查。

### Step 6：质量门禁

按改动范围执行最小相关测试，并在提交/部署前执行全量门禁。

### Step 7：更新文档

完成后必须同步：

- SDD 需求状态；
- `docs/CHANGELOG_AGENT.md`；
- `docs/PROJECT_MEMORY.md`；
- `docs/TODO_AGENT.md`；
- 有架构决策时更新 `docs/DECISIONS.md`。

### Step 8：真实验证

必须验证运行链路，而不只验证代码编译：

- API HTTP 状态和响应；
- 前端静态资源；
- Bridge/Worker 状态；
- 日志无异常；
- 用户场景真实可操作。

## 2. 任务模板

```markdown
### Task N: [标题] [FR-XXX]

**Objective:** ...

**Files:**
- Create: `...`
- Modify: `...`
- Test: `...`

**Acceptance:**
- [ ] ...

**Step 1: Write failing test**
...

**Step 2: Verify RED**
Run: `...`
Expected: FAIL because ...

**Step 3: Minimal implementation**
...

**Step 4: Verify GREEN**
Run: `...`
Expected: PASS

**Step 5: Refactor and full relevant tests**
...

**Step 6: Commit**
`git commit -m "feat(scope): ... [FR-XXX]"`
```

## 3. 质量门禁

### 3.1 后端

```bash
cd /home/young11/workspace/whatsapp-chat-system-hermes
./.venv/bin/pytest -q
python -m py_compile src/whatsapp_chat_system/*.py
```

新增数据库后补充：

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

### 3.2 前端

```bash
cd /home/young11/workspace/whatsapp-chat-system-hermes/web
npm run build
node --test tests/chatSync.test.js
```

新增 Playwright 后：

```bash
npm run test:e2e
```

### 3.3 Bridge

```bash
cd /home/young11/workspace/whatsapp-chat-system-hermes/bridge
npm test
npm run lint
```

### 3.4 文档与 Git

```bash
git diff --check
git status --short
```

检查：

- SDD 链接存在；
- 需求 ID 可追溯；
- 无 token/key/password/session 文件；
- 不提交构建缓存和运行态凭据。

### 3.5 部署门禁

Legacy 当前门禁：

1. `npm run build`；
2. `pytest -q`；
3. `node --test tests/chatSync.test.js`；
4. `/api/health` 200；
5. 首页和实际 hash JS/CSS 200；
6. 8792 只有预期服务实例；
7. 日志无启动异常。

Standalone 增加：

1. API live/ready；
2. Bridge live/ready；
3. Worker heartbeat；
4. 数据库迁移状态 head；
5. Redis/队列可用；
6. 每个 WhatsApp 账号状态可查询；
7. 问鼎 AI mock/真实安全探测；
8. 发送 Outbox 端到端测试。

## 4. 变更控制

### 4.1 规格变更

任何架构、API、数据模型、状态机、权限、模型默认值变化：

1. 修改 SDD；
2. 在 `DECISIONS.md` 记录原因和取舍；
3. 增加迁移/兼容说明；
4. 版本号按语义化更新。

### 4.2 紧急修复

P0 线上事故可先止血，但必须：

1. 限定最小修改；
2. 同一任务内补回归测试；
3. 同一任务内更新 SDD 和四文件；
4. 标明临时措施和最终修复计划。

不得以“紧急”为理由永久绕过 SDD。

### 4.3 规格冲突

优先级：

```text
用户当前明确要求
  > docs/sdd/*
  > DECISIONS.md
  > 实施计划 docs/plans/*
  > TODO_AGENT.md
  > PROJECT_MEMORY.md
  > 旧 README/ARCHITECTURE/SDD.md
```

发现冲突必须先修正文档，再实现。

## 5. 完成报告格式

每次任务最终报告必须包含：

- 对应 SDD ID；
- 修改文件；
- 已实现行为；
- 真实测试输出摘要；
- 运行/部署验证；
- 未完成或阻塞项；
- SDD 和四文件是否已更新。

不能只说“已优化”“应该可以”。
