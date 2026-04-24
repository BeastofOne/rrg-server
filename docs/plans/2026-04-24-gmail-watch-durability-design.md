# Gmail Watch Durability — Design

**Date:** 2026-04-24
**Status:** Approved for implementation
**Context:** 9-day silent lead-intake outage (April 16 → April 24) caused by expired Gmail watch on leads@resourcerealtygroupmi.com with no renewal and a health check that couldn't detect per-account silence.

## Problem

Three token/watch-related production incidents in ~7 weeks:

| Date | Failure | Class |
|------|---------|-------|
| Mar 7 | OAuth refresh token died | Testing-mode 7-day token expiry |
| Mar 17 | OAuth refresh token died | Testing-mode 7-day token expiry |
| Apr 16 → Apr 24 | leads@ watch expired, 9 days silent | Watch expiry + missing renewal schedule + blind health check |

The OAuth token class was resolved Mar 23 by moving the GCP project (`rrg-gmail-automation`) to Production. That removed the 7-day refresh-token clock.

The watch class remains. Google's hard limit: a Gmail watch expires in 7 days and must be re-registered. No service account, domain-wide delegation, or API plan removes this.

## Root cause of the April 16 incident

Two compounding failures:

1. **Renewal schedule for leads@ was deleted from the Windmill DB.** The local yaml (`schedule_gmail_leads_watch_renewal.schedule.yaml`) has `enabled: true`, but a DB query returns zero rows for any leads-related schedule. A prior `wmill sync push` wipe (Feb 25/26/28) likely removed it, and no subsequent push restored it.
2. **Health check is global, not per-account.** `check_gmail_watch_health` returns "healthy" if ANY webhook run exists recently. teamgotcher@'s heavy traffic masked leads@'s total silence for 9 days.

## Design principles

- **Do not change the pipeline.** Lead intake, draft generation, Gmail-based approval flow — all unchanged.
- **Observability and scheduling only.** The fix is renewal frequency + per-account health + alerting. No business logic touched.
- **Align with Google's explicit recommendation.** Google says call `watch()` daily. We do every 6 days. Move to daily.
- **Fail loud.** If anything breaks, Jake gets an SMS within hours. No more silent 9-day gaps.

## Architecture (5 layers)

### Layer 1 — Daily renewal (prevention)

Change renewal cadence from every 6 days to daily, for both accounts.

Files to update:
- `windmill/f/switchboard/schedule_gmail_watch_renewal.schedule.yaml` (teamgotcher@)
- `windmill/f/switchboard/schedule_gmail_leads_watch_renewal.schedule.yaml` (leads@, currently missing from DB)

Cron: `0 0 9 * * *` — 9 AM America/Detroit, every day.

Rationale: Google's own doc recommends daily. `watch()` is idempotent — calling while an active watch exists replaces it with no side effects. Daily gives a 6-day buffer against transient failures (OAuth hiccup, network, Google API blip) before a miss actually causes a watch expiration.

### Layer 2 — Per-account health check (detection)

Rewrite `f/switchboard/check_gmail_watch_health.py` to check each account independently.

Inputs (new):
- Track the most recent successful `setup_gmail_watch` / `setup_gmail_leads_watch` result in a Windmill variable: `f/switchboard/gmail_watch_state` — JSON `{"teamgotcher": {"expiration_ms": ..., "last_renewed": ...}, "leads": {...}}`. Each setup script writes its own entry at the end of a successful run.

Checks (per account):
- **Silence check:** most recent `gmail_pubsub_webhook` run with `result->>'account' = <account>` in last 24 hours. If none → unhealthy.
- **Expiration check:** tracked expiration timestamp > 36 hours from now. If <36h → unhealthy ("renewal overdue").

Return value: `{"overall": "healthy"|"unhealthy", "accounts": {"teamgotcher": {...}, "leads": {...}}, "issues": [...]}`.

### Layer 3 — SMS alerting (notification)

If `check_gmail_watch_health` returns unhealthy, or if `setup_gmail_*_watch` fails, send SMS to Jake via the existing Pixel commercial SMS gateway (`f/switchboard/sms_gateway_url`, Tailscale 100.125.176.16:8686).

Dedupe: store last-alert timestamp per issue in `f/switchboard/gmail_watch_last_alert` (JSON). Don't re-alert the same condition within 12 hours.

Message format (short, actionable):
> `[RRG] Gmail watch unhealthy: leads@ silent 8h. Last webhook: 2026-04-16 04:46 UTC. Check Windmill.`

