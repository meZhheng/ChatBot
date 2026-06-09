const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const chatMessages = document.querySelector("#chatMessages");
const agentStatus = document.querySelector("#agentStatus");
const agentStatusText = document.querySelector("#agentStatusText");
const sessionLabel = document.querySelector("#sessionLabel");
const sessionSelect = document.querySelector("#sessionSelect");
const newSessionButton = document.querySelector("#newSessionButton");
const deleteSessionButton = document.querySelector("#deleteSessionButton");
const clearChatButton = document.querySelector("#clearChatButton");

const SESSION_KEY = "rag-chat-session-id";
const SESSION_INDEX_KEY = "rag-chat-sessions";
const HISTORY_KEY_PREFIX = "rag-chat-history:";
const WELCOME_MESSAGE = "你好，我是你的 RAG 对话智能体。请直接发送问题，我会结合已入库知识和当前会话上下文回答。";

if (chatForm && messageInput && sendButton && chatMessages) {
  let sessions = loadSessions();
  let sessionId = ensureCurrentSession();
  let messages = loadMessages(sessionId);
  let toolElements = new Map();

  renderSessionSelect();
  renderMessages();
  updateSessionLabel();

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();
    if (!message) return;

    setBusy(true);
    messageInput.value = "";
    toolElements = new Map();

    messages.push({ role: "user", text: message });
    appendMessage("user", message);
    touchSession(sessionId, message);

    const streamUi = {
      botMessage: null,
    };
    showAgentStatus("模型正在思考...");
    let reply = "";
    let finalReply = "";
    let streamFailed = false;

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionId }),
      });

      if (!response.ok) {
        const detail = await readErrorText(response);
        throw new Error(detail || "聊天请求失败。");
      }

      if (!response.body) {
        throw new Error("当前浏览器不支持流式响应读取。");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const streamEvent = parseStreamLine(line);
          if (!streamEvent) continue;
          const result = handleStreamEvent(streamEvent, streamUi, reply, finalReply);
          reply = result.reply;
          finalReply = result.finalReply;
          if (streamEvent.type === "error") streamFailed = true;
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        const streamEvent = parseStreamLine(buffer);
        if (streamEvent) {
          const result = handleStreamEvent(streamEvent, streamUi, reply, finalReply);
          reply = result.reply;
          finalReply = result.finalReply;
          if (streamEvent.type === "error") streamFailed = true;
        }
      }

      if (streamFailed) {
        const failedMessage = ensureBotMessage(streamUi);
        setMessageState(failedMessage, "failed");
      } else {
        const savedReply = finalReply || reply || "没有收到模型输出。";
        hideAgentStatus();
        const finalMessage = ensureBotMessage(streamUi);
        updateMessage(finalMessage, savedReply);
        setMessageState(finalMessage, "done");
        messages.push({ role: "bot", text: savedReply });
        saveMessages(sessionId, messages);
      }
    } catch (error) {
      const errorText = error instanceof Error ? error.message : "聊天请求失败，请稍后重试。";
      hideAgentStatus();
      const failedMessage = ensureBotMessage(streamUi);
      setMessageState(failedMessage, "failed");
      updateMessage(failedMessage, errorText);
      messages.push({ role: "bot", text: errorText, state: "failed" });
      saveMessages(sessionId, messages);
    } finally {
      setBusy(false);
      renderSessionSelect();
      updateSessionLabel();
      messageInput.focus();
    }
  });

  newSessionButton?.addEventListener("click", () => {
    selectSession(createSessionRecord());
    messageInput.focus();
  });

  deleteSessionButton?.addEventListener("click", async () => {
    if (!sessionId) return;

    setBusy(true);
    try {
      await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    } catch (error) {
      // 本地删除仍可继续，后端失败会在下次请求时重新创建会话。
    } finally {
      localStorage.removeItem(historyKey(sessionId));
      sessions = sessions.filter((session) => session.id !== sessionId);
      saveSessions();
      const nextSession = sessions.slice().sort((a, b) => b.updatedAt - a.updatedAt)[0] || createSessionRecord();
      selectSession(nextSession.id);
      setBusy(false);
      messageInput.focus();
    }
  });

  clearChatButton?.addEventListener("click", () => {
    messages = [];
    localStorage.removeItem(historyKey(sessionId));
    renderMessages();
    updateSessionLabel();
    messageInput.focus();
  });

  sessionSelect?.addEventListener("change", () => {
    if (sessionSelect.value) {
      selectSession(sessionSelect.value);
      messageInput.focus();
    }
  });

  function loadSessions() {
    const rawSessions = localStorage.getItem(SESSION_INDEX_KEY);
    if (!rawSessions) return [];

    try {
      const parsed = JSON.parse(rawSessions);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((session) => session && typeof session.id === "string");
    } catch (error) {
      return [];
    }
  }

  function saveSessions() {
    localStorage.setItem(SESSION_INDEX_KEY, JSON.stringify(sessions));
  }

  function ensureCurrentSession() {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored && sessions.some((session) => session.id === stored)) {
      return stored;
    }

    if (stored && !sessions.length) {
      const migrated = buildSessionRecord(stored, "历史会话");
      sessions.push(migrated);
      saveSessions();
      return stored;
    }

    const latest = sessions.slice().sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (latest) {
      localStorage.setItem(SESSION_KEY, latest.id);
      return latest.id;
    }

    return createSessionRecord();
  }

  function createSessionRecord(title = "新会话") {
    const id = createSessionId();
    const session = buildSessionRecord(id, title);
    sessions.unshift(session);
    saveSessions();
    localStorage.setItem(SESSION_KEY, id);
    return id;
  }

  function buildSessionRecord(id, title) {
    const now = Date.now();
    return { id, title, createdAt: now, updatedAt: now };
  }

  function selectSession(nextSessionId) {
    sessionId = nextSessionId;
    localStorage.setItem(SESSION_KEY, sessionId);
    if (!sessions.some((session) => session.id === sessionId)) {
      sessions.unshift(buildSessionRecord(sessionId, "新会话"));
      saveSessions();
    }
    messages = loadMessages(sessionId);
    toolElements = new Map();
    renderSessionSelect();
    renderMessages();
    updateSessionLabel();
  }

  function touchSession(currentSessionId, firstMessage) {
    const session = sessions.find((item) => item.id === currentSessionId);
    if (!session) return;
    session.updatedAt = Date.now();
    if (session.title === "新会话" && firstMessage) {
      session.title = firstMessage.length > 18 ? `${firstMessage.slice(0, 18)}...` : firstMessage;
    }
    saveSessions();
  }

  function createSessionId() {
    if (crypto.randomUUID) {
      return `chat-${crypto.randomUUID()}`;
    }
    return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function historyKey(currentSessionId) {
    return `${HISTORY_KEY_PREFIX}${currentSessionId}`;
  }

  function loadMessages(currentSessionId) {
    const rawHistory = localStorage.getItem(historyKey(currentSessionId));
    if (!rawHistory) return [];

    try {
      const parsed = JSON.parse(rawHistory);
      if (!Array.isArray(parsed)) return [];
      const validMessages = parsed.filter((item) => item && ["user", "bot", "tool"].includes(item.role) && typeof item.text === "string");
      return dedupeToolMessages(validMessages);
    } catch (error) {
      return [];
    }
  }

  function saveMessages(currentSessionId, nextMessages) {
    localStorage.setItem(historyKey(currentSessionId), JSON.stringify(nextMessages));
    touchSession(currentSessionId);
    updateSessionLabel();
  }

  function renderSessionSelect() {
    if (!sessionSelect) return;
    sessionSelect.replaceChildren();
    const orderedSessions = sessions.slice().sort((a, b) => b.updatedAt - a.updatedAt);
    for (const session of orderedSessions) {
      const option = document.createElement("option");
      option.value = session.id;
      option.textContent = session.title || shortSessionId(session.id);
      option.selected = session.id === sessionId;
      sessionSelect.append(option);
    }
  }

  function renderMessages() {
    chatMessages.replaceChildren();
    toolElements = new Map();

    if (!messages.length) {
      appendMessage("bot", WELCOME_MESSAGE);
      return;
    }

    for (const message of messages) {
      if (message.role === "tool") {
        appendStoredToolMessage(message);
      } else {
        appendMessage(message.role, message.text, message.state || "");
      }
    }
  }

  function appendMessage(role, text, state = "") {
    const message = document.createElement("div");
    message.className = `message ${role}`;
    if (state) message.classList.add(state);

    const roleLabel = document.createElement("span");
    roleLabel.className = "message-role";
    roleLabel.textContent = roleLabelText(role);

    const content = document.createElement("p");
    content.textContent = text;

    message.append(roleLabel, content);
    chatMessages.append(message);
    scrollMessagesToBottom();
    return message;
  }

  function roleLabelText(role) {
    if (role === "user") return "You";
    if (role === "tool") return "Tool";
    return "Bot";
  }

  function updateMessage(messageElement, text) {
    const content = messageElement.querySelector("p");
    if (content) content.textContent = text;
    scrollMessagesToBottom();
  }

  function setMessageState(messageElement, state) {
    messageElement.classList.remove("thinking", "generating", "done", "failed", "streaming", "error");
    if (state) messageElement.classList.add(state);
    if (state === "failed") messageElement.classList.add("error");
  }

  function parseStreamLine(line) {
    const trimmed = line.trim();
    if (!trimmed) return null;
    try {
      return JSON.parse(trimmed);
    } catch (error) {
      return { type: "error", content: "收到无法解析的流式事件。" };
    }
  }

  function ensureBotMessage(streamUi) {
    if (!streamUi.botMessage) {
      streamUi.botMessage = appendMessage("bot", "", "generating");
    }
    return streamUi.botMessage;
  }

  function showAgentStatus(text) {
    if (!agentStatus || !agentStatusText) return;
    agentStatusText.textContent = text;
    agentStatus.hidden = false;
  }

  function hideAgentStatus() {
    if (!agentStatus) return;
    agentStatus.hidden = true;
  }

  function handleStreamEvent(streamEvent, streamUi, reply, finalReply) {
    switch (streamEvent.type) {
      case "thinking":
        showAgentStatus(streamEvent.content || "模型正在思考...");
        break;
      case "tool_call":
        showAgentStatus(`正在调用工具：${normalizedToolName(streamEvent)}`);
        upsertToolMessage(streamEvent);
        break;
      case "tool_result":
        showAgentStatus(`工具返回完成：${normalizedToolName(streamEvent)}`);
        upsertToolMessage(streamEvent);
        break;
      case "output_delta": {
        reply += streamEvent.content || "";
        hideAgentStatus();
        const botMessage = ensureBotMessage(streamUi);
        setMessageState(botMessage, "generating");
        updateMessage(botMessage, reply || "正在生成回复...");
        break;
      }
      case "output": {
        finalReply = streamEvent.content || finalReply;
        if (finalReply) {
          hideAgentStatus();
          updateMessage(ensureBotMessage(streamUi), finalReply);
        }
        break;
      }
      case "memory":
        appendMessage("tool", streamEvent.content || "上下文压缩钩子已触发。", "done");
        messages.push({ role: "tool", text: streamEvent.content || "上下文压缩钩子已触发。", state: "done" });
        break;
      case "error": {
        hideAgentStatus();
        const botMessage = ensureBotMessage(streamUi);
        setMessageState(botMessage, "failed");
        updateMessage(botMessage, streamEvent.content || "回复生成失败。请稍后重试。");
        messages.push({ role: "bot", text: streamEvent.content || "回复生成失败。请稍后重试。", state: "failed" });
        saveMessages(sessionId, messages);
        break;
      }
      case "done":
        if (streamUi.botMessage) setMessageState(streamUi.botMessage, "done");
        hideAgentStatus();
        break;
      default:
        break;
    }
    return { reply, finalReply };
  }

  function upsertToolMessage(streamEvent) {
    const isResult = streamEvent.type === "tool_result";
    const toolName = normalizedToolName(streamEvent);
    const toolRecord = resolveToolRecord(streamEvent, toolName, isResult);
    const { toolCallId, record, created } = toolRecord;
    const displayToolName = record.toolName && record.toolName !== "tool" ? record.toolName : toolName;
    const argsText = streamEvent.args !== undefined ? formatToolValue(streamEvent.args, "无参数") : record.args.textContent || "无参数";
    const resultText = streamEvent.content !== undefined ? formatToolValue(streamEvent.content, "工具返回了空结果。") : record.result.textContent || "等待工具返回结果...";
    const historyText = isResult
      ? `工具完成：${displayToolName}\n参数：${argsText}\n结果：${resultText}`
      : `调用工具：${displayToolName}\n参数：${argsText}`;

    record.toolName = displayToolName;
    record.done = isResult;
    record.name.textContent = displayToolName;
    record.args.textContent = argsText;
    if (isResult) record.result.textContent = resultText;
    record.status.textContent = isResult ? "完成" : "调用中";
    record.summary.classList.toggle("tool-running", !isResult);
    record.card.classList.add("is-open");
    record.summary.setAttribute("aria-expanded", "true");
    setMessageState(record.element, isResult ? "done" : "thinking");

    if (created) {
      messages.push({ role: "tool", text: historyText, state: isResult ? "done" : "thinking", toolCallId });
    } else {
      updateStoredToolMessage(toolCallId, displayToolName, historyText, isResult ? "done" : "thinking");
    }
  }

  function createToolCard(toolName, toolCallId) {
    const message = document.createElement("div");
    message.className = "message tool thinking";
    message.dataset.toolCallId = toolCallId;

    const card = document.createElement("div");
    card.className = "tool-card is-open";

    const summary = document.createElement("button");
    summary.className = "tool-summary tool-running";
    summary.type = "button";
    summary.setAttribute("aria-expanded", "true");

    const badge = document.createElement("span");
    badge.className = "tool-badge";
    badge.textContent = "TOOL";

    const name = document.createElement("span");
    name.className = "tool-name";
    name.textContent = toolName;

    const status = document.createElement("span");
    status.className = "tool-status";
    status.textContent = "调用中";

    const body = document.createElement("div");
    body.className = "tool-body";

    summary.addEventListener("click", () => {
      const isOpen = card.classList.toggle("is-open");
      summary.setAttribute("aria-expanded", String(isOpen));
    });

    const argsTitle = document.createElement("span");
    argsTitle.className = "tool-section-title";
    argsTitle.textContent = "参数";

    const args = document.createElement("pre");
    args.className = "tool-payload";
    args.textContent = "无参数";

    const resultTitle = document.createElement("span");
    resultTitle.className = "tool-section-title";
    resultTitle.textContent = "结果";

    const result = document.createElement("pre");
    result.className = "tool-payload tool-result";
    result.textContent = "等待工具返回结果...";

    summary.append(badge, name, status);
    body.append(argsTitle, args, resultTitle, result);
    card.append(summary, body);
    message.append(card);
    chatMessages.append(message);
    scrollMessagesToBottom();

    return { element: message, card, summary, name, status, args, result, toolName, done: false };
  }

  function resolveToolRecord(streamEvent, toolName, isResult) {
    const eventId = streamEvent.tool_call_id || "";
    if (eventId && toolElements.has(eventId)) {
      return { toolCallId: eventId, record: toolElements.get(eventId), created: false };
    }

    if (isResult) {
      const pending = findPendingToolRecord(toolName) || (toolName === "tool" ? findSinglePendingToolRecord() : null);
      if (pending) {
        if (eventId) toolElements.set(eventId, pending.record);
        return { toolCallId: pending.toolCallId, record: pending.record, created: false };
      }
    }

    const toolCallId = eventId || stableToolCallId(streamEvent, toolName);
    const existing = toolElements.get(toolCallId);
    if (existing) return { toolCallId, record: existing, created: false };

    const record = createToolCard(toolName, toolCallId);
    toolElements.set(toolCallId, record);
    return { toolCallId, record, created: true };
  }

  function findPendingToolRecord(toolName) {
    for (const [toolCallId, record] of toolElements.entries()) {
      if (record.toolName === toolName && !record.done) {
        return { toolCallId, record };
      }
    }
    return null;
  }

  function findSinglePendingToolRecord() {
    let pending = null;
    for (const [toolCallId, record] of toolElements.entries()) {
      if (record.done) continue;
      if (pending) return null;
      pending = { toolCallId, record };
    }
    return pending;
  }

  function appendStoredToolMessage(message) {
    const parsed = parseStoredToolText(message.text);
    const toolCallId = message.toolCallId || `stored:${parsed.name}:${hashText(message.text)}`;
    const record = createToolCard(parsed.name, toolCallId);
    toolElements.set(toolCallId, record);
    record.toolName = parsed.name;
    record.done = message.state === "done";
    record.name.textContent = parsed.name;
    record.args.textContent = parsed.args || "无参数";
    record.result.textContent = parsed.result || "等待工具返回结果...";
    record.status.textContent = record.done ? "完成" : "调用中";
    record.summary.classList.toggle("tool-running", !record.done);
    setMessageState(record.element, record.done ? "done" : "thinking");
  }

  function updateStoredToolMessage(toolCallId, toolName, text, state) {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const item = messages[index];
      if (item.role !== "tool") continue;
      if (item.toolCallId === toolCallId || normalizedStoredToolName(item.text) === toolName) {
        item.text = text;
        item.state = state;
        item.toolCallId = toolCallId;
        return;
      }
    }
    messages.push({ role: "tool", text, state, toolCallId });
  }

  function dedupeToolMessages(items) {
    const result = [];
    const toolIndexes = new Map();
    for (const item of items) {
      if (item.role !== "tool") {
        result.push(item);
        continue;
      }

      const name = normalizedStoredToolName(item.text);
      if (name === "tool" && item.text.includes("调用工具")) continue;
      const key = item.toolCallId || name;
      const existingIndex = toolIndexes.get(key);
      if (existingIndex === undefined) {
        toolIndexes.set(key, result.length);
        result.push(item);
        continue;
      }

      if (item.state === "done" || item.text.includes("结果：")) {
        result[existingIndex] = item;
      }
    }
    return result;
  }

  function parseStoredToolText(text) {
    return {
      name: normalizedStoredToolName(text),
      args: extractStoredSection(text, "参数") || "{}",
      result: extractStoredSection(text, "结果"),
    };
  }

  function normalizedToolName(streamEvent) {
    const explicitName = streamEvent.name && streamEvent.name !== "tool" ? streamEvent.name : "";
    return explicitName || inferToolName(streamEvent);
  }

  function normalizedStoredToolName(text) {
    const match = text.match(/(?:调用工具|工具完成)[:：\s]+([^\n\s]+)/);
    return match?.[1] || "tool";
  }

  function extractStoredSection(text, title) {
    const match = text.match(new RegExp(`${title}[:：]([\\s\\S]*?)(?=\\n(?:参数|结果)[:：]|$)`));
    return match?.[1]?.trim() || "";
  }

  function hashText(text) {
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = (hash * 31 + text.charCodeAt(index)) >>> 0;
    }
    return hash.toString(36);
  }

  function stableToolCallId(streamEvent, toolName) {
    if (streamEvent.tool_call_id) return streamEvent.tool_call_id;
    const argsKey = streamEvent.args ? JSON.stringify(streamEvent.args) : streamEvent.content || "";
    return `${toolName}:${argsKey}`;
  }

  function inferToolName(streamEvent) {
    const content = streamEvent.content || "";
    const match = content.match(/(?:调用工具|工具完成)[:：\s]+([A-Za-z0-9_:-]+)/);
    return match?.[1] || streamEvent.name || "tool";
  }

  function formatToolValue(value, emptyText) {
    if (value === null || value === undefined) return emptyText;
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed || emptyText;
    }
    if (Array.isArray(value) && !value.length) return emptyText;
    if (typeof value === "object" && !Object.keys(value).length) return emptyText;
    return formatJson(value);
  }

  function formatJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  function scrollMessagesToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function setBusy(isBusy) {
    messageInput.disabled = isBusy;
    sendButton.disabled = isBusy;
    newSessionButton?.toggleAttribute("disabled", isBusy);
    deleteSessionButton?.toggleAttribute("disabled", isBusy);
    clearChatButton?.toggleAttribute("disabled", isBusy);
    if (sessionSelect) sessionSelect.disabled = isBusy;
    sendButton.textContent = isBusy ? "生成中" : "发送";
  }

  function updateSessionLabel() {
    if (!sessionLabel) return;

    const count = messages.filter((message) => message.role === "user").length;
    sessionLabel.textContent = `${shortSessionId(sessionId)} · ${count} 条提问`;
  }

  function shortSessionId(currentSessionId) {
    return currentSessionId.length > 18 ? `${currentSessionId.slice(0, 10)}...${currentSessionId.slice(-6)}` : currentSessionId;
  }

  async function readErrorText(response) {
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json();
      return data.detail || data.message || "";
    }
    return response.text();
  }
}
