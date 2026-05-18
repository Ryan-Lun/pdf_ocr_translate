const state = {
  pages: [],
  selected: null,
  dragging: null,
  resizing: null,
  previewMode: "debug",
  selectionMode: "boxes",
  selectedBoxes: new Set(),
  selecting: null,
  lastCtrlKey: false,
  activePageIdx: 0,
  clipboard: {
    boxes: [],
    sourcePageIdx: null,
    pasteCount: 0,
  },
  viewMode: "single",
  zoom: 1,
  pdfUrl: null,
  pdfDoc: null,
  downloadName: null,
  pendingRegionPreview: null,
  consistencyGroups: [],
  selectedConsistencyKey: null,
  paragraphTermGroups: [],
  selectedParagraphTermKey: null,
  mergeNotices: [],
};

const historyState = {
  past: [],
  future: [],
  limit: 200,
  isRestoring: false,
};

let controlsBound = false;
let contextTranslatedEditKey = null;
let contextSourceEditKey = null;
let documentTemplates = [];
let templateApplyJobs = [];
const templateMode = document.body.dataset.templateMode === "true";
const BOX_HIT_SLOP_PX = 6;
const DRAG_START_THRESHOLD_PX = 4;

const statusEl = document.getElementById("status");
const fontSizeEl = document.getElementById("fontSize");
const fontSizeNumberEl = document.getElementById("fontSizeNumber");
const fontColorEl = document.getElementById("fontColor");
const alignLeftBtn = document.getElementById("alignLeft");
const alignCenterBtn = document.getElementById("alignCenter");
const alignRightBtn = document.getElementById("alignRight");
const rotateLeftBtn = document.getElementById("rotateLeft");
const rotateResetBtn = document.getElementById("rotateReset");
const rotateRightBtn = document.getElementById("rotateRight");
const deleteBtn = document.getElementById("deleteBox");
const addBoxBtn = document.getElementById("addBox");
const copyBoxBtn = document.getElementById("copyBox");
const batchApplyBoxesBtn = document.getElementById("batchApplyBoxes");
const batchDeleteBoxesBtn = document.getElementById("batchDeleteBoxes");
const saveBtn = document.getElementById("saveBtn");
const downloadBtn = document.getElementById("downloadBtn");
const headerTemplateBtn = document.getElementById("headerTemplateBtn");
const menuBtn = document.getElementById("menuBtn");
const menuDropdown = document.getElementById("menuDropdown");
const regionTranslateBtn = document.getElementById("regionTranslateBtn");
const batchRestoreBtn = document.getElementById("batchRestoreBtn");
const prevPageBtn = document.getElementById("prevPage");
const nextPageBtn = document.getElementById("nextPage");
const pageSelectEl = document.getElementById("pageSelect");
const zoomRangeEl = document.getElementById("zoomRange");
const zoomNumberEl = document.getElementById("zoomNumber");
const fitToWidthBtn = document.getElementById("fitToWidthBtn");
const pagesEl = document.getElementById("pages");
const thumbsEl = document.getElementById("thumbs");
const toggleThumbsBtn = document.getElementById("toggleThumbsBtn");
const toggleViewModeBtn = document.getElementById("toggleViewModeBtn");
const sidebarEl = document.querySelector(".editor-sidebar");
const sidebarRailButtons = Array.from(document.querySelectorAll(".sidebar-rail__item"));
const refreshConsistencyBtn = document.getElementById("refreshConsistencyBtn");
const mergeNoticeSectionEl = document.getElementById("mergeNoticeSection");
const mergeNoticeSummaryEl = document.getElementById("mergeNoticeSummary");
const mergeNoticeListEl = document.getElementById("mergeNoticeList");
const consistencySummaryEl = document.getElementById("consistencySummary");
const consistencyListEl = document.getElementById("consistencyList");
const consistencyDetailEl = document.getElementById("consistencyDetail");
const consistencySourceTitleEl = document.getElementById("consistencySourceTitle");
const consistencySourceMetaEl = document.getElementById("consistencySourceMeta");
const consistencyVariantListEl = document.getElementById("consistencyVariantList");
const consistencyTargetTextEl = document.getElementById("consistencyTargetText");
const consistencySyncTmEl = document.getElementById("consistencySyncTm");
const applyConsistencyBtn = document.getElementById("applyConsistencyBtn");
const paragraphTermSummaryEl = document.getElementById("paragraphTermSummary");
const paragraphTermListEl = document.getElementById("paragraphTermList");
const paragraphTermDetailEl = document.getElementById("paragraphTermDetail");
const paragraphTermTitleEl = document.getElementById("paragraphTermTitle");
const paragraphTermMetaEl = document.getElementById("paragraphTermMeta");
const paragraphTermVariantListEl = document.getElementById("paragraphTermVariantList");
const paragraphTermPreviewListEl = document.getElementById("paragraphTermPreviewList");
const paragraphReplaceFromEl = document.getElementById("paragraphReplaceFrom");
const paragraphReplaceToEl = document.getElementById("paragraphReplaceTo");
const paragraphSyncTmEl = document.getElementById("paragraphSyncTm");
const applyParagraphTermBtn = document.getElementById("applyParagraphTermBtn");
const contextSummaryEl = document.getElementById("contextSummary");
const contextSourceTextEl = document.getElementById("contextSourceText");
const contextTranslatedTextEl = document.getElementById("contextTranslatedText");
const contextRetranslateBtn = document.getElementById("contextRetranslateBtn");
const viewerEl = document.querySelector(".viewer");
const editedLink = document.getElementById("editedPdfLink");
const previewEl = document.getElementById("pdfPreview");
const previewDebugBtn = document.getElementById("previewDebug");
const previewEditedBtn = document.getElementById("previewEdited");
const debugLinkEl = document.querySelector(".topbar-actions a[href*='overlay_debug.pdf']");
const glossaryCnEl = document.getElementById("glossaryCn");
const glossaryEnEl = document.getElementById("glossaryEn");
const addGlossaryBtn = document.getElementById("addGlossaryBtn");
const addGlossaryRetranslateBtn = document.getElementById("addGlossaryRetranslateBtn");
const glossaryQuickHintEl = document.getElementById("glossaryQuickHint");
const systemPromptEl = document.getElementById("systemPrompt");
const savePromptBtn = document.getElementById("savePromptBtn");
const retranslateDocumentBtn = document.getElementById("retranslateDocumentBtn");
const glossaryPromptBtn = document.getElementById("glossaryPromptBtn");
const glossaryPromptModal = document.getElementById("glossaryPromptModal");
const closeGlossaryPrompt = document.getElementById("closeGlossaryPrompt");
const templateManagerBtn = document.getElementById("templateManagerBtn");
const templateManagerModal = document.getElementById("templateManagerModal");
const closeTemplateManagerBtn = document.getElementById("closeTemplateManager");
const templateNameEl = document.getElementById("templateName");
const saveTemplateBtn = document.getElementById("saveTemplateBtn");
const templateSelectEl = document.getElementById("templateSelect");
const templateSummaryEl = document.getElementById("templateSummary");
const templateApplyAllEl = document.getElementById("templateApplyAll");
const templateApplyAfterEl = document.getElementById("templateApplyAfter");
const templateApplyManualEl = document.getElementById("templateApplyManual");
const templateApplyInputEl = document.getElementById("templateApplyInput");
const applyTemplateBtn = document.getElementById("applyTemplateBtn");
const deleteTemplateBtn = document.getElementById("deleteTemplateBtn");
const templateTargetJobSelectEl = document.getElementById("templateTargetJobSelect");
const applyTemplateToJobBtn = document.getElementById("applyTemplateToJobBtn");
const regionPreviewModal = document.getElementById("regionPreviewModal");
const regionPreviewImageEl = document.getElementById("regionPreviewImage");
const regionPreviewTextEl = document.getElementById("regionPreviewText");
const confirmRegionPreviewBtn = document.getElementById("confirmRegionPreview");
const cancelRegionPreviewBtn = document.getElementById("cancelRegionPreview");
const closeRegionPreviewBtn = document.getElementById("closeRegionPreview");
const batchPageModal = document.getElementById("batchPageModal");
const batchPageSourceHintEl = document.getElementById("batchPageSourceHint");
const batchPageAllEl = document.getElementById("batchPageAll");
const batchPageAfterEl = document.getElementById("batchPageAfter");
const batchPageInputEl = document.getElementById("batchPageInput");
const confirmBatchPageModalBtn = document.getElementById("confirmBatchPageModal");
const cancelBatchPageModalBtn = document.getElementById("cancelBatchPageModal");
const closeBatchPageModalBtn = document.getElementById("closeBatchPageModal");
const alignmentButtons = [alignLeftBtn, alignCenterBtn, alignRightBtn].filter(Boolean);

// if (window.pdfjsLib) {
//   window.pdfjsLib.GlobalWorkerOptions.workerSrc =
//     "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.js";
// }
if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc =
    "/static/pdfjs/pdf.worker.min.mjs";
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

function normalizeTextAlign(value) {
  return ["left", "center", "right"].includes(value) ? value : "left";
}

function normalizeBoxRotation(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 0;
  const normalized = ((parsed % 360) + 360) % 360;
  return [0, 90, 180, 270].includes(normalized) ? normalized : 0;
}

function syncAlignmentButtons(value = "left") {
  const current = normalizeTextAlign(value);
  alignmentButtons.forEach((button) => {
    const active = button.dataset.align === current;
    button.classList.toggle("is-active", active);
    button.classList.toggle("primary", active);
    button.classList.toggle("ghost", !active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function syncRotationSummary(value = 0) {
  const summaryEl = document.getElementById("rotationSummary");
  if (!summaryEl) return;
  summaryEl.textContent = `目前角度：${normalizeBoxRotation(value)}°`;
}

function setThumbsCollapsed(collapsed) {
  if (!sidebarEl || !toggleThumbsBtn) return;
  sidebarEl.classList.toggle("is-thumbs-collapsed", collapsed);
  toggleThumbsBtn.textContent = collapsed ? "顯示頁面縮圖" : "隱藏頁面縮圖";
  toggleThumbsBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

function fitToWidth() {
  if (!viewerEl || !state.pages.length) return;
  const viewerWidth = viewerEl.clientWidth;
  if (viewerWidth < 100) return;

  const pageIdx = state.activePageIdx ?? 0;
  const page = state.pages[pageIdx];
  if (!page) return;

  const naturalWidth = page.imageSize?.[0] || 1000;
  const targetWidth = viewerWidth - 100; // Horizontal padding/margin 64
  const idealZoom = targetWidth / naturalWidth;
  
  setZoomPercent(idealZoom * 100);
}

function setActiveSidebarRail(targetId) {
  sidebarRailButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.sidebarTarget === targetId);
  });
}

function setSidebarSection(targetId) {
  const sections = ["sidebarPagesSection", "sidebarToolsSection", "sidebarConsistencySection", "sidebarShortcutsSection"];
  sections.forEach((sectionId) => {
    const sectionEl = document.getElementById(sectionId);
    if (!sectionEl) return;
    const active = sectionId === targetId;
    sectionEl.hidden = !active;
    sectionEl.classList.toggle("is-active", active);
  });
  setActiveSidebarRail(targetId);
  if (targetId === "sidebarConsistencySection") {
    refreshAllConsistencyPanels();
  }
}

function syncViewModeButton() {
  if (!toggleViewModeBtn) return;
  const isContinuous = state.viewMode === "continuous";
  toggleViewModeBtn.textContent = isContinuous ? "切換到單頁模式" : "切換到連續模式";
  toggleViewModeBtn.setAttribute("aria-pressed", isContinuous ? "true" : "false");
}

function setViewMode(mode) {
  const nextMode = mode === "continuous" ? "continuous" : "single";
  if (state.viewMode === nextMode) {
    syncViewModeButton();
    return;
  }
  state.viewMode = nextMode;
  clearSelection();
  renderPages();
  syncViewModeButton();
  if (nextMode === "continuous") {
    const page = state.pages[state.activePageIdx];
    page?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (pagesEl) {
    pagesEl.scrollTo({ top: 0, left: 0, behavior: "smooth" });
  }
}

function setSelectionMode(mode) {
  state.selectionMode = mode === "retranslate" ? "retranslate" : "boxes";
  if (!regionTranslateBtn) return;
  if (state.selectionMode === "retranslate") {
    regionTranslateBtn.textContent = "取消補翻選區";
    regionTranslateBtn.classList.add("primary");
    regionTranslateBtn.classList.remove("ghost");
  } else {
    regionTranslateBtn.textContent = "補翻選區";
    regionTranslateBtn.classList.add("ghost");
    regionTranslateBtn.classList.remove("primary");
  }
}

function openRegionPreviewModal(preview) {
  state.pendingRegionPreview = preview;
  if (regionPreviewImageEl) {
    regionPreviewImageEl.src = preview.image_data_url || "";
  }
  if (regionPreviewTextEl) {
    regionPreviewTextEl.value = preview.source_text || "";
  }
  if (regionPreviewModal) {
    regionPreviewModal.hidden = false;
  }
}

function closeRegionPreviewModal() {
  state.pendingRegionPreview = null;
  if (regionPreviewModal) {
    regionPreviewModal.hidden = true;
  }
  if (regionPreviewImageEl) {
    regionPreviewImageEl.removeAttribute("src");
  }
  if (regionPreviewTextEl) {
    regionPreviewTextEl.value = "";
  }
}

function normalizePreviewText(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

function normalizeConsistencyText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function getConsistencyGroupByKey(key) {
  return state.consistencyGroups.find((group) => group.key === key) || null;
}

function buildConsistencyGroups() {
  const groups = new Map();
  state.pages.forEach((page, pageIdx) => {
    page.boxes.forEach((box, boxIdx) => {
      if (!box || box.deleted) return;
      const sourceNormalized = String(box.tmSourceNormalized || "").trim();
      if (!sourceNormalized) return;
      const targetText = normalizeConsistencyText(box.text);
      if (!targetText) return;
      const sourceText = String(box.tmSourceText || sourceNormalized).trim() || sourceNormalized;
      const groupKey = sourceNormalized;
      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          key: groupKey,
          sourceNormalized,
          sourceText,
          boxes: [],
          variantsMap: new Map(),
        });
      }
      const group = groups.get(groupKey);
      group.boxes.push({
        pageIdx,
        boxIdx,
        pageNumber: (page.pageIndex ?? pageIdx) + 1,
        boxId: box.id,
        targetText,
      });
      if (!group.variantsMap.has(targetText)) {
        group.variantsMap.set(targetText, {
          text: targetText,
          count: 0,
          pages: new Set(),
        });
      }
      const variant = group.variantsMap.get(targetText);
      variant.count += 1;
      variant.pages.add((page.pageIndex ?? pageIdx) + 1);
    });
  });

  return Array.from(groups.values())
    .map((group) => ({
      key: group.key,
      sourceNormalized: group.sourceNormalized,
      sourceText: group.sourceText,
      boxes: group.boxes,
      variants: Array.from(group.variantsMap.values()).map((variant) => ({
        text: variant.text,
        count: variant.count,
        pages: Array.from(variant.pages).sort((a, b) => a - b),
      })).sort((a, b) => b.count - a.count || a.text.localeCompare(b.text)),
    }))
    .filter((group) => group.variants.length > 1)
    .sort((a, b) => b.boxes.length - a.boxes.length || b.variants.length - a.variants.length);
}

function renderConsistencyDetail(group) {
  if (!consistencyDetailEl || !consistencySourceTitleEl || !consistencySourceMetaEl || !consistencyVariantListEl) return;
  if (!group) {
    consistencyDetailEl.hidden = true;
    consistencyVariantListEl.innerHTML = "";
    if (consistencyTargetTextEl) consistencyTargetTextEl.value = "";
    return;
  }
  consistencyDetailEl.hidden = false;
  consistencySourceTitleEl.textContent = group.sourceText || group.sourceNormalized;
  consistencySourceMetaEl.textContent = `共 ${group.boxes.length} 個文字框，${group.variants.length} 種譯文`;
  consistencyVariantListEl.innerHTML = "";
  group.variants.forEach((variant, index) => {
    const label = document.createElement("label");
    label.className = "consistency-variant";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "consistencyVariant";
    radio.value = variant.text;
    radio.checked = index === 0;
    radio.addEventListener("change", () => {
      if (radio.checked && consistencyTargetTextEl) {
        consistencyTargetTextEl.value = variant.text;
      }
    });
    const body = document.createElement("div");
    body.className = "consistency-variant__body";
    const title = document.createElement("p");
    title.className = "consistency-variant__title";
    title.textContent = variant.text;
    const meta = document.createElement("p");
    meta.className = "consistency-variant__meta";
    meta.textContent = `出現 ${variant.count} 次，頁面 ${variant.pages.join(", ")}`;
    body.appendChild(title);
    body.appendChild(meta);
    label.appendChild(radio);
    label.appendChild(body);
    consistencyVariantListEl.appendChild(label);
  });
  if (consistencyTargetTextEl) {
    consistencyTargetTextEl.value = group.variants[0]?.text || "";
  }
}

function renderConsistencyPanel() {
  if (!consistencyListEl || !consistencySummaryEl) return;
  consistencyListEl.innerHTML = "";
  state.consistencyGroups = buildConsistencyGroups();
  if (!state.consistencyGroups.length) {
    state.selectedConsistencyKey = null;
    consistencySummaryEl.textContent = "目前沒有偵測到文件內相同來源詞的譯文衝突";
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "如果你剛修改過文字內容，可以按上方按鈕重新掃描";
    consistencyListEl.appendChild(empty);
    renderConsistencyDetail(null);
    return;
  }

  if (!getConsistencyGroupByKey(state.selectedConsistencyKey)) {
    state.selectedConsistencyKey = state.consistencyGroups[0].key;
  }
  consistencySummaryEl.textContent = `找到 ${state.consistencyGroups.length} 組疑似不一致詞彙`;
  state.consistencyGroups.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "consistency-card";
    if (group.key === state.selectedConsistencyKey) {
      button.classList.add("is-active");
    }
    button.addEventListener("click", () => {
      state.selectedConsistencyKey = group.key;
      renderConsistencyPanel();
    });
    const title = document.createElement("p");
    title.className = "consistency-card__title";
    title.textContent = group.sourceText || group.sourceNormalized;
    const meta = document.createElement("p");
    meta.className = "consistency-card__meta";
    meta.textContent = `${group.variants.length} 種譯文，${group.boxes.length} 個文字框`;
    button.appendChild(title);
    button.appendChild(meta);
    consistencyListEl.appendChild(button);
  });
  renderConsistencyDetail(getConsistencyGroupByKey(state.selectedConsistencyKey));
}

