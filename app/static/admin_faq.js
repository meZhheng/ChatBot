const faqForm = document.querySelector("#faqForm");
const faqIdInput = document.querySelector("#faqIdInput");
const faqQuestionInput = document.querySelector("#faqQuestionInput");
const faqAnswerInput = document.querySelector("#faqAnswerInput");
const faqCategoryInput = document.querySelector("#faqCategoryInput");
const faqTagsInput = document.querySelector("#faqTagsInput");
const faqPriorityInput = document.querySelector("#faqPriorityInput");
const faqStatusInput = document.querySelector("#faqStatusInput");
const faqVariantsInput = document.querySelector("#faqVariantsInput");
const faqSubmitButton = document.querySelector("#faqSubmitButton");
const faqResetButton = document.querySelector("#faqResetButton");
const faqFormStatus = document.querySelector("#faqFormStatus");
const faqFilterForm = document.querySelector("#faqFilterForm");
const faqSearchInput = document.querySelector("#faqSearchInput");
const faqFilterCategoryInput = document.querySelector("#faqFilterCategoryInput");
const faqFilterStatusInput = document.querySelector("#faqFilterStatusInput");
const refreshFaqButton = document.querySelector("#refreshFaqButton");
const faqListStatus = document.querySelector("#faqListStatus");
const faqList = document.querySelector("#faqList");
const faqRetrieveForm = document.querySelector("#faqRetrieveForm");
const faqRetrieveQueryInput = document.querySelector("#faqRetrieveQueryInput");
const faqRetrieveTopKInput = document.querySelector("#faqRetrieveTopKInput");
const faqRetrieveCategoryInput = document.querySelector("#faqRetrieveCategoryInput");
const faqRetrieveStatus = document.querySelector("#faqRetrieveStatus");
const faqRetrieveResults = document.querySelector("#faqRetrieveResults");

function splitTags(value) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function splitVariants(value) {
  return value
    .split("\n")
    .map((question) => question.trim())
    .filter(Boolean);
}

function joinTags(tags) {
  return (tags || []).join(", ");
}

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

function resetFaqForm() {
  faqIdInput.value = "";
  faqQuestionInput.value = "";
  faqAnswerInput.value = "";
  faqCategoryInput.value = "default";
  faqTagsInput.value = "";
  faqPriorityInput.value = "0";
  faqStatusInput.value = "active";
  faqVariantsInput.value = "";
  faqSubmitButton.textContent = "保存 FAQ";
  faqFormStatus.textContent = "填写标准问和答案后即可保存。";
}

