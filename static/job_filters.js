(function () {
  function normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function statusGroup(item) {
    const status = normalize(item?.job_status || item?.status_code || item?.status);
    if (["queued", "running", "cancel_requested", "uploaded", "ocr", "translate", "render", "structure", "html", "docx"].includes(status)) {
      return "active";
    }
    if (["completed", "done", "saved"].includes(status)) return "completed";
    if (status === "failed") return "failed";
    if (["cancelled", "canceled"].includes(status)) return "cancelled";
    if (status === "draft") return "draft";
    return status || "unknown";
  }

  function itemText(item, fields) {
    return fields.map((field) => normalize(item?.[field])).join(" ");
  }

  function apply(items, options) {
    const query = normalize(options.query);
    const status = normalize(options.status || "all");
    const mode = normalize(options.mode || "all");
    const fields = options.fields || ["job_name", "job_id", "creator_name", "owner_work_id", "status_label"];
    return (items || []).filter((item) => {
      if (query && !itemText(item, fields).includes(query)) return false;
      if (status !== "all" && statusGroup(item) !== status) return false;
      if (mode !== "all" && normalize(item?.document_mode || item?.job_type) !== mode) return false;
      return true;
    });
  }

  function bind(config) {
    const search = document.getElementById(config.searchId);
    const status = document.getElementById(config.statusId);
    const mode = config.modeId ? document.getElementById(config.modeId) : null;
    const reset = config.resetId ? document.getElementById(config.resetId) : null;

    const emit = () => config.onChange?.();
    search?.addEventListener("input", emit);
    status?.addEventListener("change", emit);
    mode?.addEventListener("change", emit);
    reset?.addEventListener("click", () => {
      if (search) search.value = "";
      if (status) status.value = "all";
      if (mode) mode.value = "all";
      emit();
    });
  }

  window.JobFilters = { apply, bind };
})();
