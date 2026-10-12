# Next engineering packages

P0 shared integration (coordinate with Claude): one async credential API; replace every localStorage token consumer; adopt verified identity-scoped encrypted store and cash queue; quarantine legacy IndexedDB; expose recoverable queue state; add real backend reconnect/account-switch tests; forbid offline card success; disable non-idempotent KDS replay. Route receipt callers to adapter; reconcile payment redirects and custom-origin WebSockets. Fix web service worker booking caching and mid-sale activation.

P0 server device/payment: revocable pairing credentials checked on every request; compatible client-version handshake; durable KDS idempotency; provider-backed unknown-payment recovery.

P1 Windows qualification: signed installer/update feed, per-venue nonproduction API build, touch/desktop/accessibility and display scaling, scanner/printer/drawer vendor adapters, restricted kiosk policy. Run physical Windows 10/11, power-loss, paper-out, reconnect, restart and end-of-day reconciliation tests.

Claude: Android targets 1/2, Capacitor alignment, Keystore-backed implementation of shared contract, Android lifecycle/permission/physical printer/payment tests. Apple: future native project/signing/Keychain/hardware package.
