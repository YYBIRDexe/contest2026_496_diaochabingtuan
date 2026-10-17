#!/usr/bin/env node
"use strict";

// Export Codex rollouts that were started in this checkout (or its workspace
// directory) to the contest-log JSONL format. This is intentionally local-only.
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawnSync } = require("node:child_process");

const repo = path.resolve(__dirname, "..");
const workspace = path.dirname(repo);
const expectedTeamId = "contest2026_496_diaochabingtuan";
const collectorEnvPath = path.join(os.homedir(), ".claude", "contest-collector.env");
function readCollectorEnv(filename) {
  let source;
  try { source = fs.readFileSync(filename, "utf8"); }
  catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
  const values = {};
  for (const line of source.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || match[1].startsWith("#")) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    values[match[1]] = value;
  }
  return values;
}
const collectorEnv = readCollectorEnv(collectorEnvPath);
const teamId = process.env.TEAM_ID || collectorEnv.TEAM_ID || "";
const login = process.env.GITHUB_LOGIN || collectorEnv.GITHUB_LOGIN || "";
const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
const sessionRoot = path.join(codexHome, "sessions");
const outputRoot = path.join(repo, "logs", login);
const manifestPath = path.join(outputRoot, "manifest.json");
const redact = (value) => String(value ?? "")
  .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_API_KEY]")
  .replace(/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_TOKEN]")
  .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [REDACTED]");
const norm = (value) => path.resolve(value).replace(/[\\/]+$/, "").toLowerCase();

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  const found = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...walk(full));
    else if (entry.isFile() && /^rollout-.*\.jsonl$/i.test(entry.name)) found.push(full);
  }
  return found;
}

function textFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content == null ? "" : JSON.stringify(content);
  return content.map((part) => {
    if (typeof part === "string") return part;
    return part?.text ?? part?.input_text ?? part?.output_text ?? JSON.stringify(part);
  }).join("");
}

function toEvent(record, meta, seq) {
  const payload = record.payload || {};
  const kind = payload.type;
  const base = {
    schema_version: "1.0", session_id: meta.id, team_id: teamId,
    github_login: login, tool: "codex", seq,
    ts: record.timestamp || meta.timestamp, model: meta.model, cwd: meta.cwd,
  };
  if (kind === "message") {
    const role = payload.role;
    // Do not export Codex app/developer environment instructions as contest
    // dialogue. The official Codex adapter likewise records user/assistant only.
    if (!["user", "assistant"].includes(role)) return null;
    let text = textFromContent(payload.content);
    if (payload.recipient) text = `${text}\nrecipient: ${payload.recipient}`;
    return { ...base, role, text: redact(text) };
  }
  if (kind === "reasoning") {
    return { ...base, role: "assistant", thinking: redact(textFromContent(payload.content)) };
  }
  if (kind === "function_call" || kind === "custom_tool_call") {
    return { ...base, role: "tool", tool_name: payload.name || payload.tool_name || "unknown",
      tool_call_id: payload.call_id || payload.id || "", input: redact(typeof payload.arguments === "string" ? payload.arguments : JSON.stringify(payload.arguments ?? payload.input ?? {})) };
  }
  if (kind === "function_call_output" || kind === "custom_tool_call_output") {
    const output = redact(textFromContent(payload.output ?? payload.content));
    // Tool output can echo files that contain Codex's own environment and
    // platform instructions. Keep those private instead of copying them into
    // the public contest log.
    if (/<app-context>|<skills_instructions>|<environment_context>|<tools>/i.test(output)) return null;
    return { ...base, role: "tool", tool_name: payload.name || payload.tool_name || "unknown",
      tool_call_id: payload.call_id || payload.id || "", output };
  }
  if (kind === "compacted") {
    return { ...base, role: "system", text: redact(textFromContent(payload.content ?? payload.summary)) };
  }
  return null;
}

function readManifest() {
  try { return JSON.parse(fs.readFileSync(manifestPath, "utf8")); }
  catch { return { schema_version: "1.0", team_id: teamId, github_login: login,
    generator: "codex-rollout-project-hook@1.0", updated_at: new Date().toISOString(), sessions: [] }; }
}

