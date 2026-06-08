const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chatMessages = document.querySelector("#chatMessages");
const uploadForm = document.querySelector("#uploadForm");
const knowledgeFile = document.querySelector("#knowledgeFile");
const fileName = document.querySelector("#fileName");
const uploadResult = document.querySelector("#uploadResult");
const retrieveForm = document.querySelector("#retrieveForm");
const queryInput = document.querySelector("#queryInput");
const topKInput = document.querySelector("#topKInput");
const retrieveStatus = document.querySelector("#retrieveStatus");
const retrieveResults = document.querySelector("#retrieveResults");

const hasChatUi = Boolean(chatForm && messageInput && chatMessages);
const hasUploadUi = Boolean(uploadForm && knowledgeFile && fileName && uploadResult);
const hasRetrieveUi = Boolean(retrieveForm && queryInput && topKInput && retrieveStatus && retrieveResults);

function appendMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;

  const roleLabel = document.createElement("span");
  roleLabel.className = "message-role";
  roleLabel.textContent = role === "user" ? "You" : "Bot";

  const content = document.createElement("p");
  content.textContent = text;

  message.append(roleLabel, content);
  chatMessages.append(message);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

if (hasChatUi) {
  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();
    if (!message) return;

    appendMessage("user", message);
    messageInput.value = "";

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await response.json();

    appendMessage("bot", data.reply);
  });
}

if (hasUploadUi) {
  knowledgeFile.addEventListener("change", () => {
    const selectedFile = knowledgeFile.files[0];
    fileName.textContent = selectedFile ? selectedFile.name : "支持 txt、pdf 等后续可解析文件";
  });
}


if (hasRetrieveUi) {
  retrieveForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const query = queryInput.value.trim();
    const topK = Number(topKInput.value);
    if (!query || Number.isNaN(topK) || topK < 1) return;

    retrieveStatus.textContent = "正在执行检索...";
    retrieveResults.replaceChildren();

    try {
      const response = await fetch("/api/admin/rag/retrieve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: topK }),
      });
      const data = await response.json();

      retrieveStatus.textContent = `query: ${data.query} · top_k: ${data.top_k} · results: ${data.results.length}`;

      if (!data.results.length) {
        const empty = document.createElement("p");
        empty.className = "retrieve-empty";
        empty.textContent = "未检索到结果。";
        retrieveResults.append(empty);
        return;
      }

      for (const result of data.results) {
        const card = document.createElement("article");
        card.className = "retrieve-card";

        const text = document.createElement("pre");
        text.className = "retrieve-text";
        text.textContent = result.text;

        const meta = document.createElement("dl");
        meta.className = "retrieve-meta";
        const fields = [
          ["score", result.score],
          ["source", result.metadata?.source ?? "-"],
          ["created_at", result.metadata?.created_at ?? "-"],
          ["operator", result.metadata?.operator ?? "-"],
          ["id", result.id],
        ];

        for (const [label, value] of fields) {
          const item = document.createElement("div");
          const term = document.createElement("dt");
          term.textContent = label;
          const definition = document.createElement("dd");
          definition.textContent = String(value);
          item.append(term, definition);
          meta.append(item);
        }

        card.append(text, meta);
        retrieveResults.append(card);
      }
    } catch (error) {
      retrieveStatus.textContent = "检索失败，请检查 query / top_k 后重试。";
    }
  });
}

if (hasUploadUi) {
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const selectedFile = knowledgeFile.files[0];
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append("file", selectedFile);
    uploadResult.textContent = "正在上传文件...";

    const response = await fetch("/api/knowledge/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    uploadResult.textContent = `${data.filename}：${data.message}`;
    uploadForm.reset();
    fileName.textContent = "支持 txt、pdf 等后续可解析文件";
  });
}
