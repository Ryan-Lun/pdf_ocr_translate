const glossarySearchEl = document.getElementById("glossarySearch");
const glossaryFilterEl = document.getElementById("glossaryFilter");
const glossaryRefreshBtn = document.getElementById("glossaryRefreshBtn");
const glossaryNewBtn = document.getElementById("glossaryNewBtn");
const glossaryStatusEl = document.getElementById("glossaryStatus");
const glossaryListEl = document.getElementById("glossaryList");
const glossaryEmptyEl = document.getElementById("glossaryEmpty");
const systemGlossaryFileEl = document.getElementById("systemGlossaryFile");
const exportSystemGlossaryBtn = document.getElementById("exportSystemGlossaryBtn");
const previewSystemGlossaryBtn = document.getElementById("previewSystemGlossaryBtn");
const applySystemGlossaryBtn = document.getElementById("applySystemGlossaryBtn");
const systemImportStatusEl = document.getElementById("systemImportStatus");
const systemImportSummaryEl = document.getElementById("systemImportSummary");
const systemImportPreviewEl = document.getElementById("systemImportPreview");
const effectiveCountEl = document.getElementById("effectiveCount");
const systemCountEl = document.getElementById("systemCount");
const userCountEl = document.getElementById("userCount");
const overrideCountEl = document.getElementById("overrideCount");
const detailTitleEl = document.getElementById("detailTitle");
const detailBadgeEl = document.getElementById("detailBadge");
const detailMetaEl = document.getElementById("detailMeta");
const detailCnEl = document.getElementById("detailCn");
const detailEnEl = document.getElementById("detailEn");
const saveGlossaryBtn = document.getElementById("saveGlossaryBtn");
const deleteGlossaryBtn = document.getElementById("deleteGlossaryBtn");
const overrideGlossaryBtn = document.getElementById("overrideGlossaryBtn");

const glossaryState = {
  systemGlossary: [],
  userGlossary: [],
  effectiveGlossary: [],
  selectedCn: null,
  mode: "new",
  pendingSystemImport: null,
  importPreviewLimits: {
    preview: 30,
    duplicates: 20,
    invalid: 20,
  },
};

const importStatusLabelMap = {
  add: "新增",
  update: "更新",
  unchanged: "未變更",
};

function setGlossaryStatus(message, isError = false) {
  if (!glossaryStatusEl) return;
  glossaryStatusEl.textContent = message || "";
  glossaryStatusEl.classList.toggle("glossary-status--error", Boolean(isError));
  glossaryStatusEl.classList.toggle("glossary-status--success", Boolean(message) && !isError);
}

function normalizeText(value) {
  return String(value || "").trim();
}

function setSystemImportStatus(message, isError = false) {
  if (!systemImportStatusEl) return;
  systemImportStatusEl.textContent = message || "";
  systemImportStatusEl.classList.toggle("glossary-status--error", Boolean(isError));
}

function getEffectiveEntry(cn) {
  return glossaryState.effectiveGlossary.find((item) => item.cn === cn) || null;
}

function getUserEntry(cn) {
  return glossaryState.userGlossary.find((item) => normalizeText(item.cn) === normalizeText(cn)) || null;
}

function hasPendingGlossaryChanges() {
  const currentCn = normalizeText(detailCnEl?.value);
  const currentEn = normalizeText(detailEnEl?.value);
  const entry = glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;

  if (glossaryState.mode === "new") {
    return Boolean(currentCn || currentEn);
  }
  if (glossaryState.mode === "override" && entry?.source === "system") {
    return currentEn !== normalizeText(entry.system_en);
  }
  if (!entry || entry.source !== "user") {
    return false;
  }
  return (
    currentCn !== normalizeText(entry.cn) ||
    currentEn !== normalizeText(entry.user_en || entry.en)
  );
}

function syncGlossaryActionState() {
  if (!saveGlossaryBtn || saveGlossaryBtn.hidden) return;
  const hasChanges = hasPendingGlossaryChanges();
  saveGlossaryBtn.disabled = !hasChanges;
}

function resetImportPreviewLimits() {
  glossaryState.importPreviewLimits = {
    preview: 30,
    duplicates: 20,
    invalid: 20,
  };
}

