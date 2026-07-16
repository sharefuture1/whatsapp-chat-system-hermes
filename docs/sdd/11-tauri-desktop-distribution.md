# Tauri 2 桌面安装包自动构建

> 状态：In Progress  
> 关联需求：FR-DESKTOP-001、SEC-DESKTOP-001、QA-DESKTOP-001、NFR-REL-003

## 1. 目标

为现有 React/Vite 控制台提供最小权限的 Tauri 2 薄客户端，并由 GitHub Actions 自动产生可下载的桌面测试安装包：

- Linux x64：`.deb`、`.AppImage`；
- Windows x64：NSIS `.exe`；
- macOS：`.dmg`。

桌面客户端不内嵌 Python、数据库或 WhatsApp Bridge；所有业务继续通过 `https://whats.future1.us/api` 调用服务器。

## 2. 安全边界

- Tauri HTTP capability 只允许 `https://whats.future1.us/api/**`；
- 不开放 filesystem、shell、process、clipboard、updater；
- Tauri 模式不把 session token 写入 `localStorage`；关闭应用后必须重新登录；
- Tauri 模式消息与翻译缓存仅存内存；浏览器缓存按用户名隔离，logout/401 时清理；
- Base URL 变化时不得复用旧 AI API key；必须同请求提供新 key；
- 旧格式 session 缺少 username 时必须 401，不得默认 admin。

## 3. GitHub Actions

工作流：`.github/workflows/tauri-build.yml`

触发条件：

- `main` 与 `codex/p0-hardening-tauri2` 的相关文件 push；
- Pull Request；
- `v*` tag；
- 手动 `workflow_dispatch`。

每个平台必须执行：

1. `npm ci` 与 `npm ci --prefix web`；
2. `npm run tauri:validate`；
3. `cargo check --locked`；
4. `tauri build --bundles ...`；
5. 上传 `src-tauri/target/release/bundle/**` 为 Actions artifact。

安装包默认未签名，只用于内部测试。正式发布必须增加平台签名、notarization、证书保管和 release approval。

## 4. 可重复构建

- 必须提交 `src-tauri/Cargo.lock`；
- Rust 检查必须使用 `--locked`；
- JS 使用已提交的 npm lockfile 与 `npm ci`；
- 安装包图标由 `app-icon.svg` 生成并提交到 `src-tauri/icons/`。

## 5. 验收标准

- [x] Tauri 静态策略校验通过；
- [x] Browser/Tauri 两种 Vite 构建通过；
- [x] Python/Web/Bridge 全量测试通过；
- [x] Rust lockfile 已生成；
- [x] Linux `cargo check --locked` 与 `.deb` 本机构建完成；
- [ ] GitHub Actions Linux/Windows/macOS 三个平台全部绿色并上传 artifact；
- [ ] 安装包在对应系统启动、登录、会话读取、翻译预览和注销场景完成冒烟测试。

## 6. 非目标

本阶段不声称 Android/iOS 已可发布。移动平台仍需：

- 初始化原生工程；
- Android/iOS 专用 CI runner；
- 签名与商店凭据；
- Stronghold 或平台安全存储；
- push、硬件返回、深链、真机与商店审核验收。
