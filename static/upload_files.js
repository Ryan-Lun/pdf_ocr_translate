function bindUploadFiles(options) {
  const uploadInput = document.getElementById(options.inputId);
  const uploadFilesSummary = document.getElementById(options.summaryId);
  const uploadFilesToggle = document.getElementById(options.toggleId);
  const uploadFilesList = document.getElementById(options.listId);

  if (!uploadInput || !uploadFilesSummary || !uploadFilesToggle || !uploadFilesList) {
    return;
  }

  const emptyText = options.emptyText || "尚未選擇檔案";
  const expandedText = options.expandedText || "收合";
  const collapsedText = options.collapsedText || "展開";
  const removeText = options.removeText || "移除";
  const onFilesChange = typeof options.onFilesChange === "function" ? options.onFilesChange : null;
  let filesExpanded = false;
  let selectedFiles = [];

  const fileKey = (file) => `${file.name}::${file.size}::${file.lastModified}`;

  const syncUploadInputFiles = () => {
    const dataTransfer = new DataTransfer();
    selectedFiles.forEach((file) => dataTransfer.items.add(file));
    uploadInput.files = dataTransfer.files;
  };

  const renderUploadFiles = () => {
    if (!selectedFiles.length) {
      uploadFilesSummary.textContent = emptyText;
      uploadFilesToggle.style.display = "none";
      uploadFilesList.style.display = "none";
      uploadFilesList.innerHTML = "";
      filesExpanded = false;
      uploadFilesToggle.textContent = collapsedText;
      onFilesChange?.([]);
      return;
    }

    uploadFilesSummary.textContent = `已選 ${selectedFiles.length} 個檔案`;
    uploadFilesToggle.style.display = "inline-flex";
    uploadFilesToggle.textContent = filesExpanded ? expandedText : collapsedText;

    if (!filesExpanded) {
      uploadFilesList.style.display = "none";
      uploadFilesList.innerHTML = "";
      onFilesChange?.([...selectedFiles]);
      return;
    }

    uploadFilesList.innerHTML = "";
    const listEl = document.createElement("ul");
    selectedFiles.forEach((file) => {
      const itemEl = document.createElement("li");
      itemEl.className = "upload-files-item";

      const nameEl = document.createElement("span");
      nameEl.className = "upload-files-name";
      nameEl.textContent = file.name;

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "danger upload-files-remove";
      removeBtn.textContent = removeText;
      removeBtn.addEventListener("click", () => {
        const targetKey = fileKey(file);
        selectedFiles = selectedFiles.filter((selectedFile) => fileKey(selectedFile) !== targetKey);
        syncUploadInputFiles();
        renderUploadFiles();
      });

      itemEl.appendChild(nameEl);
      itemEl.appendChild(removeBtn);
      listEl.appendChild(itemEl);
    });
    uploadFilesList.appendChild(listEl);
    uploadFilesList.style.display = "block";
    onFilesChange?.([...selectedFiles]);
  };

  uploadFilesToggle.addEventListener("click", () => {
    filesExpanded = !filesExpanded;
    renderUploadFiles();
  });

  uploadInput.addEventListener("change", () => {
    const nextFiles = Array.from(uploadInput.files || []);
    const seen = new Set(selectedFiles.map((file) => fileKey(file)));
    nextFiles.forEach((file) => {
      const key = fileKey(file);
      if (seen.has(key)) return;
      selectedFiles.push(file);
      seen.add(key);
    });
    syncUploadInputFiles();
    renderUploadFiles();
  });

  renderUploadFiles();
}
