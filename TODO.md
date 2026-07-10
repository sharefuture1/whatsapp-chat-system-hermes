# TODO Roadmap

This file is the forward-looking implementation backlog for the Hermes Messaging Operations Console.

It is intentionally practical and grouped by delivery order so future work can resume without re-planning from scratch.

## P0 – stabilize current product UX

### Mobile chat experience
- [ ] verify real-device mobile scrolling to the absolute bottom while keyboard is open
- [ ] test iPhone safe-area behavior on multiple viewport heights
- [ ] prevent tab bar / composer overlap on short screens
- [ ] keep newest message anchored when auto-translation appears asynchronously
- [ ] verify switching tabs does not reset composer draft unexpectedly

### Chat UX polish
- [ ] make chat header feel more like WeChat desktop/mobile
- [ ] refine selected conversation state and unread badge behavior
- [ ] add platform badge/icon next to the active chat title
- [ ] add platform badge/icon in conversation list rows
- [ ] improve pending-send state for optimistic assistant bubbles

### Translation quality
- [ ] extend deterministic low-info translation map for more Lao/Thai fillers
- [ ] add fallback rules for short stickers/media acknowledgements
- [ ] add a per-message “show original / show translation” toggle
- [ ] collapse very long translations behind “expand” affordance
- [ ] add tests for common low-information message translations

## P1 – multi-channel architecture

### Data model
- [ ] introduce `workspace_id` for every conversation/message source
- [ ] introduce explicit `platform` field in frontend-facing DTOs
- [ ] introduce `account_label` / `channel_label` for multi-account routing
- [ ] stop assuming `user_id` is globally unique across all channels

### Backend aggregation
- [ ] aggregate multiple Hermes profiles into one unified inbox
- [ ] add profile registry config (workspace id, platform, label, profile path)
- [ ] route outbound sends through the correct Hermes profile
- [ ] expose per-workspace health and status API
- [ ] expose reconnection / refresh actions per workspace

### UI
- [ ] add platform icons for WhatsApp / Telegram / future WeChat
- [ ] show workspace/account label in chat header and search results
- [ ] add workspace switcher / filter in the chats tab
- [ ] make Telegram conversations visibly distinct beyond `-tg`

## P1 – authentication and security
- [ ] consider switching from localStorage token to httpOnly cookie model
- [ ] add explicit password reset flow in Me/Settings
- [ ] add session list + “log out other sessions” UX
- [ ] add login audit log view for operator access tracking

## P1 – settings and configuration UX
- [ ] fully localize all settings labels in Chinese/Thai/Lao/English
- [ ] add help text for each reply-policy field
- [ ] add validation/error hints in settings forms
- [ ] group channel config into collapsible cards
- [ ] add test-send button for each admin delivery channel

## P2 – discover / me / contacts polish
- [ ] make Discover tab feel more like WeChat “发现” and less like a stats grid
- [ ] redesign Contacts tab to support grouping and search better
- [ ] make Me tab more polished with profile card, status cells, and settings navigation blocks
- [ ] add lightweight profile picture / workspace branding support

## P2 – backend performance
- [ ] add TTL caching for expensive conversation summary generation
- [ ] add incremental refresh strategy instead of full message scans
- [ ] consider SQLite read connection reuse / pooling
- [ ] add server-side pagination for search results

## P2 – testing and QA
- [ ] add browser-based screenshot QA for desktop/mobile key views
- [ ] add snapshot tests for i18n key coverage after new tabs/components
- [ ] add multi-channel fixture tests (WhatsApp + Telegram together)
- [ ] add translation cache regression tests for stale wrong translations

## Operational notes
- Current backend port: `127.0.0.1:8792`
- Current frontend dev port: `127.0.0.1:38998`
- Current Vercel API target: `https://whats.future1.us/api`
- Runtime secrets policy: keep login/bootstrap secrets only in runtime config or secret stores, never in repo docs

Keep this file updated whenever major architecture or UX work lands.
