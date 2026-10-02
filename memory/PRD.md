# NUA POS — Vercel-only Codex/Emergent collaboration (2026-10-02)

## 2026-10-02 — Owner access recovery (branch `emergent/owner-recovery`, PR #6 against `codex/vercel-only` @ `9408629`)

### Context
Continuing NUA POS alongside Codex via GitHub as shared source of truth.
Hosting: Vercel only (`sam-nua/nua-pos-staging`). Open Codex PR chain at the
time: #3 `platform-reliability→main` → #4 `deployment-readiness→platform-reliability`
→ #5 `vercel-only→deployment-readiness`, all open/unmerged; #1 merged
2026-09-20; #2 open, superseded by #3-5 per `docs/VERCEL_ONLY.md`.

### Root cause (confirmed by local reproduction, not assumed)
`routes/auth.py login()` always looks up `req.email.lower()`. `seed_admin()`
stored `ADMIN_EMAIL` verbatim — any uppercase character in the Vercel value
meant the seeded owner could never match. Reproduced locally: mixed-case
seed → login 401s; lowercase-normalize → login succeeds. The separate
"password resets on every cold start" bug had already been fixed upstream
in Codex commit `9408629` (atomic `$setOnInsert` in `_insert_seed_user`).

### Shipped
- `seed_admin()` lowercases/strips `ADMIN_EMAIL`; self-heals an existing
  owner's email casing in place (case-insensitive match on `role: owner`,
  only the email field changes — never password/role/status, never a
  duplicate).
- Operator-only recovery: `POST /auth/owner-recovery/initiate` (recoveryKey
  + email) → `POST /auth/owner-recovery/complete` (token + new password).
  Gated on new `OWNER_RECOVERY_KEY` secret (hmac-compared), shared 5/15min
  lockout bucket, 15-min single-use token (sha256 hash stored, atomic
  claim-once = replay protection), every attempt audited to
  `db.owner_recovery_audit`, rejects (409) retargeting an existing owner to
  a different email. Both routes added to `server.py` `PUBLIC_API_PATHS`.
- `frontend/src/pages/OwnerRecovery.jsx` + `/owner-recovery` route (not
  linked from Login.jsx) — two-step UI, password typed into a field.
- Tests: `test_owner_bootstrap.py` (+2), new `test_owner_recovery.py` (5
  cases). `backend/tests/inprocess/`: 826 passed / 4 failed, all 4
  pre-existing/environment-caused (Stripe-key-present assumptions in
  `test_connect_square`/`test_crypto_payments`/`test_reservations_tenant_isolation`,
  a known mongomock-concurrency flake in `test_financial_offline_integrity`)
  — none touch `auth.py` or this change.
