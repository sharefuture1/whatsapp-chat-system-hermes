# Tauri 2 application shell

This directory adds a thin Tauri 2 shell around the existing Vite/React console.
It does not embed Python, the WhatsApp Bridge, or the database: those remain on
the server and are reached through the existing HTTPS API.

## Architecture and API base

- Browser production builds use `.env.production`, keep `/api` same-origin, and
  use the browser's `fetch`. Both committed Vercel configurations preserve that
  path with an API rewrite.
- A packaged Tauri build uses the Tauri HTTP plugin when `VITE_API_BASE` is an
  absolute URL. `vite build --mode tauri` loads `.env.tauri`; the committed
  production scope allows only
  `https://whats.future1.us/**`.
- The API base is public configuration, not a credential. Every `VITE_*` value
  is embedded in the frontend bundle. Never put passwords, session tokens,
  signing keys, Bridge tokens, or AI keys in a Vite variable or Tauri config.
- To use another backend, change the HTTP capability scope and CSP to that exact
  HTTPS origin in the same reviewed change, then set `VITE_API_BASE` for the
  build. Do not replace the scope with a wildcard.

These explicit overrides are useful for CI and release jobs:

```bash
# Same-origin Web deployment (also the committed production default)
VITE_API_BASE=/api npm --prefix web run build

# Desktop/mobile package (the Tauri mode already has this public default)
VITE_API_BASE=https://whats.future1.us/api npm run tauri:build
```

During `tauri dev`, leaving `VITE_API_BASE` unset keeps `/api` relative and uses
the existing Vite proxy to `127.0.0.1:8792`.

## Prerequisites

Install Node.js LTS, Rust through `rustup`, and the platform dependencies from
the official Tauri prerequisite guide:

- Rust `1.77.2` is the declared minimum for the current HTTP plugin; use a
  current stable toolchain on build agents.

- Linux desktop: WebKitGTK 4.1 and the listed compiler, SSL, tray, and SVG
  development packages.
- Windows desktop: Microsoft C++ Build Tools and WebView2. MSI packaging also
  needs the VBSCRIPT optional feature.
- macOS desktop/iOS: Xcode. Command Line Tools alone are sufficient only when
  iOS is not a target.
- Android: Android Studio/JBR, Android SDK Platform, Platform-Tools, NDK,
  Build-Tools, Command-line Tools, and the documented `JAVA_HOME`,
  `ANDROID_HOME`, and `NDK_HOME` values.
- iOS builds and App Store distribution require macOS. Store distribution also
  requires an Apple Developer membership and code signing.

Install JavaScript dependencies before using the shell:

```bash
npm ci
npm ci --prefix web
```

## Desktop commands

```bash
npm run tauri:validate
npm run tauri:dev
npm run tauri:build
```

`tauri:validate` is a pure Node configuration guard used by CI. It verifies the
two Vite modes, exact HTTP capability/CSP origin, Rust plugin wiring, Vercel API
rewrite, and absence of credential-shaped `VITE_*` keys without requiring Rust,
WebKitGTK, Xcode, or the Android SDK.

`devUrl` is fixed to `http://localhost:38998`; `strictPort` prevents Vite from
silently selecting a different port. `frontendDist` embeds `web/dist` in release
packages, built with the separate `tauri` Vite mode. The Vite config honors
`TAURI_DEV_HOST` for physical mobile devices.

Native packages are platform builds, not one universal binary:

| Target | Typical release output | Required build host |
| --- | --- | --- |
| Windows | NSIS installer or MSI | Windows |
| macOS | signed/notarized app and DMG | macOS |
| Linux | AppImage, deb, or rpm | compatible Linux runner |
| Android | signed AAB for Play, APK for testing | Android SDK/NDK runner |
| iOS | signed Xcode archive for TestFlight/App Store | macOS with Xcode |

Use separate CI jobs and signing identities for each row. The repository CI
currently validates the shell and both frontend modes only; it deliberately
does not sign, publish, or upload native artifacts.

## Android and iOS

Initialize the native projects once on a correctly provisioned workstation,
then commit the generated platform project if it receives signing, manifest, or
native configuration changes:

```bash
npm run tauri:android:init
npm run tauri:android:dev
npm run tauri:android:build

# macOS only
npm run tauri:ios:init
npm run tauri:ios:dev
npm run tauri:ios:build
```

