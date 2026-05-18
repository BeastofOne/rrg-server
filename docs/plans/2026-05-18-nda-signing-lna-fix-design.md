# NDA Signing — Chrome Local Network Access Fix

**Date:** 2026-05-18
**Author:** Jake (with Claude)
**Status:** Design approved, ready for implementation plan

## Problem

The NDA signing form at `https://resourcerealtygroupmi.com/forms/sign-nda/` embeds DocuSeal as an iframe pointing at `https://rrg-server.tailc01f9b.ts.net/d/vjL9piBoG3jToA`. Larry reported that documents weren't getting signed and the front page wasn't auto-filling.

Investigation showed:
- Last successful submission was May 10 (Nic Bucca). Zero submissions started between May 10 and May 18 — visitors weren't even reaching DocuSeal.
- The DocuSeal container and WordPress page hadn't changed since February.
- Chrome shows a **Local Network Access (LNA) permission prompt** ("resourcerealtygroupmi.com wants to access other devices on your local network") when the iframe loads. The prompt is triggered because `rrg-server.tailc01f9b.ts.net` resolves to a Tailscale `100.x.x.x` CGNAT IP, which Chrome treats as a local-network target embedded by a public origin.
- When a visitor clicks **Block** (the natural reaction to an unexpected scary popup), DocuSeal's subresource requests inside the iframe get blocked. The form appears broken: no auto-fill, no signing, no submission record.
- Safari and Firefox don't trigger LNA and work fine. The issue is Chrome-specific.
- The "worked for months, broke a week ago" pattern matches Chrome's wider rollout of LNA prompts in early-to-mid 2026.

## Goal

Visitors using any major browser can sign the NDA on the website without seeing scary permission prompts, while keeping the embedded UX (form feels like part of the website, not a redirect).

## Non-goals

- Moving DocuSeal off rrg-server (data stays put, container stays put).
- Fixing other Tailscale-Funneled services (Windmill, Streamlit) — they're admin-only and accessed directly, not embedded.
- Changes inside the DocuSeal Rails fork (no rebuild required).

## Architecture

Expose DocuSeal at a new public-IP-fronted hostname `sign.resourcerealtygroupmi.com` via Cloudflare Tunnel. From the browser's perspective the iframe target resolves to Cloudflare's public anycast IPs, so Chrome no longer treats it as local-network and skips the LNA prompt.

```
Visitor browser
  │
  ├── (top page) ──► startlogic shared host ── WordPress
  │
  └── (iframe)   ──► Cloudflare edge (public IP)
                      └── cloudflared tunnel ──► rrg-server:3000 (DocuSeal)
```

DocuSeal still listens on `rrg-server:3000` exactly as today. The cloudflared container runs alongside the docuseal container on rrg-server and establishes an outbound tunnel to Cloudflare — no inbound ports opened at the home router.

## Why Cloudflare Tunnel

Considered and ruled out:

- **Tailscale Funnel CNAME** — doesn't help. CNAMEs resolve to the same Tailscale IP, browser still sees a private IP, LNA prompt persists.
- **VPS reverse proxy** — works but adds ~$60/yr and an extra moving part. Not necessary when Cloudflare Tunnel is free.
- **Port-forward + Let's Encrypt at home router** — exposes home IP, requires dynamic DNS, raises home-network attack surface, ISP may block port 443.
- **`window.open` instead of iframe** — bypasses LNA but loses the embedded UX, which is a stated requirement.
- **Managed DocuSeal host (Fly/Render)** — would require data migration and ongoing cost. Out of scope.

Cloudflare Tunnel is free, requires no inbound ports, no data migration, and DocuSeal stays exactly where it is.

## Changes

