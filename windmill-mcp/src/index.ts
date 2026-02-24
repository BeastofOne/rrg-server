#!/usr/bin/env node
/**
 * Windmill MCP Server
 *
 * Local replacement for Windmill's built-in MCP endpoint.
 * Wraps the same REST API with pagination and field trimming
 * to keep responses under a few KB instead of 70K-400K+.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = process.env.WINDMILL_BASE_URL || "http://100.97.86.99:8000";
const TOKEN = process.env.WINDMILL_TOKEN;
const WORKSPACE = process.env.WINDMILL_WORKSPACE || "rrg";
const WS = `/w/${WORKSPACE}`;

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

async function windmillApi(
  path: string,
  method: string = "GET",
  body?: any,
  timeoutMs: number = 30000
): Promise<any> {
  if (!TOKEN) throw new Error("WINDMILL_TOKEN environment variable is required");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${BASE_URL}/api${path}`;
    const response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        "Content-Type": "application/json",
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => "");
      if (response.status === 401) throw new Error("Token expired or invalid");
      if (response.status === 404) throw new Error(`Not found: ${path}`);
      if (response.status >= 500) throw new Error(`Windmill server error (${response.status}): ${errorText.slice(0, 200)}`);
      throw new Error(`API error ${response.status}: ${errorText.slice(0, 200)}`);
    }

    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function truncate(data: any, maxChars: number): string {
  const json = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  if (json.length <= maxChars) return json;
  return json.slice(0, maxChars) + `\n...[truncated, showing first ${maxChars} of ${json.length} chars]`;
}

function textResult(data: any, maxChars?: number) {
  const text = maxChars ? truncate(data, maxChars) : (typeof data === "string" ? data : JSON.stringify(data, null, 2));
  return { content: [{ type: "text" as const, text }] };
}

/** Convert a Windmill path to the tool name the old MCP used.
 *  f/switchboard/lead_intake → f-f_switchboard_lead__intake  (flow)
 *  f/switchboard/act_signal  → s-f_switchboard_act__signal   (script)
 */