function refreshConsistencyPanel() {
  renderConsistencyPanel();
}

function normalizeSourceTerm(text) {
  return String(text || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function escapeRegExp(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isParagraphSourceText(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  return value.length >= 28 || /[\r\n]/.test(value) || /[，,.;:；：!?]/.test(value);
}

function isShortSourceTerm(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  return value.length >= 2 && value.length <= 18 && !/[\r\n]/.test(value);
}

function getParagraphTermGroupByKey(key) {
  return state.paragraphTermGroups.find((group) => group.key === key) || null;
}

function buildParagraphTermGroups() {
  const candidateMap = new Map();
  const paragraphBoxes = [];

  const addCandidate = (sourceText, suggestedTarget = "") => {
    const cleanedSource = String(sourceText || "").trim();
    const normalizedSource = normalizeSourceTerm(cleanedSource);
    if (!isShortSourceTerm(cleanedSource) || !normalizedSource) return;
    if (!candidateMap.has(normalizedSource)) {
      candidateMap.set(normalizedSource, {
        key: normalizedSource,
        sourceText: cleanedSource,
        sourceNormalized: normalizedSource,
        suggestedTarget: String(suggestedTarget || "").trim(),
        candidateTargets: new Set(),
      });
    }
    const candidate = candidateMap.get(normalizedSource);
    if (cleanedSource.length < candidate.sourceText.length) {
      candidate.sourceText = cleanedSource;
    }
    if (suggestedTarget) {
      candidate.suggestedTarget = candidate.suggestedTarget || String(suggestedTarget).trim();
      candidate.candidateTargets.add(String(suggestedTarget).trim());
    }
  };

  glossaryEntries.forEach((entry) => {
    if (!entry) return;
    addCandidate(entry.cn, entry.en);
  });

  state.pages.forEach((page, pageIdx) => {
    page.boxes.forEach((box, boxIdx) => {
      if (!box || box.deleted) return;
      const sourceText = String(box.tmSourceText || "").trim();
      const sourceNormalized = normalizeSourceTerm(box.tmSourceNormalized || sourceText);
      const targetText = normalizeConsistencyText(box.text);
      if (isParagraphSourceText(sourceText)) {
        paragraphBoxes.push({
          pageIdx,
          boxIdx,
          pageNumber: (page.pageIndex ?? pageIdx) + 1,
          sourceText,
          sourceNormalized: normalizeSourceTerm(sourceText),
          targetText,
        });
        return;
      }
      if (isShortSourceTerm(sourceText) && sourceNormalized) {
        addCandidate(sourceText, targetText);
      }
    });
  });

  candidateMap.forEach((candidate) => {
    const directCandidate = normalizeConsistencyText(candidate.suggestedTarget);
    if (directCandidate) {
      candidate.candidateTargets.add(directCandidate);
    }
  });

  const groups = [];
  candidateMap.forEach((candidate) => {
    const matchedParagraphs = paragraphBoxes.filter((item) => item.sourceNormalized.includes(candidate.sourceNormalized));
    if (matchedParagraphs.length < 2) return;

    const variantMap = new Map();
    let unmatchedCount = 0;
    matchedParagraphs.forEach((item) => {
      let matchedVariant = "";
      Array.from(candidate.candidateTargets)
        .sort((a, b) => b.length - a.length)
        .some((term) => {
          if (!term) return false;
          const found = item.targetText.toLowerCase().includes(term.toLowerCase());
          if (found) {
            matchedVariant = term;
          }
          return found;
        });

      if (!matchedVariant) {
        unmatchedCount += 1;
      } else {
        if (!variantMap.has(matchedVariant)) {
          variantMap.set(matchedVariant, { text: matchedVariant, count: 0, pages: new Set() });
        }
        const variant = variantMap.get(matchedVariant);
        variant.count += 1;
        variant.pages.add(item.pageNumber);
      }
    });

    const foundVariants = Array.from(variantMap.values()).map((variant) => ({
      text: variant.text,
      count: variant.count,
      pages: Array.from(variant.pages).sort((a, b) => a - b),
    })).sort((a, b) => b.count - a.count || a.text.localeCompare(b.text));

    const hasConflict = foundVariants.length > 1
      || (foundVariants.length === 1 && unmatchedCount > 0)
      || (candidate.suggestedTarget
        && foundVariants.some((variant) => normalizeConsistencyText(variant.text).toLowerCase() !== candidate.suggestedTarget.toLowerCase()));
    if (!hasConflict) return;

    groups.push({
      key: candidate.key,
      sourceText: candidate.sourceText,
      sourceNormalized: candidate.sourceNormalized,
      suggestedTarget: candidate.suggestedTarget,
      foundVariants,
      unmatchedCount,
      paragraphBoxes: matchedParagraphs.map((item) => ({
        pageIdx: item.pageIdx,
        boxIdx: item.boxIdx,
        pageNumber: item.pageNumber,
        preview: item.targetText.slice(0, 140),
      })),
    });
  });

  return groups.sort((a, b) => b.paragraphBoxes.length - a.paragraphBoxes.length || b.foundVariants.length - a.foundVariants.length);
}

function renderParagraphTermDetail(group) {
  if (!paragraphTermDetailEl || !paragraphTermTitleEl || !paragraphTermMetaEl || !paragraphTermVariantListEl || !paragraphTermPreviewListEl) return;
  if (!group) {
    paragraphTermDetailEl.hidden = true;
    paragraphTermVariantListEl.innerHTML = "";
    paragraphTermPreviewListEl.innerHTML = "";
    if (paragraphReplaceFromEl) paragraphReplaceFromEl.value = "";
    if (paragraphReplaceToEl) paragraphReplaceToEl.value = "";
    return;
  }

  paragraphTermDetailEl.hidden = false;
  paragraphTermTitleEl.textContent = group.sourceText;
  paragraphTermMetaEl.textContent = `影響 ${group.paragraphBoxes.length} 個段落，已辨識 ${group.foundVariants.length} 種譯法`;
  paragraphTermVariantListEl.innerHTML = "";
  group.foundVariants.forEach((variant, index) => {
    const card = document.createElement("div");
    card.className = "consistency-variant";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "paragraphTermVariant";
    radio.value = variant.text;
    radio.checked = index === 0;
    radio.addEventListener("change", () => {
      if (radio.checked && paragraphReplaceFromEl) {
        paragraphReplaceFromEl.value = variant.text;
      }
    });
    const body = document.createElement("div");
    body.className = "consistency-variant__body";
    const title = document.createElement("p");
    title.className = "consistency-variant__title";
    title.textContent = variant.text;
    const meta = document.createElement("p");
    meta.className = "consistency-variant__meta";
    meta.textContent = `出現 ${variant.count} 次，頁面 ${variant.pages.join(", ")}`;
    body.appendChild(title);
    body.appendChild(meta);
    card.appendChild(radio);
    card.appendChild(body);
    paragraphTermVariantListEl.appendChild(card);
  });

  paragraphTermPreviewListEl.innerHTML = "";
  group.paragraphBoxes.slice(0, 6).forEach((item) => {
    const preview = document.createElement("div");
    preview.className = "paragraph-term-preview";
    const meta = document.createElement("p");
    meta.className = "paragraph-term-preview__meta";
    meta.textContent = `第 ${item.pageNumber} 頁`;
    const text = document.createElement("p");
    text.className = "paragraph-term-preview__text";
    text.textContent = item.preview;
    preview.appendChild(meta);
    preview.appendChild(text);
    paragraphTermPreviewListEl.appendChild(preview);
  });

  if (paragraphReplaceFromEl) {
    paragraphReplaceFromEl.value = group.foundVariants[0]?.text || "";
  }
  if (paragraphReplaceToEl) {
    paragraphReplaceToEl.value = group.suggestedTarget || group.foundVariants[0]?.text || "";
  }
}

function renderParagraphTermPanel() {
  if (!paragraphTermListEl || !paragraphTermSummaryEl) return;
  paragraphTermListEl.innerHTML = "";
  state.paragraphTermGroups = buildParagraphTermGroups();
  if (!state.paragraphTermGroups.length) {
    state.selectedParagraphTermKey = null;
    paragraphTermSummaryEl.textContent = "目前沒有偵測到需要人工統一的段落術語";
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "系統會優先使用文件中短詞與 glossary 當成候選術語";
    paragraphTermListEl.appendChild(empty);
    renderParagraphTermDetail(null);
    return;
  }

  if (!getParagraphTermGroupByKey(state.selectedParagraphTermKey)) {
    state.selectedParagraphTermKey = state.paragraphTermGroups[0].key;
  }
  paragraphTermSummaryEl.textContent = `找到 ${state.paragraphTermGroups.length} 組段落術語可人工統一`;
  state.paragraphTermGroups.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "consistency-card";
    if (group.key === state.selectedParagraphTermKey) {
      button.classList.add("is-active");
    }
    button.addEventListener("click", () => {
      state.selectedParagraphTermKey = group.key;
      renderParagraphTermPanel();
    });
    const title = document.createElement("p");
    title.className = "consistency-card__title";
    title.textContent = group.sourceText;
    const meta = document.createElement("p");
    meta.className = "consistency-card__meta";
    meta.textContent = `${group.paragraphBoxes.length} 個段落，${group.foundVariants.length} 種已辨識譯法`;
    button.appendChild(title);
    button.appendChild(meta);
    paragraphTermListEl.appendChild(button);
  });
  renderParagraphTermDetail(getParagraphTermGroupByKey(state.selectedParagraphTermKey));
}

function getPendingMergeNotices() {
  return (state.mergeNotices || []).filter((notice) => (notice?.status || "pending") === "pending");
}

function formatMergeNoticeScope(notice) {
  const primaryPage = Number(notice?.primary_page_index_0based);
  const secondaryPage = Number(notice?.secondary_page_index_0based);
  if (!Number.isFinite(primaryPage)) return "未知頁面";
  if (!Number.isFinite(secondaryPage) || secondaryPage === primaryPage) {
    return `第 ${primaryPage + 1} 頁`;
  }
  return `第 ${primaryPage + 1} 頁 -> 第 ${secondaryPage + 1} 頁`;
}

async function updateMergeNoticeStatus(noticeId, status) {
  const jobId = document.body.dataset.jobId;
  if (!jobId || !noticeId) return false;
  try {
    const res = await fetch(`/api/job/${jobId}/merge-notices/${encodeURIComponent(noticeId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) return false;
    const payload = await res.json().catch(() => ({}));
    const notice = payload.notice || null;
    if (notice) {
      const idx = state.mergeNotices.findIndex((item) => item.notice_id === notice.notice_id);
      if (idx >= 0) {
        state.mergeNotices[idx] = notice;
      } else {
        state.mergeNotices.push(notice);
      }
    }
    renderMergeNotices();
    return true;
  } catch (error) {
    return false;
  }
}

function focusMergeNotice(notice) {
  if (!notice) return;
  const targetPageIdx = Number.isFinite(Number(notice.primary_page_index_0based))
    ? Number(notice.primary_page_index_0based)
    : 0;
  setSidebarSection("sidebarConsistencySection");
  setActivePage(targetPageIdx);
  clearSelection();

  const primaryBoxId = Number(notice.primary_box_id);
  const secondaryPageIdx = Number(notice.secondary_page_index_0based);
  const secondaryBoxId = Number(notice.secondary_box_id);

  const primaryBoxIdx = state.pages[targetPageIdx]?.boxes.findIndex((box) => box.id === primaryBoxId) ?? -1;
  if (primaryBoxIdx >= 0) {
    setSelection(targetPageIdx, primaryBoxIdx, false);
  }
  if (secondaryPageIdx === targetPageIdx) {
    const secondaryBoxIdx = state.pages[targetPageIdx]?.boxes.findIndex((box) => box.id === secondaryBoxId) ?? -1;
    if (secondaryBoxIdx >= 0 && secondaryBoxIdx !== primaryBoxIdx) {
      setSelection(targetPageIdx, secondaryBoxIdx, true);
    }
  }
  setStatus(`已定位到 ${formatMergeNoticeScope(notice)} 的合併提醒`);
}

function renderMergeNotices() {
  if (!mergeNoticeSectionEl || !mergeNoticeSummaryEl || !mergeNoticeListEl) return;
  const pendingNotices = getPendingMergeNotices();
  mergeNoticeListEl.innerHTML = "";
  mergeNoticeSectionEl.hidden = pendingNotices.length === 0;
  if (!pendingNotices.length) {
    mergeNoticeSummaryEl.textContent = "";
    return;
  }
  mergeNoticeSummaryEl.textContent = `共有 ${pendingNotices.length} 筆模型疑似自行合併的段落，請人工確認`;
  pendingNotices.forEach((notice) => {
    const card = document.createElement("article");
    card.className = "merge-notice-card";

    const title = document.createElement("p");
    title.className = "merge-notice-card__title";
    title.textContent = `${formatMergeNoticeScope(notice)} · ${notice.primary_custom_id || ""} + ${notice.secondary_custom_id || ""}`;

    const sourceLabel = document.createElement("p");
    sourceLabel.className = "merge-notice-card__label";
    sourceLabel.textContent = "來源文字";

    const sourceBody = document.createElement("pre");
    sourceBody.className = "merge-notice-card__body";
    sourceBody.textContent = notice.source_text || "";

    const targetLabel = document.createElement("p");
    targetLabel.className = "merge-notice-card__label";
    targetLabel.textContent = "模型合併後譯文";

    const targetBody = document.createElement("pre");
    targetBody.className = "merge-notice-card__body";
    targetBody.textContent = notice.suggested_translation || "";

    const actions = document.createElement("div");
    actions.className = "button-row merge-notice-card__actions";

    const inspectBtn = document.createElement("button");
    inspectBtn.type = "button";
    inspectBtn.className = "ghost";
    inspectBtn.textContent = "前往檢查";
    inspectBtn.addEventListener("click", () => focusMergeNotice(notice));

    const acceptBtn = document.createElement("button");
    acceptBtn.type = "button";
    acceptBtn.className = "primary";
    acceptBtn.textContent = "標記已處理";
    acceptBtn.addEventListener("click", async () => {
      const ok = await updateMergeNoticeStatus(notice.notice_id, "accepted");
      setStatus(ok ? "已標記為處理完成" : "更新合併提醒失敗");
    });

    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "ghost";
    rejectBtn.textContent = "忽略";
    rejectBtn.addEventListener("click", async () => {
      const ok = await updateMergeNoticeStatus(notice.notice_id, "rejected");
      setStatus(ok ? "已忽略此合併提醒" : "更新合併提醒失敗");
    });

    actions.appendChild(inspectBtn);
    actions.appendChild(acceptBtn);
    actions.appendChild(rejectBtn);

    card.appendChild(title);
    card.appendChild(sourceLabel);
    card.appendChild(sourceBody);
    card.appendChild(targetLabel);
    card.appendChild(targetBody);
    card.appendChild(actions);
    mergeNoticeListEl.appendChild(card);
  });
}

function refreshAllConsistencyPanels() {
  renderMergeNotices();
  renderConsistencyPanel();
  renderParagraphTermPanel();
}

let glossaryEntries = [];
let currentJobId = null;
let batchPageModalResolver = null;

function normalizeGlossaryText(value) {
  return String(value || "").trim();
}

function setGlossaryActionButtonState(button, label, disabled = false) {
  if (!button) return;
  button.textContent = label;
  button.disabled = disabled;
}

function flashGlossarySaveSuccess(button, label) {
  if (!button) return;
  button.textContent = "已儲存";
  button.disabled = true;
  window.setTimeout(() => {
    button.textContent = label;
    button.disabled = false;
  }, 1200);
}

function findGlossaryEntryByCn(cn) {
  const normalizedCn = normalizeGlossaryText(cn);
  if (!normalizedCn) return null;
  return glossaryEntries.find((entry) => normalizeGlossaryText(entry?.cn) === normalizedCn) || null;
}

function renderGlossaryQuickState() {
  const cn = normalizeGlossaryText(glossaryCnEl?.value);
  const existingEntry = findGlossaryEntryByCn(cn);
  if (addGlossaryBtn) {
    addGlossaryBtn.textContent = existingEntry ? "儲存修改" : "儲存自訂詞彙";
  }
  if (addGlossaryRetranslateBtn) {
    addGlossaryRetranslateBtn.textContent = existingEntry ? "儲存修改並重新翻譯" : "儲存並重新翻譯";
  }
  if (!glossaryQuickHintEl) return;
  if (!cn) {
    glossaryQuickHintEl.textContent = "輸入中文詞彙後，可建立新的自訂詞彙或覆蓋同名自訂詞彙。";
    return;
  }
  if (existingEntry) {
    glossaryQuickHintEl.textContent = `目前已有自訂詞彙：英文「${existingEntry.en}」。儲存後會直接覆蓋這筆詞彙。`;
    return;
  }
  glossaryQuickHintEl.textContent = `目前沒有「${cn}」的自訂詞彙，儲存後會新增一筆新的使用者詞彙。`;
}

async function loadGlossary() {
  try {
    const res = await fetch(`/api/glossary`);
    if (!res.ok) return;
    const payload = await res.json();
    glossaryEntries = Array.isArray(payload.glossary) ? payload.glossary : [];
    renderGlossaryQuickState();
    refreshAllConsistencyPanels();
  } catch (error) {
    // ignore
  }
}

async function saveGlossary() {
  try {
    const res = await fetch(`/api/glossary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ glossary: glossaryEntries }),
    });
    return res.ok;
  } catch (error) {
    return false;
  }
}

