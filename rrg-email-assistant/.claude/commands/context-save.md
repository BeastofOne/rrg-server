---
model: claude-sonnet-4-0
---

Save incomplete email workflows for session continuity:

## What to Save (ONLY incomplete work)

**DO save:**
- Leads mid-workflow (started but not finished all 6 steps)
- Extracted lead information (so we don't re-read the email)
- HubSpot lookup results (so we don't re-query)
- Emails drafted but not yet sent (awaiting Jake's approval)
- Errors encountered that blocked completion

**DO NOT save:**
- Successfully completed workflows (HubSpot notes already track this)
- NDAs awaiting signature (DocuSeal sends email notification when signed)
- Historical records or session metrics

## Context Format

Save to `/Users/jacobphillips/Desktop/email-assistant/.claude/context/pending_YYYY-MM-DD.md`:

```markdown
# Pending Email Workflows - [DATE]

## Incomplete Leads (mid-workflow)

### [Lead Name] - [Email]

**Extracted from email (Step 0):**
- Lead Name: [name]
- Lead Email: [email]
- Lead Phone: [if available]
- Source: LoopNet / Crexi
- Property: [address]
- Realtor indicators: Yes (details) / No
- Message type: Automated / Personal message
- Original Email ID: [for archiving later]

**HubSpot status (Step 1):**
- Existing contact: Yes / No
- HubSpot Contact ID: [if exists]
- Existing NDA on file: Yes / No / Unknown

**Progress:**
- Stopped at step: [0-6]
- What's done: [list completed steps]
- What's needed: [remaining steps]
- Reason interrupted: [context fill / Jake ended session / error]

## Drafts Pending Approval

### Email to [Lead Name]
- Subject: [subject]
- Body: [full draft text]
- Status: Awaiting Jake's approval to send

## Errors/Blockers

- [Description of any MCP errors or issues that need attention]
```

## When to Run

Run `/context-save` when:
- Session ending with incomplete workflows
- Context window filling up mid-batch
- Before switching to different task

**Don't bother if:** All workflows completed successfully (nothing pending)

Session notes: $ARGUMENTS
