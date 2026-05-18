const SESSION_STORAGE_KEY = "agentic_llm.session_id";
const DRAFT_STORAGE_KEY = "agentic_llm.session_drafts";
const ACTIVE_TRACE_WINDOW_MS = 30000;
const ACTIVE_TRACE_LIMIT = 12;

const state = {
  view: "user",
  trace: [],
  status: null,
  sessions: [],
  currentSession: readStoredSessionId() || "demo",
  busy: false,
  uploading: false,
  attachments: [],
  seenMessages: new Set(),
  seenLiveHooks: new Set(),
  liveTraceTimer: null,
};

const els = {
  modelStatus: document.querySelector("#modelStatus"),
  viewTabs: document.querySelectorAll(".view-tab"),
  userView: document.querySelector("#userView"),
  developerView: document.querySelector("#developerView"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  addAttachmentButton: document.querySelector("#addAttachmentButton"),
  attachmentMenu: document.querySelector("#attachmentMenu"),
  addFileButton: document.querySelector("#addFileButton"),
  addFolderButton: document.querySelector("#addFolderButton"),
  fileInput: document.querySelector("#fileInput"),
  folderInput: document.querySelector("#folderInput"),
  attachmentList: document.querySelector("#attachmentList"),
  sessionInput: document.querySelector("#sessionInput"),
  openSessionButton: document.querySelector("#openSessionButton"),
  sessionList: document.querySelector("#sessionList"),
  currentSessionLabel: document.querySelector("#currentSessionLabel"),
  messageList: document.querySelector("#messageList"),
  statusGrid: document.querySelector("#statusGrid"),
  contextGrid: document.querySelector("#contextGrid"),
  toolList: document.querySelector("#toolList"),
  skillList: document.querySelector("#skillList"),
  memoryList: document.querySelector("#memoryList"),
  cronList: document.querySelector("#cronList"),
  subagentList: document.querySelector("#subagentList"),
  eventList: document.querySelector("#eventList"),
  runtimeCanvas: document.querySelector("#runtimeCanvas"),
  refreshButton: document.querySelector("#refreshButton"),
};

function setView(view) {
  state.view = view;
  els.viewTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  els.userView.classList.toggle("active", view === "user");
  els.developerView.classList.toggle("active", view === "developer");
  if (view === "developer") {
    drawRuntimeMap();
  }
}

function normalizeSessionId(value) {
  return String(value || "").trim() || "default";
}

function readStoredSessionId() {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistSessionId(sessionId) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    return;
  }
}

function getSessionId() {
  return normalizeSessionId(state.currentSession);
}

function readDrafts() {
  try {
    return JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function draftSessionIds() {
  return Object.keys(readDrafts()).map(normalizeSessionId);
}

function writeDrafts(drafts) {
  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(drafts));
  } catch {
    return;
  }
}

function saveDraftForSession(sessionId, value) {
  const normalized = normalizeSessionId(sessionId);
  const drafts = readDrafts();
  if (value) {
    drafts[normalized] = value;
  } else {
    delete drafts[normalized];
  }
  writeDrafts(drafts);
}

function clearDraftForSession(sessionId) {
  saveDraftForSession(sessionId, "");
}

function saveCurrentDraft() {
  saveDraftForSession(state.currentSession, els.messageInput.value);
}

function restoreDraftForSession(sessionId) {
  const drafts = readDrafts();
  els.messageInput.value = drafts[normalizeSessionId(sessionId)] || "";
}

async function setSessionId(sessionId, { loadHistory = true, saveDraft = true } = {}) {
  if (saveDraft) {
    saveCurrentDraft();
  }
  const previous = normalizeSessionId(state.currentSession);
  const normalized = normalizeSessionId(sessionId);
  state.currentSession = normalized;
  els.currentSessionLabel.textContent = normalized;
  persistSessionId(normalized);
  if (normalized !== previous) {
    clearAttachments();
  }
  renderSessionOptions();
  if (loadHistory) {
    await loadSessionHistory(normalized);
  }
  restoreDraftForSession(normalized);
}

async function createSessionFromInput() {
  const requested = els.sessionInput.value.trim();
  const sessionId = normalizeSessionId(requested || `session-${Date.now()}`);
  const exists = state.sessions.some((session) => normalizeSessionId(session.id) === sessionId);
  if (!exists) {
    clearDraftForSession(sessionId);
  }
  await setSessionId(sessionId);
  els.sessionInput.value = "";
  els.messageInput.focus();
}

