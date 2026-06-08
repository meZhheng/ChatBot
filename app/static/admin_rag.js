const uploadForm = document.querySelector("#uploadForm");
const uploadInput = document.querySelector("#uploadInput");
const uploadStatus = document.querySelector("#uploadStatus");
const refreshDocumentsButton = document.querySelector("#refreshDocumentsButton");
const documentsStatus = document.querySelector("#documentsStatus");
const documentsList = document.querySelector("#documentsList");
const retrieveForm = document.querySelector("#retrieveForm");
const queryInput = document.querySelector("#queryInput");
const topKInput = document.querySelector("#topKInput");
const retrieveStatus = document.querySelector("#retrieveStatus");
const retrieveResults = document.querySelector("#retrieveResults");

const hasUploadUi = Boolean(uploadForm && uploadInput && uploadStatus);
const hasDocumentsUi = Boolean(refreshDocumentsButton && documentsStatus && documentsList);
const hasRetrieveUi = Boolean(retrieveForm && queryInput && topKInput && retrieveStatus && retrieveResults);

function appendMetaFields(container, fields) {
  for (const [label, value] of fields) {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = String(value ?? "-");
    item.append(term, definition);
    container.append(item);
  }
}

function renderDocuments(documents) {
  if (!hasDocumentsUi) return;

  documentsList.replaceChildren();

  if (!documents.length) {
    documentsStatus.textContent = "当前没有已入库 documents。";
    return;
  }

  documentsStatus.textContent = `共 ${documents.length} 个 documents`;

  for (const documentItem of documents) {
    const card = document.createElement("article");
    card.className = "document-card";

    const header = document.createElement("div");
    header.className = "document-card-header";

    const titleGroup = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = documentItem.filename || documentItem.source || documentItem.document_id;
    const subtitle = document.createElement("p");
    subtitle.textContent = `${documentItem.status} · ${documentItem.active_chunk_count}/${documentItem.total_chunk_count} active chunks`;
    titleGroup.append(title, subtitle);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger-button document-delete-button";
    deleteButton.textContent = "删除 document";
    deleteButton.addEventListener("click", () => deleteDocument(documentItem.document_id, deleteButton));

    header.append(titleGroup, deleteButton);

    const meta = document.createElement("dl");
    meta.className = "document-meta";
    appendMetaFields(meta, [
      ["document_id", documentItem.document_id],
      ["document_hash", documentItem.document_hash],
      ["source", documentItem.source],
      ["content_type", documentItem.content_type],
      ["size_bytes", documentItem.size_bytes],
      ["added_chunks", documentItem.added_chunk_count],
      ["reassigned_chunks", documentItem.reassigned_chunk_count],
      ["created_at", documentItem.created_at],
      ["updated_at", documentItem.updated_at],
      ["operator", documentItem.operator],
    ]);

    const chunksWrapper = document.createElement("div");
    chunksWrapper.className = "document-chunks";

    if (!documentItem.chunks.length) {
      const empty = document.createElement("p");
      empty.className = "retrieve-empty";
      empty.textContent = "当前 document 没有 active chunks。";
      chunksWrapper.append(empty);
    }

    for (const chunk of documentItem.chunks) {
      const chunkCard = document.createElement("article");
      chunkCard.className = "document-chunk-card";

      const chunkHeader = document.createElement("div");
      chunkHeader.className = "document-chunk-header";

      const chunkTitle = document.createElement("strong");
      chunkTitle.textContent = `chunk #${chunk.chunk_index}`;

      const chunkDeleteButton = document.createElement("button");
      chunkDeleteButton.type = "button";
      chunkDeleteButton.className = "danger-button chunk-delete-button";
      chunkDeleteButton.textContent = "删除 chunk";
      chunkDeleteButton.addEventListener("click", () => deleteDocumentChunk(documentItem.document_id, chunk.chunk_id, chunkDeleteButton));

      chunkHeader.append(chunkTitle, chunkDeleteButton);

      const text = document.createElement("pre");
      text.className = "chunk-text";
      text.textContent = chunk.text;

      const chunkMeta = document.createElement("dl");
      chunkMeta.className = "chunk-meta";
      appendMetaFields(chunkMeta, [
        ["chunk_id", chunk.chunk_id],
        ["chunk_hash", chunk.chunk_hash],
        ["text_length", chunk.text_length],
        ["created_at", chunk.created_at],
        ["updated_at", chunk.updated_at],
      ]);

      chunkCard.append(chunkHeader, text, chunkMeta);
      chunksWrapper.append(chunkCard);
    }

    card.append(header, meta, chunksWrapper);
    documentsList.append(card);
  }
}

async function loadDocuments() {
  if (!hasDocumentsUi) return;

  documentsStatus.textContent = "正在加载 documents...";

  try {
    const response = await fetch("/api/admin/rag/documents");
    const data = await response.json();
    renderDocuments(data.documents);
  } catch (error) {
    documentsList.replaceChildren();
    documentsStatus.textContent = "documents 加载失败，请点击刷新重试。";
  }
}

async function deleteDocument(documentId, button) {
  if (!hasDocumentsUi) return;

  const confirmed = window.confirm("确认删除整个 document 及其所有 active chunks 吗？");
  if (!confirmed) return;

  button.disabled = true;
  documentsStatus.textContent = "正在删除 document...";

  try {
    const response = await fetch(`/api/admin/rag/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "删除 document 失败，请刷新后重试。");
    }

    documentsStatus.textContent = data.message || "document 已删除。";
    await loadDocuments();
  } catch (error) {
    documentsStatus.textContent = error.message || "删除 document 失败，请刷新后重试。";
    button.disabled = false;
  }
}

async function deleteDocumentChunk(documentId, chunkId, button) {
  if (!hasDocumentsUi) return;

  const confirmed = window.confirm("确认删除这个 document 下的 chunk 吗？");
  if (!confirmed) return;

  button.disabled = true;
  documentsStatus.textContent = "正在删除 chunk...";

  try {
    const response = await fetch(
      `/api/admin/rag/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
      { method: "DELETE" }
    );
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "删除 chunk 失败，请刷新后重试。");
    }

    documentsStatus.textContent = data.message || "chunk 已删除。";
    await loadDocuments();
  } catch (error) {
    documentsStatus.textContent = error.message || "删除 chunk 失败，请刷新后重试。";
    button.disabled = false;
  }
}

if (hasUploadUi) {
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = uploadInput.files?.[0];
    if (!file) return;

    uploadStatus.textContent = "正在上传并入库...";

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/knowledge/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      uploadStatus.textContent = data.message;
      uploadForm.reset();
      await loadDocuments();
    } catch (error) {
      uploadStatus.textContent = "上传失败，请检查文件后重试。";
    }
  });
}

if (hasDocumentsUi) {
  refreshDocumentsButton.addEventListener("click", loadDocuments);
  loadDocuments();
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
        appendMetaFields(meta, [
          ["score", result.score],
          ["document_id", result.metadata?.document_id ?? "-"],
          ["chunk_id", result.metadata?.chunk_id ?? result.id],
          ["chunk_hash", result.metadata?.chunk_hash ?? "-"],
          ["chunk_index", result.metadata?.chunk_index ?? "-"],
          ["source", result.metadata?.source ?? "-"],
          ["created_at", result.metadata?.created_at ?? "-"],
          ["operator", result.metadata?.operator ?? "-"],
        ]);

        card.append(text, meta);
        retrieveResults.append(card);
      }
    } catch (error) {
      retrieveStatus.textContent = "检索失败，请检查 query / top_k 后重试。";
    }
  });
}
