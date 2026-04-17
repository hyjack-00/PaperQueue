document.addEventListener("DOMContentLoaded", () => {
  const notebookSelect = document.getElementById("notebook_id");
  const notebookTitleInput = document.getElementById("notebook_title");
  const notebookError = document.getElementById("notebook_error");
  const manualNotebookToggle = document.getElementById("manual_notebook");
  const manualNotebookFields = document.getElementById("manual_notebook_fields");
  const jobsTable = document.querySelector("[data-jobs-table]");
  const jobsBody = jobsTable?.querySelector("tbody");
  const statusCard = document.querySelector("[data-system-status]");
  const notebookCacheKey = "paper-queue:notebooks";
  const expandedJobs = new Set();
  let currentJobs = [];

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

  const shortDate = (value) => (value ? String(value).slice(0, 10) : "-");
  const displayTitle = (job) => job.display_title || job.paper_title || job.input_text || "-";
  const displayNotebook = (job) => job.display_notebook || job.notebook_title || "Auto route";

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
    notebookSelect.disabled = !manualNotebookToggle?.checked || notebooks.length === 0;
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

  const setNotebookOverride = (enabled) => {
    if (!manualNotebookFields || !notebookSelect || !notebookTitleInput) return;
    manualNotebookFields.hidden = !enabled;
    notebookSelect.disabled = !enabled;
    if (!enabled) {
      notebookSelect.value = "";
      notebookTitleInput.value = "";
      if (notebookError) {
        notebookError.hidden = true;
      }
    } else {
      syncNotebookTitle();
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
        notebookSelect.innerHTML = '<option value="">Notebook load failed</option>';
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

  const renderExpandable = (job) => {
    const logs = (job.recent_logs || []).map((log) =>
      `<div class="recent-log">${escapeHtml(shortDate(log.created_at))} [${escapeHtml(log.level)}] ${escapeHtml(log.message)}</div>`
    ).join("");
    return `
      <tr class="expand-row" data-expand-row="${job.id}" ${expandedJobs.has(job.id) ? "" : "hidden"}>
        <td colspan="5">
          <div class="expand-box">
            <div><strong>Stage:</strong> ${escapeHtml(job.stage || "-")}</div>
            ${job.error_message ? `<div><strong>Error:</strong> ${escapeHtml(job.error_message)}</div>` : ""}
            ${job.latest_log ? `<div class="mini-log"><strong>Latest:</strong> ${escapeHtml(job.latest_log)}</div>` : ""}
            ${logs}
          </div>
        </td>
      </tr>
    `;
  };

  const renderJobRow = (job) => {
    const hasExpandable = (job.recent_logs || []).length > 0;
    return `
      <tr data-job-row data-job-id="${job.id}">
        <td class="paper-col">
          <a class="paper-link" href="/jobs/${job.id}">${escapeHtml(displayTitle(job))}</a>
        </td>
        <td class="date-col">${escapeHtml(shortDate(job.created_at))}</td>
        <td>
          ${hasExpandable
            ? `<button type="button" class="badge-button badge badge-${escapeHtml(job.status)}" data-toggle-job="${job.id}" aria-expanded="${expandedJobs.has(job.id)}">${escapeHtml(job.status)}</button>`
            : `<span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>`}
        </td>
        <td>${escapeHtml(displayNotebook(job))}</td>
        <td class="actions">
          <a class="button-link" href="/jobs/${job.id}">Details</a>
          ${job.status === "failed" ? `<button type="button" class="ghost-button" data-retry-job="${job.id}">Retry</button>` : ""}
          <button type="button" class="ghost-button danger-button" data-delete-job="${job.id}">Delete</button>
        </td>
      </tr>
      ${hasExpandable ? renderExpandable(job) : ""}
    `;
  };

  const renderJobs = (jobs) => {
    if (!jobsBody) return;
    currentJobs = jobs;
    if (jobs.length === 0) {
      jobsBody.innerHTML = '<tr><td colspan="5" class="empty-row">No jobs yet.</td></tr>';
      return;
    }
    jobsBody.innerHTML = jobs.map(renderJobRow).join("");
  };

  const setStatusField = (field, value, kind = "") => {
    const node = statusCard?.querySelector(`[data-status-field="${field}"]`);
    if (!node) return;
    node.textContent = value;
    node.classList.remove("ok", "bad");
    if (kind) {
      node.classList.add(kind);
    }
  };

  const refreshStatus = async () => {
    if (!statusCard) return;
    try {
      const response = await fetch("/api/system-status");
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "status unavailable");
      }
      setStatusField("claude", payload.claude_ok ? "ready" : "missing", payload.claude_ok ? "ok" : "bad");
      setStatusField("auth", payload.auth_message || "unknown", payload.auth_ok ? "ok" : "bad");
      setStatusField("skill", payload.skill_ok ? "installed" : "missing", payload.skill_ok ? "ok" : "bad");
      setStatusField("git_remote", payload.git_remote_message || "unknown", payload.git_remote_ok ? "ok" : "bad");
      setStatusField("git_repo", payload.git_repo_path || "-", payload.git_repo_ok ? "ok" : "bad");
      const workerLabel = payload.active_job_id ? `busy (#${payload.active_job_id})` : `idle · queued ${payload.queue_depth}`;
      setStatusField("worker", workerLabel, payload.active_job_id ? "bad" : "ok");
    } catch {
      setStatusField("claude", "unavailable", "bad");
      setStatusField("auth", "unavailable", "bad");
      setStatusField("skill", "unavailable", "bad");
      setStatusField("git_remote", "unavailable", "bad");
      setStatusField("git_repo", "unavailable", "bad");
      setStatusField("worker", "unavailable", "bad");
    }
  };

  const refreshJobs = async () => {
    if (!jobsBody) return;
    const response = await fetch("/api/jobs");
    if (!response.ok) return;
    const payload = await response.json();
    renderJobs(payload.jobs || []);
  };

  const postAction = async (url, message) => {
    const response = await fetch(url, { method: "POST" });
    if (!response.ok) {
      return;
    }
    if (message) {
      console.info(message);
    }
    await refreshJobs();
    await refreshStatus();
  };

  if (notebookSelect && notebookTitleInput) {
    notebookSelect.addEventListener("change", syncNotebookTitle);
    manualNotebookToggle?.addEventListener("change", () => {
      const enabled = Boolean(manualNotebookToggle.checked);
      setNotebookOverride(enabled);
      if (enabled && notebookSelect.options.length <= 1) {
        loadNotebooks().catch(() => {
          if (notebookError) {
            notebookError.hidden = false;
            notebookError.textContent = "Failed to load notebooks";
          }
        });
      }
    });
    setNotebookOverride(Boolean(manualNotebookToggle?.checked));
    loadNotebooks().catch(() => {
      if (notebookError) {
        notebookError.hidden = false;
        notebookError.textContent = "Failed to load notebooks";
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const toggleButton = event.target.closest("[data-toggle-job]");
    if (toggleButton) {
      const jobId = Number(toggleButton.getAttribute("data-toggle-job"));
      if (expandedJobs.has(jobId)) {
        expandedJobs.delete(jobId);
      } else {
        expandedJobs.add(jobId);
      }
      renderJobs(currentJobs);
      return;
    }

    const retryButton = event.target.closest("[data-retry-job]");
    if (retryButton) {
      await postAction(`/api/jobs/${retryButton.getAttribute("data-retry-job")}/retry`);
      return;
    }

    const deleteButton = event.target.closest("[data-delete-job]");
    if (deleteButton) {
      const ok = window.confirm("Delete this queue entry?");
      if (!ok) return;
      await postAction(`/api/jobs/${deleteButton.getAttribute("data-delete-job")}/delete`);
    }
  });

  document.querySelectorAll("[data-retry-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await postAction(form.action);
    });
  });

  refreshStatus().catch(() => {});
  if (jobsBody) {
    refreshJobs().catch(() => {});
    window.setInterval(() => {
      refreshJobs().catch(() => {});
    }, 10000);
    window.setInterval(() => {
      refreshStatus().catch(() => {});
    }, 30000);
  }
});