async function saveSystemPrompt(jobId) {
  if (!jobId) return;
  const prompt = systemPromptEl?.value ?? "";
  const idleLabel = savePromptBtn?.textContent || "儲存提示詞";
  setGlossaryActionButtonState(savePromptBtn, "儲存中...", true);
  try {
    const res = await fetch(`/api/job/${jobId}/system-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: prompt }),
    });
    if (!res.ok) {
      throw new Error("save prompt failed");
    }
    flashGlossarySaveSuccess(savePromptBtn, idleLabel);
    setStatus("已儲存提示詞");
    return true;
  } catch (error) {
    setGlossaryActionButtonState(savePromptBtn, idleLabel, false);
    setStatus("儲存提示詞失敗");
    return false;
  }
}

async function retranslateDocumentImmediately() {
  const jobId = document.body.dataset.jobId;
  if (!jobId || !retranslateDocumentBtn) return;
  retranslateDocumentBtn.disabled = true;
  const idleLabel = "立即重新翻譯整份文件";
  retranslateDocumentBtn.textContent = "儲存中...";

  const promptSaved = await saveSystemPrompt(jobId);
  if (!promptSaved) {
    retranslateDocumentBtn.disabled = false;
    retranslateDocumentBtn.textContent = idleLabel;
    return;
  }

  const saved = await saveEdits(false, { silent: true });
  if (!saved) {
    retranslateDocumentBtn.disabled = false;
    retranslateDocumentBtn.textContent = idleLabel;
    setStatus("重新翻譯前儲存失敗");
    return;
  }

  retranslateDocumentBtn.textContent = "重新翻譯中...";
  setStatus("正在重新翻譯整份文件...");
  try {
    const res = await fetch(`/api/job/${jobId}/retranslate-document`, {
      method: "POST",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `重新翻譯失敗：${body.error}` : "重新翻譯失敗");
      retranslateDocumentBtn.disabled = false;
      retranslateDocumentBtn.textContent = idleLabel;
      return;
    }
    await loadJobData(jobId, { preserveActivePage: true });
    retranslateDocumentBtn.textContent = "已完成";
    setStatus(`已即時重新翻譯 ${Number(body.updated_count || 0)} 個文字框`);
    window.setTimeout(() => {
      retranslateDocumentBtn.disabled = false;
      retranslateDocumentBtn.textContent = idleLabel;
    }, 1200);
  } catch (error) {
    retranslateDocumentBtn.disabled = false;
    retranslateDocumentBtn.textContent = idleLabel;
    setStatus("重新翻譯失敗");
  }
}

async function addGlossaryEntry(options = {}) {
  const { retranslate = false } = options;
  const cn = normalizeGlossaryText(glossaryCnEl?.value);
  const en = normalizeGlossaryText(glossaryEnEl?.value);
  if (!cn || !en) {
    setStatus("請輸入中文與英文詞彙");
    return false;
  }
  const actionButton = retranslate ? addGlossaryRetranslateBtn : addGlossaryBtn;
  const idleLabel = actionButton?.textContent || (retranslate ? "儲存並重新翻譯" : "儲存自訂詞彙");
  setGlossaryActionButtonState(actionButton, retranslate ? "儲存中..." : "儲存中...", true);
  const existingEntry = findGlossaryEntryByCn(cn);
  glossaryEntries = glossaryEntries.filter((entry) => normalizeGlossaryText(entry?.cn) !== cn);
  glossaryEntries.unshift({ cn, en });
  renderGlossaryQuickState();
  refreshAllConsistencyPanels();
  const savedGlossary = await saveGlossary();
  if (!savedGlossary) {
    setGlossaryActionButtonState(actionButton, idleLabel, false);
    setStatus("儲存詞彙失敗");
    return false;
  }
  if (!retranslate) {
    flashGlossarySaveSuccess(addGlossaryBtn, idleLabel);
    setStatus(existingEntry ? "已修改自訂詞彙" : "已加入自訂詞彙");
    return true;
  }
  if (!currentJobId) {
    setGlossaryActionButtonState(actionButton, idleLabel, false);
    setStatus("找不到目前任務，無法重翻");
    return false;
  }
  const savedEdits = await saveEdits(false, { silent: true });
  if (!savedEdits) {
    setGlossaryActionButtonState(actionButton, idleLabel, false);
    setStatus("重翻前儲存失敗");
    return false;
  }
  if (addGlossaryRetranslateBtn) {
    addGlossaryRetranslateBtn.disabled = true;
    addGlossaryRetranslateBtn.textContent = "重翻中...";
  }
  setStatus(`${existingEntry ? "已修改自訂詞彙" : "已加入自訂詞彙"}，正在重翻包含「${cn}」的命中框...`);
  try {
    const res = await fetch(`/api/job/${currentJobId}/glossary-retranslate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cn }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setGlossaryActionButtonState(actionButton, idleLabel, false);
      setStatus(body.error ? `重翻失敗：${body.error}` : "重翻失敗");
      return false;
    }
    await loadJobData(currentJobId, { preserveActivePage: true });
    flashGlossarySaveSuccess(addGlossaryRetranslateBtn, idleLabel);
    setStatus(`已重翻 ${Number(body.updated_count || 0)} 個命中框`);
    return true;
  } catch (error) {
    setGlossaryActionButtonState(actionButton, idleLabel, false);
    setStatus("重翻失敗");
    return false;
  }
}

function openGlossaryModal() {
  if (!glossaryPromptModal) return;
  renderGlossaryQuickState();
  glossaryPromptModal.hidden = false;
  glossaryCnEl?.focus();
}

function closeGlossaryModal() {
  if (!glossaryPromptModal) return;
  glossaryPromptModal.hidden = true;
}

function getSelectedTemplate() {
  const templateId = templateSelectEl?.value || "";
  return documentTemplates.find((item) => item.id === templateId) || null;
}

function renderTemplateSummary(template = null) {
  if (!templateSummaryEl) return;
  if (!template) {
    templateSummaryEl.textContent = documentTemplates.length
      ? "請選擇要套用的模板"
      : "尚未建立模板";
    return;
  }
  const pageCount = Array.isArray(template.pages) ? template.pages.length : 0;
  const boxCount = (template.pages || []).reduce(
    (sum, page) => sum + (Array.isArray(page.boxes) ? page.boxes.length : 0),
    0,
  );
  templateSummaryEl.textContent = `共 ${pageCount} 頁，${boxCount} 個模板文字框`;
}

function renderTemplateOptions(selectedId = "") {
  if (!templateSelectEl) return;
  templateSelectEl.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "請選擇模板";
  templateSelectEl.appendChild(placeholder);
  documentTemplates.forEach((template) => {
    if (template.status && template.status !== "saved") return;
    const option = document.createElement("option");
    option.value = template.id;
    option.textContent = template.name || template.display_name || template.id;
    if (template.id === selectedId) {
      option.selected = true;
    }
    templateSelectEl.appendChild(option);
  });
  renderTemplateSummary(getSelectedTemplate());
}

