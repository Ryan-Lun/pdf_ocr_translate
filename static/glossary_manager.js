const glossarySearchEl = document.getElementById("glossarySearch");
const glossaryFilterEl = document.getElementById("glossaryFilter");
const glossaryRefreshBtn = document.getElementById("glossaryRefreshBtn");
const includeInactiveEntriesEl = document.getElementById("includeInactiveEntries");
const glossaryNewBtn = document.getElementById("glossaryNewBtn");
const glossaryStatusEl = document.getElementById("glossaryStatus");
const glossaryListEl = document.getElementById("glossaryList");
const glossaryEmptyEl = document.getElementById("glossaryEmpty");
const systemGlossaryFileEl = document.getElementById("systemGlossaryFile");
const exportSystemGlossaryBtn = document.getElementById("exportSystemGlossaryBtn");
const exportGlossaryJsonBtn = document.getElementById("exportGlossaryJsonBtn");
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
const libraryNewBtn = document.getElementById("libraryNewBtn");
const libraryStatusEl = document.getElementById("libraryStatus");
const libraryListEl = document.getElementById("libraryList");
const libraryDetailTitleEl = document.getElementById("libraryDetailTitle");
const libraryDetailBadgeEl = document.getElementById("libraryDetailBadge");
const libraryCodeEl = document.getElementById("libraryCode");
const libraryNameEl = document.getElementById("libraryName");
const libraryDepartmentCodeEl = document.getElementById("libraryDepartmentCode");
const saveLibraryBtn = document.getElementById("saveLibraryBtn");
const activateLibraryBtn = document.getElementById("activateLibraryBtn");
const disableLibraryBtn = document.getElementById("disableLibraryBtn");

