# RRG Claude Endpoint

## What
HTTP API proxy that accepts prompts and pipes them to `claude -p` CLI. Runs on jake-macbook via pm2 (port 8787), accessible over Tailscale at `http://100.108.74.112:8787`.

Windmill flows on rrg-server call this to get LLM responses without their own Claude credentials — it uses an OAuth token (shared with rrg-router/pnl/brochure) passed to the CLI.

## Request/Response

**`POST /`** (any path)

Request:
```json
{
  "prompt": "Classify this email...",        // required
  "model": "haiku",                          // optional, default "haiku"
  "systemPrompt": "You are a classifier..."  // optional, prepended to prompt
}
```

Response (success):
```json
{
  "response": "This email is a lead notification...",
  "model": "haiku",
  "success": true
}
```

Response (error):
```json
{
  "error": "Missing prompt",
  "success": false
}
```

## Model Validation
Only `haiku`, `sonnet`, `opus` are accepted. Any other value falls back to `haiku`.

## How It Works
1. Receives POST with JSON body
2. Validates `prompt` exists, sanitizes `model`
3. Writes prompt to temp file (avoids shell escaping issues)
4. Runs: `cat <tempfile> | claude -p --model <model> --allowedTools ""`
5. Returns stdout as `response`
6. Cleans up temp file

Key details:
- `--allowedTools ""` = no tools, pure reasoning (no file access, no web)
- `ANTHROPIC_API_KEY` explicitly unset, `CLAUDE_CODE_OAUTH_TOKEN` passed through so CLI uses OAuth
- 10MB output buffer, 2-minute timeout
- CORS enabled (all origins)

## Environment Variables
| Variable | Default | What |
|----------|---------|------|
| `PORT` | `8787` | Listen port |
| `CLAUDE_PATH` | `$HOME/.npm-global/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | OAuth token for Claude CLI (shared with rrg-router) |

## Who Calls It
- **Windmill flows** on rrg-server — lead intake, lead conversation, message routing, draft generation


## Manage
```bash
pm2 start server.js --name claude-endpoint
pm2 restart claude-endpoint
pm2 logs claude-endpoint
pm2 status
```

## Tech
- **Language:** Node.js (vanilla, no framework)
- **Port:** 8787
- **Process manager:** pm2 (auto-starts on boot)
- **Location:** jake-macbook (must be awake for endpoint to work)
