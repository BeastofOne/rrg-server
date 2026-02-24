const { exec } = require('child_process');
const http = require('http');

const PORT = process.env.PORT || 8787;
const CLAUDE_PATH = process.env.CLAUDE_PATH || `${process.env.HOME}/.npm-global/bin/claude`;

// Validate model names to prevent injection
const VALID_MODELS = ['haiku', 'sonnet', 'opus'];

http.createServer((req, res) => {
  // CORS headers for cross-origin requests
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ error: 'Method not allowed' }));
  }

  let body = '';
  req.on('data', chunk => body += chunk);
  req.on('end', () => {
    try {
      const { prompt, model = 'haiku', systemPrompt } = JSON.parse(body);

      if (!prompt) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'Missing prompt' }));
      }

      // Validate model
      const safeModel = VALID_MODELS.includes(model) ? model : 'haiku';

      // Combine system prompt and user prompt if both provided
      let fullPrompt = prompt;
      if (systemPrompt) {
        fullPrompt = `${systemPrompt}\n\n---\n\n${prompt}`;
      }

      // Write prompt to temp file to avoid shell escaping issues
      const fs = require('fs');
      const os = require('os');
      const path = require('path');
      const tempFile = path.join(os.tmpdir(), `claude-prompt-${Date.now()}.txt`);
      fs.writeFileSync(tempFile, fullPrompt);

      // Call Claude Code CLI in conversation-only mode
      // Using cat and pipe to avoid shell escaping issues with complex prompts
      const cmd = `cat "${tempFile}" | ${CLAUDE_PATH} -p --model ${safeModel} --allowedTools ""`;

      console.log(`[${new Date().toISOString()}] Processing request with model: ${safeModel}`);

      exec(cmd, {
        maxBuffer: 1024 * 1024 * 10, // 10MB buffer for long responses
        timeout: 120000, // 2 minute timeout
        env: {
          ...process.env,
          // Use OAuth token (same account as rrg-router), clear API key to prevent conflicts
          ANTHROPIC_API_KEY: '',
          CLAUDE_CODE_OAUTH_TOKEN: process.env.CLAUDE_CODE_OAUTH_TOKEN || '',
          // Prevent "nested session" error if pm2 was started from inside Claude Code
          CLAUDECODE: ''
        }
      }, (err, stdout, stderr) => {
        // Clean up temp file
        try { fs.unlinkSync(tempFile); } catch (e) {}

        res.writeHead(200, { 'Content-Type': 'application/json' });

        if (err) {
          console.error(`[${new Date().toISOString()}] Error:`, stderr || err.message);
          res.end(JSON.stringify({
            error: stderr || err.message,
            success: false
          }));
        } else {
          console.log(`[${new Date().toISOString()}] Success - response length: ${stdout.length}`);
          res.end(JSON.stringify({
            response: stdout.trim(),
            model: safeModel,
            success: true
          }));
        }
      });
    } catch (e) {
      console.error(`[${new Date().toISOString()}] Parse error:`, e.message);
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid JSON: ' + e.message }));
    }
  });
}).listen(PORT, '0.0.0.0', () => {
  console.log(`Claude endpoint listening on port ${PORT}`);
  console.log(`Using Claude CLI at: ${CLAUDE_PATH}`);
  console.log(`Valid models: ${VALID_MODELS.join(', ')}`);
});
