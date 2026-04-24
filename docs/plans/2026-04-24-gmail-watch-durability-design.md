# Gmail Watch Durability — Design

**Date:** 2026-04-24
**Status:** Approved for implementation (revised after code review)
**Context:** 9-day silent lead-intake outage (April 16 → April 24) caused by expired Gmail watch on leads@resourcerealtygroupmi.com with no renewal and a health check that couldn't detect per-account silence.

## Problem

Three token/watch-related production incidents in ~7 weeks:

| Date | Failure | Class |
|------|---------|-------|
| Mar 7 | OAuth refresh token died | Testing-mode 7-day token expiry |
| Mar 17 | OAuth refresh token died | Testing-mode 7-day token expiry |
| Apr 16 → Apr 24 | leads@ watch expired, 9 days silent | Watch expiry + missing renewal schedule + blind health check |

The OAuth token class was resolved Mar 23 by moving the GCP project (`rrg-gmail-automation`) to Production.

## Root cause (April 16)

1. **Renewal schedule for leads@ was deleted from the Windmill DB.** Local yaml (`schedule_gmail_leads_watch_renewal.schedule.yaml`) has `enabled: true`, but a DB query returns zero rows for any leads-related schedule. Likely a prior `wmill sync push` wipe (Feb 25/26/28) removed it, and no later push restored it.
2. **Health check is global, not per-account.** `check_gmail_watch_health.check_webhook_staleness` queries for ANY successful `gmail_pubsub_webhook` run, not filtered by `result.account`. teamgotcher@'s heavy traffic masked leads@'s total silence for 9 days.

## What already works (don't rebuild)

`check_gmail_watch_health.py` already has most of the durability infrastructure:

- `attempt_self_heal` (lines 114-166): queues async renewal jobs for both `setup_gmail_watch` and `setup_gmail_leads_watch` via Windmill API.
- `send_alert` (lines 184-193): SMSs Jake's hardcoded number (`+17348960518`) via the Pixel gateway (`f/switchboard/sms_gateway_url`).
- `WATCH_SCRIPTS` (lines 24-27): maps the two setup scripts to their accounts.
- Runs daily at 10 AM ET per `gmail_watch_health_daily.schedule.yaml`.

The only bug: `check_webhook_staleness` doesn't filter by account. Everything else downstream (self-heal, SMS) is wired correctly; it just never fires because global staleness always returns ~0 hours.

## Design (minimal diff)

### Change 1 — Daily renewal cadence

