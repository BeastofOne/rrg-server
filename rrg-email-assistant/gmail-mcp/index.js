#!/usr/bin/env node

const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} = require("@modelcontextprotocol/sdk/types.js");
const { google } = require("googleapis");
const fs = require("fs");
const path = require("path");
const http = require("http");
const url = require("url");

const SCOPES = [
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.compose",
  "https://www.googleapis.com/auth/gmail.modify",
];

const CONFIG_DIR = path.join(process.env.HOME, ".gmail-mcp");
const TOKEN_PATH = path.join(CONFIG_DIR, "token.json");
const CREDENTIALS_PATH = path.join(CONFIG_DIR, "credentials.json");

// Ensure config directory exists
if (!fs.existsSync(CONFIG_DIR)) {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
}

let oauth2Client = null;

function loadCredentials() {
  if (!fs.existsSync(CREDENTIALS_PATH)) {
    return null;
  }
  const credentials = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, "utf8"));
  const { client_secret, client_id, redirect_uris } = credentials.installed || credentials.web;
  oauth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);
  return oauth2Client;
}

function loadToken() {
  if (!fs.existsSync(TOKEN_PATH)) {
    return false;
  }
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf8"));
  oauth2Client.setCredentials(token);
  return true;
}

function saveToken(token) {
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(token));
}

async function getAuthUrl() {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client) {
    return { error: "No credentials.json found. Please add it to ~/.gmail-mcp/credentials.json" };
  }

  const authUrl = oauth2Client.generateAuthUrl({
    access_type: "offline",
    scope: SCOPES,
  });
  return { authUrl };
}

