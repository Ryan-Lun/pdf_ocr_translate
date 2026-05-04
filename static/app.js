const state = {
  pages: [],
  selected: null,
  dragging: null,
  resizing: null,
  previewMode: "debug",
  selectedBoxes: new Set(),
  selecting: null,
  lastCtrlKey: false,
  activePageIdx: 0,
  clipboard: {
    boxes: [],
    sourcePageIdx: null,
    pasteCount: 0,
  },
  zoom: 1,
  pdfUrl: null,
  pdfDoc: null,
  downloadName: null,
};

const historyState = {
  past: [],
  future: [],
  limit: 200,
  isRestoring: false,
};

let controlsBound = false;

const statusEl = document.getElementById("status");
const fontSizeEl = document.getElementById("fontSize");
const fontSizeNumberEl = document.getElementById("fontSizeNumber");
const fontColorEl = document.getElementById("fontColor");
const deleteBtn = document.getElementById("deleteBox");
const addBoxBtn = document.getElementById("addBox");
const copyBoxBtn = document.getElementById("copyBox");
const saveBtn = document.getElementById("saveBtn");
const downloadBtn = document.getElementById("downloadBtn");
const batchTranslateBtn = document.getElementById("batchTranslateBtn");
const batchRestoreBtn = document.getElementById("batchRestoreBtn");
const prevPageBtn = document.getElementById("prevPage");
const nextPageBtn = document.getElementById("nextPage");
const pageSelectEl = document.getElementById("pageSelect");
const zoomRangeEl = document.getElementById("zoomRange");
const zoomNumberEl = document.getElementById("zoomNumber");
const pagesEl = document.getElementById("pages");
const thumbsEl = document.getElementById("thumbs");
const editedLink = document.getElementById("editedPdfLink");
const previewEl = document.getElementById("pdfPreview");
const previewDebugBtn = document.getElementById("previewDebug");
const previewEditedBtn = document.getElementById("previewEdited");
const debugLinkEl = document.querySelector(".topbar-actions a[href*='overlay_debug.pdf']");
const glossaryCnEl = document.getElementById("glossaryCn");
const glossaryEnEl = document.getElementById("glossaryEn");
const addGlossaryBtn = document.getElementById("addGlossaryBtn");
const glossaryListEl = document.getElementById("glossaryList");
const systemPromptEl = document.getElementById("systemPrompt");
const savePromptBtn = document.getElementById("savePromptBtn");
const glossaryPromptBtn = document.getElementById("glossaryPromptBtn");
const glossaryPromptModal = document.getElementById("glossaryPromptModal");
const closeGlossaryPrompt = document.getElementById("closeGlossaryPrompt");

// if (window.pdfjsLib) {
//   window.pdfjsLib.GlobalWorkerOptions.workerSrc =
//     "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.js";
// }
if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc =
    "/static/pdfjs/pdf.worker.min.js";
}

document.addEventListener("dragstart", (event) => {
  if (event.target.closest(".page-wrap, .overlay, .text-box, .text")) {
    event.preventDefault();
  }
});

function setStatus(message) {
  if (statusEl) {
    statusEl.textContent = message;
  }
}

let glossaryEntries = [];
let currentJobId = null;

function renderGlossary() {
  if (!glossaryListEl) return;
  glossaryListEl.innerHTML = "";
  if (!glossaryEntries.length) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "尚未加入詞彙對照。";
    glossaryListEl.appendChild(empty);
    return;
  }
  glossaryEntries.forEach((entry, index) => {
    const row = document.createElement("div");
    row.className = "glossary-item";
    const cn = document.createElement("span");
    cn.textContent = entry.cn;
    const en = document.createElement("span");
    en.textContent = entry.en;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost";
    del.textContent = "刪除";
    del.addEventListener("click", () => {
      glossaryEntries.splice(index, 1);
      renderGlossary();
      saveGlossary();
    });
    row.appendChild(cn);
    row.appendChild(en);
    row.appendChild(del);
    glossaryListEl.appendChild(row);
  });
}

async function loadGlossary() {
  try {
    const res = await fetch(`/api/glossary`);
    if (!res.ok) return;
    const payload = await res.json();
    glossaryEntries = Array.isArray(payload.glossary) ? payload.glossary : [];
    renderGlossary();
  } catch (error) {
    // ignore
  }
}

async function saveGlossary() {
  try {
    await fetch(`/api/glossary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ glossary: glossaryEntries }),
    });
  } catch (error) {
    // ignore
  }
}

async function saveSystemPrompt(jobId) {
  if (!jobId) return;
  const prompt = systemPromptEl?.value ?? "";
  try {
    await fetch(`/api/job/${jobId}/system-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: prompt }),
    });
    setStatus("已儲存提示詞。");
  } catch (error) {
    setStatus("儲存提示詞失敗。");
  }
}

function addGlossaryEntry() {
  const cn = glossaryCnEl?.value?.trim();
  const en = glossaryEnEl?.value?.trim();
  if (!cn || !en) {
    setStatus("請輸入中文與英文詞彙。");
    return;
  }
  glossaryEntries.unshift({ cn, en });
  glossaryCnEl.value = "";
  glossaryEnEl.value = "";
  renderGlossary();
  saveGlossary();
}

function openGlossaryModal() {
  if (!glossaryPromptModal) return;
  glossaryPromptModal.hidden = false;
}

function closeGlossaryModal() {
  if (!glossaryPromptModal) return;
  glossaryPromptModal.hidden = true;
}

function setBatchButtonState(status) {
  if (!batchTranslateBtn) return;
  if (status === "running" || status === "queued") {
    batchTranslateBtn.disabled = true;
    batchTranslateBtn.textContent = "Batch 翻譯中...";
  } else {
    batchTranslateBtn.disabled = false;
    batchTranslateBtn.textContent = "Batch 翻譯";
  }
}

function renderBatchStatus(status) {
  if (!status || !statusEl) return;
  const label = status.status || "unknown";
  if (label === "completed") {
    setStatus("Batch 翻譯完成，已更新編輯內容。");
  } else if (label === "running" || label === "queued") {
    setStatus("Batch 翻譯進行中...");
  } else if (label === "failed") {
    setStatus(`Batch 翻譯失敗：${status.error || "unknown error"}`);
  } else {
    setStatus("Ready.");
  }
  setBatchButtonState(label);
}

function boxKey(pageIdx, boxIdx) {
  return `${pageIdx}:${boxIdx}`;
}

function getSelectedBoxes() {
  const items = [];
  state.selectedBoxes.forEach((key) => {
    const [pageIdx, boxIdx] = key.split(":").map((value) => Number.parseInt(value, 10));
    const page = state.pages[pageIdx];
    const box = page?.boxes[boxIdx];
    if (!page || !box || box.deleted) return;
    items.push({ pageIdx, boxIdx, page, box });
  });
  return items;
}

function applySelectionClasses() {
  state.pages.forEach((page, pageIdx) => {
    page.boxes.forEach((box, boxIdx) => {
      if (!box.element) return;
      box.element.classList.toggle("selected", state.selectedBoxes.has(boxKey(pageIdx, boxIdx)));
    });
  });
}

function syncInspectorFromBox(box) {
  if (!box) return;
  const sizeValue = Math.round(box.fontSize).toString();
  if (fontSizeEl) fontSizeEl.value = sizeValue;
  if (fontSizeNumberEl) fontSizeNumberEl.value = sizeValue;
  if (fontColorEl) fontColorEl.value = box.color;
}

function clearSelection() {
  state.selected = null;
  state.selectedBoxes.clear();
  applySelectionClasses();
}

function cloneBoxData(box) {
  return {
    id: box.id,
    bbox: { ...box.bbox },
    text: box.text,
    fontSize: box.fontSize,
    color: box.color,
    noClip: !!box.noClip,
    autoGenerated: !!box.autoGenerated,
    tmSourceText: box.tmSourceText || "",
    tmSourceNormalized: box.tmSourceNormalized || "",
    tmTargetLang: box.tmTargetLang || "",
    tmDocumentMode: box.tmDocumentMode || "",
    deleted: !!box.deleted,
  };
}