async function loadFaqItems() {
  faqListStatus.textContent = "正在加载 FAQ...";
  faqList.replaceChildren();

  const params = new URLSearchParams();
  const query = faqSearchInput.value.trim();
  const category = faqFilterCategoryInput.value.trim();
  const status = faqFilterStatusInput.value;
  if (query) params.set("query", query);
  if (category) params.set("category", category);
  if (status !== undefined) params.set("status", status);

  try {
    const response = await fetch(`/api/admin/faq/items?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "FAQ 加载失败。");
    }
    renderFaqItems(data.items || []);
  } catch (error) {
    faqListStatus.textContent = error.message || "FAQ 加载失败，请点击刷新重试。";
  }
}

function renderFaqItems(items) {
  faqList.replaceChildren();
  if (!items.length) {
    faqListStatus.textContent = "当前没有 FAQ。";
    return;
  }

  faqListStatus.textContent = `共 ${items.length} 条 FAQ`;
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "document-card faq-card";

    const header = document.createElement("div");
    header.className = "document-card-header";

    const titleGroup = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = item.question;
    const subtitle = document.createElement("p");
    subtitle.textContent = `${item.status} · ${item.category} · ${item.variant_count} 个扩展问 · hit ${item.hit_count}`;
    titleGroup.append(title, subtitle);

    const actions = document.createElement("div");
    actions.className = "faq-card-actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "ghost-button";
    editButton.textContent = "编辑";
    editButton.addEventListener("click", () => editFaqItem(item.faq_id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger-button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteFaqItem(item.faq_id, deleteButton));
    actions.append(editButton, deleteButton);

    header.append(titleGroup, actions);

    const answer = document.createElement("pre");
    answer.className = "chunk-text faq-answer";
    answer.textContent = item.answer;

    const meta = document.createElement("dl");
    meta.className = "document-meta";
    appendMetaFields(meta, [
      ["faq_id", item.faq_id],
      ["tags", joinTags(item.tags)],
      ["priority", item.priority],
      ["created_at", item.created_at],
      ["updated_at", item.updated_at],
      ["operator", item.operator],
    ]);

    card.append(header, answer, meta);
    faqList.append(card);
  }
}

async function editFaqItem(faqId) {
  faqFormStatus.textContent = "正在加载 FAQ 详情...";
  try {
    const response = await fetch(`/api/admin/faq/items/${encodeURIComponent(faqId)}`);
    const item = await response.json();
    if (!response.ok) {
      throw new Error(item.detail || "FAQ 详情加载失败。");
    }
    faqIdInput.value = item.faq_id;
    faqQuestionInput.value = item.question;
    faqAnswerInput.value = item.answer;
    faqCategoryInput.value = item.category;
    faqTagsInput.value = joinTags(item.tags);
    faqPriorityInput.value = String(item.priority);
    faqStatusInput.value = item.status === "deleted" ? "disabled" : item.status;
    faqVariantsInput.value = (item.variants || []).map((variant) => variant.question).join("\n");
    faqSubmitButton.textContent = "更新 FAQ";
    faqFormStatus.textContent = "已载入 FAQ，可编辑后保存。";
    faqQuestionInput.focus();
  } catch (error) {
    faqFormStatus.textContent = error.message || "FAQ 详情加载失败。";
  }
}

async function deleteFaqItem(faqId, button) {
  const confirmed = window.confirm("确认删除这条 FAQ 及其扩展问索引吗？");
  if (!confirmed) return;

  button.disabled = true;
  faqListStatus.textContent = "正在删除 FAQ...";
  try {
    const response = await fetch(`/api/admin/faq/items/${encodeURIComponent(faqId)}`, {
      method: "DELETE",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "FAQ 删除失败。");
    }
    faqListStatus.textContent = data.message || "FAQ 已删除。";
    if (faqIdInput.value === faqId) resetFaqForm();
    await loadFaqItems();
  } catch (error) {
    faqListStatus.textContent = error.message || "FAQ 删除失败。";
    button.disabled = false;
  }
}

async function saveFaqItem(event) {
  event.preventDefault();
  const faqId = faqIdInput.value.trim();
  const payload = {
    question: faqQuestionInput.value.trim(),
    answer: faqAnswerInput.value.trim(),
    category: faqCategoryInput.value.trim() || "default",
    tags: splitTags(faqTagsInput.value),
    priority: Number(faqPriorityInput.value || 0),
    status: faqStatusInput.value,
    variants: splitVariants(faqVariantsInput.value),
  };
  if (!payload.question || !payload.answer) return;

  faqSubmitButton.disabled = true;
  faqFormStatus.textContent = faqId ? "正在更新 FAQ..." : "正在创建 FAQ...";

  try {
    const response = await fetch(faqId ? `/api/admin/faq/items/${encodeURIComponent(faqId)}` : "/api/admin/faq/items", {
      method: faqId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "FAQ 保存失败。");
    }
    faqFormStatus.textContent = faqId ? "FAQ 已更新。" : "FAQ 已创建。";
    resetFaqForm();
    await loadFaqItems();
  } catch (error) {
    faqFormStatus.textContent = error.message || "FAQ 保存失败。";
  } finally {
    faqSubmitButton.disabled = false;
  }
}

function renderRetrieveResults(results) {
  faqRetrieveResults.replaceChildren();
  if (!results.length) {
    const empty = document.createElement("p");
    empty.className = "retrieve-empty";
    empty.textContent = "未检索到 FAQ。";
    faqRetrieveResults.append(empty);
    return;
  }

  for (const result of results) {
    const card = document.createElement("article");
    card.className = "retrieve-card faq-retrieve-card";

    const question = document.createElement("h3");
    question.textContent = result.question;

    const answer = document.createElement("pre");
    answer.className = "retrieve-text";
    answer.textContent = result.answer;

    const meta = document.createElement("dl");
    meta.className = "retrieve-meta";
    appendMetaFields(meta, [
      ["score", result.score],
      ["sources", (result.sources || []).join(" + ")],
      ["matched", `${result.matched_doc_type}: ${result.matched_question}`],
      ["bm25", result.bm25_score],
      ["vector", result.vector_score],
      ["category", result.category],
      ["tags", joinTags(result.tags)],
      ["hit_count", result.hit_count],
    ]);

    card.append(question, answer, meta);
    faqRetrieveResults.append(card);
  }
}

async function runFaqRetrieve(event) {
  event.preventDefault();
  const query = faqRetrieveQueryInput.value.trim();
  const topK = Number(faqRetrieveTopKInput.value);
  const category = faqRetrieveCategoryInput.value.trim();
  if (!query || Number.isNaN(topK) || topK < 1) return;

  faqRetrieveStatus.textContent = "正在执行 FAQ 混合检索...";
  faqRetrieveResults.replaceChildren();

  try {
    const response = await fetch("/api/admin/faq/retrieve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: topK, category: category || null }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "FAQ 检索失败。");
    }
    faqRetrieveStatus.textContent = `query: ${data.query} · top_k: ${data.top_k} · results: ${data.results.length}`;
    renderRetrieveResults(data.results || []);
    await loadFaqItems();
  } catch (error) {
    faqRetrieveStatus.textContent = error.message || "FAQ 检索失败，请检查 query / top_k 后重试。";
  }
}

if (faqForm) {
  faqForm.addEventListener("submit", saveFaqItem);
  faqResetButton.addEventListener("click", resetFaqForm);
}

if (faqFilterForm) {
  faqFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadFaqItems();
  });
}

if (refreshFaqButton) {
  refreshFaqButton.addEventListener("click", loadFaqItems);
  loadFaqItems();
}

if (faqRetrieveForm) {
  faqRetrieveForm.addEventListener("submit", runFaqRetrieve);
}