Update both schedule yamls from every-6-days to daily (Google's explicit recommendation):

- `schedule_gmail_watch_renewal.schedule.yaml`: `0 0 9 */6 * *` → `0 0 9 * * *`
- `schedule_gmail_leads_watch_renewal.schedule.yaml`: `0 0 9 */6 * *` → `0 0 9 * * *`

Daily renewal gives a 6-day buffer against transient failures before a miss would actually cause a watch expiration. `watch()` is idempotent.

### Change 2 — Per-account staleness check

Modify `check_gmail_watch_health.py`:

- `check_webhook_staleness` takes an `account` parameter and adds `extra_args={"account": account}` or uses a DB-level filter on `result->>'account'`. Windmill's `/jobs/list` endpoint does not filter on result-body fields directly, so the cleanest path is to query Postgres directly via the existing Windmill DB resource pattern (see `process_staged_leads.py` for the pattern), OR accept some client-side filtering: fetch the last N jobs and filter by `account` in Python.
- `main()` loops over `WATCH_SCRIPTS` (the existing constant), calling staleness check per account.
- Alert message identifies which account is stale: `"leads@ webhook stale (Xh)..."`.
- `attempt_self_heal` is already per-account-capable (iterates WATCH_SCRIPTS); no change needed.

Threshold stays at 48 hours (matches current code). With daily renewal, a 48-hour silence means renewal ran but Pub/Sub delivery broke — genuine issue.

### Change 3 — Schedule existence probe in the health check

Add a check inside `check_gmail_watch_health.main()`: for each of the two renewal schedule paths, query `GET /api/w/rrg/schedules/get/<path>` and verify `enabled: true`. If either schedule is missing or disabled, SMS Jake and return unhealthy.

This catches the April 16 root cause directly: the schedule was deleted from DB, no renewal ran, watch expired. Probing inside the health check works regardless of HOW the schedule got wiped (sync push, DB restore, manual delete). Does not require changes to `rrg-sync.sh`.

### Change 4 — Restore leads@ schedule

Push `schedule_gmail_leads_watch_renewal.schedule.yaml` back to the DB via `wmill sync push --skip-variables --skip-secrets --skip-resources`. Verify it appears in `SELECT * FROM schedule WHERE path LIKE '%leads%'`.

## Failure modes handled

| Mode | Handler |
|------|---------|
| Watch expires (current cause) | Daily renewal + per-account silence alert |
| Renewal schedule deleted from DB | Schedule existence probe in health check |
| OAuth token revoked on one account | Daily renewal fails → silence builds → per-account alert within 48h. One SMS/day max until resolved — acceptable. |
| Pub/Sub topic/subscription breaks | `watch()` returns success but no notifications. Caught by per-account silence check within 48h. |
| Windmill DB restored from older backup | Schedule probe detects missing schedules, alerts immediately. |
| Pixel SMS gateway down | `send_alert` fails silently (existing behavior); alert gets logged but not sent. Separate issue — gateway is monitored via Tailscale. |
| Health check itself fails | Existing try/except at lines 34-41 catches and sends alert. |

## Non-goals / explicit YAGNI cuts

- **No new Windmill variables.** Earlier draft proposed `gmail_watch_state` (expiration tracking) and `gmail_watch_last_alert` (dedupe). Both unnecessary: daily renewal makes expiration always ~7 days out, and daily health-check cadence caps SMS at 1/day/account.
- **No changes to `rrg-sync.sh`.** The schedule existence probe is self-contained in Windmill; DB restores bypass sync-push anyway.
- **No try/except wrap on setup scripts.** Silence detection already catches any persistent renewal failure.
- **No fallback polling enabled.** `gmail_polling_trigger` remains disabled as "emergency fallback only" per MEMORY.md.
- **No migration to service accounts / DWD.** teamgotcher@ is consumer Gmail (can't use DWD), and DWD doesn't remove the 7-day watch clock anyway.
- **No change to the lead intake pipeline, draft flow, review process, or any business logic.**

## Components

| File | Change |
|------|--------|
| `windmill/f/switchboard/schedule_gmail_watch_renewal.schedule.yaml` | Cron → daily |
| `windmill/f/switchboard/schedule_gmail_leads_watch_renewal.schedule.yaml` | Cron → daily; push to DB |
| `windmill/f/switchboard/check_gmail_watch_health.py` | Per-account staleness loop + schedule existence probe |

## Immediate recovery (separate from design changes)

A. Trigger `setup_gmail_leads_watch` via Windmill API to re-establish the expired watch.
B. Confirm new webhook runs start appearing with `result.account = "leads"`.
C. Backlog recovery: Gmail search for lead-source messages in leads@ INBOX since 2026-04-16 04:46 UTC, stage into `staged_leads`, trigger `process_staged_leads` per unique email. Follows MEMORY.md catchup procedure.

## Testing

- Manually trigger `check_gmail_watch_health` after implementation — verify it reports per-account status.
- Temporarily disable `schedule_gmail_leads_watch_renewal` in Windmill UI, run the health check, verify SMS fires and identifies the missing schedule. Re-enable immediately after test.
- Trigger `setup_gmail_leads_watch` manually, confirm response shows new expiration ~7 days out, confirm webhook fires within 30 minutes.
- Backlog: dry-run Gmail search first, print candidate list, confirm with Jake before staging.

## Success criteria

- Both renewal schedules exist in Windmill DB with daily cadence.
- `check_gmail_watch_health` reports per-account status and triggers SMS on inducible failure (missing schedule, stale webhook).
- Expired leads@ watch re-established; webhook firing for leads@ again.
- Backlog leads (Apr 16 → present) staged and drafts generated for Jake's review in Gmail.

## Sources

- [Configure push notifications in Gmail API](https://developers.google.com/workspace/gmail/api/guides/push) — "We recommend calling watch once per day."
- [Method: users.watch](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch) — 7-day expiration contract.
- [OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices) — refresh-token lifetime/revocation semantics.

## Revision history

- **v1 (initial)**: 5-layer architecture with new variables and rrg-sync.sh check.
- **v2 (current)**: Post-code-review. Cut YAGNI: Layer 3 already exists in `check_gmail_watch_health.py`; `gmail_watch_state`/`gmail_watch_last_alert` variables eliminated; Layer 5 (rrg-sync.sh check) replaced with in-Windmill schedule existence probe; framing corrected to describe a minimal diff rather than rewriting a working file.