function rebuildEffectiveGlossary() {
  const systemMap = new Map();
  glossaryState.systemGlossary.forEach((item) => {
    const cn = normalizeText(item.cn);
    const en = normalizeText(item.en);
    if (cn && en) {
      systemMap.set(cn, en);
    }
  });
  const userMap = new Map();
  glossaryState.userGlossary.forEach((item) => {
    const cn = normalizeText(item.cn);
    const en = normalizeText(item.en);
    if (cn && en) {
      userMap.set(cn, en);
    }
  });

  const cnSet = new Set([...systemMap.keys(), ...userMap.keys()]);
  glossaryState.effectiveGlossary = Array.from(cnSet)
    .sort((a, b) => a.localeCompare(b, "zh-Hant"))
    .map((cn) => {
      const systemEn = systemMap.get(cn) || null;
      const userEn = userMap.get(cn) || null;
      const source = userEn ? "user" : "system";
      return {
        cn,
        en: userEn || systemEn || "",
        source,
        overridden: Boolean(userEn && systemEn),
        system_en: systemEn,
        user_en: userEn,
      };
    });
}

function renderSummary() {
  if (effectiveCountEl) effectiveCountEl.textContent = String(glossaryState.effectiveGlossary.length);
  if (systemCountEl) systemCountEl.textContent = String(glossaryState.systemGlossary.length);
  if (userCountEl) userCountEl.textContent = String(glossaryState.userGlossary.length);
  if (overrideCountEl) {
    overrideCountEl.textContent = String(glossaryState.effectiveGlossary.filter((item) => item.overridden).length);
  }
}

