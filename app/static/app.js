const state = {
  jobs: [],
  currentJob: null,
  pollTimer: null,
};

const els = {
  dropzone: document.querySelector("#dropzone"),
  fileInput: document.querySelector("#fileInput"),
  titleInput: document.querySelector("#titleInput"),
  languageInput: document.querySelector("#languageInput"),
  speakerInput: document.querySelector("#speakerInput"),
  uploadButton: document.querySelector("#uploadButton"),
  progressBar: document.querySelector("#progressBar"),
  progressLabel: document.querySelector("#progressLabel"),
  refreshButton: document.querySelector("#refreshButton"),
  jobList: document.querySelector("#jobList"),
  currentTitle: document.querySelector("#currentTitle"),
  txtDownload: document.querySelector("#txtDownload"),
  srtDownload: document.querySelector("#srtDownload"),
  video: document.querySelector("#video"),
  videoPanel: document.querySelector(".video-panel"),
  transcript: document.querySelector("#transcript"),
  searchInput: document.querySelector("#searchInput"),
  clearSearch: document.querySelector("#clearSearch"),
};

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function clock(seconds) {
  const whole = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function setProgress(percent, text) {
  els.progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  els.progressLabel.textContent = text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || "No se pudo completar la accion.");
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function refreshJobs() {
  const { jobs } = await api("/api/jobs");
  state.jobs = jobs;
  renderJobs();
  const active = jobs.find((job) => job.id === state.currentJob?.id);
  if (active) {
    showJob(active, false);
  } else if (!state.currentJob && jobs.length) {
    showJob(jobs[0]);
  }
}

function renderJobs() {
  els.jobList.innerHTML = "";
  if (!state.jobs.length) {
    els.jobList.innerHTML = '<div class="empty-copy">Todavia no hay transcripciones.</div>';
    return;
  }
  for (const job of state.jobs) {
    const button = document.createElement("button");
    button.className = `job ${state.currentJob?.id === job.id ? "is-active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <strong>${escapeHtml(job.title)}</strong>
      <small>${escapeHtml(job.originalFilename)} · ${formatBytes(job.sizeBytes)}</small>
      <span class="status ${job.status}">${statusLabel(job.status)}</span>
    `;
    button.addEventListener("click", () => showJob(job));
    els.jobList.append(button);
  }
}

function statusLabel(status) {
  return {
    waiting_upload: "Esperando subida",
    queued: "En cola",
    processing: "Procesando",
    completed: "Listo",
    failed: "Error",
  }[status] || status;
}

async function showJob(job, loadMedia = true) {
  state.currentJob = job;
  els.currentTitle.textContent = job.title;
  els.txtDownload.href = `/api/jobs/${job.id}/download.txt`;
  els.srtDownload.href = `/api/jobs/${job.id}/download.srt`;
  els.txtDownload.classList.toggle("disabled", job.status !== "completed");
  els.srtDownload.classList.toggle("disabled", job.status !== "completed");
  renderJobs();
  renderTranscript(job.segments || []);
  if (job.status === "completed" && loadMedia) {
    await loadMediaUrl(job.id);
  } else if (job.status !== "completed") {
    els.video.removeAttribute("src");
    els.videoPanel.classList.remove("has-video");
    if (job.failureReason) {
      els.transcript.innerHTML = `<div class="empty-copy">${escapeHtml(job.failureReason)}</div>`;
    }
  }
}

async function loadMediaUrl(jobId) {
  const { url } = await api(`/api/jobs/${jobId}/media-url`);
  els.video.src = url;
  els.videoPanel.classList.add("has-video");
}

function renderTranscript(segments) {
  els.transcript.innerHTML = "";
  if (!segments.length) {
    els.transcript.innerHTML = '<div class="empty-copy">La transcripcion va a aparecer aca.</div>';
    return;
  }
  const query = normalize(els.searchInput.value);
  for (const segment of segments) {
    const node = document.createElement("article");
    const isMatch = query && normalize(segment.text).includes(query);
    node.className = `segment ${isMatch ? "is-match" : ""}`;
    node.dataset.start = String(segment.start || 0);
    node.dataset.end = String(segment.end || segment.start || 0);
    node.innerHTML = `<time>${clock(segment.start)}</time><p>${escapeHtml(segment.text)}</p>`;
    node.addEventListener("click", () => {
      els.video.currentTime = Number(node.dataset.start);
      els.video.play().catch(() => {});
    });
    els.transcript.append(node);
  }
  syncTranscript();
}

function syncTranscript() {
  const current = els.video.currentTime || 0;
  let active = null;
  for (const node of els.transcript.querySelectorAll(".segment")) {
    const start = Number(node.dataset.start);
    const end = Number(node.dataset.end);
    const inside = current >= start && current < Math.max(end, start + 0.5);
    node.classList.toggle("is-active", inside);
    if (inside) active = node;
  }
  if (active) {
    active.scrollIntoView({ block: "nearest" });
  }
}

async function pollJob(jobId, retries = 0) {
  clearTimeout(state.pollTimer);
  try {
    const { job } = await api(`/api/jobs/${jobId}`);
    const index = state.jobs.findIndex((item) => item.id === job.id);
    if (index >= 0) state.jobs[index] = job;
    if (state.currentJob?.id === job.id) showJob(job, job.status === "completed");
    renderJobs();
    if (job.status === "processing" || job.status === "queued") {
      setProgress(100, "Amazon Transcribe esta procesando el archivo.");
      state.pollTimer = setTimeout(() => pollJob(jobId), 5000);
    } else if (job.status === "completed") {
      setProgress(100, "Transcripcion terminada.");
    } else if (job.status === "failed") {
      setProgress(0, job.failureReason || "El trabajo fallo.");
    }
  } catch (error) {
    if (error.status === 502 && retries < 3) {
      setProgress(100, "No se pudo consultar el estado. Volviendo a intentar…");
      state.pollTimer = setTimeout(() => pollJob(jobId, retries + 1), 5000);
      return;
    }
    setProgress(0, error.message);
  }
}

async function uploadSelectedFile() {
  const file = els.fileInput.files?.[0];
  if (!file) {
    setProgress(0, "Elegi un archivo primero.");
    return;
  }
  els.uploadButton.disabled = true;
  try {
    setProgress(2, "Preparando subida segura...");
    const sign = await api("/api/uploads/sign", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        title: els.titleInput.value,
        language_code: els.languageInput.value,
        identify_language: els.languageInput.value === "auto",
        speaker_labels: els.speakerInput.checked,
      }),
    });
    state.jobs.unshift(sign.job);
    showJob(sign.job, false);
    await putFile(sign.uploadUrl, file, sign.uploadHeaders || {});
    setProgress(96, "Iniciando Amazon Transcribe...");
    const { job } = await api(`/api/jobs/${sign.job.id}/start`, {
      method: "POST",
      body: JSON.stringify({ uploaded: true }),
    });
    showJob(job, false);
    pollJob(job.id);
  } catch (error) {
    setProgress(0, error.message);
  } finally {
    els.uploadButton.disabled = false;
  }
}