1. **Cloudflare account setup.** Create a free Cloudflare account, add `resourcerealtygroupmi.com` as a zone. Mirror all existing DNS records from startlogic (WordPress A records, MX records, any TXT/SPF, DKIM, etc.) so that nothing breaks when nameservers switch.
2. **Nameserver switch at startlogic.** Change NS records from `ns1/ns2.startlogic.com` → the Cloudflare-assigned nameservers. Because all records are mirrored first, this is a no-downtime change. Propagation is a few hours.
3. **cloudflared container on rrg-server.** Add a `cloudflared` service to `deploy/docker-compose.yml` (or a new `deploy/cloudflared-docker-compose.yml`) running `cloudflared tunnel run` with a named tunnel. Tunnel configuration routes hostname `sign.resourcerealtygroupmi.com` to `http://docuseal:3000`.
4. **Cloudflare DNS record for the tunnel.** Create a CNAME `sign` → `<tunnel-id>.cfargotunnel.com` (proxied/orange-cloud), wired to the named tunnel.
5. **DocuSeal `HOST` env update.** Edit `deploy/docker-compose.yml` (or wherever the docuseal service is defined) to set `HOST=sign.resourcerealtygroupmi.com`. Restart the docuseal container.
6. **WordPress page 72073 update.** Edit the inline `<script>` on `/forms/sign-nda/` so `docusealUrl` builds from `https://sign.resourcerealtygroupmi.com/d/vjL9piBoG3jToA?...` instead of `https://rrg-server.tailc01f9b.ts.net/d/...`. Single line change. Use the WordPress MCP `wordpress_update_page` tool.

## Rollback

Every step is independently reversible:

| Step | Rollback |
|------|----------|
| WordPress page change | Restore from page revision history (28 revisions saved) |
| DocuSeal HOST env | Revert env value and `docker compose up -d` |
| cloudflared container | `docker compose stop cloudflared` and remove from compose file |
| Cloudflare DNS record | Delete CNAME in dashboard |
| Nameserver switch | Revert NS records at startlogic back to `ns1/ns2.startlogic.com` |
| Cloudflare zone | Delete zone (or leave dormant) |

## Test plan

1. **Pre-deploy:** verify `https://sign.resourcerealtygroupmi.com` returns DocuSeal home page after step 4 (no website changes yet). Confirms tunnel works.
2. **Post-deploy:** in **Chrome incognito on a non-Tailscale network** (cellular hotspot if needed to verify it's not Tailscale-mediated), open `https://resourcerealtygroupmi.com/forms/sign-nda/`, fill name + email, click Continue.
   - Expected: no LNA prompt; DocuSeal form loads in iframe; "Name of Recipient" auto-fills.
3. Complete a test signing. Verify a new submission appears in DocuSeal admin and the WiseAgent webhook (`f/docuseal/nda_completed`) processes it correctly.
4. **Safari and Firefox smoke test** — same flow, expect no regression (these browsers were already working).
5. **Admin access regression check** — confirm `https://rrg-server.tailc01f9b.ts.net` still works for Jake's DocuSeal admin login (it should; we're adding a new host, not removing the old one).

## Doc updates required after deploy

- Root `CLAUDE.md` — DocuSeal now publicly accessible at `sign.resourcerealtygroupmi.com` in addition to Tailscale Funnel.
- `.claude/rules/network.md` — add Cloudflare Tunnel entry alongside other ports/services.
- Memory: note that DNS is now managed at Cloudflare (was startlogic).

## Open risks

- **Cloudflare account doesn't yet exist.** Jake will need to create one and confirm email. Trivial but a step that requires Jake's hands.
- **Startlogic NS change may take time to propagate.** Plan to do this step during a window where 2–4 hours of DNS-in-flight is acceptable. WordPress will keep working throughout (records mirrored), but it's worth confirming.
- **DocuSeal session cookies under the new domain.** Existing logged-in admin sessions on the Tailscale URL won't carry to the new domain. Jake will need to re-log into DocuSeal admin under `sign.resourcerealtygroupmi.com` once. One-time only.
- **DocuSeal `HOST` env affects signed-URL generation.** After the change, DocuSeal will generate links pointing at the new hostname. Email/PDF links sent from DocuSeal will use the new host, which is what we want, but worth confirming no hardcoded references elsewhere assume the Tailscale hostname.
