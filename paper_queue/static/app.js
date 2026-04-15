document.addEventListener("DOMContentLoaded", () => {
  const notebookSelect = document.getElementById("notebook_id");
  const notebookTitleInput = document.getElementById("notebook_title");
  const notebookError = document.getElementById("notebook_error");
  const notebookCacheKey = "paper-queue:notebooks";

  const syncNotebookTitle = () => {
    if (!notebookSelect || !notebookTitleInput) return;
    const option = notebookSelect.selectedOptions[0];
    notebookTitleInput.value = option?.dataset.title || option?.textContent || "";
  };

  const renderNotebooks = (notebooks) => {
    if (!notebookSelect) return;
    notebookSelect.innerHTML = "";
    for (const notebook of notebooks) {
      const option = document.createElement("option");
      option.value = notebook.id;
      option.dataset.title = notebook.title;
      option.textContent = notebook.title;
      notebookSelect.appendChild(option);
    }
    notebookSelect.disabled = notebooks.length === 0;
    syncNotebookTitle();
  };

  const readCachedNotebooks = () => {
    try {
      return JSON.parse(window.localStorage.getItem(notebookCacheKey) || "[]");
    } catch {
      return [];
    }
  };

  const writeCachedNotebooks = (notebooks) => {
    try {
      window.localStorage.setItem(notebookCacheKey, JSON.stringify(notebooks));
    } catch {
      // ignore storage errors
    }
  };

  const loadNotebooks = async () => {
    if (!notebookSelect) return;
    const cached = readCachedNotebooks();
    if (cached.length > 0) {
      renderNotebooks(cached);
    }

    const response = await fetch("/api/notebooks");
    const payload = await response.json();

    if (!response.ok) {
      if (cached.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Notebook load failed";
        notebookSelect.innerHTML = "";
        notebookSelect.appendChild(option);
        notebookSelect.disabled = true;
      }
      if (notebookError) {
        notebookError.hidden = false;
        notebookError.textContent = cached.length > 0
          ? `Notebook refresh failed, using cache: ${payload.error || "unknown error"}`
          : (payload.error || "Failed to load notebooks");
      }
      return;
    }

    if (notebookError) {
      notebookError.hidden = true;
    }
    writeCachedNotebooks(payload.notebooks);
    renderNotebooks(payload.notebooks);
  };

  if (notebookSelect && notebookTitleInput) {
    notebookSelect.addEventListener("change", syncNotebookTitle);
    loadNotebooks().catch(() => {
      if (notebookError) {
        notebookError.hidden = false;
        notebookError.textContent = "Failed to load notebooks";
      }
    });
  }

  document.querySelectorAll("[data-retry-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const response = await fetch(form.action, { method: "POST" });
      if (response.ok) {
        window.location.reload();
      }
    });
  });

  if (document.querySelector("[data-jobs-table]")) {
    window.setInterval(async () => {
      const response = await fetch("/api/jobs");
      if (!response.ok) return;
      window.location.reload();
    }, 10000);
  }
});