async function loadDocumentTemplates(options = {}) {
  const { selectedId = "" } = options;
  try {
    const res = await fetch(`/api/document-templates`);
    if (!res.ok) {
      renderTemplateSummary(null);
      return;
    }
    const payload = await res.json().catch(() => ({}));
    documentTemplates = Array.isArray(payload.templates) ? payload.templates : [];
    renderTemplateOptions(selectedId);
  } catch (error) {
    renderTemplateSummary(null);
  }
}

function renderTemplateTargetJobs() {
  if (!templateTargetJobSelectEl) return;
  const currentJobId = document.body.dataset.jobId || "";
  templateTargetJobSelectEl.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "請選擇翻譯任務";
  templateTargetJobSelectEl.appendChild(placeholder);
  templateApplyJobs
    .filter((job) => job.job_id !== currentJobId)
    .forEach((job) => {
      const option = document.createElement("option");
      option.value = job.job_id;
      option.textContent = job.job_name && job.job_name.trim()
        ? `${job.job_name} (${job.job_id.slice(0, 8)})`
        : job.job_id.slice(0, 8);
      templateTargetJobSelectEl.appendChild(option);
    });
}

async function loadTemplateTargetJobs() {
  if (!templateMode || !templateTargetJobSelectEl) return;
  try {
    const res = await fetch(`/api/jobs`);
    if (!res.ok) return;
    const payload = await res.json().catch(() => ({}));
    templateApplyJobs = Array.isArray(payload.jobs) ? payload.jobs : [];
    renderTemplateTargetJobs();
  } catch (error) {
    // ignore
  }
}

function buildTemplatePayloadFromState(templateName) {
  const pages = state.pages.map((page) => {
    const width = Number(page?.imageSize?.[0]) || 0;
    const height = Number(page?.imageSize?.[1]) || 0;
    if (width <= 0 || height <= 0) return null;
    const boxes = page.boxes
      .filter((box) => (
        !box.deleted
        && String(box.text || "").trim()
        && (templateMode || box.autoGenerated)
      ))
      .map((box) => ({
        x_ratio: box.bbox.x / width,
        y_ratio: box.bbox.y / height,
        w_ratio: box.bbox.w / width,
        h_ratio: box.bbox.h / height,
        text: box.text,
        font_size: box.fontSize,
        color: box.color,
        text_align: normalizeTextAlign(box.align),
        rotation: normalizeBoxRotation(box.rotation),
        no_clip: !!box.noClip,
      }));
    if (!boxes.length) return null;
    return {
      page_index_0based: page.pageIndex,
      boxes,
    };
  }).filter(Boolean);

  return {
    name: String(templateName || "").trim(),
    pages,
  };
}

async function saveCurrentAsTemplate() {
  const name = templateNameEl?.value?.trim() || "";
  if (!name) {
    setStatus("請先輸入模板名稱");
    return;
  }
  const payload = buildTemplatePayloadFromState(name);
  if (!payload.pages.length) {
    setStatus("目前沒有可保存的文字框");
    return;
  }
  const originalText = saveTemplateBtn?.textContent || "儲存為模板";
  if (saveTemplateBtn) {
    saveTemplateBtn.disabled = true;
    saveTemplateBtn.textContent = "儲存中...";
  }
  try {
    const res = await fetch(`/api/document-templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `儲存模板失敗：${body.error}` : "儲存模板失敗");
      return;
    }
    templateNameEl.value = "";
    await loadDocumentTemplates({ selectedId: body.template?.id || "" });
    setStatus(`已儲存模板「${body.template?.name || name}」`);
  } catch (error) {
    setStatus("儲存模板失敗");
  } finally {
    if (saveTemplateBtn) {
      saveTemplateBtn.disabled = false;
      saveTemplateBtn.textContent = originalText;
    }
  }
}

function openTemplateManagerModal() {
  if (!templateManagerModal) return;
  templateManagerModal.hidden = false;
  setTemplateApplyPreset("all");
  if (templateApplyInputEl) {
    templateApplyInputEl.value = "";
  }
  loadDocumentTemplates({ selectedId: templateSelectEl?.value || "" });
  loadTemplateTargetJobs();
}

function closeTemplateManagerModal() {
  if (!templateManagerModal) return;
  templateManagerModal.hidden = true;
}

function setTemplateApplyPreset(mode) {
  if (!templateApplyAllEl || !templateApplyAfterEl || !templateApplyManualEl || !templateApplyInputEl) return;
  templateApplyAllEl.checked = mode === "all";
  templateApplyAfterEl.checked = mode === "after";
  templateApplyManualEl.checked = mode === "manual";
  templateApplyInputEl.disabled = mode !== "manual";
}

function getTemplatePageIndexes(template) {
  return Array.from(
    new Set(
      (template?.pages || [])
        .map((page) => Number(page?.page_index_0based))
        .filter((pageIdx) => Number.isInteger(pageIdx) && pageIdx >= 0),
    ),
  ).sort((a, b) => a - b);
}

function getTemplateTargetPageLabel(templatePageIdxs) {
  if (!templatePageIdxs.length) {
    return "模板頁";
  }
  const pageLabels = templatePageIdxs.map((pageIdx) => `第 ${pageIdx + 1} 頁`).join("、");
  return `模板頁：${pageLabels}`;
}

function getTemplateApplyTargetPages(template) {
  const templatePageIdxs = getTemplatePageIndexes(template);
  if (!templatePageIdxs.length) {
    setStatus("模板沒有可套用的頁面");
    return null;
  }
  const mode = templateApplyAfterEl?.checked
    ? "after"
    : templateApplyManualEl?.checked
      ? "manual"
      : "all";
  let allowedPageIdxs = [];
  if (mode === "all") {
    allowedPageIdxs = parsePageSelectionInput("all", state.pages.length);
  } else if (mode === "after") {
    const firstTemplatePageIdx = templatePageIdxs[0];
    allowedPageIdxs = parsePageSelectionInput(
      "after",
      state.pages.length,
      firstTemplatePageIdx >= 0 ? [firstTemplatePageIdx] : [],
    );
  } else {
    allowedPageIdxs = parsePageSelectionInput(templateApplyInputEl?.value || "", state.pages.length);
  }
  if (!allowedPageIdxs.length) {
    setStatus("沒有符合的目標頁");
    return null;
  }
  return {
    templatePageIdxs,
    allowedPageIdxs,
  };
}

async function applyTemplateToDocument() {
  const template = getSelectedTemplate();
  if (!template) {
    setStatus("請先選擇模板");
    return;
  }
  const applyTarget = getTemplateApplyTargetPages(template);
  if (!applyTarget) {
    return;
  }
  const { templatePageIdxs, allowedPageIdxs } = applyTarget;
  const allowedPageSet = new Set(allowedPageIdxs);
  const createdBoxes = [];
  let nextId = state.pages.reduce((maxValue, page) => {
    const pageMax = page.boxes.reduce((innerMax, box) => Math.max(innerMax, Number(box.id) || 0), 0);
    return Math.max(maxValue, pageMax);
  }, 0) + 1;

  const addTemplateBoxesToPage = (templateBoxes, pageIdx) => {
    const page = pageIdx >= 0 ? state.pages[pageIdx] : null;
    const width = Number(page?.imageSize?.[0]) || 0;
    const height = Number(page?.imageSize?.[1]) || 0;
    if (!page || width <= 0 || height <= 0) return;
    (templateBoxes || []).forEach((templateBox) => {
      const box = {
        id: nextId++,
        bbox: {
          x: Math.max(0, Math.min(width, Number(templateBox.x_ratio) * width)),
          y: Math.max(0, Math.min(height, Number(templateBox.y_ratio) * height)),
          w: Math.max(1, Number(templateBox.w_ratio) * width),
          h: Math.max(1, Number(templateBox.h_ratio) * height),
        },
        text: templateBox.text || "",
        fontSize: Number(templateBox.font_size) || 16,
        color: templateBox.color || "#0000ff",
        align: normalizeTextAlign(templateBox.text_align),
        rotation: normalizeBoxRotation(templateBox.rotation),
        noClip: !!templateBox.no_clip,
        autoGenerated: true,
        tmSourceText: "",
        tmSourceNormalized: "",
        tmTargetLang: "",
        tmDocumentMode: "",
        deleted: false,
      };
      const maxX = Math.max(0, width - box.bbox.w);
      const maxY = Math.max(0, height - box.bbox.h);
      box.bbox.x = Math.max(0, Math.min(box.bbox.x, maxX));
      box.bbox.y = Math.max(0, Math.min(box.bbox.y, maxY));
      addBoxToPage(pageIdx, box);
      createdBoxes.push({ pageIdx, box: cloneBoxData(box) });
    });
  };

  if (templatePageIdxs.length === 1) {
    const templatePage = (template.pages || [])[0];
    allowedPageIdxs.forEach((pageIdx) => {
      addTemplateBoxesToPage(templatePage?.boxes || [], pageIdx);
    });
  } else {
    (template.pages || []).forEach((templatePage) => {
      const pageIdx = Number(templatePage.page_index_0based);
      if (!allowedPageSet.has(pageIdx)) return;
      addTemplateBoxesToPage(templatePage.boxes || [], pageIdx);
    });
  };

  if (!createdBoxes.length) {
    setStatus("模板沒有可套用到目前文件的頁面");
    return;
  }
  pushAction({ type: "add_boxes", boxes: createdBoxes });
  refreshAllConsistencyPanels();
  setStatus(`已套用模板「${template.name}」，新增 ${createdBoxes.length} 個文字框`);
  closeTemplateManagerModal();
}

async function deleteSelectedTemplate() {
  const template = getSelectedTemplate();
  if (!template) {
    setStatus("請先選擇模板");
    return;
  }
  const originalText = deleteTemplateBtn?.textContent || "刪除模板";
  if (deleteTemplateBtn) {
    deleteTemplateBtn.disabled = true;
    deleteTemplateBtn.textContent = "刪除中...";
  }
  try {
    const res = await fetch(`/api/document-templates/${template.id}`, {
      method: "DELETE",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `刪除模板失敗：${body.error}` : "刪除模板失敗");
      return;
    }
    await loadDocumentTemplates();
    setStatus(`已刪除模板「${template.name}」`);
  } catch (error) {
    setStatus("刪除模板失敗");
  } finally {
    if (deleteTemplateBtn) {
      deleteTemplateBtn.disabled = false;
      deleteTemplateBtn.textContent = originalText;
    }
  }
}

async function applyTemplateToTargetJob() {
  const template = getSelectedTemplate();
  const jobId = templateTargetJobSelectEl?.value || "";
  if (!template) {
    setStatus("請先選擇模板");
    return;
  }
  if (!jobId) {
    setStatus("請先選擇目標任務");
    return;
  }
  const originalText = applyTemplateToJobBtn?.textContent || "套用到目標任務";
  if (applyTemplateToJobBtn) {
    applyTemplateToJobBtn.disabled = true;
    applyTemplateToJobBtn.textContent = "套用中...";
  }
  try {
    const res = await fetch(`/api/document-templates/${template.id}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `套用模板失敗：${body.error}` : "套用模板失敗");
      return;
    }
    setStatus(`已套用模板到任務 ${jobId.slice(0, 8)}，新增 ${Number(body.created_count || 0)} 個文字框`);
  } catch (error) {
    setStatus("套用模板失敗");
  } finally {
    if (applyTemplateToJobBtn) {
      applyTemplateToJobBtn.disabled = false;
      applyTemplateToJobBtn.textContent = originalText;
    }
  }
}

function setBatchPagePreset(mode) {
  if (!batchPageAllEl || !batchPageAfterEl || !batchPageInputEl) return;
  batchPageAllEl.checked = mode === "all";
  batchPageAfterEl.checked = mode === "after";
  batchPageInputEl.disabled = mode === "all" || mode === "after";
}

function openBatchPageModal(sourcePageIdx, modeLabel, sourceLabelOverride = "") {
  if (!batchPageModal) return Promise.resolve(null);
  if (batchPageSourceHintEl) {
    batchPageSourceHintEl.textContent = sourceLabelOverride
      ? `${sourceLabelOverride}，請設定要${modeLabel}的目標頁`
      : `來源頁：第 ${sourcePageIdx + 1} 頁請設定要${modeLabel}的目標頁`;
  }
  if (batchPageInputEl) {
    batchPageInputEl.value = "";
  }
  setBatchPagePreset("all");
  batchPageModal.hidden = false;
  return new Promise((resolve) => {
    batchPageModalResolver = resolve;
    confirmBatchPageModalBtn?.focus();
  });
}

function finishBatchPageModal(result) {
  if (!batchPageModal) return;
  batchPageModal.hidden = true;
  const resolver = batchPageModalResolver;
  batchPageModalResolver = null;
  if (resolver) {
    resolver(result);
  }
}

function setBatchButtonState(status) {
  void status;
}

