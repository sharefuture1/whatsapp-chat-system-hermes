# Architecture

## Overview

The project is a profile-aware operator console layered on top of an existing Hermes WhatsApp support workspace.

There are three major layers:

1. Hermes profile runtime
   - WhatsApp gateway
   - Hermes state.db session/message storage
   - Hermes send command for outbound platform delivery

2. Python application layer
   - reads Hermes session/message state
   - derives user summaries and routing behavior
   - exposes a secure FastAPI API

3. React operator UI
   - authenticates with a password-backed session token
   - lists conversations and message history
   - previews and sends replies
   - manages operator settings and routing

## Data sources

Primary durable source:
- `state.db`

Supplementary profile-local files:
- `sessions/sessions.json`
- `channel_directory.json`
- `user-aliases.json`
- `admin-channels.json`
- `web-settings.json`
- `user-memory-md/*.md`

## Core backend responsibilities

### web_api.py
- auth guard
- dashboard metrics
- conversation APIs
- reply preview/send APIs
- settings APIs
- local hide APIs
- job trigger APIs

### router.py
- resolves targets by alias/name/id
- loads user memory
- chooses rewrite strategy
- sends final outbound messages through Hermes

### rewriter.py
- smart rewrite mode
- translate-only mode
- fallback control
- output validation / length control

### forwarder.py
- forwards user/assistant transcript pairs to configured admin channels

### memory_refresh.py
- synthesizes markdown memory files from Hermes transcript history

## Security model

Current security is application-layer login:
- password stored as a PBKDF2-HMAC-SHA256 record in `web-settings.json`
- successful login issues a session token
- token is required in `x-session-token` for protected endpoints

Runtime secret policy:
- live passwords, bootstrap secrets, API keys, and session tokens must stay out of git-managed docs
- profile-local runtime files may contain secrets and must be treated as sensitive operational state
- screenshots/HAR/audit exports should be ignored or redacted before sharing

This is sufficient for a private internal console, but not yet a full enterprise auth layer.

## Functional constraints

### WhatsApp message deletion
The app currently cannot revoke/delete messages for both sides because the Hermes WhatsApp bridge does not expose a delete/revoke endpoint.

Therefore the UI exposes only:
- local hide
- local bulk hide

## Suggested future extensions

- real remote deletion if the bridge is extended
- websocket/live updates
- durable operator notes and tags in a dedicated app DB
- multi-operator roles
- session expiry and login throttling