function pathToToolName(path: string, isFlow: boolean): string {
  const prefix = isFlow ? "f-" : "s-";
  const converted = path.replace(/_/g, "__").replace(/\//g, "_");
  return prefix + converted;
}

// ---------------------------------------------------------------------------
// Dynamic tool state (populated at startup)
// ---------------------------------------------------------------------------

interface DynamicToolInfo {
  path: string;
  isFlow: boolean;
}

const dynamicToolMap = new Map<string, DynamicToolInfo>();
let dynamicToolDefs: any[] = [];

// ---------------------------------------------------------------------------
// Static tool definitions
// ---------------------------------------------------------------------------

function getStaticTools(): any[] {
  return [
    // ---- List / Read tools ----
    {
      name: "listFlows",
      description: "List all Windmill flows in the workspace. Returns path and summary for each flow.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listScripts",
      description: "List all Windmill scripts in the workspace. Returns path, summary, and language for each script.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "getFlowByPath",
      description: "Get the full definition of a Windmill flow by its path.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Flow path (e.g. f/switchboard/lead_intake)" },
        },
        required: ["path"],
      },
      annotations: { readOnlyHint: true },
    },
    {
      name: "getScriptByPath",
      description: "Get the full code and metadata of a Windmill script by its path.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Script path (e.g. f/switchboard/act_signal)" },
        },
        required: ["path"],
      },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listVariable",
      description: "List all Windmill variables. Returns path and description (values omitted for safety).",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "getVariable",
      description: "Get the full value of a Windmill variable by path.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Variable path (e.g. f/switchboard/property_mapping)" },
        },
        required: ["path"],
      },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listResource",
      description: "List all Windmill resources. Returns path and resource_type.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "getResource",
      description: "Get the full value of a Windmill resource by path.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Resource path (e.g. f/switchboard/gmail_oauth)" },
        },
        required: ["path"],
      },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listResourceType",
      description: "List Windmill resource types. Returns name and description.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listSchedules",
      description: "List all Windmill schedules. Returns path, cron schedule, enabled status, and script path.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "getSchedule",
      description: "Get the full details of a Windmill schedule by path.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Schedule path" },
        },
        required: ["path"],
      },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listJobs",
      description: "List the 15 most recent completed jobs. Returns id, path, success, duration, and timestamp.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listQueue",
      description: "List up to 15 queued/running jobs. Returns id, path, and timestamps.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },
    {
      name: "listWorkers",
      description: "List Windmill workers. Returns worker name, last ping, and worker group.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
    },

    // ---- Write / Execute tools ----
    {
      name: "runScriptPreviewAndWaitResult",
      description: "Run a Windmill script by path and wait for the result. Returns the script output (truncated to 5KB).",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Script path to run (e.g. f/switchboard/read_signals)" },
          args: { type: "object", description: "Input arguments for the script", additionalProperties: true },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "createVariable",
      description: "Create a new Windmill variable.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Variable path (e.g. f/switchboard/my_var)" },
          value: { type: "string", description: "Variable value" },
          is_secret: { type: "boolean", description: "Whether the variable is a secret (default: false)" },
          description: { type: "string", description: "Variable description" },
        },
        required: ["path", "value"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "updateVariable",
      description: "Update an existing Windmill variable.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Variable path to update" },
          value: { type: "string", description: "New variable value" },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "deleteVariable",
      description: "Delete a Windmill variable.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Variable path to delete" },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "createResource",
      description: "Create a new Windmill resource.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Resource path" },
          value: { type: "object", description: "Resource value (JSON object)", additionalProperties: true },
          resource_type: { type: "string", description: "Resource type name" },
        },
        required: ["path", "value", "resource_type"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "updateResource",
      description: "Update an existing Windmill resource.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Resource path to update" },
          value: { type: "object", description: "New resource value", additionalProperties: true },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "deleteResource",
      description: "Delete a Windmill resource.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Resource path to delete" },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "createSchedule",
      description: "Create a new Windmill schedule.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Schedule path" },
          schedule: { type: "string", description: "Cron expression (e.g. '0 10 * * *')" },
          script_path: { type: "string", description: "Script or flow path to run" },
          is_flow: { type: "boolean", description: "Whether script_path is a flow (default: false)" },
          args: { type: "object", description: "Arguments to pass to the script", additionalProperties: true },
          enabled: { type: "boolean", description: "Whether the schedule is enabled (default: true)" },
          timezone: { type: "string", description: "Timezone (default: America/Detroit)" },
        },
        required: ["path", "schedule", "script_path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "updateSchedule",
      description: "Update an existing Windmill schedule.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Schedule path to update" },
          schedule: { type: "string", description: "New cron expression" },
          args: { type: "object", description: "New arguments", additionalProperties: true },
          enabled: { type: "boolean", description: "Enable or disable the schedule" },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
    {
      name: "deleteSchedule",
      description: "Delete a Windmill schedule.",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string", description: "Schedule path to delete" },
        },
        required: ["path"],
      },
      annotations: { destructiveHint: true },
    },
  ];
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

const server = new Server(
  { name: "windmill-mcp-server", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// ---------------------------------------------------------------------------
// Tool listing
// ---------------------------------------------------------------------------

let allTools: any[] = [];

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: allTools,
}));

