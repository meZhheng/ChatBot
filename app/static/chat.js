const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const chatMessages = document.querySelector("#chatMessages");
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

    const botMessage = appendMessage("bot", "模型正在思考...", "thinking");
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
          const result = handleStreamEvent(streamEvent, botMessage, reply, finalReply);
          reply = result.reply;
          finalReply = result.finalReply;
          if (streamEvent.type === "error") streamFailed = true;
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        const streamEvent = parseStreamLine(buffer);
        if (streamEvent) {
          const result = handleStreamEvent(streamEvent, botMessage, reply, finalReply);
          reply = result.reply;
          finalReply = result.finalReply;
          if (streamEvent.type === "error") streamFailed = true;
        }
      }

      if (streamFailed) {
        setMessageState(botMessage, "failed");
      } else {
        const savedReply = finalReply || reply || "没有收到模型输出。";
        updateMessage(botMessage, savedReply);
        setMessageState(botMessage, "done");
        messages.push({ role: "bot", text: savedReply });
        saveMessages(sessionId, messages);
      }
    } catch (error) {
      const errorText = error instanceof Error ? error.message : "聊天请求失败，请稍后重试。";
      setMessageState(botMessage, "failed");
      updateMessage(botMessage, errorText);
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
      return parsed.filter((item) => item && ["user", "bot", "tool"].includes(item.role) && typeof item.text === "string");
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
      appendMessage(message.role, message.text, message.state || "");
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

  function handleStreamEvent(streamEvent, botMessage, reply, finalReply) {
    switch (streamEvent.type) {
      case "thinking":
        setMessageState(botMessage, "thinking");
        updateMessage(botMessage, streamEvent.content || "模型正在思考...");
        break;
      case "tool_call":
        upsertToolMessage(streamEvent);
        break;
      case "tool_result":
        upsertToolMessage(streamEvent);
        break;
      case "output_delta":
        reply += streamEvent.content || "";
        setMessageState(botMessage, "generating");
        updateMessage(botMessage, reply || "正在生成回复...");
        break;
      case "output":
        finalReply = streamEvent.content || finalReply;
        if (finalReply) updateMessage(botMessage, finalReply);
        break;
      case "memory":
        appendMessage("tool", streamEvent.content || "上下文压缩钩子已触发。", "done");
        messages.push({ role: "tool", text: streamEvent.content || "上下文压缩钩子已触发。", state: "done" });
        break;
      case "error":
        setMessageState(botMessage, "failed");
        updateMessage(botMessage, streamEvent.content || "回复生成失败。请稍后重试。");
        messages.push({ role: "bot", text: streamEvent.content || "回复生成失败。请稍后重试。", state: "failed" });
        saveMessages(sessionId, messages);
        break;
      case "done":
        setMessageState(botMessage, "done");
        break;
      default:
        break;
    }
    return { reply, finalReply };
  }

  function upsertToolMessage(streamEvent) {
    const toolCallId = streamEvent.tool_call_id || `${streamEvent.name || "tool"}-${streamEvent.seq || Date.now()}`;
    const toolName = streamEvent.name || "tool";
    const argsText = streamEvent.args ? `\n参数：${JSON.stringify(streamEvent.args)}` : "";
    const resultText = streamEvent.content ? `\n结果：${streamEvent.content}` : "";
    const text = streamEvent.type === "tool_call"
      ? `调用工具：${toolName}${argsText}`
      : `工具完成：${toolName}${resultText}`;

    let toolMessage = toolElements.get(toolCallId);
    if (!toolMessage) {
      toolMessage = appendMessage("tool", text, streamEvent.type === "tool_call" ? "thinking" : "done");
      toolElements.set(toolCallId, toolMessage);
      messages.push({ role: "tool", text, state: streamEvent.type === "tool_call" ? "thinking" : "done" });
    } else {
      updateMessage(toolMessage, text);
      setMessageState(toolMessage, streamEvent.type === "tool_call" ? "thinking" : "done");
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const item = messages[index];
        if (item.role === "tool" && item.text.includes(toolName)) {
          item.text = text;
          item.state = streamEvent.type === "tool_call" ? "thinking" : "done";
          break;
        }
      }
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
