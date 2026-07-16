# 2026-07-16 Tauri 2 桌面安装包自动构建计划

## 关联规格

- `docs/sdd/11-tauri-desktop-distribution.md`
- FR-DESKTOP-001
- SEC-DESKTOP-001
- QA-DESKTOP-001
- NFR-REL-003

## 目标

1. 修复 Tauri 审查发现的 session、缓存、AI key 与配置读取安全问题；
2. 提交 Rust `Cargo.lock` 和多平台图标；
3. 本机通过 `cargo check --locked` 与 Linux `.deb` 构建；
4. GitHub Actions 自动构建 Linux、Windows、macOS 测试安装包；
5. 每个平台上传可下载 artifact；
6. 不将未签名测试安装包描述为正式发布版。

## TDD 步骤

1. RED：补旧 Session 提权、AI URL/key 换域、配置读取权限、Tauri token/cache 测试；
2. GREEN：授权 fail-closed、admin 迁移、最小 capabilities DTO、Tauri 内存 token/cache；
3. 生成 `Cargo.lock` 和图标；
4. 增加 `.github/workflows/tauri-build.yml`；
5. 运行 Python/Web/Bridge、Browser/Tauri build、Ruff、Rust check；
6. 本机构建 Linux `.deb`；
7. 推送分支并验证 GitHub Actions 三平台运行及 artifacts。

## 发布边界

- 当前 artifacts 未签名，仅供测试；
- Windows Authenticode、Apple Developer ID/notarization、Linux repository signing 后续单独实施；
- Android/iOS 不属于本阶段自动构建完成范围。