const glossaryState = {
  systemGlossary: [],
  userGlossary: [],
  effectiveGlossary: [],
  selectedCn: null,
  selectedEntryId: null,
  mode: "new",
  pendingSystemImport: null,
  libraries: [],
  selectedLibraryId: null,
  libraryMode: "new",
  includeInactiveEntries: false,
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

function setLibraryStatus(message, isError = false) {
  if (!libraryStatusEl) return;
  libraryStatusEl.textContent = message || "";
  libraryStatusEl.classList.toggle("glossary-status--error", Boolean(isError));
  libraryStatusEl.classList.toggle("glossary-status--success", Boolean(message) && !isError);
}

function normalizeText(value) {
  return String(value || "").trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}


function setSystemImportStatus(message, isError = false) {
  if (!systemImportStatusEl) return;
  systemImportStatusEl.textContent = message || "";
  systemImportStatusEl.classList.toggle("glossary-status--error", Boolean(isError));
}

function getEffectiveEntry(cn) {
  return glossaryState.effectiveGlossary.find((item) => item.cn === cn) || null;
}

function getSelectedEntry() {
  if (glossaryState.selectedEntryId != null) {
    return glossaryState.effectiveGlossary.find((item) => Number(item.entry_id || item.id) === Number(glossaryState.selectedEntryId)) || null;
  }
  return glossaryState.selectedCn ? getEffectiveEntry(glossaryState.selectedCn) : null;
}

function hasPendingGlossaryChanges() {
  const currentCn = normalizeText(detailCnEl?.value);
  const currentEn = normalizeText(detailEnEl?.value);
  const entry = getSelectedEntry();

  if (glossaryState.mode === "new") {
    return Boolean(currentCn || currentEn);
  }
  if (!entry || entry.status === "disabled") {
    return false;
  }
  return currentCn !== normalizeText(entry.cn) || currentEn !== normalizeText(entry.en);
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
  glossaryState.effectiveGlossary = glossaryState.systemGlossary.map((item) => ({
    entry_id: item.entry_id || item.id || null,
    cn: normalizeText(item.cn),
    en: normalizeText(item.en),
    source: "system",
    overridden: false,
    system_en: normalizeText(item.en),
    user_en: null,
    status: item.status || "active",
  })).filter((item) => item.cn && item.en);
}


function renderSummary() {
  const activeCount = glossaryState.effectiveGlossary.filter((item) => item.status !== "disabled").length;
  const inactiveCount = glossaryState.effectiveGlossary.filter((item) => item.status === "disabled").length;
  if (effectiveCountEl) effectiveCountEl.textContent = String(activeCount);
  if (systemCountEl) systemCountEl.textContent = String(activeCount);
  if (userCountEl) userCountEl.textContent = String(inactiveCount);
  if (overrideCountEl) overrideCountEl.textContent = String(glossaryState.effectiveGlossary.length);
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
                  <td>${escapeHtml(row.cn)}</td>
                  <td>${escapeHtml(row.previous_en || "-")}</td>
                  <td>${escapeHtml(row.en || "")}</td>
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
                  <td>${escapeHtml(row.cn || "-")}</td>
                  <td>${escapeHtml(row.en || "-")}</td>
                  <td>${escapeHtml(row.reason || "invalid")}</td>
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
                    <td>${escapeHtml(row.cn)}</td>
                    <td>${escapeHtml(row.current_en || "-")}</td>
                    <td>${escapeHtml(row.next_en || "")}</td>
                    <td>
                      <span class="job-badge ${
                        row.status === "update"
                          ? "job-badge--general_force"
                          : row.status === "add"
                            ? "job-badge--form"
                            : ""
                      }">${escapeHtml(importStatusLabelMap[row.status] || row.status)}</span>
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

function getSelectedLibrary() {
  return glossaryState.libraries.find((library) => Number(library.id) === Number(glossaryState.selectedLibraryId)) || null;
}

function renderLibraryList() {
  if (!libraryListEl) return;
  libraryListEl.innerHTML = "";
  const libraries = Array.isArray(glossaryState.libraries) ? glossaryState.libraries : [];
  if (!libraries.length) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "目前沒有部門詞彙庫";
    libraryListEl.appendChild(empty);
    return;
  }
  libraries.forEach((library) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "glossary-row glossary-library-admin-row";
    if (Number(library.id) === Number(glossaryState.selectedLibraryId)) {
      button.classList.add("is-selected");
    }

    const header = document.createElement("div");
    header.className = "glossary-row__header";

    const title = document.createElement("div");
    title.className = "glossary-row__title";
    title.textContent = library.name || "未命名詞彙庫";

    const meta = document.createElement("div");
    meta.className = "glossary-row__meta";

    const statusBadge = document.createElement("span");
    statusBadge.className = `job-badge ${library.is_active ? "job-badge--form" : ""}`;
    statusBadge.textContent = library.is_active ? "active" : "inactive";
    meta.appendChild(statusBadge);

    if (library.is_default) {
      const defaultBadge = document.createElement("span");
      defaultBadge.className = "job-badge";
      defaultBadge.textContent = "default";
      meta.appendChild(defaultBadge);
    }

    header.appendChild(title);
    header.appendChild(meta);
    button.appendChild(header);

    const detail = document.createElement("div");
    detail.className = "glossary-row__translation";
    detail.textContent = `${library.department_code || "-"} / ${library.code || "-"}`;
    button.appendChild(detail);

    button.addEventListener("click", () => {
      glossaryState.selectedLibraryId = library.id;
      glossaryState.libraryMode = "edit";
      glossaryState.selectedCn = null;
      glossaryState.selectedEntryId = null;
      glossaryState.mode = "new";
      glossaryState.pendingSystemImport = null;
      resetImportPreviewLimits();
      loadGlossaryLibrary(library.id);
    });
    libraryListEl.appendChild(button);
  });
}

