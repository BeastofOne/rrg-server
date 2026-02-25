# Claude.md System Cleanup — Design Doc

> **Date:** 2026-02-25
> **Scope:** rrg-server instruction system + global ~/.claude/ cleanup
> **Goal:** Clean separation of concerns between global, rrg-server, and jake-server domains

---

## Problem

The global `~/.claude/` layer is doing triple duty — holding universal Jake stuff, jake-server/assistant stuff, AND rrg-server stuff. When working in rrg-server, irrelevant to-do list / HubSpot / artifact context gets loaded. Several skills are stale (reference old paths, deprecated services, or wrong trigger mechanisms). No auto-memory is in use.

## Principles

- **Global = truly universal.** Only content that applies to every project Jake works in.
- **Project-level = project-specific.** CRE brokerage infra stays in rrg-server, personal CRE toolkit stays in jake-server.
- **Single source of truth.** No duplicated info across layers.
- **Skills are on-demand context.** Only load what's relevant; stale skills are worse than no skills.
- **Memory persists learnings.** Use auto-memory for cross-session notes about deprecations, gotchas, decisions.

---

## Changes

### 1. Global `~/.claude/CLAUDE.md` — slim to universal

**Keep as-is:**
- Who I Am
- ADHD & Executive Dysfunction
- Communication Style
- Personal Process Rules (date verification)
- Credentials (load `~/.secrets/jake-system.json`)
- Tool Restrictions

**Remove:**
- Financial Reality section (jake-server domain)
- Quality Control Checklist (references HubSpot IDs, `[DEAL-XXX]` tags, artifacts — jake-server domain)

### 2. Global `~/.claude/rules/safety.md` — remove jake-server refs

**Remove lines:**
- "Never fabricate Council voices — must read artifact_6 first"
- "Never add sections to artifacts without Jake's explicit approval"
- "Never cut/delete items from artifacts without Jake's approval"

**Keep lines:**
- No destructive git operations without explicit approval
- Never send "fix" emails for mistakes — stop and ask Jake
- Never use scripts as panic response for token concerns
- Only use incremental edits on files — never rebuild from scratch

### 3. Skills — move 8 to jake-server, delete 3

**Move to `~/Desktop/jake-server/.claude/skills/`:**

| Skill | Reason |
|-------|--------|
| `council` | To-do list / advisory system |
| `deals` | HubSpot deal management |
| `people` | HubSpot contact management |
| `todo-updates` | To-do list workflow |
| `parking-lot` | Deferred task management |
| `hubspot` | HubSpot CRM operations |
| `email` | CRE outreach templates (references old jake-server paths) |
| `jake-system` + 3 reference docs | Old infrastructure snapshot (pre-NixOS wipe) |

**Delete (outdated, duplicated by `docs/LEAD_INTAKE_PIPELINE.md` or no longer accurate):**

| Skill | Reason |
|-------|--------|
| `windmill-lead-intake` | Stale (says polling, actual system uses Pub/Sub push) |
| `leads` | Stale (same issues, condensed duplicate of pipeline docs) |
| `nda` | Stale (references jake-server hostname, n8n, wrong DocuSeal URL) |

**Remaining global skills after cleanup:**
- `nix` — universal (used in rrg-server and jake-server builds)
- `dates` — universal (date verification rules)

### 4. Delete `rrg-server/rrg-claude-endpoint/CLAUDE.md`

78 lines documenting a DEPRECATED service. The root CLAUDE.md already notes it as deprecated in the directory tree. Delete the file entirely.

### 5. Delete `rrg-server/.claude/rules/email.md`

Fully redundant or outdated:
- Gmail integration section — outdated (early automation attempts, ~1 month old)
- Mandatory rules — outdated (reply vs new email rules from early attempts, CC Jasmin no longer applies)
- Jake's signature — already in global `~/.claude/CLAUDE.md` under Communication Style
- "Never send fix emails" — already in global `~/.claude/rules/safety.md`

Delete the entire file.

### 6. Initialize auto-memory for rrg-server

Create `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md` with:
- Note that `rrg-claude-endpoint` is deprecated (CLAUDE.md deleted Feb 2026)
- Note that jake-server skills were moved out of global (Feb 2026)
- Note that lead intake / NDA skills were deleted as stale — recreate from current docs if needed

### 8. Migrate orphaned memory to correct path

Memory files are stranded at the old Desktop path:
- **Old (orphaned):** `~/.claude/projects/-Users-jacobphillips-Desktop-rrg-server/memory/MEMORY.md` (123 lines)
- **Current (empty):** `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md`

The old memory has valuable notes (deleted systems, renames, Gmail split inbox, Windmill MCP, Docker gotchas, deploy keys, sync setup) that aren't loading in current sessions.

**Action:** Migrate the old memory content into the current path. During migration, audit each section:
- Remove anything that's now covered by project docs or CLAUDE.md (no duplication)
- Remove jake-server-specific content (Pixel 9a hardware specs belong in jake-server)
- Keep rrg-server operational notes, gotchas, and infrastructure decisions

Also migrate the home-directory memory (`-Users-jacobphillips/memory/`) — the infrastructure.md has rrg-server content (Windmill worker Nix gotchas, Docker compose project names) that belongs in the rrg-server memory.

After migration, delete the orphaned old-path memory directory.

### 9. Create jake-server skills directory

Create `~/Desktop/jake-server/.claude/skills/` and move the 8 skills there. This parks them cleanly so they're out of global scope but preserved for when jake-server gets rebuilt.

---

## What we're NOT changing

- `rrg-server/CLAUDE.md` (90 lines, accurate, reasonable size)
- `rrg-server/.claude/rules/` (network.md, doc-sync.md — current, right size)
- Child project CLAUDE.md files (rrg-pnl, rrg-brochure, rrg-router, rrg-email-assistant) — not audited this pass
- `~/.claude/rules/verification.md` — universal, no changes needed
- `~/.claude/settings.local.json` — accumulated Bash permissions, cosmetic clutter, separate cleanup
- Superpowers plugin skills (14 skills in plugin cache, managed by plugin)

---

## Context window impact

**Before:** Every rrg-server session loads ~1,200 lines of irrelevant jake-server skill content when keywords trigger, plus stale info in global CLAUDE.md and safety rules.

**After:** Global loads are ~30 lines (slimmed CLAUDE.md) + 22 lines (rules). Only `nix` and `dates` skills remain to fire from global scope. Project-level context is accurate and rrg-server-specific.
