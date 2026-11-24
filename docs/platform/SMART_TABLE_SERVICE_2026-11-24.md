# NUA Smart Table Service — Phase 1 Pilot Handoff
Date: 24 November 2026. PR: https://github.com/Sam-NUA/NUA/pull/44. Draft; not in main and off by default.

## Operational scope
Smart Table Service adds seven independent owner-configured deadlines with warnings and escalation: no order after seating (5/8 min), after actual drinks-served event without food order (8/12), entrée served with mains held (10/15), mains fired but not ready (20/30), food ready but unserved (3/5), after mains follow-up (12/18), bill requested but not handled (5/8). These are recommended defaults, not mandatory times.

Owners configure rules in Floor Plan → Smart Alerts, and managers can assign servers in the table drawer. Staff record milestone actions for drinks served, order taken, food ordered, entrée served, guest follow-up, bill request and bill delivery. Existing kitchen states supply fire, ready and served timestamps.

An authenticated NUA staff session polls about every 15 seconds; it shows a nonblocking popup and attention queue. The operator can open the table, acknowledge, snooze for 3 minutes or resolve. The API supports snooze durations 1/3/5/10/15 minutes. Mains firing is never automated by a reminder. Once a warning is escalated to urgent, a previous acknowledgement or snooze can reopen; staff still must check the table before using existing Fire controls.

Backend stores an idempotent alert per tenant, table session and rule. Data and assignment are business-scoped; owner/manager can see all, assigned floor staff see their own, unassigned floor alerts go to floor staff. Kitchen users see only kitchen delay and ready-pass events. Alert records expire after 90 days through a TTL index.

## Required acceptance before production
1. Verify existing security and CI gates, and inspect the new focused acceptance workflow.
2. Deploy to a controlled staging/test venue. No live payment acceptance testing.
3. Enable alerts as owner, set deliberately short test thresholds, seat a fake party, observe popups and current course colours.
4. Assign an employee to the table and validate that only permitted staff plus management receive alerts; check cross-tenant access is denied.
5. Mark drinks served, order taken, entrée served; fire mains manually from normal kitchen flow; mark ready and served; verify each alert auto-resolves.
6. Check duplicate alerts are not created by two signed-in tablets. Acknowledge/snooze/resolve on one, verify the other reflects the same status.
7. Test offline/reconnect, table cleared, switch venues, iPad/Android and Windows fullscreen; record signoff and timestamps.

## Limits
This is near-real-time polling, not push while the application is closed. POS carts not yet sent to the kitchen are not observable unless staff record Order taken. Identical physical table numbers across different floor plans cannot be safely joined to kitchen tickets. Full service-analytics reports, conditional shift presets and background push notifications are Phase 2.

Source PR #44 is independent of unmerged printer fleet PR #43.