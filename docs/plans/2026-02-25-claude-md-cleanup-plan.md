# Claude.md System Cleanup — Implementation Plan

> **For Claude:** This is a file-reorganization task, not a feature build. No TDD cycle — just careful file moves, edits, and deletions with verification after each step.

**Goal:** Clean separation of concerns between global, rrg-server, and jake-server instruction files.

**Architecture:** Remove jake-server content from global scope, delete stale skills, migrate orphaned memory, clean leaked secrets from permissions files.

**Design doc:** `docs/plans/2026-02-25-claude-md-cleanup-design.md`

---

### Task 1: Slim global CLAUDE.md

**Files:**
- Modify: `~/.claude/CLAUDE.md`

**Step 1: Remove Financial Reality section**

Remove these lines:
```
## Financial Reality
- Cash reserves: ~$3,700
- Runway: 2-3 months (runs out ~March 31, 2026)
- Need: $4K-8K in NEW closed commissions by end of March
- → SURVIVAL SPEED REQUIRED
```

**Step 2: Remove Quality Control Checklist**

Remove these lines:
```
## Quality Control Checklist
Before presenting ANY output, verify:
- [ ] Did I load the relevant skill file(s)?
- [ ] Did I run `date` before stating day-of-week?
- [ ] Did I use [DEAL-XXX] and [P-XXX] tags correctly?
- [ ] Did I look up HubSpot IDs (not guess)?
- [ ] Did I preserve Jake's exact words in context?
- [ ] Did I keep artifact_1 context under 10 lines?
- [ ] Did I update BOTH local artifact AND HubSpot?
- [ ] Did I verify email addresses before sending?
- [ ] Did I complete ALL steps (not stop mid-workflow)?
```

**Step 3: Verify**

Read `~/.claude/CLAUDE.md` — confirm only these sections remain: Who I Am, ADHD, Communication Style, Personal Process Rules, Credentials, Tool Restrictions.

---

### Task 2: Clean global safety rules

**Files:**
- Modify: `~/.claude/rules/safety.md`

**Step 1: Remove artifact-related lines**

Remove these three lines:
- `- Never fabricate Council voices — must read artifact_6 first`
- `- Never add sections to artifacts without Jake's explicit approval`
- `- Never cut/delete items from artifacts without Jake's approval`

**Step 2: Verify**

Read `~/.claude/rules/safety.md` — confirm 4 remaining rules: no destructive git, no fix emails, no panic scripts, incremental edits only.

---

### Task 3: Delete stale skills

**Files:**
- Delete: `~/.claude/skills/windmill-lead-intake/SKILL.md`
- Delete: `~/.claude/skills/leads/SKILL.md`
- Delete: `~/.claude/skills/nda/SKILL.md`
- Delete: directories `~/.claude/skills/windmill-lead-intake/`, `~/.claude/skills/leads/`, `~/.claude/skills/nda/`

**Step 1: Delete the three skill directories**

```bash
rm -rf ~/.claude/skills/windmill-lead-intake
rm -rf ~/.claude/skills/leads
rm -rf ~/.claude/skills/nda
```

**Step 2: Verify**

```bash
ls ~/.claude/skills/
```

Expected: `council/`, `dates/`, `deals/`, `email/`, `hubspot/`, `jake-system/`, `nix/`, `parking-lot/`, `people/`, `todo-updates/` (10 remaining — 8 to move, 2 staying)

---

### Task 4: Create jake-server skills directory and move 8 skills

**Files:**
- Create: `~/Desktop/jake-server/.claude/skills/`
- Move 8 skill directories from `~/.claude/skills/` to `~/Desktop/jake-server/.claude/skills/`

**Step 1: Create the target directory**

```bash
mkdir -p ~/Desktop/jake-server/.claude/skills
```

**Step 2: Move the 8 skills**

```bash
mv ~/.claude/skills/council ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/deals ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/people ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/todo-updates ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/parking-lot ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/hubspot ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/email ~/Desktop/jake-server/.claude/skills/
mv ~/.claude/skills/jake-system ~/Desktop/jake-server/.claude/skills/
```

**Step 3: Verify**

```bash
ls ~/.claude/skills/
```

Expected: only `dates/` and `nix/`

```bash
ls ~/Desktop/jake-server/.claude/skills/
```

Expected: `council/`, `deals/`, `email/`, `hubspot/`, `jake-system/`, `parking-lot/`, `people/`, `todo-updates/`

---

### Task 5: Delete stale project files