async function authenticateWithCode(code) {
  if (!oauth2Client) {
    loadCredentials();
  }
  try {
    const { tokens } = await oauth2Client.getToken(code);
    oauth2Client.setCredentials(tokens);
    saveToken(tokens);
    return { success: true, message: "Authentication successful! You can now send emails." };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function sendEmail(to, subject, body, cc = null, bcc = null) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client) {
    return { success: false, error: "Not configured. Run setup first." };
  }
  if (!loadToken()) {
    return { success: false, error: "Not authenticated. Run authenticate first." };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  // Build email headers
  let emailLines = [
    `To: ${to}`,
    `Subject: ${subject}`,
  ];

  if (cc) {
    emailLines.push(`Cc: ${cc}`);
  }
  if (bcc) {
    emailLines.push(`Bcc: ${bcc}`);
  }

  emailLines.push(
    "Content-Type: text/plain; charset=utf-8",
    "MIME-Version: 1.0",
    "",
    body
  );

  const email = emailLines.join("\r\n");
  const encodedEmail = Buffer.from(email).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  try {
    const res = await gmail.users.messages.send({
      userId: "me",
      requestBody: {
        raw: encodedEmail,
      },
    });
    return { success: true, messageId: res.data.id, threadId: res.data.threadId };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function replyToEmail(threadId, messageId, to, subject, body, cc = null, bcc = null) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client) {
    return { success: false, error: "Not configured. Run setup first." };
  }
  if (!loadToken()) {
    return { success: false, error: "Not authenticated. Run authenticate first." };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    // Get the original message to extract Message-ID for In-Reply-To header
    const originalMsg = await gmail.users.messages.get({
      userId: "me",
      id: messageId,
      format: "metadata",
      metadataHeaders: ["Message-ID", "References"],
    });

    let originalMessageId = null;
    let references = null;
    for (const header of originalMsg.data.payload.headers) {
      if (header.name === "Message-ID") {
        originalMessageId = header.value;
      }
      if (header.name === "References") {
        references = header.value;
      }
    }

    // Build References header (existing references + original message ID)
    let referencesHeader = references ? `${references} ${originalMessageId}` : originalMessageId;

    // Ensure subject starts with "Re: " if not already
    if (!subject.toLowerCase().startsWith("re:")) {
      subject = `Re: ${subject}`;
    }

    // Build email headers with threading headers
    let emailLines = [
      `To: ${to}`,
      `Subject: ${subject}`,
    ];

    if (originalMessageId) {
      emailLines.push(`In-Reply-To: ${originalMessageId}`);
      emailLines.push(`References: ${referencesHeader}`);
    }

    if (cc) {
      emailLines.push(`Cc: ${cc}`);
    }
    if (bcc) {
      emailLines.push(`Bcc: ${bcc}`);
    }

    emailLines.push(
      "Content-Type: text/plain; charset=utf-8",
      "MIME-Version: 1.0",
      "",
      body
    );

    const email = emailLines.join("\r\n");
    const encodedEmail = Buffer.from(email).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

    const res = await gmail.users.messages.send({
      userId: "me",
      requestBody: {
        raw: encodedEmail,
        threadId: threadId,  // This is the key for threading!
      },
    });
    return { success: true, messageId: res.data.id, threadId: res.data.threadId, isReply: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function sendBulkEmails(emails) {
  // emails is an array of { to, subject, body, cc?, bcc? }
  const results = [];
  for (const email of emails) {
    const result = await sendEmail(email.to, email.subject, email.body, email.cc, email.bcc);
    results.push({ ...email, result });
    // Small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return results;
}

async function getRecentEmails(maxResults = 10) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    const res = await gmail.users.messages.list({
      userId: "me",
      maxResults,
      labelIds: ["INBOX"],
    });

    const messages = [];
    for (const msg of res.data.messages || []) {
      const detail = await gmail.users.messages.get({
        userId: "me",
        id: msg.id,
        format: "metadata",
        metadataHeaders: ["From", "To", "Subject", "Date"],
      });

      const headers = {};
      for (const header of detail.data.payload.headers) {
        headers[header.name] = header.value;
      }
      messages.push({
        id: msg.id,
        threadId: msg.threadId,
        from: headers.From,
        to: headers.To,
        subject: headers.Subject,
        date: headers.Date,
        snippet: detail.data.snippet,
      });
    }
    return { success: true, messages };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function getSentEmails(maxResults = 20) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    const res = await gmail.users.messages.list({
      userId: "me",
      maxResults,
      labelIds: ["SENT"],
    });

    const messages = [];
    for (const msg of res.data.messages || []) {
      const detail = await gmail.users.messages.get({
        userId: "me",
        id: msg.id,
        format: "metadata",
        metadataHeaders: ["From", "To", "Subject", "Date"],
      });

      const headers = {};
      for (const header of detail.data.payload.headers) {
        headers[header.name] = header.value;
      }
      messages.push({
        id: msg.id,
        threadId: msg.threadId,
        from: headers.From,
        to: headers.To,
        subject: headers.Subject,
        date: headers.Date,
        snippet: detail.data.snippet,
      });
    }
    return { success: true, messages };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function searchEmails(query, maxResults = 20) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    const res = await gmail.users.messages.list({
      userId: "me",
      maxResults,
      q: query,
    });

    if (!res.data.messages || res.data.messages.length === 0) {
      return { success: true, messages: [], total: 0 };
    }

    const messages = [];
    for (const msg of res.data.messages || []) {
      const detail = await gmail.users.messages.get({
        userId: "me",
        id: msg.id,
        format: "metadata",
        metadataHeaders: ["From", "To", "Subject", "Date"],
      });

      const headers = {};
      for (const header of detail.data.payload.headers) {
        headers[header.name] = header.value;
      }
      messages.push({
        id: msg.id,
        threadId: msg.threadId,
        from: headers.From,
        to: headers.To,
        subject: headers.Subject,
        date: headers.Date,
        snippet: detail.data.snippet,
      });
    }
    return { success: true, messages, total: res.data.resultSizeEstimate };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Helper function to extract body from message payload
function extractBody(payload) {
  let body = "";

  if (payload.body && payload.body.data) {
    // Direct body data
    body = Buffer.from(payload.body.data, "base64").toString("utf8");
  } else if (payload.parts) {
    // Multipart message - look for text/plain first, then text/html
    for (const part of payload.parts) {
      if (part.mimeType === "text/plain" && part.body && part.body.data) {
        body = Buffer.from(part.body.data, "base64").toString("utf8");
        break;
      }
    }
    // If no plain text found, try html
    if (!body) {
      for (const part of payload.parts) {
        if (part.mimeType === "text/html" && part.body && part.body.data) {
          body = Buffer.from(part.body.data, "base64").toString("utf8");
          // Strip HTML tags for readability
          body = body.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
          break;
        }
      }
    }
    // Check nested parts (for multipart/alternative inside multipart/mixed)
    if (!body) {
      for (const part of payload.parts) {
        if (part.parts) {
          body = extractBody(part);
          if (body) break;
        }
      }
    }
  }

  return body;
}

// Get a single message with full body
async function getMessage(messageId) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    const detail = await gmail.users.messages.get({
      userId: "me",
      id: messageId,
      format: "full",
    });

    const headers = {};
    for (const header of detail.data.payload.headers) {
      headers[header.name] = header.value;
    }

    const body = extractBody(detail.data.payload);

    return {
      success: true,
      message: {
        id: detail.data.id,
        threadId: detail.data.threadId,
        from: headers.From,
        to: headers.To,
        cc: headers.Cc,
        subject: headers.Subject,
        date: headers.Date,
        body: body,
        snippet: detail.data.snippet,
      },
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Get all messages in a thread with full bodies
async function getThread(threadId) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    const thread = await gmail.users.threads.get({
      userId: "me",
      id: threadId,
      format: "full",
    });

    const messages = [];
    for (const msg of thread.data.messages || []) {
      const headers = {};
      for (const header of msg.payload.headers) {
        headers[header.name] = header.value;
      }

      const body = extractBody(msg.payload);

      messages.push({
        id: msg.id,
        threadId: msg.threadId,
        from: headers.From,
        to: headers.To,
        cc: headers.Cc,
        subject: headers.Subject,
        date: headers.Date,
        body: body,
        snippet: msg.snippet,
      });
    }

    return { success: true, messages };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Archive a single message (remove from inbox)
async function archiveMessage(messageId) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client || !loadToken()) {
    return { success: false, error: "Not authenticated" };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    await gmail.users.messages.modify({
      userId: "me",
      id: messageId,
      requestBody: {
        removeLabelIds: ["INBOX"],
      },
    });
    return { success: true, messageId, archived: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Create a draft email (new or reply)
async function createDraft(to, subject, body, cc = null, bcc = null, threadId = null, messageId = null) {
  if (!oauth2Client) {
    loadCredentials();
  }
  if (!oauth2Client) {
    return { success: false, error: "Not configured. Run setup first." };
  }
  if (!loadToken()) {
    return { success: false, error: "Not authenticated. Run authenticate first." };
  }

  const gmail = google.gmail({ version: "v1", auth: oauth2Client });

  try {
    // Build email headers
    let emailLines = [
      `To: ${to}`,
      `Subject: ${subject}`,
    ];

    // If this is a reply, add threading headers
    if (messageId && threadId) {
      const originalMsg = await gmail.users.messages.get({
        userId: "me",
        id: messageId,
        format: "metadata",
        metadataHeaders: ["Message-ID", "References"],
      });

      let originalMessageId = null;
      let references = null;
      for (const header of originalMsg.data.payload.headers) {
        if (header.name === "Message-ID") {
          originalMessageId = header.value;
        }
        if (header.name === "References") {
          references = header.value;
        }
      }

      if (originalMessageId) {
        emailLines.push(`In-Reply-To: ${originalMessageId}`);
        const referencesHeader = references ? `${references} ${originalMessageId}` : originalMessageId;
        emailLines.push(`References: ${referencesHeader}`);
      }

      // Ensure subject starts with "Re:" for replies
      if (!subject.toLowerCase().startsWith("re:")) {
        // Replace the subject line we already added
        emailLines[1] = `Subject: Re: ${subject}`;
      }
    }

    if (cc) {
      emailLines.push(`Cc: ${cc}`);
    }
    if (bcc) {
      emailLines.push(`Bcc: ${bcc}`);
    }

    emailLines.push(
      "Content-Type: text/plain; charset=utf-8",
      "MIME-Version: 1.0",
      "",
      body
    );

    const email = emailLines.join("\r\n");
    const encodedEmail = Buffer.from(email).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

    const requestBody = {
      message: {
        raw: encodedEmail,
      },
    };

    // If replying to a thread, include the threadId
    if (threadId) {
      requestBody.message.threadId = threadId;
    }

    const res = await gmail.users.drafts.create({
      userId: "me",
      requestBody,
    });

    return {
      success: true,
      draftId: res.data.id,
      messageId: res.data.message.id,
      threadId: res.data.message.threadId,
      isReply: !!(threadId && messageId),
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Archive multiple messages
async function archiveMessages(messageIds) {
  const results = [];
  for (const messageId of messageIds) {
    const result = await archiveMessage(messageId);
    results.push(result);
    // Small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const successful = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;
  return {
    success: failed === 0,
    total: messageIds.length,
    archived: successful,
    failed,
    results
  };
}

// Create MCP Server
const server = new Server(
  {
    name: "gmail-mcp",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "gmail_check_auth",
        description: "Check if Gmail is authenticated and ready to use",
        inputSchema: {
          type: "object",
          properties: {},
          required: [],
        },
      },
      {
        name: "gmail_get_auth_url",
        description: "Get the OAuth URL to authenticate with Gmail. User needs to visit this URL and authorize the app.",
        inputSchema: {
          type: "object",
          properties: {},
          required: [],
        },
      },
      {
        name: "gmail_authenticate",
        description: "Complete authentication by providing the authorization code from the OAuth flow",
        inputSchema: {
          type: "object",
          properties: {
            code: {
              type: "string",
              description: "The authorization code from the OAuth redirect URL",
            },
          },
          required: ["code"],
        },
      },
      {
        name: "gmail_send",
        description: "Send a single email via Gmail",
        inputSchema: {
          type: "object",
          properties: {
            to: {
              type: "string",
              description: "Recipient email address",
            },
            subject: {
              type: "string",
              description: "Email subject line",
            },
            body: {
              type: "string",
              description: "Email body (plain text)",
            },
            cc: {
              type: "string",
              description: "CC recipients (optional, comma-separated)",
            },
            bcc: {
              type: "string",
              description: "BCC recipients (optional, comma-separated)",
            },
          },
          required: ["to", "subject", "body"],
        },
      },
      {
        name: "gmail_send_bulk",
        description: "Send multiple emails at once. Each email can have different recipients, subjects, and bodies.",
        inputSchema: {
          type: "object",
          properties: {
            emails: {
              type: "array",
              description: "Array of email objects to send",
              items: {
                type: "object",
                properties: {
                  to: { type: "string", description: "Recipient email address" },
                  subject: { type: "string", description: "Email subject" },
                  body: { type: "string", description: "Email body" },
                  cc: { type: "string", description: "CC recipients (optional)" },
                  bcc: { type: "string", description: "BCC recipients (optional)" },
                },
                required: ["to", "subject", "body"],
              },
            },
          },
          required: ["emails"],
        },
      },
      {
        name: "gmail_recent",
        description: "Get recent emails from inbox",
        inputSchema: {
          type: "object",
          properties: {
            maxResults: {
              type: "number",
              description: "Maximum number of emails to retrieve (default 10)",
            },
          },
          required: [],
        },
      },
      {
        name: "gmail_sent",
        description: "Get recent sent emails",
        inputSchema: {
          type: "object",
          properties: {
            maxResults: {
              type: "number",
              description: "Maximum number of sent emails to retrieve (default 20)",
            },
          },
          required: [],
        },
      },
      {
        name: "gmail_search",
        description: "Search emails using Gmail search query syntax. Examples: 'subject:invoice', 'from:john@example.com', 'after:2024/01/01 before:2024/01/31', 'in:sent subject:Woodside'",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Gmail search query (same syntax as Gmail search box)",
            },
            maxResults: {
              type: "number",
              description: "Maximum number of emails to retrieve (default 20)",
            },
          },
          required: ["query"],
        },
      },
      {
        name: "gmail_reply",
        description: "Reply to an existing email thread. This sends the reply within the same thread as the original message, maintaining conversation continuity.",
        inputSchema: {
          type: "object",
          properties: {
            threadId: {
              type: "string",
              description: "The thread ID to reply to (from search/recent results)",
            },
            messageId: {
              type: "string",
              description: "The message ID to reply to (for In-Reply-To header)",
            },
            to: {
              type: "string",
              description: "Recipient email address",
            },
            subject: {
              type: "string",
              description: "Email subject line (will be prefixed with 'Re:' if not already)",
            },
            body: {
              type: "string",
              description: "Email body (plain text)",
            },
            cc: {
              type: "string",
              description: "CC recipients (optional, comma-separated)",
            },
            bcc: {
              type: "string",
              description: "BCC recipients (optional, comma-separated)",
            },
          },
          required: ["threadId", "messageId", "to", "subject", "body"],
        },
      },
      {
        name: "gmail_get_message",
        description: "Get a single email message with full body content. Use this when you need to read the complete email body, not just the snippet.",
        inputSchema: {
          type: "object",
          properties: {
            messageId: {
              type: "string",
              description: "The message ID to retrieve (from search/recent results)",
            },
          },
          required: ["messageId"],
        },
      },
      {
        name: "gmail_get_thread",
        description: "Get all messages in an email thread with full body content. Use this to read an entire email conversation.",
        inputSchema: {
          type: "object",
          properties: {
            threadId: {
              type: "string",
              description: "The thread ID to retrieve (from search/recent results)",
            },
          },
          required: ["threadId"],
        },
      },
      {
        name: "gmail_create_draft",
        description: "Create a draft email in Gmail. Can be a new email or a reply to an existing thread. The draft is saved but NOT sent — it appears in Gmail's Drafts folder for review before sending.",
        inputSchema: {
          type: "object",
          properties: {
            to: {
              type: "string",
              description: "Recipient email address",
            },
            subject: {
              type: "string",
              description: "Email subject line (for replies, 'Re:' is added automatically if not present)",
            },
            body: {
              type: "string",
              description: "Email body (plain text)",
            },
            cc: {
              type: "string",
              description: "CC recipients (optional, comma-separated)",
            },
            bcc: {
              type: "string",
              description: "BCC recipients (optional, comma-separated)",
            },
            threadId: {
              type: "string",
              description: "The thread ID to reply to (optional — include for reply drafts, omit for new email drafts)",
            },
            messageId: {
              type: "string",
              description: "The message ID to reply to (optional — include for reply drafts to set In-Reply-To header)",
            },
          },
          required: ["to", "subject", "body"],
        },
      },
      {
        name: "gmail_archive",
        description: "Archive a single email message (removes it from inbox but keeps it in All Mail)",
        inputSchema: {
          type: "object",
          properties: {
            messageId: {
              type: "string",
              description: "The message ID to archive (from search/recent results)",
            },
          },
          required: ["messageId"],
        },
      },
      {
        name: "gmail_archive_bulk",
        description: "Archive multiple email messages at once. Useful for cleaning up inbox after processing leads.",
        inputSchema: {
          type: "object",
          properties: {
            messageIds: {
              type: "array",
              items: { type: "string" },
              description: "Array of message IDs to archive",
            },
          },
          required: ["messageIds"],
        },
      },
    ],
  };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "gmail_check_auth": {
      loadCredentials();
      if (!oauth2Client) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                authenticated: false,
                configured: false,
                message: "No credentials.json found. Please download OAuth credentials from Google Cloud Console and save to ~/.gmail-mcp/credentials.json",
              }, null, 2),
            },
          ],
        };
      }
      const hasToken = loadToken();
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              authenticated: hasToken,
              configured: true,
              message: hasToken
                ? "Gmail is authenticated and ready to send emails!"
                : "Credentials found but not authenticated. Use gmail_get_auth_url to get the authorization URL.",
            }, null, 2),
          },
        ],
      };
    }

    case "gmail_get_auth_url": {
      const result = await getAuthUrl();
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_authenticate": {
      const result = await authenticateWithCode(args.code);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_send": {
      const result = await sendEmail(args.to, args.subject, args.body, args.cc, args.bcc);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_send_bulk": {
      const result = await sendBulkEmails(args.emails);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_recent": {
      const result = await getRecentEmails(args.maxResults || 10);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_sent": {
      const result = await getSentEmails(args.maxResults || 20);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_search": {
      const result = await searchEmails(args.query, args.maxResults || 20);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_reply": {
      const result = await replyToEmail(args.threadId, args.messageId, args.to, args.subject, args.body, args.cc, args.bcc);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_get_message": {
      const result = await getMessage(args.messageId);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_get_thread": {
      const result = await getThread(args.threadId);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_create_draft": {
      const result = await createDraft(args.to, args.subject, args.body, args.cc, args.bcc, args.threadId, args.messageId);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_archive": {
      const result = await archiveMessage(args.messageId);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    case "gmail_archive_bulk": {
      const result = await archiveMessages(args.messageIds);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Gmail MCP Server running");
}

main().catch(console.error);
