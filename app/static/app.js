const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chatMessages = document.querySelector("#chatMessages");
const uploadForm = document.querySelector("#uploadForm");
const knowledgeFile = document.querySelector("#knowledgeFile");
const fileName = document.querySelector("#fileName");
const uploadResult = document.querySelector("#uploadResult");

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

knowledgeFile.addEventListener("change", () => {
  const selectedFile = knowledgeFile.files[0];
  fileName.textContent = selectedFile ? selectedFile.name : "支持 txt、pdf 等后续可解析文件";
});

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
