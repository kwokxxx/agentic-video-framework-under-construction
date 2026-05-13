const state = {
  view: "user",
  trace: [],
  status: null,
  busy: false,
};

const els = {
  modelStatus: document.querySelector("#modelStatus"),
  viewTabs: document.querySelectorAll(".view-tab"),
  userView: document.querySelector("#userView"),
  developerView: document.querySelector("#developerView"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  sessionInput: document.querySelector("#sessionInput"),
  messageList: document.querySelector("#messageList"),
  statusGrid: document.querySelector("#statusGrid"),
  toolList: document.querySelector("#toolList"),
  eventList: document.querySelector("#eventList"),
  runtimeCanvas: document.querySelector("#runtimeCanvas"),
  refreshButton: document.querySelector("#refreshButton"),
  promptChips: document.querySelectorAll(".prompt-chip"),
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

function setBusy(busy) {
  state.busy = busy;
  els.sendButton.disabled = busy;
  els.chatForm.classList.toggle("is-busy", busy);
  els.sendButton.textContent = busy ? "Running" : "Send";
}

async function sendMessage(message) {
  const sessionId = els.sessionInput.value.trim() || "default";
  addMessage("user", message);
  const pending = addMessage("system", "MQ INBOUND -> AGENT LOOP");
  setBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Agent request failed");
    }
    pending.remove();
    addMessage("assistant", payload.message.content || "");
    state.trace = payload.trace || state.trace;
    await loadStatus();
    renderTrace();
    drawRuntimeMap();
  } catch (error) {
    pending.textContent = `ERROR: ${error.message}`;
  } finally {
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
  renderTrace();
  drawRuntimeMap();
}

async function refreshTrace() {
  const response = await fetch("/api/trace?limit=120");
  const payload = await response.json();
  state.trace = payload.trace || [];
  renderTrace();
  drawRuntimeMap();
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
  const recentTypes = new Set((state.trace || []).slice(-12).map((event) => event.type));

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
    const active = isNodeActive(title, recentTypes);
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

function isNodeActive(title, recentTypes) {
  if (title === "MQ In") return recentTypes.has("mq.inbound");
  if (title === "MQ Out") return recentTypes.has("mq.outbound");
  if (title === "Agent") return recentTypes.has("agent.iteration") || recentTypes.has("agent.finalize");
  if (title === "LLM") return recentTypes.has("llm.response");
  if (title === "Tools") return recentTypes.has("tool.executed");
  if (title === "Store") return recentTypes.has("session.history");
  if (title === "Router") return recentTypes.has("mq.inbound");
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
  if (!message || state.busy) {
    return;
  }
  els.messageInput.value = "";
  sendMessage(message);
});

els.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

els.promptChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    els.messageInput.value = chip.dataset.prompt || "";
    els.messageInput.focus();
  });
});

els.refreshButton.addEventListener("click", () => {
  loadStatus();
  refreshTrace();
});

window.addEventListener("resize", drawRuntimeMap);

loadStatus();
setInterval(refreshTrace, 5000);
