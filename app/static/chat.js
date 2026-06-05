const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const chatMessages = document.querySelector("#chatMessages");
const sessionLabel = document.querySelector("#sessionLabel");
const newSessionButton = document.querySelector("#newSessionButton");
const clearChatButton = document.querySelector("#clearChatButton");

const SESSION_KEY = "rag-chat-session-id";
const HISTORY_KEY_PREFIX = "rag-chat-history:";
const WELCOME_MESSAGE = "你好，我是你的 RAG 对话智能体。请直接发送问题，我会结合已入库知识和当前会话上下文回答。";

if (chatForm && messageInput && sendButton && chatMessages) {
  let sessionId = getSessionId();
  let messages = loadMessages(sessionId);

  renderMessages();
  updateSessionLabel();

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();
    if (!message) return;

    setBusy(true);
    messageInput.value = "";

    messages.push({ role: "user", text: message });
    appendMessage("user", message);

    const botMessage = appendMessage("bot", "", true);
    let reply = "";

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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        reply += chunk;
        updateMessage(botMessage, reply || "正在生成回复...");
      }

      const tail = decoder.decode();
      if (tail) {
        reply += tail;
        updateMessage(botMessage, reply);
      }

      messages.push({ role: "bot", text: reply || "没有收到模型输出。" });
      saveMessages(sessionId, messages);
    } catch (error) {
      const errorText = error instanceof Error ? error.message : "聊天请求失败，请稍后重试。";
      botMessage.classList.add("error");
      updateMessage(botMessage, errorText);
      messages.push({ role: "bot", text: errorText });
      saveMessages(sessionId, messages);
    } finally {
      botMessage.classList.remove("streaming");
      setBusy(false);
      messageInput.focus();
    }
  });

  newSessionButton?.addEventListener("click", () => {
    sessionId = createSessionId();
    localStorage.setItem(SESSION_KEY, sessionId);
    messages = [];
    renderMessages();
    updateSessionLabel();
    messageInput.focus();
  });

  clearChatButton?.addEventListener("click", () => {
    messages = [];
    localStorage.removeItem(historyKey(sessionId));
    renderMessages();
    updateSessionLabel();
    messageInput.focus();
  });

  function getSessionId() {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored) return stored;

    const nextSessionId = createSessionId();
    localStorage.setItem(SESSION_KEY, nextSessionId);
    return nextSessionId;
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
      return parsed.filter((item) => item && ["user", "bot"].includes(item.role) && typeof item.text === "string");
    } catch (error) {
      return [];
    }
  }

  function saveMessages(currentSessionId, nextMessages) {
    localStorage.setItem(historyKey(currentSessionId), JSON.stringify(nextMessages));
    updateSessionLabel();
  }

  function renderMessages() {
    chatMessages.replaceChildren();

    if (!messages.length) {
      appendMessage("bot", WELCOME_MESSAGE);
      return;
    }

    for (const message of messages) {
      appendMessage(message.role, message.text);
    }
  }

  function appendMessage(role, text, streaming = false) {
    const message = document.createElement("div");
    message.className = `message ${role}`;
    if (streaming) message.classList.add("streaming");

    const roleLabel = document.createElement("span");
    roleLabel.className = "message-role";
    roleLabel.textContent = role === "user" ? "You" : "Bot";

    const content = document.createElement("p");
    content.textContent = text;

    message.append(roleLabel, content);
    chatMessages.append(message);
    scrollMessagesToBottom();
    return message;
  }

  function updateMessage(messageElement, text) {
    const content = messageElement.querySelector("p");
    if (content) content.textContent = text;
    scrollMessagesToBottom();
  }

  function scrollMessagesToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function setBusy(isBusy) {
    messageInput.disabled = isBusy;
    sendButton.disabled = isBusy;
    newSessionButton?.toggleAttribute("disabled", isBusy);
    clearChatButton?.toggleAttribute("disabled", isBusy);
    sendButton.textContent = isBusy ? "生成中" : "发送";
  }

  function updateSessionLabel() {
    if (!sessionLabel) return;

    const shortId = sessionId.length > 18 ? `${sessionId.slice(0, 10)}...${sessionId.slice(-6)}` : sessionId;
    const count = messages.filter((message) => message.role === "user").length;
    sessionLabel.textContent = `${shortId} · ${count} 条提问`;
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
