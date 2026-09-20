# Nua — Restaurant OS

> **Updated 14 September 2026**
>
> An AI-first restaurant operating system. POS, kitchen, reservations, inventory, accounting, loyalty, social-media marketing — all in one place. Built with React + FastAPI + MongoDB. Themed in NUA's signature orange / purple / pink palette and rebranded as **Nua - Restaurant OS** from iteration 37 onward.
>
> This is a multi-tenant SaaS platform: many businesses share one deployment, each other's data kept apart by application-level `businessId` scoping (no per-tenant database or schema separation). A security/tenant-isolation audit found and fixed a severe class of bugs in that scoping this year — see [`backend/TRUST_RELEASE_FINAL_REPORT.md`](backend/TRUST_RELEASE_FINAL_REPORT.md) for the honest, evidence-backed account of what's fixed, what's tested, and what's still a known, documented gap before calling any part of this "production-ready" for a real multi-tenant deployment.

---

## Table of Contents

1. [What you get](#what-you-get)
2. [Tech stack](#tech-stack)
3. [Quick start](#quick-start)
4. [Demo credentials](#demo-credentials)
5. [Feature map](#feature-map)
6. [Project timeline (Day 1 → today)](#project-timeline-day-1--today)
7. [Repository layout](#repository-layout)
8. [API surface (selected)](#api-surface-selected)
9. [Configuration](#configuration)
10. [Testing](#testing)
11. [Roadmap / Backlog](#roadmap--backlog)

---

## What you get

- **POS Terminal** — fluid grid, modifier picker, dine-in / takeaway flows, customer attachment, points-and-pay, split payments with validation, QR / UPI / Cash / Card / Stripe, gift cards, vouchers, modifier sheet, live status bar with date/time/devices/network, table/walk-in inputs.
- **Kitchen Display** — station readiness, kitchen heat, station rebalance, prep-time AI sync.
- **Reservations** — booking inbox AI parser (web/social/SMS), AI auto-assign tables, channel source badges, overbooking guardrail, phone agent.
- **Catalog (Products & Promotions)** — categories with icons & colours, multi-modifiers, bulk-edit (price ±%, cost, GST, image, 86, modifiers), inline edit, image library, drag-to-select marquee, recently-edited sidebar, CSV import/export, promotion dialog with day-of-week & time-window targeting.
- **Channel Menus** — per-platform (Uber, DoorDash, Menulog, Deliveroo, Website, Kiosk, Google Food) pricing overrides, AI prep-time sync, AI slow-mover discounts.
- **Inventory & Accounting** — ingredients with base units (g/mL/ea), recipes with auto unit conversion, auto stock deduction on sale, weighted-moving-average ingredient cost, stock-take with shrinkage, BAS / GST report (FY + quarter + CSV), Fair Work superannuation by award.
- **CRM** — customers, tiers, points, your-usual, GDPR export/erase, cohort retention, booking heatmap.
- **Loyalty Engine** — category multipliers, points-and-pay (10pt = 10c floor), Ash AI agent.
- **Online Ordering** — public storefront, AI ETA with surge & queue penalty, kitchen load board, order tracking.
- **Social Media Marketing** — connect mocked Instagram/Facebook/TikTok/X/Google Business; AI composer (Claude Sonnet 4.6) generates caption + hashtags + image alt; **Content Calendar** with month grid, drag-to-reschedule, AI Weekly Plan that schedules 7 days from top sellers + active promos; wired to image library.
- **Voucher / Gift Card** lifecycle — auto-mint on sale, partial redemption ledger, barcode print, in-POS apply.
- **AI Suite** — voice recipe (Whisper + GPT), AI Pantry invoice OCR + suggested price, AI upsell strip, AI cost coach, AI labor forecast, AI price tune with audit, AI surge pricing, AI marketing emails, AI overbooking check.
- **Enterprise** — multi-tenant licensing with ABR/ABN verification, 30-min JWT entitlement, Stripe billing webhook with progressive lockout, audit log, 2FA, device fleet, dispute & evidence packs, supplier marketplace, multi-site command center, franchise dashboard, fraud detection, dynamic pricing, subscriptions, kiosk, customer-facing display, profit guardian, station readiness.
- **Integrations Hub** — Stripe, ElevenLabs, OpenAI, Anthropic, Gemini, 12 AU banks, 15 payment terminals, Resend, SendGrid, Twilio, Xero (placeholders), Uber Eats / DoorDash channel pricing.

## Tech stack

| Layer        | Tech                                                                  |
| ------------ | --------------------------------------------------------------------- |
| Frontend     | React 18, React Router 6, Tailwind, shadcn/ui, lucide-react, sonner   |
| Backend      | FastAPI, Pydantic, Motor (async MongoDB), httpx                       |
| Database     | MongoDB                                                               |
| LLMs         | Claude Sonnet 4.6 / GPT-5.x / Gemini (via `emergentintegrations`)     |
| Auth         | JWT (`jose`) + bcrypt + optional 2FA                                  |
| Payments     | Stripe (test key in pod env)                                          |
| Object store | base64-encoded data URLs (compressed client-side to ≤1.5 MB)          |

## Quick start

```bash
# 1. Backend
cd /app/backend
pip install -r requirements.txt
# Set MONGO_URL, DB_NAME, EMERGENT_LLM_KEY in .env (already pre-configured in the pod)
sudo supervisorctl restart backend

# 2. Frontend
cd /app/frontend
yarn install
sudo supervisorctl restart frontend
```

Both services are managed by **supervisord** with hot reload. Use `sudo supervisorctl status` to inspect.

## Demo credentials

| Role     | Email                | Password           |
| -------- | -------------------- | ------------------ |
| Owner    | `owner@nua.com`     | `NuaOwner2026!`   |
| Manager  | `manager@nua.com`   | `Staff2026!`       |
| Cashier  | `cashier@nua.com`   | `Staff2026!`       |
| Kitchen  | `kitchen@nua.com`   | `Staff2026!`       |
| 2FA code | `123456`             | (demo only)        |

## Feature map

| Area                    | Route                | Backend module                                       |
| ----------------------- | -------------------- | ---------------------------------------------------- |
| POS                     | `/pos`               | `routes/transactions.py`, `routes/products.py`       |
| Kitchen                 | `/kitchen`           | `routes/kitchen.py`                                  |
| Reservations            | `/reservations`      | `routes/reservations.py`, `routes/bookings_inbox.py` |
| Items                   | `/products`          | `routes/products.py`, `routes/items_system.py`       |
| Channel Menus           | `/channel-menus`     | `routes/channel_menus.py`                            |
| Inventory & Accounting  | `/inventory-accounting` | `routes/inventory_accounting.py`, `routes/awards.py` |
| Customers               | `/customers`         | `routes/customers.py`                                |
| Loyalty                 | (POS embed)          | `routes/loyalty_engine.py`                           |
| Online Ordering         | `/online-orders`, `/order-online`, `/track/:code` | `routes/online_orders.py` |
| Social Media Marketing  | `/social-media`      | `routes/social_media.py`                             |
| Enterprise Command      | `/enterprise`        | `routes/v25_suite.py`, `routes/v26_commerce.py`      |
| License & Billing       | `/license`           | `routes/licensing.py`                                |

## Project timeline (Day 1 → today)

Each block is one user-driven iteration. Bullets are the **user instruction** plus what shipped.

### Day 1 — Foundation (Iterations 1–10, late 2025)
- **Build a restaurant POS** — initial scaffold: React + FastAPI + MongoDB, basic products / categories / transactions / customers CRUD, auth (JWT + bcrypt) with seeded admin user.
- **Add a kitchen display** — `/kitchen` with station load, prep timers, ticket aging.
- **Reservations** — table management, party-size grid, status flow.
- **Customer DB** — visits / spend / points / tier; "your usual" derived from last 20 transactions.
- **Modifiers, Discounts, Comps/Voids, Payment Links** — full `items_system` CRUD.

### Day 2 — Analytics + AI Wave 1 (Iterations 11–18, Dec 2025)
- **Analytics dashboard** — revenue, top items, hour-of-day heatmap.
- **AI upsell strip** under the POS cart (LLM-driven, debounced 1.2s).
- **AI Cost Coach, Labor Forecast, Surge Pricing, Voice Recipe** pages and endpoints (Wave 2).
- **Phone Agent, Purchase Orders, A/B Testing, Agent Autonomy** (Iteration 24).
- **Auto-PO from low stock**, **Auto-VIP tier promotion**, voice "raise espresso 50c" actions verified.

### Day 3 — Enterprise + Licensing (Iterations 25–27, Jan 2026)
- **Iteration 25–26** — Unified Gift Cards + AI Marketing Emails + AI Roster Blackouts + Live CFD. Atomic `find_one_and_update` gift-card redemption with ledger; `/v26/cfd/push` for live customer-facing display.
- **Iteration 26 (Enterprise)** — `routes/v25_suite.py` with 30+ endpoints: sync queue, exceptions, sites, hardware fleet, disputes, supplier marketplace, kiosk, CFD, recovery, station readiness, margin guardrails, dynamic pricing, subscriptions, gift cards, recipes, waste, concierge, reputation, franchise, fraud detection, Ash Pro, profit guardian, digital twin. EnterpriseCommandCenter UI with 24-tile launcher.
- **Iteration 27 (Licensing)** — `routes/licensing.py`: ABR-verified ABN issuance, JWT entitlement tokens, device fleet, Stripe billing webhooks with state machine `active → past_due → grace → suspended → cancelled`, owner+2FA ABN change with support override, lock screen overlay, audit log. `LicenseEnforcementMiddleware`.

### Iteration 28 — POS Refactor + Fluid Layout + Seed Catalog (Jan 2026)
- **"Make POS fluid and prettier"** — switched product grid to `auto-fill,minmax(130px,1fr)`, side cart `w-full lg:w-[440px]`. Extracted `SwipeableCartItem`, `CustomerCombobox`, `PaymentDialogs`.
- **"Add icons and colours per category"** — categories accept `icon` + `color`; admin page rewritten with 21-icon picker grid + 15-swatch row.
- **"Seed a real menu"** — `POST /api/seed/catalog` (owner): 5 canonical categories, 60 products, 10 modifiers (idempotent).
- 86-toggle on POS tiles + smart substitution + kiosk upsell.

### Iteration 29 — Online Ordering + Invoice OCR + Item Insights (Jan 2026)
- **"Build me online ordering"** — public storefront `/order-online`, owner pipeline board `/online-orders`, tracking `/track/:code`. Channel-aware (pickup/delivery/dine-in). AI ETA = base prep × surge × queue + delivery offset, wrapped in LLM-generated friendly message.
- **"Let me upload a supplier invoice and bump prices"** — AI Pantry invoice tab; LLM extracts supplier/items, fuzzy-matches to products, suggests price preserving margin %.
- **"Show me which items make money"** — `/api/products/insights` with weeklyUnitsSold / weeklyRevenue / marginAmount / marginPct. Product cards render margin chip (green ≥60% / amber ≥40% / red <40%) and a weekly-sales tile.

### Iteration 30 — Notifications + Recipes + BAS / GST + Stock-take (Jan 2026)
- **"Connect SendGrid + Twilio"** — `utils/notifications.py` channel abstraction. Wiring real channels is now a config change.
- **"Ingredients → Recipes → auto stock deduction"** — `routes/inventory_accounting.py`; recipes with kg↔g, L↔mL conversion; `deduct_recipe_stock(productId, qty)` runs on every sale.
- **"Invoice → ingredient assignment"** — increments stock with WMA cost, cascade re-rolls every dependent recipe.
- **"Stock-take with variance"** — counts vs expected → totalShrinkageValue.
- **"Australian BAS / GST report"** — G1, 1A (= total/11), G11, 1B, netGstPayable. CSV export.

### Iteration 31 — NUA Brand + Items: Categories & Multi-Modifiers + Page Split (Feb 2026)
- **"Apply NUA brand identity globally"** — orange `#f58c14` / purple `#8b5cf6` / pink `#ec4899`. Legacy indigo migrates from localStorage on next load. Light/dark toggle in BottomDock.
- **"Items must support multi-modifier assignment + dynamic categories"** — `categoryId` + `modifierIds[]` on Product. Multi-toggle chip picker in the dialog.
- **"Split V25/V26 page bundles"** — barrel re-exports; implementations in `/pages/v25/*.jsx` (21 files) and `/pages/v26/*.jsx` (5 files).

### Iteration 32 — POS Modifier Picker (Feb 2026)
- **"POS should prompt for modifiers when item has them"** — `ModifierSheet` opens on every product tap when `modifierIds.length > 0`. Required vs Optional badges, single/multi-select with `maxSelections`, per-option surcharges. Cart line gets a synthetic id so two Flat Whites with different milk are separate lines but resolve to the same product.

### Iteration 33 — Items Power Tools (Feb 2026)
- **"Add sort/filter, bulk-edit, image library, inline edit"** —
  - Toolbar: search by name/SKU, sort by name/category/price/stock/margin/recent-edit asc/desc, status filter, grid/table toggle, CSV export.
  - Category filter chips, select-all visible, per-row checkboxes.
  - Bulk: change category, ±% price, set cost/GST, set image (from library), 86/un-86, add/remove modifier ids, delete.
  - **Image Library** — owner uploads once, auto-compressed to ≤800px / 0.85 JPEG; picker reusable from single-product and bulk dialogs.
  - **Inline edit** on cards & rows for name/price/stock. Per-row quick 86 toggle.

### Iteration 34 — Big Sweep (Feb 2026)
- **"Cart Dine-in / Takeaway table inputs, POS Date/Time header, Super via Fair Work, AU Bank integrations, AI Bookings Inbox, Channel Menus overrides, Kitchen Heat AI prep times, P2 auth refactors"** — all of the above shipped:
  - POSHeaderBar with clock + date + connected devices + network.
  - Free-text table input for dine-in, walk-in-name for takeaway.
  - Fair Work Modern Awards catalogue with 7 seeded awards; superannuation computation by award.
  - 12 AU bank cards + 15 payment terminals in the Integrations Hub.
  - `/api/bookings-inbox` — AI parses inbound bookings from web/social/phone/SMS; convert to reservation in one click.
  - **Channel Menus** CRUD; per-channel price overrides; AI Kitchen Heat prep-time sync; AI slow-mover discount endpoint.
- **P2 auth refactor (partial)** — `_require_owner_or_manager` moved to `deps.py` (full apply landed in iteration 36).

### Iteration 35 — P0 Auth Precedence (Feb 2026)
- **"401/403 must fire before Pydantic 422"** — `deps.py` exposes `get_user`, `require_owner`, `require_owner_or_manager` as top-level FastAPI `Depends`. Refactored `products.py`, `items_system.py`, `channel_menus.py`. Anonymous POSTs with bogus payloads now correctly return 401, not 422.

### Iteration 36 — Full Auth Refactor + Products.jsx Split (Feb 2026)
- **"Apply the Depends pattern to all the legacy routers"** — 16 routers, ~230 endpoints refactored: `advanced_features`, `ai_pantry`, `enterprise_features`, `gamification`, `inventory_accounting`, `licensing`, `loyalty_engine`, `menu_features`, `multi_tenant`, `online_orders`, `phase_ef`, `phase_ef_wave2`, `reservation_features`, `staff_management`, `v15_features`, `v25_suite`, `v26_commerce`. Edge cases referencing `request` after the auth block (~8 endpoints) intentionally skipped for bespoke handling.
- **CRITICAL fix** — `/loyalty/redeem` auth bypass: legacy `routes/loyalty.py` was registering the route BEFORE the auth-protected one in `loyalty_engine.py`. Removed.
- **"Split Products.jsx into Toolbar / ProductTable / BulkEditDialog"** — 963 → 618 lines.

### Iteration 37 — Drag-to-Select Marquee + Recently Edited + Nua Rebrand (Feb 2026)
- **"Drag-to-bulk-select rectangle on the Products grid, plus a Recently Edited sidebar showing the last 10 items touched today"**
  - Finder-style marquee on the grid: mouse-down on empty space → drag → cards intersecting are selected. Shift/⌘/Ctrl = additive. Escape cancels. Drags on buttons/inputs ignored. 6px movement threshold.
  - `RecentlyEditedSidebar` top-10 with optimistic `touchTimes` map so the list updates instantly.
- **"Change title to Nua - Restaurant OS and make sure no emergent anywhere in code"** — title + PWA manifest rebranded. Only `EMERGENT_LLM_KEY` env var and `emergentintegrations` package stay (functional, not user-facing).

### Iteration 38 — Social Media Marketing + Loyalty + Split + Promotion Extract (Feb 2026)
- **"Extract Promotion dialog from Products.jsx"** — `components/products/PromotionDialog.jsx`.
- **"Make sure all components are interconnected for CRM, stock and availability"** — verified: `routes/transactions.py` decrements stock + recipe ingredients + customer totals on every sale; 86-toggle honoured everywhere.
- **"Split payment should update as per selection, and it should check if wrong payment is entered, also after payment"** — Pay button disabled on ≤ 0 or excess. Imbalance warning banner when custom-mode splits don't add to the bill. Final txn refuses to create if splits don't balance within 1¢.
- **"Customers can redeem points for payments, a minimum of 10 points for 10 cents"** — `minRedeem` 50 → 10 in `loyalty_engine.py`; POS shows "Points & Pay (1 pt = $0.01, min 10)".
- **"Social Media Marketing should be AI-implemented, posting posts/stories/reels from products and deals + specials, connected to image library"** —
  - `routes/social_media.py`: accounts (mock OAuth) for Instagram/Facebook/TikTok/X/Google Business, posts CRUD, publish stub, `POST /social/ai-generate` (Claude Sonnet 4.6).
  - `/social-media` page: composer (source toggle product/promotion/special, tone, format, platforms, image picker, schedule), drafts preview with editable captions and hashtag chips, posts history table.

### Iteration 39 — Content Calendar + AI Weekly Plan + README (Feb 2026)
- **"Add a content calendar + AI weekly plan, keep Social Media features as is"** — `components/social/SocialCalendar.jsx`:
  - Month grid, colour-coded chips per platform, drag-to-reschedule via `PATCH /api/social/posts/{id}`.
  - **AI Weekly Plan** — `POST /api/social/ai-weekly-plan`: pulls top-7 selling products from the last 7 days, mixes with active promos and chef-special seeds, distributes one post per connected platform per day. Idempotent — re-running deletes prior `autoPlanRun=true` posts in the window before regenerating.
  - "Next 7 days" upcoming strip with inline publish / delete.
  - Composer / Calendar tab toggle at the top of `/social-media`.
- **"Create a README from Day 1 till today"** — this file.

### Iteration 40 — Background Worker + Calendar Edit/Reuse + Bespoke Auth Cleanup (25 Jun 2026, current)
- **"Move ai_weekly_plan to a background task"** — `POST /social/ai-weekly-plan` now returns in **~64ms** (was 130s) with `{planId, status:'queued', expected, message}`. A FastAPI `BackgroundTasks` worker streams progress into `social_plan_jobs` so each LLM call is observed. New `GET /social/plan-jobs/{plan_id}` for polling: returns `{status: queued|in_progress|complete|failed, completed, expected, fallbacks}`. Calendar UI shows a live progress bar (`plan-progress-bar`) and refreshes chips as they're generated.
- **"Schedule calendar post can be edited by the owner and reused when needed"** —
  - **Edit dialog** on the Calendar: click any chip OR the new `Pencil` icon in the Next-7-Days strip → opens a form with caption, hashtags, schedule, image URL and status. `PATCH /api/social/posts/{id}` already supported it; UI wires through `data-testid=edit-post-dialog`.
  - **Duplicate / Reuse** — new `POST /api/social/posts/{id}/duplicate` clones a previous post as a fresh draft, strips `autoPlan*` flags + `publishedAt`, regenerates id + timestamps, records `duplicatedFrom`. Optional body keys (`platform`, `caption`, `hashtags`, `imageUrl`, `scheduledFor`, `status`) let the owner tweak at duplicate time. New `Copy` icon on every upcoming row + an inline button inside the Edit dialog header.
- **"Improve weekly-plan error wording to distinguish no-connected vs no-matching-platforms"** — `ai-weekly-plan` now returns a **structured `detail`** with `code: 'no_connected_accounts' | 'no_matching_platforms'`, plus `connected[]` and `requested[]`. The UI surfaces `.message` if present, falls back to the raw detail otherwise.
- **"P2 ~8 legacy inline-auth endpoints"** — cleared (the last batch with multi-line signatures or post-auth `request` usage). Refactored:
  - `accounting/bas` and `accounting/bas.csv` — request dropped from sig, gated by `Depends(require_owner_or_manager)`.
  - `licensing/abn/approve/{req_id}` — request kept (reads `X-Support-Override` header) + `Depends(require_owner)`.
  - `agent/tick` and `agent/voice-command` (loyalty_engine) — request kept (voice flow), auth via Depends.
  - `agent/auto-publish-roster` and `agent/tick-extended` (phase_ef) — Depends-gated.
  - `v25/products/{id}/86` — custom owner+manager+kitchen role check kept (after Depends auth).
  - `v25/ash-pro/approve` — Depends(require_owner).
  - `v25/concierge` — Depends(get_user).
  - `v25/warehouse/export` — Depends(require_owner).
  - Only `bookings_inbox.ack` retains inline auth — intentional graceful-degradation for webhook callers.
- **README updated** (this file).

### Trust Release — security hardening + Voice POS + Loyalty 3.0 + Booking 3.0 (Sep 2026)

Not a single user-typed instruction like the iterations above — a multi-week directive to independently audit and harden the platform for a genuine multi-tenant SaaS deployment (every business's data kept apart on one shared database, with no per-tenant schema), then build three deferred features on top of a verified-solid foundation. Full detail, every fix cited with its file and commit, is in [`backend/TRUST_RELEASE_FINAL_REPORT.md`](backend/TRUST_RELEASE_FINAL_REPORT.md) and [`backend/TENANT_ISOLATION_REMAINING_WORK.md`](backend/TENANT_ISOLATION_REMAINING_WORK.md) — this entry is the short version.

- **P0 — security & safety foundation.** CI restored and strengthened (flake8, mypy, pip-audit, gitleaks, npm audit, e2e job). Hardcoded secret fallbacks removed (7 files now fail closed instead of trusting a default key). Stripe/webhook signature verification now rejects unsigned or misconfigured payloads instead of silently accepting them. Ash (the AI agent)'s tool-execution safety hardened: an owner-only audited kill switch, high-risk tools can no longer be set to auto-execute, idempotency keys on tool calls, rollback for the directive's named action types. Financial/offline integrity: refund caps and online-order status transitions made atomic (were exploitable by two concurrent requests), stock floor added, offline-queue replay dedup end-to-end.
- **P0.3 — tenant isolation, the largest single effort.** The original audit found 38 of 58 backend route files with zero `businessId` scoping. Two root causes were found and fixed: `ActorContextMiddleware` let a client-supplied header override the JWT-derived tenant on write, and `_stamp_new()`'s `doc.setdefault("businessId", ...)` was a no-op against a field that already existed as `None` on every `BaseEntity` model — meaning **every product ever created was tagged `businessId=None` and visible to every other business on the deployment**, silently, since the feature was built. Beyond the original 34-file list, the same sweep found and fixed a comparable root-cause bug in `models/reservation.py` (no `businessId` field at all — the entire reservations/bookings system, direct guest PII included, had been unscoped since it was written) and in `loyalty_ledger` (every points earn/redeem/refund event, at every real write site). Nine-plus confirmed zero-authentication endpoints were found across `bill_split.py`, `awards.py`, `reservations.py`'s floor-plan and waitlist CRUD, `channel_menus.py`, `loyalty.py`, and `loyalty_engine.py`'s reports — reachable with no credential, or by any authenticated staff member regardless of business. All fixed with the same pattern throughout (`tenant_scope_filter`/`tenant_owns`), each with its own regression test, the full backend suite re-run before every commit. What's still a documented, deliberate gap (not silently left broken) is in `TENANT_ISOLATION_REMAINING_WORK.md`.
- **Voice POS** — the `/agent/voice-command` router existed and was wired into the UI, but its target endpoint had been deleted; the mic button silently did nothing. Rebuilt end-to-end and verified in a real browser (Playwright, fake audio device) — recording, transcription request, and a genuine `agentAPI.tick()`/navigation response. The AI Phone Agent's "order" intent now actually creates a kitchen ticket via `services/channel_orders.py` instead of only logging what it heard.
- **Loyalty 3.0** — a unified guest-facing loyalty passport (points, tier, badges, milestones, active subscription) surfaced a severe pre-existing gap: `routes/loyalty_v2.py`'s badge/milestone catalogs, challenges, referrals and leaderboard had zero tenant scoping at all, on par with the `_stamp_new` finding. Tier perks are now enforced for real (Silver+ jumps the waitlist queue, never ahead of an earlier-joined fellow member) and a redemption-cost-vs-incremental-spend ROI report was added, explicit in both its docstring and its response about being a same-business snapshot proxy, not a causal cohort study.
- **Booking 3.0** — deposits are now collected through a real Stripe Checkout session (not a staff-ticked checkbox), and a no-show only forfeits a deposit that was actually collected — never a bare flag. A per-business cancellation-policy engine (configurable free-cancellation cutoff, default 24h) decides refund vs. forfeit on cancellation. The waitlist's "Notify" button now sends a real SMS instead of only changing a status label. Honest limit, stated in the code: NUA has no saved-card/off-session-charge capability (only Stripe's one-time hosted Checkout), so a walk-in that never had a deposit collected still can't be charged a no-show fee after the fact.

## Repository layout

```
/app
├── backend/
│   ├── deps.py                     # FastAPI auth dependencies (single source of truth)
│   ├── database.py                 # Motor client + DB_NAME
│   ├── server.py                   # FastAPI app + router registration
│   ├── middleware/
│   │   └── license_middleware.py
│   ├── models/                     # Pydantic models (product, transaction, customer, …)
│   ├── routes/
│   │   ├── auth.py
│   │   ├── products.py
│   │   ├── items_system.py
│   │   ├── transactions.py
│   │   ├── customers.py
│   │   ├── reservations.py
│   │   ├── kitchen.py
│   │   ├── analytics.py
│   │   ├── inventory_accounting.py
│   │   ├── awards.py
│   │   ├── channel_menus.py
│   │   ├── bookings_inbox.py
│   │   ├── social_media.py
│   │   ├── loyalty_engine.py
│   │   ├── licensing.py
│   │   ├── v15_features.py / v25_suite.py / v26_commerce.py
│   │   ├── phase_ef.py / phase_ef_wave2.py
│   │   └── ...
│   ├── services/
│   │   └── abr_service.py
│   ├── utils/
│   │   └── notifications.py
│   └── tests/                      # pytest suites per iteration
├── frontend/
│   ├── public/
│   │   ├── index.html              # title: "Nua - Restaurant OS"
│   │   └── manifest.json           # PWA name: "Nua - Restaurant OS"
│   ├── src/
│   │   ├── App.js                  # routes
│   │   ├── contexts/               # AuthContext, POSContext, ThemeContext, LicenseContext
│   │   ├── services/api.js         # axios bindings
│   │   ├── components/
│   │   │   ├── BottomDock.jsx
│   │   │   ├── ImageLibrary.jsx
│   │   │   ├── pos/                # ModifierSheet, PaymentDialogs, SwipeableCartItem, …
│   │   │   ├── products/           # ProductsToolbar, ProductTable, BulkEditDialog,
│   │   │   │                        # PromotionDialog, RecentlyEditedSidebar
│   │   │   ├── social/             # SocialCalendar (NEW)
│   │   │   └── ui/                 # shadcn primitives
│   │   └── pages/
│   │       ├── POSTerminal.jsx
│   │       ├── Products.jsx
│   │       ├── ChannelMenus.jsx
│   │       ├── BookingsInbox.jsx
│   │       ├── SocialMedia.jsx     # composer + calendar
│   │       ├── InventoryAccounting.jsx
│   │       ├── EnterpriseCommandCenter.jsx
│   │       ├── LicensePage.jsx
│   │       ├── v25/   v26/         # split bundles
│   │       └── ...
├── memory/
│   ├── PRD.md                      # full per-iteration changelog
│   └── test_credentials.md
└── test_reports/                   # iteration_NN.json per testing-agent run
```

## API surface (selected)

Every endpoint is prefixed `/api`. Auth via Bearer JWT from `POST /api/auth/login`.

| Domain         | Endpoint(s)                                                           | Notes |
| -------------- | --------------------------------------------------------------------- | ----- |
| Auth           | `POST /auth/login`, `POST /auth/2fa/{setup,verify,disable}`           | JWT + optional 2FA |
| Products       | `GET/POST/PUT/DELETE /products`, `POST /products/bulk-edit`           | Bulk has fast `update_many` path |
| Modifiers      | `GET/POST/PUT/DELETE /modifiers`                                      | |
| Categories     | `GET/POST/PUT/DELETE /categories`, `POST /categories/cleanup-legacy`  | icon + color + prepTime + channels |
| Transactions   | `GET/POST /transactions`, `POST /transactions/refund`                 | Stock + recipe + customer cascade |
| Loyalty        | `GET/PUT /loyalty/config`, `POST /loyalty/redeem`, `GET /loyalty/reports/roi` | `minRedeem` = 10 (= $0.10); ROI report is a same-business proxy, not a causal cohort study |
| Loyalty 2.0    | `GET /loyalty/v2/passport/{customerId}`, `.../badges`, `.../challenges`, `.../referrals`, `.../leaderboard` | Unified guest passport + tier badges/milestones |
| Reservations   | `GET/POST /reservations`, `POST /reservations/{id}/ai-assign-table`, `POST .../request-deposit`, `GET/PUT /reservations/cancellation-policy` | AI auto-assign by party size; real Stripe deposit collection; per-business cancellation cutoff |
| Waitlist       | `GET/POST /waitlist`, `PUT /waitlist/{id}` (status→`notified` sends a real SMS), `GET /waitlist/track/{code}` | Silver+ tier jumps the queue |
| Voice POS      | `POST /agent/voice-command`, `POST /phone-agent/simulate`             | Voice command → `agentAPI.tick()`/navigate; phone agent places real orders |
| Bookings Inbox | `POST /bookings/inbox`, `POST /bookings/inbox/{id}/ack`               | AI parse → reservation |
| Channel Menus  | `GET /channel-menus/{channel}`, `POST .../patch`, `.../ai-prep-times`, `.../ai-discount-slow` | |
| Awards         | `GET /awards/catalogue`, `POST /awards/install`, `POST /payruns/super-by-award` | Fair Work AU |
| Social Media   | `GET /social/platforms`, `GET/POST/DELETE /social/accounts`, `GET/POST/PATCH/DELETE /social/posts`, `POST /social/posts/{id}/publish`, `POST /social/ai-generate`, `POST /social/ai-weekly-plan` | Mock OAuth; AI via Claude Sonnet 4.6 |
| Online Orders  | Public: `GET /online/{categories,products}`, `POST /online/orders`, `GET /online/orders/track/{code}` · Auth: `GET /online/orders`, `PATCH .../status`, `POST .../eta` | AI ETA |
| Licensing      | `POST /license/{onboard,validate}`, `POST /license/device/{activate,revoke}`, `POST /license/abn/change-request`, `POST /license/stripe/webhook` | Progressive lockout |

## Configuration

Environment variables (all in `.env` files, never hard-coded):

| Var                       | Where             | Required | Notes                                     |
| ------------------------- | ----------------- | -------- | ----------------------------------------- |
| `MONGO_URL`               | `backend/.env`    | ✅       | Don't rename                              |
| `DB_NAME`                 | `backend/.env`    | ✅       | Don't rename                              |
| `EMERGENT_LLM_KEY`        | `backend/.env`    | ✅       | Universal LLM key for all AI features      |
| `LLM_GATEWAY_URL`         | `backend/.env`    | optional | Defaults to the Emergent gateway          |
| `JWT_SECRET`              | `backend/.env`    | ✅       | Signs entitlement tokens                  |
| `STRIPE_API_KEY`          | `backend/.env`    | optional | Live billing                              |
| `STRIPE_WEBHOOK_SECRET`   | `backend/.env`    | optional | Verifies Stripe webhooks                  |
| `SENDGRID_API_KEY`        | `backend/.env`    | optional | When set, real emails fire                |
| `TWILIO_ACCOUNT_SID`      | `backend/.env`    | optional | When set, real SMS fires                  |
| `ABR_GUID`                | `backend/.env`    | optional | Live ABR ABN verification                 |
| `ALLOW_ABR_DEV_SKIP`      | `backend/.env`    | optional | Off by default (production-safe)          |
| `REACT_APP_BACKEND_URL`   | `frontend/.env`   | ✅       | Don't rename                              |

## Testing

- **Fast unit/route tests (the ones to run locally and in CI)** — `cd backend && python3 -m pytest tests/inprocess -q`. Runs entirely against `mongomock-motor`, no live database or server needed — this is the suite every Trust Release fix was validated against, full run, before every commit. **613 passing** as of the security-hardening + Voice POS/Loyalty 3.0/Booking 3.0 work above (up from 469 pre-Trust-Release).
- **Legacy live-server integration tests** — the flat `backend/tests/test_iteration*.py` / `test_*_features.py` files predate `tests/inprocess` and hit a real running instance over HTTP (`requests` against `REACT_APP_BACKEND_URL`), not mongomock. They need a deployed backend + real env vars to run at all; treat them as historical per-iteration scorecards (below), not as part of the fast local/CI loop.
- **End-to-end** — `testing_agent_v3_fork` is the integrated subagent used for full Playwright + curl runs. Reports land in `/app/test_reports/iteration_NN.json`.
- **Per-iteration scorecards**

| Iter | Backend | Frontend                | Notes                                                              |
| ---- | ------- | ----------------------- | ------------------------------------------------------------------ |
| 33   | 10/10   | 100%                    | Items power tools                                                   |
| 34   | 16/16   | 100%                    | Cart inputs, bookings inbox, super, banks, channel menus            |
| 35   | 42/42   | n/a                     | Auth precedence                                                     |
| 36   | 85/85   | full Products flow      | Auth refactor (×230 endpoints) + Products split + loyalty bypass fix |
| 37   | n/a     | 9/10 → 10/10 post-fix  | Drag-select + Recently Edited + Nua rebrand                         |
| 38   | 20/20   | ~88% (testid gaps only) | Social Media + Loyalty 10pt + Split + PromotionDialog               |
| 39   | curl-verified | self-tested      | Content Calendar + AI Weekly Plan + README                          |
| 40   | curl+pytest verified | self-tested | Background worker (~64ms enqueue) + Edit/Duplicate + bespoke auth   |
| Trust Release | 613/613 (`tests/inprocess`) | Voice POS: real-browser Playwright verified; Loyalty 3.0/Booking 3.0: pytest only | Security hardening + tenant isolation + Voice POS + Loyalty 3.0 + Booking 3.0 |

## Roadmap / Backlog

### P0 — security/trust gaps, known and documented (see `backend/TENANT_ISOLATION_REMAINING_WORK.md`)
- Remaining backend route files still needing a tenant-isolation pass — the original audit found 38, most are fixed (see the Trust Release entry above), a handful remain and are ranked by risk in the tracking doc.
- `loyalty_config` and a few `db.settings` singleton documents (business hours, print routing, email config) are still single global documents shared by every business on a deployment — no way for two businesses on one deployment to run different rates/settings yet.
- No saved-card / off-session Stripe charge capability (`SetupIntent` + a later `PaymentIntent`) — only the one-time hosted Checkout redirect exists today, which caps what "charge a no-show fee" or "auto-renew a subscription" can actually do.
- `table_ordering.py`'s guest-facing QR menu and `public.py`'s `join-waitlist` are genuinely public by design but carry no business-identifying signal in their request shape yet, so on a real multi-tenant deployment they'd need a `?business=` param threaded through (the pattern `online_orders.py`'s public storefront already uses) before they're safe to expose past a single-business demo.

### P1
- Real **SendGrid / Twilio API keys** to activate live notifications.
- **Real Meta / TikTok / X OAuth** to lift the social-publish stub.

### P2
- **Chargeback / dispute console** with evidence packs UI polish.
- **Hardware health monitoring** alerts.
- **`x-ai-parsed-fallback` response header** so the UI can warn when the LLM fell back.
- **Touch-friendly drag-and-drop** for the calendar (HTML5 DnD doesn't work on tablets) → `@dnd-kit` migration.
- Surface **`partialFailures`** on AI weekly-plan response so the UI can warn when some platforms used the template.

### Stretch
- Real-time WebSocket push for kitchen load and live A/B exposure.
- Surge pricing applied to live POS prices (currently only persisted).
- One-click `/voice-recipe` → product, with cost rolled up from ingredients.
- Auto-swap-finder + auto-EOD-email.

---

© Nua — Restaurant OS. Built iteratively. Tested rigorously. Themed boldly.