async function loadSessions() {
  const response = await fetch("/api/sessions");
  const payload = await response.json();
  state.sessions = payload.sessions || [];
  renderSessionOptions();
}

function renderSessionOptions() {
  const current = normalizeSessionId(state.currentSession);
  const seen = new Set();
  const sessions = [];
  const draftSessions = draftSessionIds().map((id) => ({
    id,
    message_count: 0,
    draft: true,
  }));
  [...state.sessions, ...draftSessions, { id: current, message_count: 0 }].forEach((session) => {
    const id = normalizeSessionId(session.id);
    if (seen.has(id)) {
      return;
    }
    seen.add(id);
    sessions.push({
      ...session,
      id,
      persisted: state.sessions.some((item) => normalizeSessionId(item.id) === id),
    });
  });
  els.sessionList.innerHTML = sessions
    .map((session) => {
      const count = Number(session.message_count || 0);
      const activeClass = session.id === current ? " active" : "";
      const meta = count ? `${count} messages` : session.draft ? "Draft" : "No messages";
      const deleteButton = session.persisted
        ? `<button type="button" class="session-delete" data-session="${escapeHtml(session.id)}" aria-label="Delete ${escapeHtml(session.id)}">Delete</button>`
        : "";
      return `<div class="session-item${activeClass}" data-session="${escapeHtml(session.id)}">
        <button type="button" class="session-open" data-session="${escapeHtml(session.id)}">
          <span class="session-name">${escapeHtml(session.id)}</span>
          <span class="session-meta">${escapeHtml(meta)}</span>
        </button>
        ${deleteButton}
      </div>`;
    })
    .join("");
}

async function deleteSession(sessionId) {
  const normalized = normalizeSessionId(sessionId);
  if (!window.confirm(`Delete conversation "${normalized}"?`)) {
    return;
  }
  saveCurrentDraft();
  const response = await fetch(`/api/session?session_id=${encodeURIComponent(normalized)}`, {
    method: "DELETE",
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Failed to delete session");
  }
  clearDraftForSession(normalized);
  await loadSessions();
  if (normalizeSessionId(state.currentSession) === normalized) {
    const nextSession = state.sessions[0] ? normalizeSessionId(state.sessions[0].id) : "demo";
    await setSessionId(nextSession, { saveDraft: false });
  } else {
    renderSessionOptions();
  }
}

async function loadSessionHistory(sessionId = getSessionId()) {
  const normalized = normalizeSessionId(sessionId);
  const response = await fetch(`/api/history?session_id=${encodeURIComponent(normalized)}`);
  const payload = await response.json();
  if (normalizeSessionId(state.currentSession) !== normalized) {
    return;
  }
  renderHistoryMessages(payload.messages || []);
}

function renderHistoryMessages(messages) {
  state.seenMessages = new Set(messages.map((message) => message.id));
  els.messageList.innerHTML = "";
  if (!messages.length) {
    renderEmptyMessages();
    return;
  }
  messages.forEach((message) => addMessage(message.role, message.content || ""));
}

function renderEmptyMessages() {
  els.messageList.innerHTML = `<div class="empty-state">
    <p>Welcome back</p>
  </div>`;
}

function addMessage(role, content) {
  const empty = els.messageList.querySelector(".empty-state");
  if (empty) {
    empty.remove();
  }
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = content;
  els.messageList.appendChild(node);
  els.messageList.scrollTop = els.messageList.scrollHeight;
  return node;
}

function renderAttachmentList() {
  els.attachmentList.innerHTML = state.attachments
    .map((attachment) => {
      const label = `${attachment.name || "file"} (${formatFileSize(attachment.size_bytes)})`;
      const removeLabel = `Remove ${attachment.name || "file"}`;
      return `<div class="attachment-chip" data-attachment="${escapeHtml(attachment.id)}">
        <span title="${escapeHtml(label)}">${escapeHtml(label)}</span>
        <button type="button" class="attachment-remove" data-attachment="${escapeHtml(attachment.id)}" aria-label="${escapeHtml(removeLabel)}">x</button>
      </div>`;
    })
    .join("");
}

function clearAttachments() {
  state.attachments = [];
  renderAttachmentList();
}

function removeAttachment(attachmentId) {
  state.attachments = state.attachments.filter(
    (attachment) => attachment.id !== attachmentId
  );
  renderAttachmentList();
}

function setAttachmentMenuOpen(open) {
  els.attachmentMenu.hidden = !open;
  els.addAttachmentButton.setAttribute("aria-expanded", open ? "true" : "false");
}

function toggleAttachmentMenu() {
  if (state.busy || state.uploading) {
    return;
  }
  setAttachmentMenuOpen(els.attachmentMenu.hidden);
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) {
    return;
  }

  const formData = new FormData();
  const manifest = files.map((file) => ({
    filename: file.name,
    relative_path: file.webkitRelativePath || file.name,
  }));
  formData.append("session_id", getSessionId());
  formData.append("manifest", JSON.stringify(manifest));
  files.forEach((file) => formData.append("files", file, file.name));
  setAttachmentMenuOpen(false);
  setUploading(true);

  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Upload failed");
    }
    state.attachments = [...state.attachments, ...(payload.attachments || [])];
    renderAttachmentList();
  } catch (error) {
    addMessage("system", `ERROR: ${error.message}`);
  } finally {
    setUploading(false);
  }
}

