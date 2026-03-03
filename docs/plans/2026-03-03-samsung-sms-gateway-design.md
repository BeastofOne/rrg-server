# Samsung Tablet Residential SMS Gateway — Design

**Date:** 2026-03-03
**Status:** Approved

## Problem

All lead SMS (commercial and residential) currently routes through a single device — the Pixel 9a. Jake wants to split residential lead SMS onto a dedicated Samsung Galaxy Tab E 8.0 (SM-T377A) so each lead type has its own sender number.

## Device Constraints

- **Model:** Samsung Galaxy Tab E 8.0 (SM-T377A, AT&T variant)
- **Android:** 6.0.1 (Marshmallow), API 23
- **CPU:** ARMv7 32-bit (Cortex-A7), 1.4GB RAM
- **SIM:** Active, SMS-capable, phone (734) 808-1176
- **Tailscale:** NOT compatible (requires Android 8+)
- **Termux:** Requires legacy Android 5/6 build (modern Termux needs Android 7+)

## Architecture

```
Windmill Post-Approval Modules
  │
  ├─ source_type ∈ {crexi, loopnet, bizbuysell}
  │   └── POST → Pixel 9a (100.125.176.16:8686/send-sms, Tailscale)
  │       Phone: (734) 932-0111
  │
  └─ source_type ∈ {realtor_com, seller_hub, social_connect, upnest}
      └── POST → Samsung Tab E (192.168.1.250:8686/send-sms, local WiFi)
          Phone: (734) 808-1176

Health Check (every 15 min):
  check_sms_gateway_health → GET /health on both
  Cross-alerting: if one down, alert Jake via the other
```

## Gateway Contract

Both devices expose identical endpoints:

```
POST /send-sms
  Request:  {"phone": "+1XXXXXXXXXX", "message": "..."}
  Response: {"success": true} or {"success": false, "error": "..."}

GET /health
  Response: {"status": "ok", "uptime_seconds": N, "sms_sent_count": N, "battery": {...}}
```

## Device Hardening

- Timezone: America/Detroit
- Stay awake while charging (Developer Options)
- Doze disabled (re-applied on boot via start-gateway.sh)
- Samsung battery management: Termux exempted
- Mobile data: OFF (SIM retains SMS without data)
- WiFi: Smart Network Switch OFF, always-on during sleep
- Static IP: 192.168.1.250 (set on-device)
- ADB over WiFi: port 5555 for remote management from rrg-server

## Windmill Changes

- New variable: `f/switchboard/sms_gateway_url_residential` = `http://192.168.1.250:8686/send-sms`
- Modified: `lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` — dual-gateway routing
- Modified: `lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py` — dual-gateway routing
- New script: `f/switchboard/check_sms_gateway_health` — cross-alerting health check
- Hardcoded alert URLs (Pixel 9a IP for internal error alerts): unchanged

## Key Risks

1. **Termux signing key mismatch** — Termux, Termux:API, Termux:Boot must share same signing key. Showstopper if no compatible set exists for Android 6.
2. **Legacy Termux unmaintained** — No upstream fixes if something breaks.
3. **No Tailscale** — Tablet only reachable via local WiFi. If WiFi drops, SMS fails silently until health check fires.
4. **Device age** — 10-year-old hardware. Battery degradation may cause issues even when plugged in.
5. **Doze reset on reboot** — Boot script re-disables, but there's a window after boot before Termux:Boot fires.

## Fallback

If Termux won't work on Android 6 (signing key issue, SMS permissions, package repo issues), fall back to MacroDroid — a free Android automation app that supports Android 5+ with HTTP trigger and SMS action.
