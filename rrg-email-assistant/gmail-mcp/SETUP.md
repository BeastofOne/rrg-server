# Gmail MCP Server Setup

## One-Time Setup (15 minutes)

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name it "Gmail MCP" → Create
4. Wait for project to be created, then select it

### Step 2: Enable Gmail API

1. Go to [APIs & Services → Library](https://console.cloud.google.com/apis/library)
2. Search for "Gmail API"
3. Click on it → Click "Enable"

### Step 3: Create OAuth Credentials

1. Go to [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure OAuth consent screen first:
   - User Type: "External" → Create
   - App name: "Gmail MCP"
   - User support email: your email
   - Developer contact: your email
   - Click "Save and Continue" through all steps
   - On "Test users" page, click "Add Users" and add your Gmail address
   - Complete the wizard
4. Back to Credentials → "Create Credentials" → "OAuth client ID"
5. Application type: "Desktop app"
6. Name: "Gmail MCP"
7. Click Create
8. Click "Download JSON"
9. Save the file as `credentials.json` in `~/.gmail-mcp/`:

```bash
mkdir -p ~/.gmail-mcp
mv ~/Downloads/client_secret_*.json ~/.gmail-mcp/credentials.json
```

### Step 4: Add to Claude Code Config

Add this to your Claude Code MCP settings (`~/.claude/claude_desktop_config.json` or similar):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "node",
      "args": ["/Users/jacobphillips/Desktop/email-assistant/gmail-mcp/index.js"]
    }
  }
}
```

### Step 5: Restart Claude Code

Restart Claude Code to load the new MCP server.

### Step 6: Authenticate

In Claude Code, I'll run:
1. `gmail_check_auth` - Verify credentials are found
2. `gmail_get_auth_url` - Get the authorization URL
3. You visit the URL, authorize, and give me the code
4. `gmail_authenticate` - Complete the auth with your code

After that, you're done forever!

---

## Available Tools

Once authenticated, these tools are available:

- **gmail_send** - Send a single email (to, subject, body, cc, bcc)
- **gmail_send_bulk** - Send multiple emails at once
- **gmail_recent** - Read recent inbox emails
- **gmail_check_auth** - Verify authentication status

## Example Usage

```
// Send single email
gmail_send(to: "person@example.com", subject: "Hello", body: "Message here")

// Send bulk emails
gmail_send_bulk(emails: [
  { to: "person1@example.com", subject: "Subject 1", body: "Body 1" },
  { to: "person2@example.com", subject: "Subject 2", body: "Body 2" },
])
```
