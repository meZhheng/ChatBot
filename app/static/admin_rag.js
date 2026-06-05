const refreshChunksButton = document.querySelector("#refreshChunksButton");
const chunksStatus = document.querySelector("#chunksStatus");
const chunksList = document.querySelector("#chunksList");
const retrieveForm = document.querySelector("#retrieveForm");
const queryInput = document.querySelector("#queryInput");
const topKInput = document.querySelector("#topKInput");
const retrieveStatus = document.querySelector("#retrieveStatus");
const retrieveResults = document.querySelector("#retrieveResults");

const hasChunksUi = Boolean(refreshChunksButton && chunksStatus && chunksList);
const hasRetrieveUi = Boolean(retrieveForm && queryInput && topKInput && retrieveStatus && retrieveResults);

if (hasChunksUi) {
  function renderChunks(chunks) {
    chunksList.replaceChildren();

    if (!chunks.length) {
      chunksStatus.textContent = "当前没有已入库 chunks。";
      return;
    }

    chunksStatus.textContent = `共 ${chunks.length} 条 chunks`;

    for (const chunk of chunks) {
      const card = document.createElement("article");
      card.className = "chunk-card";

      const text = document.createElement("pre");
      text.className = "chunk-text";
      text.textContent = chunk.text;

      const meta = document.createElement("dl");
      meta.className = "chunk-meta";

      const fields = [
        ["source", chunk.metadata?.source ?? "-"],
        ["created_at", chunk.metadata?.created_at ?? "-"],
        ["operator", chunk.metadata?.operator ?? "-"],
        ["id", chunk.id],
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
      chunksList.append(card);
    }
  }

  async function loadChunks() {
    chunksStatus.textContent = "正在加载 chunks...";

    try {
      const response = await fetch("/api/admin/rag/chunks");
      const data = await response.json();
      renderChunks(data.chunks);
    } catch (error) {
      chunksList.replaceChildren();
      chunksStatus.textContent = "chunks 加载失败，请点击刷新重试。";
    }
  }

  refreshChunksButton.addEventListener("click", loadChunks);
  loadChunks();
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