function formatComposerUserMessage(message, attachments) {
  const lines = [];
  if (message) {
    lines.push(message);
  }
  if (attachments.length) {
    lines.push(
      `Attached: ${attachments
        .map(
          (attachment) =>
            `${attachment.name || "file"} (${formatFileSize(attachment.size_bytes)})`
        )
        .join(", ")}`
    );
  }
  return lines.join("\n\n") || "Attached file(s)";
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function startLiveTracePolling() {
  stopLiveTracePolling();
  refreshTrace();
  state.liveTraceTimer = window.setInterval(refreshTrace, 800);
}

function stopLiveTracePolling() {
  if (!state.liveTraceTimer) {
    return;
  }
  window.clearInterval(state.liveTraceTimer);
  state.liveTraceTimer = null;
}

function renderLiveToolHooks(trace) {
  if (!state.busy) {
    return;
  }
  const currentSession = getSessionId();
  trace.forEach((event) => {
    if (event.session_id !== currentSession) {
      return;
    }
    if (event.type !== "tool.call" && event.type !== "tool.executed") {
      return;
    }
    const tools = (event.metadata && event.metadata.tools) || [];
    tools.forEach((tool, index) => {
      const hookId = `${event.id}:${tool.id || tool.name || index}:${event.type}`;
      if (state.seenLiveHooks.has(hookId)) {
        return;
      }
      state.seenLiveHooks.add(hookId);
      addMessage("system", formatLiveToolHook(event.type, tool));
    });
  });
}

function formatLiveToolHook(type, tool) {
  if (type === "tool.call") {
    const details = formatSafeToolDetails(tool.arguments || {});
    return [`Tool call: ${tool.name || "unknown"}`, details].filter(Boolean).join("\n");
  }

  const details = formatSafeToolDetails({
    ...(tool.metadata || {}),
    content_chars: tool.content_chars,
    duration_ms: tool.duration_ms,
  });
  return [`Tool result: ${tool.name || "unknown"} / ${tool.status || "success"}`, details].filter(Boolean).join("\n");
}

function formatSafeToolDetails(values) {
  const safeKeys = [
    "action",
    "chars",
    "content_chars",
    "duration_ms",
    "height",
    "kind",
    "matches",
    "max_chars",
    "max_matches",
    "name",
    "path",
    "pattern",
    "replacements",
    "mime_type",
    "size_bytes",
    "status",
    "truncated",
    "url",
    "width",
  ];
  return safeKeys
    .filter((key) => values[key] !== undefined && values[key] !== null && values[key] !== "")
    .map((key) => `${key}: ${values[key]}`)
    .join("\n");
}

function setBusy(busy) {
  state.busy = busy;
  updateComposerState();
}

function setUploading(uploading) {
  state.uploading = uploading;
  updateComposerState();
}

function updateComposerState() {
  const disabled = state.busy || state.uploading;
  els.sendButton.disabled = disabled;
  els.addAttachmentButton.disabled = disabled;
  els.addFileButton.disabled = disabled;
  els.addFolderButton.disabled = disabled;
  if (disabled) {
    setAttachmentMenuOpen(false);
  }
  els.chatForm.classList.toggle("is-busy", state.busy);
  els.chatForm.classList.toggle("is-uploading", state.uploading);
  els.sendButton.textContent = state.busy
    ? "..."
    : state.uploading
      ? "..."
      : "↑";
}

async function sendMessage(message) {
  const sessionId = getSessionId();
  const attachments = state.attachments.slice();
  await setSessionId(sessionId, { loadHistory: false, saveDraft: false });
  addMessage("user", formatComposerUserMessage(message, attachments));
  const pending = addMessage("system", "MQ INBOUND -> AGENT LOOP");
  setBusy(true);
  state.seenLiveHooks = new Set();
  startLiveTracePolling();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message, attachments }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Agent request failed");
    }
    stopLiveTracePolling();
    state.busy = false;
    pending.remove();
    state.seenMessages.add(payload.message.id);
    state.trace = payload.trace || state.trace;
    clearAttachments();
    await loadSessions();
    await loadSessionHistory(sessionId);
    await loadStatus();
    renderTrace();
    drawRuntimeMap();
  } catch (error) {
    pending.textContent = `ERROR: ${error.message}`;
  } finally {
    stopLiveTracePolling();
    setBusy(false);
  }
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const payload = await response.json();
  state.status = payload;
  state.trace = payload.trace || state.trace;
  renderStatus();
  renderTools();
  renderRuntimeExtensions();
  renderTrace();
  drawRuntimeMap();
}

