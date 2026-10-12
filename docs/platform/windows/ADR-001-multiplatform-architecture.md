# ADR 001: Shared React core; isolated Windows Electron host

Status: accepted for FOUNDATION, not production release. Date: 2026-10-12.

Android tablet/phone: Claude owns Capacitor alignment and implementation. Do not fork the React POS per OS. Apple remains design-only. Windows touch and desktop share one host with an explicit input mode.

Choose Electron over the directive's preferred Tauri for this package: the repo already has Electron packaging, staff maintain JavaScript, and Electron exposes printer enumeration and OS spooler submission directly. Tauri/WebView2 is viable and smaller but would add Rust/COM or a separately vetted printing plugin. This is a maintenance/hardware decision, not a claim that Electron solves POS reliability. Existing Electron 33 must not ship. Pin the current registry release in the isolated Windows package and audit its dependencies.

Use `nua://app` bundled assets, no remote executable code, no file-origin routing, sandbox/context isolation, strict navigation/permission policy, sender-validated IPC. Keep API origin explicit at build time. No local API proxy or embedded Mongo. API CORS must explicitly permit this origin in a nonproduction integration environment; no live env changes here.

Use Electron OS encryption for Windows local persistence, fail closed on unsupported OS/crypto. Main-process scoped durable state supports primitives only; current shared auth still needs migration. Tenant/account scope comes from verified authentication at the integration boundary, never merely a local label. Device install UUID is identification only.

Queue supports cash orders only, stable operation ID before first attempt, durable pending/retry/conflict state and account-switch fencing. Backend still recomputes values and enforces business/RBAC. No automatic replay of card, loyalty redemption, stock promises or non-idempotent KDS actions. Existing browser queue is not silently migrated or declared safe.

References reviewed: https://www.electronjs.org/docs/latest/tutorial/security ; https://www.electronjs.org/docs/latest/api/web-contents ; https://www.electronjs.org/docs/latest/api/safe-storage ; https://v2.tauri.app/reference/config/ ; https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/print .