function findBox(pageIdx, boxId) {
  return state.pages[pageIdx]?.boxes.find((box) => box.id === boxId) || null;
}

function applyBoxData(pageIdx, boxId, data) {
  const page = state.pages[pageIdx];
  const box = findBox(pageIdx, boxId);
  if (!page || !box) return;
  box.bbox = { ...data.bbox };
  box.text = data.text;
  box.fontSize = data.fontSize;
  box.color = data.color;
  box.noClip = !!data.noClip;
  box.autoGenerated = !!data.autoGenerated;
  box.tmSourceText = data.tmSourceText || "";
  box.tmSourceNormalized = data.tmSourceNormalized || "";
  box.tmTargetLang = data.tmTargetLang || "";
  box.tmDocumentMode = data.tmDocumentMode || "";
  box.deleted = !!data.deleted;
  updateBoxElement(page, box);
}

function addBoxToPage(pageIdx, data) {
  const page = state.pages[pageIdx];
  if (!page) return;
  const newBox = {
    id: data.id,
    bbox: { ...data.bbox },
    text: data.text,
    fontSize: data.fontSize,
    color: data.color,
    noClip: !!data.noClip,
    autoGenerated: !!data.autoGenerated,
    tmSourceText: data.tmSourceText || "",
    tmSourceNormalized: data.tmSourceNormalized || "",
    tmTargetLang: data.tmTargetLang || "",
    tmDocumentMode: data.tmDocumentMode || "",
    deleted: !!data.deleted,
    element: null,
  };
  page.boxes.push(newBox);
  const newIdx = page.boxes.length - 1;
  createBoxElement(pageIdx, newIdx);
  updateBoxElement(page, newBox);
}

function removeBoxFromPage(pageIdx, boxId) {
  const page = state.pages[pageIdx];
  if (!page) return;
  const idx = page.boxes.findIndex((box) => box.id === boxId);
  if (idx === -1) return;
  const box = page.boxes[idx];
  if (box.element) {
    box.element.remove();
  }
  page.boxes.splice(idx, 1);
}

function pushAction(action) {
  if (historyState.isRestoring) return;
  historyState.past.push(action);
  historyState.future = [];
  if (historyState.past.length > historyState.limit) {
    historyState.past.shift();
  }
}

function applyAction(action) {
  switch (action.type) {
    case "batch":
      action.actions.forEach(applyAction);
      break;
    case "update_boxes":
      action.updates.forEach((update) => {
        applyBoxData(update.pageIdx, update.boxId, update.after);
      });
      break;
    case "add_boxes":
      action.boxes.forEach((entry) => addBoxToPage(entry.pageIdx, entry.box));
      break;
    case "delete_boxes":
      action.boxes.forEach((entry) => {
        applyBoxData(entry.pageIdx, entry.box.id, { ...entry.box, deleted: true });
      });
      break;
    default:
      break;
  }
}

function revertAction(action) {
  switch (action.type) {
    case "batch":
      [...action.actions].reverse().forEach(revertAction);
      break;
    case "update_boxes":
      action.updates.forEach((update) => {
        applyBoxData(update.pageIdx, update.boxId, update.before);
      });
      break;
    case "add_boxes":
      action.boxes.forEach((entry) => removeBoxFromPage(entry.pageIdx, entry.box.id));
      break;
    case "delete_boxes":
      action.boxes.forEach((entry) => {
        applyBoxData(entry.pageIdx, entry.box.id, entry.box);
      });
      break;
    default:
      break;
  }
}

function resetHistory() {
  historyState.past = [];
  historyState.future = [];
}

function undoHistory() {
  const action = historyState.past.pop();
  if (!action) return;
  historyState.isRestoring = true;
  revertAction(action);
  historyState.future.push(action);
  historyState.isRestoring = false;
  clearSelection();
  setStatus("Undo.");
}

function redoHistory() {
  const action = historyState.future.pop();
  if (!action) return;
  historyState.isRestoring = true;
  applyAction(action);
  historyState.past.push(action);
  historyState.isRestoring = false;
  clearSelection();
  setStatus("Redo.");
}

