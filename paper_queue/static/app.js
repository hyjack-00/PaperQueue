document.addEventListener("DOMContentLoaded", () => {
  const notebookSelect = document.getElementById("notebook_id");
  const notebookTitleInput = document.getElementById("notebook_title");
  const notebookError = document.getElementById("notebook_error");
  const manualNotebookToggle = document.getElementById("manual_notebook");
  const manualNotebookFields = document.getElementById("manual_notebook_fields");
  const jobsTable = document.querySelector("[data-jobs-table]");
  const jobsBody = jobsTable?.querySelector("tbody");
  const statusCard = document.querySelector("[data-system-status]");
  const submitForm = document.querySelector("[data-submit-form]");
  const submitButton = document.querySelector("[data-submit-button]");
  const submitFeedback = document.querySelector("[data-submit-feedback]");
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
  const displayTopic = (job) => job.display_topic || job.notebook_title || "Auto route";
  const displayVersion = (job) => job.display_version || job.framework_version || "-";

  const iconSvg = {
    info: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5c5.5 0 9.5 5.5 9.5 7s-4 7-9.5 7S2.5 13.5 2.5 12 6.5 5 12 5Zm0 2C8.1 7 5 10.8 4.2 12 5 13.2 8.1 17 12 17s7-3.8 7.8-5C19 10.8 15.9 7 12 7Zm0 2.5A2.5 2.5 0 1 1 9.5 12 2.5 2.5 0 0 1 12 9.5Z"/></svg>',
    retry: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5a7 7 0 1 1-6.7 9h2.1A5 5 0 1 0 9 8.8V12H4V7h2.2l1.5 1.5A6.9 6.9 0 0 1 12 5Z"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v8h-2V9Zm4 0h2v8h-2V9ZM7 9h2v8H7V9Zm-1 11h12a2 2 0 0 0 2-2V8H4v10a2 2 0 0 0 2 2Z"/></svg>',
  };

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
        <td class="version-col">${escapeHtml(displayVersion(job))}</td>
        <td>
          ${hasExpandable
            ? `<button type="button" class="badge-button badge badge-${escapeHtml(job.status)}" data-toggle-job="${job.id}" aria-expanded="${expandedJobs.has(job.id)}">${escapeHtml(job.status)}</button>`
            : `<span class="badge badge-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>`}
        </td>
        <td>${escapeHtml(displayTopic(job))}</td>
        <td class="actions">
          <a class="icon-button" href="/jobs/${job.id}" aria-label="View details" title="View details">${iconSvg.info}</a>
          ${(job.status === "failed" || (job.status === "completed" && !job.is_latest_version))
            ? `<button type="button" class="icon-button" data-retry-job="${job.id}" aria-label="Retry" title="Retry">${iconSvg.retry}</button>`
            : ""}
          <button type="button" class="icon-button danger-button" data-delete-job="${job.id}" aria-label="Delete" title="Delete">${iconSvg.delete}</button>
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

  const pushSubmittingRow = (inputText) => {
    const tempId = `temp-${Date.now()}`;
    const job = {
      id: tempId,
      status: "submitting",
      input_text: inputText,
      display_title: inputText,
      display_topic: "Auto route",
      display_version: "pending",
      recent_logs: [],
      is_latest_version: false,
    };
    currentJobs = [job, ...currentJobs];
    renderJobs(currentJobs);
    return tempId;
  };

  const replaceSubmittingRow = (tempId, realJobs) => {
    currentJobs = currentJobs.filter((job) => String(job.id) !== String(tempId));
    if (realJobs) {
      currentJobs = realJobs;
    }
    renderJobs(currentJobs);
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

  submitForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(submitForm);
    const inputText = String(formData.get("input") || "").trim();
    if (!inputText) {
      return;
    }
    submitButton?.setAttribute("disabled", "disabled");
    if (submitFeedback) {
      submitFeedback.hidden = false;
      submitFeedback.textContent = "Submitting...";
    }
    const tempId = pushSubmittingRow(inputText);
    try {
      const response = await fetch("/submit", {
        method: "POST",
        body: formData,
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "submit failed");
      }
      submitForm.reset();
      setNotebookOverride(Boolean(manualNotebookToggle?.checked));
      await refreshJobs();
      await refreshStatus();
      replaceSubmittingRow(tempId, currentJobs);
      if (submitFeedback) {
        submitFeedback.textContent = `Queued as #${payload.job_id}`;
      }
    } catch (error) {
      replaceSubmittingRow(tempId, currentJobs.filter((job) => String(job.id) !== String(tempId)));
      if (submitFeedback) {
        submitFeedback.textContent = error instanceof Error ? error.message : "submit failed";
      }
    } finally {
      submitButton?.removeAttribute("disabled");
    }
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