For Google Play, build an AAB with `npm run tauri -- android build --aab` and
configure Android signing outside the repository. For iOS, use
`npm run tauri -- ios build --open` to archive/sign in Xcode. The App Store
bundle ID must exactly match `identifier` in `src-tauri/tauri.conf.json`, so
confirm that identifier before registering either store application.

## Capabilities and release signing

`src-tauri/capabilities/main.json` grants the main window only the scoped HTTP
permission needed for the production API. No filesystem, shell, process,
clipboard, window-management, or updater permission is enabled.

The updater is intentionally not enabled in this scaffold:

- Desktop updater artifacts must be signed; signature verification cannot be
  disabled. Keep `TAURI_SIGNING_PRIVATE_KEY` and its password in the release
  secret store, never in `.env` or the repository. Back up the private key: a
  lost key prevents updates for already-installed clients.
- Android and iOS releases should use Google Play and App Store/TestFlight
  update channels and their platform signing identities.
- Add the desktop updater only after an HTTPS update endpoint, immutable signing
  key custody, rollback policy, and release CI are ready.

For future native credential storage, evaluate the all-platform Stronghold
plugin separately. This first scaffold deliberately keeps the native attack
surface to one scoped HTTP permission.

## Required before store submission

The shell is a development baseline, not a store-ready mobile application. Do
not submit it to Apple or Google until this checklist has owners, tests, and a
release sign-off:

- **Native session storage:** move the packaged app's long-lived session token
  out of WebView `localStorage` into the Stronghold plugin, expose only narrowly
  scoped login/logout/token-use commands, define lock/logout behavior, and test
  device backup/restore and compromised-WebView cases. The browser build keeps
  its existing storage path.
- **Realtime and push:** design an authenticated SSE/WebSocket channel for use
  only while the app is foregrounded. Add server-side device-token registration
  and APNs/FCM for background delivery, token rotation, logout revocation, and
  privacy-safe notification payloads. Tauri's local notification plugin is not
  a substitute for remote push and cannot make a suspended WebView reliable.
- **Android navigation:** map the hardware/gesture back action onto an explicit
  chat/list/modal route stack. Test predictive back, deep links, drafts, and the
  root-screen exit behavior instead of treating every back action as app exit.
- **Mobile layout:** verify every screen with safe-area insets, notches, tablets,
  rotation, large text, reduced motion, and both iOS/Android soft keyboards.
  Composer focus and the active message must remain visible as the viewport
  resizes.
- **Media and permissions:** design around Android `content://` URIs and iOS
  photo/file providers rather than durable filesystem paths. Add camera,
  microphone, photo-library, and file permissions only with a concrete feature;
  scope native capabilities, validate MIME/size, strip sensitive metadata where
  appropriate, and test upload cancellation and revoked permission states.
- **Privacy and store declarations:** publish a privacy policy and support/account
  deletion path; document message/contact/media retention and subprocessors;
  complete Apple privacy manifests and App Store disclosures plus Google Play
  Data Safety/content declarations; review export-compliance, account login,
  notification, and platform messaging-policy requirements.
- **Release controls:** finalize the immutable bundle/application ID, icons,
  version-code strategy, signing custody, CI provenance/SBOM, staged rollout,
  crash reporting consent, rollback, and an on-device release test matrix.

Stronghold, push, media pickers, camera access, and extra window/process APIs are
deliberately absent today. Each future plugin must add a platform-specific,
least-privilege capability and a corresponding threat-model/test update.

## Official Tauri 2 references

- Prerequisites: <https://v2.tauri.app/start/prerequisites/>
- Existing frontend/manual setup: <https://v2.tauri.app/start/create-project/#manual-setup-tauri-cli>
- Configuration (`devUrl`, `frontendDist`): <https://v2.tauri.app/reference/config/>
- Mobile development: <https://v2.tauri.app/develop/#developing-your-mobile-application>
- Capabilities: <https://v2.tauri.app/security/capabilities/>
- HTTP plugin and scoped URLs: <https://v2.tauri.app/plugin/http-client/>
- Stronghold plugin: <https://v2.tauri.app/plugin/stronghold/>
- Notification plugin: <https://v2.tauri.app/plugin/notification/>
- Distribution and signing: <https://v2.tauri.app/distribute/>
- Updater signatures: <https://v2.tauri.app/plugin/updater/#signing-updates>
- Google Play: <https://v2.tauri.app/distribute/google-play/>
- App Store: <https://v2.tauri.app/distribute/app-store/>