Implementation lives in `check_gmail_watch_health` (for silence/expiration alerts) and inside each `setup_gmail_*_watch` script (for setup-failure alerts — wrap the main body in try/except, SMS on exception, then re-raise so Windmill still logs failure).

### Layer 4 — Fallback polling (redundancy, no change)

`gmail_polling_trigger` stays disabled as "emergency fallback only" per existing memory. No design change. Listed here only to document that push is the only active ingestion path, and monitoring is the safety net.

### Layer 5 — Schedule durability (prevention of recurrence)

Two changes:

1. **Verify `wmill.yaml` includes schedules** — already confirmed: `includeSchedules: true` at line 18.
2. **Post-push verification step in `rrg-sync.sh`** on rrg-server: after any `wmill sync push`, query `SELECT COUNT(*) FROM schedule` and compare to the count of `*.schedule.yaml` files in `windmill/f/`. If mismatch → SMS Jake and log to `~/rrg-server/logs/sync-schedule-mismatch.log`. This would have caught the deleted-schedule state the moment it happened.

## Immediate recovery actions (not part of design, done during implementation)

A. Verify OAuth for leads@ is still valid by triggering `setup_gmail_leads_watch` manually.
B. Push the leads renewal schedule back to the DB via `wmill sync push --skip-variables --skip-secrets --skip-resources` after updating cron to daily.
C. Backlog recovery: Gmail search for lead-source messages in leads@ INBOX since 2026-04-16 04:46 UTC, stage them into `staged_leads` table, trigger `process_staged_leads` per unique email. Follows the catchup procedure in MEMORY.md exactly.

## Components

| Component | Type | Change |
|-----------|------|--------|
| `schedule_gmail_watch_renewal.schedule.yaml` | Schedule | Cron → daily |
| `schedule_gmail_leads_watch_renewal.schedule.yaml` | Schedule | Cron → daily; re-push to DB |
| `setup_gmail_watch.py` | Script | On success, write state to `gmail_watch_state` var. On failure, SMS + re-raise. |
| `setup_gmail_leads_watch.py` | Script | Same. |
| `check_gmail_watch_health.py` | Script | Rewrite: per-account silence + expiration checks, SMS on unhealthy. |
| `gmail_watch_state` | Windmill variable (new) | JSON state per account |
| `gmail_watch_last_alert` | Windmill variable (new) | JSON alert dedupe state |
| `rrg-sync.sh` (rrg-server) | Shell | Add schedule-count verification after push |

## Error handling

- **`setup_gmail_*_watch` transient failure** (Google 5xx, network): Windmill retries are not configured on the schedule; rely on daily cadence — next run is 24h away. With daily cadence, 6 consecutive failures = 6 days = still one day before watch expires. Good enough.
- **`setup_gmail_*_watch` persistent failure** (OAuth revoked): SMS on every run until fixed, deduped to every 12h. Jake must manually re-auth.
- **SMS gateway down:** log error, don't block the health check. Gateway uptime is separately monitored via Tailscale status.
- **Windmill down:** schedules don't run. Out of scope — Windmill is the platform.

## Testing

- Manually trigger `check_gmail_watch_health` before/after renewal to confirm state transitions correctly.
- Temporarily set `gmail_watch_state` to show near-expiry for one account, run health check, verify SMS sent.
- Run `setup_gmail_leads_watch` against current OAuth to verify it still works; confirm new `gmail_watch_state` entry written.
- Backlog recovery: dry-run Gmail search first, confirm candidate list with Jake before staging.

## Non-goals

- Not changing the intake pipeline, draft flow, or review process.
- Not enabling fallback polling as a default — push remains primary.
- Not migrating to service accounts / DWD — leads@ is Workspace (could theoretically) but teamgotcher@ is consumer Gmail (cannot), and DWD doesn't remove the 7-day watch clock anyway.
- Not adding a third ingestion path (IMAP, etc.) — out of scope.

## Success criteria

- Both `schedule_gmail_watch_renewal` and `schedule_gmail_leads_watch_renewal` active in Windmill DB with daily cadence.
- `check_gmail_watch_health` returns per-account status, accurately identifies silence.
- Inducing a fake "silent leads@" state triggers an SMS to Jake within one health-check cycle.
- Post-push schedule-count check in `rrg-sync.sh` runs successfully after each sync.
- Backlog of missed leads (Apr 16 → present) is staged and drafts generated.

## Sources

- [Configure push notifications in Gmail API](https://developers.google.com/workspace/gmail/api/guides/push) — "We recommend calling watch once per day."
- [Method: users.watch](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch) — 7-day expiration contract.
- [OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices) — refresh-token lifetime/revocation semantics.
