# NDA Signing — Chrome Local Network Access Fix

**Date:** 2026-05-18 (revised after research)
**Author:** Jake (with Claude)
**Status:** Design approved in principle, on hold until Alexa is in office

## Problem

NDA signing form at `https://resourcerealtygroupmi.com/forms/sign-nda/` embeds DocuSeal as an iframe pointing at `https://rrg-server.tailc01f9b.ts.net/d/vjL9piBoG3jToA`. Larry reported documents weren't being signed and the front page wasn't auto-filling.

Investigation:
- Last successful submission: Nic Bucca, May 10. Zero submissions started between May 10 and May 18.
- DocuSeal container and WordPress page unchanged since February.
- **Chrome's Local Network Access (LNA) permission prompt** fires when the iframe loads. Triggered because `rrg-server.tailc01f9b.ts.net` resolves to a Tailscale `100.x.x.x` CGNAT IP, which Chrome treats as "local network" when embedded by a public origin.
- Visitors clicking **Block** on the prompt blocks DocuSeal subresource requests → form silently fails.
- Safari and Firefox don't trigger LNA. Issue is Chrome-specific.
- "Worked for months, broke a week ago" matches Chrome's wider LNA rollout in early-to-mid 2026.

The genuine fix per Chromium documentation: "ensure that tunnelled resources aren't resolved to CGNAT addresses from the browser's perspective, by configuring split tunnelling or DNS resolution so that browser-initiated requests go through a reverse proxy with a public address."

## Goal

Visitors using any major browser can sign the NDA on the website without seeing scary permission prompts, while keeping the embedded UX. No changes to existing DNS for `resourcerealtygroupmi.com` that would risk WordPress or Google Workspace email.

## Non-goals

- Moving DocuSeal off rrg-server (data stays put, container stays put).
- Fixing other Tailscale-Funneled services (Windmill, Streamlit) — admin-only, accessed directly, not embedded.
- Changes inside the DocuSeal Rails fork.

## DNS scope (locked)

Jake's constraint (May 18, 2026): no changes to existing DNS at startlogic. Apex `resourcerealtygroupmi.com`, `www`, Google Workspace MX records, SPF, DKIM, and google-site-verification TXTs all remain at startlogic, untouched. The only allowed change at startlogic is **adding** new records for the new `sign.` subdomain — never editing or removing existing records.

This constraint rules out full DNS migration to Cloudflare.

## Architecture

Small VPS as a public-IP reverse proxy in front of DocuSeal. VPS is joined to the Tailscale network so it can reach `rrg-server:3000` over the encrypted overlay; visitors reach the VPS over the public internet.

```
Visitor browser
  │
  ├── (top page) ──► startlogic shared host ── WordPress
  │
  └── (iframe to sign.resourcerealtygroupmi.com)
                │
                ▼
       VPS public IP  (Hetzner CX11, €4/mo)
                │  Caddy with auto-TLS via Let's Encrypt
                │  Tailscale node
                ▼
       rrg-server:3000 (DocuSeal, unchanged)
```

DocuSeal still listens on `rrg-server:3000` exactly as today. No inbound ports opened at the home router. No data migration.

## Why VPS reverse proxy (vs. alternatives)

Considered and ruled out:

- **Cloudflare Tunnel + full DNS migration to Cloudflare.** Free, but explicitly rejected by Jake — touches Google Workspace email DNS, accepts non-zero risk to a critical system for a non-critical fix.
- **Cloudflare Tunnel + subdomain-only zone delegation.** Per Cloudflare's own docs (May 2026): "Subdomain setup is only available for Enterprise accounts." Not viable on free plan.
- **Cloudflare Tunnel + partial setup (CNAME setup).** Per Cloudflare's docs: Business plan or higher only (~$200/mo). Not viable.
- **Cloudflare Quick Tunnel** (free, random `trycloudflare.com` URL). URL rotates on every restart. Useless for production embed. Only useful for one-shot theory verification.
- **Tailscale Funnel CNAME workaround.** Doesn't help — CNAMEs resolve to the same Tailscale IP, browser still sees private IP, LNA prompt persists.
- **Port-forward + Let's Encrypt at home router.** Exposes home IP, requires DDNS for IP changes, raises home-network attack surface, ISP may block port 443. Not gold-standard.
- **`window.open` instead of iframe.** Bypasses LNA but loses the embedded UX. Stated requirement violated.
- **Move DocuSeal to a managed host** (Fly.io, Render). Requires data migration and adds an independent maintenance surface separate from rrg-server. Not justified by current need; possible future direction.
- **Oracle Cloud Always Free ARM VPS.** Genuinely free, generous specs, but account approval is unreliable and Oracle reclaims idle accounts. Acceptable cost-saving alternative but not the gold-standard recommendation.

A small Hetzner VPS (€4–5/mo) gives a permanent public IP without touching any existing DNS apart from one new A record. The same VPS can later become the gateway for other home-hosted services (Windmill admin UI, Streamlit dashboards) without repeating this dance per service.

## Bonus quality improvement (independent of LNA fix)