function renderLibraryPanel() {
  const library = getSelectedLibrary();
  const isNew = glossaryState.libraryMode === "new" || !library;
  if (!libraryDetailTitleEl || !libraryDetailBadgeEl || !libraryCodeEl || !libraryNameEl || !libraryDepartmentCodeEl || !saveLibraryBtn || !activateLibraryBtn || !disableLibraryBtn) return;

  if (isNew) {
    libraryDetailTitleEl.textContent = "新增詞彙庫";
    libraryDetailBadgeEl.textContent = "new";
    libraryDetailBadgeEl.className = "job-badge job-badge--general";
    libraryCodeEl.value = "";
    libraryNameEl.value = "";
    libraryDepartmentCodeEl.value = "";
    saveLibraryBtn.textContent = "新增詞彙庫";
    saveLibraryBtn.disabled = false;
    activateLibraryBtn.hidden = true;
    disableLibraryBtn.hidden = true;
    return;
  }

  libraryDetailTitleEl.textContent = library.name || "詞彙庫";
  libraryDetailBadgeEl.textContent = library.is_active ? "active" : "inactive";
  libraryDetailBadgeEl.className = `job-badge ${library.is_active ? "job-badge--form" : ""}`;
  libraryCodeEl.value = library.code || "";
  libraryNameEl.value = library.name || "";
  libraryDepartmentCodeEl.value = library.department_code || "";
  saveLibraryBtn.textContent = "儲存修改";
  saveLibraryBtn.disabled = !library.is_active;
  activateLibraryBtn.hidden = library.is_active;
  disableLibraryBtn.hidden = !library.is_active;
}

function startNewLibrary() {
  glossaryState.selectedLibraryId = null;
  glossaryState.libraryMode = "new";
  renderLibraryList();
  renderLibraryPanel();
  libraryNameEl?.focus();
}

function applyLibraryPayload(payload) {
  glossaryState.libraries = Array.isArray(payload.libraries) ? payload.libraries : [];
  renderLibraryList();
  renderLibraryPanel();
}

async function saveCurrentLibrary() {
  const name = normalizeText(libraryNameEl?.value);
  const departmentCode = normalizeText(libraryDepartmentCodeEl?.value);
  if (!name || !departmentCode) {
    setLibraryStatus("請輸入詞彙庫名稱與部門代碼", true);
    return;
  }
  const library = getSelectedLibrary();
  const isNew = glossaryState.libraryMode === "new" || !library;
  const url = isNew ? "/api/glossary/libraries" : `/api/glossary/libraries/${library.id}`;
  const method = isNew ? "POST" : "PATCH";
  const originalText = saveLibraryBtn?.textContent || "儲存";
  if (saveLibraryBtn) {
    saveLibraryBtn.disabled = true;
    saveLibraryBtn.textContent = "儲存中...";
  }
  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, department_code: departmentCode }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || "儲存詞彙庫失敗");
    }
    glossaryState.selectedLibraryId = payload.library?.id || glossaryState.selectedLibraryId;
    glossaryState.libraryMode = "edit";
    applyGlossaryPayload(payload);
    renderLibraryList();
    renderLibraryPanel();
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    setLibraryStatus(`已儲存詞彙庫「${payload.library?.name || name}」`);
  } catch (error) {
    setLibraryStatus(error.message || "儲存詞彙庫失敗", true);
  } finally {
    if (saveLibraryBtn) {
      saveLibraryBtn.textContent = originalText;
    }
    renderLibraryPanel();
  }
}

async function changeCurrentLibraryActiveState({ active }) {
  const library = getSelectedLibrary();
  if (!library || library.is_active === active) return;
  const actionLabel = active ? "啟用" : "停用";
  const button = active ? activateLibraryBtn : disableLibraryBtn;
  const progressLabel = active ? "啟用中..." : "停用中...";
  const failureLabel = active ? "啟用詞彙庫失敗" : "停用詞彙庫失敗";
  const successLabel = active ? "已啟用" : "已停用";
  const warning = active
    ? `確定啟用「${library.name}」？啟用後會出現在新任務選單。`
    : `確定停用「${library.name}」？停用後不會出現在新任務選單。`;
  if (!window.confirm(warning)) {
    return;
  }
  const originalText = button?.textContent || `${actionLabel}詞彙庫`;
  if (button) {
    button.disabled = true;
    button.textContent = progressLabel;
  }
  try {
    const endpoint = active ? "activate" : "disable";
    const res = await fetch(`/api/glossary/libraries/${library.id}/${endpoint}`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || failureLabel);
    }
    glossaryState.selectedLibraryId = payload.library?.id || library.id;
    glossaryState.libraryMode = "edit";
    applyGlossaryPayload(payload);
    renderLibraryList();
    renderLibraryPanel();
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    setLibraryStatus(`${successLabel}詞彙庫「${payload.library?.name || library.name}」`);
  } catch (error) {
    setLibraryStatus(error.message || failureLabel, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
    renderLibraryPanel();
  }
}

