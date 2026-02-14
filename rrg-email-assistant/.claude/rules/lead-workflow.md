# Lead Processing Workflow (6 Steps)

**Trigger:** New lead notification from LoopNet, Crexi, Realtor.com, or Seller Hub.

---

## Step 0: Information Gathering (Gmail MCP)

**MANDATORY FIRST STEP.** Before doing anything else:

1. Search inbox: `gmail__search_emails(query="from:leads@loopnet.com is:unread", max_results=10)`
2. Read full email: `gmail__read_email(email_id="[ID]")`
3. Extract from email content:
   - **Name** (subject line, sender display, or body)
   - **Email** (from body — this is the SOURCE OF TRUTH for outreach)
   - **Phone** (if available)
   - **Property** (from subject or body)
4. Determine source: LoopNet (`leads@loopnet.com`) vs Crexi (`crexi.com`)
5. Check for realtor indicators (explicit broker language only — investment company domains are NOT indicators)
6. Note message type: automated notification vs personal message

**Save this data — needed throughout workflow:**
- Lead Name, Email, Phone, Source, Realtor indicators, Message type, Property, Email ID

---

## Step 1: HubSpot Lookup

```
hubspot__search_contacts(query="[LEAD EMAIL]")
```

- No results → NEW lead (proceed to Step 2)
- Match found → Check contact record for NDA status, then proceed

---

## Step 2: Create HubSpot Contact (if new)

```
hubspot__create_contact(
  email="[LEAD EMAIL]",
  firstname="[First]",
  lastname="[Last]",
  phone="[Phone if available]",
  lifecyclestage="lead",
  hs_lead_status="Uncontacted"
)
```

**Step 2C (Crexi leads only):** Check Crexi for existing NDA:
1. Go to Crexi → My Listings → Lead Activity
2. Search by name, then email, in both Sale and Lease Leads
3. If "Signed CA" found within last year → skip Step 3, note in HubSpot
4. If no valid CA → proceed to Step 3

---

## Step 3: Send NDA (Inkless MCP)

```
inkless__send_document(
  recipient_name="[Full Name]",
  recipient_email="[Email]",
  document_type="NDA",
  message="Please sign this Non-Disclosure Agreement to access our off-market commercial real estate opportunities."
)
```

---

## Step 4: Send Follow-Up Email (Gmail MCP)

**ALWAYS show draft to Jake before sending.**

```
gmail__send_email(
  to="[LEAD EMAIL]",
  cc="Jasmin@resourcerealtygroupmi.com",
  subject="[Property Address] - Resource Realty Group",
  body="[Use template from email_templates.md]"
)
```

Template customization:
- `[First Name]` → actual name
- `[Property Address]` → actual property
- Source: "LoopNet" or "Crexi" (match actual source)
- NDA source: "Inkless" (not DotLoop)

---

## Step 5: Update HubSpot (MANDATORY)

**5a: Update lead status:**
```
hubspot__update_contact(contact_id="[ID]", properties={"hs_lead_status": "Attempting to Contact"})
```

**5b: Add note:**
```
hubspot__add_note(
  contact_id="[ID]",
  note="[Source] lead - [action/property]\n\nActions taken:\n1. Created HubSpot contact\n2. Sent NDA via Inkless\n3. Sent follow-up email, CC'd Jasmin\n\nNext steps: Wait for NDA signature. Jake to make follow-up call."
)
```

**CRITICAL:** Every email/text MUST be followed by a HubSpot note.

---

## Step 6: Archive Email (Gmail MCP)

```
gmail__modify_labels(email_id="[EMAIL ID from Step 0]", remove_labels=["INBOX"])
```

**Only archive AFTER all steps (1-5) are complete.** Inbox = to-do list.

---

## Existing Contact (Step 2B)

If lead IS in HubSpot: **ASK JAKE** for guidance. This branch is not yet documented.