function setActivePage(pageIdx, options = {}) {
  if (!Number.isFinite(pageIdx)) return;
  const { scroll = true } = options;
  const maxIdx = Math.max(0, state.pages.length - 1);
  state.activePageIdx = Math.max(0, Math.min(pageIdx, maxIdx));
  syncPageSelector();
  updatePageNavButtons();
  state.pages.forEach((page, idx) => {
    if (page.thumbElement) {
      page.thumbElement.classList.toggle("is-active", idx === state.activePageIdx);
    }
  });
  if (scroll) {
    const page = state.pages[state.activePageIdx];
    if (page?.element) {
      page.element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
}

function syncPageSelector() {
  if (!pageSelectEl) return;
  const current = state.activePageIdx ?? 0;
  if (Number.isFinite(current)) {
    pageSelectEl.value = String(current);
  }
}

function updatePageNavButtons() {
  if (prevPageBtn) {
    prevPageBtn.disabled = state.activePageIdx <= 0;
  }
  if (nextPageBtn) {
    nextPageBtn.disabled = state.activePageIdx >= state.pages.length - 1;
  }
}

function applyZoomToPage(page) {
  if (!page?.image) return;
  if (state.pdfDoc) {
    renderPdfPage(state.pages.indexOf(page));
    return;
  }
  const zoom = state.zoom || 1;
  const img = page.image;
  if (img.naturalWidth) {
    img.style.width = `${img.naturalWidth * zoom}px`;
  } else {
    img.style.width = `${zoom * 100}%`;
  }
  updatePageLayout(page);
}

function applyZoom(zoom) {
  const clamped = Math.max(0.25, Math.min(2, zoom));
  state.zoom = clamped;
  if (state.pdfDoc) {
    renderAllPdfPages();
    renderThumbnails();
  } else {
    state.pages.forEach((page) => applyZoomToPage(page));
    renderThumbnails();
  }
}

function setZoomPercent(percent) {
  const value = Math.max(25, Math.min(200, Math.round(percent)));
  if (zoomRangeEl) zoomRangeEl.value = String(value);
  if (zoomNumberEl) zoomNumberEl.value = String(value);
  applyZoom(value / 100);
}

function setSelection(pageIdx, boxIdx, additive = false) {
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (!page || !box || box.deleted) {
    if (!additive) {
      clearSelection();
    }
    return;
  }
  setActivePage(pageIdx, { scroll: false });
  const key = boxKey(pageIdx, boxIdx);
  if (!additive) {
    state.selectedBoxes.clear();
  }
  if (additive && state.selectedBoxes.has(key)) {
    state.selectedBoxes.delete(key);
  } else {
    state.selectedBoxes.add(key);
  }

  const selectedList = getSelectedBoxes();
  if (!selectedList.length) {
    state.selected = null;
    applySelectionClasses();
    return;
  }

  const primary = selectedList.find((item) => item.pageIdx === pageIdx && item.boxIdx === boxIdx) || selectedList[0];
  state.selected = { pageIdx: primary.pageIdx, boxIdx: primary.boxIdx };
  applySelectionClasses();
  syncInspectorFromBox(primary.box);
}

function boxesIntersect(a, b) {
  return a.x <= b.x + b.w && a.x + a.w >= b.x && a.y <= b.y + b.h && a.y + a.h >= b.y;
}

function deleteSelectedBoxes() {
  const selected = getSelectedBoxes();
  if (!selected.length) return;
  const action = {
    type: "delete_boxes",
    boxes: selected.map(({ pageIdx, box }) => ({
      pageIdx,
      box: cloneBoxData(box),
    })),
  };
  selected.forEach(({ page, box }) => {
    box.deleted = true;
    updateBoxElement(page, box);
  });
  clearSelection();
  setStatus("Box deleted.");
  pushAction(action);
}

function copySelectedBoxes() {
  const selected = getSelectedBoxes();
  if (!selected.length) {
    setStatus("No boxes selected.");
    return;
  }
  state.clipboard = {
    boxes: selected.map(({ box }) => ({
      bbox: { ...box.bbox },
      text: box.text,
      fontSize: box.fontSize,
      color: box.color,
      noClip: !!box.noClip,
    })),
    sourcePageIdx: selected.length === 1 ? selected[0].pageIdx : null,
    pasteCount: 0,
  };
  setStatus(`Copied ${selected.length} box${selected.length > 1 ? "es" : ""}.`);
}

function pasteClipboardBoxes() {
  const items = state.clipboard?.boxes || [];
  if (!items.length) {
    setStatus("Clipboard is empty.");
    return;
  }
  const targetPageIdx = Number.isFinite(state.activePageIdx)
    ? state.activePageIdx
    : state.selected?.pageIdx ?? 0;
  const targetPage = state.pages[targetPageIdx];
  if (!targetPage) return;

  const samePage = state.clipboard.sourcePageIdx === targetPageIdx;
  const pasteOffset = (state.clipboard.pasteCount + 1) * 12;
  const dx = samePage ? pasteOffset : 0;
  const dy = samePage ? pasteOffset : 0;

  const baseNextId = targetPage.boxes.length
    ? Math.max(...targetPage.boxes.map((b) => Number(b.id) || 0)) + 1
    : 0;
  let nextId = baseNextId;

  const newSelections = [];
  const addedBoxes = [];
  items.forEach((item) => {
    const bbox = {
      x: item.bbox.x + dx,
      y: item.bbox.y + dy,
      w: item.bbox.w,
      h: item.bbox.h,
    };

    if (targetPage.imageSize && targetPage.imageSize.length === 2) {
      const maxX = Math.max(0, targetPage.imageSize[0] - bbox.w);
      const maxY = Math.max(0, targetPage.imageSize[1] - bbox.h);
      bbox.x = Math.min(Math.max(0, bbox.x), maxX);
      bbox.y = Math.min(Math.max(0, bbox.y), maxY);
    }

    const newBox = {
      id: nextId++,
      bbox,
      text: item.text,
      fontSize: item.fontSize,
      color: item.color,
      noClip: !!item.noClip,
      autoGenerated: false,
      deleted: false,
      element: null,
    };

    targetPage.boxes.push(newBox);
    const newIndex = targetPage.boxes.length - 1;
    createBoxElement(targetPageIdx, newIndex);
    newSelections.push({ pageIdx: targetPageIdx, boxIdx: newIndex });
    addedBoxes.push({ pageIdx: targetPageIdx, box: cloneBoxData(newBox) });
  });

  state.clipboard.pasteCount += 1;
  clearSelection();
  newSelections.forEach(({ pageIdx, boxIdx }, idx) => {
    state.selectedBoxes.add(boxKey(pageIdx, boxIdx));
    if (idx === 0) {
      state.selected = { pageIdx, boxIdx };
      syncInspectorFromBox(state.pages[pageIdx]?.boxes[boxIdx]);
      setActivePage(pageIdx);
    }
  });
  applySelectionClasses();
  setStatus(`Pasted ${items.length} box${items.length > 1 ? "es" : ""}.`);
  if (addedBoxes.length) {
    pushAction({ type: "add_boxes", boxes: addedBoxes });
  }
}

function duplicateSelectedBoxes() {
  const selected = getSelectedBoxes();
  if (!selected.length) return;

  const targetPageIdx = Number.isFinite(state.activePageIdx)
    ? state.activePageIdx
    : state.selected?.pageIdx ?? 0;
  const targetPage = state.pages[targetPageIdx];
  if (!targetPage) return;

  const nextIdByPage = new Map();
  const offsetCountByPage = new Map();
  const newSelections = [];
  const addedBoxes = [];

  selected.forEach(({ pageIdx, page, box }) => {
    const sourcePageIdx = pageIdx;
    const nextId = nextIdByPage.has(targetPageIdx)
      ? nextIdByPage.get(targetPageIdx)
      : targetPage.boxes.length
      ? Math.max(...targetPage.boxes.map((b) => Number(b.id) || 0)) + 1
      : 0;

    const offsetCount = offsetCountByPage.get(targetPageIdx) ?? 0;
    const offset = sourcePageIdx === targetPageIdx ? 12 * (offsetCount + 1) : 0;

    const bbox = {
      x: box.bbox.x + offset,
      y: box.bbox.y + offset,
      w: box.bbox.w,
      h: box.bbox.h,
    };

    if (targetPage.imageSize && targetPage.imageSize.length === 2) {
      const maxX = Math.max(0, targetPage.imageSize[0] - bbox.w);
      const maxY = Math.max(0, targetPage.imageSize[1] - bbox.h);
      bbox.x = Math.min(Math.max(0, bbox.x), maxX);
      bbox.y = Math.min(Math.max(0, bbox.y), maxY);
    }

      const newBox = {
        id: nextId,
        bbox,
        text: box.text,
        fontSize: box.fontSize,
        color: box.color,
        noClip: !!box.noClip,
        autoGenerated: false,
        deleted: false,
        element: null,
      };

      targetPage.boxes.push(newBox);
      nextIdByPage.set(targetPageIdx, nextId + 1);
      offsetCountByPage.set(targetPageIdx, offsetCount + 1);

      const newIndex = targetPage.boxes.length - 1;
      createBoxElement(targetPageIdx, newIndex);
      newSelections.push({ pageIdx: targetPageIdx, boxIdx: newIndex });
      addedBoxes.push({ pageIdx: targetPageIdx, box: cloneBoxData(newBox) });
    });

  clearSelection();
  newSelections.forEach(({ pageIdx, boxIdx }, idx) => {
    state.selectedBoxes.add(boxKey(pageIdx, boxIdx));
    if (idx === 0) {
      state.selected = { pageIdx, boxIdx };
      syncInspectorFromBox(state.pages[pageIdx]?.boxes[boxIdx]);
      setActivePage(pageIdx);
    }
  });
    applySelectionClasses();
    setStatus("Box duplicated.");
    if (addedBoxes.length) {
      pushAction({ type: "add_boxes", boxes: addedBoxes });
    }
  }

function updateEditedLink(url) {
  if (!editedLink) return;
  if (url) {
    editedLink.href = url;
    editedLink.style.display = "inline-flex";
    if (previewEditedBtn) {
      previewEditedBtn.disabled = false;
    }
    if (state.previewMode === "edited") {
      setPreviewMode("edited", url);
    }
  }
}

function setPreviewMode(mode, editedUrl) {
  if (!previewEl) return;
  const debugUrl = debugLinkEl?.href || previewEl.dataset.debugUrl || previewEl.getAttribute("data") || "";
  if (mode === "edited" && editedUrl) {
    previewEl.setAttribute("data", editedUrl);
    previewEditedBtn?.classList.add("is-active");
    previewDebugBtn?.classList.remove("is-active");
    state.previewMode = "edited";
  } else {
    previewEl.setAttribute("data", debugUrl);
    previewDebugBtn?.classList.add("is-active");
    previewEditedBtn?.classList.remove("is-active");
    state.previewMode = "debug";
  }
}

function withDownloadParam(url) {
  if (!url) return url;
  return url.includes("?") ? `${url}&download=1` : `${url}?download=1`;
}

function triggerDownload(url, filename) {
  if (!url) return;
  const anchor = document.createElement("a");
  anchor.href = withDownloadParam(url);
  anchor.download = filename || "edited.pdf";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

function polyToBbox(poly) {
  const xs = poly.map((p) => p[0]);
  const ys = poly.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  return {
    x: minX,
    y: minY,
    w: Math.max(1, maxX - minX),
    h: Math.max(1, maxY - minY),
  };
}

function buildState(data) {
  state.pdfUrl = data.pdf_url || null;
  state.downloadName = data.download_name || "edited.pdf";
  state.pages = data.pages.map((page) => {
    const boxes = page.rec_polys.map((poly, index) => {
      const bbox = polyToBbox(poly);
      const text = page.edit_texts[index] ?? page.rec_texts[index] ?? "";
      const baseSize = 25;
      const fontSize = Number(page.font_sizes?.[index]);
      const color = page.colors?.[index] ?? "#0000ff";
      const id = page.box_ids?.[index] ?? index;
      const noClip = Boolean(page.no_clips?.[index]);
      const autoGenerated = Boolean(page.auto_generated_flags?.[index]);
      const tmSourceText = page.tm_source_texts?.[index] ?? "";
      const tmSourceNormalized = page.tm_source_normalizeds?.[index] ?? "";
      const tmTargetLang = page.tm_target_langs?.[index] ?? "";
      const tmDocumentMode = page.tm_document_modes?.[index] ?? "";
      return {
        id,
        bbox,
        text,
        fontSize: fontSize > 0 ? fontSize : baseSize,
        color,
        noClip,
        autoGenerated,
        tmSourceText,
        tmSourceNormalized,
        tmTargetLang,
        tmDocumentMode,
        deleted: false,
        element: null,
      };
    });
    return {
      pageIndex: page.page_index_0based,
      imageUrl: page.image_url,
      imageSize: page.image_size_px,
      boxes,
      element: null,
      overlay: null,
      image: null,
      scale: 1,
    };
  });
  state.activePageIdx = 0;
  state.zoom = 0.5;
  if (zoomRangeEl) zoomRangeEl.value = "50";
  if (zoomNumberEl) zoomNumberEl.value = "50";
  if (pageSelectEl) {
    pageSelectEl.innerHTML = "";
    state.pages.forEach((page, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${page.pageIndex + 1}`;
      pageSelectEl.appendChild(option);
    });
  }
  syncPageSelector();
  updatePageNavButtons();
}

function updateBoxElement(page, box) {
  if (!box.element) return;
  const scale = page.scale || 1;
  const left = box.bbox.x * scale;
  const top = box.bbox.y * scale;
  const width = box.bbox.w * scale;
  const baseHeight = box.bbox.h * scale;
  const textEl = box.element.querySelector(".text");
  const expanded = !!box.noClip || !!box._isExpanded;
  let height = baseHeight;

  box.element.style.left = `${left}px`;
  box.element.style.top = `${top}px`;
  box.element.style.width = `${width}px`;
  if (textEl) {
    textEl.style.fontSize = `${box.fontSize * scale}px`;
  }
  if (expanded && textEl) {
    const previousHeight = textEl.style.height;
    textEl.style.height = "auto";
    const boxStyle = window.getComputedStyle(box.element);
    const paddingY = Number.parseFloat(boxStyle.paddingTop || "0") + Number.parseFloat(boxStyle.paddingBottom || "0");
    height = Math.max(baseHeight, textEl.scrollHeight + paddingY);
    textEl.style.height = previousHeight;
  }
  box.element.style.height = `${height}px`;
  box.element.style.color = box.color;
  box.element.classList.toggle("is-deleted", box.deleted);
  box.element.classList.toggle("no-clip", !!box.noClip);
  box.element.classList.toggle("is-expanded", expanded);
}

function updatePageLayout(page) {
  if (!page.image || !page.overlay) return;
  const img = page.image;
  const naturalWidth = page.imageSize?.[0] || img.naturalWidth || img.width || img.clientWidth || 1;
  const scale = img.clientWidth / naturalWidth;
  page.scale = scale || 1;
  page.overlay.style.width = `${img.clientWidth}px`;
  page.overlay.style.height = `${img.clientHeight}px`;
  page.boxes.forEach((box) => updateBoxElement(page, box));
}

async function loadPdfDocument(pdfUrl) {
  if (!pdfUrl || !window.pdfjsLib) return;
  state.pdfUrl = pdfUrl;
  try {
    const task = window.pdfjsLib.getDocument(pdfUrl);
    state.pdfDoc = await task.promise;
    await renderAllPdfPages();
  } catch (error) {
    state.pdfDoc = null;
    state.pdfUrl = null;
    renderPages();
    setStatus("PDF 載入失敗。");
  }
}

async function renderPdfPage(pageIdx) {
  if (!state.pdfDoc) return;
  const page = state.pages[pageIdx];
  if (!page || !page.image) return;
  if (typeof page.image.getContext !== "function") return;
  const pdfPage = await state.pdfDoc.getPage(page.pageIndex + 1);
  const baseViewport = pdfPage.getViewport({ scale: 1 });
  const imageW = page.imageSize?.[0] || baseViewport.width;
  const imageH = page.imageSize?.[1] || baseViewport.height;
  const baseScale = imageW / baseViewport.width;
  const zoom = state.zoom || 1;
  const scale = baseScale * zoom;
  const viewport = pdfPage.getViewport({ scale });

  const canvas = page.image;
  const ctx = canvas.getContext("2d");
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  canvas.style.width = `${canvas.width}px`;
  canvas.style.height = `${canvas.height}px`;

  await pdfPage.render({ canvasContext: ctx, viewport }).promise;
  updatePageLayout(page);
}

async function renderThumbnail(pageIdx, canvas) {
  if (!state.pdfDoc) return;
  const page = state.pages[pageIdx];
  if (!page) return;
  const pdfPage = await state.pdfDoc.getPage(page.pageIndex + 1);
  const baseViewport = pdfPage.getViewport({ scale: 1 });
  const targetWidth = 130;
  const scale = targetWidth / baseViewport.width;
  const viewport = pdfPage.getViewport({ scale });
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  const ctx = canvas.getContext("2d");
  await pdfPage.render({ canvasContext: ctx, viewport }).promise;
}

function renderThumbnails() {
  if (!thumbsEl) return;
  thumbsEl.innerHTML = "";
  state.pages.forEach((page, pageIdx) => {
    const thumb = document.createElement("button");
    thumb.type = "button";
    thumb.className = "thumb";
    thumb.addEventListener("click", () => {
      setActivePage(pageIdx);
      setStatus(`Active page: ${page.pageIndex + 1}`);
    });

    if (state.pdfUrl && window.pdfjsLib && state.pdfDoc) {
      const canvas = document.createElement("canvas");
      canvas.className = "thumb-canvas";
      thumb.appendChild(canvas);
      renderThumbnail(pageIdx, canvas);
    } else if (page.imageUrl) {
      const img = document.createElement("img");
      img.src = page.imageUrl;
      img.alt = `Page ${page.pageIndex + 1}`;
      thumb.appendChild(img);
    }

    const label = document.createElement("span");
    label.textContent = `${page.pageIndex + 1}`;
    thumb.appendChild(label);

    page.thumbElement = thumb;
    thumbsEl.appendChild(thumb);
  });
  state.pages.forEach((page, idx) => {
    if (page.thumbElement) {
      page.thumbElement.classList.toggle("is-active", idx === state.activePageIdx);
    }
  });
}
async function renderAllPdfPages() {
  if (!state.pdfDoc) return;
  for (let i = 0; i < state.pages.length; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await renderPdfPage(i);
  }
}

function selectBox(pageIdx, boxIdx, additive = false) {
  setSelection(pageIdx, boxIdx, additive);
}

function buildDragGroup(pageIdx, boxIdx) {
  const selected = getSelectedBoxes().filter((item) => item.pageIdx === pageIdx);
  const key = boxKey(pageIdx, boxIdx);
  if (!state.selectedBoxes.has(key)) {
    state.selectedBoxes.add(key);
  }
  if (!selected.length) {
    const page = state.pages[pageIdx];
    const box = page?.boxes[boxIdx];
    if (!page || !box) return [];
    return [{ pageIdx, boxIdx, originX: box.bbox.x, originY: box.bbox.y }];
  }
  return selected.map((item) => ({
    pageIdx: item.pageIdx,
    boxIdx: item.boxIdx,
    originX: item.box.bbox.x,
    originY: item.box.bbox.y,
  }));
}

function onDragStart(event, pageIdx, boxIndex, groupMode = false) {
  if (event.button !== 0) return;
  event.preventDefault();
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIndex];
  if (!page || !box || box.deleted) return;
  setActivePage(pageIdx, { scroll: false });
  const key = boxKey(pageIdx, boxIndex);
  const selectedOnPage = getSelectedBoxes().filter((item) => item.pageIdx === pageIdx);
  const shouldGroup = groupMode || (selectedOnPage.length > 1 && state.selectedBoxes.has(key));

  if (shouldGroup) {
    const key = boxKey(pageIdx, boxIndex);
    if (!state.selectedBoxes.has(key)) {
      state.selectedBoxes.add(key);
      applySelectionClasses();
    }
    state.selected = { pageIdx, boxIdx: boxIndex };
    syncInspectorFromBox(box);
    } else {
      selectBox(pageIdx, boxIndex);
    }
    const group = shouldGroup ? buildDragGroup(pageIdx, boxIndex) : [{ pageIdx, boxIdx: boxIndex, originX: box.bbox.x, originY: box.bbox.y }];
    const beforeUpdates = group.map((item) => {
      const sourcePage = state.pages[item.pageIdx];
      const sourceBox = sourcePage?.boxes[item.boxIdx];
      return {
        pageIdx: item.pageIdx,
        boxId: sourceBox?.id,
        before: sourceBox ? cloneBoxData(sourceBox) : null,
      };
    }).filter((update) => Number.isFinite(update.boxId) && update.before);
    state.dragging = {
      pageIdx,
      boxIndex,
      startX: event.clientX,
      startY: event.clientY,
      groupMode: shouldGroup,
      group,
      beforeUpdates,
    };
  box.element.setPointerCapture(event.pointerId);
}

function onDragMove(event) {
  if (state.resizing) return;
  if (!state.dragging) return;
  const { pageIdx, startX, startY, group } = state.dragging;
  const page = state.pages[pageIdx];
  if (!page) return;
  const scale = page.scale || 1;
  const dx = (event.clientX - startX) / scale;
  const dy = (event.clientY - startY) / scale;

    if (group && group.length) {
      group.forEach((item) => {
        const targetPage = state.pages[item.pageIdx];
        const targetBox = targetPage?.boxes[item.boxIdx];
        if (!targetPage || !targetBox) return;
        targetBox.bbox.x = Math.max(0, item.originX + dx);
        targetBox.bbox.y = Math.max(0, item.originY + dy);
        updateBoxElement(targetPage, targetBox);
      });
      if (dx !== 0 || dy !== 0) {
        state.dragging.moved = true;
      }
      return;
    }
  }

function onDragEnd(event) {
  if (!state.dragging) return;
  const { pageIdx, boxIndex } = state.dragging;
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIndex];
  if (box?.element) {
    box.element.releasePointerCapture(event.pointerId);
  }
  if (state.dragging.moved) {
    const updates = (state.dragging.beforeUpdates || []).map((update) => {
      const current = findBox(update.pageIdx, update.boxId);
      return current ? { ...update, after: cloneBoxData(current) } : null;
    }).filter(Boolean);
    if (updates.length) {
      pushAction({ type: "update_boxes", updates });
    }
  }
  state.dragging = null;
}

function onResizeStart(event, pageIdx, boxIdx, dir = "se") {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (!page || !box || box.deleted) return;
  const key = boxKey(pageIdx, boxIdx);
  const selectedOnPage = getSelectedBoxes().filter((item) => item.pageIdx === pageIdx);
  const shouldGroup = selectedOnPage.length > 1 && state.selectedBoxes.has(key);
  if (!shouldGroup) {
    setSelection(pageIdx, boxIdx);
  } else {
    setActivePage(pageIdx, { scroll: false });
    syncInspectorFromBox(box);
  }
  const group = shouldGroup
    ? selectedOnPage.map((item) => ({
      pageIdx: item.pageIdx,
      boxIdx: item.boxIdx,
      originW: item.box.bbox.w,
      originH: item.box.bbox.h,
      originX: item.box.bbox.x,
      originY: item.box.bbox.y,
    }))
    : [{ pageIdx, boxIdx, originW: box.bbox.w, originH: box.bbox.h, originX: box.bbox.x, originY: box.bbox.y }];
  const beforeUpdates = group.map((item) => {
    const sourcePage = state.pages[item.pageIdx];
    const sourceBox = sourcePage?.boxes[item.boxIdx];
    return {
      pageIdx: item.pageIdx,
      boxId: sourceBox?.id,
      before: sourceBox ? cloneBoxData(sourceBox) : null,
    };
  }).filter((update) => Number.isFinite(update.boxId) && update.before);
  state.resizing = {
    pageIdx,
    boxIdx,
    startX: event.clientX,
    startY: event.clientY,
    groupMode: shouldGroup,
    group,
    beforeUpdates,
    dir,
    handleEl: event.currentTarget,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
}

function onResizeMove(event) {
  if (!state.resizing) return;
  const { pageIdx, startX, startY, group, dir } = state.resizing;
  const page = state.pages[pageIdx];
  if (!page) return;
  const scale = page.scale || 1;
  const dx = (event.clientX - startX) / scale;
  const dy = (event.clientY - startY) / scale;
  const minSize = 12;

  if (group && group.length) {
    group.forEach((item) => {
      const targetPage = state.pages[item.pageIdx];
      const targetBox = targetPage?.boxes[item.boxIdx];
      if (!targetPage || !targetBox) return;

      let newX = item.originX;
      let newY = item.originY;
      let newW = item.originW;
      let newH = item.originH;

      const hasW = dir.includes("w");
      const hasE = dir.includes("e");
      const hasN = dir.includes("n");
      const hasS = dir.includes("s");

      if (hasE) {
        newW = item.originW + dx;
      }
      if (hasS) {
        newH = item.originH + dy;
      }
      if (hasW) {
        newX = item.originX + dx;
        newW = item.originW - dx;
      }
      if (hasN) {
        newY = item.originY + dy;
        newH = item.originH - dy;
      }

      if (newW < minSize) {
        if (hasW) {
          newX -= (minSize - newW);
        }
        newW = minSize;
      }
      if (newH < minSize) {
        if (hasN) {
          newY -= (minSize - newH);
        }
        newH = minSize;
      }

      newX = Math.max(0, newX);
      newY = Math.max(0, newY);

      if (targetPage.imageSize && targetPage.imageSize.length === 2) {
        const maxW = targetPage.imageSize[0] - newX;
        const maxH = targetPage.imageSize[1] - newY;
        if (Number.isFinite(maxW)) newW = Math.min(newW, maxW);
        if (Number.isFinite(maxH)) newH = Math.min(newH, maxH);
      }

      targetBox.bbox.x = newX;
      targetBox.bbox.y = newY;
      targetBox.bbox.w = newW;
      targetBox.bbox.h = newH;
      updateBoxElement(targetPage, targetBox);
      if (newW !== item.originW || newH !== item.originH || newX !== item.originX || newY !== item.originY) {
        state.resizing.changed = true;
      }
    });
  }
}

function onResizeEnd(event) {
  if (!state.resizing) return;
  const { pageIdx, boxIdx } = state.resizing;
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (state.resizing.handleEl?.releasePointerCapture) {
    state.resizing.handleEl.releasePointerCapture(event.pointerId);
  }
  if (state.resizing.changed) {
    const updates = (state.resizing.beforeUpdates || []).map((update) => {
      const current = findBox(update.pageIdx, update.boxId);
      return current ? { ...update, after: cloneBoxData(current) } : null;
    }).filter(Boolean);
    if (updates.length) {
      pushAction({
        type: "update_boxes",
        updates,
      });
    }
  }
  state.resizing = null;
}

function startRangeSelection(event, pageIdx) {
  if (event.button !== 0) return;
  if (event.target.closest(".text-box")) return;
  const page = state.pages[pageIdx];
  if (!page || !page.overlay) return;
  setActivePage(pageIdx, { scroll: false });
  const bounds = page.overlay.getBoundingClientRect();
  const startX = event.clientX - bounds.left;
  const startY = event.clientY - bounds.top;
  const rectEl = page.selectionRect;
  if (!rectEl) return;
  const additive = event.ctrlKey;

  rectEl.style.display = "block";
  rectEl.style.left = `${startX}px`;
  rectEl.style.top = `${startY}px`;
  rectEl.style.width = "0px";
  rectEl.style.height = "0px";

  state.selecting = {
    pageIdx,
    startX,
    startY,
    bounds,
    overlayEl: page.overlay,
    rectEl,
    captureEl: event.currentTarget,
    pointerId: event.pointerId,
    additive,
    scrollLeft: pagesEl?.scrollLeft ?? 0,
    scrollTop: pagesEl?.scrollTop ?? 0,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  if (!additive) {
    clearSelection();
  }
}

function updateRangeSelection(event) {
  if (!state.selecting) return;
  const { startX, startY, rectEl, overlayEl, scrollLeft, scrollTop } = state.selecting;
  if (!overlayEl) return;
  const bounds = overlayEl.getBoundingClientRect();
  const scrollDx = (pagesEl?.scrollLeft ?? 0) - scrollLeft;
  const scrollDy = (pagesEl?.scrollTop ?? 0) - scrollTop;
  let clientX = event.clientX;
  let clientY = event.clientY;
  if (event.type === "wheel" && state.selecting.lastClientX != null && state.selecting.lastClientY != null) {
    clientX = state.selecting.lastClientX;
    clientY = state.selecting.lastClientY;
  } else {
    state.selecting.lastClientX = event.clientX;
    state.selecting.lastClientY = event.clientY;
  }
  if (event.type === "wheel") {
    state.selecting.scrollLeft = pagesEl?.scrollLeft ?? scrollLeft;
    state.selecting.scrollTop = pagesEl?.scrollTop ?? scrollTop;
  }
  const currentX = clientX - bounds.left + scrollDx;
  const currentY = clientY - bounds.top + scrollDy;
  const left = Math.min(startX, currentX);
  const top = Math.min(startY, currentY);
  const width = Math.abs(currentX - startX);
  const height = Math.abs(currentY - startY);
  rectEl.style.left = `${left}px`;
  rectEl.style.top = `${top}px`;
  rectEl.style.width = `${width}px`;
  rectEl.style.height = `${height}px`;
  state.selecting.bounds = bounds;
  state.selecting.lastClientX = event.clientX;
  state.selecting.lastClientY = event.clientY;
  state.selecting.rect = { left, top, width, height };
}

function endRangeSelection(event) {
  if (!state.selecting) return;
  const { pageIdx, rect, rectEl, captureEl, pointerId, additive } = state.selecting;
  rectEl.style.display = "none";
  if (captureEl) {
    captureEl.releasePointerCapture(pointerId);
  }
  state.selecting = null;

  if (!rect || rect.width < 4 || rect.height < 4) {
    if (!additive) {
      clearSelection();
    }
    return;
  }

  const page = state.pages[pageIdx];
  if (!page) return;
  const scale = page.scale || 1;
  const selectionBox = {
    x: rect.left / scale,
    y: rect.top / scale,
    w: rect.width / scale,
    h: rect.height / scale,
  };

  page.boxes.forEach((box, boxIdx) => {
    if (box.deleted) return;
    if (boxesIntersect(box.bbox, selectionBox)) {
      state.selectedBoxes.add(boxKey(pageIdx, boxIdx));
    }
  });

  const selectedList = getSelectedBoxes();
  if (selectedList.length) {
    const primary = selectedList[0];
    state.selected = { pageIdx: primary.pageIdx, boxIdx: primary.boxIdx };
    syncInspectorFromBox(primary.box);
  } else {
    state.selected = null;
  }
  applySelectionClasses();
}

function renderPages() {
  pagesEl.innerHTML = "";
  state.pages.forEach((page, pageIdx) => {
    const pageEl = document.createElement("article");
    pageEl.className = "page";

    const header = document.createElement("div");
    header.className = "page-header";
    header.innerHTML = `<span class="page-number">Page ${page.pageIndex + 1}</span>`;
    header.addEventListener("click", () => {
      setActivePage(pageIdx);
      setStatus(`Active page: ${page.pageIndex + 1}`);
    });

    const wrap = document.createElement("div");
    wrap.className = "page-wrap";
    wrap.draggable = false;
    wrap.addEventListener("dragstart", (event) => event.preventDefault());

    let img;
    if (state.pdfUrl && window.pdfjsLib) {
      img = document.createElement("canvas");
      img.className = "pdf-canvas";
    } else {
      img = document.createElement("img");
      img.src = page.imageUrl;
      img.alt = `Page ${page.pageIndex + 1}`;
      img.draggable = false;
      img.addEventListener("dragstart", (event) => event.preventDefault());
      img.addEventListener("load", () => {
        applyZoomToPage(page);
      });
    }

    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.draggable = false;
    overlay.addEventListener("dragstart", (event) => event.preventDefault());

    const selectionRect = document.createElement("div");
    selectionRect.className = "selection-rect";
    selectionRect.style.display = "none";
    overlay.appendChild(selectionRect);

    window.addEventListener("resize", () => updatePageLayout(page));

    wrap.appendChild(img);
    wrap.appendChild(overlay);
    pageEl.appendChild(header);
    pageEl.appendChild(wrap);
    pagesEl.appendChild(pageEl);

    page.element = pageEl;
    page.overlay = overlay;
    page.image = img;
    page.selectionRect = selectionRect;

    wrap.addEventListener("pointerdown", (event) => startRangeSelection(event, pageIdx));
    wrap.addEventListener("pointermove", updateRangeSelection);
    wrap.addEventListener("pointerup", endRangeSelection);
    wrap.addEventListener("pointercancel", endRangeSelection);
    wrap.addEventListener("wheel", (event) => {
      if (state.selecting) {
        updateRangeSelection(event);
      }
    }, { passive: true });

    page.boxes.forEach((box, index) => {
      createBoxElement(pageIdx, index);
    });
  });
  renderThumbnails();
}

function createBoxElement(pageIdx, boxIdx) {
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (!page || !box || !page.overlay) return null;

  const boxEl = document.createElement("div");
  boxEl.className = "text-box";
  boxEl.style.left = "0px";
  boxEl.style.top = "0px";

  const textEl = document.createElement("div");
  textEl.className = "text";
  textEl.contentEditable = "true";
  textEl.spellcheck = false;
  textEl.draggable = false;
  textEl.addEventListener("dragstart", (event) => event.preventDefault());
  textEl.textContent = box.text;
  textEl.innerText = box.text;
  boxEl.appendChild(textEl);
  page.overlay.appendChild(boxEl);
  boxEl.draggable = false;
  boxEl.addEventListener("dragstart", (event) => event.preventDefault());

  boxEl.addEventListener("pointerdown", (event) => {
    state.lastCtrlKey = event.ctrlKey;
    if (event.target.closest(".resize-handle")) {
      return;
    }
    if (event.target.closest(".text")) {
      selectBox(pageIdx, boxIdx, event.ctrlKey);
      return;
    }
    if (event.ctrlKey) {
      const key = boxKey(pageIdx, boxIdx);
      const wasSelected = state.selectedBoxes.has(key);
      selectBox(pageIdx, boxIdx, true);
      if (wasSelected) {
        return;
      }
      onDragStart(event, pageIdx, boxIdx, true);
      return;
    }
    onDragStart(event, pageIdx, boxIdx);
  });
  boxEl.addEventListener("pointermove", onDragMove);
  boxEl.addEventListener("pointerup", onDragEnd);
  boxEl.addEventListener("pointercancel", onDragEnd);
  boxEl.addEventListener("dblclick", (event) => {
    if (event.target.closest(".resize-handle") || event.target.closest(".text")) {
      return;
    }
    event.preventDefault();
    selectBox(pageIdx, boxIdx, event.ctrlKey);
    if (!box.noClip) {
      box.noClip = true;
      updateBoxElement(page, box);
    }
  });

  textEl.addEventListener("focus", () => {
    selectBox(pageIdx, boxIdx, state.lastCtrlKey);
    state.lastCtrlKey = false;
    if (!box._editBefore) {
      box._editBefore = cloneBoxData(box);
    }
  });
  
  textEl.addEventListener("input", () => {
    box.text = textEl.innerText;
    if (box.noClip || box._isExpanded) {
      updateBoxElement(page, box);
    }
  });

  textEl.addEventListener("blur", () => {
    const normalized = textEl.innerText.trim();
    box.text = normalized;
    if (textEl.innerText !== normalized) {
      textEl.innerText = normalized;
    }
  });
  
  ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach((dir) => {
    const handleEl = document.createElement("div");
    handleEl.className = `resize-handle resize-${dir}`;
    handleEl.dataset.dir = dir;
    boxEl.appendChild(handleEl);

    handleEl.addEventListener("pointerdown", (event) => onResizeStart(event, pageIdx, boxIdx, dir));
    handleEl.addEventListener("pointermove", onResizeMove);
    handleEl.addEventListener("pointerup", onResizeEnd);
    handleEl.addEventListener("pointercancel", onResizeEnd);
  });

  box.element = boxEl;
  updateBoxElement(page, box);
  return textEl;
}

function addNewBox() {
  if (!state.pages.length) return;
  const targetPageIdx = state.selected?.pageIdx ?? state.activePageIdx ?? 0;
  const page = state.pages[targetPageIdx];
  if (!page) return;

  const pageWidth = page.imageSize?.[0] ?? 800;
  const pageHeight = page.imageSize?.[1] ?? 1000;
  const defaultW = Math.min(220, pageWidth * 0.4);
  const defaultH = Math.min(48, pageHeight * 0.1);

  let x = 24;
  let y = 24;
  if (state.selected && state.selected.pageIdx === targetPageIdx) {
    const selBox = page.boxes[state.selected.boxIdx];
    if (selBox) {
      x = selBox.bbox.x;
      y = selBox.bbox.y + selBox.bbox.h + 12;
    }
  }
  if (x + defaultW > pageWidth) x = Math.max(0, pageWidth - defaultW - 12);
  if (y + defaultH > pageHeight) y = Math.max(0, pageHeight - defaultH - 12);

  const nextId = page.boxes.length ? Math.max(...page.boxes.map((box) => Number(box.id) || 0)) + 1 : 0;
  const box = {
    id: nextId,
    bbox: { x, y, w: defaultW, h: defaultH },
    text: "",
    fontSize: Math.max(10, Math.min(28, defaultH * 0.6)),
    color: "#0000ff",
    noClip: false,
    autoGenerated: false,
    deleted: false,
    element: null,
  };
  page.boxes.push(box);
  const textEl = createBoxElement(targetPageIdx, page.boxes.length - 1);
  selectBox(targetPageIdx, page.boxes.length - 1);
  if (textEl) {
    textEl.focus();
  }
  setStatus("Text box added.");
  pushAction({ type: "add_boxes", boxes: [{ pageIdx: targetPageIdx, box: cloneBoxData(box) }] });
}

function buildSavePayload() {
  return {
    pages: state.pages.map((page) => ({
      page_index_0based: page.pageIndex,
      boxes: page.boxes.map((box) => ({
        id: box.id,
        deleted: box.deleted,
        bbox: box.bbox,
        text: box.text,
        font_size: box.fontSize,
        no_clip: !!box.noClip,
        color: box.color,
        auto_generated: !!box.autoGenerated,
        tm_source_text: box.tmSourceText || "",
        tm_source_normalized: box.tmSourceNormalized || "",
        tm_target_lang: box.tmTargetLang || "",
        tm_document_mode: box.tmDocumentMode || "",
      })),
    })),
  };
}

async function loadJobData(jobId) {
  setStatus("Loading OCR data...");
  const res = await fetch(`/api/job/${jobId}`);
  if (!res.ok) {
    setStatus("Failed to load job data.");
    return null;
  }
  const data = await res.json();
  buildState(data);
  renderPages();
  if (state.pdfUrl && window.pdfjsLib) {
    await loadPdfDocument(state.pdfUrl);
  }
  updateEditedLink(data.edited_pdf_url);
  if (previewEditedBtn) {
    previewEditedBtn.disabled = !data.edited_pdf_url;
  }
  renderBatchStatus(data.batch_status);
  resetHistory();
  return data;
}

async function pollBatchStatus(jobId) {
  const res = await fetch(`/api/job/${jobId}/batch-status`);
  if (!res.ok) return null;
  const payload = await res.json();
  const status = payload.status || { status: "unknown" };
  renderBatchStatus(status);
  if (status.status === "running" || status.status === "queued") {
    setTimeout(() => pollBatchStatus(jobId), 5000);
  } else if (status.status === "completed") {
    await loadJobData(jobId);
  }
  return status;
}

async function saveEdits(shouldDownload = false) {
  const jobId = document.body.dataset.jobId;
  if (!jobId) return;
  const originalText = saveBtn ? saveBtn.textContent : null;
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
  }
  if (downloadBtn) {
    downloadBtn.disabled = true;
  }
  setStatus("Saving edits...");
  try {
    const payload = buildSavePayload();
    const res = await fetch(`/api/job/${jobId}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok) {
      if (body.edited_pdf_url) {
        updateEditedLink(body.edited_pdf_url);
        if (shouldDownload) {
          triggerDownload(body.edited_pdf_url, state.downloadName);
        }
      }
      setStatus("Edits saved.");
    } else {
      setStatus(body.error ? `Save failed: ${body.error}` : "Save failed. Check server logs.");
    }
  } catch (error) {
    setStatus("Save failed. Check console/logs.");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = originalText || "Save edits";
    }
    if (downloadBtn) {
      downloadBtn.disabled = false;
    }
  }
}

function bindControls() {
  if (controlsBound) return;
  controlsBound = true;
  const applyFontSize = (value) => {
    if (!Number.isFinite(value)) return;
    const minValue = Math.max(
      Number(fontSizeEl?.min ?? value),
      Number(fontSizeNumberEl?.min ?? value),
    );
    const maxValue = Math.min(
      Number(fontSizeEl?.max ?? value),
      Number(fontSizeNumberEl?.max ?? value),
    );
    const clamped = Math.max(minValue, Math.min(maxValue, value));
    const displayValue = Math.round(clamped).toString();
    if (fontSizeEl) fontSizeEl.value = displayValue;
    if (fontSizeNumberEl) fontSizeNumberEl.value = displayValue;

    const selected = getSelectedBoxes();
    if (!selected.length) return;
    const updates = selected.map(({ pageIdx, box }) => ({
      pageIdx,
      boxId: box.id,
      before: cloneBoxData(box),
    }));
    selected.forEach(({ page, box }) => {
      box.fontSize = clamped;
      updateBoxElement(page, box);
    });
    const finalized = updates.map((update) => {
      const current = findBox(update.pageIdx, update.boxId);
      return current ? { ...update, after: cloneBoxData(current) } : null;
    }).filter(Boolean).filter((update) => update.before.fontSize !== update.after.fontSize);
    if (finalized.length) {
      pushAction({ type: "update_boxes", updates: finalized });
    }
  };

  const tryApplyFontSizeInput = (value) => {
    if (!Number.isFinite(value)) return;
    const minValue = Math.max(
      Number(fontSizeEl?.min ?? value),
      Number(fontSizeNumberEl?.min ?? value),
    );
    const maxValue = Math.min(
      Number(fontSizeEl?.max ?? value),
      Number(fontSizeNumberEl?.max ?? value),
    );
    if (value < minValue || value > maxValue) return;
    applyFontSize(value);
  };

  if (fontSizeEl) {
    fontSizeEl.addEventListener("input", () => {
      applyFontSize(Number(fontSizeEl.value));
    });
  }

  if (fontSizeNumberEl) {
    fontSizeNumberEl.addEventListener("input", () => {
      tryApplyFontSizeInput(Number(fontSizeNumberEl.value));
    });
    fontSizeNumberEl.addEventListener("change", () => {
      applyFontSize(Number(fontSizeNumberEl.value));
    });
  }

  if (fontColorEl) {
    fontColorEl.addEventListener("input", () => {
      const selected = getSelectedBoxes();
      if (!selected.length) return;
      const updates = selected.map(({ pageIdx, box }) => ({
        pageIdx,
        boxId: box.id,
        before: cloneBoxData(box),
      }));
      const value = fontColorEl.value;
      selected.forEach(({ page, box }) => {
        box.color = value;
        updateBoxElement(page, box);
      });
      const finalized = updates.map((update) => {
        const current = findBox(update.pageIdx, update.boxId);
        return current ? { ...update, after: cloneBoxData(current) } : null;
      }).filter(Boolean).filter((update) => update.before.color !== update.after.color);
      if (finalized.length) {
        pushAction({ type: "update_boxes", updates: finalized });
      }
    });
  }

  if (pageSelectEl) {
    pageSelectEl.addEventListener("change", () => {
      const idx = Number.parseInt(pageSelectEl.value, 10);
      if (!Number.isFinite(idx)) return;
      setActivePage(idx);
      const page = state.pages[idx];
      page?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  if (prevPageBtn) {
    prevPageBtn.addEventListener("click", () => {
      const idx = Math.max(0, (state.activePageIdx ?? 0) - 1);
      setActivePage(idx);
      const page = state.pages[idx];
      page?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  if (nextPageBtn) {
    nextPageBtn.addEventListener("click", () => {
      const idx = Math.min(state.pages.length - 1, (state.activePageIdx ?? 0) + 1);
      setActivePage(idx);
      const page = state.pages[idx];
      page?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  const applyZoomFromInput = (value, force = false) => {
    if (!Number.isFinite(value)) return;
    const minValue = Number(zoomRangeEl?.min ?? 25);
    const maxValue = Number(zoomRangeEl?.max ?? 200);
    if (!force && (value < minValue || value > maxValue)) return;
    setZoomPercent(value);
  };

  if (zoomRangeEl) {
    zoomRangeEl.addEventListener("input", () => {
      applyZoomFromInput(Number(zoomRangeEl.value));
    });
  }

  if (zoomNumberEl) {
    zoomNumberEl.addEventListener("input", () => {
      applyZoomFromInput(Number(zoomNumberEl.value));
    });
    zoomNumberEl.addEventListener("change", () => {
      applyZoomFromInput(Number(zoomNumberEl.value), true);
    });
  }

  if (pagesEl) {
    pagesEl.addEventListener(
      "wheel",
      (event) => {
        if (state.selecting && !event.ctrlKey) {
          updateRangeSelection(event);
          return;
        }
        if (!event.ctrlKey) return;
        event.preventDefault();
        const step = event.deltaY < 0 ? 5 : -5;
        const current = Number(zoomNumberEl?.value || Math.round((state.zoom || 1) * 100));
        setZoomPercent(current + step);
      },
      { passive: false },
    );
  }

  if (deleteBtn) {
    deleteBtn.addEventListener("click", () => {
      deleteSelectedBoxes();
    });
  }

  if (addBoxBtn) {
    addBoxBtn.addEventListener("click", () => {
      addNewBox();
    });
  }

  if (copyBoxBtn) {
    copyBoxBtn.addEventListener("click", () => {
      duplicateSelectedBoxes();
    });
  }

  if (addGlossaryBtn) {
    addGlossaryBtn.addEventListener("click", () => {
      addGlossaryEntry();
    });
  }

  if (savePromptBtn) {
    savePromptBtn.addEventListener("click", () => {
      saveSystemPrompt(currentJobId);
    });
  }

  if (glossaryPromptBtn) {
    glossaryPromptBtn.addEventListener("click", () => {
      openGlossaryModal();
    });
  }

  if (closeGlossaryPrompt) {
    closeGlossaryPrompt.addEventListener("click", () => {
      closeGlossaryModal();
    });
  }

  if (glossaryPromptModal) {
    glossaryPromptModal.addEventListener("click", (event) => {
      if (event.target === glossaryPromptModal) {
        closeGlossaryModal();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeGlossaryModal();
    }
  });

  if (glossaryCnEl) {
    glossaryCnEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addGlossaryEntry();
      }
    });
  }

  if (glossaryEnEl) {
    glossaryEnEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addGlossaryEntry();
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", (event) => {
      event.preventDefault();
      saveEdits();
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", (event) => {
      event.preventDefault();
      saveEdits(true);
    });
  }

  if (previewDebugBtn) {
    previewDebugBtn.addEventListener("click", () => {
      setPreviewMode("debug");
    });
  }

  if (previewEditedBtn) {
    previewEditedBtn.addEventListener("click", () => {
      if (!previewEditedBtn.disabled && editedLink?.href) {
        setPreviewMode("edited", editedLink.href);
      }
    });
  }

  if (batchTranslateBtn) {
    batchTranslateBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      const jobId = document.body.dataset.jobId;
      if (!jobId) return;
      setBatchButtonState("running");
      setStatus("啟動 Batch 翻譯...");
      try {
        const res = await fetch(`/api/job/${jobId}/batch-translate`, { method: "POST" });
        if (!res.ok) {
          setStatus("Batch 翻譯啟動失敗。");
          setBatchButtonState("failed");
          return;
        }
        setTimeout(() => pollBatchStatus(jobId), 3000);
      } catch (error) {
        setStatus("Batch 翻譯啟動失敗。");
        setBatchButtonState("failed");
      }
    });
  }

  if (batchRestoreBtn) {
    batchRestoreBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      const jobId = document.body.dataset.jobId;
      if (!jobId) return;
      setStatus("回復翻譯結果中...");
      try {
        const res = await fetch(`/api/job/${jobId}/batch-restore`, { method: "POST" });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          setStatus(body.error ? `回復失敗：${body.error}` : "回復失敗。");
          return;
        }
        await loadJobData(jobId);
        setStatus("已回復翻譯結果。");
      } catch (error) {
        setStatus("回復失敗。");
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isEditing =
      target && (target.isContentEditable || ["INPUT", "TEXTAREA"].includes(target.tagName));

    if ((event.ctrlKey || event.metaKey) && !isEditing) {
      const key = event.key.toLowerCase();
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redoHistory();
        } else {
          undoHistory();
        }
        return;
      }
      if (key === "y") {
        event.preventDefault();
        redoHistory();
        return;
      }
      if (key === "c") {
        event.preventDefault();
        copySelectedBoxes();
        return;
      }
      if (key === "v") {
        event.preventDefault();
        pasteClipboardBoxes();
        return;
      }
    }

    if (event.key !== "Delete") return;
    if (isEditing) return;
    deleteSelectedBoxes();
  });
}

async function init() {
  const jobId = document.body.dataset.jobId;
  if (!jobId) return;
  currentJobId = jobId;
  bindControls();
  const data = await loadJobData(jobId);
  if (!data) return;
  glossaryEntries = Array.isArray(data.glossary) ? data.glossary : [];
  renderGlossary();
  loadGlossary();
  if (systemPromptEl) {
    systemPromptEl.value = data.system_prompt || "";
  }
  const status = data.batch_status?.status;
  if (status === "running" || status === "queued") {
    setTimeout(() => pollBatchStatus(jobId), 5000);
  }
}

if (document.body.classList.contains("editor")) {
  init();
}