async function disableCurrentLibrary() {
  await changeCurrentLibraryActiveState({ active: false });
}

async function activateCurrentLibrary() {
  await changeCurrentLibraryActiveState({ active: true });
}

function selectedLibraryQuery() {
  const library = getSelectedLibrary();
  const params = new URLSearchParams();
  if (library?.id) params.set("library_id", String(library.id));
  if (glossaryState.includeInactiveEntries) params.set("include_inactive", "1");
  const query = params.toString();
  return query ? `?${query}` : "";
}

function selectedLibraryEntryBaseUrl() {
  const library = getSelectedLibrary();
  if (!library?.id) return null;
  return `/api/glossary/libraries/${library.id}/entries`;
}

function filteredGlossaryItems() {
  const keyword = normalizeText(glossarySearchEl?.value).toLowerCase();
  const filter = glossaryFilterEl?.value || "all";
  return glossaryState.effectiveGlossary.filter((item) => {
    const isInactive = item.status === "disabled";
    if (!glossaryState.includeInactiveEntries && isInactive) return false;
    if (filter === "inactive" && !isInactive) return false;
    if (filter === "all" && isInactive && !glossaryState.includeInactiveEntries) return false;
    if (!keyword) return true;
    const haystacks = [item.cn, item.en, item.system_en, item.user_en, item.status]
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
    const entryId = item.entry_id || item.id || null;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "glossary-row";
    if (entryId != null && Number(entryId) === Number(glossaryState.selectedEntryId)) {
      button.classList.add("is-selected");
    }

    const header = document.createElement("div");
    header.className = "glossary-row__header";

    const title = document.createElement("div");
    title.className = "glossary-row__title";
    title.textContent = item.cn;

    const meta = document.createElement("div");
    meta.className = "glossary-row__meta";

    const statusBadge = document.createElement("span");
    statusBadge.className = `job-badge ${item.status === "disabled" ? "" : "job-badge--form"}`;
    statusBadge.textContent = item.status === "disabled" ? "inactive" : "active";
    meta.appendChild(statusBadge);

    header.appendChild(title);
    header.appendChild(meta);
    button.appendChild(header);

    const translation = document.createElement("div");
    translation.className = "glossary-row__translation";
    translation.textContent = item.en;
    button.appendChild(translation);
    button.addEventListener("click", () => {
      glossaryState.selectedEntryId = entryId;
      glossaryState.selectedCn = item.cn;
      glossaryState.mode = "edit";
      renderGlossaryList();
      renderDetailPanel();
    });
    glossaryListEl.appendChild(button);
  });
}


