# Tenant isolation acceptance

Automated foundation tests: independent A/B and same-business different-user encrypted stores; A→B switch during replay stops subsequent A sends; logout blocks reads; response business mismatch retains conflict; stable ID survives lost response/restart; failed durable write prevents send.

Required full-stack tests before native release:
1. Authenticate A, cache catalogue and queue sale, log out. Authenticate B. Assert A caches/queue/customer/printer records unavailable and no A operation sent under B.
2. Switch account between transport verification and dispatch; reject without sending using B's token.
3. Restart with a sending record; reconnect as A; assert exactly one Mongo sale and one inventory/KDS effect.
4. Revoke device/user or change business during outage; replay must fail closed and retain recoverable data.
5. Send forged businessId, foreign product/customer/printer/order/booking IDs and dedup IDs; backend must reject or scope them strictly.
6. Inspect app storage/logs for plaintext tokens, card data and foreign tenant details.

Backend in-process regressions run in full. Passing them does not certify custom-origin native authentication or hardware behavior. Do not disable correctly failing tenant tests to make a platform demo pass.