function renderBatchStatus(status) {
  if (!status || !statusEl) return;
  const label = status.status || "unknown";
  if (label === "completed") {
    setStatus("Batch 翻譯完成，已更新編輯內容");
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

function getSingleSelectedBox() {
  const selected = getSelectedBoxes();
  return selected.length === 1 ? selected[0] : null;
}

function getBoxElementTextNode(box) {
  return box?.element?.querySelector(".text") || null;
}

function setBoxText(page, box, nextText) {
  const value = String(nextText ?? "");
  box.text = value;
  const textEl = getBoxElementTextNode(box);
  if (textEl) {
    const isActiveEditor = document.activeElement === textEl && textEl.isContentEditable;
    if (!isActiveEditor && textEl.textContent !== value) {
      textEl.textContent = value;
      textEl.innerText = value;
    }
  }
  if (box.noClip || box._isExpanded) {
    updateBoxElement(page, box);
  }
}

function beginBoxTextEdit(box) {
  if (!box || box._editBefore) return;
  box._editBefore = cloneBoxData(box);
}

function insertEditorLineBreak(textEl) {
  if (!textEl) return;
  textEl.focus();
  if (document.queryCommandSupported?.("insertLineBreak")) {
    if (document.execCommand("insertLineBreak")) {
      return;
    }
  }
  if (document.queryCommandSupported?.("insertHTML")) {
    if (document.execCommand("insertHTML", false, "<br>")) {
      return;
    }
  }
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return;
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const br = document.createElement("br");
  range.insertNode(br);
  range.setStartAfter(br);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function insertEditorPlainText(textEl, text) {
  if (!textEl) return;
  const value = String(text ?? "").replace(/\r\n/g, "\n");
  textEl.focus();
  if (document.queryCommandSupported?.("insertText")) {
    if (document.execCommand("insertText", false, value)) {
      return;
    }
  }
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return;
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const textNode = document.createTextNode(value);
  range.insertNode(textNode);
  range.setStartAfter(textNode);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function commitBoxTextEdit(pageIdx, boxIdx, finalText) {
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (!page || !box) return;
  const normalized = String(finalText ?? "").trim();
  setBoxText(page, box, normalized);
  const before = box._editBefore;
  delete box._editBefore;
  if (!before) return;
  const after = cloneBoxData(box);
  if (before.text !== after.text) {
    pushAction({
      type: "update_boxes",
      updates: [{ pageIdx, boxId: box.id, before, after }],
    });
  }
}

function setContextInspectorEmpty(message = "請先點選一個翻譯文字框") {
  if (contextSummaryEl) contextSummaryEl.textContent = "請選取文字框";
  if (contextSourceTextEl) {
    contextSourceTextEl.value = "";
    contextSourceTextEl.placeholder = message;
    contextSourceTextEl.disabled = true;
  }
  if (contextTranslatedTextEl) {
    contextTranslatedTextEl.value = "";
    contextTranslatedTextEl.placeholder = message;
    contextTranslatedTextEl.disabled = true;
  }
  if (contextRetranslateBtn) {
    contextRetranslateBtn.classList.remove("ghost");
    contextRetranslateBtn.classList.add("primary", "retranslate-btn--idle");
    contextRetranslateBtn.classList.remove("retranslate-btn--ready", "retranslate-btn--busy");
    contextRetranslateBtn.textContent = "請先選取單一文字框";
    contextRetranslateBtn.disabled = true;
  }
  contextTranslatedEditKey = null;
  contextSourceEditKey = null;
}

function isContextSourceDirty(selected = null) {
  if (!contextSourceTextEl) return false;
  const current = String(contextSourceTextEl.value || "").trim();
  if (!current) return false;
  const boxSelection = selected || getSingleSelectedBox();
  if (!boxSelection) return false;
  const original = String(boxSelection.box?.tmSourceText || "").trim();
  return current !== original;
}

function syncContextRetranslateButton(selected = null) {
  if (!contextRetranslateBtn) return;
  const boxSelection = selected || getSingleSelectedBox();
  let stateName = "idle";
  let label = "請先選取單一文字框";
  const dirty = isContextSourceDirty(selected);
  if (!boxSelection) {
    stateName = getSelectedBoxes().length > 1 ? "multi" : "idle";
    label = stateName === "multi" ? "多選時無法重新翻譯" : "請先選取單一文字框";
  } else if (!String(contextSourceTextEl?.value || "").trim()) {
    stateName = "empty";
    label = "請先輸入修正後原始內容";
  } else if (!dirty) {
    stateName = "clean";
    label = "修改原始內容後可重新翻譯";
  } else {
    stateName = "ready";
    label = "用修正後原始內容重新翻譯";
  }
  contextRetranslateBtn.classList.remove(
    "retranslate-btn--idle",
    "retranslate-btn--ready",
    "retranslate-btn--busy",
    "ghost",
    "primary",
  );
  contextRetranslateBtn.classList.add(stateName === "ready" ? "primary" : "ghost");
  contextRetranslateBtn.classList.add(
    stateName === "ready" ? "retranslate-btn--ready" : "retranslate-btn--idle",
  );
  contextRetranslateBtn.textContent = label;
  contextRetranslateBtn.disabled = stateName !== "ready";
}

function syncContextInspector() {
  if (!contextSummaryEl) return;
  const selected = getSelectedBoxes();
  if (!selected.length) {
    setContextInspectorEmpty();
    return;
  }
  if (selected.length > 1) {
    if (contextSummaryEl) contextSummaryEl.textContent = `已選取 ${selected.length} 個文字框`;
    if (contextSourceTextEl) {
      contextSourceTextEl.value = "";
      contextSourceTextEl.placeholder = "多選時不可直接修正原始內容，請改為單選";
      contextSourceTextEl.disabled = true;
    }
    if (contextTranslatedTextEl) {
      contextTranslatedTextEl.value = "";
      contextTranslatedTextEl.placeholder = "多選時不可直接編輯譯文，請改為單選";
      contextTranslatedTextEl.disabled = true;
    }
    if (contextRetranslateBtn) {
      contextRetranslateBtn.disabled = true;
    }
    contextTranslatedEditKey = null;
    contextSourceEditKey = null;
    return;
  }

  const { page, box, pageIdx, boxIdx } = selected[0];
  const selectedKey = boxKey(pageIdx, boxIdx);
  if (contextSummaryEl) contextSummaryEl.textContent = `第 ${Number(page.pageIndex) + 1} 頁選取中`;
  if (contextSourceTextEl) {
    const sourceValue = String(box.tmSourceText || "").trim();
    if (document.activeElement !== contextSourceTextEl || contextSourceEditKey !== selectedKey) {
      contextSourceTextEl.value = sourceValue;
    } else if (contextSourceTextEl.value !== sourceValue) {
      contextSourceTextEl.value = sourceValue;
    }
    contextSourceTextEl.placeholder = "可在此修正原始內容";
    contextSourceTextEl.disabled = false;
  }
  if (contextTranslatedTextEl) {
    const value = String(box.text || "").trim();
    if (document.activeElement !== contextTranslatedTextEl || contextTranslatedEditKey !== selectedKey) {
      contextTranslatedTextEl.value = value;
    } else if (contextTranslatedTextEl.value !== value) {
      contextTranslatedTextEl.value = value;
    }
    contextTranslatedTextEl.placeholder = "可在此直接編輯目前譯文";
    contextTranslatedTextEl.disabled = false;
  }
  syncContextRetranslateButton(selected[0]);
  contextTranslatedEditKey = selectedKey;
  contextSourceEditKey = selectedKey;
}

async function retranslateSelectedBoxFromSource() {
  const selected = getSingleSelectedBox();
  const jobId = document.body.dataset.jobId;
  if (!jobId || !selected || !contextSourceTextEl) return;
  const sourceText = String(contextSourceTextEl.value || "").trim();
  if (!sourceText) {
    setStatus("請先輸入修正後的原始內容");
    return;
  }
  const saved = await saveEdits(false, { silent: true });
  if (!saved) {
    setStatus("重翻前儲存失敗");
    return;
  }
  if (contextRetranslateBtn) {
    contextRetranslateBtn.classList.remove("ghost", "retranslate-btn--idle", "retranslate-btn--ready");
    contextRetranslateBtn.classList.add("primary", "retranslate-btn--busy");
    contextRetranslateBtn.disabled = true;
    contextRetranslateBtn.textContent = "重新翻譯中...";
  }
  setStatus(`正在重翻第 ${selected.page.pageIndex + 1} 頁目前文字框...`);
  try {
    const res = await fetch(`/api/job/${jobId}/retranslate-box`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_index_0based: selected.page.pageIndex,
        box_id: selected.box.id,
        source_text: sourceText,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `重翻失敗：${body.error}` : "重翻失敗");
      return;
    }
    await loadJobData(jobId, { preserveActivePage: true });
    const reselectedPageIdx = state.pages.findIndex((page) => page.pageIndex === selected.page.pageIndex);
    if (reselectedPageIdx >= 0) {
      const reselectedBoxIdx = state.pages[reselectedPageIdx].boxes.findIndex((box) => box.id === selected.box.id);
      if (reselectedBoxIdx >= 0) {
        setSelection(reselectedPageIdx, reselectedBoxIdx, false);
      }
    }
    setStatus("已使用修正後原始內容重新翻譯目前文字框");
  } catch (error) {
    setStatus("重翻失敗");
  } finally {
    if (contextRetranslateBtn) {
      contextRetranslateBtn.classList.remove("retranslate-btn--busy");
      syncContextInspector();
    }
  }
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
  syncAlignmentButtons(box.align);
  syncRotationSummary(box.rotation);
  syncContextInspector();
}

function clearSelection() {
  state.selected = null;
  state.selectedBoxes.clear();
  applySelectionClasses();
  syncAlignmentButtons("left");
  syncRotationSummary(0);
  syncContextInspector();
}

function selectAllBoxes() {
  const targetPageIdx = Number.isFinite(state.activePageIdx)
    ? state.activePageIdx
    : state.selected?.pageIdx ?? 0;
  const page = state.pages[targetPageIdx];
  if (!page) return false;

  const selectable = page.boxes
    .map((box, boxIdx) => ({ box, boxIdx }))
    .filter(({ box }) => box && !box.deleted);
  if (!selectable.length) return false;

  state.selectedBoxes.clear();
  selectable.forEach(({ boxIdx }) => {
    state.selectedBoxes.add(boxKey(targetPageIdx, boxIdx));
  });
  state.selected = { pageIdx: targetPageIdx, boxIdx: selectable[0].boxIdx };
  applySelectionClasses();
  syncInspectorFromBox(selectable[0].box);
  return true;
}

function cloneBoxData(box) {
  return {
    id: box.id,
    bbox: { ...box.bbox },
    text: box.text,
    fontSize: box.fontSize,
    color: box.color,
    align: normalizeTextAlign(box.align),
    rotation: normalizeBoxRotation(box.rotation),
    noClip: !!box.noClip,
    autoGenerated: !!box.autoGenerated,
    tmSourceText: box.tmSourceText || "",
    tmSourceNormalized: box.tmSourceNormalized || "",
    tmTargetLang: box.tmTargetLang || "",
    tmDocumentMode: box.tmDocumentMode || "",
    deleted: !!box.deleted,
  };
}

function nudgeSelectedBoxes(deltaX, deltaY) {
  const selected = getSelectedBoxes();
  if (!selected.length) return false;

  const updates = selected.map(({ pageIdx, page, box }) => {
    if (!page || !box || box.deleted) return null;
    const before = cloneBoxData(box);
    const pageWidth = page.imageSize?.[0];
    const pageHeight = page.imageSize?.[1];
    const maxX = Number.isFinite(pageWidth) ? Math.max(0, pageWidth - box.bbox.w) : null;
    const maxY = Number.isFinite(pageHeight) ? Math.max(0, pageHeight - box.bbox.h) : null;
    const nextX = maxX === null
      ? Math.max(0, box.bbox.x + deltaX)
      : Math.min(Math.max(0, box.bbox.x + deltaX), maxX);
    const nextY = maxY === null
      ? Math.max(0, box.bbox.y + deltaY)
      : Math.min(Math.max(0, box.bbox.y + deltaY), maxY);

    if (nextX === box.bbox.x && nextY === box.bbox.y) {
      return null;
    }

    box.bbox.x = nextX;
    box.bbox.y = nextY;
    updateBoxElement(page, box);
    return {
      pageIdx,
      boxId: box.id,
      before,
      after: cloneBoxData(box),
    };
  }).filter(Boolean);

  if (!updates.length) return false;
  pushAction({ type: "update_boxes", updates });
  syncContextInspector();
  return true;
}

function rotateBoxGeometry(box, nextRotation, page) {
  const previous = normalizeBoxRotation(box.rotation);
  const target = normalizeBoxRotation(nextRotation);
  if ((previous % 180) === (target % 180)) {
    box.rotation = target;
    return;
  }

  const cx = box.bbox.x + (box.bbox.w / 2);
  const cy = box.bbox.y + (box.bbox.h / 2);
  const nextW = box.bbox.h;
  const nextH = box.bbox.w;
  let nextX = cx - (nextW / 2);
  let nextY = cy - (nextH / 2);

  const pageWidth = page?.imageSize?.[0] ?? null;
  const pageHeight = page?.imageSize?.[1] ?? null;
  if (Number.isFinite(pageWidth)) {
    nextX = Math.max(0, Math.min(nextX, Math.max(0, pageWidth - nextW)));
  } else {
    nextX = Math.max(0, nextX);
  }
  if (Number.isFinite(pageHeight)) {
    nextY = Math.max(0, Math.min(nextY, Math.max(0, pageHeight - nextH)));
  } else {
    nextY = Math.max(0, nextY);
  }

  box.bbox.x = nextX;
  box.bbox.y = nextY;
  box.bbox.w = nextW;
  box.bbox.h = nextH;
  box.rotation = target;
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
  box.align = normalizeTextAlign(data.align);
  box.rotation = normalizeBoxRotation(data.rotation);
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
    align: normalizeTextAlign(data.align),
    rotation: normalizeBoxRotation(data.rotation),
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
  const previousIdx = state.activePageIdx ?? 0;
  const maxIdx = Math.max(0, state.pages.length - 1);
  state.activePageIdx = Math.max(0, Math.min(pageIdx, maxIdx));
  syncPageSelector();
  updatePageNavButtons();
  state.pages.forEach((page, idx) => {
    if (page.thumbElement) {
      page.thumbElement.classList.toggle("is-active", idx === state.activePageIdx);
    }
  });
  if (previousIdx !== state.activePageIdx) {
    clearSelection();
    if (state.viewMode === "single") {
      renderCurrentPage();
    }
  }
  if (scroll && state.viewMode === "continuous") {
    const page = state.pages[state.activePageIdx];
    page?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (scroll && pagesEl) {
    pagesEl.scrollTo({ top: 0, left: 0, behavior: "smooth" });
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
    if (state.viewMode === "continuous") {
      state.pages.forEach((page) => applyZoomToPage(page));
    } else {
      const currentPage = state.pages[state.activePageIdx];
      if (currentPage) {
        applyZoomToPage(currentPage);
      }
    }
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
    syncContextInspector();
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
      align: normalizeTextAlign(box.align),
      noClip: !!box.noClip,
    })),
    sourcePageIdx: selected.length === 1 ? selected[0].pageIdx : null,
    pasteCount: 0,
  };
  setStatus(`Copied ${selected.length} box${selected.length > 1 ? "es" : ""}.`);
}

function getPageDimensions(page) {
  const width = Number(page?.imageSize?.[0]) || 1;
  const height = Number(page?.imageSize?.[1]) || 1;
  return { width, height };
}

function normalizeTextForMatch(text) {
  return String(text || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function getNormalizedBbox(page, bbox) {
  const { width, height } = getPageDimensions(page);
  return {
    x: bbox.x / width,
    y: bbox.y / height,
    w: bbox.w / width,
    h: bbox.h / height,
  };
}

function denormalizeBbox(page, normalized) {
  const { width, height } = getPageDimensions(page);
  return {
    x: normalized.x * width,
    y: normalized.y * height,
    w: Math.max(1, normalized.w * width),
    h: Math.max(1, normalized.h * height),
  };
}

function clampBboxToPage(page, bbox) {
  const next = { ...bbox };
  if (page.imageSize && page.imageSize.length === 2) {
    const maxX = Math.max(0, page.imageSize[0] - next.w);
    const maxY = Math.max(0, page.imageSize[1] - next.h);
    next.x = Math.min(Math.max(0, next.x), maxX);
    next.y = Math.min(Math.max(0, next.y), maxY);
    next.w = Math.min(next.w, page.imageSize[0] - next.x);
    next.h = Math.min(next.h, page.imageSize[1] - next.y);
  }
  return next;
}

function getNextBoxId(page) {
  return page.boxes.length ? Math.max(...page.boxes.map((box) => Number(box.id) || 0)) + 1 : 0;
}

function parsePageSelectionInput(input, totalPages, excludedPageIdxs = []) {
  const raw = String(input || "").trim().toLowerCase();
  const excluded = new Set(excludedPageIdxs);
  const allPageIdxs = Array.from({ length: totalPages }, (_, idx) => idx).filter(
    (idx) => !excluded.has(idx),
  );
  if (!raw || raw === "all" || raw === "全部") {
    return allPageIdxs;
  }
  if (raw === "after" || raw === "之後") {
    const minExcluded = excludedPageIdxs.length ? Math.min(...excludedPageIdxs) : -1;
    return allPageIdxs.filter((idx) => idx > minExcluded);
  }

  const result = new Set();
  raw.split(",").forEach((token) => {
    const value = token.trim();
    if (!value) return;
    const rangeMatch = value.match(/^(\d+)\s*-\s*(\d+)$/);
    if (rangeMatch) {
      const start = Number.parseInt(rangeMatch[1], 10);
      const end = Number.parseInt(rangeMatch[2], 10);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return;
      const from = Math.max(1, Math.min(start, end));
      const to = Math.min(totalPages, Math.max(start, end));
      for (let pageNo = from; pageNo <= to; pageNo += 1) {
        const pageIdx = pageNo - 1;
        if (!excluded.has(pageIdx)) {
          result.add(pageIdx);
        }
      }
      return;
    }
    const pageNo = Number.parseInt(value, 10);
    if (!Number.isFinite(pageNo)) return;
    const pageIdx = pageNo - 1;
    if (pageIdx >= 0 && pageIdx < totalPages && !excluded.has(pageIdx)) {
      result.add(pageIdx);
    }
  });
  return Array.from(result).sort((a, b) => a - b);
}

async function askBatchTargetPages(sourcePageIdx, modeLabel, excludedPageIdxs = []) {
  const selection = await openBatchPageModal(sourcePageIdx, modeLabel);
  if (!selection) return null;

  let pageIdxs = [];
  if (selection.mode === "all") {
    pageIdxs = parsePageSelectionInput("all", state.pages.length, excludedPageIdxs);
  } else if (selection.mode === "after") {
    pageIdxs = parsePageSelectionInput("after", state.pages.length, excludedPageIdxs);
  } else {
    pageIdxs = parsePageSelectionInput(selection.pages, state.pages.length, excludedPageIdxs);
  }
  if (!pageIdxs.length) {
    setStatus("沒有符合的目標頁");
    return null;
  }
  return pageIdxs;
}

function getSingleSourceSelection() {
  const selected = getSelectedBoxes();
  if (!selected.length) {
    setStatus("請先選取文字框");
    return null;
  }
  const sourcePageIdxs = new Set(selected.map((item) => item.pageIdx));
  if (sourcePageIdxs.size !== 1) {
    setStatus("批次套用需從同一頁選取來源文字框");
    return null;
  }
  const sourcePageIdx = selected[0].pageIdx;
  return {
    sourcePageIdx,
    sourcePage: state.pages[sourcePageIdx],
    selected,
  };
}

function buildBatchTemplate(selected, sourcePage) {
  return selected.map(({ box }) => ({
    sourceId: box.id,
    normalizedBbox: getNormalizedBbox(sourcePage, box.bbox),
    text: box.text,
    fontSize: box.fontSize,
    color: box.color,
    align: normalizeTextAlign(box.align),
    noClip: !!box.noClip,
  }));
}

function computeIoU(a, b) {
  const left = Math.max(a.x, b.x);
  const top = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.w, b.x + b.w);
  const bottom = Math.min(a.y + a.h, b.y + b.h);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  if (intersection <= 0) return 0;
  const areaA = Math.max(0, a.w) * Math.max(0, a.h);
  const areaB = Math.max(0, b.w) * Math.max(0, b.h);
  const union = areaA + areaB - intersection;
  return union > 0 ? intersection / union : 0;
}

async function batchApplySelectedBoxes() {
  const selection = getSingleSourceSelection();
  if (!selection) return;
  const targetPageIdxs = await askBatchTargetPages(
    selection.sourcePageIdx,
    "套用",
    [selection.sourcePageIdx],
  );
  if (!targetPageIdxs?.length) return;

  const template = buildBatchTemplate(selection.selected, selection.sourcePage);
  const { width: sourceWidth, height: sourceHeight } = getPageDimensions(selection.sourcePage);
  const actions = [];
  let addedCount = 0;

  targetPageIdxs.forEach((targetPageIdx) => {
    const targetPage = state.pages[targetPageIdx];
    if (!targetPage) return;
    const { width: targetWidth, height: targetHeight } = getPageDimensions(targetPage);
    const fontScale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
    let nextId = getNextBoxId(targetPage);
    const addedBoxes = [];

    template.forEach((item) => {
      const bbox = clampBboxToPage(targetPage, denormalizeBbox(targetPage, item.normalizedBbox));
      const newBox = {
        id: nextId++,
        bbox,
        text: item.text,
        fontSize: Math.max(8, item.fontSize * fontScale),
        color: item.color,
        align: normalizeTextAlign(item.align),
        noClip: item.noClip,
        autoGenerated: false,
        deleted: false,
        element: null,
      };
      targetPage.boxes.push(newBox);
      createBoxElement(targetPageIdx, targetPage.boxes.length - 1);
      addedBoxes.push({ pageIdx: targetPageIdx, box: cloneBoxData(newBox) });
      addedCount += 1;
    });

    if (addedBoxes.length) {
      actions.push({ type: "add_boxes", boxes: addedBoxes });
    }
  });

  if (!actions.length) {
    setStatus("沒有新增任何文字框");
    return;
  }
  pushAction(actions.length === 1 ? actions[0] : { type: "batch", actions });
  setStatus(`已批次套用 ${addedCount} 個文字框到 ${targetPageIdxs.length} 頁`);
}

async function batchDeleteMatchingBoxes() {
  const selection = getSingleSourceSelection();
  if (!selection) return;
  const targetPageIdxs = await askBatchTargetPages(
    selection.sourcePageIdx,
    "刪除",
    [selection.sourcePageIdx],
  );
  if (!targetPageIdxs?.length) return;

  const template = buildBatchTemplate(selection.selected, selection.sourcePage);
  const actions = [];
  let deletedCount = 0;

  const sourceDeletedEntries = selection.selected.map(({ pageIdx, box }) => ({
    pageIdx,
    box: cloneBoxData(box),
  }));
  selection.selected.forEach(({ page, box }) => {
    box.deleted = true;
    updateBoxElement(page, box);
    deletedCount += 1;
  });
  if (sourceDeletedEntries.length) {
    actions.push({ type: "delete_boxes", boxes: sourceDeletedEntries });
  }

  targetPageIdxs.forEach((targetPageIdx) => {
    const targetPage = state.pages[targetPageIdx];
    if (!targetPage) return;
    const usedBoxIds = new Set();
    const deletedEntries = [];

    template.forEach((item) => {
      const expectedBbox = denormalizeBbox(targetPage, item.normalizedBbox);
      const expectedText = normalizeTextForMatch(item.text);
      let bestCandidate = null;
      let bestScore = 0;

      targetPage.boxes.forEach((candidate) => {
        if (!candidate || candidate.deleted || usedBoxIds.has(candidate.id)) return;
        const iou = computeIoU(candidate.bbox, expectedBbox);
        const centerDx = Math.abs(
          candidate.bbox.x + candidate.bbox.w / 2 - (expectedBbox.x + expectedBbox.w / 2),
        );
        const centerDy = Math.abs(
          candidate.bbox.y + candidate.bbox.h / 2 - (expectedBbox.y + expectedBbox.h / 2),
        );
        const distancePenalty = (centerDx + centerDy) / 10000;
        const textBonus =
          expectedText && normalizeTextForMatch(candidate.text) === expectedText ? 0.2 : 0;
        const score = iou + textBonus - distancePenalty;
        if (score > bestScore) {
          bestScore = score;
          bestCandidate = candidate;
        }
      });

      if (bestCandidate && bestScore >= 0.25) {
        usedBoxIds.add(bestCandidate.id);
        deletedEntries.push({ pageIdx: targetPageIdx, box: cloneBoxData(bestCandidate) });
        bestCandidate.deleted = true;
        updateBoxElement(targetPage, bestCandidate);
        deletedCount += 1;
      }
    });

    if (deletedEntries.length) {
      actions.push({ type: "delete_boxes", boxes: deletedEntries });
    }
  });

  if (!actions.length) {
    setStatus("沒有找到可批次刪除的對應文字框");
    return;
  }
  clearSelection();
  pushAction(actions.length === 1 ? actions[0] : { type: "batch", actions });
  setStatus(`已批次刪除 ${deletedCount} 個對應文字框`);
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
      align: normalizeTextAlign(item.align),
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
      setActivePage(pageIdx, { scroll: false });
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
        align: normalizeTextAlign(box.align),
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

function buildState(data, options = {}) {
  const { activePageIdx = 0 } = options;
  state.pdfUrl = data.pdf_url || null;
  state.pdfDoc = null;
  state.downloadName = data.download_name || "edited.pdf";
  state.mergeNotices = Array.isArray(data.merge_notices) ? data.merge_notices : [];
  state.pages = data.pages.map((page) => {
    const boxes = page.rec_polys.map((poly, index) => {
      const bbox = polyToBbox(poly);
      const text = page.edit_texts[index] ?? page.rec_texts[index] ?? "";
      const baseSize = 25;
      const fontSize = Number(page.font_sizes?.[index]);
      const color = page.colors?.[index] ?? "#0000ff";
      const align = normalizeTextAlign(page.alignments?.[index]);
      const rotation = normalizeBoxRotation(page.rotations?.[index]);
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
        align,
        rotation,
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
  const maxIdx = Math.max(0, state.pages.length - 1);
  state.activePageIdx = Math.max(0, Math.min(activePageIdx, maxIdx));
  
  // Initial zoom logic: use fitToWidth instead of hardcoded 0.5
  if (state.pages.length > 0) {
    // We need to wait for the layout to settle slightly for clientWidth to be accurate
    setTimeout(fitToWidth, 100);
  } else {
    state.zoom = 1.0;
    if (zoomRangeEl) zoomRangeEl.value = "100";
    if (zoomNumberEl) zoomNumberEl.value = "100";
  }

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
  setContextInspectorEmpty();
}

function updateBoxElement(page, box) {
  if (!box.element) return;
  const scale = page.scale || 1;
  const left = box.bbox.x * scale;
  const top = box.bbox.y * scale;
  const width = box.bbox.w * scale;
  const baseHeight = box.bbox.h * scale;
  const rotation = normalizeBoxRotation(box.rotation);
  const textEl = box.element.querySelector(".text");
  const expanded = !!box.noClip || !!box._isExpanded;
  let height = baseHeight;
  const insetX = 4;
  const insetY = 2;
  const innerWidth = Math.max(1, width - insetX * 2);
  const innerHeight = Math.max(1, baseHeight - insetY * 2);

  box.element.style.left = `${left}px`;
  box.element.style.top = `${top}px`;
  box.element.style.width = `${width}px`;
  if (textEl) {
    textEl.style.left = `${insetX}px`;
    textEl.style.top = `${insetY}px`;
    textEl.style.fontSize = `${box.fontSize * scale}px`;
    textEl.style.textAlign = normalizeTextAlign(box.align);
    const horizontal = rotation % 180 === 0;
    const layoutWidth = horizontal ? innerWidth : innerHeight;
    const layoutHeight = horizontal ? innerHeight : innerWidth;
    textEl.style.width = `${layoutWidth}px`;
    textEl.style.height = expanded && horizontal ? "auto" : `${layoutHeight}px`;
    textEl.classList.toggle("is-rotated", rotation !== 0);
    if (rotation === 90) {
      textEl.style.transform = `translateX(${layoutHeight}px) rotate(90deg)`;
    } else if (rotation === 180) {
      textEl.style.transform = `translate(${layoutWidth}px, ${layoutHeight}px) rotate(180deg)`;
    } else if (rotation === 270) {
      textEl.style.transform = `translateY(${layoutWidth}px) rotate(270deg)`;
    } else {
      textEl.style.transform = "none";
    }
  }
  if (expanded && textEl) {
    const previousHeight = textEl.style.height;
    textEl.style.height = "auto";
    height = Math.max(baseHeight, textEl.scrollHeight + insetY * 2);
    textEl.style.height = previousHeight;
  }
  box.element.style.height = `${height}px`;
  box.element.style.color = box.color;
  box.element.classList.toggle("is-deleted", box.deleted);
  box.element.classList.toggle("no-clip", !!box.noClip);
  box.element.classList.toggle("is-expanded", expanded);
  if (state.selectedBoxes.has(boxKey(state.pages.indexOf(page), page.boxes.indexOf(box)))) {
    syncContextInspector();
  }
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
    setStatus("PDF 載入失敗");
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
      img.loading = "lazy";
      img.decoding = "async";
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
  const movedDistance = Math.hypot(event.clientX - startX, event.clientY - startY);

    if (movedDistance < DRAG_START_THRESHOLD_PX) {
      return;
    }

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

function clampSelectionCoordinate(value, maxValue) {
  if (!Number.isFinite(value)) return 0;
  if (!Number.isFinite(maxValue) || maxValue <= 0) return Math.max(0, value);
  return Math.max(0, Math.min(value, maxValue));
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
  const rawCurrentX = clientX - bounds.left + scrollDx;
  const rawCurrentY = clientY - bounds.top + scrollDy;
  const maxX = overlayEl.clientWidth;
  const maxY = overlayEl.clientHeight;
  const currentX = clampSelectionCoordinate(rawCurrentX, maxX);
  const currentY = clampSelectionCoordinate(rawCurrentY, maxY);
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

async function endRangeSelection(event) {
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

  if (state.selectionMode === "retranslate") {
    await retranslateSelectedRegion(pageIdx, selectionBox);
    return;
  }

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
  if (state.viewMode === "continuous") {
    renderContinuousPages();
  } else {
    renderCurrentPage();
  }
  renderThumbnails();
}

function disposeRenderedPage(page) {
  if (!page) return;
  page.element = null;
  page.overlay = null;
  page.image = null;
  page.selectionRect = null;
  page.boxes.forEach((box) => {
    box.element = null;
  });
}

function renderCurrentPage() {
  pagesEl.innerHTML = "";
  state.pages.forEach((page) => disposeRenderedPage(page));
  const pageIdx = state.activePageIdx ?? 0;
  const page = state.pages[pageIdx];
  if (!page) return;

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
  if (state.pdfDoc && window.pdfjsLib) {
    img = document.createElement("canvas");
    img.className = "pdf-canvas";
  } else {
    img = document.createElement("img");
    img.loading = "eager";
    img.decoding = "async";
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

  applySelectionClasses();
}

function renderContinuousPages() {
  pagesEl.innerHTML = "";
  state.pages.forEach((page) => disposeRenderedPage(page));
  state.pages.forEach((page, pageIdx) => {
    const pageEl = document.createElement("article");
    pageEl.className = "page";

    const header = document.createElement("div");
    header.className = "page-header";
    header.innerHTML = `<span class="page-number">Page ${page.pageIndex + 1}</span>`;
    header.addEventListener("click", () => {
      setActivePage(pageIdx, { scroll: false });
      setStatus(`Active page: ${page.pageIndex + 1}`);
    });

    const wrap = document.createElement("div");
    wrap.className = "page-wrap";
    wrap.draggable = false;
    wrap.addEventListener("dragstart", (event) => event.preventDefault());

    const img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.src = page.imageUrl;
    img.alt = `Page ${page.pageIndex + 1}`;
    img.draggable = false;
    img.addEventListener("dragstart", (event) => event.preventDefault());
    img.addEventListener("load", () => {
      applyZoomToPage(page);
    });

    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.draggable = false;
    overlay.addEventListener("dragstart", (event) => event.preventDefault());

    const selectionRect = document.createElement("div");
    selectionRect.className = "selection-rect";
    selectionRect.style.display = "none";
    overlay.appendChild(selectionRect);

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
    wrap.addEventListener(
      "wheel",
      (event) => {
        if (state.selecting) {
          updateRangeSelection(event);
        }
      },
      { passive: true },
    );

    page.boxes.forEach((box, index) => {
      createBoxElement(pageIdx, index);
    });
  });

  applySelectionClasses();
}

function createBoxElement(pageIdx, boxIdx) {
  const page = state.pages[pageIdx];
  const box = page?.boxes[boxIdx];
  if (!page || !box || !page.overlay) return null;

  const boxEl = document.createElement("div");
  boxEl.className = "text-box";
  boxEl.style.left = "0px";
  boxEl.style.top = "0px";
  boxEl.style.setProperty("--box-hit-slop", `${BOX_HIT_SLOP_PX}px`);

  const hitAreaEl = document.createElement("div");
  hitAreaEl.className = "text-box-hit-area";
  boxEl.appendChild(hitAreaEl);

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
    beginBoxTextEdit(box);
  });

  textEl.addEventListener("pointerdown", (event) => {
    state.lastCtrlKey = event.ctrlKey;
    selectBox(pageIdx, boxIdx, event.ctrlKey);
  });

  textEl.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    insertEditorLineBreak(textEl);
  });

  textEl.addEventListener("paste", (event) => {
    event.preventDefault();
    const pastedText = event.clipboardData?.getData("text/plain")
      ?? window.clipboardData?.getData("Text")
      ?? "";
    insertEditorPlainText(textEl, pastedText);
  });
  
  textEl.addEventListener("input", () => {
    setBoxText(page, box, textEl.innerText);
    syncContextInspector();
  });

  textEl.addEventListener("blur", () => {
    const normalized = textEl.innerText.trim();
    if (textEl.innerText !== normalized) {
      textEl.innerText = normalized;
    }
    commitBoxTextEdit(pageIdx, boxIdx, normalized);
    syncContextInspector();
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
    align: "left",
    rotation: state.selected && state.selected.pageIdx === targetPageIdx
      ? normalizeBoxRotation(page.boxes[state.selected.boxIdx]?.rotation)
      : 0,
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
        text_align: normalizeTextAlign(box.align),
        rotation: normalizeBoxRotation(box.rotation),
        auto_generated: !!box.autoGenerated,
        tm_source_text: box.tmSourceText || "",
        tm_source_normalized: box.tmSourceNormalized || "",
        tm_target_lang: box.tmTargetLang || "",
        tm_document_mode: box.tmDocumentMode || "",
      })),
    })),
  };
}

async function retranslateSelectedRegion(pageIdx, bbox) {
  const jobId = document.body.dataset.jobId;
  const page = state.pages[pageIdx];
  if (!jobId || !page) {
    setSelectionMode("boxes");
    return;
  }
  setSelectionMode("boxes");
  const saved = await saveEdits(false, { silent: true });
  if (!saved) {
    setStatus("補翻前儲存失敗，已取消補翻");
    return;
  }
  setStatus(`擷取第 ${page.pageIndex + 1} 頁選取區域中...`);
  try {
    const res = await fetch(`/api/job/${jobId}/region-ocr-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_index_0based: page.pageIndex,
        bbox,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `擷取失敗：${body.error}` : "擷取失敗");
      return;
    }
    openRegionPreviewModal({
      pageIndex: page.pageIndex,
      bbox,
      region_bbox: body.region_bbox || bbox,
      merged_bbox: body.merged_bbox || bbox,
      source_text: body.source_text || "",
      image_data_url: body.image_data_url || "",
    });
    setStatus("請確認擷取區域與 OCR 結果");
  } catch (error) {
    setStatus("擷取失敗");
  }
}

async function confirmRegionPreview() {
  const jobId = document.body.dataset.jobId;
  const preview = state.pendingRegionPreview;
  if (!jobId || !preview) return;
  const sourceText = normalizePreviewText(regionPreviewTextEl?.value || preview.source_text || "");
  closeRegionPreviewModal();
  setStatus(`補翻第 ${preview.pageIndex + 1} 頁選取區域中...`);
  try {
    const res = await fetch(`/api/job/${jobId}/retranslate-region`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_index_0based: preview.pageIndex,
        bbox: preview.region_bbox || preview.bbox,
        merged_bbox: preview.merged_bbox || preview.bbox,
        source_text: sourceText,
        replace_existing: true,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `補翻失敗：${body.error}` : "補翻失敗");
      return;
    }
    await loadJobData(jobId, { preserveActivePage: true });
    setStatus(body.boxes_added ? `補翻完成，新增 ${body.boxes_added} 個文字框` : "補翻完成，但沒有新增文字框");
  } catch (error) {
    setStatus("補翻失敗");
  }
}

async function loadJobData(jobId, options = {}) {
  const { preserveActivePage = false } = options;
  const preservedScroll = preserveActivePage && pagesEl
    ? { left: pagesEl.scrollLeft, top: pagesEl.scrollTop }
    : null;
  setStatus("Loading OCR data...");
  const res = await fetch(`/api/job/${jobId}`);
  if (!res.ok) {
    setStatus("Failed to load job data.");
    return null;
  }
  const data = await res.json();
  const targetPageIdx = preserveActivePage ? (state.activePageIdx ?? 0) : 0;
  buildState(data, { activePageIdx: targetPageIdx });
  renderPages();
  refreshAllConsistencyPanels();
  if (preserveActivePage) {
    setActivePage(targetPageIdx, { scroll: false });
    if (preservedScroll && state.viewMode === "continuous") {
      pagesEl.scrollTo({ left: preservedScroll.left, top: preservedScroll.top, behavior: "auto" });
    }
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
    await loadJobData(jobId, { preserveActivePage: true });
  }
  return status;
}

async function saveEdits(shouldDownload = false, options = {}) {
  const { silent = false } = options;
  const jobId = document.body.dataset.jobId;
  if (!jobId) return;
  const originalText = saveBtn ? saveBtn.textContent : null;
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";
  }
  if (downloadBtn) {
    downloadBtn.disabled = true;
  }
  if (!silent) {
    setStatus("保存中...");
  }
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
      if (!silent) {
        setStatus("Edits saved.");
      }
      return true;
    } else {
      setStatus(body.error ? `Save failed: ${body.error}` : "Save failed. Check server logs.");
      return false;
    }
  } catch (error) {
    setStatus("Save failed. Check console/logs.");
    return false;
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

async function applyConsistencyToDocument() {
  const jobId = document.body.dataset.jobId;
  const group = getConsistencyGroupByKey(state.selectedConsistencyKey);
  const targetText = normalizePreviewText(consistencyTargetTextEl?.value || "");
  if (!jobId || !group) return;
  if (!targetText) {
    setStatus("請先輸入要統一套用的譯文");
    return;
  }

  const updates = group.boxes.map(({ pageIdx, boxIdx }) => {
    const page = state.pages[pageIdx];
    const box = page?.boxes[boxIdx];
    if (!page || !box || box.deleted) return null;
    const before = cloneBoxData(box);
    box.text = targetText;
    const textEl = box.element?.querySelector(".text");
    if (textEl) {
      textEl.textContent = targetText;
      textEl.innerText = targetText;
    }
    updateBoxElement(page, box);
    return {
      pageIdx,
      boxId: box.id,
      before,
      after: cloneBoxData(box),
    };
  }).filter(Boolean).filter((update) => update.before.text !== update.after.text);

  if (updates.length) {
    pushAction({ type: "update_boxes", updates });
  }
  refreshConsistencyPanel();

  const originalText = applyConsistencyBtn?.textContent || "套用到本文件全部匹配文字框";
  if (applyConsistencyBtn) {
    applyConsistencyBtn.disabled = true;
    applyConsistencyBtn.textContent = "套用中...";
  }
  try {
    const res = await fetch(`/api/job/${jobId}/consistency/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages: buildSavePayload().pages,
        source_normalized: group.sourceNormalized,
        target_text: targetText,
        sync_to_tm: !!consistencySyncTmEl?.checked,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `一致性套用失敗: ${body.error}` : "一致性套用失敗");
      return;
    }
    if (body.edited_pdf_url) {
      updateEditedLink(body.edited_pdf_url);
    }
    setStatus(`已統一 ${body.updated_count || updates.length} 個文字框`);
  } catch (error) {
    setStatus("一致性套用失敗");
  } finally {
    if (applyConsistencyBtn) {
      applyConsistencyBtn.disabled = false;
      applyConsistencyBtn.textContent = originalText;
    }
  }
}