**Files:**
- Delete: `~/rrg-server/rrg-claude-endpoint/CLAUDE.md`
- Delete: `~/rrg-server/.claude/rules/email.md`

**Step 1: Delete deprecated endpoint docs**

```bash
rm ~/rrg-server/rrg-claude-endpoint/CLAUDE.md
```

**Step 2: Delete redundant email rules**

```bash
rm ~/rrg-server/.claude/rules/email.md
```

**Step 3: Verify**

```bash
ls ~/rrg-server/rrg-claude-endpoint/CLAUDE.md 2>/dev/null && echo "STILL EXISTS" || echo "DELETED"
ls ~/rrg-server/.claude/rules/email.md 2>/dev/null && echo "STILL EXISTS" || echo "DELETED"
```

Expected: both say "DELETED"

---

### Task 6: Migrate orphaned memory to correct path

**Files:**
- Create: `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md`
- Read from: `~/.claude/projects/-Users-jacobphillips-Desktop-rrg-server/memory/MEMORY.md`
- Read from: `~/.claude/projects/-Users-jacobphillips/memory/infrastructure.md`
- Delete after: both old memory directories

**Step 1: Create the new MEMORY.md**

Write the migrated, audited memory file to `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md`.

Content should include (from old memory, keeping only rrg-server-relevant, non-redundant items):

```markdown
# RRG Server Memory

## Quick Facts (details in docs/)
- Lead intake trigger: Pub/Sub push (~2-5s), NOT polling. Polling is deprecated.
- Split inbox: leads@ receives notifications, teamgotcher@ sends drafts/receives replies
- Lead sources: Crexi, LoopNet, BizBuySell, Realtor.com, Seller Hub, Social Connect
- Resume mechanism: thread_id matching (Gmail strips X-headers)
- CRM for lead intake: WiseAgent (not HubSpot)
- Approval UI: Gmail (send draft = approve, delete draft = reject)
- Templates: Larry signs commercial (Crexi/LoopNet/BizBuySell), Jake signs residential/seller

## Repo & Sync
- Real path: ~/rrg-server, symlink at ~/Desktop/rrg-server (macOS blocks background process access to ~/Desktop/)
- Auto-sync on MacBook: launchd agent (~/Library/LaunchAgents/com.rrg.sync.plist), NOT cron. Runs every 5 min.
- Auto-sync on rrg-server: cron every 5 min (rrg-sync.sh). Windmill flows sync hourly via windmill/sync-pull.sh
- GitHub is single source of truth
- Before committing, run `wmill sync pull` to export latest Windmill flows

## DocuSeal
- Separate fork repo: BeastofOne/docuseal (rrg branch), at /home/andrea/docuseal/
- gemset.nix quirks: bundix generates wrong hashes for platform-specific gems (ffi, nokogiri, sqlite3) — must manually fix with nix-prefetch-url
- nokogiri needs mini_portile2 added to gemset.nix (not in Gemfile.lock because platform-specific)
- SSH key: ~/.ssh/id_docuseal with alias github.com-docuseal

## SSH & Deploy Keys
- rrg-server SSH keys: ~/.ssh/id_ed25519 (alias github.com-beastofone), ~/.ssh/id_docuseal (docuseal fork)
- GitHub deploy keys: rrg-server repo + docuseal fork both have write-access deploy keys from rrg-server
- Tailscale SSH: ssh andrea@rrg-server (no keys needed)

## Windmill MCP
- Custom local MCP at rrg-server/windmill-mcp/ replaces built-in endpoint (built-in returns 70K-400K+ tokens — never use it)
- Configured in ~/.claude.json user-level MCP config
- queryDocumentation deliberately skipped (uses third-party Inkeep) — use WebSearch/WebFetch instead
- Dynamic tools (per-flow/per-script) registered at startup; new scripts need MCP restart

## Nix Build Gotchas
- Windmill Worker (windmill-worker:latest): Stock Docker image + Claude CLI layered via Nix buildLayeredImage
- CRITICAL: Do NOT put pkgs.claude-code directly in `contents` — creates root-level /bin, /lib symlinks that mask base image directories (breaks dynamic linker). Only include claudeLayer (runCommand that creates /usr/local/bin/claude symlink).
- Stock image CMD (windmill) is NOT preserved by buildLayeredImage — must specify command: windmill in docker-compose

## Docker Compose
- Windmill stack: project name = windmill (windmill-windmill_server-1, windmill-windmill_worker-1, windmill-db-1)
- RRG containers: explicit container_name (rrg-router, rrg-pnl, rrg-brochure)
- Windmill commands: docker compose -p windmill -f windmill-docker-compose.yml ...
- RRG commands: docker compose up -d (from deploy/ dir)

## Claude CLI Token
- All server containers use teamgotcher@gmail.com Max 5x setup-token (~1yr expiry)
- Token stored in ~/rrg-server/deploy/.env as CLAUDE_CODE_OAUTH_TOKEN
- Also in ~/.secrets/jake-system.json → anthropic.claude_code_oauth_token

## Doc-Sync Hook
- .claude/hooks/doc-sync-check.sh blocks stopping if source files changed without doc updates
- Actively verify this hook is working during sessions

## Deprecated (Feb 2026)
- rrg-claude-endpoint: DEPRECATED — CLAUDE.md deleted, service replaced by Claude CLI in containers directly
- pm2 claude-endpoint process on MacBook: DELETED
- f/switchboard/claude_endpoint_url variable: DELETED
- gmail_polling_trigger: schedule disabled, kept as emergency fallback only

## Cleanup History
- Feb 25, 2026: Moved 8 jake-server skills out of global (council, deals, people, todo-updates, parking-lot, hubspot, email, jake-system)
- Feb 25, 2026: Deleted 3 stale skills (windmill-lead-intake, leads, nda) — recreate from current docs if needed
- Feb 25, 2026: Slimmed global CLAUDE.md (removed Financial Reality, Quality Control Checklist)
```

