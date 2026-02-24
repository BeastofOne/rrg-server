---
model: claude-sonnet-4-0
---

Restore incomplete email workflows from previous session:

## Restoration Process

1. **Check for pending work file:**
   ```
   /Users/jacobphillips/Desktop/email-assistant/.claude/context/pending_*.md
   ```

2. **If file exists, load and use the saved data:**
   - **Extracted lead info** - Don't re-read the original email, use saved name/email/phone/source/property
   - **HubSpot status** - Don't re-query, use saved contact ID and NDA status
   - **Progress checkpoint** - Resume from exact step where it stopped
   - **Pending drafts** - Present saved draft text for approval
   - **Errors** - Retry or flag for Jake

3. **If no file exists:**
   - No pending work from previous sessions
   - Start fresh with new emails

## What to Do After Restore

**For incomplete leads:**
- Resume from the saved step number
- Use the extracted info (don't re-read email)
- Use the HubSpot status (don't re-query unless needed)
- Complete remaining steps

**For pending drafts:**
- Show the saved draft text to Jake
- Send if approved, discard if rejected

**For errors/blockers:**
- Attempt to resolve
- If still blocked, flag for Jake

## Cleanup

After completing pending work:
- Delete the pending file (work is done)
- Or update it if new incomplete work exists

Context to restore: $ARGUMENTS