- `requirements.txt`: added `sentinels` (mongomock's missing transitive dep;
  `tests/inprocess` couldn't import without it in this environment).
- Docs: `docs/VERCEL_ONLY.md` updated; new `docs/COLLABORATION_HANDOFF.md`
  (Emergent/Codex sections + file ownership table).

### Verified
End-to-end locally (broken password hash → recovery initiate/complete →
login with new password → token replay rejected) and via the UI testing
agent against the running preview (`/owner-recovery` page, all 6 scenarios
passed, see conversation). NOT verified against real Vercel staging or
real `ADMIN_EMAIL`/`ADMIN_PASSWORD`/Mongo data — no Vercel token was
available this pass.

### P0 — next (blocked on access)
- Get Vercel API access or have the operator confirm directly: is
  `ADMIN_EMAIL`/`ADMIN_PASSWORD` actually set on `nua-pos-staging`? Is
  `FRONTEND_URL` save confirmed (previously only "started")? Deploy/merge
  this PR, set `OWNER_RECOVERY_KEY` in Vercel, run the real recovery flow
  once, confirm owner login on the live URL, then remove the recovery key.
- SendGrid (`SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`) intentionally
  deferred — `/forgot-password` still silently no-ops without them.

### P1/P2 — after owner access is confirmed restored on staging
- Durable background jobs (Vercel Queues/Workflows or Cron) replacing the
  in-process Ash/coursing schedulers and delivery outboxes — Hobby Cron is
  daily-only, insufficient for minute-level coursing.
- Multi-instance realtime fan-out, distributed rate limiting (current
  lockout/rate-limit buckets are per-instance in Mongo but not yet audited
  for cross-instance correctness under Vercel's serverless concurrency).
- Durable upload/backup storage (not ephemeral function storage).
- Live two-tenant/role/payment-sandbox smoke tests against the actual
  deployed edge (see `docs/DEPLOYMENT_READINESS.md` release order).

---


# NUA POS — PRD v36.6 (NUA namespace refactor · Per-channel schedule/hours UI)


## v36.6 — Iteration 64 (Feb 2026): NUA namespace refactor + Channel schedule UI

### Shipped

**Backend `ash` → `nua` namespace refactor** (`services/nua_*.py`, `routes/nua.py`, `server.py`)
- Renamed Python modules: `services/ash_{agent,memory,tools,scheduler,briefing,personas,intelligence,planner}.py` → `services/nua_*.py`; `routes/ash.py` → `routes/nua.py`.
- Route prefix flipped: native routes are now `/api/nua/*` (was `/api/ash/*`).
- Rewrote all Python import statements and attribute references (from `ash_x` module identifiers to `nua_x`) with a scripted rewriter — 6 files changed. String literals used as DB source tags (e.g. `sourceType: "ash_agent"`) intentionally preserved for data compatibility.
- Flipped `NuaAliasMiddleware` direction: it now rewrites `/api/ash/*` → `/api/nua/*` so old integrations, tests and iteration reports keep working.
- DB collection names (`db.ash_insights`, `db.ash_plans`, `db.ash_memories`, `db.ash_agent_traces`, `db.ash_agent_log`, `db.ash_chat_log`, `db.ash_tool_config`, `db.ash_briefings`) intentionally unchanged — no data migration.
- Testing: 20/20 backend pytest cases PASS (`test_iteration56_nua_channels.py`), both `/api/nua/*` and `/api/ash/*` return 200 for tools/personas/briefing/health-score/scheduler-status/agent.

**Per-channel schedule UI (simple + advanced)** (`components/channel/ChannelPauseControl.jsx`, `routes/finalize.py`)
- Existing pause/resume/pause-until buttons preserved; added a new **Hours** button per channel.
- **Simple mode**: single daily open/close window applied every day (with a Closed toggle).
- **Weekly mode**: 7-day grid with per-day open/close and Closed toggle.
- **Date overrides**: Add-date rows for holidays/one-offs — each has date + closed toggle + optional open/close + reason.
- New backend endpoints (owner/manager only):
  - `GET /api/channels/{channel}/schedule` — returns saved schedule or defaults.
  - `POST /api/channels/{channel}/schedule` — save; preserves previously-saved weeklyHours when caller only updates Simple mode.
  - `GET /api/channels/{channel}/effective-status` — merges pause-state + schedule + overrides + current UTC time to return `{state, schedule, openNow:{isOpen,reason}, effective:'active'|'paused'}`.
- Live status pill on Channel Menus now shows Open-hours reason (e.g. "11:00–22:00" or "outside 11:00–22:00") when scheduling is enabled.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (on hold per user).
- **P1** SendGrid / Twilio production keys (on hold per user).
- **P1** Hardware Health polish.
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** `x-ai-parsed-fallback` header on AI endpoints.
- **P2** Move `ai_weekly_plan` to a background task.


## v36.5 — Iteration 63 (Feb 2026): POS cart & split payment fixes

### Shipped

**Cart swipe — reliable on tablets and POS terminals** (`components/pos/SwipeableCartItem.jsx`)
- Root cause: previously only used `onPointerDown/Move/Up`. That works on desktop but is flaky on iPadOS Safari, older Android WebViews and some POS-terminal browsers (setPointerCapture throws/no-ops).
- Fix: added explicit `onTouchStart/Move/End/Cancel` fallback next to the pointer handlers. Both drive a single shared `beginDrag/moveDrag/endDrag` state machine.
- New axis-lock: after ~6px of movement the swipe locks to `x` or `y`. Vertical touches now cleanly hand off to the page's scroll instead of being stolen mid-drag.
- Horizontal drag calls `preventDefault()` only on the swipe axis so native scroll is unaffected.
- Verified end-to-end on desktop: right-swipe on Chocolate Cake bumped qty 1 → 2, left-swipe on the 2nd item removed it, `Subtotal $19.98 · Tax $2.00 · Total $21.98` reconciled correctly.

**Split Payment — QR/UPI dialog actually shows now** (`pages/POSTerminal.jsx`, `components/pos/PaymentDialogs.jsx`)
- Root cause: `handlePaySplit` was calling `paymentAPI.generateQR()` and then immediately `paymentAPI.confirm()` **without ever displaying the QR to the guest**. Clicking Pay on a UPI/QR split silently marked it paid.
- Fix: refactored into two-phase flow —
  1. `handlePaySplit` generates the QR and opens the `QrPaymentDialog`/`UpiPaymentDialog` stacked on top of the split dialog (with per-split amount + `nua@upi` copy-to-clipboard).
  2. Cashier taps **Confirm Payment Received** → `confirmSplitQr` calls `/payments/confirm` and only then `finaliseSplitPart` marks the row Paid.
  3. Cancel/close in the QR dialog leaves the split row `pending` (no accidental writes).
- Card and Cash split parts remain instant (no dialog, no external gateway needed).

**Split Payment — remaining balance now impossible to miss** (`components/pos/PaymentDialogs.jsx`)
- Root cause: remaining was a tiny badge next to the title; cashiers didn't realise it was live.
- Fix: 3-tile header **Bill Total · Paid So Far · Remaining** — bill in grey, paid in emerald, remaining in orange (flips to emerald "All settled" once the maths balances). Every tile updates the instant `finaliseSplitPart` runs.
- Verified: 3-way split of $28.92 → per-guest $9.64. After Guest 1 pays via UPI, header shows `Bill $28.92 · Paid $9.64 · Remaining $19.28` with Guest 1's card marked Paid.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (on hold per user).
- **P1** SendGrid / Twilio production keys (on hold per user).
- **P1** Hardware Health polish.
- **P2** ~~`ash` → `nua` backend namespace refactor~~ ✅ Done in v36.6.
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** ~~Channel Menus per-channel pause/resume + schedule toggle UI~~ ✅ Done in v36.6.
- **P2** `x-ai-parsed-fallback` header on AI endpoints.
- **P2** Move `ai_weekly_plan` to a background task.


## v36.4 — Iteration 62 (Feb 2026): Section-grouped permissions (role + staff)

### Shipped

**Feature Access Control — full RBAC redesign** (`services/permission_catalog.py`, `routes/enterprise_features.py`, `routes/auth.py`, `components/settings/PermissionsPanel.jsx`)
- Expanded the flat 26-permission list into a **13-section catalog of 84 features** covering every route the Owner has: Sales, Bookings, Kitchen, Menu & Products, Inventory, Customers & Loyalty, Analytics & Insights, Finance, Staff & Rosters, Automation & AI, Approvals & Audit, Enterprise, Settings.
- **Per-role defaults** now DB-backed (`db.role_permissions`) with code-level fallbacks — Owner sets what Manager / Staff (Cashier) / Kitchen / any custom role gets. Owner is protected (always `["*"]`, 400 on modification attempts).
- **Two-mode Settings UI**:
  - **By Role**: role tiles show live "X of 84 features" badges + a "Customised" indicator when the Owner has overridden the built-in defaults.
  - **By Staff Member**: dropdown → panel shows "using role defaults" vs "custom override", one-click Reset reverts to role defaults.
- **Collapsible sections** with an icon, "X / Y" counter, colour-coded progress bar (green all / amber some / grey none), section-level Select-All, and a grid of per-feature checkboxes.
- Bulk Select-All / Clear + Save / Reset on the toolbar.
- `auth.py` login and `/me` now resolve permissions via new `_effective_permissions` helper: **custom overrides > DB role defaults > code fallbacks**. Owner always full.

### New endpoints
- `GET  /api/permissions/catalog` — 13 sections × 84 features (labels + section-icon).
- `GET  /api/permissions/roles` — every role + its effective perms + whether it's DB-overridden.
- `POST /api/permissions/roles/{role}` — Owner sets a role's default (400 on `owner`).
- `DELETE /api/permissions/roles/{role}` — reset a role to code defaults.
- `GET  /api/permissions/staff/{id}` — now also returns `roleDefaults` + `usingRoleDefaults`.
- `DELETE /api/permissions/staff/{id}` — clear per-user override.

### Verified
- Catalog returns 13 sections × 84 features.
- Owner=84 · Manager=60 · Cashier=11 · Kitchen=6 built-in defaults.
- Owner-modification attempt → HTTP 400 "Owner permissions cannot be modified".
- Set Manager to `[pos, tables, kitchen, pre-shift, staff-roster, shift-swaps, products, customers, reservations, waitlist]` → persisted, `payroll=False`, `staff-roster=True`, `overridden=True`.
- Reset → back to 60 defaults, `overridden=False`.
- UI smoke test: role tiles, section progress bars (Sales 5/5 green, Kitchen 4/5 amber), per-feature toggles all render; Save toast confirms `"Saved 60 permissions for manager"`; staff-mode picker shows all non-owner staff; Reset toast confirms `"Reverted to role defaults"`.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (needs client IDs/secrets).
- **P1** SendGrid / Twilio production keys.
- **P1** Hardware Health polish.
- **P2** `ash` → `nua` backend namespace refactor.
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** Channel Menus per-channel pause/resume + schedule toggle UI.
- **P2** `x-ai-parsed-fallback` header on AI endpoints.
- **P2** Move `ai_weekly_plan` to a background task.


## v36.3 — Iteration 61 (Feb 2026): AI Menu Import review flow

### Shipped

**AI Menu Import — 3-stage flow with review before persistence** (`routes/menu_features.py`, `components/menu/AIMenuImportReview.jsx`)
- Replaced the one-shot "upload → items created blind" flow with **Preview → Review → Commit**.
- **`POST /menu/ai-preview`** — runs GPT-5.2 vision on the image (or `pypdf` on the PDF), fuzzy-matches each proposed category against existing DB categories (`difflib.SequenceMatcher`, score ≥ 0.55, contains-boost to 0.85). Attaches `suggestedModifierIds` for every item whose matched category is in a modifier's `assignedCategories`. Detects duplicates by name. **No DB writes.**
- **`POST /menu/ai-commit`** — accepts the reviewed items, writes them via `stamped_insert` (audit trail), honours `skipIfDuplicate` per-row.
- **UI** — new `AIMenuImportReview` dialog with 3 stages (upload / review / done):
  - Review table: editable name / category / price / cost, per-row include checkbox, tick-to-attach modifier chips (only modifiers assigned to that category are shown).
  - Category dropdown: existing categories in **green**, "New: X" fallback in **amber** with an inline note ("AI suggested 'BRUNCH' — will be created").
  - Live stats strip: Detected · Selected · Duplicates · Menu Value.
  - Margin column colour-coded (≥60% emerald, ≥40% amber, else red) so the owner can spot cost issues at a glance.
  - Bulk `Select all` / `Deselect all`.
  - Duplicates auto-deselected, flagged with an amber "already exists — will be skipped" warning.
- Legacy `/menu/ai-import` kept for backwards compat (also now fuzzy-matches categories + auto-attaches modifiers).

### Verified
- Preview on a 7-item menu image (Flat White, Cappuccino, Latte, Beef Burger, Chicken Schnitzel, Espresso Martini, Negroni): all 7 fuzzy-matched to existing categories (Coffee, Mains, Cocktails), all flagged as duplicates, "Selected=0 → Import 0 items" (correct).
- Preview on a fresh 5-item brunch menu (Avocado Smash Bruschetta, Ricotta Hotcakes, Green Goddess Bowl, Berry Kombucha, Golden Latte): 0 duplicates, new categories `BRUNCH` and `DRINKS` proposed in amber. Select-all + Commit → 5 products written with SKUs `AI-…`, `createdBy=owner@nua.com`, audit stamped.
- Duplicate skip: replaying the same commit → `created=0 skipped=3` with detailed `skippedDetails`.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (needs client IDs/secrets).
- **P1** SendGrid / Twilio production keys.
- **P1** Hardware Health polish.
- **P2** `ash` → `nua` backend namespace refactor.
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** Channel Menus per-channel pause/resume + schedule toggle UI.
- **P2** `x-ai-parsed-fallback` header on AI endpoints.
- **P2** Move `ai_weekly_plan` to a background task.


## v36.2 — Iteration 60 (Feb 2026): AI Menu Import + CSV Import fixes

### Shipped

**AI Menu Import — actually works now** (`routes/menu_features.py`, `MenuEngineering.jsx`)
- Root cause: the endpoint was passing a base64 image string as **plain text** to the LLM. GPT can't "see" a raw base64 blob — it saw random characters and returned nothing.
- Fix: images now travel via `emergentintegrations.ImageContent(image_base64=…)` so GPT-5.2 uses vision on the real menu. PDFs are handed to `pypdf` for text extraction first, then the extracted text is sent to the LLM.
- Extra hardening: strips `data:` URL prefix, tolerates JSON returned inside code fences, per-item defensive parsing, `stamped_insert` writes so every AI-created product lands in the audit trail. UI shows an error toast if `count == 0` instead of silent failure.
- Verified: 9 items extracted from a synthetic menu image (Flat White $5.20, Cappuccino $5.20, Long Black $4.80, Chai Latte $5.40, Beef Burger $16.50, Chicken Schnitzel $24.50, Fish & Chips $22.00, Chocolate Cake $8.50, Lemon Tart $7.80).

**CSV Import UX — no more silent failures** (`pages/Products.jsx`)
- Root cause: worked but felt broken — `alert("Imported undefined products")` on any error, `accept=".csv"` sometimes greyed out valid `.csv` files, no feedback on click failure.
- Fix: swapped `alert()` for `sonner` toasts (`loading` + `success` / `error`), quote-aware CSV splitter, validates `name` column, broadened `accept` to `.csv,text/csv,application/vnd.ms-excel,text/plain`, safe optional-chaining on the button click.
- Verified: 2/2 products imported → toast "Imported 2 of 2 products"; malformed CSV → toast "CSV must include a 'name' column".

### Deps
- `pypdf==6.14.2` added (PDF text extraction for AI menu import).

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (needs client IDs/secrets) — on hold per user.
- **P1** SendGrid / Twilio production keys — on hold per user.
- **P1** Hardware Health polish.
- **P2** `ash` → `nua` backend namespace refactor.
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** Channel Menus per-channel pause/resume + schedule toggle UI.
- **P2** `x-ai-parsed-fallback` header on AI endpoints.
- **P2** Move `ai_weekly_plan` to a background task.


## v36.1 — Iteration 59 (Feb 2026): Dashboard products & categories repair

### Shipped

**P0 bug fix — Empty POS dashboard + inactive alcohol categories** (`models/product.py`, `services/alcohol_seeder.py`)
- Root cause: `Product` Pydantic model required `cost`, `sku`, `image` fields. The alcohol seeder omitted them → `GET /api/products` returned **HTTP 500** on every load, so the POS grid never rendered. Additionally 14/19 categories were missing the `active` flag → the Categories admin page rendered them as "Inactive".
- Fix 1 — `Product` model: `category`, `cost`, `sku`, `image` now default to safe empty values so a legacy row never blows up the whole list.
- Fix 2 — `alcohol_seeder.py`: new categories/products are stamped with `active=True`, `sortOrder`, `channels`, `prepTime`, plus `cost` (derived from measured stock pour-cost, or 35% of price), `sku=ALC-…`, `image=""`, `active=True`, `eightySixed=False`, `gstRate=10`.
- Fix 3 — one-shot startup repair (`_repair_orphan_categories`, `_repair_orphan_products`): patches any legacy doc missing those fields so an existing DB self-heals on next boot without needing a wipe. Also normalises legacy lowercase icon names (beer/wine/glass) to the PascalCase keys the frontend icon map uses.
- Verified: `/api/products` → HTTP 200 with 100 items; `/api/categories` → 19 items, 0 inactive; POS smoke-test shows 100 tiles across 20 category tabs.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (needs client IDs/secrets).
- **P1** SendGrid / Twilio production keys.
- **P1** Hardware health monitoring polish (route exists, page skeletal).
- **P2** `ash` → `nua` backend namespace refactor (aliases already exist).
- **P2** `@dnd-kit` tablet-friendly DnD for Social Calendar.
- **P2** Channel Menus per-channel pause/resume + schedule toggle UI.
- **P2** `x-ai-parsed-fallback` header on AI endpoints so UI can warn on LLM fallback.
- **P2** Move `ai_weekly_plan` to a background task (35 LLM calls inline).
- **P2** Chargeback / dispute console UI polish.


## v36.0 — Iteration 58 (10 Feb 2026): Loyalty phase-2 + Kitchen server-notify + Ash Marketing + Beverage margin + Alcohol seed

### Shipped

**Notifications** (`services/notification_service.py`, `routes/notifications.py`, `components/NotificationBell.jsx`)
- Universal in-app notifications routed by email / role / topic — kinds: loyalty, kitchen, approval, marketing, referral, ash, system.
- Global floating bell (bottom-right, next to NUA FAB) with unread badge + 30 s polling + slide-out panel.
- Owner is super-user: sees all role-scoped notifications (marketing / manager / server / kitchen).

**Loyalty 2.0 Phase-2** (`routes/loyalty_v2.py`, `pages/LoyaltyProgress.jsx`)
- Earn notifications: badge / milestone awards fire simultaneous notifications to `role="marketing"` (for staff follow-up) and to the customer's email (respecting existing consent).
- Referral engine: `POST /loyalty/v2/referrals` creates a pending referral, `POST .../{id}/complete` issues **$20 referrer + $10 referee vouchers** and refreshes Insight #14. UI: dedicated Referrals tab with create + complete flow.
- Leaderboard: `GET /loyalty/v2/leaderboard?metric=points|visits|spend|referrals` — top-25 with rank medal styling. UI: dedicated Leaderboard tab with metric switcher.

**Kitchen server-notifications** (`routes/kitchen.py`)
- `fire-course` → notifies `serverId` (or role="server" fallback) with `Table X — Main fired` + link back to KDS.
- `mark_order_ready` → notifies with `Table X — order ready`.

**Ash Marketing autonomous draft** (`routes/ash.py`)
- `POST /nua/marketing/draft-campaign {goal}` — GPT-5.2 grounds on churning-cohort + slow-inventory, emits a full campaign JSON (name / objective / segment / channel / offer / copy / dates / expectedReach / expectedRevenue / risk / reasoning), enqueues it in the Approval Queue with source="ash_marketing", and pings the owner.
- Deterministic fallback (Weekend Winback template) so the endpoint never fails.

**Beverage margin (enhancement)** (`services/measured_inventory_service.py`, `routes/measured_inventory.py`)
- `beverage_cost(product_id)` → costPerPour derived from container cost / totalMeasure × deductAmount.
- `GET /measured-inventory/beverage-margin/{id}` → single product margin card.
- `GET /measured-inventory/beverage-margin` → P&L-ready roll-up of every measured beverage, sorted by margin %. Feeds NUA Finance and future Menu Engineering integration.

**Alcohol catalog seed** (`services/alcohol_seeder.py`, `server.py` startup hook)
- Idempotent on-startup seeder: 12 alcohol categories (Beer, Wine Red / White / Sparkling / Rosé, Cocktails, Spirits × 5, Liqueurs), 2 Drinks categories (Non-Alcoholic, Coffee & Tea).
- ~38 products: draft beers, cocktails (Espresso Martini, Negroni, Old Fashioned, Margarita, Aperol Spritz, Whisky Sour, Mojito), spirits (30ml pours), wine glasses / bottles.
- Every pourable product auto-links a StockUnit + SellVariant so beverage margin math is live from day one.

### Verified via curl
- 2 unread notifications after firing a kitchen course + completing a referral + drafting a campaign ✅
- Leaderboard by spend returns Sarah Johnson #1 ($1500) ✅
- Baileys 86.3%, Amaretto 83.7%, Vodka 83.6% pour margins ✅
- Fire course #2 on order KO-E638A17D → notification "Table 7 — Main fired" ✅
- 12 alcohol categories seeded on startup ✅
- Referral created + completed → $20 & $10 vouchers issued to both parties ✅
- Ash Marketing draft → Weekend Winback campaign queued in Approvals ✅

### Files added / touched
- backend/services/notification_service.py           NEW
- backend/routes/notifications.py                    NEW
- backend/services/alcohol_seeder.py                 NEW
- backend/routes/loyalty_v2.py                       earn-notify + referrals + leaderboard
- backend/routes/kitchen.py                          fire/ready notify hooks
- backend/routes/ash.py                              draft-campaign endpoint
- backend/services/measured_inventory_service.py     beverage_cost()
- backend/routes/measured_inventory.py               beverage-margin endpoints
- backend/server.py                                  notifications router + alcohol seed hook
- frontend/src/components/NotificationBell.jsx       NEW (global bell)
- frontend/src/App.js                                bell mounted in layout
- frontend/src/pages/LoyaltyProgress.jsx             Leaderboard + Referrals tabs

---


## v35.0 — Iteration 57 (10 Feb 2026): Measured / Fractional Stock (Phase 1)

### Shipped

- **Five new BaseEntity models** in `backend/models/measured_inventory.py`:
  `UomConversion`, `StockUnit`, `SellVariant`, `OpenContainer`, `WastageEvent`.
  All extend BaseEntity, all writes route through `stamped_insert` /
  `stamped_update`, all audit-logged.
- **`backend/services/measured_inventory_service.py`** — `deduct_on_sale`
  (hooked in `transactions.py`), auto-open-container, overdraw rollover,
  `apply_wastage_to_container`, `reorder_available`, `reconcile_stocktake`.
  Built-in ml↔l and g↔kg conversion table + owner-configurable UomConversion
  override.
- **`backend/routes/measured_inventory.py`** at `/api/measured-inventory/*` —
  CRUD for stock-units, sell-variants, open-containers, wastage,
  stocktake-reconcile, and a per-product summary endpoint for the UI.
- **Ash Intelligence updated**:
  • Insight #2 (theft) now includes pour-variance signals from flagged reconciles.
  • Insight #6 (waste) now includes wastage-event spikes (≥3 events or
    ≥500 units in 7 days per stock unit).
  • Insight #11 (purchasing) now folds partial container equivalents into
    "available stock" so kegs mid-pour aren't invisible to reorder logic.
- **Frontend**: `MeasuredStock.jsx` — grouped-by-station live containers with
  remaining measure + progress bar + estimated serves; setup dialog to link
  a product with stock units + sell variants; wastage modal; reconcile modal
  showing theoretical vs counted + variance result. Registered in Sidebar
  under Menu Engineering → Measured Stock.

### Verified (curl + python asyncio)
- AC #1: 5 × 150ml sales on a 750ml bottle → closes at 0 ✅
- AC #2: overdraw of a bottle at 100ml by a 150ml glass → closes bottle 1
  at 0 and auto-opens bottle 2 at 700ml (750 − 50 overdraw) ✅
- AC #3: 4 wastage events / 480 units surfaced in Insight #6 as a warning ✅
- AC #4: reconcile with 27.3% variance → Insight #2 fires severity=high ✅
- AC #5: Insight #11 for a product with an open container shows
  `available 0.93 < par 5` (sealed 0 + partial 0.93) ✅
- AC #6: 20 audit_events written across stock_unit, open_container,
  wastage_event, stocktake_reconcile with actor/device/version stamped ✅
- AC #7: whole-unit products with no SellVariant behave identically —
  `deduct_on_sale` returns `{measured: False}` and the existing
  `$inc: stock -1` continues to fire ✅

### Files added / touched
- backend/models/measured_inventory.py                 NEW
- backend/services/measured_inventory_service.py       NEW
- backend/routes/measured_inventory.py                 NEW
- backend/server.py                                    router registered
- backend/routes/transactions.py                       hook in deduct_on_sale
- backend/services/ash_intelligence.py                 insights #2, #6, #11 updated
- frontend/src/pages/MeasuredStock.jsx                 NEW
- frontend/src/App.js                                  route registered
- frontend/src/components/Sidebar.jsx                  entry under Menu Engineering
- memory/NUA_POS_Master_Roadmap_v1.txt                 §7.7 updated

---


## v34.0 — Iteration 56 (10 Feb 2026): NUA rebrand · Kitchen course hold/fire + docket enrichment · Master Roadmap doc

### Shipped

**Rebrand — Ash → NUA (user-facing)**
- Legacy floating `AskNua` button removed; the "Ask NUA" experience now lives inside the unified NUA FAB as the default persona.
- All 6 personas relabeled: `Ask NUA` (executive), `NUA Finance`, `NUA Ops`, `NUA HR`, `NUA Marketing`, `NUA Guest`.
- Sidebar labels & page titles updated: **NUA Command Center**, **NUA Planner**, **NUA Permissions**, **NUA Memory**, **NUA Intelligence**, **NUA Autonomy Controls**.
- Agent system prompt updated so the AI refers to itself as **NUA** in every reply.
- New `NuaAliasMiddleware` in `server.py` rewrites `/api/nua/*` → `/api/ash/*` at the ASGI level — both routes work; frontend now uses `/api/nua/*` exclusively.

**Kitchen — Course Hold/Fire + Docket Enrichment**
- New per-course lifecycle: `queued → held → fired → served` stored under `KitchenOrder.courses[c]` with `heldAt`, `firedAt`, `firedBy`, `servedAt`.
- New endpoints: `POST /api/kitchen/orders/{id}/hold-course/{c}`, `.../fire-course/{c}`, `.../serve-course/{c}`.
- Kitchen order creation auto-enriches every docket with:
  - `createdByName` / `createdByEmail` (staff who put through the order).
  - `deviceLabel` / `deviceId` (from `X-Device-Label` header or user-agent).
  - `covers` (from reservation or manual entry).
  - `guestName` (from reservation).
- Owner-configurable docket display via `GET/PUT /api/kitchen/docket-config` — 11 toggles + fontSize + warn/critical thresholds. UI in `Kitchen.jsx` behind the "Docket" button (owner/manager only).
- Redesigned `Kitchen.jsx` order card: docket meta row (staff · device · covers · guest · in-time), courses as coloured groups with per-course Hold/Fire/Serve controls, elapsed timer with tri-tone warn/critical, all fields respect owner toggles.

**Master Roadmap document**
- Authored `/app/memory/NUA_POS_Master_Roadmap_v1.txt` — single source of truth covering: vision · principles · tech stack · repo layout · Universal Entity Model · full NUA/Ash intelligence layer (6 personas, 25 tools, planning engine, simulation, memory, health score) · module-by-module inventory (28 sections) · security · analytics · user matrices · data models · 24-month prioritised roadmap · chronology · glossary.

### Verification (smoke-tested via curl)
- `GET /api/nua/personas` returns 6 renamed labels.
- `GET /api/ash/personas` (legacy) still works — 6 items.
- Kitchen order created with `X-Device-Label: Front POS` header captures `deviceLabel="Front POS"`, `createdByName="Owner"`, `covers=4`.
- `fire-course/2` sets `courses.2.status="fired"`, `firedAt`, `firedBy="Owner"`.
- `hold-course/3` sets `courses.3.status="held"` + `heldAt`.
- `PUT /kitchen/docket-config` accepts partial patches (`showCovers=false`, `fontSize=large`, `warnMinutes=10`).

### Files touched / added
- `/app/backend/server.py` — NuaAliasMiddleware.
- `/app/backend/services/ash_personas.py` — persona labels + tone updated.
- `/app/backend/services/ash_agent.py` — self-refers as NUA.
- `/app/backend/models/kitchen_order.py` — enriched fields + courses map.
- `/app/backend/routes/kitchen.py` — hold/fire/serve endpoints + docket-config CRUD + docket auto-enrichment.
- `/app/frontend/src/pages/Kitchen.jsx` — full redesign for course lifecycle + docket meta + settings dialog.
- `/app/frontend/src/services/api.js` — kitchenAPI methods for hold/fire/serve/config.
- `/app/frontend/src/App.js` — removed legacy AskNua button.
- `/app/frontend/src/components/AshChat.jsx` — Ask NUA default persona label, warmer suggestions, `Sparkles` icon.
- `/app/frontend/src/components/Sidebar.jsx` — NUA-branded labels.
- `/app/frontend/src/components/BottomDock.jsx`, `pages/AgentDashboard.jsx`, `pages/AgentAutonomy.jsx`, `pages/Vouchers.jsx`, `pages/AshDashboard.jsx`, `pages/AshMemory.jsx`, `pages/AshPermissions.jsx`, `pages/AshPlans.jsx`, `pages/AshCommandCenter.jsx`, `pages/NuaPro.jsx`, `components/VoiceCommandCatalog.jsx` — user-visible "Ash" → "NUA".
- **Deleted**: `/app/frontend/src/components/AskNua.jsx` (merged into AshChat FAB).
- **New**: `/app/memory/NUA_POS_Master_Roadmap_v1.txt`.

### Test credentials
- `owner@nua.com` / `NuaOwner2026!`

---


## v33.0 — Iteration 55 (10 Feb 2026): Ash v3 Phases 4–19 + Loyalty 2.0

### Shipped

**Ash Personas** — `services/ash_personas.py`, `services/ash_agent.py`
- 6 specialised Ash identities: **Executive** (all modules, chief-of-staff), **Finance** (CFO), **Ops** (kitchen/inventory), **HR** (people), **Marketing** (CMO), **Guest** (hospitality).
- Each persona owns a tone, focus, colour, icon and a module allowlist that filters which of the 25 tools it may invoke.
- Agent loop now accepts `persona` param — swaps system prompt and refuses tools outside remit ("switch to Ash Finance").
- Endpoints: `GET /api/ash/personas`, `POST /api/ash/agent {message, persona}` returns `persona` + `personaLabel`.
- Frontend `components/AshChat.jsx` — persona picker in the FAB header, colour-themed FAB icon per persona, per-persona suggestion prompts, session resets on persona swap.
- **Bug fix** — `_extract_json` in `ash_agent.py` now has a regex last-resort so the `{"action":"final","reply":"..."}` envelope can never leak into the user-visible reply.

**Ash Planner** — `services/ash_planner.py`, `pages/AshPlans.jsx`
- `POST /api/ash/plans/generate {goal, persona?}` — GPT-5.2 proposes a 2-6 step plan, each step maps to a real tool from the catalog (steps referencing unknown tools are marked `invalid` and dropped from execution).
- Persisted lifecycle: `proposed → executing → awaiting_approvals → completed | partial_failed | rejected`.
- Endpoints: `GET /plans`, `GET /plans/{id}`, `POST /plans/{id}/approve` (walks all pending steps), `POST /plans/{id}/reject`, `POST /plans/{id}/steps/{idx}/approve`, `POST /plans/{id}/steps/{idx}/reject`.
- Every step goes through the tool permission gate — write tools respect the same Approval Queue as manual invocations.

**Ash Plan Simulation ("Digital Twin")** — `services/ash_planner.py::simulate_plan`
- `POST /plans/{id}/simulate` — dry-run: read-only steps execute normally, write steps are DESCRIBED not executed.
- GPT-5.2 writes a projected-impact narrative; UI shows per-step simulation in an expandable panel before Approve.

**Ash Memory** — `services/ash_memory.py`, `pages/AshMemory.jsx`
- Long-term structured store: `{scope, kind, text, confidence, source, usageCount}` where `kind ∈ {preference,pattern,fact,note}` and scope is `global | customer:<id> | staff:<id> | product:<id> | supplier:<id>`.
- `remember()` is upsert-style: same `(scope, text)` reinforces (+0.1 confidence, no duplicates).
- Memories are injected into every agent turn via `context_pack(scope)` — Ash grounds every reply in what it's already been taught.
- Endpoints: `GET /ash/memory`, `GET /ash/memory/scopes`, `POST /ash/memory`, `DELETE /ash/memory/{id}` + `remember` and `recall` tools added to `ash_tools` (both auto-permission).
- UI: teach-new-fact dialog, kind/scope filters, scope chips with counts.

**Ash Permissions UI** — `pages/AshPermissions.jsx`
- Dedicated permissions surface (was previously a tab in Command Center) — module-grouped cards, live counts of auto/approval/disabled, search, module & risk filters, per-module batch-set buttons ("All approval", "All disabled").
- Same PUT `/ash/tools/{name}/permission` backend as before.

**Loyalty 2.0** — `routes/loyalty_v2.py`, `pages/LoyaltyProgress.jsx`
- **Badges** (10 seeded): First Visit, Regular, Loyalist, Century Club, Big Spender, VIP Whale, Early Bird, Wine Buff, Community Builder, Birthday Guest — each with icon, colour, condition string, awarded points.
- **Milestones** (6 seeded): 5/25 visits and $100/$500/$2000/$5000 spent with tiered rewards (voucher | points | tier bump).
- **Seasonal Challenges** — owner-authored, time-boxed missions (`metric`, `target`, `startDate`, `endDate`, `reward`); per-customer progress tracked in `customer_challenge_progress`.
- **Tier progression** — server computes current tier, next tier, points-needed, percent-complete for the UI hero card.
- `POST /loyalty/v2/evaluate/{cid}` idempotent — composite keys `(customerId, badgeId)` and `(customerId, milestoneId)` prevent double-award.
- Endpoints: `GET/POST/PATCH/DELETE /loyalty/v2/challenges`, `GET /loyalty/v2/progress/{cid}`, `POST /loyalty/v2/evaluate/{cid}`, `GET /loyalty/v2/{badges,milestones}`.

### Verification (Iteration 55)
- Backend: **32/32 pytest cases pass** (~91s) at `/app/backend/tests/test_iteration55_p0_p2.py`.
- Personas / Planner / Simulation / Memory / Permissions / Loyalty 2.0 all green. Zero regressions on Ash insights, health-score, briefing, chat, approvals, finance, audit, HQ.
- JSON-envelope leak from iter54 confirmed FIXED — `reply` field is always clean prose.

### Files added
- `/app/backend/services/ash_personas.py`
- `/app/backend/services/ash_planner.py`
- `/app/backend/services/ash_memory.py`
- `/app/backend/routes/loyalty_v2.py`
- `/app/frontend/src/pages/AshPlans.jsx`
- `/app/frontend/src/pages/AshPermissions.jsx`
- `/app/frontend/src/pages/AshMemory.jsx`
- `/app/frontend/src/pages/LoyaltyProgress.jsx`

### Test credentials
- `owner@nua.com` / `NuaOwner2026!`

---


## v32.0 — Iteration 53 (10 Feb 2026): Ash goes always-on + conversational; Finance page modularised

### Shipped
**Ash Scheduler** — `services/ash_scheduler.py`
- Boots on backend startup as an asyncio background task.
- Runs `run_all_insights()` every `ASH_HOURLY_SECONDS` (default 3600s).
- Once per day at `ASH_DAILY_DIGEST_HOUR` (default 8 UTC), generates the weekly summary via GPT-5.2 + pulls top open high/warning insights, then dispatches through `utils.notifications.send_email` (log-only fallback if SendGrid isn't wired).
- Persists a per-day record in `db.ash_digests` so re-runs are idempotent.
- Endpoints: `GET /api/ash/scheduler/status`, `POST /api/ash/scheduler/digest-now` (owner/manager — force regenerate even before digest hour).
- Cleanly cancels on shutdown.

**Ash Chat** — `routes/ash.py::/chat`
- Conversational surface grounded on the last 30 audit events + 20 open insights + pending-approval count.
- POST `/api/ash/chat` with `{ message, sessionId?, context? }` → returns `{ sessionId, reply, context }`.
- GPT-5.2 (Emergent Universal Key) authors the response; deterministic fallback surfaces the top open insight if the LLM is unreachable — endpoint always returns a non-empty reply.
- `GET /api/ash/chat/history/{sessionId}` returns the full session in ascending order.
- Session logs stored in `db.ash_chat_log`.
- Frontend `components/AshChat.jsx` — floating FAB (bottom-right) with pulse indicator; expandable 96×540 panel with gradient header, minimize/close, 5 seeded suggestion prompts, "Ash is thinking…" indicator, context badges (audit/insights/approvals), persistent session in localStorage keyed per user email, "Reset conversation" link.
- Mounted globally inside `StaffLayout` — available on every authenticated page.

**Finance Ledger split** — `pages/finance/*`
- `pages/FinanceLedger.jsx` is now a slim 45-line router.
- 7 modular components extracted: `Overview`, `Reports`, `AccountsPayable`, `AccountsReceivable`, `BankRec`, `Journals`, `ChartOfAccounts`.
- Shared helpers `pages/finance/helpers.js` (FMT, today, fyStart).
- All `data-testid`s preserved for regression safety.

### Verification (Iteration 53)
- Backend: 9/9 pytest cases pass (`/app/backend/tests/test_iteration53_scheduler_chat.py`).
- Frontend: 100% — FAB present on `/finance`, `/ash`, `/approvals`; chat send flow shows user bubble → thinking indicator → Ash bubble with context badges; persistence across page navigation confirmed; minimise/expand/close all clean.
- Two testing-agent code-review nits fixed post-report: `logging` import added to `routes/ash.py`; `_maybe_send_daily_digest(force=True)` bypass added for manual triggers; AshChat localStorage now scoped per user email.

### Test credentials
- `owner@nua.com` / `NuaOwner2026!`

---


## v31.0 — Iteration 52 (9 Feb 2026): Product-Vision Refactor — AI-powered Hospitality Operating System

### Foundation shipped (Phase 1)
- **`/app/MISSION.md`** — product vision, principles, universal entity model, Ash's 16 responsibilities, approval-queue policy, franchise topology.
- **`models/base_entity.py`** — `BaseEntity` / `LocationEntity` mixin with `id, businessId, locationId, createdBy, createdAt, updatedBy, updatedAt, deletedAt, deletedBy, device, ip, version`.
- **`middleware/actor_context.py`** — Starlette middleware puts actor (email/role from JWT), device (UA), IP (X-Forwarded-For aware), businessId (X-Tenant-Id), locationId (X-Location-Id) into a `ContextVar` for the request lifetime.
- **`services/audit_service.py`** — universal `audit_events` log (who/when/device/ip/before/after/severity/tags).
- **`services/entity_service.py`** — `stamped_insert`, `stamped_update` (auto-snapshots into `entity_versions`), `soft_delete`, `hard_delete` (GDPR purge), `get_history`, `restore_version`.
- **`routes/audit.py`** — `/api/audit/events`, `/api/audit/history/{type}/{id}`, `/api/audit/restore/{type}/{id}/{version}`, `/api/audit/purge/{type}/{id}`, `/api/audit/summary`.

### Entity retrofit (Phase 2)
- Customer create/update, Product create/update/delete now go through `stamped_insert`/`stamped_update`/`soft_delete`. Legacy docs are stamped on next update.
- POS transaction create emits an audit event (`transaction:created` with full snapshot).
- Manual journal creation emits an audit event.

### Approval Queue (Phase 3)
- **`services/approval_service.py`** — policy engine:
  - `AI_APPROVAL_MODE=thresholds|strict|off` (default `thresholds`)
  - `AI_APPROVE_PO_ABOVE=500`, `AI_APPROVE_REFUND_ABOVE=100`, `AI_APPROVE_TIER_DOWNGRADES=1`
  - `enqueue_or_execute(...)` — the ONE call-site every automated action goes through. Enqueues an approval if policy demands it; executes immediately otherwise.
- **`routes/approvals.py`** — `/api/approvals` (list, filter by status), `/api/approvals/{id}` (get), `/api/approvals/{id}/approve` (owner/manager — runs the action), `/api/approvals/{id}/reject` (with reason), `/api/approvals/pending/count`, `/api/approvals/config/policy`.
- **Rules Engine hooked** — every rule action now flows through `enqueue_or_execute`. Verified curl: a `create_purchase_order` action with estimatedCost $1250 correctly enqueued instead of executing. After approval, the action ran and produced a purchase order.

### Franchise / HQ Roll-up (Phase 4)
- **`routes/hq.py`** — `/api/hq/brands`, `/api/hq/locations`, `/api/hq/kpi-roll-up?days=`, `/api/hq/leaderboard`.
- Frontend `pages/HQDashboard.jsx` (`/hq`) — network-wide revenue card + per-location breakdown + 30-day leaderboard with medals.

### Ash — the Autonomous Operating Layer (Phase 5)
- **`services/ash_intelligence.py`** — **16 stateless generators**:
  1. `predict_staffing_shortage` (roster vs bookings)
  2. `detect_theft_signals` (voids by cashier)
  3. `detect_fraud_signals` (refund velocity)
  4. `recommend_pricing` (margin < 30% → suggested price for 35%)
  5. `suggest_promotions` (slow-movers)
  6. `predict_food_waste` (ingredient expiry vs pull rate)
  7. `detect_labour_anomalies` (wages ÷ revenue > 35%)
  8. `detect_menu_underperformance` (< 20% of median unit sales)
  9. `forecast_weather_impact` (cover swing heuristic)
  10. `forecast_public_holiday_demand` (AU holiday lookup)
  11. `recommend_purchasing` (par-level reorder)
  12. `recommend_roster_changes` (bookings vs shifts)
  13. `predict_staff_burnout` (>80h in 14 days)
  14. `predict_customer_churn` (days-since-visit vs tier)
  15. `recommend_menu_engineering` (Star/Puzzle/Plow-Horse/Dog quadrants)
  16. `generate_weekly_summary` — **the one LLM call** (GPT-5.2 via Emergent Universal Key) narrates the week's KPIs; falls back to a deterministic template if the key is missing.
- **`routes/ash.py`** — `/api/ash/insights`, `/api/ash/insights/summary`, `/api/ash/capabilities`, `POST /api/ash/run`, `POST /api/ash/summary/weekly`, `POST /api/ash/insights/{id}/dismiss`.
- Frontend `pages/AshDashboard.jsx` (`/ash`) — KPI header, category tabs, insight cards with dismiss + recommendedActions, capability strip. Screenshot verified.

### Frontend also shipped
- `/approvals` — pending queue + policy banner + approve/reject dialogs.
- `/audit` — full mutation log with actor/entity/action filters and before/after diff drawer.
- Sidebar updated with 4 new links: Ash Intelligence · HQ Roll-up · Approvals · Audit Log.

### Verification (curl smoke-tests)
- `POST /api/ash/run` → 3 promotion insights generated (slow-mover heuristic on real DB products).
- `POST /api/rules` create rule with `create_purchase_order` param `estimatedCost=1250` → `POST /api/rules/emit` returned `outcome.result.status = pending_approval`.
- `POST /api/approvals/{id}/approve` executed the action → `purchaseOrderId` returned.
- `GET /api/audit/summary` reports actors/entities/actions correctly (owner@nua.com most active).
- `GET /api/hq/leaderboard` returns location rankings.
- `GET /api/hq/kpi-roll-up?days=30` returns $966 network revenue over 10 covers.

---


## v30.0 — Iteration 51 (9 Feb 2026): Enterprise Double-Entry Accounting · Cross-Module Rules Engine

### Shipped
**Enterprise Finance & Accounting (double-entry)**
- `services/accounting_service.py` — full ledger engine:
  - Idempotent seed of hospitality Chart of Accounts (39 accounts: assets 1xxx, liabilities 2xxx, equity 3xxx, revenue 4xxx, COGS 5xxx, expenses 6xxx). GST/PAYG/Super/Gift-Card/Voucher liability accounts pre-wired.
  - `post_entry(...)` — validates `sum(debits) == sum(credits)`, blocks debit+credit on same line, auto-numbers `JE-000001`, enriches account names, and is idempotent by `sourceType + sourceRef` so hooks are safe to re-fire.
  - `reverse_entry(...)` — creates an opposite balancing journal, links `reversedBy`.
  - Reports as read-only aggregations over `journal_lines`: `trial_balance`, `profit_and_loss`, `balance_sheet`, `cash_flow` (direct method), `general_ledger(code)`.
  - Auto-post hooks: `auto_post_pos_sale`, `auto_post_refund`, `auto_post_gift_card_sale`, `auto_post_voucher_redeem`, `auto_post_bill`, `auto_post_bill_payment`, `auto_post_invoice`, `auto_post_invoice_receipt`, `auto_post_payroll_run`, `auto_post_customer_deposit`, `auto_post_deposit_applied`.
- `models/accounting.py` — `Account`, `JournalEntry`, `JournalLine`, `Bill`, `Invoice`, `CustomerDeposit`, `Budget`, `BudgetLine`, `BankStatementLine`.
- `routes/accounting.py` — 30+ endpoints under `/api/accounting/*`: accounts CRUD, journals CRUD + reverse, bills (AP) CRUD + pay, invoices (AR) CRUD + receive, deposits, bank rec (statement, import, match, ignore, auto-suggest 3-day window), budgets, KPIs, and 5 reports (trial-balance, profit-loss, balance-sheet, cash-flow, general-ledger, budget-vs-actual).
- COA seeds automatically on backend startup.
- POS sale, refund, and gift-card sale flows auto-post to the ledger. Manual journals + full history + reversal all available.
- Frontend `pages/FinanceLedger.jsx` (`/finance`) — 7-tab workspace:
  1. **Overview** — 6 live KPI cards (Revenue FYTD, Gross/Net Profit + margin %, Cash on Hand, AR/AP outstanding).
  2. **Reports** — P&L, Balance Sheet, Trial Balance, Cash Flow with date range picker.
  3. **Bills (AP)** — create + pay with double-entry posting.
  4. **Invoices (AR)** — create + receive with double-entry posting.
  5. **Bank Rec** — import statement lines + auto-suggested journal matches within a 3-day window.
  6. **Journals** — manual entries with live balance-check, reversal button, source-type badges.
  7. **Chart of Accounts** — grouped by type, add/delete non-system accounts.
- Sidebar link "Finance Suite" under Accounting; BottomDock too.

**Cross-Module Rules Engine ("Automation Brain")**
- `services/rules_engine.py` — event bus + condition evaluator + action library:
  - **24 events** across POS, Commerce, Inventory, CRM, Bookings, Labour, Kitchen, Finance (`EVENT_CATALOG`).
  - **12 actions**: `dock_notify`, `send_email`, `send_sms`, `create_purchase_order`, `upgrade_vip_tier`, `apply_customer_credit`, `issue_voucher`, `dispatch_task`, `post_journal`, `mark_dish_86`, `apply_discount`, `webhook`.
  - Condition DSL: `{path, op, value}` clauses combined via `mode: all|any`. Ops: eq, ne, gt, gte, lt, lte, in, not_in, contains, starts_with, exists.
  - `emit_event(...)` matches active rules by `triggerEvent`, evaluates conditions, executes actions in priority order, records the whole run in `db.rule_executions`.
  - `safe_emit(...)` fire-and-forget helper used by producers.
- `routes/rules_engine.py` under `/api/rules/*` — CRUD, toggle, catalog, stats, `/emit`, `/simulate`, execution history, event history, and `/ai-build` (GPT-5.2 via Emergent LLM Key returns a valid rule spec from a plain-English prompt).
- Cross-module producers hooked: POS transactions emit `pos.sale.completed` + `inventory.low_stock|stockout`; refunds emit `pos.refund.issued`; customer creation emits `customer.created`; reservations emit `booking.created`.
- Frontend `pages/AutomationTriggers.jsx` completely rebuilt to talk to the new engine — 3 tabs (Rules · History · Events & Actions), 4 KPI cards, AI Builder dialog, full clause editor with dropdown operators, per-action params JSON editor, and a Simulator that dry-runs a payload against a rule.

**Data models used**
- Backend collections: `accounts`, `journal_entries`, `bills`, `bill_payments`, `ar_invoices`, `ar_receipts`, `customer_deposits`, `budgets`, `bank_statement_lines`, `rules`, `rule_events`, `rule_executions`, `notifications`, `tasks`, `purchase_orders`.

### Verification (backend curl)
- COA seed idempotent (39 accounts, 0 duplicates on re-seed).
- Manual journal posts + trial-balance balanced.
- Unbalanced journal returns 400.
- POS transaction auto-posts to bank/sales/GST; P&L, BS, Cash Flow all reflect the sale correctly.
- Bill create + pay produces two balanced journals; Invoice + receipt likewise.
- Rules engine: created rule, simulated with payload, emitted event → both actions fired (dock_notify + upgrade_vip_tier), stats and history reflect the firing.
- AI Builder with GPT-5.2 returned a fully populated rule spec (event, conditions, actions) for a plain-English restock prompt.

### Test credentials
- `owner@nua.com` / `NuaOwner2026!`

---


## v29.0 — Iteration 49-50 (9 Jul 2026): Customer Commerce Platform · Universal Voucher Engine · Unified Wallet · AI Personalisation

### Shipped
**Models**
- `models/voucher.py` — Universal Voucher schema. Fields: HMAC-signed `qrPayload`, human-readable `code` (NUA-XXXX-XXXX), `sourceType` (promotion|refund|gift_card|referral|birthday|anniversary|staff|corporate|event|manual), `valueType` (amount|percentage|free_item), `usageType` (one_time|multi_use|unlimited), `partialRedeemable` with `residualValue` tracking, comprehensive `rules` (weekdays, times, min_spend, eligible/exclude items/categories, locations, channels, first_visit_only, club_only, happy_hour_only), full `redemptions[]` audit trail (staff/terminal/txn/location/timestamp).
- `models/wallet_ledger.py` — signed ledger entries per customer per bucket (points, store_credit, gift_card, voucher, cashback, referral). Every movement snapshots `balanceAfter`. Balance = sum of `sign*amount` per bucket.

**Backend `routes/commerce_v29.py`** (registered) — 22 endpoints:
- **Vouchers**: POST /vouchers, POST /vouchers/bulk, GET /vouchers, GET /vouchers/{id}, GET /vouchers/lookup/{code}, POST /vouchers/validate, POST /vouchers/redeem (with 409 duplicate guard + partial residual), POST /vouchers/{id}/revoke.
- **Wallet**: GET /wallet/{cid}, POST /wallet/{cid}/credit, POST /wallet/{cid}/debit (with balance guard), GET /wallet/{cid}/timeline (merged bookings + orders + refunds + ledger + vouchers + reviews, DESC, with LTV + totalOrders).
- **Refunds**: POST /refunds/flexible with split modes (card | store_credit | points | voucher) — each split writes correct ledger entries and auto-issues refund vouchers.
- **AI Promotion Builder**: POST /ai/promotion-goal — LLM-first (openai/gpt-4o-mini via Emergent Universal Key) with heuristic fallback library, returns name + voucherTemplate + rules + smsCopy + emailBody + estimatedROI.
- **Analytics**: GET /promo-analytics/summary (issued, redeemed, redemptionRate, faceValue, revenueGenerated, bySource breakdown).
- **Loyalty 2.0**: GET /loyalty/status/{cid} — tier (Bronze→Silver→Gold→Platinum→VIP), nextTier + progress, totalVisits, totalSpend, weekly streak, 6 milestones with progress bars, auto-award to `db.loyalty_awards`, badges list. POST /loyalty/award.
- **AI Personalisation**: GET /personalisation/{cid} — favourite items, typical hour/weekday, days since last visit, avg check → personalised recommendations (winback/favourite/high_value/time_based) each with a ready-to-issue offer payload.
- **Gift Card 2.0**: POST /gift-cards/schedule (deferred delivery), POST /gift-cards/{id}/reload (top-up existing balance).

**Frontend**
- `pages/Vouchers.jsx` (route `/vouchers`) — 5-KPI analytics strip, filterable table (status/source/search), Issue dialog with all rule toggles + bulk count, Detail dialog with the signed QR + full audit trail, AI Promotion Builder tab (goal → complete campaign → "Turn into voucher" auto-fills the form).
- `components/customers/CustomerWalletPanel.jsx` — embedded in customer profile: 6 balance buckets + tier + streak + loyalty progress + milestones + tabs (Vouchers / Journey / AI Recs). One-click voucher issue from any recommendation.
- `components/payments/RefundDialog.jsx` — flexible refund UI with add-split buttons per mode, live totals, per-mode extras (points-per-dollar, voucher label + expiry). Wired into `pages/Accounting.jsx`.
- API service methods for all 22 endpoints in `services/api.js`.

**Regression fixes in Iter 50**
- `GET /api/transactions` and `GET /api/gift-cards` — safe_parse_list + `_id:0` projection (were 500ing due to leaked ObjectId).
- Voucher redeem: dupe transactionId check moved BEFORE rules → returns proper 409, not 400 "max reached". Partial vouchers now decrement residual freely until 0 (not blocked by max_redemptions=1).

### Tests
- Iter 49: 22/25 backend PASS · 3 bugs found · frontend surfaces verified.
- Iter 50 retest: **35/35 backend PASS · all 3 bugs verified fixed · zero regressions**. Full v29 suite green.


## v28.1 — Iteration 48 (8 Jul 2026): Australian Payroll Compliance · BAS Worksheet · Wallet Creds UI · AI Bundle Discovery

### Shipped
- **`utils/au_payroll.py`** — self-contained Australian compliance engine:
  - **PAYG withholding** — ATO Schedule 1 (Nov 2023) coefficient formula for weekly Scale 1/2/3, fortnight/monthly scaling per Sch 1 §7, HELP/STSL 8% loading above threshold.
  - **Super Guarantee** — tiered by pay date (10.5→11.0→11.5→12.0%), computed on OTE only (excludes overtime), capped at quarterly max contribution base, due-by = quarter-end + 28d per SGAA.
  - **Modern Award penalty matrix** — casual +25%, Sat +25%, Sun +50%, PH +150%, night after 10pm +10%, OT ×1.5 first 2h then ×2.
  - **NES leave accrual** — 152h annual + 76h personal + LSL per year; zero for casuals.
  - **STP2 pay-event JSON** — full shape (employer/period/employees/totals) ready for SBR2 submitters.
  - **Roster compliance checker** — flags AWARD_MAX_DAILY, MEAL_BREAK_MISSING, REST_BREAK_MISSING, MIN_SHIFT_LENGTH.
- **`routes/payroll.py`** — 8 endpoints:
  - `POST /payroll/payrun/calculate` — timecards → award-aware rows + totals + compliance meta.
  - `POST /payroll/payrun/commit` — persists + auto-builds STP2 event (`stpStatus:'ready_to_submit'`).
  - `GET /payroll/register?days=90` — pay run history + KPIs.
  - `GET /payroll/ytd/{staffId}` — YTD gross/PAYG/super/net/hours.
  - `GET /payroll/payslip/{runId}/{staffId}/pdf` — Fair Work Reg 3.46-compliant payslip PDF.
  - `POST /payroll/stp/build` — STP2 event body for any run (SBR2-ready).
  - `GET /payroll/roster-compliance` — Fair Work + Award violations for upcoming shifts.
  - `GET/POST /settings/wallet-credentials` — owner-only env plumbing; DB-persisted; loaded at startup.
- **`analytics.py::GET /bas-gst/worksheet`** — full ATO **NAT 4189** worksheet (G1–G20, W1–W5, T1) with summary (`gstToPay/gstToClaim/paygWithheld/paygInstalment/totalOwing/refundDue`). Reconciles POS transactions + expenses + committed pay runs into the exact labels the BAS form requires.
- **`v26_commerce.py::GET /promotions/bundle-suggestions`** — AI Bundle Discovery via Apriori-lite market-basket analysis. Scans last N days, counts 2/3-item combos with `min_support`, proposes a bundle price 15% below average à-la-carte, floored to `COGS × 1.5` (guarantees ~33% margin). Returns support%, confidence (high/med/low), estimated savings.
- **Frontend `Payroll.jsx`** — 3 tabs (Pay Run / Register / Roster Compliance), KPI cards, compliance badges (`ATO Sch 1 (Nov 2023)`, `SG 12%`, `Super due 2026-10-28`), row table with leave accrual per period, register listing, compliance flag chips per shift.
- **Frontend `BasWorksheetPanel`** — sits at the top of `/bas-gst`. Renders all G/W/T labels in three columns with a dedicated Summary card, date-range picker, CSV export.
- **Frontend `WalletCredentialsPanel`** — new Settings > Wallet Passes tab. Owner pastes Apple Pass Type ID + Team ID + 3 PEMs + Google Issuer ID + Class ID + service-account JSON. Shows "Production ready" / "Preview mode" per provider. Secrets never re-displayed.
- **Frontend AI Bundle Discovery** — new block inside `PromotionDialog` (create mode). One click calls the market-basket endpoint and lists the top 6 combos (triples first) with the à-la-carte-vs-proposed price and support/confidence. Clicking a suggestion auto-fills the form (fixed_price + bundlePrice + products + minQuantity).

### Iter 48 Tests
- Backend: 14/14 pytest PASS — payrun calc + commit (empty & populated), register/YTD, roster compliance, BAS worksheet shape, wallet-credentials round-trip + no-secret-leak, bundle-suggestions shape, seeded transaction case.
- Frontend: all 4 new surfaces render + wire to backend correctly (screenshots verify Payroll compliance badges, BAS G1..G20 rows, Wallet tab presence, AI discovery block inside promo dialog).
- Regression: Iter 47 promotion percentage & fixed-price flows unchanged.


## v28.0 — Iteration 47 (8 Jul 2026): Bundle & Category Multi-Select Promotions

### Shipped
- **Backend `Promotion` model extended** with:
  - `pricingMode` — `"percentage"` (existing behaviour) OR `"fixed_price"` (whole bundle = one $).
  - `bundlePrice` — the fixed $ price of the bundle when `pricingMode="fixed_price"`.
  - `categories` — array of categories (owner can now pick multiple) alongside the legacy singular `category`.
  - `minQuantity` / `maxQuantity` — bundle quantity gates (e.g. "any 3+ Mains = $25").
  - `stackable` — allow the promo to stack with other running promos.
  - `type` accepts `bundle` | `category` | `mixed` (mixed = categories AND explicit items).
- **`POST /api/v26/cart/apply-promos` rewritten** to honour:
  - Categories OR products filter (either matches → line is eligible).
  - Min-quantity gate — promo silently skips when the matching cart has too few items.
  - Fixed bundle price recalc — line-relevant `originalTotal – bundlePrice = discount`; returned with `pricingMode`, `bundlePrice`, `originalTotal`, `savingsPct` so the POS surfaces "$25 bundle · save $5 (17% off)" chips.
  - Percentage promos unchanged — full backwards compat.
- **`PromotionDialog` rebuilt** with a fluent 3-step selector:
  1. **Type** — Category / Bundle / Mixed as visual buttons with icon+descriptor.
  2. **Pricing** — Percentage OFF vs Fixed Bundle Price toggle; fixed mode reveals `$` price + min/max qty inputs.
  3. **Applicability** — multi-select category chips + searchable product checkbox list (based on type). Live preview card shows `$original → $bundle · Save $X · Y% off` in emerald when the maths lands.
- **Promotion card display** on `/products` now shows: pricing badge (`$25.00 for 3+` OR `X% OFF`), category count, item count, stackable badge, schedule window.

### Iter 47 Tests
- Backend: 8/8 pytest PASS — POST/PUT/GET shape, fixed-price cart calc, percentage no-regression, categories-OR-products filter, minQuantity gate.
- Frontend: 5/5 flows verified — Create dialog opens with all selectors; Fixed mode reveals bundle-price + qty inputs; Mixed type shows both category chips + item list; preview appears when maths favours the bundle; card displays correct badge.


## v27.9 — Iteration 46 (7 Jul 2026): Refactor · Source Attribution · Real Wallet Passes · @dnd-kit · Channel Pause

### Shipped
- **Refactor — `utils/mongo_safe.py`**: New `safe_parse_list()` + `safe_find_list()` helpers that centralise "parse-list-with-per-row-fallback" logic. `routes/settings.py` (locations) and `routes/customers.py` (customers) migrated. No more bespoke try/except sprinkles for legacy-doc handling — same behaviour, one place to change.
- **Booking source attribution on Reservations**: New `components/reservations/BookingSourceStrip.jsx` renders the top 4 booking sources of the last 30 days (bookings, covers, %-share, coloured bar) with a summary line (`X bookings · Y covers · Z QR scans · $R est.`). Pulls `GET /api/marketing/analytics?days=30` and self-hides if empty. Slots into `Reservations.jsx` directly under the today KPI row.
- **Real Apple Wallet `.pkpass` + Google Wallet save-link**:
  - `utils/wallet_passes.py` builds a fully-structured `.pkpass` zip (pass.json + manifest.json + signature + icon.png/@2x/logo.png). Signature is a DETACHED CMS/PKCS7 over `manifest.json` using the `PASS_TYPE_CERT_PEM` / `PASS_TYPE_KEY_PEM` / `APPLE_WWDR_CERT_PEM` env certs. When those aren't set (preview env), it emits an unsigned but structurally valid pass and stamps the response header `X-Pkpass-Signed: false` so ops can see the state.
  - Google Wallet endpoint constructs a signed JWT `payload.loyaltyObjects[0]` with class id + object id + QR barcode + tier text module. Signs with `GOOGLE_WALLET_SERVICE_ACCOUNT_KEY` (RS256) when configured; otherwise returns an HS256 preview JWT and `signed:false` for QA.
  - New endpoints: `GET /api/customers/{id}/wallet/apple.pkpass` (streams pkpass) and `GET /api/customers/{id}/wallet/google` (returns `{url, jwt, signed, classId, objectId}`). `GuestWalletDialog` now shows dedicated "Add to Apple Wallet" and "Save to Google Wallet" buttons alongside the copy/text-pass ones.
- **`@dnd-kit` migration for Social Calendar**: Replaced HTML5 `draggable/onDragStart/onDrop` with `DndContext` + `PointerSensor` (`distance: 6`) + `TouchSensor` (`delay: 180ms`, `tolerance: 6`) + `DragOverlay`. New `DraggablePostChip` and `DroppableDay` sub-components keep the rescheduling logic identical while unlocking full touch/tablet drag support. Chip click still opens the edit dialog (activation constraint prevents accidental drags on tap).
- **Channel Menus per-channel Pause / Resume / Schedule**: New `components/channel/ChannelPauseControl.jsx` slot above the Channel Menus action bar. Shows a Live/Paused badge and Pause / Schedule buttons; Schedule mode collects `pausedUntil` (datetime-local) + reason. Wires to `GET/POST /api/channels/state` with owner/manager RBAC.

### Iter 46 Tests
- Backend: 9/9 pytest PASS — mongo_safe regressions on locations + customers, Apple pkpass zip structure + headers, Google Wallet JWT link, marketing analytics shape, channels state pause/resume/schedule + RBAC 403 for cashier.
- Frontend: all 5 flows verified end-to-end — Reservations source strip (28/92/2), Wallet dialog with 4 buttons + pkpass download + Google Wallet tab, Channel Menus pause/schedule dialog, Social Calendar mounts + still edits chips.


## v27.8 — Iteration 45 (4 Jul 2026): Finalization UI Batch · Locations Defensive · Digital Wallet · Automation Triggers

### Shipped
- **P0 Bug Fix — `GET /api/settings/locations` defensive read**: Wrapped Pydantic parsing in try/except per-row, coerces legacy `hours` (string → null) and legacy `timings` (dict → `hours`), and falls back to a minimal safe shape when a doc is unrecoverable. Verified end-to-end with two intentionally malformed docs injected into Mongo — endpoint still returned 200. Closes the recurring "Pydantic validation on lists" 500 class.
- **Reservations ↔ AI Booking Inbox merge**: Reservations page (`/reservations`) now hosts two top-level tabs (`Bookings` / `AI Inbox`). AI Inbox tab embeds the existing `BookingsInbox` component. Zero behaviour regression for either page. `/bookings-inbox` route still works standalone.
- **Guest Digital Wallet** (`components/customers/GuestWalletDialog.jsx`): New dialog opened from a customer profile via a `Wallet` button. Renders the signed QR token as `<QRCodeSVG>` on a gradient card, plus tier badge, points, store credit, barcode, and Copy/Download-pass buttons. Backed by `GET /api/customers/{id}/wallet` and `POST /api/customers/lookup-by-token` (both HMAC-signed with `JWT_SECRET`).
- **Automation Triggers page** (`/automation-triggers`, `AutomationTriggers.jsx`): CRUD UI for the `automation_triggers` collection — Name, Event (8 preset events with descriptions), Conditions (JSON), Actions (typed list: send_email · send_sms · dock_notify · dispatch_task · apply_discount), Active toggle. "AI Suggest" dialog turns a plain-English prompt into a pre-filled template via `POST /api/automations/ai-suggest` (LLM: `openai/gpt-4o-mini`, template fallback when key missing). Sidebar Automation menu expanded to group "Automation Engine" + "Custom Triggers".
- **Settings > Locations extended UI**: Add/Edit dialog now captures `email`, `website`, `logoUrl` (with live preview), `gmbPlaceId`, plus per-day opening hours (Mon–Sun, open/close/closed). Location cards show the logo, GMB badge with last-sync date, and a dedicated `Sync GMB` button that calls `POST /api/locations/{id}/gmb-sync`.

### Iter 45 Tests
- Backend: 13/13 pytest PASS (`/app/backend/tests/test_iteration45_finalize.py`) — defensive locations GET (with 2 malformed-doc injections), extended POST/PUT persistence, GMB sync 200/400, wallet shape + signed-token roundtrip, triggers CRUD + AI-suggest happy/empty-prompt cases.
- Frontend: full flow verified — Reservations tabs, Customers → Wallet dialog (QR + copy/download), /automation-triggers create + AI-suggest, Settings Location dialog with all new test-ids (`loc-logo-input`, `loc-website-input`, `loc-email-input`, `loc-gmb-input`, `loc-hours-mon-open/close/closed`, `save-loc-btn`, `gmb-sync-{id}`).

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth via `integration_playbook_expert_v2` (needs client IDs/secrets).
- **P1** SendGrid / Twilio production keys.
- **P2** Channel Menus — per-channel pause/resume + schedule toggle UI.
- **P2** `@dnd-kit` migration for tablet drag on Social Calendar.
- **P2** Hardware health monitoring surface.


## v27.6 — Iteration 43 (2 Jul 2026): Ops · Marketing · Super · Items · Floor 5-in-1

### Shipped
- **Temperature Monitoring** (`/temperature`) — HACCP-friendly, hardware-agnostic. Owner registers each fridge / freezer / cool-room / display / hot-hold and pairs it with a sensor brand from a 13-brand catalog (SensorPush · Govee · Inkbird · ThermoPro · Monnit · Cooper-Atkins · HOBO · La Crosse · Ambient Weather · Wireless Sensor Tags · Sensaphone · Generic HTTP · Manual). Ingest paths: (1) `POST /api/temperature/ingest` — no-auth webhook, guarded by per-device `ingestSecret`, so any 3rd-party device or companion Bluetooth app can push readings; (2) `POST /api/temperature/readings` — manual entry for battery/device failures. Abnormal readings auto-create alerts (email best-effort + POS dock). Reports: `weekly | monthly | yearly | custom (start,end)` returning per-device min/max/avg/stdev/abnormal counts + raw chronological log; frontend has period pills + custom date pickers + CSV export. `POST /scan-missing` = twice-daily "have you logged?" nudge for devices with no reading in 12h.
- **Social Media &amp; Promotions umbrella** (`/marketing`) — new page with 9 lazy-loaded tabs: Social Media · Promotions · Experiences · Club Members · Email Marketing · Loyalty · Vouchers · Gift Cards · Events. URL keeps `?tab=` in sync. Old routes (`/social-media`, `/discounts`, `/loyalty`, `/booking-experience`, `/clubmember`, `/email-marketing`) `<Navigate replace>` to the new hub with the right tab pre-selected — zero broken bookmarks.
- **Superannuation** (`/super`, `routes/super.py`) — Fair Work Commission tiered rate (12% from 2025-07-01, 11.5% before, plus historic tiers). Weekly pay-run calculator (`POST /super/calc`) with per-employee OTE + SG, then `POST /super/weekly-runs` commits to the ledger. BAS pulls in via `GET /super/bas-line?quarterStart=&quarterEnd=` — returns totalSuper / totalPaid / totalOutstanding + `reportingDueBy` (quarter-end + 28 days per ATO). `GET /super/summary` gives 4 quarter buckets for a FY. Owner can override rate per run or mark commits paid.
- **Items KPI strip** (`components/products/ItemsKpiStrip.jsx`) — 5 clickable tiles at the top of `/products`: Total / Low-stock / Out-of-stock / Active / Inactive/86. Each tile toggles a filter on the table below; second click clears. LowStock uses `stock > 0 && stock <= (lowStockThreshold ?? 5)`; OutOfStock uses `stock <= 0`.
- **Floor Plan course-aware drawer** (`components/floor/TableInfoDrawer.jsx`) — plain-click a table (view mode) now opens a slide-in drawer with live course + dwell timer + party info + course-advance pills + Send-nudge card. Owner opens the "Configure" link → course-thresholds dialog with per-row colour picker, label, and max-minutes. Tables auto-colour by current course; when a table exceeds its course's `maxMinutes`, the SVG fill flips to `overdueColour` (default `#7F1D1D`). Legacy status-cycle preserved as `Shift+click`.

### Backend surface
- 3 new routers wired into `server.py`: `super`, `temperature`, `table_courses`.
- 21 endpoints total added across these three modules — full CRUD + reports + settings + notifications.

### Frontend
- 4 new pages: `Marketing.jsx`, `Super.jsx`, `Temperature.jsx`, plus components `ItemsKpiStrip.jsx` + `TableInfoDrawer.jsx`.
- 6 legacy routes redirected to the marketing hub.
- BottomDock "More" menu reshuffled: new **Social Media &amp; Promotions** group replaces scattered marketing entries in the old Items/Customers/Enterprise groups; **Super** slots under Accounting; **Temp Monitoring** slots under Operations.

### Iter 43 Tests
- Backend: 21/21 pytest PASS (`/app/backend/tests/test_iteration43_batch.py`).
- Frontend: ~95% — all critical flows (Products KPI toggling, Marketing hub 9-tab + URL sync + 6 legacy redirects, Super KPIs + calculator + commit, Temperature KPIs + device dialog + secret display + report periods + CSV export, FloorPlan drawer + course pills + send nudge + course-settings dialog) verified live. Two LOW cosmetic alias mismatches (`add-device` vs `add-device-btn`; `floor-table-{id}` vs `table-{id}`) — no functional impact.

### Backlog (unchanged)
- **P1** Real Meta / TikTok / X OAuth (needs client IDs/secrets).
- **P1** SendGrid / Twilio production keys.
- **P2** `@dnd-kit` migration for tablet-friendly drag on Social Calendar.
- **P2** Hardware health monitoring surface.


## v27.4 — Iteration 41 (26 Jun 2026): Best-Time-to-Post Analytics · AI Fallback Header · Chargeback Console · For Sam

### What landed
- **`GET /api/social/best-times`** + reusable `_compute_best_times()` — mines 7-day POS transactions, groups quantity by `(hour-of-day, category)` and filters per platform via `PLATFORM_CATEGORY_AFFINITY`. Each row returns `{platform, platformLabel, recommendedHour, recommendedTime, sampleSize, source ∈ {pos_peak | pos_peak_clamped | default_band}, band [lo,hi]}` so the UI can show *why* it picked that hour.
- **`WeeklyPlanIn.useBestTimes: bool`** (default `False`) — when `True`, the AI weekly plan applies per-platform best hours from `_compute_best_times()` instead of a fixed `postTime`. Plan-days were refactored to carry `dayBase` (midnight ISO) and a helper `_resolve_scheduled_for(plan_day, platform)` / `_sched_for(...)` (inline preview + background worker) computes the per-platform `scheduledFor`. Job doc now persists `useBestTimes` + `bestTimeMap` so the polling UI knows the schedule shape.
- **`x-ai-parsed-fallback` header on `POST /api/bookings/inbox`** — `_ai_parse()` returns a 4th `fallback: bool`; the route sets the header (`true`/`false`) and also stores `aiParsedFallback` on the persisted document so historic cards can still surface a warning. `CORS expose_headers = ['x-ai-parsed-fallback']` so SPA `fetch` can read it.
- **Chargeback / Dispute Console rewrite** (`/app/frontend/src/pages/v25/Disputes.jsx`):
  - KPI strip: Open / Evidence-In / Won / At-risk $ / Recovered $ with tone-coloured cards.
  - Filter pills (All/Open/Evidence/Won/Lost), status-keyed badges with icons, monospace IDs, "Attach evidence" CTA opens a proper Radix dialog (with `DialogDescription` for a11y).
  - New-Dispute dialog replaces the old `prompt()`-driven flow — TX id + amount validation + reason dropdown (`fraud | product_not_received | duplicate | unrecognised | service_not_provided | other`).
- **Frontend best-time chips** in `SocialCalendar.jsx` — strip below the KPI row showing each platform's recommended time + source pill (POS / POS± / Default) + "Use best times in AI plan & drag-drop" toggle (default on). Drop-to-reschedule now snaps to the platform's best hour when the toggle is on.
- **`/app/For Sam.md`** — 350-line deployment doc covering Web (Docker + compose + hosting picks), Windows (PWA install OR Electron kiosk), Android (PWA OR TWA via Bubblewrap OR React Native shell), Day-2 ops (backups, secret rotation, monitoring), troubleshooting cheat-sheet, and a 5-year posture section (multi-tenant, offline-first, edge cache, reservations OAuth, hardware health).

### Iteration 41 Tests
- **Backend 10/10 PASS** (`tests/test_iteration41_best_times_and_inbox.py`). `/best-times` shape contract verified per platform; `ai-weekly-plan` preview honours per-platform hours when `useBestTimes=true`, falls back to fixed `postTime` when `false`; save-path returns queued, polls to complete, posts persisted with correct per-platform `scheduledFor`. Inbox header verified both true/false branches; CORS exposes the header.
- **Frontend 100%** on tested flows: best-time chip strip renders all 5 platforms with correct chips + toggle, Disputes console renders all 5 KPIs + dialog opens.

### Backlog
- **P2** Touch-friendly DnD for tablets (`@dnd-kit` migration).
- **P1** Real Meta / TikTok / X OAuth — playbook pending API keys from user.
- **P1** SendGrid / Twilio production keys.
- **P2** Hardware health monitoring (route already exists in `automation.py`).

## v27.3 — Iteration 40 (25 Jun 2026): Background Worker · Calendar Edit/Reuse · Bespoke Auth Cleanup

### What landed
- **`POST /social/ai-weekly-plan` is now a background job** (FastAPI `BackgroundTasks`). The HTTP call returns in **~64ms** (verified) with `{planId, status:'queued', expected, platformsUsed, message}`. Progress is streamed into `social_plan_jobs` with `{status, completed, expected, fallbacks}` — polled via new **`GET /social/plan-jobs/{plan_id}`** every 2.5s by the UI. Background worker catches exceptions and flips status to `failed` with the error string preserved. Save=true takes the background path; save=false still runs inline because the caller wants the preview body back synchronously.
- **`POST /social/posts/{id}/duplicate`** — owner clones any prior post as a fresh draft (or scheduled when `scheduledFor` is provided). Strips `autoPlan*` / `publishedAt` flags, regenerates id+createdAt, records `duplicatedFrom`. Optional body fields (`platform`, `caption`, `hashtags`, `imageUrl`, `scheduledFor`, `status`) allow tweaks at duplicate time. Status enum + platform validated.
- **Calendar `edit + reuse` UX** (`components/social/SocialCalendar.jsx`):
  - Click any chip OR the new Pencil icon on the Next-7-Days strip → `[data-testid=edit-post-dialog]` opens pre-filled with caption / hashtags / scheduledFor / imageUrl / status. Save fires `PATCH /api/social/posts/{id}` and reloads.
  - Inline **Duplicate** button (`Copy` icon) on every upcoming row, plus a Duplicate-as-draft link inside the Edit dialog header.
  - **Live progress bar** (`plan-progress-bar`) shows during AI Weekly Plan generation; calendar chips appear progressively as posts land; final 'Done — N posts saved' toast on completion.
- **Improved error wording** on `ai-weekly-plan` — structured `detail` with **`code: 'no_connected_accounts' | 'no_matching_platforms'`** plus `connected[]`, `requested[]`, `message`. UI surfaces `.message` if present, falls back to the raw detail otherwise.
- **Bespoke auth refactor (last ~8 endpoints) — cleared**:
  - `accounting/bas` + `accounting/bas.csv` — request dropped, `Depends(require_owner_or_manager)`.
  - `licensing/abn/approve/{req_id}` — request kept (header read) + `Depends(require_owner)`.
  - `agent/tick`, `agent/voice-command` (loyalty_engine) — request kept (voice/headers), auth via Depends.
  - `agent/auto-publish-roster`, `agent/tick-extended` (phase_ef) — Depends-gated.
  - `v25/products/{id}/86` — owner+manager+kitchen role check kept after Depends auth.
  - `v25/ash-pro/approve` — Depends(require_owner).
  - `v25/concierge` — Depends(get_user).
  - `v25/warehouse/export` — Depends(require_owner). Sig also cleaned (removed `request: Request = None` quirk).
  - Only `bookings_inbox.ack` retains inline auth — intentional graceful-degradation for webhook callers.
- **README updated** — Day 1 → 25 Jun 2026 timeline.

### Iteration 40 Tests
- **Backend 33/33 PASS** (`tests/test_iteration40_background_plan.py`). All 11 refactored endpoints validate anon-401, then owner-200 happy paths. Background job returns ~queued in <500ms. Polling advances queued→in_progress→complete in ~30-35s. Structured errors verified. Duplicate edge cases (anon, missing, status=scheduled without scheduledFor, fresh fields). PATCH (anon, invalid status, missing, success). Idempotency intact (iter 39 destructive-preview fix still holds).
- **Frontend 100% on tested flows**: AI Weekly Plan queue → progress bar (0→7) → completion toast in ~35s with chips appearing progressively. Edit dialog pre-fills + saves + reloads. Duplicate via upcoming button + via edit-dialog link both work. Composer regression clean.

### Minor (non-blocking)
- BAS field names — impl returns `g1TotalSales`/`oneA_gstOnSales`/`g11TotalPurchases`/`oneB_gstCredits`. Values correct; only key naming differs from the literal `G1`/`1A`/`G11`/`1B`. Won't change without explicit ATO contract guidance.

### Backlog
- **P2** Touch-friendly drag-and-drop for the calendar (HTML5 DnD doesn't work on tablets) → `@dnd-kit` migration.
- **P2** Chargeback / dispute console with evidence packs UI polish.
- **P2** `x-ai-parsed-fallback` header on AI endpoints so the UI can warn when LLM fell back.
- **P1** Real SendGrid / Twilio API keys.
- **P1** Real Meta / TikTok / X OAuth to lift the publish stub.

## v27.2 — Iteration 39 (Feb 2026): Content Calendar · AI Weekly Plan · README

### What landed
- **Content Calendar** at `/social-media` (Calendar tab):
  - Month grid (6×7), Monday-first, day-of-week header, prev/next/today nav.
  - Posts rendered as colour-coded chips per platform (Instagram pink, Facebook blue, TikTok cyan, X black, Google Business green) with status glyph (`✓` published, `◷` scheduled, `✎` draft).
  - **Drag-to-reschedule** — HTML5 native drag-and-drop. Drop a chip onto any cell → `PATCH /api/social/posts/{id}` bumps `scheduledFor` and flips `draft` → `scheduled` if needed. Published posts are non-draggable.
  - **AI Weekly Plan button** runs `POST /api/social/ai-weekly-plan` (auth, owner/manager) — pulls top-7 selling products from the last 7 days of transactions (`$unwind` + `$group` pipeline), mixes them with active promos and chef-special seeds, distributes one post per connected platform per day. Idempotent: re-running deletes prior `autoPlanRun:true` scheduled posts in the window before regenerating.
  - KPI strip: `scheduled / published / drafts` counts.
  - "Next 7 days" upcoming strip with inline publish/delete.
- **`PATCH /api/social/posts/{id}`** — small allow-list mutation (`caption`, `hashtags`, `imageUrl`, `scheduledFor`, `status`, `postType`). Status & postType validated against the same enums as create. 404 if not found.
- **Composer/Calendar tab toggle** on `/social-media` — existing composer + drafts + posts history all preserved.
- **README** at `/app/README.md` — full timeline from Day 1 through iteration 39, feature map, tech stack, API surface, configuration, testing scorecards, roadmap.

### Iteration 39 Tests
- **Backend 9/9 PASS** (`tests/test_iteration39_social_calendar.py`, ~130s — real Claude Sonnet 4.6 calls per platform/day). Covers: anon 401, save=true persistence, idempotent re-run, **save=false preview no longer destructive** (post-fix), PATCH reschedule, PATCH 400/401/404, no-accounts → 400.
- **Frontend 100% on tested flows**: tab toggle, calendar mount + month nav (`June 2026` → `July 2026` → Today), KPI strip render, 12 colour-coded `cal-post-{id}` chips rendering, 25 upcoming items, publish-from-upcoming flips chip to ✓, composer tab regression, 5-page regression (`/pos`, `/products`, `/channel-menus`, `/reservations`, `/inventory-accounting`) with 0 console errors. Drag-to-reschedule was UX-deferred from browser e2e (already covered by backend PATCH tests).

### Bug fixed during testing
- **CRITICAL** — `POST /social/ai-weekly-plan` preview mode (`save=false`) was destructive: the `delete_many({autoPlanRun:True, scheduledFor: in-window})` ran unconditionally BEFORE the `if body.save:` branch, so calling Preview wiped the user's saved auto-plan. Fixed by gating the delete inside `if body.save:`. Verified end-to-end: save=true creates 7 posts → save=false leaves them intact (preview returns 7 in `preview[]` without persistence).

### Backlog
- **P2** Move `ai_weekly_plan` to a background task — currently N×P Claude calls run inline (7 days × 5 platforms = 35 LLM calls in one HTTP request — risks gateway timeout in high-platform deployments).
- **P2** Touch-friendly drag-and-drop for the calendar (HTML5 native DnD doesn't work on tablets) — `@dnd-kit` migration.
- **P2** Distinguish "no connected accounts" from "no platforms in request matched" in the weekly-plan error message.
- **P2** ~8 inline-auth endpoints still on legacy pattern (custom role mixes / signed-device-secret) — bespoke refactor pending.
- **P1** Real SendGrid / Twilio API keys to activate live notifications.
- **P1** Real Meta / TikTok / X OAuth to lift the social-publish stub.

## v27.1 — Iteration 38 (Feb 2026): Social Media Marketing · Loyalty 10pt Floor · Split Validation · Promotion Dialog Extract

### What landed
- **Social Media Marketing** — new top-level feature at **`/social-media`**:
  - **Backend** `routes/social_media.py` with full CRUD for connections (Instagram/Facebook/TikTok/X/Google Business), draft + scheduled + published posts, and an AI generation endpoint. Mock OAuth at the connection boundary; actual cross-posting is a stub on `POST /social/posts/{id}/publish` (status flip + logged).
  - **AI content** via **Claude Sonnet 4.6** through the Emergent LLM Key. Pick a product, promotion, or describe a daily special → returns platform-tuned `{caption, hashtags[], imageAlt, isFallback}` per platform. Falls back to templated copy if the LLM key is missing or upstream errors (with `aiError` flag). Validated: real generations come back in ~5s, `isFallback: false`.
  - **Frontend** `pages/SocialMedia.jsx` — composer card (source toggle product/promotion/special, tone/format/platforms/image picker/schedule), drafts preview with editable captions and clickable hashtag chips, posts history table with per-row publish/delete. Wired to the existing **Image Library** for hero images. Mock-OAuth banner clearly communicates that connections are sandboxed.
  - **Nav** — added to `BottomDock` (More menu) with the Sparkles icon.
- **Promotion dialog extracted** to `components/products/PromotionDialog.jsx` (117 lines). `Products.jsx` is now 608 lines.
- **Split payment validation** (`PaymentDialogs.jsx` + `POSTerminal.handlePaySplit`):
  - Pay button **disabled** when amount ≤ $0 OR exceeds remaining.
  - **Imbalance warning banner** (`split-imbalance-warning`) when custom-mode splits don't add to bill total.
  - Final txn refuses to create if splits don't balance within 1¢ (reverts the just-confirmed status so the cashier can fix it).
- **Loyalty floor lowered**: `minRedeem` 50 → **10 points (= $0.10)** in `routes/loyalty_engine.py` DEFAULT_CONFIG + live config row updated. POS POS displays "min 10" prompt and 10 points discount = $0.10. CRM still records earnings/visits/lastVisit/totalSpent on every txn.
- **Components interconnection (verified, not new)**:
  - `routes/transactions.py` already decrements `products.stock`, fires `deduct_recipe_stock()`, and increments customer `totalSpent/visits/points + lastVisit` per sale.
  - 86-toggle persists via `products.eightySixed` and is honoured throughout grid/table/POS.

### Iteration 38 Tests
- **Backend 20/20 PASS** (`tests/test_iteration38_social_loyalty.py`). Anonymous 401 / cashier 403 / duplicate 409 / invalid platform 400 / invalid status 400 / AI generation real (non-fallback) / accounts + posts CRUD / publish / delete / loyalty config minRedeem=10.
- **Frontend ~88% PASS**. SocialMedia create → generate → publish flow live; Promotion dialog extraction works; split-pay validation works; loyalty 10pt floor honoured. Bug found: legacy `social_accounts` doc (channel_menus / v25 era) leaking into `GET /social/accounts` → **FIXED** by filtering `{tokenStatus: {$exists: True}}` and adding `data-testid="platform-card-{key}"` for E2E determinism.

### Backlog
- **P2** Real Meta / TikTok / X OAuth integration to lift the publish stub.
- **P2** ~8 inline-auth endpoints (custom role mixes / signed-device-secret) still on the legacy pattern — bespoke refactor required.
- **P2** `social_media_router` `partialFailures` top-level field so the UI can warn when LLM fell back.
- **P1** Real SendGrid / Twilio API keys to activate notifications.

## v27.0 — Iteration 37 (Feb 2026): Drag-to-Select Marquee · Recently Edited Sidebar · Nua Rebrand

### What landed
- **Browser title** is now **"Nua - Restaurant OS"** (`/app/frontend/public/index.html`). PWA manifest rebranded to `Nua - Restaurant OS` / short name `Nua` with the orange theme colour `#f97316`.
- **User-facing "Emergent" references removed**: the only remaining occurrence was a code comment in `routes/v15_features.py`; it now reads "Universal LLM gateway (OpenAI-compatible)…" and the gateway base URL is overridable via `LLM_GATEWAY_URL` env var. The Python lib `emergentintegrations` and the `EMERGENT_LLM_KEY` env var stay (required for the LLM integration to function).
- **Drag-to-select marquee** on the Products grid (Finder/Explorer-style). Mouse-down on empty grid space starts a marquee rectangle; cards whose bounding box intersects the rectangle become selected on release. Hold **Shift / ⌘ / Ctrl** during drag-start to ADD to the existing selection; plain drag REPLACES it. Drags that start inside a button/input/anchor/select/textarea are ignored so single-clicks still work. Movement under 6px is treated as a click, not a marquee. **Escape** during drag cancels without changing selection. `data-testid="marquee-rect"` and `data-testid="products-grid"` are exposed for tests.
- **Recently Edited sidebar** (`/app/frontend/src/components/products/RecentlyEditedSidebar.jsx`) — shows the 10 most recently touched products *today*, sorted newest first. Each item is clickable and opens the product editor. Hidden on screens narrower than `lg` so the grid keeps its full width on tablets/mobile. Powered by a hybrid source: backend `updatedAt` / `createdAt` PLUS an optimistic client `touchTimes` map so the list updates the instant you finish an inline-edit, bulk-edit, 86-toggle or save — no waiting for the next GET.
- **Backend fix** — `models/product.py` no longer falls back to `datetime.utcnow()` for missing `createdAt` / `updatedAt`. Both are now `Optional[datetime] = None`. Previously every read filled them with NOW, which made every legacy product look "edited just now" and silently pushed freshly-edited products further down the Recently Edited list. `POST /api/products` explicitly sets both timestamps on create; `PUT /api/products/{id}` continues to bump `updatedAt`.

### Iteration 37 Tests
- Iter 37 (frontend-only): 9/10 → **after the touchTimes + Pydantic fix, expected 10/10**. Title + manifest rebrand verified, drag-select marquee verified (shows during drag, bulk action bar reflects count, Shift+drag additive, mouse-down on buttons ignored, Escape cancels, table view hides grid), sidebar visible + renders prior edits + clicking opens editor.
- Backend regression on Products CRUD (curl) — PUT now returns a real ISO `updatedAt`; GET returns the persisted value (no longer "now").

### Backlog
- P2: ~8 remaining inline-auth endpoints (custom role mixes / signed-device-secret auth) skipped in iter 36's refactor — bespoke handling required.
- P1: Provide real SendGrid / Twilio API keys to activate the notification abstraction.
- P2: AI bookings inbox response header `x-ai-parsed-fallback` so UI can warn when LLM is unavailable.
- P2: Extract the Promotion dialog from `Products.jsx` into its own component (file is at ~631 lines now).

## v26.9 — Iteration 36 (Feb 2026): Full Auth-Depends Refactor + Products.jsx Split

### What landed
- **Backend `Depends` refactor — 16 legacy routers, ~230 endpoints**: `advanced_features.py`, `ai_pantry.py`, `enterprise_features.py`, `gamification.py`, `inventory_accounting.py`, `licensing.py`, `loyalty_engine.py`, `menu_features.py`, `multi_tenant.py`, `online_orders.py`, `phase_ef.py`, `phase_ef_wave2.py`, `reservation_features.py`, `staff_management.py`, `v15_features.py`, `v25_suite.py`, `v26_commerce.py` — all inline `from routes.auth import get_current_user` patterns converted to top-level `Depends(get_user / require_owner / require_owner_or_manager)` from `/app/backend/deps.py`. Anonymous POSTs now reliably return **401 BEFORE Pydantic 422**, cashier-role calls return **403**. Edge cases that referenced `request` after the auth block (~8 endpoints) were intentionally skipped and remain on the inline pattern.
- **CRITICAL bug fix — `/loyalty/redeem` auth bypass**: the legacy `routes/loyalty.py` was registering `POST /loyalty/redeem` BEFORE the auth-protected version in `routes/loyalty_engine.py`, allowing anonymous callers to deduct points from any customer. The legacy unprotected handler has been **removed**; `routes/loyalty.py` now also guards `POST /loyalty/rewards` and `DELETE /loyalty/rewards/{id}` with `Depends(require_owner_or_manager)`. A code comment in the file marks the redeem endpoint as owned by `loyalty_engine.py`.
- **Frontend — `Products.jsx` split (963 → 618 lines)**: extracted into three pure, presentational components under `/app/frontend/src/components/products/`:
  - `ProductsToolbar.jsx` (160 lines) — search, sort, status filter, layout toggle, CSV export, category chips, bulk-action bar, select-all checkbox.
  - `ProductTable.jsx` (307 lines) — both grid and table renderings of the catalog, with inline price/stock/name edit and 86 toggle.
  - `BulkEditDialog.jsx` (161 lines) — bulk-edit form with category/price-delta/cost/GST/status/image/modifier add+remove.
  All `data-testid` attributes preserved; bulk-edit, inline-edit, layout toggle, 86 toggle, CSV export and Image Library wiring all validated end-to-end.

### Iteration 36 Tests
- **Backend 85/85 PASS** (after fix). Anon-401 across 24 endpoints, owner-GET across 43 endpoints, owner-POST happy-path across 10 endpoints, iter-35 regression intact. Test: `/app/backend/tests/test_iteration36_depends_refactor.py`.
- **Frontend** — Products.jsx split fully validated: toolbar renders, bulk-edit dialog opens + applies +5% delta, inline price persists, table view loads, select-all works, CSV downloads. Smoke-tested /pos, /channel-menus, /reservations, /bookings-inbox, /inventory-accounting all clean.

### Note on intentionally-public storefront endpoints
- `POST /api/v25/kiosk/session*` and `POST /api/online/orders` remain **public by design** (guest kiosk checkout & customer-facing online ordering). Documented in route comments.

### Backlog
- P2: ~8 remaining inline-auth endpoints across `v25_suite.py`, `phase_ef.py`, `phase_ef_wave2.py`, `licensing.py`, `inventory_accounting.py`, `loyalty_engine.py` that use `request` after the auth block (custom role mixes or signed-device-secret auth) — skipped intentionally, would need bespoke refactor.
- P2: AI bookings inbox response header `x-ai-parsed-fallback` so the UI can warn when the LLM is unavailable.
- P1: Provide real SendGrid / Twilio API keys to fully activate the notification abstraction.

## v26.8 — Iteration 35 (Feb 2026): P0 Auth-Precedence Refactor (Depends Pattern)

### What landed
- **`/app/backend/deps.py`** is now the single source of truth for FastAPI auth dependencies. Exposes `get_user`, `require_owner`, `require_owner_or_manager` — all wired as top-level `Depends(...)` so the auth check fires BEFORE Pydantic body validation. Anonymous POSTs with bogus payloads now correctly return **401** (not 422); cashier-role calls return **403** instead of leaking the schema.
- **Refactored routes** to remove inline `from routes.auth import get_current_user` boilerplate:
  - `routes/products.py` — `bulk-edit`, `product-images` GET/POST/DELETE
  - `routes/items_system.py` — categories CRUD, modifiers CRUD, discounts CRUD, comp-void, payment-links, seed/catalog
  - `routes/channel_menus.py` — replaced its local `_owner_or_manager` with the shared dep; all 7 protected endpoints now use `Depends(require_owner_or_manager)`
- **Channel Menus** (already implemented in iteration 34, validated in 35): `/api/channel-menus/{channel}/ai-prep-times` syncs per-product prep times against current kitchen heat (active KDS tickets ×1.0/1.1/1.25/1.5). `/api/channel-menus/{channel}/ai-discount-slow` applies an N%-off to bottom-N slowest sellers of the last 7 days, with unsold products surfaced first. UI is wired in `pages/ChannelMenus.jsx` via `ai-prep-btn` and `ai-discount-btn`.

### Iteration 35 Tests
- **Backend 42/42 PASS** — 12 endpoints × {anon 401, cashier 403} = 24 precedence tests, plus happy-path Products bulk-edit / Modifiers CRUD / Product Images / Channel Menus CRUD+AI / Reservations AI assign-seat-complete chain / Fair Work Awards (catalogue, install, sync-fairwork, super-by-award) / Bookings AI Inbox (real LLM parse). Regression on products/transactions/customers green.
- Test file: `/app/backend/tests/test_iteration_p0_auth_refactor.py`.

### Backlog
- P2: Apply the same `Depends` refactor to legacy routers (`advanced_features.py`, `loyalty_engine.py`, `phase_ef_wave2.py`, `v25_suite.py`, `v26_commerce.py`, `enterprise_features.py`, `inventory_accounting.py`, `staff_management.py`, etc.) — currently still inline `get_current_user(request)`. Not a behaviour bug, just consistency.
- P2: Split `Products.jsx` (~960 lines) into `components/products/{Toolbar, ProductTable, BulkEditDialog}.jsx`.
- P2: AI bookings inbox response header `x-ai-parsed-fallback` so UI can warn when LLM is unavailable.
- P1: Provide real SendGrid / Twilio API keys to activate the notification abstraction.

## v26.7 — Iteration 34 (Feb 2026): Cart inputs · POS status bar · AI Bookings Inbox · Super (Awards) · Banks + Payment Terminals · P2 fixes

### What landed
- **Cart inputs simplified**: replaced 1-10 table buttons with a single free-text `Table #` input (`data-testid='table-input'`) for Dine-in and `Name` input (`data-testid='walk-in-name'`) for Takeaway. CustomerCombobox still ties the order to a loyalty profile.
- **POS Header Bar** (`/app/frontend/src/components/pos/POSHeaderBar.jsx`): replaces the "POS Terminal" title. Shows live HH:MM:SS clock, full date, devices-online count `N/M devices online` with offline-device names tooltipped, and a Wi-Fi / Ethernet / Offline indicator using the browser Network Information API. Polls `/api/v25/hardware` every 30s.
- **AI Bookings Inbox** (`/bookings-inbox` route + `routes/bookings_inbox.py`): unified inbox for inbound bookings from Instagram DM, Facebook Messenger, WhatsApp, SMS, phone, email, web form, walk-in. POST `/api/bookings/inbox` runs an LLM parse (env-configurable model via `BOOKINGS_INBOX_MODEL`, defaults to `gpt-4o-mini`) and extracts `{date, time, partySize, name, phone, notes}` + summary + suggestedReply. Past-dated extracted dates are now clamped to today so the LLM can't hallucinate "tonight" → 2023. `POST /bookings/inbox/{id}/ack` flips status and optionally converts to a reservation; `acknowledgedBy` is now taken from the auth token, never from the body (security fix flagged in code review).
- **Super (Awards) tab** in `/inventory-accounting`: new panel under `InventoryAccounting.jsx`. Award catalogue includes 4 Fair Work AU awards (Restaurant MA000119, Hospitality MA000009, Fast Food MA000003, General Retail MA000004) plus seed NZ/UK/US equivalents. Each award has classifications with base hourly + casual + weekend/PH loadings + super rate. Owner can Install/Uninstall awards (POST `/api/awards/install`, DELETE `/api/awards/{code}`). `POST /api/payruns/super-by-award` computes super per staff member from a payrun; returns `unresolvedAwards: []` so the UI can prompt to install missing codes.
- **Integrations Hub** extended (`routes/integrations.py`): 12 new AU bank cards (CBA, Westpac, ANZ, NAB, Macquarie, Bendigo, Bankwest, Suncorp, HSBC, ING Direct, BOQ, Judo) and 15 payment-terminal cards (Tyro, Smartpay, QIKI, Westpac EFTPOS Air, ANZ Worldline, NAB Easy Tap, Square Terminal, Zeller, mx51/Linkly, Verifone, Ingenico, PAX, Adyen, Razorpay, PayPal Zettle). Two new categories: 'Banks (AU)' (Building2 icon) and 'Payment Terminals' (Wallet icon). All auto-render in the existing Integrations page.
- **P2 fixes**:
  - `POST /api/products/bulk-edit` now picks a `update_many` fast path when no per-row math is needed (no `pricePercentDelta`, no add/remove modifier ops); returns `mode: 'update_many' | 'per_row'`. Per-row math still uses the slow path with price clamping.
  - **Auth guard** added to `/api/product-images`: POST + DELETE require owner/manager; GET requires any signed-in user (cashiers need to see images).

### Iteration 34 Tests
- **Backend pytest 16/16 PASS** — Bookings ingest/ack/convert, dismiss-404, Awards catalogue/install/uninstall/super-by-award math, country filter, Integrations Banks + Payment Terminals present, bulk-edit mode dispatch correct in both branches, product-images auth (anonymous 403, cashier 403, owner 200, GET requires auth).
- **Frontend 100% PASS** — POS header bar (clock + date + 5/5 devices + Wi-Fi), table-input free-text in dine-in, walk-in-name in takeaway, customer picker preserved, bookings-inbox compose → AI parse → Book it → reservation creation, Super (Awards) catalogue render + install/uninstall + Load Payrun + Compute Super, Integrations Banks (AU) and Payment Terminals chips filter correctly and Connect dialog opens.

### Backlog
- P2: SEED_AWARDS in `routes/awards.py` is hardcoded — production deployments will want a sync job to pull from Fair Work Modern Awards API.
- P2: AI bookings inbox header `x-ai-parsed-fallback` so UI can warn when LLM is unavailable.
- P2: Split `Products.jsx` (~960 lines) into smaller components — deferred again to avoid risking the just-added power-user features.
- P2: Move `_require_owner_or_manager` into a top-level FastAPI `Depends` so auth fires before Pydantic 422 (schema currently leaks to anonymous callers).



## v26.6 — Iteration 33 (Feb 2026): Items Page Power Tools — Filter, Sort, Bulk Edit, Image Library, Inline Edit

### What landed
- **Toolbar**: search by Name OR SKU, sort by name/category/price/stock/margin/recent-edit with asc/desc toggle, status filter (all/active/86), grid ↔ table layout toggle, CSV export of current view.
- **Category filter chips** — multi-select. Tap chips to OR-filter; tap 'All' to clear.
- **Selection + bulk actions**: per-row checkboxes, "Select all visible", bulk action bar appears when items selected. Supports:
  - bulk **change category**
  - bulk **±% price** (clamped to ≥-99% server-side to avoid negative prices)
  - bulk **set cost / GST rate**
  - bulk **set image** (pick from Image Library)
  - bulk **86 / un-86**
  - bulk **add/remove modifier ids**
  - bulk **delete**
- **Image Library** (NEW): `/app/frontend/src/components/ImageLibrary.jsx`. Owner uploads pictures once — auto-compressed client-side to ≤800px / 0.85 JPEG (~150-400 KB). Stored as base64 `dataUrl` in `db.product_images`. Search by name, tag-filter, delete. Pickable from single-product dialog **and** bulk-edit dialog.
- **Inline edit** on cards & table rows for `name`, `price`, `stock` — click → input → Enter → PUT /api/products/{id}. 4xx responses re-fetch instead of leaving stale optimistic UI.
- **Per-row quick 86 toggle**.

### New API surface
- `POST /api/products/bulk-edit` — body `{productIds, category?, categoryId?, pricePercentDelta?, cost?, gstRate?, image?, eightySixed?, active?, addModifierIds?, removeModifierIds?, replaceModifierIds?, onlineChannels?}` → `{updated, failed}`. `pricePercentDelta` clamped to ≥-99 and final price floored at 0.
- `GET  /api/product-images?search=&tag=&limit=` (default 100, max 500)
- `POST /api/product-images` — `{name, contentType, dataUrl, tags?, createdBy?}` — rejects non-data: URLs (400) and payloads >1.5MB (413)
- `DELETE /api/product-images/{id}`
- `ProductCreate.image` is now `Optional[str] = ""` (was required) to match the inline-edit UX

### Iteration 33 Tests
- Backend pytest **10/10 PASS** — bulk-edit price/cost/gst/category/eightySixed/modifier-ops, invalid+empty IDs, image upload/list/delete, non-data URL 400, oversize 413, delete 404.
- Frontend smoke **100%** — toolbar testids all present, sort by price persists, category chip filter works, grid↔table toggle, bulk-action-bar with correct count, bulk-edit-dialog with bulk-pick-image, inline price → Enter persists, image-library modal opens, CSV download works.

### Backlog from iteration 33 test report (P2)
- Split Products.jsx (~960 lines) into `components/products/{Toolbar,ProductTable,BulkEditDialog}.jsx`
- Auth guard on /api/product-images (currently open)
- Optimise bulk-edit with `update_many` when no per-row math



## v26.5 — Iteration 32 (Feb 2026): POS Modifier Picker End-to-End

### What landed
- **ModifierSheet** (`/app/frontend/src/components/pos/ModifierSheet.jsx`) — opens on every product tap when the product has `modifierIds.length > 0`. Required vs Optional badges, single-select / multi-select with `maxSelections`, per-option surcharges. Add button gated until all mandatory groups have ≥1 pick. data-testids: `modifier-sheet`, `mod-group-{id}`, `mod-opt-{modId}-{optName}`, `mod-confirm`, `mod-cancel`, `mod-validation`, `mod-loading`.
- **POSContext.addToCart** extended to `(product, qty, selectedModifiers, extraPrice)`. Items with modifier picks get a unique synthetic line id `${productId}__${shortUuid}` while preserving the original `productId` field — so two Flat Whites with different milk are separate cart lines but still resolve to the right product on the backend.
- **SwipeableCartItem** displays selected modifiers under the product name (`data-testid='cart-mods-{lineId}'`).
- **POSTerminal**: loads `/api/modifiers` once in parallel with categories. `handleProductClick` opens the sheet when `modifierIds` is non-empty (no longer gated on defs being loaded — sheet shows a loading hint and disables Confirm during the race). Both product card layouts (categorised + flat) show a `+N options` hint (`data-testid='pos-prod-mod-hint-{id}'`).
- **Transactions**: new helper `toTxItem` flattens each line's `selectedModifiers` into the backend `TransactionItem.modifiers: List[SelectedModifier]` shape — `{modifierId, modifierName, optionId, optionName, price}` — verified round-trips via GET /api/transactions/{id}.
- **Backend** `transaction.py` — widened `Transaction.tableNumber` and `TransactionCreate.tableNumber` to `Optional[str]` (was `Optional[int]`) since the frontend sends string table numbers and freeform 'Other' values.

### Verified (iter32, 4/4 backend + 100% frontend)
- Flat White: 6 modifier groups render, Required/Optional badges, surcharges, single-select cycle, multi-select cap, validation message.
- Cart shows the modifier breakdown per line.
- Cash transaction persists modifier picks; GET /api/transactions returns them.
- Items without modifiers (Soft Drink, Smoothies, etc.) bypass the sheet and merge as before.

### Files added / changed (iter32)
- NEW: `components/pos/ModifierSheet.jsx`
- CHANGED: `contexts/POSContext.js`, `components/pos/SwipeableCartItem.jsx`, `pages/POSTerminal.jsx`, `backend/models/transaction.py`
- NEW pytest: `backend/tests/test_iteration32_modifiers.py`



## v26.5 — Iteration 31 (Feb 2026): NUA Brand Identity + Items: Categories & Multi-Modifiers + V25/V26 Page Split

### Brand Identity Applied
- **ThemeContext default:** primary `#f58c14` (orange), secondary `#8b5cf6` (purple), accent `#ec4899` (pink). Legacy indigo (`#6366f1`) auto-migrates from localStorage to NUA orange on next load.
- **Dark / Light toggle** added to BottomDock (Sun/Moon icon, `data-testid='dock-theme-toggle'`). Flips body bg between NUA dark `#0b0b0f` and light `#f6f7fb`. CSS vars exposed: `--nua-bg`, `--nua-surface`, `--nua-card`, `--nua-text`, `--nua-muted`, `--nua-primary/secondary/accent`.
- **StaffLayout** now uses `darkMode` for body bg + text color (no more hard-coded `bg-gray-50`).
- **Login page** Sign-In button + Email/PIN tabs now use brand orange (was emerald).

### Items — Categories & Multi-Modifier Assignment (new requirement)
- **Backend** `models/product.py` — added `categoryId: Optional[str]` and `modifierIds: List[str] = []` to `Product`, `ProductCreate`, `ProductUpdate`. Empty list `[]` is honored by PUT (verified by pytest).
- **Frontend** `pages/Products.jsx`:
  - Loads `categoriesAPI.getAll()` + `modifiersAPI.getAll()` dynamically (no more hardcoded Beverages/Food/Bakery dropdown).
  - Add/Edit Product dialog has dynamic category `<select>` (`data-testid='product-category-select'`) populated from `/api/categories`, sorted by `sortOrder`, filtered to active.
  - Add/Edit Product dialog has new multi-toggle modifier chips area (`data-testid='product-modifiers-picker'`). Each modifier chip is `data-testid='mod-toggle-{id}'`. Tap-to-toggle persists `modifierIds: []` on save.
  - Product cards now show a "{n} modifier(s) attached" line under SKU when `modifierIds` is non-empty.

### V25 / V26 Page Split (refactor, no behaviour change)
- `pages/V25Pages.jsx` (688 lines) → barrel re-export. Implementations live in `/pages/v25/*.jsx` (21 files: `ShiftManager`, `AutoMarketing`, `Exceptions`, `HardwareHealth`, `Disputes`, `SupplierMarketplace`, `GiftCards`, `PredictiveOrders`, `WasteTracking`, `Concierge`, `Reputation`, `Franchise`, `FraudDetection`, `MarginGuardrails`, `StationReadiness`, `KioskMode`, `CFD`, `ChurnRisk`, `RecipeCosting`, `DynamicPricing`, `Subscriptions`).
- `pages/V26Pages.jsx` (599 lines) → barrel re-export. Implementations live in `/pages/v26/*.jsx` (5 files: `VoucherManager`, `EventsManager`, `StaffAvailability`, `GiftCardSale`, `MarketingEmails`).
- `App.js` imports unchanged.

### Iteration 31 Bug Fixes (post-test-agent)
- `pages/v26/StaffAvailability.jsx` — was reading `localStorage.getItem('token')` (returns `null`) instead of the actual `'nua_token'` key. Auth-failed response then crashed `.filter`. Fixed key + added `Array.isArray(d) ? d : []` guard. Page now renders cleanly.
- `Inventory.jsx` + `Products.jsx` `<img>` tags — added placeholder fallback for empty `product.image` to eliminate 404 spam.

### Test Status — Iteration 31
- **Backend 7/7 PASS** — `categoryId`/`modifierIds` POST + PUT + GET persistence + empty-list semantics.
- **Frontend 12/12 PASS after fixes** — theme toggle, Products modifier picker, staff-availability render, all 26 v25/v26 routes.



## v26 (Feb 2026) — Iteration 27 — LICENSING RELEASE

### New backend module — `routes/licensing.py` (12 endpoints, prefix `/license`)
- `POST /api/license/onboard` — Issue tenant license bound to ABR-verified ABN (one ABN per license, immutable). `devSkipAbr=true` + `ALLOW_ABR_DEV_SKIP=true` env allows dev-mode issuance without ABR_GUID; production must omit the override.
- `POST /api/license/validate` — Server-authoritative startup/periodic check. Returns short-lived signed JWT entitlement token (30 min TTL). Specific error codes: `NO_LICENSE`, `DEVICE_NOT_AUTHORIZED`, `ABN_REVERIFY_REQUIRED`, `SUBSCRIPTION_PAST_DUE`, `LICENSE_SUSPENDED`, `LICENSE_CANCELLED`.
- `POST /api/license/device/activate` · `POST /api/license/device/revoke` — owner-gated device list with `maxDevices` enforcement.
- `POST /api/license/abn/change-request` — owner + 4-char 2FA + ABR re-verification + 7-day grace; immediately moves tenant into `abn_review` state.
- `POST /api/license/abn/approve/{req_id}` — gated by `X-Support-Override` header (per spec: "ABN cannot be changed once a license is issued").
- `POST /api/license/stripe/webhook` — handles `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`. Progressive state machine: Day 0-1 `past_due` (warn) → Day 2-6 `grace` (restrict admin) → Day 7+ `suspended` (block sales) → `cancelled` (export-only).
- `POST /api/license/billing/recovery-link` — generates a Stripe Billing Portal session URL for owner card update.
- `GET /api/license/me` · `GET /api/license/audit` — owner dashboard data.
- `POST /api/license/dev/force-state` — owner-only QA helper to simulate any of the 6 states.

### New services
- `services/abr_service.py` — `checksum_valid()` (MOD-89) + `lookup_abn()` (live ABR REST call via httpx, requires `ABR_GUID` from abr.business.gov.au/Tools/WebServices). Raises `RuntimeError("ABR_GUID not configured")` if env missing — refuses silent fallback unless explicit dev override.

### New middleware — `middleware/license_middleware.py`
- `LicenseEnforcementMiddleware` — server-authoritative. Allowlist: `/auth/`, `/license/`, `/payments/`, `/webhook/`, `/v25/warehouse/`. State enforcement:
  - **active** → all OK
  - **past_due / grace** → admin writes (settings, sites/publish, dynamic-pricing, device activation) → 423 `SUBSCRIPTION_PAST_DUE`
  - **suspended** → new sales (transactions, tabs, kiosk, gift-cards) → 423 `LICENSE_SUSPENDED`
  - **abn_review** → same as suspended but error code `ABN_REVERIFY_REQUIRED`
  - **cancelled** → only `/license/` + `/v25/warehouse/export` work; everything else → 423 `LICENSE_CANCELLED`

### New frontend
- `contexts/LicenseContext.jsx` — `LicenseProvider`, `useLicense()`, periodic 10-min revalidation, stable deviceId via localStorage.
- `pages/LicensePage.jsx` — three exports:
  - **default `LicensePage`** — owner dashboard: onboarding form (when no license), state badge, plan/devices/ABN verified/grace cards, device table with revoke, ABN change request (with 2FA + reason), dev/QA force-state controls, audit log.
  - **`LicenseLockScreen`** — full-page dark overlay (z-index 9999) shown when state is suspended/cancelled/abn_review; "POS Locked", "What you can still do", Update Billing + License Details CTAs, error code visible.
  - **`LicenseBanner`** — non-blocking amber strip at top of app shown during past_due/grace.
- `App.js` — `LicenseProvider` wraps `StaffLayout`; `LicenseBanner` + `LicenseLockScreen` mounted globally; `/license` route added.
- `BottomDock` — "License & Billing" entry added under Enterprise group (owner-only).
- `services/api.js` — `licenseAPI` export (me, audit, validate, onboard, activateDevice, revokeDevice, requestAbnChange, billingRecovery, forceState).

### Security & policy
- All license decisions server-side; the frontend cannot bypass state.
- 30-min JWT entitlement tokens (`HS256`, env `JWT_SECRET`).
- Stripe webhook signature verification when `STRIPE_WEBHOOK_SECRET` is set (warns and falls back in dev).
- Progressive lockout — never instant shutdown.
- Audit log of every state change (`license.created`, `device.activated/revoked`, `state.*`, `abn.change_requested`, `billing.paid/payment_failed`).
- Owner+2FA required for ABN change; support override key required for approval.
- Always-open routes: auth, license itself, billing recovery, data export, webhooks — even when suspended.

### Hardenings
- `ALLOW_ABR_DEV_SKIP` defaults to **off** (production-safe). Set explicitly on dev/staging.
- `forceState` in LicensePage now awaits `revalidate()` before resolving so navigation reflects new state immediately.

### Verified
- `testing_agent_v3_fork` iteration_24: **19/19 backend pytest passed**, all enforcement flows verified (suspended → 423, grace → 423 on admin writes, allowlist intact, ABN re-verification flow gates 2FA + support override, device authorization, stripe webhook with unknown customer returns 200 ignored, audit log chronological, no ObjectId leaks).
- Lock screen overlay verified visually with "SUSPENDED · POS Locked · LICENSE_SUSPENDED" + Update Billing CTA.

## Backlog (post-licensing polish)

## v25 (Feb 2026) — Iteration 26 — ENTERPRISE RELEASE

### Bug fix (P0)
- POSTerminal crash on customer selection — `yourUsual` state was referenced but never declared. Added `useState([])`.

### New backend module — `routes/v25_suite.py` (30+ endpoints, prefix `/v25`)

**MUST-HAVE (v25)**
- `POST/GET /api/v25/sync-queue` — Offline sync queue with duplicate detection
- `GET /api/v25/exceptions` — Loss-control: voids/comps/refunds + suspicious-user flagging
- `GET/POST /api/v25/sites` · `POST /v25/sites/publish` · `POST /v25/sites/rollback/{id}` — Multi-site command center
- `GET /api/v25/hardware` · `POST /v25/hardware/heartbeat` (X-Device-Secret) — Device fleet
- `GET/POST /api/v25/disputes` · `POST /v25/disputes/{id}/evidence` — Chargeback console with evidence packs
- `GET /api/v25/suppliers/compare` · `POST /v25/suppliers/quote` — Supplier marketplace with annual-savings calc

**SHOULD-HAVE (v26-v27)**
- `POST /api/v25/kiosk/session` + add + checkout + `GET /v25/kiosk/sessions` — Self-service kiosk
- `GET /api/v25/cfd/current` — Customer-facing display mirror
- `POST /api/v25/substitute` — Smart 86 substitution
- `GET /api/v25/recovery/churn-risk` · `POST /v25/recovery/win-back` — Guest recovery
- `GET /api/v25/station-readiness` — 0-100 ops score
- `GET /api/v25/margin-guardrails` — Items below 50% margin

**TIER 1 — Differentiators**
- `GET /api/v25/ash-pro/plan` (idempotent per-day) · `POST /v25/ash-pro/approve` — AI GM "Approve All"
- `GET /api/v25/profit-guardian` — Nightly margin drift detection
- `GET /api/v25/digital-twin` — Today's revenue ± 8% + covers + wait
- `GET /api/v25/shift-manager` — Real-time intervention alerts
- `POST /api/v25/marketing/auto` · `GET /v25/marketing/auto` — LLM-drafted campaigns

**TIER 2 — Revenue**
- `GET/POST /api/v25/dynamic-pricing` — Per (category, dow, hour) multipliers
- `GET /api/v25/subscriptions/plans` · `POST /v25/subscriptions/plans` · enroll · members
- `GET/POST /api/v25/gift-cards` · `POST /v25/gift-cards/{code}/redeem` (atomic findOneAndUpdate)

**TIER 3 — Inventory**
- `GET /api/v25/recipes/list` · `POST /v25/recipes/upsert` · `GET /v25/recipes/{productId}` — Recipe costing, pushes computedCost back to product
- `POST /api/v25/predictive-orders` — 14-day velocity → next-week POs grouped by supplier
- `GET/POST /api/v25/waste` · `GET /v25/waste/insights` — 30d cost insights

**TIER 4 — Guest Experience**
- `GET /api/v25/guest/{id}` — Universal profile (spend + visits + reservations + points)
- `POST /api/v25/concierge` — LLM classifies + auto-creates reservation
- `GET /api/v25/reputation` · `POST /v25/reputation/respond` (LLM-drafted)
- `POST /api/v25/recovery-action` — Service recovery voucher + flag

**TIER 5 — Enterprise**
- `GET /api/v25/franchise/dashboard`
- `GET /api/v25/benchmark` — Multi-store comparison
- `GET /api/v25/warehouse/export` — Power BI / Tableau export
- `GET /api/v25/fraud-detection` — Per-staff risk score

### New frontend
- `EnterpriseCommandCenter.jsx` — 24-tile launcher + 3 live KPI cards (Station Readiness, Expected Revenue, Live Alerts)
- `NuaPro.jsx` — Signals + actions + Approve All (one-click executor)
- `ProfitGuardian.jsx`, `DigitalTwin.jsx` — dedicated rich pages
- `V25Pages.jsx` — 21 compact pages: ShiftManager, AutoMarketing, Exceptions, HardwareHealth, Disputes, SupplierMarketplace, GiftCards, PredictiveOrders, WasteTracking, Concierge, Reputation, Franchise, FraudDetection, MarginGuardrails, StationReadiness, KioskMode, CFD, ChurnRisk, RecipeCosting, DynamicPricing, Subscriptions
- BottomDock — new "Enterprise (v25)" group with 25 entries; owner quick-action now shows "Enterprise" instead of Dashboard
- `services/api.js` — `v25API` export with all 40+ method bindings

### Hardenings applied post-test
- Gift-card redeem: atomic `findOneAndUpdate` with balance precondition (no race)
- Hardware heartbeat: requires `X-Device-Secret` header
- Ash-plan: idempotent upsert by `planDate` (no collection bloat)
- All seeded items pop `_id` before returning (no ObjectId leak)
- LLM errors logged via `logger.warning`, graceful degradation

### Verified
- `testing_agent_v3_fork` iteration_23: **34/34 backend pytest green · 25/25 frontend routes · 0 console errors**
- POSTerminal customer-selection regression PASSED
- All seed data prefixed `TEST_` for cleanup

## Backlog (post-v25 polish)

### Diagnostic fixes (P0)
- `/api/reservations` 500 → 200: `Reservation` model now accepts legacy `customerName`/`phone` via `model_validator(mode='before')`.
- `/api/purchase-orders` 500 → 200: removed conflicting strict-schema GET in `analytics.py`; `phase_ef.py` is the canonical handler.
- `phase_ef.py` phone-agent + auto-confirm now insert/read using `guestName`/`guestPhone`.

### Backend (`routes/phase_ef_wave2.py` — new)
- `POST /api/ai/upsell` — LLM (GPT-5.2) suggests 1-3 high-margin add-ons given current cart
- `GET /api/ai/price-tune` · `POST /api/ai/price-tune/apply` — 30-day velocity vs median → recommend raise/drop with audit `priceHistory` array
- `POST /api/ai/overbooking-check` — capacity + 10% buffer (configurable via `settings.overbooking.bufferRatio`) vs existing covers in ±30 min slot
- `GET /api/ai/cost-coach` — 30-day food-cost analysis vs 32% target + LLM 3-action plan
- `GET /api/ai/labor-forecast` — 8-week pattern → 7-day hourly FOH/BOH staffing needs
- `GET /api/ai/surge-recommendations` · `POST /api/ai/surge/apply` · `GET /api/ai/surge/active` — per (day, hour) demand multipliers
- `POST /api/ai/voice-recipe` · `GET /api/ai/recipes` — chef text or voice → structured recipe spec (Whisper + GPT-5.2); validates name+ingredients before persist
- `GET /api/ai/kitchen-load` — open-ticket station load + rebalance/priority suggestions

### Frontend
- New pages: `AICostCoach.jsx` `LaborForecast.jsx` `SurgePricing.jsx` `VoiceRecipe.jsx` `KitchenLoad.jsx` `PriceTune.jsx`
- 6 new routes wired in `App.js`: `/ai-cost-coach` `/labor-forecast` `/surge-pricing` `/voice-recipe` `/kitchen-load` `/price-tune`
- `BottomDock` "More" splash — Analytics & AI group expanded with 6 new tiles
- `POSTerminal.jsx` — AI upsell strip (debounced 1.2s, LLM-driven) under cart with 1-3 high-margin pairings
- `Reservations.jsx` — overbooking guardrail dialog before reservation creation (fail-open)

### Curl + Playwright verified
- All 8 Wave 2 endpoints return 200; LLM upsell returns 3 valid suggestions referencing real productIds
- POS cart → 3-5s → "✨ AI SUGGESTS" strip with reasoned upsells ✅
- All 6 new pages render with correct titles, no console errors ✅
- testing_agent iteration_22: 13/13 backend pytest green, 6/6 frontend smoke green

## v18 (Feb 2026) — Iteration 24

### Backend (`routes/phase_ef.py`)
- `GET/PUT /api/agent/autonomy` — owner toggles for auto-publish-roster, auto-confirm-SMS, A/B testing, VIP thresholds, reorder threshold
- `GET /api/comms/sms-queue` · `POST /api/comms/auto-confirm/{resId}` — auto SMS confirmation queue
- `POST /api/agent/voice-extended` — extended voice intents: void_last_item · price_change · eighty_six
- `POST /api/agent/auto-publish-roster` — generates + commits AI weekly shifts within budget cap
- `GET /api/phone-agent/calls` · `POST /api/phone-agent/simulate` — AI Phone Agent (GPT-5.2 classifier, auto-creates reservation, queues confirmation SMS)
- `GET /api/purchase-orders` · `POST /api/purchase-orders/generate` · `POST /api/purchase-orders/{id}/{approve,send,receive,cancel}` — auto-PO generation, receive auto-increments stock
- `GET/POST /api/ab-tests` · `POST /api/ab-tests/{id}/{exposure,conversion,conclude}` — live menu A/B testing with winner auto-pick
- `GET /api/customers/{id}/your-usual` — top-3 frequent items from last-20 transactions
- `POST /api/agent/tick-extended` — runs auto-VIP + auto-SMS + auto-PO rules in one shot

### Frontend
- `pages/PhoneAgent.jsx` (`/phone-agent`) — call log + simulate inbound call
- `pages/PurchaseOrders.jsx` (`/purchase-orders`) — supplier-grouped POs with workflow buttons
- `pages/MenuABTesting.jsx` (`/ab-tests`) — variant pair creator, exposure/conversion table, winner trophy
- `pages/AgentAutonomy.jsx` (`/agent-autonomy`) — owner toggle panel + threshold inputs + "Run Extended Tick"
- POSTerminal: **Your Usual** strip when known customer selected
- VoiceOrderButton now hands off transcript to `voice-extended` for void/price/86 commands
- BottomDock splash: 4 new tiles added under Analytics & AI group

## Curl-verified
- Voice "raise espresso by 50 cents" → $5.70 → $6.20 ✅
- Voice "drop latte by 1 dollar" → Product not found (handled gracefully) ✅
- Phone agent "book for 4 Saturday 7pm" → reservation auto-created + SMS queued ✅
- Auto-PO: seeded 3 low-stock products with supplier "Acme Wholesale" → 1 PO created ✅
- Auto-VIP: Sarah Johnson with spend=1500, visits=25 → tier auto-promoted from Gold to VIP ✅
- Your Usual: customer with 2 past orders → 2 most-frequent items returned ✅

## Frontend Playwright-verified
- `/phone-agent`, `/purchase-orders`, `/ab-tests`, `/agent-autonomy` all render ✅
- `/pos` with Sarah Johnson selected → Your Usual block visible ✅

## Credentials
Owner: owner@nua.com / NuaOwner2026!  
Manager: manager@nua.com / Staff2026!  
Cashier: cashier@nua.com / Staff2026!  
Kitchen: kitchen@nua.com / Staff2026!  
2FA demo: 123456

## Backlog
- Phase B (user keys): WhatsApp · Twilio Voice/SMS · Stripe Tap-to-Pay · Crypto USDC · Xero/QB · Uber Eats · DoorDash · Google Reserve · TikTok Shop
- Real-time: WebSocket for kitchen-load auto-refresh and live A/B test exposure
- Refactor: Split POSTerminal.jsx (~1220 lines) into Cart/Payment/QR sub-components, split V25Pages.jsx and V26Pages.jsx mega-files
- Surge pricing apply to live POS prices (currently only persisted) — hook into product price calc
- Recipe → menu item: 1-click convert /voice-recipe generated spec into a product with cost-rolled-up from ingredient prices
- Auto-swap-finder + auto-EOD-email (Phase E next wave residual)

---

## v26.4 — Iteration 30 (Feb 2026): Notifications + Ingredients + Recipes + BAS + Stock-take

### Backend
- **`utils/notifications.py`** — channel abstraction `send_email` (SendGrid), `send_sms` (Twilio), `notify_order` (both, best-effort). Drops to `delivered:false / reason:not_configured` when env vars absent. **Wiring real channels is now a config change, not a code change** — just drop `SENDGRID_API_KEY`/`SENDGRID_FROM_EMAIL` + `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM_PHONE` into backend/.env.
- **Order notifications wired**: `/online/orders` (place) + `/online/orders/{id}/status` now call `notify_order` and store `deliveryReceipts[]` on the order.
- **`routes/inventory_accounting.py`** — new module:
  - **Ingredients** with canonical `baseUnit` (g / mL / ea). CRUD + low-stock alert + reorderLevel guard.
  - **Recipes** (`PUT /recipes/product/{id}`) — auto-converts kg↔g, L↔mL, cl→mL. Rejects incompatible conversions (g↔mL). Computes product cost = `Σ qtyBase × ingredient.unitCost` and pushes back to the products collection so margin chips stay accurate.
  - **Auto stock deduction** on POS sale — `routes/transactions.py` calls `deduct_recipe_stock(productId, qty)` per item.
  - **Invoice → Ingredient assignment** (`POST /invoices/{id}/assign-stock`) — increments stock with unit conversion, updates unitCost as **weighted moving average**, posts a `stock_movements` audit row, then **cascade re-rolls** every recipe that uses the touched ingredients.
  - **Stock-take** (`POST /stock-takes`) — counts vs expected → variance + totalShrinkageValue.
  - **Australian BAS / GST report** (`GET /accounting/bas`) — G1 sales (incl GST), 1A GST collected (= total/11), G11 purchases (incl), 1B GST credits, netGstPayable. Supports `?fy=2026&quarter=Q3` or arbitrary `?monthStart&monthEnd`. CSV export at `/accounting/bas.csv` (ASCII-safe filename).

### Frontend (`pages/InventoryAccounting.jsx`)
- New 5-tab page at `/inventory-accounting`:
  1. **Ingredients** — inline add-form + table with low-stock alert banner.
  2. **Recipes** — product list ↔ recipe editor with kg/g/L/mL/ea selects, computed-cost preview.
  3. **Invoices → Stock** — pick a parsed invoice from AI Pantry, map each line to an ingredient + unit, one-click "Apply" updates stock + WMA cost + cascades recipe re-cost.
  4. **Stock-take** — table of all ingredients with expected vs counted vs Δ + history sidebar.
  5. **BAS / GST** — financial-year + quarter selector + 8 KPI tiles in system colours + CSV download.

### Test status — Iteration 30
- Backend **16/16 PASS** — every flow above + notification fallback (no keys → graceful `not_configured`).
- Frontend tabs all render, recipe editor + stock-take + BAS all interact.
- One issue auto-fixed by testing agent: CSV download filename was using Unicode arrow; now ASCII-sanitised.
- `retest_needed=false`.

## v26.3 — Iteration 29 (Feb 2026): Online Ordering + AI ETA + Invoice OCR + Item Insights

### Backend additions
- **`/api/online/*`** new module (`routes/online_orders.py`) — public storefront + owner inbox + AI ETA engine:
  - `GET /online/categories` (public) — channel-filtered active categories with prepTime + icon + color.
  - `GET /online/products` (public) — in-stock, not-86'd, online-channel-enabled catalog.
  - `POST /online/orders` (public) — places an order; computes deterministic ETA = max(category prepTime per line, +30% per extra unit of same cat) × surge(load-based, ≤1.6×) + queuePenaltyMins + deliveryOffsetMins. Wraps the ETA in a friendly LLM-generated natural-language message (GPT-5.2; deterministic fallback if no key).
  - `GET /online/orders/track/{code}` (public) — exposes only customer-safe fields (no phone/email/address leak).
  - `GET /online/orders` · `GET /online/orders/{id}` · `PATCH /online/orders/{id}/status` · `POST /online/orders/{id}/eta` (auth) — owner pipeline with channel-aware notification messages.
  - `GET /online/kitchen/load` (auth) — live snapshot of {pending, accepted, preparing, queuePenaltyMins}.
- **Categories** gain `prepTime` + `channels` (`dine-in` / `pickup` / `delivery`).
- **`POST /api/categories/cleanup-legacy`** (owner) — removes any non-canonical category that has zero products attached; safe / idempotent.
- **`POST /api/ai-pantry/parse-invoice`** (owner/manager) — accepts `text` or `imageBase64`. GPT-5.2 extracts supplier, invoice#, date, line items. Fuzzy-matches each line to existing products (exact lower-case → token overlap fallback). Computes suggestedPrice that preserves the current margin %.
- **`POST /api/ai-pantry/apply-invoice/{id}`** (owner/manager) — applies selected price/cost updates; returns audit trail.
- **`GET /api/products/insights`** — per-product `weeklyUnitsSold`, `weeklyRevenue`, `marginAmount`, `marginPct` (last-7-day window).
- **Product pydantic model** unchanged but `eightySixed`/`active` now visible in GET responses.

### Frontend additions
- **`/online-orders`** (owner) — pipeline board (5 stages: pending/accepted/preparing/ready/out_for_delivery/completed) with kitchen-load chip, click-through order details modal showing AI ETA breakdown (base / surge / queue penalty), step-by-step timeline, and stage-advance buttons (channel-aware: `Dispatch driver` for delivery, `Mark Ready` etc.). Polls every 8s.
- **`/order-online`** (public storefront, no auth) — channel picker (Pickup / Delivery / Dine-in), category strip with prepTime hint, fluid product grid, sticky cart with customer details form, navigates to tracking page on submit.
- **`/track/:code`** (public) — large AI ETA tile, ordered step-by-step timeline (channel-aware), customer notification feed. Polls every 12s.
- **AI Pantry — Invoice Upload tab** — file dropper (accepts image / PDF, FileReader → base64) + paste-text textarea, parsed invoice table with apply-cost / apply-price checkboxes per row, suggestedPrice shown in theme accent, one-click apply.
- **Items dashboard (`/items`)** — product cards now show: (a) margin chip in tier colours (green ≥60% / amber ≥40% / red <40%), (b) weekly-sales tile in `theme.primary` accent showing units sold + revenue past 7 days, (c) 86 corner badge preserved.
- **Categories admin** — prepTime input + 3 channel toggle pills, "Remove demo categories" cleanup button.

### Test status — Iteration 29
- **Backend 11/11 PASS** — full lifecycle, PII privacy on tracking endpoint, AI ETA accuracy, invoice OCR (LLM parsed "INVOICE 12345 / 2x Espresso / 5x Long Black" → matched + applied + audit), insights endpoint.
- **Frontend E2E PASS** (Playwright) — public storefront → order placement → auto-navigate to /track → AI ETA + timeline rendering; owner pipeline + kitchen load; categories with prep+channels; AI Pantry invoice tab; product cards with margin/weekly badges.
- `retest_needed=false`.

## v26.2 — Iteration 27-28 (Feb 2026): Fluid POS, Category Icons, Seed Catalog, P2 Refinement, Refactor

### Backend additions
- **`/api/seed/catalog`** (owner-only, idempotent): inserts 5 canonical categories (Coffee, Burgers, Mains, Cakes & Slices, Pasta), 60 products and 10 modifiers (Milk Choice, Extra Shot, Coffee Strength, Syrup, Burger Cheese, Burger Add-ons, Cooking Pref, Side Choice, Pasta Style, Sauce Add-on) — assigned by category.
- **Categories now accept `icon` + `color`** (`POST/PUT /api/categories`). `icon` is a lucide-react name (`Coffee`, `Beef`, `UtensilsCrossed`, `Cake`, `Soup`, …), `color` is a hex string.
- **`/api/v25/sync-queue/process`** (owner/manager): replays pending offline ops into real collections — `transaction.create`, `kitchen.order`, `stock.adjust`, `tab.append`. Idempotent via `clientOpId`. Returns `{applied, errors, pendingBefore}`.
- **`/api/v25/products/{id}/86`**: toggles 86 (out-of-stock) flag. Persists `eightySixed`, `eightySixedAt`, `eightySixedBy`. Sets stock to 0 when 86'd. Returns a `suggestedSubstitute` so the cashier can offer it on the spot.
- **`/api/v25/substitute`**: now ranks substitutes by price-proximity + stock and attaches a `substitutionReason` string per result.
- **`/api/v25/kiosk/session/{sid}/upsell`**: smart category-based upsell — examines what's missing in the kiosk cart and suggests up to 3 complementary items with reasons (e.g. "Add a drink to round out the meal", "Save room for something sweet").
- **`Product` pydantic model** gained `active`, `eightySixed`, `eightySixedAt`, `eightySixedBy` so the 86 flag round-trips through `GET /api/products`.

### Frontend
- **POSTerminal refactor**: extracted three components into `/app/frontend/src/components/pos/`:
  - `SwipeableCartItem.jsx` — left-swipe delete, right-swipe repeat
  - `CustomerCombobox.jsx` — cmdk-based searchable customer picker
  - `PaymentDialogs.jsx` — QR / UPI / Split payment dialogs as named exports
- **Fluid POS dashboard**: product grid switched to `[grid-template-columns:repeat(auto-fill,minmax(130px,1fr))]` (was fixed `grid-cols-3 sm:4 md:5 lg:6`). Side cart panel is `w-full lg:w-[440px]` so it stacks on narrow viewports.
- **Category icons on the POS**: each category button shows its custom icon + color (icon in coloured tile, active state floods the button with the category colour, not the global theme colour).
- **Categories admin (`/categories`)** rewritten with: large icon preview card, name+sortOrder+active inputs, **icon picker grid (21 lucide icons)**, **15-swatch colour row + custom colour picker**, live preview. Added `DialogDescription` for shadcn a11y.
- **`Barcode128`** extracted to shared `/components/Barcode128.jsx` (used by gift card sale page & subscription plans).
- **Login → POS redirect**: `Login.jsx` now uses `useNavigate('/pos', { replace: true })` after `login()` resolves.
- **86 indicator**: POSTerminal product tiles render a red "86" badge on out-of-stock items and disable the click handler (`opacity-50 cursor-not-allowed`).

### Frontend API surface (`services/api.js`)
- `itemsSystemAPI.createCategory/updateCategory` already accepted icon+color (passthrough).
- `v25API.processSync()`, `v25API.kioskUpsell(sid)`, `v25API.toggle86(id, eightySixed)`.

### Test status
- **Iteration 27**: Backend 10/10 PASS (seed idempotency, category icon CRUD, sync-queue replay, 86 toggle + substitute, kiosk upsell, gift card regression). Frontend POSTerminal + Categories admin rendered correctly.
- **Iteration 28**: Backend 6/6 PASS + Frontend 3/3 PASS — all action items from iteration 27 (Product model fields, login redirect, 86 badge, dialog a11y) verified fixed. `retest_needed=false`.


## v26.1 — Iteration 25-26 (Feb 2026): Unified Gift Cards + AI Marketing + AI Roster Blackouts + Live CFD

### Backend additions (`routes/v26_commerce.py`)
- **Unified Voucher↔Gift Card lifecycle**:
  - `POST /v26/vouchers` with `kind=gift` now also mints a paired `gift_card` row in `pending_activation` (shared code + barcode, `currentBalance=0`, `voucherId` linked).
  - `POST /v26/gift-cards/{code}/activate` — idempotent state transition pending → active. Sets `currentBalance = initial + bonus`, writes an `activate` ledger row in `db.gift_card_transactions`. Called automatically by POS *after* the cart paying for the card settles.
  - `POST /v26/gift-cards/{code}/redeem` — atomic partial redemption via `find_one_and_update` guarded by `currentBalance >= amount`. Writes a `redeem` ledger row, flips status to `depleted` at 0.
  - `GET /v26/gift-cards/{code}/transactions` — ledger by ascending createdAt.
  - `GET /v26/gift-cards?status=...` — list (optional status filter).
  - `GET /v26/gift-cards/lookup/{code}` — back-fills legacy cards with `currentBalance`.
  - `POST /v26/gift-cards/sell` — counter sale activates immediately + writes ledger; online channel lands as pending.
- **AI Marketing Email engine**:
  - `POST /v26/marketing/email/generate` — LLM (`emergentintegrations` GPT-5.2) drafts a complete email featuring upcoming events, active vouchers, and tier perks. Audience-aware, tone-aware, horizon-aware. Persisted as `draft` in `db.marketing_emails`.
  - `GET /v26/marketing/emails` · `PATCH /v26/marketing/emails/{id}` · `DELETE /v26/marketing/emails/{id}`.
- **Customer Display live push**:
  - `POST /v26/cfd/push` — POS pushes live cart + customer to `db.cfd_live` (keyed by terminalId).
  - `GET /v26/cfd/enriched?terminalId=...` — returns the pushed feed enriched with customerName, tableNumber, pointsEarned/missed; falls back to `pos_tabs` when no live feed.

### Backend update (`routes/v15_features.py`)
- `POST /staff/auto-roster` now consumes `db.staff_availability`:
  - Filters out staff whose weekly availability excludes the day or whose blackoutDates cover that calendar date.
  - Response gains an `excluded[]` array `{staffId, staffName, date, reason}` and reasoning string reports exclusion count.

### Backend update (`routes/v25_suite.py`)
- `POST /v25/subscriptions/plans` now mints a scannable manualCode + barcode (`SUB-XXXX-XXXX`), accepts `inclusions[]`, `termsAndConditions`, `trialDays`, `priceAnnual`.

### Frontend additions
- **POSContext.js** — added `appliedGiftCards` tender array and `pendingGiftActivations` queue. `calculateTotal()` returns both `total` (gross) and `balanceDue` (after gift-card tenders) so cash/QR/UPI/Stripe only charge the remainder.
- **POSTerminal.jsx**:
  - "🎁 Apply" gift-card input inside the discount picker. Looks up the card, auto-tenders min(balance, balanceDue).
  - Totals panel shows applied gift cards as violet chips with × to remove + a "Balance due (after gift cards)" line.
  - `settleGiftCards()` runs after every successful checkout (standard / QR / UPI / Split) and: activates any pending-sold cards, redeems applied tenders, all via the ledger endpoints.
  - Live cart pushed to `/v26/cfd/push` 400ms-debounced on every cart/customer change.
- **V26Pages.jsx**:
  - `VoucherManager.save()` surfaces the auto-minted gift-card code in a toast when `kind=gift`.
  - **New `MarketingEmails` page** (`/marketing-emails`) — generate · list drafts · edit subject/preheader/body/sms/cta · delete (owner only). Bottom Dock entry added under Enterprise.
- **api.js** — `v26API` extended: `listGiftCards`, `activateGift`, `redeemGiftPartial`, `giftTransactions`, `generateMarketingEmail`, `listMarketingEmails`, `updateMarketingEmail`, `deleteMarketingEmail`, `cfdPush`.

### Test status (Iteration 25 + 26)
- **Backend**: 19/19 PASS (`/app/test_reports/iteration_25.json`) — full gift-card lifecycle, ledger correctness, AI marketing CRUD, blackout-aware roster, live CFD.
- **Frontend**: 6/6 PASS (`/app/test_reports/iteration_26.json`) — gift card chip in POS totals, voucher creation toast, marketing email generator + editor, bottom-dock entry.

### Known status
- License enforcement remains feature-flagged OFF for dev (`LICENSE_ENFORCEMENT_ENABLED=false`).
- P2 backlog items (offline-first sync, kiosk mode, smart 86/substitution) have working MVP backend + frontend stubs from earlier iterations — production-grade refinement still backlogged.