async function applyParagraphTermToDocument() {
  const jobId = document.body.dataset.jobId;
  const group = getParagraphTermGroupByKey(state.selectedParagraphTermKey);
  const replaceFrom = normalizeConsistencyText(paragraphReplaceFromEl?.value || "");
  const replaceTo = normalizeConsistencyText(paragraphReplaceToEl?.value || "");
  if (!jobId || !group) return;
  if (!replaceFrom || !replaceTo) {
    setStatus("請先輸入段落術語的替換前與替換後內容");
    return;
  }

  const originalText = applyParagraphTermBtn?.textContent || "套用到包含此術語的段落";
  if (applyParagraphTermBtn) {
    applyParagraphTermBtn.disabled = true;
    applyParagraphTermBtn.textContent = "套用中...";
  }
  try {
    const res = await fetch(`/api/job/${jobId}/paragraph-term/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages: buildSavePayload().pages,
        source_term: group.sourceText,
        replace_from: replaceFrom,
        replace_to: replaceTo,
        sync_to_tm: !!paragraphSyncTmEl?.checked,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(body.error ? `段落術語套用失敗: ${body.error}` : "段落術語套用失敗");
      return;
    }
    await loadJobData(jobId, { preserveActivePage: true });
    setStatus(`已更新 ${body.updated_count || 0} 個段落文字框`);
  } catch (error) {
    setStatus("段落術語套用失敗");
  } finally {
    if (applyParagraphTermBtn) {
      applyParagraphTermBtn.disabled = false;
      applyParagraphTermBtn.textContent = originalText;
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

  if (menuBtn && menuDropdown) {
    menuBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      menuDropdown.hidden = !menuDropdown.hidden;
    });

    document.addEventListener("click", (event) => {
      if (!menuDropdown.hidden && !menuDropdown.contains(event.target) && event.target !== menuBtn) {
        menuDropdown.hidden = true;
      }
    });
  }

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

  alignmentButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = normalizeTextAlign(button.dataset.align);
      syncAlignmentButtons(value);
      const selected = getSelectedBoxes();
      if (!selected.length) return;
      const updates = selected.map(({ pageIdx, box }) => ({
        pageIdx,
        boxId: box.id,
        before: cloneBoxData(box),
      }));
      selected.forEach(({ page, box }) => {
        box.align = value;
        updateBoxElement(page, box);
      });
      const finalized = updates.map((update) => {
        const current = findBox(update.pageIdx, update.boxId);
        return current ? { ...update, after: cloneBoxData(current) } : null;
      }).filter(Boolean).filter((update) => update.before.align !== update.after.align);
      if (finalized.length) {
        pushAction({ type: "update_boxes", updates: finalized });
      }
    });
  });

  const applyRotationDelta = (delta = 0, absolute = null) => {
    const selected = getSelectedBoxes();
    if (!selected.length) return;
    const updates = selected.map(({ pageIdx, box }) => ({
      pageIdx,
      boxId: box.id,
      before: cloneBoxData(box),
    }));
    selected.forEach(({ page, box }) => {
      const current = normalizeBoxRotation(box.rotation);
      const next = absolute == null
        ? normalizeBoxRotation(current + delta)
        : normalizeBoxRotation(absolute);
      rotateBoxGeometry(box, next, page);
      updateBoxElement(page, box);
    });
    const finalized = updates.map((update) => {
      const current = findBox(update.pageIdx, update.boxId);
      return current ? { ...update, after: cloneBoxData(current) } : null;
    }).filter(Boolean).filter((update) => (
      update.before.rotation !== update.after.rotation
      || update.before.bbox.x !== update.after.bbox.x
      || update.before.bbox.y !== update.after.bbox.y
      || update.before.bbox.w !== update.after.bbox.w
      || update.before.bbox.h !== update.after.bbox.h
    ));
    if (finalized.length) {
      pushAction({ type: "update_boxes", updates: finalized });
      syncInspectorFromBox(selected[0].box);
    }
  };

  rotateLeftBtn?.addEventListener("click", () => applyRotationDelta(-90));
  rotateRightBtn?.addEventListener("click", () => applyRotationDelta(90));
  rotateResetBtn?.addEventListener("click", () => applyRotationDelta(0, 0));

  if (pageSelectEl) {
    pageSelectEl.addEventListener("change", () => {
      const idx = Number.parseInt(pageSelectEl.value, 10);
      if (!Number.isFinite(idx)) return;
      setActivePage(idx);
    });
  }

  if (prevPageBtn) {
    prevPageBtn.addEventListener("click", () => {
      const idx = Math.max(0, (state.activePageIdx ?? 0) - 1);
      setActivePage(idx);
    });
  }

  if (nextPageBtn) {
    nextPageBtn.addEventListener("click", () => {
      const idx = Math.min(state.pages.length - 1, (state.activePageIdx ?? 0) + 1);
      setActivePage(idx);
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

  if (fitToWidthBtn) {
    fitToWidthBtn.addEventListener("click", () => {
      fitToWidth();
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

  window.addEventListener("resize", () => {
    if (state.viewMode === "continuous") {
      state.pages.forEach((page) => {
        if (page.element) {
          updatePageLayout(page);
        }
      });
    } else {
      const page = state.pages[state.activePageIdx ?? 0];
      if (page) {
        updatePageLayout(page);
      }
    }
  });

  if (toggleThumbsBtn) {
    toggleThumbsBtn.addEventListener("click", () => {
      const collapsed = sidebarEl?.classList.contains("is-thumbs-collapsed");
      setThumbsCollapsed(!collapsed);
    });
  }

  if (toggleViewModeBtn) {
    toggleViewModeBtn.addEventListener("click", () => {
      setViewMode(state.viewMode === "continuous" ? "single" : "continuous");
    });
  }

  sidebarRailButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.sidebarTarget;
      if (!targetId) return;
      setSidebarSection(targetId);
    });
  });

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

  if (batchApplyBoxesBtn) {
    batchApplyBoxesBtn.addEventListener("click", () => {
      batchApplySelectedBoxes();
    });
  }

  if (batchDeleteBoxesBtn) {
    batchDeleteBoxesBtn.addEventListener("click", () => {
      batchDeleteMatchingBoxes();
    });
  }

  if (refreshConsistencyBtn) {
    refreshConsistencyBtn.addEventListener("click", () => {
      refreshAllConsistencyPanels();
      setStatus("已重新掃描文件內的一致性問題");
    });
  }

  if (applyConsistencyBtn) {
    applyConsistencyBtn.addEventListener("click", () => {
      applyConsistencyToDocument();
    });
  }

  if (applyParagraphTermBtn) {
    applyParagraphTermBtn.addEventListener("click", () => {
      applyParagraphTermToDocument();
    });
  }

  if (addGlossaryBtn) {
    addGlossaryBtn.addEventListener("click", async () => {
      await addGlossaryEntry();
    });
  }

  if (addGlossaryRetranslateBtn) {
    addGlossaryRetranslateBtn.addEventListener("click", async () => {
      await addGlossaryEntry({ retranslate: true });
    });
  }

  if (savePromptBtn) {
    savePromptBtn.addEventListener("click", async () => {
      await saveSystemPrompt(currentJobId);
    });
  }

  if (retranslateDocumentBtn) {
    retranslateDocumentBtn.addEventListener("click", async () => {
      await retranslateDocumentImmediately();
    });
  }

  if (glossaryPromptBtn) {
    glossaryPromptBtn.addEventListener("click", () => {
      openGlossaryModal();
    });
  }

  if (templateManagerBtn) {
    templateManagerBtn.addEventListener("click", () => {
      openTemplateManagerModal();
    });
  }

  if (headerTemplateBtn) {
    headerTemplateBtn.addEventListener("click", () => {
      openTemplateManagerModal();
    });
  }

  if (closeGlossaryPrompt) {
    closeGlossaryPrompt.addEventListener("click", () => {
      closeGlossaryModal();
    });
  }

  if (closeTemplateManagerBtn) {
    closeTemplateManagerBtn.addEventListener("click", () => {
      closeTemplateManagerModal();
    });
  }

  if (saveTemplateBtn) {
    saveTemplateBtn.addEventListener("click", () => {
      saveCurrentAsTemplate();
    });
  }

  if (templateSelectEl) {
    templateSelectEl.addEventListener("change", () => {
      renderTemplateSummary(getSelectedTemplate());
    });
  }

  if (templateApplyAllEl) {
    templateApplyAllEl.addEventListener("change", () => {
      if (templateApplyAllEl.checked) {
        setTemplateApplyPreset("all");
      }
    });
  }

  if (templateApplyAfterEl) {
    templateApplyAfterEl.addEventListener("change", () => {
      if (templateApplyAfterEl.checked) {
        setTemplateApplyPreset("after");
      }
    });
  }

  if (templateApplyManualEl) {
    templateApplyManualEl.addEventListener("change", () => {
      if (templateApplyManualEl.checked) {
        setTemplateApplyPreset("manual");
        templateApplyInputEl?.focus();
      }
    });
  }

  if (templateApplyInputEl) {
    templateApplyInputEl.addEventListener("input", () => {
      if (templateApplyInputEl.value.trim()) {
        setTemplateApplyPreset("manual");
      }
    });
  }

  if (applyTemplateBtn) {
    applyTemplateBtn.addEventListener("click", () => {
      applyTemplateToDocument();
    });
  }

  if (applyTemplateToJobBtn) {
    applyTemplateToJobBtn.addEventListener("click", () => {
      applyTemplateToTargetJob();
    });
  }

  if (deleteTemplateBtn) {
    deleteTemplateBtn.addEventListener("click", () => {
      deleteSelectedTemplate();
    });
  }

  if (confirmRegionPreviewBtn) {
    confirmRegionPreviewBtn.addEventListener("click", () => {
      confirmRegionPreview();
    });
  }

  if (cancelRegionPreviewBtn) {
    cancelRegionPreviewBtn.addEventListener("click", () => {
      closeRegionPreviewModal();
      setStatus("已取消補翻");
    });
  }

  if (closeRegionPreviewBtn) {
    closeRegionPreviewBtn.addEventListener("click", () => {
      closeRegionPreviewModal();
      setStatus("已取消補翻");
    });
  }

  if (batchPageAllEl) {
    batchPageAllEl.addEventListener("change", () => {
      if (batchPageAllEl.checked) {
        setBatchPagePreset("all");
      } else {
        setBatchPagePreset("manual");
      }
    });
  }

  if (batchPageAfterEl) {
    batchPageAfterEl.addEventListener("change", () => {
      if (batchPageAfterEl.checked) {
        setBatchPagePreset("after");
      } else {
        setBatchPagePreset("manual");
      }
    });
  }

  if (batchPageInputEl) {
    batchPageInputEl.addEventListener("input", () => {
      if (!batchPageInputEl.disabled && batchPageInputEl.value.trim()) {
        setBatchPagePreset("manual");
      }
    });
    batchPageInputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        confirmBatchPageModalBtn?.click();
      }
    });
  }

  if (confirmBatchPageModalBtn) {
    confirmBatchPageModalBtn.addEventListener("click", () => {
      if (batchPageAllEl?.checked) {
        finishBatchPageModal({ mode: "all", pages: "" });
        return;
      }
      if (batchPageAfterEl?.checked) {
        finishBatchPageModal({ mode: "after", pages: "" });
        return;
      }
      const raw = batchPageInputEl?.value?.trim() || "";
      if (!raw) {
        setStatus("請勾選全部/之後，或輸入指定頁碼");
        return;
      }
      finishBatchPageModal({ mode: "manual", pages: raw });
    });
  }

  if (cancelBatchPageModalBtn) {
    cancelBatchPageModalBtn.addEventListener("click", () => {
      finishBatchPageModal(null);
    });
  }

  if (closeBatchPageModalBtn) {
    closeBatchPageModalBtn.addEventListener("click", () => {
      finishBatchPageModal(null);
    });
  }

  if (glossaryPromptModal) {
    glossaryPromptModal.addEventListener("click", (event) => {
      if (event.target === glossaryPromptModal) {
        closeGlossaryModal();
      }
    });
  }

  if (templateManagerModal) {
    templateManagerModal.addEventListener("click", (event) => {
      if (event.target === templateManagerModal) {
        closeTemplateManagerModal();
      }
    });
  }

  if (regionPreviewModal) {
    regionPreviewModal.addEventListener("click", (event) => {
      if (event.target === regionPreviewModal) {
        closeRegionPreviewModal();
        setStatus("已取消補翻");
      }
    });
  }

  if (batchPageModal) {
    batchPageModal.addEventListener("click", (event) => {
      if (event.target === batchPageModal) {
        finishBatchPageModal(null);
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (regionPreviewModal && !regionPreviewModal.hidden) {
        closeRegionPreviewModal();
        setStatus("已取消補翻");
        return;
      }
      if (batchPageModal && !batchPageModal.hidden) {
        finishBatchPageModal(null);
        return;
      }
      if (templateManagerModal && !templateManagerModal.hidden) {
        closeTemplateManagerModal();
        return;
      }
      closeGlossaryModal();
    }
  });

  if (glossaryCnEl) {
    glossaryCnEl.addEventListener("input", () => {
      renderGlossaryQuickState();
    });
    glossaryCnEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addGlossaryEntry();
      }
    });
  }

  if (glossaryEnEl) {
    glossaryEnEl.addEventListener("input", () => {
      renderGlossaryQuickState();
    });
    glossaryEnEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addGlossaryEntry();
      }
    });
  }

  if (templateNameEl) {
    templateNameEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveCurrentAsTemplate();
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

  if (contextTranslatedTextEl) {
    contextTranslatedTextEl.addEventListener("focus", () => {
      const selected = getSingleSelectedBox();
      if (!selected) return;
      beginBoxTextEdit(selected.box);
      contextTranslatedEditKey = boxKey(selected.pageIdx, selected.boxIdx);
    });
    contextTranslatedTextEl.addEventListener("input", () => {
      const selected = getSingleSelectedBox();
      if (!selected) return;
      setBoxText(selected.page, selected.box, contextTranslatedTextEl.value);
      syncContextInspector();
    });
    contextTranslatedTextEl.addEventListener("blur", () => {
      const selected = getSingleSelectedBox();
      if (!selected) {
        syncContextInspector();
        return;
      }
      commitBoxTextEdit(selected.pageIdx, selected.boxIdx, contextTranslatedTextEl.value);
      syncContextInspector();
    });
  }

  if (contextSourceTextEl) {
    contextSourceTextEl.addEventListener("focus", () => {
      const selected = getSingleSelectedBox();
      if (!selected) return;
      contextSourceEditKey = boxKey(selected.pageIdx, selected.boxIdx);
    });
    contextSourceTextEl.addEventListener("input", () => {
      syncContextRetranslateButton();
    });
  }

  if (contextRetranslateBtn) {
    contextRetranslateBtn.addEventListener("click", () => {
      retranslateSelectedBoxFromSource();
    });
  }

  if (regionTranslateBtn) {
    regionTranslateBtn.addEventListener("click", () => {
      if (state.selectionMode === "retranslate") {
        setSelectionMode("boxes");
        setStatus("已取消補翻選區");
        return;
      }
      clearSelection();
      setSelectionMode("retranslate");
      setStatus("請在頁面上框選要補翻的區域");
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
          setStatus(body.error ? `回復失敗：${body.error}` : "回復失敗");
          return;
        }
        await loadJobData(jobId, { preserveActivePage: true });
        setStatus("已回復翻譯結果");
      } catch (error) {
        setStatus("回復失敗");
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isEditing =
      target && (target.isContentEditable || ["INPUT", "TEXTAREA"].includes(target.tagName));

    if ((event.ctrlKey || event.metaKey) && !isEditing) {
      const key = event.key.toLowerCase();
      if (key === "a") {
        event.preventDefault();
        if (selectAllBoxes()) {
          setStatus("已全選目前頁面文字框");
        }
        return;
      }
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

    if (!isEditing && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
      const step = event.shiftKey ? 10 : 1;
      let moved = false;
      if (event.key === "ArrowUp") moved = nudgeSelectedBoxes(0, -step);
      if (event.key === "ArrowDown") moved = nudgeSelectedBoxes(0, step);
      if (event.key === "ArrowLeft") moved = nudgeSelectedBoxes(-step, 0);
      if (event.key === "ArrowRight") moved = nudgeSelectedBoxes(step, 0);
      if (moved) {
        event.preventDefault();
        setStatus(`已移動 ${getSelectedBoxes().length} 個文字框`);
      }
      return;
    }

    if (event.key !== "Delete") return;
    if (isEditing) return;
    deleteSelectedBoxes();
  });

  syncAlignmentButtons("left");
}

async function init() {
  const jobId = document.body.dataset.jobId;
  if (!jobId) return;
  currentJobId = jobId;
  bindControls();
  setSelectionMode("boxes");
  const data = await loadJobData(jobId);
  if (!data) return;
  glossaryEntries = Array.isArray(data.glossary) ? data.glossary : [];
  renderGlossaryQuickState();
  loadGlossary();
  if (systemPromptEl) {
    systemPromptEl.value = data.system_prompt || "";
  }
  const status = data.batch_status?.status;
  if (status === "running" || status === "queued") {
    setTimeout(() => pollBatchStatus(jobId), 5000);
  }
  if (templateMode) {
    loadTemplateTargetJobs();
  }
}

if (document.body.classList.contains("editor")) {
  setThumbsCollapsed(false);
  syncViewModeButton();
  setSidebarSection("sidebarPagesSection");
  init();
}
