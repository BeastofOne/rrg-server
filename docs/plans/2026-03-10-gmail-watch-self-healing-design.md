# Gmail Watch Self-Healing Design

**Date:** 2026-03-10
**Status:** Approved

## Problem

Gmail watches expire every 7 days (hard Google constraint). Two scheduled renewals (`setup_gmail_watch`, `setup_gmail_leads_watch`) run every 6 days. Both failed:

1. **teamgotcher@** — `RefreshError: Token has been expired or revoked.` The `gmail_oauth` Windmill resource has a revoked refresh token.
2. **leads@** — `Invalid topicName does not match projects/claude-connector-484817/topics/*`. The `gmail_leads_oauth` resource uses `claude-connector` project credentials, but the Pub/Sub topic is in `rrg-gmail-automation`. Google requires these to match.

Result: no email processing for ~5 days. Leads sitting unprocessed in Gmail (not lost — history ID catch-up will recover them).

The deeper problem: the system has no recovery path. If a renewal fails, the watch dies silently and the health check only alerts after 48h, requiring manual intervention.

## Solution

### Part 1: Immediate Fixes (Manual)

1. Re-auth teamgotcher@ via rrg-gmail-automation OAuth flow, update `gmail_oauth` resource with fresh refresh token
2. Re-auth leads@ via rrg-gmail-automation OAuth flow (NOT claude-connector), update `gmail_leads_oauth` resource
3. Run both watch setup scripts to re-register watches and catch up on missed emails

### Part 2: Self-Healing Health Check (Code Change)

Modify `check_gmail_watch_health.py` so when it detects staleness (>48h since last successful webhook):

**Current:** Alert Jake immediately.

**New:**
1. Trigger `setup_gmail_watch` via Windmill API (`POST /api/w/rrg/jobs/run_wait_result/p/f/switchboard/setup_gmail_watch`)
2. Trigger `setup_gmail_leads_watch` via same API
3. If both succeed → return `self_healed`, no alert
4. If either fails → alert Jake with the specific error message from the failed script

This handles the common case (watch expired, token still valid) silently. The uncommon case (token revoked) still alerts Jake because that requires human re-auth.

## Files Changed

- `windmill/f/switchboard/check_gmail_watch_health.py` — add self-healing logic

## Files NOT Changed

- `setup_gmail_watch.py` — no code changes, just needs valid OAuth resource
- `setup_gmail_leads_watch.py` — no code changes, just needs valid OAuth resource
- Schedule YAMLs — no changes needed
