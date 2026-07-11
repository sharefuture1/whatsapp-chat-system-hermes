# 开发环境与自动化检查

## 一条命令安装

新成员克隆仓库后，在仓库根目录执行：

```bash
./scripts/setup-dev.sh
```

该命令会：

1. 创建或复用 `.venv`；
2. 安装后端及开发依赖：pytest、Ruff、pre-commit；
3. 使用 lockfile 执行 `npm ci` 安装 Web 和 Bridge 依赖；
4. 安装 `pre-commit` 和 `pre-push` Git hooks；
5. 预创建 hook 工具环境。

## Git hooks

### pre-commit：秒级快速检查

提交前仅运行适合高频反馈的检查：

- Python 暂存文件：Ruff 自动修复、格式化和静态检查；
- Bridge 暂存 JavaScript：`node --check`；
- JSON、YAML、TOML 语法；
- 尾随空格、文件结尾、合并冲突标记；
- 私钥和超大文件检查；
- `git diff --cached --check`。

手动执行：

```bash
./.venv/bin/pre-commit run --all-files
```

### pre-push：完整慢检查

推送前运行：

- Python 全量 pytest；
- Web 全量 Node tests 和 Vite production build；
- Bridge 全量 tests 和现有 lint。

手动执行：

```bash
./.venv/bin/pre-commit run --hook-stage pre-push --all-files
```

也可以直接执行：

```bash
./scripts/check-pre-push.sh all
```

## Claude Code 文件修改 hooks

仓库的 `.claude/settings.json` 配置了 `PostToolUse`：Claude Code 使用 Write/Edit/MultiEdit 修改文件后调用：

```bash
python3 scripts/claude-post-edit.py
```

行为：

- Python：Ruff format，然后 Ruff check `--fix`；
- 普通 JavaScript：`node --check`；
- JSON：解析校验；
- JSX 不使用 Node 直接解析，避免错误处理；其权威检查仍是 Web tests 和 Vite build。

该 hook 只检查刚修改的文件，不在每次 AI 编辑后运行全仓库慢检查。

## 跳过 hooks

紧急场景可由开发者显式使用 Git 的 `--no-verify`，但提交或推送前仍必须补跑对应检查；CI/评审不得把跳过检查视为通过。
