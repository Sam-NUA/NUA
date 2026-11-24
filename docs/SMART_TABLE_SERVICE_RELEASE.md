# NUA Smart Table Service — deployment and operating notes

## Rollout / safe defaults

- **OFF by default per business**. Existing outlets experience no new warnings until an owner/manager enables the feature.
- Owner/manager: open any authenticated NUA POS screen, press **Table attention**, select the settings cog, enable reminders, review all seven rules, then Save.
- Per-stage course colours and floor-plan dwell limits are separate existing controls under **Floor Plan → Table → Dining Course Thresholds**.
- Default rules: order not taken 5/8 min; drinks to food 8/12; mains held 10/15; kitchen cooking 20/30; ready food 3/5; post-mains check 12/18; bill request 5/8. First/escalation thresholds are owner-editable (1–240 min / 1–480 min; escalation > first alert).
- Stage colours and orange overdue rings remain intact.
- **No action in this feature automatically fires, pays, voids, or changes an order.** The “Open table” action navigates to the operational screen; staff must use the regular Fire/Hold controls.

## Operational usage

1. Floor Plan: seat a table to start the arrival clock; if possible, **assign waiter** to themselves or through the manager's staff picker.
2. Record drinks served / food ordered / bill requested / bill completed in that table's drawer when those events occur. Kitchen send, fire, ready and serve events use the live kitchen tickets.
3. Shared floor queue shows unassigned tables to eligible floor staff; assigned tables show to the waiter plus managers. Kitchen delay alerts show to kitchen staff plus managers.
4. Actions: **Acknowledge**, **Snooze 3 minutes**, **Resolve**. Acknowledged alerts remain visible in the attention queue but stop pop-ups; a new escalation can re-open once when the higher threshold is crossed. Snoozed alerts reappear when their timer expires.
5. Pause service if guests request a break, then Resume. Recorded pause periods are excluded from the effective service elapsed time. Clearing a table makes its current alerts obsolete; they resolve on the next refresh.

## Architecture / security

- REST paths under authenticated `/api/table-service/*`: `GET/PUT settings`, `GET staff`, `GET alerts`, `POST events`, `POST alerts/{id}/action`.
- Durable alerts are keyed by a deterministic hash of business, table, rule, and source timestamp; MongoDB has a unique id index to dedupe concurrent tablet polls.
- Every read/write is scoped by `businessId` and staff actions respect waiter assignment. No recipient PIN or password is exposed by staff lookup.
- Client refreshes every 15 seconds, preserves acknowledgements on the server, and stops interfering with order entry during network interruptions. This is a near-real-time poll, not a push notification to an app that is closed.
- Table service rules and alerts are tenant-scoped. Multi-location-specific presets and staff phone push notifications are **not** part of this release.

## Validation and release gates

- Backend lint + mypy differential, pip-audit differential and in-process tests; frontend npm runtime audit + lint + Jest + build; booking and Playwright E2E suites; secret scan.
- Review mobile/desktop foundation build workflows separately. Device-specific signed installers need their own release and signing gates; browser deployment does not sign an iOS IPA.
- Inspect Vercel production deployment, confirm authenticated alert endpoints and a disabled-by-default business. Enable in staging, simulate overdue table, verify exactly one durable alert across two signed-in devices, acknowledgement/snooze/escalation, reload, and tenant isolation.
- Rollback: switch off **Enable automatic service reminders** per business; if code rollback necessary restore the previous Vercel production deployment. The alert subsystem never mutates order or payment state.