// ---------------------------------------------------------------------------
// Tool execution
// ---------------------------------------------------------------------------

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      // =====================================================================
      // LIST / READ TOOLS
      // =====================================================================

      case "listFlows": {
        const flows = await windmillApi(`${WS}/flows/list`);
        const trimmed = (Array.isArray(flows) ? flows : []).map((f: any) => ({
          path: f.path,
          summary: f.summary || "",
        }));
        return textResult(trimmed);
      }

      case "listScripts": {
        const scripts = await windmillApi(`${WS}/scripts/list`);
        const trimmed = (Array.isArray(scripts) ? scripts : []).map((s: any) => ({
          path: s.path,
          summary: s.summary || "",
          language: s.language || "",
        }));
        return textResult(trimmed);
      }

      case "getFlowByPath": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const flow = await windmillApi(`${WS}/flows/get/${path}`);
        return textResult(flow, 8000);
      }

      case "getScriptByPath": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const script = await windmillApi(`${WS}/scripts/get/p/${path}`);
        return textResult(script, 8000);
      }

      case "listVariable": {
        const vars = await windmillApi(`${WS}/variables/list`);
        const trimmed = (Array.isArray(vars) ? vars : []).map((v: any) => ({
          path: v.path,
          description: v.description || "",
          is_secret: v.is_secret || false,
        }));
        return textResult(trimmed);
      }

      case "getVariable": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const variable = await windmillApi(`${WS}/variables/get/${path}`);
        return textResult(variable);
      }

      case "listResource": {
        const resources = await windmillApi(`${WS}/resources/list`);
        const trimmed = (Array.isArray(resources) ? resources : []).map((r: any) => ({
          path: r.path,
          resource_type: r.resource_type || "",
        }));
        return textResult(trimmed);
      }

      case "getResource": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const resource = await windmillApi(`${WS}/resources/get/${path}`);
        return textResult(resource);
      }

      case "listResourceType": {
        const types = await windmillApi(`${WS}/resources/type/list`);
        const trimmed = (Array.isArray(types) ? types : []).map((t: any) => ({
          name: t.name,
          description: t.description || "",
        }));
        return textResult(trimmed);
      }

      case "listSchedules": {
        const schedules = await windmillApi(`${WS}/schedules/list`);
        const trimmed = (Array.isArray(schedules) ? schedules : []).map((s: any) => ({
          path: s.path,
          schedule: s.schedule,
          enabled: s.enabled,
          script_path: s.script_path,
          is_flow: s.is_flow || false,
        }));
        return textResult(trimmed);
      }

      case "getSchedule": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const schedule = await windmillApi(`${WS}/schedules/get/${path}`);
        return textResult(schedule);
      }

      case "listJobs": {
        const jobs = await windmillApi(`${WS}/jobs/completed/list?per_page=15&order_desc=true`);
        const trimmed = (Array.isArray(jobs) ? jobs : []).map((j: any) => ({
          id: j.id,
          path: j.script_path || j.raw_flow?.value?.modules?.[0]?.value?.path || "",
          success: j.success,
          duration_ms: j.duration_ms,
          created_at: j.created_at,
          job_kind: j.job_kind,
        }));
        return textResult(trimmed);
      }

      case "listQueue": {
        const queue = await windmillApi(`${WS}/jobs/queue/list?per_page=15&order_desc=true`);
        const trimmed = (Array.isArray(queue) ? queue : []).map((q: any) => ({
          id: q.id,
          path: q.script_path || "",
          created_at: q.created_at,
          started_at: q.started_at,
          scheduled_for: q.scheduled_for,
          job_kind: q.job_kind,
        }));
        return textResult(trimmed);
      }

      case "listWorkers": {
        const workers = await windmillApi(`/workers/list`);
        const trimmed = (Array.isArray(workers) ? workers : []).map((w: any) => ({
          worker: w.worker,
          last_ping: w.last_ping,
          worker_group: w.worker_group,
          started_at: w.started_at,
          jobs_executed: w.jobs_executed,
        }));
        return textResult(trimmed);
      }

      // =====================================================================
      // WRITE / EXECUTE TOOLS
      // =====================================================================

      case "runScriptPreviewAndWaitResult": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const scriptArgs = (args?.args as Record<string, any>) || {};
        const result = await windmillApi(
          `${WS}/jobs/run_wait_result/p/${path}`,
          "POST",
          scriptArgs,
          120000
        );
        return textResult(result, 5000);
      }

      case "createVariable": {
        const result = await windmillApi(`${WS}/variables/create`, "POST", {
          path: args?.path,
          value: args?.value ?? "",
          is_secret: args?.is_secret ?? false,
          description: args?.description ?? "",
        });
        return textResult({ success: true, path: args?.path, result });
      }

      case "updateVariable": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const body: any = {};
        if (args?.value !== undefined) body.value = args.value;
        const result = await windmillApi(`${WS}/variables/update/${path}`, "POST", body);
        return textResult({ success: true, path, result });
      }

      case "deleteVariable": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const result = await windmillApi(`${WS}/variables/delete/${path}`, "DELETE");
        return textResult({ success: true, path, result });
      }

      case "createResource": {
        const result = await windmillApi(`${WS}/resources/create`, "POST", {
          path: args?.path,
          value: args?.value ?? {},
          resource_type: args?.resource_type,
        });
        return textResult({ success: true, path: args?.path, result });
      }

      case "updateResource": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const body: any = {};
        if (args?.value !== undefined) body.value = args.value;
        const result = await windmillApi(`${WS}/resources/update/${path}`, "POST", body);
        return textResult({ success: true, path, result });
      }

      case "deleteResource": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const result = await windmillApi(`${WS}/resources/delete/${path}`, "DELETE");
        return textResult({ success: true, path, result });
      }

      case "createSchedule": {
        const result = await windmillApi(`${WS}/schedules/create`, "POST", {
          path: args?.path,
          schedule: args?.schedule,
          script_path: args?.script_path,
          is_flow: args?.is_flow ?? false,
          args: args?.args ?? {},
          enabled: args?.enabled ?? true,
          timezone: args?.timezone ?? "America/Detroit",
        });
        return textResult({ success: true, path: args?.path, result });
      }

      case "updateSchedule": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const body: any = {};
        if (args?.schedule !== undefined) body.schedule = args.schedule;
        if (args?.args !== undefined) body.args = args.args;
        if (args?.enabled !== undefined) body.enabled = args.enabled;
        const result = await windmillApi(`${WS}/schedules/update/${path}`, "POST", body);
        return textResult({ success: true, path, result });
      }

      case "deleteSchedule": {
        const path = args?.path as string;
        if (!path) throw new Error("path is required");
        const result = await windmillApi(`${WS}/schedules/delete/${path}`, "DELETE");
        return textResult({ success: true, path, result });
      }

      // =====================================================================
      // DYNAMIC TOOLS (flows & scripts)
      // =====================================================================

      default: {
        const dynamic = dynamicToolMap.get(name);
        if (dynamic) {
          const prefix = dynamic.isFlow ? "f" : "p";
          const result = await windmillApi(
            `${WS}/jobs/run_wait_result/${prefix}/${dynamic.path}`,
            "POST",
            args || {},
            120000
          );
          return textResult(result, 5000);
        }
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { content: [{ type: "text" as const, text: `Error: ${message}` }], isError: true };
  }
});