function renderDetailPanel() {
  const entry = getSelectedEntry();
  const isNew = !entry && glossaryState.mode === "new";
  const isInactive = entry?.status === "disabled";

  if (isNew) {
    detailTitleEl.textContent = "新增詞彙";
    detailBadgeEl.textContent = "active";
    detailBadgeEl.className = "job-badge job-badge--form";
    detailMetaEl.textContent = "新增詞彙會寫入目前選取的部門詞彙庫";
    detailCnEl.value = "";
    detailEnEl.value = "";
    detailCnEl.disabled = false;
    detailEnEl.disabled = false;
    saveGlossaryBtn.hidden = false;
    deleteGlossaryBtn.hidden = true;
    overrideGlossaryBtn.hidden = true;
    saveGlossaryBtn.textContent = "新增詞彙";
    syncGlossaryActionState();
    return;
  }

  if (!entry) {
    detailTitleEl.textContent = "詞彙詳情";
    detailBadgeEl.textContent = "view";
    detailBadgeEl.className = "job-badge";
    detailMetaEl.textContent = "從左側選擇詞彙，或新增詞彙";
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
  detailEnEl.value = entry.en;
  detailCnEl.disabled = isInactive;
  detailEnEl.disabled = isInactive;
  detailBadgeEl.textContent = isInactive ? "inactive" : "active";
  detailBadgeEl.className = `job-badge ${isInactive ? "" : "job-badge--form"}`;
  detailMetaEl.textContent = isInactive
    ? "這筆詞彙已停用，只保留作為歷史紀錄"
    : "這筆詞彙屬於目前選取的部門詞彙庫";
  saveGlossaryBtn.hidden = isInactive;
  deleteGlossaryBtn.hidden = isInactive;
  overrideGlossaryBtn.hidden = true;
  saveGlossaryBtn.textContent = "儲存修改";
  syncGlossaryActionState();
}


async function upsertSelectedGlossaryEntry(cn, en, entryId = null) {
  const baseUrl = selectedLibraryEntryBaseUrl();
  if (!baseUrl) {
    throw new Error("請先選擇部門詞彙庫");
  }
  const url = entryId ? `${baseUrl}/${entryId}` : baseUrl;
  const res = await fetch(url, {
    method: entryId ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cn, en }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.ok === false) {
    throw new Error(payload.error || "儲存 glossary 失敗");
  }
  applyGlossaryPayload(payload);
  return payload.entry || null;
}

function applyGlossaryPayload(payload) {
  glossaryState.systemGlossary = Array.isArray(payload.entries)
    ? payload.entries.map((entry) => ({
        id: entry.id,
        entry_id: entry.id,
        cn: entry.cn,
        en: entry.en,
        status: entry.status || "active",
      }))
    : Array.isArray(payload.system_glossary)
      ? payload.system_glossary
      : [];
  glossaryState.userGlossary = [];
  rebuildEffectiveGlossary();
  glossaryState.libraries = Array.isArray(payload.libraries) ? payload.libraries : glossaryState.libraries;
  if (payload.selected_library?.id) {
    glossaryState.selectedLibraryId = payload.selected_library.id;
    glossaryState.libraryMode = "edit";
  }
}


async function loadGlossaryLibrary(libraryId = glossaryState.selectedLibraryId) {
  setGlossaryStatus("載入中...");
  try {
    const params = new URLSearchParams();
    if (libraryId) params.set("library_id", String(libraryId));
    if (glossaryState.includeInactiveEntries) params.set("include_inactive", "1");
    const query = params.toString();
    const res = await fetch(`/api/glossary/library${query ? `?${query}` : ""}`);
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || "載入 glossary 失敗");
    }
    applyGlossaryPayload(payload);
    const entryStillVisible = glossaryState.effectiveGlossary.some((entry) => Number(entry.entry_id || entry.id) === Number(glossaryState.selectedEntryId));
    if (!entryStillVisible) {
      glossaryState.selectedEntryId = null;
      glossaryState.selectedCn = null;
      glossaryState.mode = "new";
    }
    renderLibraryList();
    renderLibraryPanel();
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    renderSystemImportPreview();
    const library = getSelectedLibrary();
    setGlossaryStatus(`已載入 ${library?.name || "目前詞彙庫"} ${glossaryState.effectiveGlossary.length} 筆詞彙`);
  } catch (error) {
    setGlossaryStatus(error.message || "載入 glossary 失敗", true);
  }
}


function startNewGlossaryEntry() {
  glossaryState.selectedCn = null;
  glossaryState.selectedEntryId = null;
  glossaryState.mode = "new";
  renderGlossaryList();
  renderDetailPanel();
  detailCnEl?.focus();
}

