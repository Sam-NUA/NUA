# Offline sync foundation and integration gate

`packages/platform-core/queue.cjs` is a durable cash-order state machine with injected storage and transport, not a replacement already connected to POSTerminal. Scope is a collision-safe tuple of server-verified businessId, userId and deviceId. Logout locks reads and replay; switching invalidates in-progress iteration. The transport MUST pin verified authentication to expectedScope immediately before dispatch; it must not obtain an unrelated current localStorage token. Identity labels are isolation keys, not credentials.

Persist operation ID and payload before first network attempt. Pending → sending → synced; network/5xx/429 → retry with bounded exponential backoff; 4xx or foreign-business response → conflict. Preserve conflicts and stop FIFO, never silently delete. Sending rows after restart are replayed with the same ID; exactly-once effect requires backend deduplication. A lost response is not payment failure. Retain synced rows for reconciliation; bounded retention/export is a follow-up before production.

Encrypted atomic store writes a temporary file, fsyncs content, then renames. Corruption/disk-full/OS-encryption failure fails closed, never resets to an empty queue. Unit tests use real temporary files with AES-GCM fixtures; Windows CI separately checks real OS crypto. Power-loss durability on actual Windows storage needs testing.

Card, gift-card/customer-balance and loyalty redemption are forbidden by the cash queue. Offline kitchen/booking/stock allocation is not enabled. Legacy unscoped IndexedDB data cannot be automatically assigned to the next logged-in business. A shared migration must quarantine it, reconcile with original business credentials and expose pending/retry/conflict states in POS UI. The active web queue is still unsafe until that coordinated change lands.

Acceptance still required with the real app/API: take cash order, disconnect, restart, reauthenticate same business, reconnect, exactly one sale and expected inventory/KDS effects; then sign into a different business and prove no data visibility/replay. Current contract tests do not establish that full-stack milestone.