function main() {
  if (teamId !== expectedTeamId) {
    console.error(`Invalid TEAM_ID in ${collectorEnvPath}; expected ${expectedTeamId}.`);
    return 2;
  }
  if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(login)) {
    console.error(`Set GITHUB_LOGIN to your GitHub username in ${collectorEnvPath} before collecting logs.`);
    return 2;
  }
  if (process.argv.includes("--check-config")) {
    console.log(`Collector identity: ${login} (${teamId}); output: ${outputRoot}`);
    return 0;
  }
  if (!fs.existsSync(sessionRoot)) {
    console.log(`Codex sessions not found at ${sessionRoot}; nothing to collect.`);
    return 0;
  }
  const roots = new Set([norm(repo), norm(workspace)]);
  const manifest = readManifest();
  manifest.sessions = Array.isArray(manifest.sessions) ? manifest.sessions : [];
  const existing = new Map(manifest.sessions.map((entry) => [entry.session_id, entry]));
  const rolloutsBySession = new Map();
  const changed = [];
  let collected = 0;

  for (const filename of walk(sessionRoot)) {
    let records;
    try { records = fs.readFileSync(filename, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)); }
    catch { continue; } // Ignore a rollout being written at the same time.
    const metaRecord = records.find((row) => row.type === "session_meta");
    const meta = metaRecord?.payload || {};
    if (!meta.id || !roots.has(norm(meta.cwd || ""))) continue;
    const converted = [];
    for (const row of records) {
      if (row.type !== "response_item") continue; // Avoid duplicate event_msg mirrors.
      const event = toEvent(row, { ...meta, timestamp: metaRecord.timestamp }, converted.length);
      if (event) converted.push(event);
    }
    if (converted.length === 0) continue;
    const group = rolloutsBySession.get(meta.id) || { meta, events: [] };
    group.events.push(...converted);
    if (!group.meta.model && meta.model) group.meta.model = meta.model;
    rolloutsBySession.set(meta.id, group);
  }

  for (const [sessionId, group] of rolloutsBySession) {
    const seen = new Set();
    const events = group.events
      .filter((event) => {
        const { seq, ...withoutSeq } = event;
        const key = JSON.stringify(withoutSeq);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => Date.parse(a.ts || 0) - Date.parse(b.ts || 0));
    events.forEach((event, index) => { event.seq = index; });
    if (events.length === 0) continue;

    const firstTs = events[0].ts || group.meta.timestamp;
    const date = new Date(firstTs).toISOString().slice(0, 10);
    const dayDir = path.join(outputRoot, date);
    fs.mkdirSync(dayDir, { recursive: true });
    const relative = `logs/${login}/${date}/codex__${sessionId}.jsonl`;
    const target = path.join(repo, relative);
    fs.writeFileSync(target, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");

    // A resumed Codex session can have multiple rollout files. Keep its merged
    // transcript at one manifest path and remove older per-segment copies.
    const targetPath = path.resolve(target);
    const outputPrefix = `${path.resolve(outputRoot)}${path.sep}`;
    const expectedName = `codex__${sessionId}.jsonl`;
    for (const oldFile of walk(outputRoot)) {
      const resolved = path.resolve(oldFile);
      if (path.basename(oldFile) === expectedName && resolved !== targetPath && resolved.startsWith(outputPrefix)) {
        fs.unlinkSync(oldFile);
        const staleRelative = path.relative(repo, oldFile).split(path.sep).join("/");
        if (!changed.includes(staleRelative)) changed.push(staleRelative);
      }
    }

    const last = events[events.length - 1];
    const prior = existing.get(sessionId) || {};
    const entry = { ...prior, session_id: sessionId, tool: "codex",
      started_at: firstTs, last_event_at: last.ts, event_count: events.length,
      file_path: relative, collection_mode: "cli", model: group.meta.model || prior.model,
      data_completeness_warning: "由本机 Git hook 从本项目工作区的 Codex rollout 转录；包含用户/助手对话与工具事件，跳过 system/developer 环境提示及回显平台提示的工具输出，凭证已脱敏。" };
    if (!existing.has(sessionId)) manifest.sessions.push(entry);
    else Object.assign(prior, entry);
    existing.set(sessionId, entry);
    changed.push(relative);
    collected++;
  }

  if (collected === 0) {
    console.log("No project-scoped Codex sessions found; nothing to collect.");
    return 0;
  }
  manifest.updated_at = new Date().toISOString();
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  changed.push(`logs/${login}/manifest.json`);
  const staged = spawnSync("git", ["add", "--", ...changed], { cwd: repo, stdio: "inherit" });
  if (staged.status !== 0) return staged.status || 1;
  console.log(`Collected ${collected} project Codex session(s); staged ${changed.length} log file(s).`);
  return 0;
}

process.exitCode = main();