function startOverrideEntry() {
  startNewGlossaryEntry();
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

  try {
    const selectedEntry = getSelectedEntry();
    const entryId = glossaryState.mode === "edit" ? (selectedEntry?.entry_id || selectedEntry?.id || null) : null;
    const entry = await upsertSelectedGlossaryEntry(cn, en, entryId);
    glossaryState.selectedEntryId = entry?.id || glossaryState.selectedEntryId;
    glossaryState.selectedCn = cn;
    glossaryState.mode = "edit";
    renderSummary();
    renderLibraryList();
    renderLibraryPanel();
    renderGlossaryList();
    renderDetailPanel();
    setGlossaryStatus(`已儲存詞彙「${cn}」`);
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
  const entry = getSelectedEntry();
  const baseUrl = selectedLibraryEntryBaseUrl();
  const entryId = entry?.entry_id || entry?.id;
  if (!entry || !entryId || !baseUrl || entry.status === "disabled") return;
  if (!window.confirm(`確定停用「${entry.cn}」？`)) {
    return;
  }
  try {
    const res = await fetch(`${baseUrl}/${entryId}/disable`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || "停用 glossary 失敗");
    }
    applyGlossaryPayload(payload);
    glossaryState.mode = "new";
    glossaryState.selectedCn = null;
    glossaryState.selectedEntryId = null;
    renderSummary();
    renderLibraryList();
    renderLibraryPanel();
    renderGlossaryList();
    renderDetailPanel();
    setGlossaryStatus(`已停用詞彙「${entry.cn}」`);
  } catch (error) {
    setGlossaryStatus(error.message || "停用 glossary 失敗", true);
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
    const res = await fetch(`/api/glossary/system-import-preview${selectedLibraryQuery()}`, {
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
      setSystemImportStatus(`已解析 ${file.name}，可套用到目前詞彙庫`);
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
    setSystemImportStatus("沒有可匯入的詞彙", true);
    return;
  }
  if ((payload.duplicates || []).length || (payload.invalid_rows || []).length) {
    setSystemImportStatus("請先排除重複詞彙列與無效列，才能套用到目前詞彙庫", true);
    return;
  }
  setSystemImportStatus("正在合併目前詞彙庫...");
  try {
    const res = await fetch("/api/glossary/system-import-apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        library_id: getSelectedLibrary()?.id || null,
        items: payload.items,
        duplicates: payload.duplicates || [],
        invalid_rows: payload.invalid_rows || [],
      }),
    });
    const applied = await res.json().catch(() => ({}));
    if (!res.ok || applied.ok === false) {
      throw new Error(applied.error || "詞彙匯入失敗");
    }
    applyGlossaryPayload(applied);
    renderLibraryList();
    renderLibraryPanel();
    glossaryState.pendingSystemImport = null;
    resetImportPreviewLimits();
    renderSummary();
    renderGlossaryList();
    renderDetailPanel();
    renderSystemImportPreview();
    setSystemImportStatus("已完成目前詞彙庫合併");
    setGlossaryStatus(`已更新目前詞彙庫，現在共有 ${glossaryState.systemGlossary.length} 筆 active 詞彙`);
  } catch (error) {
    setSystemImportStatus(error.message || "詞彙匯入失敗", true);
  }
}

function exportSystemGlossary() {
  window.location.href = `/api/glossary/system-export${selectedLibraryQuery()}`;
}

function exportGlossaryJson() {
  window.location.href = `/api/glossary/export-json${selectedLibraryQuery()}`;
}

glossarySearchEl?.addEventListener("input", renderGlossaryList);
glossaryFilterEl?.addEventListener("change", renderGlossaryList);
includeInactiveEntriesEl?.addEventListener("change", () => {
  glossaryState.includeInactiveEntries = Boolean(includeInactiveEntriesEl.checked);
  loadGlossaryLibrary();
});
glossaryRefreshBtn?.addEventListener("click", loadGlossaryLibrary);
glossaryNewBtn?.addEventListener("click", startNewGlossaryEntry);
exportSystemGlossaryBtn?.addEventListener("click", exportSystemGlossary);
exportGlossaryJsonBtn?.addEventListener("click", exportGlossaryJson);
saveGlossaryBtn?.addEventListener("click", saveCurrentGlossary);
deleteGlossaryBtn?.addEventListener("click", deleteCurrentGlossary);
overrideGlossaryBtn?.addEventListener("click", startOverrideEntry);
libraryNewBtn?.addEventListener("click", startNewLibrary);
saveLibraryBtn?.addEventListener("click", saveCurrentLibrary);
activateLibraryBtn?.addEventListener("click", activateCurrentLibrary);
disableLibraryBtn?.addEventListener("click", disableCurrentLibrary);
previewSystemGlossaryBtn?.addEventListener("click", previewSystemGlossaryImport);
applySystemGlossaryBtn?.addEventListener("click", applySystemGlossaryImport);
detailCnEl?.addEventListener("input", syncGlossaryActionState);
detailEnEl?.addEventListener("input", syncGlossaryActionState);

startNewGlossaryEntry();
loadGlossaryLibrary();
