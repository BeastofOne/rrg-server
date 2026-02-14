---
name: outreach
description: Crexi bulk outreach workflow for CRE leads tracked in Google Sheets. Use when doing bulk email/SMS outreach to Crexi leads. Triggers on "outreach", "bulk email", "crexi leads", "spreadsheet outreach".
---

# Crexi Lead Outreach Workflow

Bulk outreach to leads who viewed properties on Crexi. Leads tracked in Google Sheet, organized by property type.

## Google Sheet
- **Sheet ID:** `1iD6ablBi9e2X8bFT6-C-VRfr8q27-mjlkagOLmqwcQg`
- **Sheet Name:** `Crexi Leads`
- **Columns:** Name, Phone, Email, Property, Action, Date, HubSpot Status, CA Status

## Workflow Steps

### Step 1: Read spreadsheet
```
mcp__googlesheets__read_range(spreadsheet_id, range)
```

### Step 2: Filter by property type
- Group contacts by "Property" column
- Check "CA Status" for template version (A = no NDA, B = has NDA)

### Step 3: Draft emails/texts
- Use templates from `email_templates.md`
- Personalize `[First name]` (use "there" if no proper first name)
- **ALWAYS show drafts to Jake before sending**

### Step 4: Send communications
- **Emails:** `mcp__gmail__gmail_send` with CC to Jasmin@resourcerealtygroupmi.com
- **Texts:** `mcp__httpsms__httpsms_send`
- **ALWAYS get Jake's explicit approval before sending**

### Step 5: Update HubSpot (MANDATORY after EVERY email or NDA)
- Search: `mcp__hubspot__hubspot-search-objects`
- Create if missing: `mcp__hubspot__hubspot-batch-create-objects`
- Add note: `mcp__hubspot__hubspot-create-engagement`

### Step 6: Update spreadsheet
- Mark "Action" column as reached
- Update "Date" column

## HubSpot IDs
- **Owner ID:** 84263493
- **Hub ID:** 244167410

## SMS Template
```
Hey [Name], it's Jake Phillips from Resource Realty Group. I just sent you an email about [Property/Topic]. Let me know if you have any questions-- (734) 896-0518.
```

## Rules
1. CC Jasmin on ALL emails
2. ALWAYS show drafts before sending
3. ALWAYS update HubSpot after sending emails
4. ALWAYS update HubSpot after sending NDAs
5. Add missing contacts to HubSpot
6. Use "there" for company names or unclear names