function putFile(url, file, headers) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [key, value] of Object.entries(headers)) {
      xhr.setRequestHeader(key, value);
    }
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 92);
        setProgress(percent, `Subiendo a AWS: ${percent}%`);
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`S3 rechazo la subida (${xhr.status}). Revisá CORS y permisos.`));
    });
    xhr.addEventListener("error", () => reject(new Error("No se pudo subir a S3.")));
    xhr.send(file);
  });
}

function normalize(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

els.fileInput.addEventListener("change", () => {
  const file = els.fileInput.files?.[0];
  if (file && !els.titleInput.value) {
    els.titleInput.value = file.name.replace(/\.[^.]+$/, "");
  }
});
els.uploadButton.addEventListener("click", uploadSelectedFile);
els.refreshButton.addEventListener("click", refreshJobs);
els.video.addEventListener("timeupdate", syncTranscript);
els.searchInput.addEventListener("input", () => renderTranscript(state.currentJob?.segments || []));
els.clearSearch.addEventListener("click", () => {
  els.searchInput.value = "";
  renderTranscript(state.currentJob?.segments || []);
});

for (const eventName of ["dragenter", "dragover"]) {
  els.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropzone.classList.add("is-dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  els.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.dropzone.classList.remove("is-dragging");
  });
}
els.dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  els.fileInput.files = transfer.files;
  els.fileInput.dispatchEvent(new Event("change"));
});

refreshJobs().catch((error) => setProgress(0, error.message));