function renderSystemImportPreview() {
  if (!systemImportSummaryEl || !systemImportPreviewEl || !applySystemGlossaryBtn) return;
  const payload = glossaryState.pendingSystemImport;
  const showUnchangedPreviewEl = document.getElementById("showUnchangedPreview");
  if (!payload) {
    applySystemGlossaryBtn.hidden = true;
    systemImportSummaryEl.hidden = true;
    systemImportPreviewEl.hidden = true;
    systemImportSummaryEl.innerHTML = "";
    systemImportPreviewEl.innerHTML = "";
    applySystemGlossaryBtn.disabled = true;
    return;
  }

  const summary = payload.summary || {};
  const duplicates = Array.isArray(payload.duplicates) ? payload.duplicates : [];
  const invalidRows = Array.isArray(payload.invalid_rows) ? payload.invalid_rows : [];
  const previewRows = Array.isArray(payload.preview_rows) ? payload.preview_rows : [];
  const showUnchanged = Boolean(showUnchangedPreviewEl?.checked);
  const hasBlockingIssues = duplicates.length > 0 || invalidRows.length > 0;
  const duplicateLimit = glossaryState.importPreviewLimits.duplicates;
  const invalidLimit = glossaryState.importPreviewLimits.invalid;
  const previewLimit = glossaryState.importPreviewLimits.preview;
  applySystemGlossaryBtn.hidden = false;
  systemImportSummaryEl.hidden = false;
  systemImportPreviewEl.hidden = false;
  applySystemGlossaryBtn.disabled = !Array.isArray(payload.items) || payload.items.length === 0 || hasBlockingIssues;
  systemImportSummaryEl.innerHTML = `
    <span class="job-badge">匯入筆數 ${summary.incoming || 0}</span>
    <span class="job-badge job-badge--form">新增 ${summary.additions || 0}</span>
    <span class="job-badge job-badge--general_force">更新 ${summary.updates || 0}</span>
    <span class="job-badge">未變更 ${summary.unchanged || 0}</span>
    <span class="job-badge">重複 ${duplicates.length}</span>
    <span class="job-badge">無效 ${invalidRows.length}</span>
  `;

  const blocks = [];
  if (duplicates.length) {
    const visibleDuplicates = duplicates.slice(0, duplicateLimit);
    blocks.push(`
      <div class="glossary-import-block">
        <h3>重複詞彙列</h3>
        <div class="glossary-import-table-wrap">
          <table class="glossary-import-table glossary-import-table--duplicates">
            <thead>
              <tr>
                <th>列號</th>
                <th>中文詞彙</th>
                <th>原英文詞彙</th>
                <th>覆蓋英文詞彙</th>
              </tr>
            </thead>
            <tbody>
              ${visibleDuplicates.map((row) => `
                <tr>
                  <td>row ${row.row}</td>
                  <td>${row.cn}</td>
                  <td>${row.previous_en || "-"}</td>
                  <td>${row.en || ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
        ${duplicates.length > visibleDuplicates.length ? `
          <div class="glossary-import-more">
            <button class="ghost glossary-import-more__btn" type="button" data-more-target="duplicates">顯示更多 (${duplicates.length - visibleDuplicates.length})</button>
          </div>
        ` : ""}
      </div>
    `);
  }
  if (invalidRows.length) {
    const visibleInvalidRows = invalidRows.slice(0, invalidLimit);
    blocks.push(`
      <div class="glossary-import-block">
        <h3>無效列</h3>
        <div class="glossary-import-table-wrap">
          <table class="glossary-import-table glossary-import-table--invalid">
            <thead>
              <tr>
                <th>列號</th>
                <th>中文詞彙</th>
                <th>英文詞彙</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              ${visibleInvalidRows.map((row) => `
                <tr>
                  <td>row ${row.row}</td>
                  <td>${row.cn || "-"}</td>
                  <td>${row.en || "-"}</td>
                  <td>${row.reason || "invalid"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
        ${invalidRows.length > visibleInvalidRows.length ? `
          <div class="glossary-import-more">
            <button class="ghost glossary-import-more__btn" type="button" data-more-target="invalid">顯示更多 (${invalidRows.length - visibleInvalidRows.length})</button>
          </div>
        ` : ""}
      </div>
    `);
  }
  const visibleRows = previewRows
    .filter((row) => showUnchanged || row.status !== "unchanged")
    .slice(0, previewLimit);
  if (previewRows.length) {
    const filteredPreviewRows = previewRows.filter((row) => showUnchanged || row.status !== "unchanged");
    blocks.push(`
      <div class="glossary-import-block">
        <div class="glossary-import-block__header">
          <h3>匯入詞彙</h3>
          <label class="glossary-inline-toggle">
            <input id="showUnchangedPreview" type="checkbox" ${showUnchanged ? "checked" : ""} />
            <span>顯示未變更</span>
          </label>
        </div>
        ${visibleRows.length ? `
          <div class="glossary-import-table-wrap">
            <table class="glossary-import-table glossary-import-table--preview">
              <thead>
                <tr>
                  <th>中文詞彙</th>
                  <th>目前系統英文詞彙</th>
                  <th>匯入英文詞彙</th>
                  <th>狀態</th>
                </tr>
              </thead>
              <tbody>
                ${visibleRows.map((row) => `
                  <tr>
                    <td>${row.cn}</td>
                    <td>${row.current_en || "-"}</td>
                    <td>${row.next_en || ""}</td>
                    <td>
                      <span class="job-badge ${
                        row.status === "update"
                          ? "job-badge--general_force"
                          : row.status === "add"
                            ? "job-badge--form"
                            : ""
                      }">${importStatusLabelMap[row.status] || row.status}</span>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
          ${filteredPreviewRows.length > visibleRows.length ? `
            <div class="glossary-import-more">
              <button class="ghost glossary-import-more__btn" type="button" data-more-target="preview">顯示更多 (${filteredPreviewRows.length - visibleRows.length})</button>
            </div>
          ` : ""}
        ` : `
          <div class="hint">目前只包含未變更項目，勾選「顯示未變更」即可查看。</div>
        `}
      </div>
    `);
  }
  systemImportPreviewEl.innerHTML = blocks.join("");
  document.getElementById("showUnchangedPreview")?.addEventListener("change", renderSystemImportPreview);
  systemImportPreviewEl.querySelectorAll("[data-more-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = String(button.getAttribute("data-more-target") || "");
      if (target === "preview" || target === "duplicates" || target === "invalid") {
        glossaryState.importPreviewLimits[target] += 30;
        renderSystemImportPreview();
      }
    });
  });
}

function filteredGlossaryItems() {
  const keyword = normalizeText(glossarySearchEl?.value).toLowerCase();
  const filter = glossaryFilterEl?.value || "all";
  return glossaryState.effectiveGlossary.filter((item) => {
    if (filter === "system" && item.source !== "system") return false;
    if (filter === "user" && item.source !== "user") return false;
    if (filter === "user_overrides" && !item.overridden) return false;
    if (!keyword) return true;
    const haystacks = [item.cn, item.en, item.system_en, item.user_en]
      .map((value) => String(value || "").toLowerCase());
    return haystacks.some((value) => value.includes(keyword));
  });
}

function renderGlossaryList() {
  if (!glossaryListEl || !glossaryEmptyEl) return;
  glossaryListEl.innerHTML = "";
  const items = filteredGlossaryItems();
  glossaryEmptyEl.style.display = items.length ? "none" : "block";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "glossary-row";
    if (item.cn === glossaryState.selectedCn) {
      button.classList.add("is-selected");
    }

    const header = document.createElement("div");
    header.className = "glossary-row__header";

    const title = document.createElement("div");
    title.className = "glossary-row__title";
    title.textContent = item.cn;

    const meta = document.createElement("div");
    meta.className = "glossary-row__meta";

    const sourceBadge = document.createElement("span");
    sourceBadge.className = `job-badge ${item.source === "user" ? "job-badge--general" : ""}`;
    sourceBadge.textContent = item.source;
    meta.appendChild(sourceBadge);

    if (item.overridden) {
      const overrideBadge = document.createElement("span");
      overrideBadge.className = "job-badge job-badge--general_force";
      overrideBadge.textContent = "override";
      meta.appendChild(overrideBadge);
    }

    header.appendChild(title);
    header.appendChild(meta);
    button.appendChild(header);

    const translation = document.createElement("div");
    translation.className = "glossary-row__translation";
    translation.textContent = item.en;
    button.appendChild(translation);
    button.addEventListener("click", () => {
      glossaryState.selectedCn = item.cn;
      glossaryState.mode = item.source === "system" ? "system" : "user";
      renderGlossaryList();
      renderDetailPanel();
    });
    glossaryListEl.appendChild(button);
  });
}

function renderDetailPanel() {
  const entry = glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;
  const isNew = !entry && glossaryState.mode === "new";
  const isSystemOnly = entry && entry.source === "system";
  const isUserEntry = entry && entry.source === "user";
  const isOverride = Boolean(entry?.overridden);

  if (isNew) {
    detailTitleEl.textContent = "新增自訂詞彙";
    detailBadgeEl.textContent = "user";
    detailBadgeEl.className = "job-badge job-badge--general";
    detailMetaEl.textContent = "若中文詞彙與系統中文詞彙相同，會視為覆蓋";
    detailCnEl.value = "";
    detailEnEl.value = "";
    detailCnEl.disabled = false;
    detailEnEl.disabled = false;
    saveGlossaryBtn.hidden = false;
    deleteGlossaryBtn.hidden = true;
    overrideGlossaryBtn.hidden = true;
    saveGlossaryBtn.textContent = "新增自訂詞彙";
    syncGlossaryActionState();
    return;
  }

  if (!entry) {
    detailTitleEl.textContent = "詞彙詳情";
    detailBadgeEl.textContent = "view";
    detailBadgeEl.className = "job-badge";
    detailMetaEl.textContent = "從左側選擇詞彙，或新增自訂詞彙";
    detailCnEl.value = "";
    detailEnEl.value = "";
    detailCnEl.disabled = false;
    detailEnEl.disabled = false;
    saveGlossaryBtn.hidden = false;
    deleteGlossaryBtn.hidden = true;
    overrideGlossaryBtn.hidden = true;
    saveGlossaryBtn.textContent = "儲存";
    syncGlossaryActionState();
    return;
  }

  detailTitleEl.textContent = entry.cn;
  detailCnEl.value = entry.cn;
  detailEnEl.value = entry.user_en || entry.en;
  detailCnEl.disabled = isSystemOnly || isOverride;
  detailEnEl.disabled = false;

  if (isSystemOnly) {
    detailBadgeEl.textContent = "system";
    detailBadgeEl.className = "job-badge";
    detailMetaEl.textContent = "系統詞彙不能直接修改，可建立自訂詞彙覆蓋";
    detailEnEl.value = entry.system_en || "";
    detailEnEl.disabled = true;
    saveGlossaryBtn.hidden = true;
    saveGlossaryBtn.disabled = true;
    deleteGlossaryBtn.hidden = true;
    overrideGlossaryBtn.hidden = false;
    return;
  }

  detailBadgeEl.textContent = isOverride ? "user override" : "user";
  detailBadgeEl.className = `job-badge ${isOverride ? "job-badge--general_force" : "job-badge--general"}`;
  detailMetaEl.textContent = isOverride
    ? "這筆自訂詞彙正在覆蓋系統詞彙"
    : "使用者自訂詞彙，可直接編輯或刪除";
  saveGlossaryBtn.hidden = false;
  deleteGlossaryBtn.hidden = false;
  overrideGlossaryBtn.hidden = true;
  saveGlossaryBtn.textContent = "儲存修改";
  syncGlossaryActionState();
}

async function persistUserGlossary() {
  const res = await fetch("/api/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ glossary: glossaryState.userGlossary }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.ok === false) {
    throw new Error(payload.error || "儲存 glossary 失敗");
  }
  glossaryState.userGlossary = Array.isArray(payload.glossary) ? payload.glossary : [];
  rebuildEffectiveGlossary();
}

async function loadGlossaryLibrary() {
  setGlossaryStatus("載入中...");
  try {
    const res = await fetch("/api/glossary/library");
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || "載入 glossary 失敗");
    }
    glossaryState.systemGlossary = Array.isArray(payload.system_glossary) ? payload.system_glossary : [];
    glossaryState.userGlossary = Array.isArray(payload.user_glossary) ? payload.user_glossary : [];
    glossaryState.effectiveGlossary = Array.isArray(payload.effective_glossary) ? payload.effective_glossary : [];
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    renderSystemImportPreview();
    setGlossaryStatus(`已載入 ${glossaryState.effectiveGlossary.length} 筆有效詞彙`);
  } catch (error) {
    setGlossaryStatus(error.message || "載入 glossary 失敗", true);
  }
}

function startNewGlossaryEntry() {
  glossaryState.selectedCn = null;
  glossaryState.mode = "new";
  renderGlossaryList();
  renderDetailPanel();
  detailCnEl?.focus();
}

function startOverrideEntry() {
  const entry = glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;
  if (!entry || entry.source !== "system") return;
  detailTitleEl.textContent = `${entry.cn} 覆蓋`;
  detailBadgeEl.textContent = "user override";
  detailBadgeEl.className = "job-badge job-badge--general_force";
  detailMetaEl.textContent = "建立自訂覆蓋後，翻譯流程將優先使用這筆 user 詞彙";
  detailCnEl.value = entry.cn;
  detailCnEl.disabled = true;
  detailEnEl.value = entry.system_en || "";
  detailEnEl.disabled = false;
  saveGlossaryBtn.hidden = false;
  deleteGlossaryBtn.hidden = true;
  overrideGlossaryBtn.hidden = true;
  saveGlossaryBtn.textContent = "新增自訂詞彙覆蓋";
  glossaryState.mode = "override";
  syncGlossaryActionState();
  detailEnEl.focus();
}

async function saveCurrentGlossary() {
  const cn = normalizeText(detailCnEl?.value);
  const en = normalizeText(detailEnEl?.value);
  if (!cn || !en) {
    setGlossaryStatus("請輸入完整的中文與英文詞彙", true);
    return;
  }
  const originalButtonText = saveGlossaryBtn?.textContent || "儲存";
  if (saveGlossaryBtn) {
    saveGlossaryBtn.disabled = true;
    saveGlossaryBtn.textContent = "儲存中...";
  }

  const currentEntry = glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;
  let targetCn = cn;
  if (glossaryState.mode === "override" && currentEntry?.source === "system") {
    targetCn = currentEntry.cn;
  }
  if (currentEntry?.overridden) {
    targetCn = currentEntry.cn;
  }

  const originalCn = currentEntry?.source === "user" ? currentEntry.cn : null;
  const nextUserGlossary = glossaryState.userGlossary.filter((item) => {
    const itemCn = normalizeText(item.cn);
    if (itemCn === targetCn) {
      return false;
    }
    if (originalCn && itemCn === originalCn) {
      return false;
    }
    return true;
  });
  nextUserGlossary.unshift({ cn: targetCn, en });
  glossaryState.userGlossary = nextUserGlossary;

  try {
    await persistUserGlossary();
    glossaryState.selectedCn = targetCn;
    glossaryState.mode = "user";
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    setGlossaryStatus(`已儲存詞彙「${targetCn}」`);
    if (saveGlossaryBtn) {
      saveGlossaryBtn.textContent = "已儲存";
      window.setTimeout(() => {
        if (saveGlossaryBtn.textContent === "已儲存") {
          renderDetailPanel();
        }
      }, 1200);
    }
  } catch (error) {
    setGlossaryStatus(error.message || "儲存 glossary 失敗", true);
    if (saveGlossaryBtn) {
      saveGlossaryBtn.textContent = originalButtonText;
      syncGlossaryActionState();
    }
  }
}

async function deleteCurrentGlossary() {
  const entry = glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;
  if (!entry || entry.source !== "user") return;
  glossaryState.userGlossary = glossaryState.userGlossary.filter((item) => normalizeText(item.cn) !== entry.cn);
  try {
    await persistUserGlossary();
    glossaryState.mode = "new";
    glossaryState.selectedCn = null;
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    setGlossaryStatus(`已刪除自訂詞彙「${entry.cn}」`);
  } catch (error) {
    setGlossaryStatus(error.message || "刪除 glossary 失敗", true);
  }
}

async function previewSystemGlossaryImport() {
  const file = systemGlossaryFileEl?.files?.[0];
  if (!file) {
    setSystemImportStatus("請先選擇 .xlsx 檔案", true);
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  setSystemImportStatus(`正在解析 ${file.name} ...`);
  try {
    const res = await fetch("/api/glossary/system-import-preview", {
      method: "POST",
      body: formData,
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || "預覽匯入失敗");
    }
    glossaryState.pendingSystemImport = payload;
    resetImportPreviewLimits();
    renderSystemImportPreview();
    if ((payload.duplicates || []).length || (payload.invalid_rows || []).length) {
      setSystemImportStatus(`已解析 ${file.name}，請先排除詞彙表重複詞彙列與無效列，排除後再重新上傳`, true);
    } else {
      setSystemImportStatus(`已解析 ${file.name}，可套用到系統詞彙`);
    }
  } catch (error) {
    glossaryState.pendingSystemImport = null;
    resetImportPreviewLimits();
    renderSystemImportPreview();
    setSystemImportStatus(error.message || "預覽匯入失敗", true);
  }
}

async function applySystemGlossaryImport() {
  const payload = glossaryState.pendingSystemImport;
  if (!payload || !Array.isArray(payload.items) || !payload.items.length) {
    setSystemImportStatus("沒有可匯入的 system 詞彙", true);
    return;
  }
  if ((payload.duplicates || []).length || (payload.invalid_rows || []).length) {
    setSystemImportStatus("請先排除重複詞彙列與無效列，才能套用到系統詞彙", true);
    return;
  }
  setSystemImportStatus("正在合併系統詞彙...");
  try {
    const res = await fetch("/api/glossary/system-import-apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: payload.items,
        duplicates: payload.duplicates || [],
        invalid_rows: payload.invalid_rows || [],
      }),
    });
    const applied = await res.json().catch(() => ({}));
    if (!res.ok || applied.ok === false) {
      throw new Error(applied.error || "詞彙匯入失敗");
    }
    glossaryState.systemGlossary = Array.isArray(applied.system_glossary) ? applied.system_glossary : [];
    glossaryState.userGlossary = Array.isArray(applied.user_glossary) ? applied.user_glossary : glossaryState.userGlossary;
    glossaryState.effectiveGlossary = Array.isArray(applied.effective_glossary) ? applied.effective_glossary : glossaryState.effectiveGlossary;
    glossaryState.pendingSystemImport = null;
    resetImportPreviewLimits();
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    renderSystemImportPreview();
    setSystemImportStatus("已完成系統詞彙合併");
    setGlossaryStatus(`已更新系統詞彙，現在共有 ${glossaryState.systemGlossary.length} 筆系統詞彙`);
  } catch (error) {
    setSystemImportStatus(error.message || "system 詞彙匯入失敗", true);
  }
}

function exportSystemGlossary() {
  window.location.href = "/api/glossary/system-export";
}

glossarySearchEl?.addEventListener("input", renderGlossaryList);
glossaryFilterEl?.addEventListener("change", renderGlossaryList);
glossaryRefreshBtn?.addEventListener("click", loadGlossaryLibrary);
glossaryNewBtn?.addEventListener("click", startNewGlossaryEntry);
exportSystemGlossaryBtn?.addEventListener("click", exportSystemGlossary);
saveGlossaryBtn?.addEventListener("click", saveCurrentGlossary);
deleteGlossaryBtn?.addEventListener("click", deleteCurrentGlossary);
overrideGlossaryBtn?.addEventListener("click", startOverrideEntry);
previewSystemGlossaryBtn?.addEventListener("click", previewSystemGlossaryImport);
applySystemGlossaryBtn?.addEventListener("click", applySystemGlossaryImport);
detailCnEl?.addEventListener("input", syncGlossaryActionState);
detailEnEl?.addEventListener("input", syncGlossaryActionState);

startNewGlossaryEntry();
loadGlossaryLibrary();