The WordPress page currently embeds DocuSeal with a hand-rolled `<iframe>` and ad-hoc postMessage handlers. Replace with DocuSeal's official `<docuseal-form>` custom element (loaded from `https://cdn.docuseal.com/js/form.js`). Gives proper event hooks (`init`, `load`, `completed`, `declined`), prefill via `data-values`, optional read-only fields, and built-in completion redirect. Future-proof and matches DocuSeal's documented embed pattern.

## Changes

1. **Provision VPS.** Hetzner CX11 in Ashburn (or closest US region) running Debian 12. Note the assigned IPv4 address.
2. **Join VPS to Tailscale.** Install Tailscale on the VPS, authenticate, name it `rrg-edge` (or similar). Confirm it can reach `rrg-server:3000`.
3. **Install and configure Caddy on VPS.** Single-site Caddyfile reverse-proxying `sign.resourcerealtygroupmi.com` to `http://rrg-server:3000`. Caddy auto-provisions a Let's Encrypt cert once DNS resolves.
4. **Add A record at startlogic.** `sign.resourcerealtygroupmi.com → <VPS public IPv4>`. This is the only DNS change at startlogic. Apex/www/MX/SPF/DKIM untouched.
5. **Wait for DNS propagation + verify TLS.** `curl https://sign.resourcerealtygroupmi.com` should return the DocuSeal home page with a valid cert.
6. **Update DocuSeal `HOST` env** in `deploy/docker-compose.yml` from `rrg-server.tailc01f9b.ts.net` to `sign.resourcerealtygroupmi.com`. Restart docuseal container.
7. **Update WordPress page 72073.** Replace the hand-rolled iframe block with the DocuSeal `<docuseal-form>` embed, pointing at `https://sign.resourcerealtygroupmi.com/d/vjL9piBoG3jToA`. Use the WordPress MCP `wordpress_update_page` tool.
8. **Verify end-to-end** in Chrome incognito on a non-Tailscale network (cellular hotspot to ensure no Tailscale shortcut).

## Rollback

Every step independently reversible:

| Step | Rollback |
|------|----------|
| WordPress page change | Restore from page revision history (28 revisions saved) |
| DocuSeal HOST env | Revert env value, `docker compose up -d` |
| A record at startlogic | Delete the `sign` A record |
| VPS | Destroy the VPS (Hetzner billing prorated) |

## Test plan

1. **Pre-deploy:** after step 5, `curl -I https://sign.resourcerealtygroupmi.com` returns 200 with valid cert. `curl https://sign.resourcerealtygroupmi.com/d/vjL9piBoG3jToA?name=Test&email=test@test.com` returns a 302 redirect to `/s/<slug>` (DocuSeal working).
2. **Post-deploy:** Chrome incognito on a non-Tailscale network (cellular hotspot), open `https://resourcerealtygroupmi.com/forms/sign-nda/`, fill name + email, click Continue.
   - Expected: NO LNA prompt; DocuSeal form loads inline; "Name of Recipient" auto-fills.
3. Complete a test signing. Verify new submission appears in DocuSeal admin and the WiseAgent webhook (`f/docuseal/nda_completed`) processes it correctly.
4. **Safari and Firefox smoke test** — same flow, expect no regression.
5. **Admin access regression check** — confirm `https://rrg-server.tailc01f9b.ts.net` still works for Jake's DocuSeal admin login (we're adding a host, not removing one).
6. **Email/PDF link spot check** — sign a test NDA, verify any post-sign emails/PDFs from DocuSeal contain links using `sign.resourcerealtygroupmi.com` (driven by `HOST` env).

## Doc updates required after deploy

- Root `CLAUDE.md` — DocuSeal now reachable at `sign.resourcerealtygroupmi.com` (public) in addition to Tailscale Funnel (admin).
- `.claude/rules/network.md` — add `rrg-edge` VPS entry alongside other Tailscale machines.
- Memory: VPS reverse proxy architecture and rationale (correct the earlier Cloudflare assumption).

## Open risks

- **VPS provisioning involves Jake.** Account setup at Hetzner (or chosen provider) + payment method, ~10 min one-time.
- **A-record propagation at startlogic.** New `sign.` A record will take minutes to a few hours to propagate. No impact on anything currently working because nothing uses that name today.
- **Caddy auto-TLS requires the domain to resolve first** before Let's Encrypt issues the cert. If propagation is slow, retry the Caddy reload after DNS lookups succeed.
- **DocuSeal session cookies under the new domain.** Existing logged-in admin sessions on the Tailscale URL won't carry to the new domain. Jake re-logs into DocuSeal admin under `sign.resourcerealtygroupmi.com` once. One-time.
- **`HOST` env affects signed-URL generation.** Email/PDF links sent from DocuSeal will use the new hostname after the change — which is what we want for new submissions, but worth confirming no other integration hardcodes the Tailscale hostname.
- **VPS becomes a small new ops surface** — needs OS patches, Tailscale upgrades, Caddy upgrades. Modest. Unattended-upgrades on Debian handles most of it.
