# wmill.yaml Configuration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a `wmill.yaml` config file that codifies existing CLI flags as defaults, eliminating the "No wmill.yaml found" warning and making safe sync the default behavior.

**Architecture:** Single YAML file in `windmill/` directory. Encodes the skip/include flags already used in `sync-pull.sh` so that bare `wmill sync push` and `wmill sync pull` are safe by default. No `gitBranches` section (single workspace, single branch — not needed).

**Tech Stack:** Windmill CLI (`windmill-cli` via npx), YAML config

---

### Task 1: Create wmill.yaml

**Files:**
- Create: `windmill/wmill.yaml`

**Step 1: Create the file**

```yaml
# Windmill CLI sync configuration
# Codifies the --skip-* and --include-* flags from sync-pull.sh as defaults.
# A bare `wmill sync push` is now safe (won't wipe resources/variables/secrets).
includes:
  - "f/**"
excludes: []
defaultTs: "bun"
skipVariables: true
skipResources: true
skipSecrets: true
skipResourceTypes: true
skipScripts: false
skipFlows: false
skipApps: false
skipFolders: false
includeSchedules: true
includeTriggers: true
includeUsers: false
includeGroups: false
includeSettings: false
```

**Step 2: Verify locally — no warnings**

Run from rrg-server via SSH:
```bash
ssh andrea@rrg-server "cd ~/rrg-server && git pull && cd windmill && nix-shell -p nodejs_22 --run 'npx windmill-cli@latest sync pull --base-url http://localhost:8000 --workspace rrg --token <TOKEN> --yes' 2>&1 | head -5"
```

Expected: No "No wmill.yaml found" warning. Output starts with "Computing the files to update..."

**Step 3: Verify push is safe**

```bash
ssh andrea@rrg-server "cd ~/rrg-server/windmill && nix-shell -p nodejs_22 --run 'npx windmill-cli@latest sync push --base-url http://localhost:8000 --workspace rrg --token <TOKEN> --yes' 2>&1 | head -5"
```

Expected: No warning. "0 changes to apply" (since flows are already in sync).

**Step 4: Commit**

```bash
git add windmill/wmill.yaml
git commit -m "chore: add wmill.yaml to codify safe sync defaults"
```

---

### Task 2: Simplify sync-pull.sh

**Files:**
- Modify: `windmill/sync-pull.sh`

**Step 1: Remove redundant CLI flags**

The `--skip-variables --skip-secrets --skip-resources --include-schedules --include-triggers` flags are now defaults from `wmill.yaml`. Update `sync-pull.sh` to:

```bash
#!/bin/bash
# Pull latest Windmill flows/scripts to local files for version control
# Runs hourly on cron; changes are auto-committed by rrg-sync.sh (every 5 min)
cd "$(dirname "$0")"
nix-shell -p nodejs_22 --run "npx windmill-cli@latest sync pull \
  --base-url http://localhost:8000 \
  --workspace rrg \
  --token "${WINDMILL_TOKEN:?WINDMILL_TOKEN env var must be set}" \
  --yes" 2>&1
```

**Step 2: Verify sync-pull still works**

```bash
ssh andrea@rrg-server "cd ~/rrg-server && git pull && cd windmill && WINDMILL_TOKEN=<TOKEN> bash sync-pull.sh"
```

Expected: Same output as before — "0 changes to apply", no warnings.

**Step 3: Commit**

```bash
git add windmill/sync-pull.sh
git commit -m "chore: simplify sync-pull.sh — flags now in wmill.yaml"
```