async function refreshDeveloperView() {
  await loadStatus();
  await refreshTrace();
}

async function pollBackgroundMessages() {
  const sessionId = getSessionId();
  const response = await fetch(`/api/messages?session_id=${encodeURIComponent(sessionId)}`);
  const payload = await response.json();
  const messages = payload.messages || [];
  messages.forEach((message) => {
    if (state.seenMessages.has(message.id)) {
      return;
    }
    state.seenMessages.add(message.id);
    addMessage("assistant", message.content || "");
  });
  if (messages.length) {
    await loadSessions();
  }
}

async function refreshTrace() {
  const response = await fetch("/api/trace?limit=120");
  const payload = await response.json();
  state.trace = payload.trace || [];
  renderLiveToolHooks(state.trace);
  renderTrace();
  drawRuntimeMap();
}

async function initialize() {
  els.sessionInput.value = "";
  els.currentSessionLabel.textContent = state.currentSession;
  await loadStatus();
  await loadSessions();
  await loadSessionHistory(state.currentSession);
  restoreDraftForSession(state.currentSession);
}

function renderStatus() {
  if (!state.status) {
    return;
  }
  els.modelStatus.textContent = state.status.model || "MODEL";
  const rows = [
    ["model", state.status.model],
    ["base_url", state.status.base_url],
    ["api_key", state.status.api_key_configured ? "configured" : "missing"],
    ["partitions", String(state.status.partition_count)],
    ["workspace", state.status.workspace_root],
    ["state", state.status.state_root],
    ["bootstrap", Object.entries(state.status.bootstrap || {}).map(([key, value]) => `${key}:${value ? "on" : "off"}`).join(" / ")],
  ];
  els.statusGrid.innerHTML = rows
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || "")}</dd>`)
    .join("");
}

function renderTools() {
  const tools = (state.status && state.status.tools) || [];
  els.toolList.innerHTML = tools
    .map((tool) => {
      return `<div class="tool-item">
        <div class="tool-name">${escapeHtml(tool.name)}</div>
        <div class="tool-description">${escapeHtml(tool.description)}</div>
      </div>`;
    })
    .join("");
}

function renderRuntimeExtensions() {
  renderContextCompression();
  renderSkills();
  renderMemory();
  renderCronJobs();
  renderSubAgents();
}

function renderContextCompression() {
  const report = (state.status && state.status.context_compression) || {};
  const rows = [
    ["original", String(report.original_records || 0)],
    ["final", String(report.final_records || 0)],
    ["folded_tools", String(report.folded_tool_results || 0)],
    ["pruned", String(report.pruned_records || 0)],
    ["summary", report.summary_created ? "yes" : "no"],
    ["stages", (report.stages || []).join(" / ") || "-"],
  ];
  els.contextGrid.innerHTML = rows
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

function renderSkills() {
  const skills = (state.status && state.status.skills) || [];
  if (!skills.length) {
    els.skillList.innerHTML = `<div class="tool-item"><div class="tool-name">No skills loaded</div><div class="tool-description">Create workspace skills under skills/*/SKILL.md.</div></div>`;
    return;
  }
  els.skillList.innerHTML = skills
    .map((skill) => `<div class="tool-item">
      <div class="tool-name">${escapeHtml(skill.name)} ${skill.always ? "(always)" : ""}</div>
      <div class="tool-description">${escapeHtml(skill.description)}</div>
      <div class="event-meta">${escapeHtml(skill.location)}</div>
    </div>`)
    .join("");
}

function renderMemory() {
  const memories = (state.status && state.status.memory) || [];
  els.memoryList.innerHTML = memories
    .map((memory) => `<div class="tool-item">
      <div class="tool-name">${escapeHtml(memory.filename)} / ${memory.exists ? "present" : "missing"}</div>
      <div class="tool-description">${escapeHtml(memory.description)}</div>
    </div>`)
    .join("");
}

function renderCronJobs() {
  const jobs = (state.status && state.status.cron_jobs) || [];
  if (!jobs.length) {
    els.cronList.innerHTML = `<div class="tool-item"><div class="tool-name">No jobs</div><div class="tool-description">CronTool jobs will appear here after creation.</div></div>`;
    return;
  }
  els.cronList.innerHTML = jobs
    .map((job) => `<div class="tool-item">
      <div class="tool-name">${escapeHtml(job.id)} / ${job.enabled ? "enabled" : "disabled"}</div>
      <div class="tool-description">${escapeHtml(job.description)}</div>
      <div class="event-meta">next_run_at_ms=${escapeHtml(job.state && job.state.next_run_at_ms)} / schedule=${escapeHtml(job.schedule && (job.schedule.expr || job.schedule.kind))}</div>
    </div>`)
    .join("");
}

function renderSubAgents() {
  const tasks = (state.status && state.status.subagents) || [];
  if (!tasks.length) {
    els.subagentList.innerHTML = `<div class="tool-item"><div class="tool-name">No SubAgents</div><div class="tool-description">SpawnTool tasks will appear here while running or after completion.</div></div>`;
    return;
  }
  els.subagentList.innerHTML = tasks
    .map((task) => `<div class="tool-item">
      <div class="tool-name">${escapeHtml(task.id)} / ${escapeHtml(task.status)}</div>
      <div class="tool-description">${escapeHtml(task.prompt)}</div>
      <div class="event-meta">${escapeHtml(task.error || task.result || "")}</div>
    </div>`)
    .join("");
}

function renderTrace() {
  const trace = state.trace || [];
  if (!trace.length) {
    els.eventList.innerHTML = `<div class="event"><div class="event-type">TRACE</div><div><div class="event-title">No events yet</div><div class="event-detail">Send a request to populate the runtime stream.</div></div></div>`;
    return;
  }
  els.eventList.innerHTML = trace
    .slice()
    .reverse()
    .map((event) => {
      const meta = JSON.stringify(event.metadata || {}, null, 2);
      return `<div class="event">
        <div class="event-type">${escapeHtml(event.type)}</div>
        <div>
          <div class="event-title">${escapeHtml(event.title)}</div>
          <div class="event-detail">${escapeHtml(event.detail)}</div>
          <div class="event-meta">${escapeHtml(formatTime(event.created_at_ms))} / session ${escapeHtml(event.session_id || "-")}${meta === "{}" ? "" : `\n${escapeHtml(meta)}`}</div>
        </div>
      </div>`;
    })
    .join("");
}

function drawRuntimeMap() {
  const canvas = els.runtimeCanvas;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(rect.width * scale);
  canvas.height = Math.floor(320 * scale);
  ctx.scale(scale, scale);
  ctx.clearRect(0, 0, rect.width, 320);

  const nodes = [
    ["User", "Prompt"],
    ["MQ In", "Inbound"],
    ["Router", "Session"],
    ["Agent", "Loop"],
    ["LLM", "DeepSeek"],
    ["Tools", "Registry"],
    ["Store", "History"],
    ["MQ Out", "Reply"],
  ];
  const width = rect.width;
  const y = 145;
  const gap = width / (nodes.length + 1);
  const recentEvents = getActiveTraceEvents(state.trace || []);

  ctx.lineWidth = 1;
  ctx.strokeStyle = "#363a3f";
  ctx.fillStyle = "#0c0d0f";

  for (let i = 0; i < nodes.length - 1; i += 1) {
    const x1 = gap * (i + 1) + 58;
    const x2 = gap * (i + 2) - 58;
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
  }

  nodes.forEach(([title, subtitle], index) => {
    const x = gap * (index + 1);
    const active = isNodeActive(title, recentEvents);
    ctx.beginPath();
    ctx.roundRect(x - 54, y - 42, 108, 84, 8);
    ctx.fillStyle = active ? "#ffffff" : "#191919";
    ctx.strokeStyle = active ? "#ffffff" : "#212327";
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = active ? "#0a0a0a" : "#ffffff";
    ctx.font = "14px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(title, x, y - 4);
    ctx.fillStyle = active ? "#363a3f" : "#7d8187";
    ctx.font = "12px ui-monospace, Menlo, monospace";
    ctx.fillText(subtitle, x, y + 18);
  });

  ctx.fillStyle = "#7d8187";
  ctx.font = "12px ui-monospace, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.fillText("Runtime path: Web -> MQ -> Session Router -> AgentOnceRun -> LLM/Tools -> History/Checkpoint -> MQ", 18, 292);
}

function getActiveTraceEvents(trace) {
  const now = Date.now();
  return trace
    .slice(-ACTIVE_TRACE_LIMIT)
    .filter((event) => event.created_at_ms && now - event.created_at_ms <= ACTIVE_TRACE_WINDOW_MS);
}

function hasEvent(events, type, predicate = null) {
  return events.some((event) => event.type === type && (!predicate || predicate(event)));
}

function isNodeActive(title, recentEvents) {
  if (title === "User") return hasEvent(recentEvents, "user.prompt");
  if (title === "MQ In") return hasEvent(recentEvents, "mq.inbound");
  if (title === "MQ Out") return hasEvent(recentEvents, "mq.outbound");
  if (title === "Agent") return hasEvent(recentEvents, "agent.iteration") || hasEvent(recentEvents, "agent.finalize");
  if (title === "LLM") return hasEvent(recentEvents, "llm.response");
  if (title === "Tools") return hasEvent(recentEvents, "tool.call") || hasEvent(recentEvents, "tool.executed");
  if (title === "Store") return hasEvent(recentEvents, "session.history");
  if (title === "Router") return hasEvent(recentEvents, "mq.inbound");
  return false;
}

function formatTime(ms) {
  if (!ms) return "-";
  return new Date(ms).toLocaleTimeString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.viewTabs.forEach((tab) => {
  tab.addEventListener("click", () => setView(tab.dataset.view));
});

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  if ((!message && !state.attachments.length) || state.busy || state.uploading) {
    return;
  }
  els.messageInput.value = "";
  clearDraftForSession(state.currentSession);
  sendMessage(message);
});

els.addAttachmentButton.addEventListener("click", () => {
  toggleAttachmentMenu();
});

els.addFileButton.addEventListener("click", () => {
  setAttachmentMenuOpen(false);
  els.fileInput.click();
});

els.addFolderButton.addEventListener("click", () => {
  setAttachmentMenuOpen(false);
  els.folderInput.click();
});

els.fileInput.addEventListener("change", () => {
  uploadFiles(els.fileInput.files);
  els.fileInput.value = "";
});

els.folderInput.addEventListener("change", () => {
  uploadFiles(els.folderInput.files);
  els.folderInput.value = "";
});

document.addEventListener("click", (event) => {
  if (event.target.closest(".composer-tools")) {
    return;
  }
  setAttachmentMenuOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setAttachmentMenuOpen(false);
  }
});

els.attachmentList.addEventListener("click", (event) => {
  const removeButton = event.target.closest(".attachment-remove");
  if (!removeButton) {
    return;
  }
  removeAttachment(removeButton.dataset.attachment);
});

els.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

els.messageInput.addEventListener("input", () => {
  saveCurrentDraft();
});

els.sessionList.addEventListener("click", (event) => {
  const deleteButton = event.target.closest(".session-delete");
  if (deleteButton) {
    deleteSession(deleteButton.dataset.session).catch((error) => {
      addMessage("system", `ERROR: ${error.message}`);
    });
    return;
  }
  const openButton = event.target.closest(".session-open");
  if (!openButton) {
    return;
  }
  setSessionId(openButton.dataset.session);
});

els.sessionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    createSessionFromInput();
  }
});

els.openSessionButton.addEventListener("click", () => {
  createSessionFromInput();
});

els.refreshButton.addEventListener("click", () => {
  refreshDeveloperView();
});

window.addEventListener("resize", drawRuntimeMap);

initialize();
setInterval(refreshTrace, 5000);
setInterval(pollBackgroundMessages, 5000);