// ---------------------------------------------------------------------------
// Dynamic tool registration (called once at startup)
// ---------------------------------------------------------------------------

async function initDynamicTools() {
  try {
    const [flows, scripts] = await Promise.all([
      windmillApi(`${WS}/flows/list`),
      windmillApi(`${WS}/scripts/list`),
    ]);

    for (const flow of (Array.isArray(flows) ? flows : [])) {
      const toolName = pathToToolName(flow.path, true);
      dynamicToolMap.set(toolName, { path: flow.path, isFlow: true });
      dynamicToolDefs.push({
        name: toolName,
        description: `Run Windmill flow: ${flow.path}${flow.summary ? " - " + flow.summary : ""}`,
        inputSchema: { type: "object", additionalProperties: true },
        annotations: { destructiveHint: true },
      });
    }

    for (const script of (Array.isArray(scripts) ? scripts : [])) {
      const toolName = pathToToolName(script.path, false);
      dynamicToolMap.set(toolName, { path: script.path, isFlow: false });
      dynamicToolDefs.push({
        name: toolName,
        description: `Run Windmill script: ${script.path}${script.summary ? " - " + script.summary : ""}`,
        inputSchema: { type: "object", additionalProperties: true },
        annotations: { destructiveHint: true },
      });
    }

    console.error(`Registered ${dynamicToolDefs.length} dynamic tools (${(Array.isArray(flows) ? flows : []).length} flows, ${(Array.isArray(scripts) ? scripts : []).length} scripts)`);
  } catch (error) {
    console.error("Warning: failed to load dynamic tools:", error instanceof Error ? error.message : error);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  if (!TOKEN) {
    console.error("Warning: WINDMILL_TOKEN not set. Set it before making API calls.");
  }

  await initDynamicTools();
  allTools = [...getStaticTools(), ...dynamicToolDefs];
  console.error(`Windmill MCP server ready with ${allTools.length} tools (${BASE_URL}, workspace: ${WORKSPACE})`);

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