**Step 2: Move Pixel 9a hardware specs to jake-server memory**

Create `~/Desktop/jake-server/.claude/projects/-Users-jacobphillips-Desktop-jake-server/memory/MEMORY.md` (or just save inline in the jake-server directory for now) with the Pixel 9a hardware specs section from the old memory.

**Step 3: Delete orphaned memory directories**

```bash
rm -rf ~/.claude/projects/-Users-jacobphillips-Desktop-rrg-server/memory
rm -rf ~/.claude/projects/-Users-jacobphillips/memory
```

**Step 4: Verify**

Read `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/MEMORY.md` — confirm it exists and is under 200 lines.

---

### Task 7: Clean project settings.local.json (secrets + bloat)

**Files:**
- Modify: `~/rrg-server/.claude/settings.local.json`

**Step 1: Review current file and identify keepers**

Read the full file. Identify which permissions are:
- **Keep:** Windmill MCP tools, ssh, git operations, common utilities (curl, python3, ls, etc.), WebSearch, WebFetch for commonly used domains
- **Remove:** Anything with hardcoded tokens/secrets, one-time debugging commands, deprecated service commands, old Desktop paths, adb commands, MCP test commands

**Step 2: Write clean replacement**

Replace with a clean file containing only the actively needed permissions. Group by category for readability.

**Step 3: Verify**

```bash
grep -c "muswxrd\|sk-ant\|Bearer\|OAuth" ~/rrg-server/.claude/settings.local.json
```

Expected: 0

---

### Task 8: Clean global settings.local.json (bloat)

**Files:**
- Modify: `~/.claude/settings.local.json`

**Step 1: Review and identify keepers**

Same approach as Task 7 — keep actively needed permissions, remove one-time commands, old paths, leaked secrets.

**Step 2: Write clean replacement**

**Step 3: Verify**

---

### Task 9: Commit cleanup

**Step 1: Stage rrg-server changes**

```bash
git add rrg-claude-endpoint/CLAUDE.md  # deletion
git add .claude/rules/email.md          # deletion
git add .claude/settings.local.json     # cleaned
git add docs/plans/                     # design doc + plan
```

Note: Global files (~/.claude/) are not in the rrg-server repo and don't need committing.

**Step 2: Commit**

```bash
git commit -m "chore: clean up Claude instruction system

- Delete deprecated rrg-claude-endpoint/CLAUDE.md
- Delete redundant .claude/rules/email.md
- Remove leaked secrets from .claude/settings.local.json
- Add design doc and implementation plan"
```

**Step 3: Verify**

```bash
git status
git log --oneline -1
```

---

## Execution Order

Tasks 1-2 (global edits) and Tasks 3-4 (skill moves) are independent — can run in parallel.
Task 5 (project file deletes) is independent.
Task 6 (memory migration) depends on Tasks 3-4 being done (so cleanup history is accurate).
Task 7-8 (settings cleanup) are independent of each other but should be done carefully.
Task 9 (commit) must be last.
