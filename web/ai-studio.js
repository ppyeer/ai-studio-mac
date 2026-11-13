// AI Studio 独立页：出片相关的全部界面代码。
const app = document.querySelector("#app");
const TOOLBOX_STANDALONE_TITLES = { ai_studio: "AI Studio" };
const AI_STUDIO_COMPOSE_COLLAPSED_KEY = "aiStudioComposeCollapsed";
const AI_STUDIO_PROMPT_LANG_KEY = "aiStudioPromptLang";
const AI_STUDIO_COMPOSE_WIDTH_KEY = "aiStudioComposeWidth";
const AI_STUDIO_THUMBS_KEY = "aiStudioThumbView";
const AI_STUDIO_COMPOSE_DEFAULT_WIDTH = 440;
const AI_STUDIO_COMPOSE_MIN_WIDTH = 320;
const AI_STUDIO_COMPOSE_MAX_WIDTH = 760;
const AI_STUDIO_COMPOSE_COLLAPSE_WIDTH = 240;
const TOOLBOX_SHORT_PATHS = { "/ai-studio": "ai_studio", "/comfyui": "comfyui" };
const toolboxShortPath = (view) => Object.keys(TOOLBOX_SHORT_PATHS).find((path) => TOOLBOX_SHORT_PATHS[path] === view) || "";
const toolboxShortPathView = () => TOOLBOX_SHORT_PATHS[`/${window.location.pathname.split("/")[1] || ""}`] || "";
// /ai-studio/<系列>/<分组>?view=works：进到哪个系列、分组，网址就带上对应的 id
function aiStudioNavFromUrl() {
  if (toolboxShortPathView() !== "ai_studio") return { series: "", group: "" };
  const [series = "", group = ""] = window.location.pathname.split("/").slice(2).map((part) => decodeURIComponent(part));
  return {
    series: series === "unfiled" ? "__none__" : series,
    group: series ? group : "",
    view: series && new URLSearchParams(window.location.search).get("view") === "works" ? "works" : "",
  };
}
function aiStudioNavPath(nav = {}) {
  if (!nav.series) return "";
  const parts = [nav.series === "__none__" ? "unfiled" : nav.series, nav.group].filter(Boolean).map(encodeURIComponent);
  return `/${parts.join("/")}${nav.view === "works" ? "?view=works" : ""}`;
}

const model = {
  toolboxOpen: true,
  toolboxView: "ai_studio",
  toolboxStandalone: true,
  homeOpen: false,
  theme: localStorage.getItem("aiStudioTheme") === "day" ? "day" : "night",
  aiStudioConfig: null,
  aiStudioState: null,
  aiStudioLoading: false,
  aiStudioBusy: "",
  aiStudioError: "",
  aiStudioMessage: "",
  aiStudioFormError: "",
  aiStudioDraft: null,
  aiStudioDraftsByKind: {},
  aiStudioLint: null,
  aiStudioFilter: { kind: "", category: "", format: "", status: "" },
  aiStudioNav: aiStudioNavFromUrl(),
  aiStudioSeriesEditor: null,
  aiStudioComposeCollapsed: localStorage.getItem(AI_STUDIO_COMPOSE_COLLAPSED_KEY) === "1",
  aiStudioThumbs: localStorage.getItem(AI_STUDIO_THUMBS_KEY) === "1",
  aiStudioComposeWidth: clampAiStudioComposeWidth(Number(localStorage.getItem(AI_STUDIO_COMPOSE_WIDTH_KEY)) || AI_STUDIO_COMPOSE_DEFAULT_WIDTH),
};

function isToolboxStandalone() {
  return true;
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function workspaceNewsDate() {
  return "";
}

async function apiJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

function renderAiKnowledgeToggle() {
  return "";
}

function syncUrlState(mode = "replace") {
  const next = `/ai-studio${aiStudioNavPath(model.aiStudioNav)}${window.location.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  window.history[mode === "push" ? "pushState" : "replaceState"]({}, "", next);
}

function render(pushUrl = false) {
  document.documentElement.dataset.theme = model.theme;
  syncUrlState(pushUrl ? "push" : "replace");
  document.title = aiStudioDocumentTitle() || "AI Studio";
  app.innerHTML = `
    <div class="app-shell toolbox-standalone">
      <main class="main toolbox-page-main">
        <section class="memo-page toolbox-page toolbox-standalone-bare">
          <div class="toolbox-body">${renderToolboxAiStudioPanel()}</div>
        </section>
      </main>
    </div>`;
  bindToolboxAiStudioEvents();
  maybeLoadToolboxAiStudio();
}

function renderPreservingToolboxBodyPosition(focusSelector = "") {
  const body = document.querySelector(".toolbox-body");
  const scrollTop = body instanceof HTMLElement ? body.scrollTop : 0;
  render();
  const restore = () => {
    const next = document.querySelector(".toolbox-body");
    if (next instanceof HTMLElement) next.scrollTop = scrollTop;
  };
  restore();
  requestAnimationFrame(restore);
  setTimeout(restore, 80);
  if (focusSelector) {
    requestAnimationFrame(() => {
      const control = document.querySelector(focusSelector);
      if (control instanceof HTMLElement) control.focus({ preventScroll: true });
    });
  }
}

const AI_STUDIO_ACTIVE = new Set(["queued", "submitted", "running", "finishing"]);
const AI_STUDIO_MAX_REFS = 4;
let aiStudioPollTimer = 0;
let aiStudioGallerySignature = "";

function aiStudioIsActive() {
  return model.toolboxOpen && model.toolboxView === "ai_studio";
}

function aiStudioCategory(id) {
  return (model.aiStudioConfig?.categories || []).find((item) => item.id === id) || null;
}

function aiStudioPromptLang(value) {
  if (value === "zh" || value === "en") return value;
  try {
    return localStorage.getItem(AI_STUDIO_PROMPT_LANG_KEY) === "zh" ? "zh" : "en";
  } catch {
    return "en";
  }
}

function aiStudioDraftFromCategory(categoryId, previous = {}) {
  const category = aiStudioCategory(categoryId) || {};
  const kind = category.kind || "video";
  const sameKind = (previous.kind || "video") === kind;
  const lang = aiStudioPromptLang(previous.lang);
  const sectionTemplates = (lang === "zh" && category.sections_zh) || category.sections;
  const sections = {};
  (model.aiStudioConfig?.sections || []).forEach(({ key }) => {
    sections[key] = sectionTemplates?.[key] || "";
  });
  const draft = {
    kind,
    title: previous.title || "",
    series: previous.series || "",
    group: previous.group || "",
    episode: previous.episode || "",
    shot: previous.shot || 0,
    category: category.id || "free",
    style: category.style || "free",
    mode: category.mode || (kind === "image" ? "t2i" : "t2v"),
    format: category.format || "portrait",
    quality: sameKind && previous.quality ? previous.quality : kind === "image" ? "4mp" : "preview",
    seconds: previous.seconds || 5,
    seed: "",
    lang,
    sections,
    free_text: (lang === "zh" && category.prompt_zh) || category.prompt || "",
    first_image: previous.first_image || "",
    last_image: previous.last_image || "",
    fast: Boolean(previous.fast),
    dirty: false,
  };
  for (let index = 1; index <= AI_STUDIO_MAX_REFS; index += 1) draft[`ref${index}_image`] = previous[`ref${index}_image`] || "";
  return aiStudioWithOrigin(draft);
}

// 「复原」回到的提示词：新建时是模板，从镜头或历史任务载入时是载入的那份
function aiStudioWithOrigin(draft) {
  return { ...draft, origin: { style: draft.style, lang: draft.lang, sections: { ...(draft.sections || {}) }, free_text: draft.free_text || "", dirty: Boolean(draft.dirty) } };
}

function aiStudioSwitchKind(kind) {
  const current = model.aiStudioDraft || {};
  if ((current.kind || "video") === kind) return;
  model.aiStudioDraftsByKind = { ...(model.aiStudioDraftsByKind || {}), [current.kind || "video"]: current };
  const saved = model.aiStudioDraftsByKind[kind];
  const firstCategory = (model.aiStudioConfig?.categories || []).find((item) => item.kind === kind);
  model.aiStudioDraft = saved
    ? { ...saved, series: current.series || "", group: current.group || "" }
    : aiStudioDraftFromCategory(firstCategory?.id || "free", { title: "", series: current.series, group: current.group });
  model.aiStudioLint = null;
  model.aiStudioFormError = "";
}

async function loadAiStudio({ quiet = false } = {}) {
  if (model.aiStudioLoading) return;
  model.aiStudioLoading = true;
  if (!quiet) {
    model.aiStudioError = "";
    if (aiStudioIsActive()) render();
  }
  try {
    const payload = await apiJson("/api/tools/ai-studio", { cache: "no-store" });
    if (payload.config) model.aiStudioConfig = payload.config;
    model.aiStudioState = payload;
    if (!model.aiStudioDraft && model.aiStudioConfig) model.aiStudioDraft = aiStudioDraftFromCategory("free");
  } catch (error) {
    model.aiStudioError = error.message || "无法读取 AI Studio 状态";
  } finally {
    model.aiStudioLoading = false;
    scheduleAiStudioPoll();
    if (!aiStudioIsActive()) return;
    if (quiet && document.querySelector("[data-ai-studio-panel]")) refreshAiStudioLibraryDom();
    else renderPreservingToolboxBodyPosition();
  }
}

function scheduleAiStudioPoll() {
  clearTimeout(aiStudioPollTimer);
  const busy = (model.aiStudioState?.jobs || []).some((job) => AI_STUDIO_ACTIVE.has(job.status))
    || (model.aiStudioState?.voices || []).some((voice) => voice.status === "queued" || voice.status === "running");
  aiStudioPollTimer = setTimeout(() => {
    if (aiStudioIsActive()) loadAiStudio({ quiet: true });
  }, busy ? 5000 : 30000);
}

function maybeLoadToolboxAiStudio() {
  if (!aiStudioIsActive()) return;
  if (!model.aiStudioLoading && !model.aiStudioState && !model.aiStudioError) loadAiStudio();
}

function aiStudioMediaUrl(job, kind) {
  return `/api/tools/ai-studio/media/${encodeURIComponent(job.id)}/${kind}`;
}

function aiStudioDuration(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  return value >= 60 ? `${Math.floor(value / 60)} 分 ${value % 60} 秒` : `${value} 秒`;
}

function aiStudioJobMeta(job) {
  const config = model.aiStudioConfig || {};
  const image = job.kind === "image";
  return [
    config.formats?.[job.format]?.label,
    `${job.width}×${job.height}`,
    image ? "" : `${job.seconds} 秒`,
    image ? config.image_modes?.[job.mode] : config.modes?.[job.mode],
    `seed ${job.seed}`,
    job.fast ? "快速" : "",
  ].filter(Boolean).join(" · ");
}

function renderAiStudioActiveJobs() {
  const jobs = (model.aiStudioState?.jobs || []).filter((job) => AI_STUDIO_ACTIVE.has(job.status));
  if (!jobs.length) return "";
  return `
    <div class="ai-studio-active">
      <h4>进行中 · ${jobs.length}</h4>
      ${jobs.map((job) => {
        const progress = job.progress && job.status === "running" ? job.progress : null;
        const percent = progress ? Math.round((progress.step / Math.max(1, progress.total)) * 100) : job.status === "finishing" ? 100 : 0;
        return `
          <article class="ai-studio-active-job" data-ai-studio-active-job="${escapeHtml(job.id)}">
            <div class="ai-studio-active-head">
              <strong>${escapeHtml(job.title)}</strong>
              <span class="ai-studio-status ${escapeHtml(job.status)}">${escapeHtml(job.status_label)}${progress ? ` · 第 ${progress.step}/${progress.total} 步` : ""}${job.elapsed ? ` · 已用 ${escapeHtml(aiStudioDuration(job.elapsed))}` : ""}</span>
            </div>
            <div class="ai-studio-progress" aria-hidden="true"><span style="width:${percent}%"></span></div>
            <div class="ai-studio-active-foot">
              <small>${escapeHtml([aiStudioPlacementLabel(job), aiStudioCategory(job.category)?.label].filter(Boolean).join(" · "))} · ${escapeHtml(aiStudioJobMeta(job))}</small>
              <span class="ai-studio-active-actions">
                <a class="ai-studio-comfyui-log-link" href="/api/tools/ai-studio/comfy-log" target="_blank" rel="noopener" data-ai-studio-comfyui-log title="查看 ComfyUI 运行日志" aria-label="查看 ComfyUI 运行日志"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 9l3 3-3 3M12.5 15H17"/></svg></a>
                ${job.status === "finishing" ? `<small>${job.kind === "image" ? "生成完毕，正在整理…" : "生成完毕，正在整理与质检…"}</small>` : `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-cancel="${escapeHtml(job.id)}">取消</button>`}
              </span>
            </div>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

// 工具箱里直接切到 ComfyUI 页并滚到日志最新处；独立页按链接在新标签打开 /comfyui
document.addEventListener("click", (event) => {
  const link = event.target.closest("[data-ai-studio-comfyui-log]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
  const tab = !isToolboxStandalone() && document.querySelector('[data-toolbox-view="comfyui"]');
  if (!tab) return;
  event.preventDefault();
  tab.click();
  let tries = 0;
  const reveal = () => {
    const log = document.querySelector("[data-comfyui-log]");
    if (log && model.comfyuiStatus) {
      log.scrollTop = log.scrollHeight;
      log.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else if (tries++ < 30) setTimeout(reveal, 200);
  };
  setTimeout(reveal, 100);
});

const AI_STUDIO_UNFILED = "__none__";

function aiStudioSeriesList() {
  return model.aiStudioState?.series || [];
}

function aiStudioSeriesById(id) {
  return aiStudioSeriesList().find((item) => item.id === id) || null;
}

function aiStudioPlacementLabel(job) {
  const series = aiStudioSeriesById(job.series);
  if (!series) return "";
  const group = (series.groups || []).find((item) => item.id === job.group);
  return group ? `${series.name} · ${group.name}` : series.name;
}

function renderAiStudioPlacementOptions(seriesId, groupId) {
  const option = (value, label, selected) => `<option value="${escapeHtml(value)}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  return [
    option("", "未归入系列", !seriesId),
    ...aiStudioSeriesList().map((series) => `<optgroup label="${escapeHtml(series.name)}">
      ${option(`${series.id}|`, `${series.name}（不分组）`, seriesId === series.id && !groupId)}
      ${(series.groups || []).map((group) => option(`${series.id}|${group.id}`, `${series.name} · ${group.name}`, seriesId === series.id && groupId === group.id)).join("")}
    </optgroup>`),
  ].join("");
}

function aiStudioFinishedJobs() {
  return (model.aiStudioState?.jobs || []).filter((job) => !AI_STUDIO_ACTIVE.has(job.status));
}

function aiStudioFolderJobs() {
  const nav = model.aiStudioNav || {};
  return aiStudioFinishedJobs().filter((job) => nav.series === AI_STUDIO_UNFILED
    ? !aiStudioSeriesById(job.series)
    : job.series === nav.series && (!nav.group || (nav.group === AI_STUDIO_UNFILED ? !job.group : job.group === nav.group)));
}

function aiStudioFilteredJobs(scope) {
  const filter = model.aiStudioFilter || {};
  return scope.filter((job) => (!filter.kind || (job.kind || "video") === filter.kind)
    && (!filter.category || job.category === filter.category)
    && (!filter.format || job.format === filter.format)
    && (!filter.status || job.status === filter.status));
}

function renderAiStudioZoomableVideo(job, className = "") {
  const poster = job.has?.thumb ? aiStudioMediaUrl(job, "thumb") : "";
  const src = aiStudioMediaUrl(job, "video");
  return `
    <div class="ai-studio-zoomable">
      <video${className ? ` class="${className}"` : ""} controls preload="none" playsinline ${poster ? `poster="${escapeHtml(poster)}"` : ""} src="${escapeHtml(src)}"></video>
      <button class="ai-studio-zoom-btn" type="button" data-ai-studio-zoom-video="${escapeHtml(src)}" data-poster="${escapeHtml(poster)}" data-title="${escapeHtml(job.title || "")}" title="放大查看（也可双击视频）" aria-label="放大查看「${escapeHtml(job.title || "视频")}」">⤢</button>
    </div>
  `;
}

function openAiStudioVideoViewer({ src, poster = "", title = "", currentTime = 0, image = false }) {
  document.querySelector(".ai-studio-viewer")?.remove();
  const viewer = document.createElement("div");
  viewer.className = "ai-studio-viewer";
  viewer.setAttribute("role", "dialog");
  viewer.setAttribute("aria-modal", "true");
  viewer.setAttribute("aria-label", title || (image ? "放大查看图片" : "放大查看视频"));
  viewer.innerHTML = `
    <div class="ai-studio-viewer-head">
      <strong>${escapeHtml(title)}</strong>
      <span class="ai-studio-viewer-actions">
        <a href="${escapeHtml(src)}" target="_blank" rel="noopener" title="新标签页打开原文件">新标签页打开</a>
        <button type="button" data-ai-studio-viewer-close title="关闭（Esc）" aria-label="关闭">×</button>
      </span>
    </div>
    ${image
      ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(title)}">`
      : `<video controls autoplay playsinline ${poster ? `poster="${escapeHtml(poster)}"` : ""} src="${escapeHtml(src)}"></video>`}
  `;
  const video = viewer.querySelector("video");
  if (video && currentTime > 0) video.addEventListener("loadedmetadata", () => { video.currentTime = currentTime; }, { once: true });
  const close = () => {
    video?.pause();
    viewer.remove();
    document.removeEventListener("keydown", onKey, true);
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };
  viewer.addEventListener("click", (event) => {
    if (event.target === viewer || event.target.closest("[data-ai-studio-viewer-close]")) close();
  });
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(viewer);
  viewer.querySelector("[data-ai-studio-viewer-close]").focus();
}

document.addEventListener("click", (event) => {
  if (event.metaKey || event.ctrlKey || event.shiftKey) return;
  const imageLink = event.target.closest("[data-ai-studio-zoom-image]");
  if (imageLink) {
    event.preventDefault();
    openAiStudioVideoViewer({ src: imageLink.dataset.aiStudioZoomImage || imageLink.getAttribute("href"), title: imageLink.dataset.title || "", image: true });
    return;
  }
  const button = event.target.closest("[data-ai-studio-zoom-video]");
  if (!button) return;
  event.preventDefault();
  const inline = button.parentElement?.querySelector("video");
  const currentTime = inline?.currentTime || 0;
  inline?.pause();
  openAiStudioVideoViewer({ src: button.dataset.aiStudioZoomVideo, poster: button.dataset.poster, title: button.dataset.title, currentTime });
});

document.addEventListener("dblclick", (event) => {
  const video = event.target.closest(".ai-studio-zoomable > video");
  if (!video) return;
  event.preventDefault();
  video.parentElement.querySelector("[data-ai-studio-zoom-video]")?.click();
});

function aiStudioCompactQcLine(line) {
  return String(line || "").trim()
    .replace(/\[((?:\(\d+(?:\.\d+)?,\s*\d+(?:\.\d+)?\)(?:,\s*)?)+)\]/g, (match, body) => {
      const spans = [...body.matchAll(/\((\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\)/g)].map((pair) => [Number(pair[1]), Number(pair[2])]);
      const merged = [];
      spans.forEach(([start, end]) => {
        const last = merged[merged.length - 1];
        if (last && start <= last[1]) last[1] = Math.max(last[1], end);
        else merged.push([start, end]);
      });
      return merged.map(([start, end]) => `${start}–${end} 秒`).join("、");
    })
    .replace(/（单位：秒；?/g, "（")
    .replace(/（）/g, "");
}

const aiStudioQcOpen = new Set();

function aiStudioCardQcParts(qc, qcClass, key) {
  const lines = (qc?.lines || []).slice(1).map((line) => line.trim()).filter(Boolean);
  const notes = lines.filter((line) => !line.includes(".qa.json"));
  if (!notes.length) return { toggle: "", body: "" };
  const detail = lines.find((line) => line.includes(".qa.json"));
  const summary = notes.map(aiStudioCompactQcLine);
  const open = aiStudioQcOpen.has(key);
  return {
    toggle: `<button class="ai-studio-qc-toggle" type="button" data-ai-studio-qc-toggle="${escapeHtml(key)}" aria-expanded="${open ? "true" : "false"}" title="${escapeHtml(summary.join("\n"))}">${open ? "收起" : "展开"}</button>`,
    body: `
      <div class="ai-studio-card-qc ${qcClass}${open ? " open" : ""}" data-ai-studio-qc-body="${escapeHtml(key)}">
        <div class="ai-studio-card-qc-full">
          ${notes.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
          ${detail ? `<p class="ai-studio-card-qc-path">${escapeHtml(detail.replace(/^明细\s*/, "明细："))}</p>` : ""}
        </div>
      </div>`,
  };
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-studio-qc-toggle]");
  if (!button) return;
  const key = button.dataset.aiStudioQcToggle;
  const open = !aiStudioQcOpen.has(key);
  if (open) aiStudioQcOpen.add(key);
  else aiStudioQcOpen.delete(key);
  button.textContent = open ? "收起" : "展开";
  button.setAttribute("aria-expanded", open ? "true" : "false");
  document.querySelectorAll(`[data-ai-studio-qc-body="${CSS.escape(key)}"]`).forEach((body) => body.classList.toggle("open", open));
});

const aiStudioTitleOpen = new Set();

// 中文对照：用本机模型把英文提示词逐段翻成中文，只供阅读，提交的仍是英文
function aiStudioZhRefKeys() {
  const draft = model.aiStudioDraft;
  if (!draft) return [];
  if (draft.kind === "image" || draft.style === "free") return ["free_text"];
  return (model.aiStudioConfig?.sections || []).map((item) => item.key);
}

function aiStudioZhRefSource(key) {
  const draft = model.aiStudioDraft || {};
  return String((key === "free_text" ? draft.free_text : draft.sections?.[key]) || "");
}

function aiStudioZhRefHtml(key) {
  const ref = model.aiStudioZhRef;
  const text = aiStudioZhRefSource(key);
  if (!text.trim()) return "";
  const item = ref?.items?.[key];
  if (!item || item.loading) return `<small class="ai-studio-zh-pending">中文对照 · ${item ? "本机模型翻译中…" : "排队中…"}</small>`;
  if (item.error) return `<small class="ai-studio-zh-error">中文对照失败：${escapeHtml(item.error)} <button type="button" data-ai-studio-zh-retry="${escapeHtml(key)}">重试</button></small>`;
  const stale = item.src !== text;
  return `${stale ? `<small class="ai-studio-zh-stale">英文改过了，下面还是改之前的译文 <button type="button" data-ai-studio-zh-retry="${escapeHtml(key)}">重新翻译</button></small>` : ""}<p>${escapeHtml(item.zh)}</p>`;
}

function aiStudioZhRefPaint(key) {
  document.querySelectorAll(`[data-ai-studio-zh-ref="${CSS.escape(key)}"]`).forEach((node) => {
    node.innerHTML = aiStudioZhRefHtml(key);
    node.hidden = !node.innerHTML;
  });
}

async function aiStudioZhTranslate(key) {
  const ref = model.aiStudioZhRef;
  const text = aiStudioZhRefSource(key);
  if (!ref?.on || !text.trim()) return;
  const draft = model.aiStudioDraft;
  ref.items[key] = { src: text, loading: true };
  aiStudioZhRefPaint(key);
  let next;
  try {
    const payload = await apiJson("/api/tools/ai-studio/translate", { method: "POST", body: JSON.stringify({ text }) });
    next = { src: text, zh: payload.zh || "" };
  } catch (error) {
    next = { src: text, error: error.message || "翻译失败" };
  }
  if (model.aiStudioZhRef !== ref || ref.draft !== draft) return;
  ref.items[key] = next;
  aiStudioZhRefPaint(key);
}

function aiStudioZhRefSync() {
  const ref = model.aiStudioZhRef;
  if (!ref?.on || !model.aiStudioDraft) return;
  if (ref.draft !== model.aiStudioDraft) {
    ref.draft = model.aiStudioDraft;
    ref.items = {};
  }
  aiStudioZhRefKeys().forEach((key) => {
    if (!ref.items[key] && aiStudioZhRefSource(key).trim()) aiStudioZhTranslate(key);
  });
}

function setAiStudioZhRef(on) {
  model.aiStudioZhRef = on ? { on: true, draft: null, items: {} } : null;
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-studio-zh-retry]");
  if (!button) return;
  event.preventDefault();
  aiStudioZhTranslate(button.dataset.aiStudioZhRetry);
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-studio-view-mode]");
  if (!button) return;
  const thumbs = button.dataset.aiStudioViewMode === "thumbs";
  if (model.aiStudioThumbs === thumbs) return;
  model.aiStudioThumbs = thumbs;
  try {
    localStorage.setItem(AI_STUDIO_THUMBS_KEY, thumbs ? "1" : "0");
  } catch {}
  document.querySelectorAll("[data-ai-studio-view-mode]").forEach((item) => {
    const active = (item.dataset.aiStudioViewMode === "thumbs") === thumbs;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", active ? "true" : "false");
  });
  refreshAiStudioLibraryDom({ force: true });
});

document.addEventListener("click", (event) => {
  const title = event.target.closest("[data-ai-studio-title-toggle]");
  if (!title) return;
  const id = title.dataset.aiStudioTitleToggle;
  const clamped = title.scrollHeight > title.clientHeight + 1;
  if (!clamped && !title.classList.contains("expanded")) return;
  const open = !title.classList.contains("expanded");
  if (open) aiStudioTitleOpen.add(id);
  else aiStudioTitleOpen.delete(id);
  title.classList.toggle("expanded", open);
});

function renderAiStudioJobCard(job) {
  const qc = job.qc || null;
  const qcClass = qc?.verdict === "PASS" ? "pass" : qc?.verdict === "FAIL" ? "fail" : "warn";
  const qcParts = aiStudioCardQcParts(qc, qcClass, `card:${job.id}`);
  const image = job.kind === "image";
  const placeholder = `<div class="ai-studio-video placeholder">${escapeHtml(job.status === "failed" ? "生成失败" : job.status === "cancelled" ? "已取消" : image ? "无图片" : "无视频")}</div>`;
  const media = image
    ? (job.has?.image
      ? `<a class="ai-studio-image-link" href="${escapeHtml(aiStudioMediaUrl(job, job.has.preview ? "preview" : "image"))}" target="_blank" rel="noopener" data-ai-studio-zoom-image data-title="${escapeHtml(job.title || "")}" title="放大查看（⌘+点击在新标签页打开）"><img class="ai-studio-video" loading="lazy" src="${escapeHtml(aiStudioMediaUrl(job, job.has.thumb ? "thumb" : "image"))}" alt="${escapeHtml(job.title)}"></a>`
      : placeholder)
    : job.has?.video
      ? renderAiStudioZoomableVideo(job, "ai-studio-video")
      : placeholder;
  const refCount = Object.keys(job.has || {}).filter((key) => /^ref\d$/.test(key) && job.has[key]).length;
  return `
    <article class="ai-studio-card ${escapeHtml(job.format)}${job.rating === "keep" ? " keep" : job.rating === "reject" ? " reject" : ""}">
      ${media}
      <div class="ai-studio-card-body">
        <div class="ai-studio-card-head">
          <strong class="${aiStudioTitleOpen.has(job.id) ? "expanded" : ""}" title="${escapeHtml(job.title)}" data-ai-studio-title-toggle="${escapeHtml(job.id)}">${escapeHtml(job.title)}</strong>
          ${qc ? `<span class="ai-studio-qc ${qcClass}" title="${escapeHtml((qc.lines || []).join("\n"))}">${escapeHtml(qc.verdict === "PASS" ? "质检通过" : qc.verdict === "FAIL" ? "质检未过" : qc.verdict)}</span>` : ""}
        </div>
        <small>${escapeHtml(aiStudioJobMeta(job))}${refCount ? ` · 参考图 ${refCount} 张` : ""}</small>
        <small>${escapeHtml(String(job.created_at || "").replace("T", " ").slice(0, 16))}${job.render_secs ? ` · ${image ? "生成" : "渲染"} ${escapeHtml(aiStudioDuration(job.render_secs))}` : ""}${qcParts.toggle}</small>
        ${job.error ? `<p class="ai-studio-card-error">${escapeHtml(job.error)}</p>` : ""}
        ${qcParts.body}
        <details class="ai-studio-card-prompt"><summary>提示词</summary><pre>${escapeHtml(job.prompt || "")}</pre></details>
        <label class="ai-studio-card-move"><span>归入</span><select data-ai-studio-move="${escapeHtml(job.id)}" aria-label="把「${escapeHtml(job.title)}」移到其他系列或分组">${renderAiStudioPlacementOptions(aiStudioSeriesById(job.series) ? job.series : "", job.group)}</select></label>
        <div class="ai-studio-card-actions">
          <button class="tiny-btn ghost-tiny${job.rating === "keep" ? " active" : ""}" type="button" data-ai-studio-rate="${escapeHtml(job.id)}" data-rating="${job.rating === "keep" ? "" : "keep"}" title="标记为可用">★ 留用</button>
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-rerun="${escapeHtml(job.id)}" data-new-seed="1" title="同样设置、换一个 seed 再出一条">换 seed</button>
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-edit="${escapeHtml(job.id)}" title="把这条的设置和提示词载入左侧编辑">载入编辑</button>
          ${job.has?.sheet ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(job, "sheet"))}" target="_blank" rel="noopener" data-ai-studio-zoom-image data-title="${escapeHtml(`${job.title || ""} · 联系表`)}" title="4×3 联系表，每秒 1.2 帧（⌘+点击在新标签页打开）">联系表</a>` : ""}
          ${job.has?.video ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(job, "video"))}" download title="${escapeHtml(job.video_path || "")}">下载</a>` : ""}
          ${job.has?.preview ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-use-first="${escapeHtml(job.id)}" title="把这张图带到视频创作，作为首帧">用作首帧</button>` : ""}
          ${job.has?.source ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-use-ref="${escapeHtml(job.id)}" title="把这张图加入图片编辑的参考图">用作参考图</button>` : ""}
          ${job.has?.image ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(job, "image"))}" download title="${escapeHtml(job.image_path || "")}">下载原图</a>` : ""}
          <button class="tiny-btn ghost-tiny danger" type="button" data-ai-studio-delete="${escapeHtml(job.id)}" title="删除记录和成片文件">删除</button>
        </div>
      </div>
    </article>
  `;
}

function renderAiStudioGallery() {
  if (model.aiStudioSeriesEditor) return renderAiStudioSeriesEditor();
  const nav = model.aiStudioNav || {};
  if (model.aiStudioState && nav.series && nav.series !== AI_STUDIO_UNFILED && !aiStudioSeriesById(nav.series)) {
    model.aiStudioNav = { series: "", group: "" };
    syncUrlState();
  }
  return model.aiStudioNav?.series ? renderAiStudioFolder() : renderAiStudioSeriesOverview();
}

function renderAiStudioCover(jobs, fallback) {
  const cover = jobs.find((job) => job.status === "done" && job.has?.thumb);
  return cover
    ? `<img src="${escapeHtml(aiStudioMediaUrl(cover, "thumb"))}" alt="" loading="lazy">`
    : `<span class="ai-studio-tile-mark" aria-hidden="true">${escapeHtml(fallback)}</span>`;
}

function renderAiStudioSeriesOverview() {
  const jobs = aiStudioFinishedJobs();
  const unfiled = jobs.filter((job) => !aiStudioSeriesById(job.series));
  const kinds = (list) => {
    const videos = list.filter((job) => (job.kind || "video") === "video").length;
    return [videos ? `视频 ${videos}` : "", list.length - videos ? `图片 ${list.length - videos}` : ""].filter(Boolean).join(" · ") || "还没有作品";
  };
  const tile = (series) => {
    const own = jobs.filter((job) => job.series === series.id);
    const groups = series.groups || [];
    return `
      <button class="ai-studio-tile" type="button" data-ai-studio-open-series="${escapeHtml(series.id)}">
        <span class="ai-studio-tile-cover">${renderAiStudioCover(own, Array.from(series.name)[0] || "系")}</span>
        <span class="ai-studio-tile-body">
          <strong>${escapeHtml(series.name)}</strong>
          <small>${escapeHtml(kinds(own))}${groups.length ? ` · ${groups.length} 个分组` : ""}</small>
          ${groups.length ? `<span class="ai-studio-tile-groups">${groups.slice(0, 6).map((group) => `<em>${escapeHtml(group.name)} ${own.filter((job) => job.group === group.id).length}</em>`).join("")}${groups.length > 6 ? "<em>…</em>" : ""}</span>` : ""}
          ${series.description ? `<span class="ai-studio-tile-desc">${escapeHtml(series.description)}</span>` : ""}
        </span>
      </button>
    `;
  };
  const unfiledTile = unfiled.length || !aiStudioSeriesList().length ? `
    <button class="ai-studio-tile unfiled" type="button" data-ai-studio-open-series="${AI_STUDIO_UNFILED}">
      <span class="ai-studio-tile-cover">${renderAiStudioCover(unfiled, "散")}</span>
      <span class="ai-studio-tile-body">
        <strong>未归入系列</strong>
        <small>${escapeHtml(kinds(unfiled))}</small>
        <span class="ai-studio-tile-desc">单独的镜头和图片；在作品卡片的「归入」里可以移到某个系列。</span>
      </span>
    </button>` : "";
  const categories = aiStudioSeriesCategories();
  const others = aiStudioSeriesList().filter((series) => !String(series.category || "").trim());
  const sections = categories.length
    ? [
      ...categories.map((name) => ({ name, items: aiStudioSeriesList().filter((series) => String(series.category || "").trim() === name) })),
      ...(others.length || unfiledTile ? [{ name: "其他", items: others, unfiled: true }] : []),
    ]
    : [{ name: "", items: aiStudioSeriesList(), unfiled: true }];
  return `
    <div class="ai-studio-overview-head">
      <span>按系列整理，点开系列再按分组、类型、画幅查看。</span>
      <button class="tiny-btn primary-tiny" type="button" data-ai-studio-new-series>＋ 新建系列</button>
    </div>
    ${sections.map((section) => `
      ${section.name ? `<h5 class="ai-studio-category-head">${escapeHtml(section.name)}<small>${section.items.length} 个系列</small></h5>` : ""}
      <div class="ai-studio-tiles">
        ${section.items.map(tile).join("")}
        ${section.unfiled ? unfiledTile : ""}
      </div>
    `).join("")}
  `;
}

function aiStudioSeriesCategories() {
  return [...new Set(aiStudioSeriesList().map((series) => String(series.category || "").trim()).filter(Boolean))];
}

function renderAiStudioFolder() {
  const nav = model.aiStudioNav || {};
  const unfiled = nav.series === AI_STUDIO_UNFILED;
  const series = unfiled ? null : aiStudioSeriesById(nav.series);
  const seriesJobs = aiStudioFinishedJobs().filter((job) => unfiled ? !aiStudioSeriesById(job.series) : job.series === nav.series);
  const groups = series?.groups || [];
  const currentGroup = groups.find((group) => group.id === nav.group) || null;
  const episodes = series?.episodes || [];
  const showEpisodes = Boolean(episodes.length) && nav.view !== "works";
  const items = showEpisodes ? episodes : seriesJobs;
  const ungrouped = items.filter((item) => !groups.some((group) => group.id === item.group));
  const visibleEpisodes = episodes.filter((item) => !nav.group || (nav.group === AI_STUDIO_UNFILED ? !groups.some((group) => group.id === item.group) : item.group === nav.group));
  const groupTabs = series && groups.length ? `
    <div class="ai-studio-chips ai-studio-group-tabs" role="group" aria-label="按分组查看">
      <button class="ai-studio-chip${!nav.group ? " active" : ""}" type="button" data-ai-studio-nav-group="">全部 <small>${items.length}</small></button>
      ${groups.map((group) => `<button class="ai-studio-chip${nav.group === group.id ? " active" : ""}" type="button" data-ai-studio-nav-group="${escapeHtml(group.id)}" ${group.note ? `title="${escapeHtml(group.note)}"` : ""}>${escapeHtml(group.name)} <small>${items.filter((item) => item.group === group.id).length}</small></button>`).join("")}
      ${ungrouped.length ? `<button class="ai-studio-chip${nav.group === AI_STUDIO_UNFILED ? " active" : ""}" type="button" data-ai-studio-nav-group="${AI_STUDIO_UNFILED}">未分组 <small>${ungrouped.length}</small></button>` : ""}
    </div>` : "";
  const note = currentGroup?.note || (!nav.group ? series?.description : "");
  return `
    <nav class="ai-studio-crumbs" aria-label="成片库位置">
      <button type="button" data-ai-studio-nav-root>全部系列</button>
      <span aria-hidden="true">/</span>
      ${currentGroup || nav.group === AI_STUDIO_UNFILED
        ? `<button type="button" data-ai-studio-nav-group="">${escapeHtml(series?.name || "")}</button><span aria-hidden="true">/</span><strong>${escapeHtml(currentGroup?.name || "未分组")}</strong>`
        : `<strong>${escapeHtml(unfiled ? "未归入系列" : series?.name || "")}</strong>`}
      ${series ? `<span class="ai-studio-crumbs-actions">
        <button class="tiny-btn primary-tiny" type="button" data-ai-studio-compose-in title="左侧创作的新作品会归入${escapeHtml(currentGroup ? `「${series.name} · ${currentGroup.name}」` : `「${series.name}」`)}">在这里创作</button>
        <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-edit-series="${escapeHtml(series.id)}">编辑系列</button>
        <button class="tiny-btn ghost-tiny danger" type="button" data-ai-studio-delete-series="${escapeHtml(series.id)}" title="只删除系列，作品回到「未归入系列」">删除系列</button>
      </span>` : ""}
    </nav>
    ${note ? `<p class="ai-studio-folder-note">${escapeHtml(note)}</p>` : ""}
    ${groupTabs}
    ${episodes.length ? `<div class="ai-studio-chips ai-studio-view-switch" role="group" aria-label="查看分集或成片">
      <button class="ai-studio-chip${showEpisodes ? " active" : ""}" type="button" data-ai-studio-nav-view="episodes">分集提示词 <small>${visibleEpisodes.length}</small></button>
      <button class="ai-studio-chip${showEpisodes ? "" : " active"}" type="button" data-ai-studio-nav-view="works">成片 <small>${aiStudioFolderJobs().length}</small></button>
    </div>` : ""}
    ${showEpisodes
      ? renderAiStudioEpisodes(series, visibleEpisodes, !nav.group)
      : renderAiStudioJobList(aiStudioFolderJobs(), series && !nav.group && groups.length ? series : null)}
  `;
}

function aiStudioEpisodeShots(episode) {
  if (Array.isArray(episode?.shots)) return episode.shots;
  return episode?.video ? [{ ...episode.video, mode: "i2v", lines: episode.recite || "" }] : [];
}

function aiStudioEpisodeJob(episodeId, kind, done = false, shot = null) {
  return (model.aiStudioState?.jobs || []).find((job) => job.episode === episodeId && !job.final && (job.kind || "video") === kind
    && (shot === null || Number(job.shot || 0) === shot)
    && (done ? job.status === "done" : job.status !== "cancelled")) || null;
}

function aiStudioShotTake(episodeId, shot) {
  const done = (model.aiStudioState?.jobs || []).filter((job) => job.episode === episodeId && !job.final && (job.kind || "video") === "video"
    && Number(job.shot || 0) === shot && job.status === "done" && job.has?.video && job.rating !== "reject");
  const voice = aiStudioShotVoice(episodeId, shot);
  const synced = voice?.status === "done" ? done.find((job) => job.voice_sync === voice.id) : null;
  return synced || done.find((job) => job.rating === "keep") || done[0] || null;
}

function aiStudioCardTake(episodeId, shot = 0) {
  const done = (model.aiStudioState?.jobs || []).filter((job) => job.episode === episodeId && !job.final && job.kind === "image"
    && Number(job.shot || 0) === shot && job.status === "done" && job.rating !== "reject");
  return done.find((job) => job.rating === "keep") || done[0] || null;
}

function aiStudioPlayback(episode) {
  const rank = { intro: 0, "": 1, bridge: 2 };
  return aiStudioEpisodeShots(episode).map((shot, index) => ({ shot, index }))
    .sort((a, b) => (rank[a.shot.role || ""] ?? 1) - (rank[b.shot.role || ""] ?? 1) || a.index - b.index).map((item) => item.index);
}

function aiStudioShotLabel(episode, index) {
  const shot = aiStudioEpisodeShots(episode)[index] || {};
  if (shot.role === "bridge") return "承上启下";
  if (shot.role === "intro") return `序章 ${aiStudioPlayback(episode).filter((i) => aiStudioEpisodeShots(episode)[i]?.role === "intro").indexOf(index) + 1}`;
  return `第 ${index + 1} 镜`;
}

function aiStudioNextEpisode(episode) {
  const episodes = aiStudioSeriesById(model.aiStudioNav?.series)?.episodes || [];
  const position = episodes.findIndex((item) => item.id === episode.id);
  return position >= 0 ? episodes[position + 1] || null : null;
}

// 首帧来源：自带底图 → 底图；第一个正片镜头 → 片头图；其余 → 播放顺序里上一镜的最后一帧。尾帧：本集或下一集的片头图。
function aiStudioShotSources(episode, index) {
  const shot = aiStudioEpisodeShots(episode)[index] || {};
  const mode = shot.mode || "i2v";
  const order = aiStudioPlayback(episode);
  const mains = order.filter((i) => !aiStudioEpisodeShots(episode)[i]?.role);
  let first = null;
  let last = null;
  if (mode !== "t2v") {
    if (shot.image_prompt) first = { job: aiStudioCardTake(episode.id, index), kind: "card", missing: "先出这一镜的底图" };
    else if (index === mains[0]) first = { job: aiStudioCardTake(episode.id), kind: "card", missing: "先出片头图，这一镜用它作为首帧" };
    else {
      const previous = order[order.indexOf(index) - 1];
      first = { job: aiStudioShotTake(episode.id, previous), kind: "tail", missing: `先出${aiStudioShotLabel(episode, previous)}，这一镜接着它的最后一帧` };
    }
  }
  if (mode === "flf") {
    const next = shot.last_from === "next_card" ? aiStudioNextEpisode(episode) : episode;
    last = { job: next ? aiStudioCardTake(next.id) : null, kind: "card",
      missing: shot.last_from === "next_card" ? `先出下一集「${next?.title || ""}」的片头图，这一镜落在它上面` : "先出片头图，这一镜落在它上面" };
  }
  return { mode, first, last };
}

function aiStudioShotNeeds(episode, index) {
  const { first, last } = aiStudioShotSources(episode, index);
  if (first && !first.job) return first.missing;
  if (last && !last.job) return last.missing;
  return "";
}

function aiStudioEpisodeFinal(episodeId, done = false) {
  return (model.aiStudioState?.jobs || []).find((job) => job.episode === episodeId && job.final
    && (done ? job.status === "done" : job.status !== "cancelled")) || null;
}

function aiStudioJobStatusText(latest, done) {
  if (latest && AI_STUDIO_ACTIVE.has(latest.status)) {
    return `${latest.status_label}${latest.progress && latest.status === "running" ? ` · ${latest.progress.step}/${latest.progress.total}` : ""}`;
  }
  return latest?.status === "failed" ? "上次失败" : done ? "已完成" : "未生成";
}

function aiStudioComposeSections(sections) {
  return (model.aiStudioConfig?.sections || []).map(({ key }) => `${key}: ${sections?.[key] || ""}`).join("\n");
}

function renderAiStudioEpisodeCardStep(episode) {
  const latest = aiStudioEpisodeJob(episode.id, "image", false, 0);
  const done = aiStudioCardTake(episode.id);
  const active = latest && AI_STUDIO_ACTIVE.has(latest.status);
  const preview = done?.has?.thumb
    ? `<a href="${escapeHtml(aiStudioMediaUrl(done, done.has.preview ? "preview" : "image"))}" target="_blank" rel="noopener" data-ai-studio-zoom-image data-title="${escapeHtml(`${episode.title} 片头图`)}" title="放大查看（⌘+点击在新标签页打开）"><img src="${escapeHtml(aiStudioMediaUrl(done, "thumb"))}" alt="${escapeHtml(episode.title)} 片头图" loading="lazy"></a>`
    : `<span class="ai-studio-episode-empty">片头图</span>`;
  return `
    <div class="ai-studio-shot${done ? " done" : ""}" data-ai-studio-target="${escapeHtml(`${episode.id}:image:0`)}">
      <div class="ai-studio-shot-media">${preview}</div>
      <div class="ai-studio-shot-body">
        <strong>① 片头地图 <small class="${active ? "ai-studio-status" : ""}">${escapeHtml(aiStudioJobStatusText(latest, done))}</small></strong>
        <span class="ai-studio-shot-lines">${(episode.route || []).length ? "按经纬度画的行迹地图（和成片开场一样），作为第 1 镜首帧" : "地图 + 诗名 + 时间地点，作为第 1 镜首帧"}</span>
        <div class="ai-studio-shot-actions">
          <button class="tiny-btn primary-tiny" type="button" data-ai-studio-episode-run="${escapeHtml(episode.id)}" data-kind="image" ${active || model.aiStudioBusy ? "disabled" : ""} title="${(episode.route || []).length ? "程序直接画行迹地图，几秒钟，不占用出图模型" : "H3-Image 文生图，约 3.5 分钟"}">${done ? ((episode.route || []).length ? "重画地图" : "再出一张") : "出片头图"}</button>
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-episode-load="${escapeHtml(episode.id)}" data-kind="image" title="载入左侧表单，可修改后再提交">载入编辑</button>
        </div>
      </div>
    </div>
  `;
}

function aiStudioShotVoice(episodeId, index) {
  const list = (model.aiStudioState?.voices || []).filter((voice) => voice.episode === episodeId && Number(voice.shot) === index);
  return list[list.length - 1] || null;
}

function aiStudioVoiceText(shot) {
  return String(shot.voice || shot.lines || "").trim();
}

function renderAiStudioVoiceRow(episode, shot, index) {
  const text = aiStudioVoiceText(shot);
  const voice = aiStudioShotVoice(episode.id, index);
  const running = voice && (voice.status === "queued" || voice.status === "running");
  const stale = voice?.status === "done" && voice.text !== text;
  const status = !voice ? (index < 0 ? "未配音，合成时没有这一段" : "未配音，合成时用原片的声音")
    : running ? (voice.status === "queued" ? "配音排队中…" : "配音生成中…")
    : voice.status === "failed" ? `配音失败：${voice.error || "未知错误"}`
    : stale ? "配音文字已改，需重新配音（合成时先用原片的声音）"
    : `已配音 · ${Number(voice.duration || 0).toFixed(1)} 秒，${index < 0 ? "合成时放在片头前" : "合成时替换原片人声"}`;
  const poly = (voice?.polyphones || []).map((item) => `${item.char}(${item.guess})`).join(" ");
  const ready = model.aiStudioState?.voice_available;
  const take = aiStudioShotTake(episode.id, index);
  const series = aiStudioSeriesById(model.aiStudioNav?.series);
  const synced = voice?.status === "done" && !stale && take?.voice_sync === voice.id;
  const syncing = voice && (model.aiStudioState?.jobs || []).some((job) => job.voice_sync === voice.id && ["queued", "submitted", "running", "finishing"].includes(job.status));
  return `
    <div class="ai-studio-voice-row">
      <span class="ai-studio-voice-text"><b>配音</b>${escapeHtml(text || "（没有配音文字）")}${shot.voice || index < 0 ? "" : text ? " <small>（同朗读文字）</small>" : ""}</span>
      <small class="${running ? "ai-studio-status" : ""}">${escapeHtml(status)}</small>
      ${poly && !running ? `<small class="ai-studio-voice-poly" title="按上下文猜的读音；不对就在「配音设置 · 读音表」里加一行，再重新配音">多音字请核对：${escapeHtml(poly)}</small>` : ""}
      ${voice?.status === "done" ? `<audio controls preload="none" src="${escapeHtml(aiStudioMediaUrl(voice, "voice"))}"></audio>` : ""}
      <div class="ai-studio-shot-actions">
        <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-run="${escapeHtml(episode.id)}" data-shot="${index}" ${running || !text || !ready || model.aiStudioBusy ? "disabled" : ""} title="${escapeHtml(ready ? "IndexTTS 按旁白音色读这一镜的配音文字，不用重出视频" : model.aiStudioState?.voice_missing || "配音模型还没就绪")}">${voice?.status === "done" ? "重新配音" : "生成配音"}</button>
        <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-edit="${escapeHtml(episode.id)}" data-shot="${index}" ${running || model.aiStudioBusy ? "disabled" : ""} title="只改配音读的文字，画面里的字幕不变；可以写 <似|SI4> 指定读音">改配音文字</button>
        ${take && shot.role ? (series?.narrator === take.id ? `<small class="ai-studio-voice-poly" title="序章、承上、承上启下的解说都用这个声音">系列解说音色</small>`
          : `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-narrator="${escapeHtml(take.id)}" title="整个系列的序章、承上、承上启下解说都照这一镜原片的声音读；诗句仍用各集的朗读参考">用这镜做系列解说音色</button>`) : ""}
        ${take && episode.narrator === take.id ? `<small class="ai-studio-voice-poly" title="本集配音都照这一镜原片的声音和语气读">本集朗读参考</small>`
          : take ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-reference="${escapeHtml(episode.id)}" data-take="${escapeHtml(take.id)}" title="本集配音都照这一镜原片的声音、抑扬顿挫来读，整集连贯；设好后点「整集配音」">用这镜做本集朗读参考</button>` : ""}
        ${take && (episode.music || episode.narrator) === take.id ? `<small class="ai-studio-voice-poly" title="整集背景音乐取自这一镜原片分离出的伴奏，循环铺满全片">整集配乐来源</small>`
          : take ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-music="${escapeHtml(episode.id)}" data-take="${escapeHtml(take.id)}" title="整集只铺一条连续的背景音乐，取自这一镜原片的伴奏；换了之后重新合成生效">用这镜配乐做整集背景音乐</button>` : ""}
        ${synced ? `<small class="ai-studio-voice-poly" title="这一镜的画面是按当前配音生成的，嘴型跟着配音走">口型已对上配音</small>`
          : voice?.status === "done" && !stale && take ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-lipsync="${escapeHtml(episode.id)}" data-shot="${index}" ${syncing || model.aiStudioBusy ? "disabled" : ""} title="人物在镜头里开口时用：按这条配音重新生成这一镜的视频，H3 让嘴型跟着配音动（首帧和画面描述沿用原来那条，约半小时）">${syncing ? "正在按配音对口型…" : "按配音重做口型"}</button>` : ""}
        ${voice && !running ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-delete="${escapeHtml(voice.id)}" title="删掉这条配音，合成时回到原片的声音">删配音</button>` : ""}
      </div>
    </div>
  `;
}

function renderAiStudioVoiceSettings(series) {
  const narrator = series.narrator ? (model.aiStudioState?.jobs || []).find((job) => job.id === series.narrator) : null;
  const rules = String(series.pron || "").split("\n").filter((line) => line.trim()).length;
  return `
    <details class="ai-studio-voice-settings">
      <summary>配音设置 · 读音表 ${rules} 条 · 解说音色：${escapeHtml(narrator ? narrator.title : "每镜用自己原片的声音")}${model.aiStudioState?.voice_available ? "" : ` · ${escapeHtml(model.aiStudioState?.voice_missing || "配音模型未就绪")}`}</summary>
      <small class="ai-studio-hint">配音单独生成，再和视频合成：改读音、改文字只需重新配音（每条十几秒），不用重出视频。读音表每行一条：词语 + 空格 + 每个字的拼音（数字声调，ü 写 v，不标的字写 -），如「知何似 - - si4」「指爪 - zhao3」「那复 na3 -」。</small>
      <textarea class="ai-studio-voice-pron" data-ai-studio-pron rows="5" placeholder="知何似 - - si4&#10;指爪 - zhao3&#10;那复 na3 -">${escapeHtml(series.pron || "")}</textarea>
      <div class="ai-studio-shot-actions">
        <button class="tiny-btn primary-tiny" type="button" data-ai-studio-pron-save="${escapeHtml(series.id)}" ${model.aiStudioBusy ? "disabled" : ""}>保存读音表</button>
        ${narrator ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-narrator="" title="不指定解说音色，解说也用本集朗读参考或原片的声音">改回每镜用原声</button>` : ""}
      </div>
    </details>
  `;
}

function renderAiStudioShotRow(episode, shot, index) {
  const latest = aiStudioEpisodeJob(episode.id, "video", false, index);
  const done = aiStudioShotTake(episode.id, index);
  const active = latest && AI_STUDIO_ACTIVE.has(latest.status);
  const needs = aiStudioShotNeeds(episode, index);
  const bridge = shot.role === "bridge";
  const sources = aiStudioShotSources(episode, index);
  const source = [shot.mode === "t2v" ? (bridge ? "地图动画" : "新场景") : shot.image_prompt ? "底图开场" : sources.first?.kind === "card" ? "片头图开场" : "接上一镜",
    shot.mode === "flf" ? (shot.last_from === "next_card" ? "落在下一集片头图" : "落在本集片头图") : ""].filter(Boolean).join(" → ");
  const label = aiStudioShotLabel(episode, index);
  const cardLatest = shot.image_prompt ? aiStudioEpisodeJob(episode.id, "image", false, index) : null;
  const cardDone = shot.image_prompt ? aiStudioCardTake(episode.id, index) : null;
  const cardActive = cardLatest && AI_STUDIO_ACTIVE.has(cardLatest.status);
  const preview = done?.has?.thumb
    ? renderAiStudioZoomableVideo({ ...done, title: `${episode.title} · ${label}` })
    : `<span class="ai-studio-episode-empty">${label}</span>`;
  const qcParts = done?.qc ? aiStudioCardQcParts(done.qc, done.qc.verdict === "PASS" ? "pass" : done.qc.verdict === "FAIL" ? "fail" : "warn", `shot:${done.id}`) : { toggle: "", body: "" };
  const takes = (model.aiStudioState?.jobs || []).filter((job) => job.episode === episode.id && !job.final && (job.kind || "video") === "video"
    && Number(job.shot || 0) === index && job.status === "done").length;
  return `
    <div class="ai-studio-shot${done ? " done" : ""}" data-ai-studio-target="${escapeHtml(`${episode.id}:video:${index}`)}"${shot.image_prompt ? ` data-ai-studio-target-image="${escapeHtml(`${episode.id}:image:${index}`)}"` : ""}>
      <div class="ai-studio-shot-media">${preview}</div>
      <div class="ai-studio-shot-body">
        <strong>${label} <small>${escapeHtml(source)} · ${Number(shot.seconds || 12)} 秒</small>
          <small class="${active ? "ai-studio-status" : ""}">${escapeHtml(aiStudioJobStatusText(latest, done))}${takes > 1 ? ` · ${takes} 条${done?.rating === "keep" ? "，用留用那条" : "，用最新一条"}` : ""}</small>${qcParts.toggle}</strong>
        ${shot.caption_title ? `<span class="ai-studio-shot-caption">${escapeHtml([shot.caption_title, shot.caption_line].filter(Boolean).join(" · "))}</span>` : ""}
        <span class="ai-studio-shot-lines">${escapeHtml(shot.lines || "（无朗读）")}</span>
        ${aiStudioVoiceText(shot) ? renderAiStudioVoiceRow(episode, shot, index) : ""}
        ${qcParts.body}
        <div class="ai-studio-shot-actions">
          <button class="tiny-btn primary-tiny" type="button" data-ai-studio-episode-run="${escapeHtml(episode.id)}" data-kind="video" data-shot="${index}" ${active || needs || model.aiStudioBusy ? "disabled" : ""} title="${escapeHtml(needs || `${Number(shot.seconds || 12)} 秒预览清晰度约 ${Math.round(Number(shot.seconds || 12) * 3.3)} 分钟`)}">${done ? "再出一条" : `出${label.replace(" ", "")}`}</button>
          ${shot.image_prompt ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-episode-run="${escapeHtml(episode.id)}" data-kind="image" data-shot="${index}" ${cardActive || model.aiStudioBusy ? "disabled" : ""} title="H3-Image 画这一镜的底图（总路线图），约 3.5 分钟">${cardActive ? "底图生成中…" : cardDone ? "重出底图" : "出底图"}</button>${cardDone ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(cardDone, cardDone.has?.preview ? "preview" : "image"))}" target="_blank" rel="noopener" data-ai-studio-zoom-image data-title="${escapeHtml(`${episode.title || ""} · 第 ${index + 1} 镜底图`)}">看底图</a>` : ""}` : ""}
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-episode-load="${escapeHtml(episode.id)}" data-kind="video" data-shot="${index}" title="载入左侧表单，可修改后再提交">载入编辑</button>
        </div>
      </div>
    </div>
  `;
}

function renderAiStudioFinalRow(episode, shots) {
  const latest = aiStudioEpisodeFinal(episode.id);
  const done = aiStudioEpisodeFinal(episode.id, true);
  const active = latest && AI_STUDIO_ACTIVE.has(latest.status);
  const missing = shots.findIndex((_, index) => !aiStudioShotTake(episode.id, index));
  const ready = shots.length && missing < 0;
  const status = active ? "合成中…" : latest?.status === "failed" ? latest.error || "上次合成失败" : done ? `已合成 · ${aiStudioDuration(done.seconds)}` : ready ? "镜头齐了，可以合成" : `还差${aiStudioShotLabel(episode, missing)}`;
  const preview = done?.has?.video
    ? renderAiStudioZoomableVideo({ ...done, title: `${episode.title} · 成片` })
    : `<span class="ai-studio-episode-empty">成片</span>`;
  return `
    <div class="ai-studio-shot ai-studio-shot-final${done ? " done" : ""}" data-ai-studio-target="${escapeHtml(`${episode.id}:final`)}">
      <div class="ai-studio-shot-media">${preview}</div>
      <div class="ai-studio-shot-body">
        <strong>④ 合成成片 <small class="${active ? "ai-studio-status" : ""}">${escapeHtml(status)}</small></strong>
        <span class="ai-studio-shot-lines">按序章 → 分镜 → 全诗片尾 → 承上启下拼接；诗句隶书竖排，旁白横排字幕，另附可开关的字幕轨（1080P）；配音和整集连续的配乐分两轨合成，可分别下载${(episode.route || []).length ? "；地图按真实经纬度绘制，承上启下落在下一集的同一帧" : ""}</span>
        <div class="ai-studio-shot-actions">
          <button class="tiny-btn primary-tiny" type="button" data-ai-studio-episode-compose="${escapeHtml(episode.id)}" ${active || !ready || model.aiStudioBusy ? "disabled" : ""} title="${ready ? "每镜用「留用」那条，没有就用最新一条；约 1 分钟" : "先把每一镜都出好"}">${done ? "重新合成" : "合成成片"}</button>
          ${shots.some((shot) => aiStudioVoiceText(shot)) ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-voice-run="${escapeHtml(episode.id)}" ${!model.aiStudioState?.voice_available || model.aiStudioBusy ? "disabled" : ""} title="${escapeHtml(model.aiStudioState?.voice_available ? "把本集所有带配音文字的镜头都重新配一遍（模型只加载一次）" : model.aiStudioState?.voice_missing || "配音模型还没就绪")}">整集配音</button>` : ""}
          ${done?.has?.video ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(done, "video"))}" download>下载成片</a>` : ""}
          ${done?.has?.srt ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(done, "srt"))}" download title="字幕文件，可导入剪映等再精修">字幕 SRT</a>` : ""}
          ${done?.has?.voice_track ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(done, "voice_track"))}" download title="只有朗读和旁白，和成片等长">配音轨</a>` : ""}
          ${done?.has?.music_track ? `<a class="tiny-btn ghost-tiny" href="${escapeHtml(aiStudioMediaUrl(done, "music_track"))}" download title="整集连续的背景音乐，和成片等长">配乐轨</a>` : ""}
        </div>
      </div>
    </div>
  `;
}

function renderAiStudioThumbTile(job, { label = "", sub = "", state = "", attrs = "" } = {}) {
  const image = job?.kind === "image";
  const hasMedia = job && (image ? job.has?.image : job.has?.video);
  const poster = job?.has?.thumb ? aiStudioMediaUrl(job, "thumb") : image && job?.has?.image ? aiStudioMediaUrl(job, "image") : "";
  const title = label || job?.title || "";
  const zoom = !hasMedia ? ""
    : image ? ` data-ai-studio-zoom-image="${escapeHtml(aiStudioMediaUrl(job, job.has.preview ? "preview" : "image"))}" data-title="${escapeHtml(job.title || title)}"`
      : ` data-ai-studio-zoom-video="${escapeHtml(aiStudioMediaUrl(job, "video"))}" data-poster="${escapeHtml(poster)}" data-title="${escapeHtml(job.title || title)}"`;
  return `
    <figure class="ai-studio-thumb${state ? ` ${state}` : ""}${job?.rating === "keep" ? " keep" : ""}${job?.format ? ` fmt-${escapeHtml(job.format)}` : ""}"${attrs}>
      <button class="ai-studio-thumb-media" type="button"${zoom} ${hasMedia ? `title="放大查看「${escapeHtml(job.title || title)}」"` : "disabled"}>
        ${poster ? `<img src="${escapeHtml(poster)}" alt="" loading="lazy">` : `<span>${escapeHtml(state === "active" ? "生成中" : "未生成")}</span>`}
        ${hasMedia && !image ? `<i aria-hidden="true">▶</i>` : ""}
      </button>
      <figcaption><strong title="${escapeHtml(job?.title || title)}">${escapeHtml(title)}</strong>${sub ? `<small>${escapeHtml(sub)}</small>` : ""}</figcaption>
    </figure>
  `;
}

function renderAiStudioJobThumb(job) {
  const active = AI_STUDIO_ACTIVE.has(job.status);
  const sub = active ? job.status_label || "生成中"
    : job.status === "failed" ? "生成失败" : job.status === "cancelled" ? "已取消"
      : [job.seconds ? aiStudioDuration(job.seconds) : "", job.qc?.verdict === "PASS" ? "质检通过" : job.qc?.verdict === "FAIL" ? "质检未过" : ""].filter(Boolean).join(" · ");
  const parts = String(job.title || "").split(" · ");
  const label = parts.length >= 3 ? `${parts[0]} · ${parts[parts.length - 1]}` : job.title;
  return renderAiStudioThumbTile(job, { label, sub, state: active ? "active" : job.status === "failed" ? "failed" : "" });
}

function renderAiStudioEpisodeThumbs(episode) {
  const shots = aiStudioEpisodeShots(episode);
  const order = [...shots.map((shot, index) => shot.role === "intro" ? index : -1), ...shots.map((shot, index) => shot.role ? -1 : index), ...shots.map((shot, index) => shot.role === "bridge" ? index : -1)].filter((index) => index >= 0);
  const doneShots = shots.filter((_, index) => aiStudioShotTake(episode.id, index)).length;
  const status = (latest, done) => latest && AI_STUDIO_ACTIVE.has(latest.status) ? { state: "active", sub: aiStudioJobStatusText(latest, done) } : { state: done ? "" : "empty", sub: done ? "" : aiStudioJobStatusText(latest, done) };
  const cardLatest = aiStudioEpisodeJob(episode.id, "image", false, 0);
  const cardDone = aiStudioCardTake(episode.id);
  const finalLatest = aiStudioEpisodeFinal(episode.id);
  const finalDone = aiStudioEpisodeFinal(episode.id, true);
  const finalStatus = status(finalLatest, finalDone);
  return `
    <article class="ai-studio-episode thumbs">
      <header>
        <strong>${escapeHtml(episode.title)}</strong>
        <small>已出 ${doneShots}/${shots.length}${finalDone ? ` · 成片 ${escapeHtml(aiStudioDuration(finalDone.seconds))}` : ""}</small>
      </header>
      <div class="ai-studio-thumb-grid">
        ${renderAiStudioThumbTile(cardDone, { label: "片头图", ...status(cardLatest, cardDone), attrs: ` data-ai-studio-target="${escapeHtml(`${episode.id}:image:0`)}"` })}
        ${order.map((index) => {
          const latest = aiStudioEpisodeJob(episode.id, "video", false, index);
          const done = aiStudioShotTake(episode.id, index);
          return renderAiStudioThumbTile(done, { label: aiStudioShotLabel(episode, index), ...status(latest, done), attrs: ` data-ai-studio-target="${escapeHtml(`${episode.id}:video:${index}`)}"` });
        }).join("")}
        ${renderAiStudioThumbTile(finalDone, { label: "成片", sub: finalStatus.sub || (finalDone ? aiStudioDuration(finalDone.seconds) : ""), state: `${finalStatus.state} final`, attrs: ` data-ai-studio-target="${escapeHtml(`${episode.id}:final`)}"` })}
      </div>
    </article>
  `;
}

function renderAiStudioEpisodeCard(episode) {
  if (model.aiStudioThumbs) return renderAiStudioEpisodeThumbs(episode);
  const shots = aiStudioEpisodeShots(episode);
  const doneShots = shots.filter((_, index) => aiStudioShotTake(episode.id, index)).length;
  const total = shots.reduce((sum, shot) => sum + Number(shot.seconds || 12), 0);
  const shotCount = shots.filter((shot) => !shot.role).length;
  const introRows = shots.map((shot, index) => shot.role === "intro" ? renderAiStudioShotRow(episode, shot, index) : "").join("");
  return `
    <article class="ai-studio-episode">
      <header>
        <strong>${escapeHtml(episode.title)}</strong>
        ${episode.poem_title ? `<small>《${escapeHtml(episode.poem_title)}》${episode.author ? ` · ${escapeHtml(episode.author)}` : ""}</small>` : ""}
        <small>${escapeHtml([episode.place, episode.date, episode.age].filter(Boolean).join(" · "))}</small>
        ${episode.post ? `<small>${escapeHtml(episode.post)}</small>` : ""}
        ${(episode.route || []).length ? `<small class="ai-studio-episode-route" title="合成时按经纬度画行迹地图：序章、片头、承上启下都用它">行迹：${escapeHtml((episode.route || []).map((stop) => stop.name).filter((name, index, list) => name && name !== list[index - 1]).join(" → "))}</small>` : ""}
      </header>
      ${episode.poem ? `<blockquote class="ai-studio-episode-poem" title="整首诗，按镜头分句朗读">${escapeHtml(episode.poem)}</blockquote>` : ""}
      <small class="ai-studio-hint">${introRows ? "序章 + " : ""}${shotCount} 个镜头${shots.some((shot) => shot.role === "bridge") ? " + 承上启下" : ""} · 约 ${Math.round(total)} 秒 + 全诗片尾 7 秒 · 已出 ${doneShots}/${shots.length}</small>
      <div class="ai-studio-shots">
        ${renderAiStudioEpisodeCardStep(episode)}
        ${introRows ? `<div class="ai-studio-shot-group">序章（在片头之前播放：总路线与时间线，最后落在本集片头图上）</div>${introRows}` : ""}
        ${episode.recap ? `<div class="ai-studio-shot-group">承上（片头前一段解说，画面是本集开场地图，不用出视频）</div>
          <div class="ai-studio-shot">${renderAiStudioVoiceRow(episode, { lines: episode.recap }, -1)}</div>` : ""}
        <div class="ai-studio-shot-group">② 分镜（整首诗，按顺序出）</div>
        ${shots.map((shot, index) => shot.role ? "" : renderAiStudioShotRow(episode, shot, index)).join("")}
        ${shots.some((shot) => shot.role === "bridge") ? `<div class="ai-studio-shot-group">③ 承上启下（从本集最后一帧化入地图，落在下一集片头图上，两集无缝相接）</div>` : ""}
        ${shots.map((shot, index) => shot.role === "bridge" ? renderAiStudioShotRow(episode, shot, index) : "").join("")}
        ${renderAiStudioFinalRow(episode, shots)}
      </div>
      <details class="ai-studio-card-prompt"><summary>片头图提示词</summary><pre>${escapeHtml(episode.image?.prompt || "")}</pre></details>
      <details class="ai-studio-card-prompt"><summary>分镜提示词（${shots.length} 镜）</summary>${shots.map((shot, index) => `<p class="ai-studio-shot-prompt-title">${aiStudioShotLabel(episode, index)} · ${escapeHtml(shot.lines || "")}</p><pre>${escapeHtml(aiStudioComposeSections(shot.sections))}</pre>`).join("")}</details>
      ${episode.note ? `<small class="ai-studio-hint">${escapeHtml(episode.note)}</small>` : ""}
    </article>
  `;
}

function renderAiStudioEpisodes(series, episodes, byGroup) {
  if (!episodes.length) return `<p class="ai-studio-empty">这个分组还没有分集提示词。</p>`;
  const groups = byGroup ? (series.groups || []).map((group) => ({ group, episodes: episodes.filter((item) => item.group === group.id) })) : [];
  const loose = byGroup ? episodes.filter((item) => !(series.groups || []).some((group) => group.id === item.group)) : episodes;
  return `
    ${renderAiStudioVoiceSettings(series)}
    ${groups.filter((entry) => entry.episodes.length).map(({ group, episodes: list }) => `
      <section class="ai-studio-group">
        <h4>${escapeHtml(group.name)} <small>${list.length} 集</small></h4>
        <div class="ai-studio-episodes">${list.map(renderAiStudioEpisodeCard).join("")}</div>
      </section>
    `).join("")}
    ${loose.length ? `<div class="ai-studio-episodes">${loose.map(renderAiStudioEpisodeCard).join("")}</div>` : ""}
  `;
}

function renderAiStudioJobList(allJobs, bySeriesGroups) {
  const config = model.aiStudioConfig || {};
  const filter = model.aiStudioFilter || {};
  const jobs = aiStudioFilteredJobs(allJobs);
  const categories = (config.categories || []).filter((category) => !filter.kind || category.kind === filter.kind);
  const count = (key, value) => allJobs.filter((job) => (key === "kind" ? job.kind || "video" : job[key]) === value).length;
  const sections = bySeriesGroups
    ? [...(bySeriesGroups.groups || []).map((group) => ({ title: group.name, jobs: jobs.filter((job) => job.group === group.id) })),
      { title: "未分组", jobs: jobs.filter((job) => !(bySeriesGroups.groups || []).some((group) => group.id === job.group)) }]
    : categories.map((category) => ({ title: category.label, note: category.kind === "image" ? "图片" : "视频", jobs: jobs.filter((job) => job.category === category.id) }));
  const groups = sections.filter((section) => section.jobs.length);
  return `
    ${allJobs.length ? `<div class="ai-studio-filters">
      <div class="ai-studio-chips" role="group" aria-label="按成品类型筛选">
        ${[["", "视频 + 图片", allJobs.length], ["video", "视频", count("kind", "video")], ["image", "图片", count("kind", "image")]].map(([value, label, total]) => `<button class="ai-studio-chip${(filter.kind || "") === value ? " active" : ""}" type="button" data-ai-studio-filter="kind" data-value="${value}">${label} <small>${total}</small></button>`).join("")}
      </div>
      <div class="ai-studio-chips" role="group" aria-label="按类别筛选">
        <button class="ai-studio-chip${!filter.category ? " active" : ""}" type="button" data-ai-studio-filter="category" data-value="">全部类别</button>
        ${categories.filter((category) => count("category", category.id) || filter.category === category.id).map((category) => `<button class="ai-studio-chip${filter.category === category.id ? " active" : ""}" type="button" data-ai-studio-filter="category" data-value="${escapeHtml(category.id)}">${escapeHtml(category.label)} <small>${count("category", category.id)}</small></button>`).join("")}
      </div>
      <div class="ai-studio-chips" role="group" aria-label="按画幅和状态筛选">
        <button class="ai-studio-chip${!filter.format ? " active" : ""}" type="button" data-ai-studio-filter="format" data-value="">全部画幅</button>
        ${Object.entries(config.formats || {}).filter(([key]) => count("format", key) || filter.format === key).map(([key, item]) => `<button class="ai-studio-chip${filter.format === key ? " active" : ""}" type="button" data-ai-studio-filter="format" data-value="${escapeHtml(key)}">${escapeHtml(item.label)} <small>${count("format", key)}</small></button>`).join("")}
        <span class="ai-studio-chip-divider" aria-hidden="true"></span>
        ${[["", "全部状态"], ["done", "已完成"], ["failed", "失败"], ["cancelled", "已取消"]].map(([value, label]) => `<button class="ai-studio-chip${(filter.status || "") === value ? " active" : ""}" type="button" data-ai-studio-filter="status" data-value="${value}">${label}</button>`).join("")}
      </div>
    </div>` : ""}
    ${groups.length ? groups.map((group) => `
      <section class="ai-studio-group">
        <h4>${escapeHtml(group.title)} <small>${group.note ? `${escapeHtml(group.note)} · ` : ""}${group.jobs.length} 条</small></h4>
        ${model.aiStudioThumbs ? `<div class="ai-studio-thumb-grid">${group.jobs.map(renderAiStudioJobThumb).join("")}</div>` : `<div class="ai-studio-grid">${group.jobs.map(renderAiStudioJobCard).join("")}</div>`}
      </section>
    `).join("") : `<p class="ai-studio-empty">${allJobs.length ? "没有符合筛选条件的作品。" : model.aiStudioNav?.series && model.aiStudioNav.series !== AI_STUDIO_UNFILED ? "这里还没有作品。点上方「在这里创作」，左侧出片 / 出图后会自动归到这里。" : "还没有作品。在左侧写好提示词，点「直接出片」或「直接出图」。"}</p>`}
  `;
}

function renderAiStudioSeriesEditor() {
  const editor = model.aiStudioSeriesEditor;
  const groups = editor.groups || [];
  return `
    <form class="ai-studio-series-editor" data-ai-studio-series-form autocomplete="off">
      <h4>${editor.id ? "编辑系列" : "新建系列"}</h4>
      <label class="ai-studio-field"><span>系列名称</span>
        <input type="text" maxlength="30" value="${escapeHtml(editor.name || "")}" placeholder="例如：唐诗系列" data-ai-studio-series-field="name">
      </label>
      <label class="ai-studio-field"><span>类别 <small>成片库里同一类别的系列排在一起；留空归到「其他」</small></span>
        <input type="text" maxlength="20" value="${escapeHtml(editor.category || "")}" placeholder="例如：诗文行迹" list="ai-studio-series-categories" data-ai-studio-series-field="category">
        <datalist id="ai-studio-series-categories">${aiStudioSeriesCategories().map((name) => `<option value="${escapeHtml(name)}"></option>`).join("")}</datalist>
      </label>
      <label class="ai-studio-field"><span>系列说明 <small>定位、受众、每集结构，只给自己看</small></span>
        <textarea rows="3" maxlength="1000" data-ai-studio-series-field="description">${escapeHtml(editor.description || "")}</textarea>
      </label>
      <label class="ai-studio-field"><span>系列风格 <small>英文画面规范：画风、色调、光线、镜头、服化道。创作时可一键插入提示词，保证全系列统一</small></span>
        <textarea rows="5" maxlength="3000" spellcheck="false" data-ai-studio-series-field="style">${escapeHtml(editor.style || "")}</textarea>
      </label>
      <div class="ai-studio-field"><span>分组 <small>例如按诗人、按季、按主题；作品可以在分组之间随时移动</small></span>
        <div class="ai-studio-series-groups">
          ${groups.map((group, index) => `
            <div class="ai-studio-series-group">
              <input type="text" maxlength="30" value="${escapeHtml(group.name || "")}" placeholder="分组名，例如：李白" data-ai-studio-group-field="name" data-index="${index}" aria-label="第 ${index + 1} 个分组名称">
              <textarea rows="2" maxlength="600" placeholder="分组说明：人物设定、篇目清单……" data-ai-studio-group-field="note" data-index="${index}" aria-label="第 ${index + 1} 个分组说明">${escapeHtml(group.note || "")}</textarea>
              <button class="tiny-btn ghost-tiny danger" type="button" data-ai-studio-group-remove="${index}" title="${group.id ? "移除分组，其中的作品变为「未分组」" : "移除"}">移除</button>
            </div>
          `).join("")}
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-group-add>＋ 添加分组</button>
        </div>
      </div>
      ${editor.error ? `<div class="error toolbox-publish-error">${escapeHtml(editor.error)}</div>` : ""}
      <div class="ai-studio-submit">
        <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-series-cancel>取消</button>
        <button class="tiny-btn primary-tiny" type="button" data-ai-studio-series-save ${editor.busy ? "disabled" : ""}>${editor.busy ? "保存中…" : editor.id ? "保存" : "创建系列"}</button>
      </div>
    </form>
  `;
}

function aiStudioGalleryKey() {
  const jobs = model.aiStudioNav?.view !== "works" && aiStudioSeriesById(model.aiStudioNav?.series)?.episodes?.length
    ? (model.aiStudioState?.jobs || []).map((job) => ({ ...job, title: `${job.title}#${job.progress?.step || ""}` }))
    : aiStudioFinishedJobs();
  return JSON.stringify([model.aiStudioThumbs, model.aiStudioFilter, model.aiStudioNav, model.aiStudioSeriesEditor, model.aiStudioState?.series || [],
    jobs.map((job) => [job.id, job.status, job.rating, job.title, job.series, job.group, Boolean(job.qc)])]);
}

function aiStudioDocumentTitle() {
  if (!isToolboxStandalone() || model.toolboxView !== "ai_studio") return "";
  const nav = model.aiStudioNav || {};
  const series = nav.series === AI_STUDIO_UNFILED ? { name: "未归入系列" } : aiStudioSeriesById(nav.series);
  const group = (series?.groups || []).find((item) => item.id === nav.group);
  return series ? `${[series.name, group?.name].filter(Boolean).join(" · ")} · AI Studio` : "AI Studio";
}

function refreshAiStudioLibraryDom({ force = false } = {}) {
  const active = document.querySelector("[data-ai-studio-active]");
  if (active) active.innerHTML = renderAiStudioActiveJobs();
  const pill = document.querySelector("[data-ai-studio-engine]");
  if (pill) pill.outerHTML = renderAiStudioEnginePill();
  const key = aiStudioGalleryKey();
  const gallery = document.querySelector("[data-ai-studio-gallery]");
  if (gallery && key !== aiStudioGallerySignature && (force || !model.aiStudioSeriesEditor)) {
    // 正在播放的成片不被轮询打断；筛选是用户主动操作，照常刷新。
    const playing = [...gallery.querySelectorAll("video")].some((video) => !video.paused);
    if (force || !playing) {
      gallery.innerHTML = renderAiStudioGallery();
      aiStudioGallerySignature = key;
      syncUrlState();
      if (isToolboxStandalone()) document.title = aiStudioDocumentTitle() || document.title;
    }
  }
}

function renderAiStudioEnginePill() {
  const running = Boolean(model.aiStudioState?.comfy_running);
  return `<span class="toolbox-comfyui-state${running ? " running" : ""}" data-ai-studio-engine>${running ? "ComfyUI 运行中" : "ComfyUI 未启动 · 出片时会自动启动"}</span>`;
}

function renderAiStudioForm() {
  const config = model.aiStudioConfig || {};
  const draft = model.aiStudioDraft || {};
  const category = aiStudioCategory(draft.category) || {};
  const lint = model.aiStudioLint;
  const imageKind = draft.kind === "image";
  const draftSeries = aiStudioSeriesById(draft.series);
  const draftGroup = (draftSeries?.groups || []).find((group) => group.id === draft.group) || null;
  const draftEpisode = (draftSeries?.episodes || []).find((item) => item.id === draft.episode) || null;
  const sizes = (imageKind ? config.formats?.[draft.format]?.image_sizes : config.formats?.[draft.format]?.sizes)?.[draft.quality] || [];
  const qualities = imageKind ? config.image_qualities || {} : config.qualities || {};
  const formats = Object.entries(config.formats || {})
    .filter(([, item]) => (item.kinds || ["video"]).includes(imageKind ? "image" : "video"))
    .map(([key, item]) => [key, item.label]);
  if (imageKind && draft.mode === "edit") formats.unshift(["auto", "跟随参考图"]);
  const refSlots = [];
  for (let index = 1; index <= (config.max_refs || AI_STUDIO_MAX_REFS); index += 1) {
    refSlots.push(index);
    if (!draft[`ref${index}_image`]) break;
  }
  const pickImage = (kind, rawLabel, note = "点击选择 PNG / JPEG") => {
    const label = escapeHtml(rawLabel);
    return `
    <label class="ai-studio-image-pick${draft[`${kind}_image`] ? " has-image" : ""}">
      ${draft[`${kind}_image`] ? `<img src="${escapeHtml(draft[`${kind}_image`])}" alt="${label}"><em>${label}</em>` : `<span>${label}<small>${escapeHtml(note)}</small></span>`}
      <input type="file" accept="image/png,image/jpeg,image/webp" data-ai-studio-image="${kind}">
      ${draft[`${kind}_image`] ? `<button class="ai-studio-image-clear" type="button" data-ai-studio-image-clear="${kind}" title="移除" aria-label="移除${label}">×</button>` : ""}
    </label>
  `;
  };
  const segmented = (field, options) => `
    <div class="ai-studio-segmented" role="radiogroup">
      ${options.map(([value, label, note]) => `<button type="button" class="${draft[field] === value ? "active" : ""}" role="radio" aria-checked="${draft[field] === value ? "true" : "false"}" data-ai-studio-set="${field}" data-value="${escapeHtml(value)}" ${note ? `title="${escapeHtml(note)}"` : ""}>${escapeHtml(label)}</button>`).join("")}
    </div>
  `;
  const step = (index, title, note, body) => `
    <section class="ai-studio-step">
      <header class="ai-studio-step-head"><b>${index}</b><strong>${title}</strong>${note ? `<small>${note}</small>` : ""}</header>
      ${body}
    </section>
  `;
  const modeEntries = Object.entries((imageKind ? config.image_modes : config.modes) || {}).map(([key, label]) => [key, label]);
  draft.lang = aiStudioPromptLang(draft.lang);
  const zhPrompt = draft.lang === "zh";
  const zhRef = !zhPrompt && Boolean(model.aiStudioZhRef?.on);
  const categoryHint = (zhPrompt && category.hint_zh) || category.hint;
  const needsFrames = !imageKind && draft.mode !== "t2v";
  const needsRefs = imageKind && draft.mode === "edit";
  const qualityHint = sizes.length
    ? `${sizes[0]}×${sizes[1]} · ${qualities[draft.quality]?.note || ""}`
    : draft.format === "auto" ? `按 <Picture 1> 的比例选最接近的画幅 · ${qualities[draft.quality]?.note || ""}` : "";
  const secondsField = imageKind ? "" : `<label class="ai-studio-field"><span>时长（秒）</span><input type="number" min="1" max="12" step="0.5" value="${escapeHtml(String(draft.seconds || 5))}" data-ai-studio-input="seconds"></label>`;
  const seedField = `<label class="ai-studio-field"><span>Seed</span><input type="text" inputmode="numeric" value="${escapeHtml(draft.seed || "")}" placeholder="留空随机" data-ai-studio-input="seed"></label>`;
  const fastField = imageKind ? "" : `<label class="ai-studio-field" title="特征变化小的采样步直接复用上一步结果，省时间但可能掉细节；实验中，重要镜头先和关闭时对比">
    <span>快速（实验）</span><span><input type="checkbox" ${draft.fast ? "checked" : ""} data-ai-studio-check="fast"> 跳步缓存</span></label>`;
  return `
    <form class="ai-studio-form" data-ai-studio-form autocomplete="off">
      ${step(1, "类型与类别", "", `
        <div class="ai-studio-kind-switch ai-studio-segmented" role="radiogroup" aria-label="创作类型">
          ${[["video", "出片 · 视频", "MiniMax H3 · 8 步"], ["image", "出图 · 图片", "MiniMax H3-Image · 6 步"]].map(([value, label, note]) => `<button type="button" class="${(draft.kind || "video") === value ? "active" : ""}" role="radio" aria-checked="${(draft.kind || "video") === value ? "true" : "false"}" data-ai-studio-kind="${value}">${label}<small>${note}</small></button>`).join("")}
        </div>
        <div class="ai-studio-field">
          <div class="ai-studio-chips">
            ${(config.categories || []).filter((item) => (item.kind || "video") === (draft.kind || "video")).map((item) => `<button class="ai-studio-chip${draft.category === item.id ? " active" : ""}" type="button" data-ai-studio-category="${escapeHtml(item.id)}">${escapeHtml(item.label)}</button>`).join("")}
          </div>
          ${categoryHint ? `<small class="ai-studio-hint">${escapeHtml(categoryHint)}</small>` : ""}
        </div>
      `)}
      ${step(2, "生成方式", needsFrames || needsRefs ? "需要选择图片" : imageKind ? "只用提示词出图" : "只用提示词出片", `
        ${segmented("mode", modeEntries)}
        ${needsFrames ? `<div class="ai-studio-images">${pickImage("first", "首帧")}${draft.mode === "flf" ? pickImage("last", "尾帧") : ""}</div>` : ""}
        ${needsRefs ? `<div class="ai-studio-field">
          <div class="ai-studio-images ai-studio-refs">${refSlots.map((index) => pickImage(`ref${index}`, `<Picture ${index}>`, index === 1 ? "要编辑的图" : "补充参考")).join("")}</div>
          <small class="ai-studio-hint">&lt;Picture 1&gt; 是要编辑的图，其余是参考；在提示词里按编号指代，例如 “Replace the sofa in &lt;Picture 1&gt; with the chair from &lt;Picture 2&gt;”。</small>
        </div>` : ""}
      `)}
      ${step(3, "提示词", "", `
        <div class="ai-studio-prompt-head">
          ${imageKind ? `<small class="ai-studio-hint">6 步出图，不用写负面提示词</small>` : segmented("style", [["structured", "六段式"], ["free", "自由描述"]])}
          <div class="ai-studio-lang-switch" title="提示词语言：中文会直接交给 H3（Qwen3-VL 文本编码器能读懂中文）">${segmented("lang", [["en", "EN"], ["zh", "中文"]])}</div>
          ${zhPrompt ? "" : `<button class="tiny-btn ghost-tiny${zhRef ? " active" : ""}" type="button" data-ai-studio-zh-ref-toggle aria-pressed="${zhRef ? "true" : "false"}" title="在每段英文下面显示中文译文，只供阅读；提交的仍是英文。用本机 Ollama 翻译，不上传">中文对照</button>`}
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-template title="放弃对提示词的改动，回到载入时的样子（新建时就是模板）">复原</button>
        </div>
        ${zhRef ? `<small class="ai-studio-hint">中文对照：每段下面是本机模型的译文，只供阅读，提交的仍是英文；译文会记住，下次打开同一段不用再等。ComfyUI 正在出片时翻译会慢一些。<button class="ai-studio-zh-link" type="button" data-ai-studio-zh-switch-template>改用中文模板写</button></small>` : ""}
        ${zhPrompt ? `<small class="ai-studio-hint">中文模式：直接用中文提交，不经过翻译。台词照样放在引号里；如果画面里冒出多余字幕，换回 EN 再出一次。</small>` : ""}
        ${imageKind || draft.style === "free"
          ? `<textarea class="ai-studio-free" rows="14" spellcheck="false" data-ai-studio-input="free_text" placeholder="${zhPrompt
            ? imageKind ? "完整的中文画面描述：主体、环境、光线、镜头、质感；要画进图里的字放在引号里。" : "中文描述画面、分镜、机位、声音；台词放在引号里。"
            : imageKind ? "完整的英文画面描述：主体、环境、光线、镜头、质感；要画进图里的字放在引号里。" : "英文描述画面、分镜、机位、声音；中文只放在引号台词里。"}">${escapeHtml(draft.free_text || "")}</textarea>${zhRef ? `<div class="ai-studio-zh-ref" data-ai-studio-zh-ref="free_text">${aiStudioZhRefHtml("free_text")}</div>` : ""}`
          : (config.sections || []).map(({ key, label }) => `
            <label class="ai-studio-section">
              <span><b>${escapeHtml(label)}</b><code>${escapeHtml(key)}</code></span>
              <textarea rows="${key === "detailed_description" ? 5 : key === "non_diegetic_music" ? 1 : 3}" spellcheck="false" data-ai-studio-section="${escapeHtml(key)}">${escapeHtml(draft.sections?.[key] || "")}</textarea>
            </label>
            ${zhRef ? `<div class="ai-studio-zh-ref" data-ai-studio-zh-ref="${escapeHtml(key)}">${aiStudioZhRefHtml(key)}</div>` : ""}
          `).join("")}
        ${lint ? `<div class="ai-studio-lint${lint.errors?.length ? " has-errors" : ""}">
          ${lint.errors?.length ? lint.errors.map((item) => `<p class="error-line">✕ ${escapeHtml(item)}</p>`).join("") : `<p class="ok-line">✓ 没有错误</p>`}
          ${(lint.warns || []).map((item) => `<p class="warn-line">! ${escapeHtml(item)}</p>`).join("")}
        </div>` : ""}
      `)}
      ${step(4, "画面参数", "", `
        <div class="ai-studio-params">
          <div class="ai-studio-field ai-studio-param-wide"><span>画幅</span>${segmented("format", formats)}</div>
          <div class="ai-studio-field ai-studio-param-wide"><span>清晰度</span>${segmented("quality", Object.entries(qualities).map(([key, item]) => [key, item.label, item.note]))}
            ${qualityHint ? `<small class="ai-studio-hint">${escapeHtml(qualityHint)}</small>` : ""}
          </div>
          ${secondsField}
          ${seedField}
          ${fastField}
        </div>
      `)}
      ${step(5, "命名与归档", "可选", `
        <label class="ai-studio-field">
          <span>${imageKind ? "图片标题" : "镜头标题"}</span>
          <input type="text" maxlength="60" value="${escapeHtml(draft.title || "")}" placeholder="${imageKind ? "例如：雨夜面馆 · 海报" : "例如：司马光砸瓮 · 第 2 镜"}" data-ai-studio-input="title">
        </label>
        <div class="ai-studio-field">
          <span>归入系列</span>
          <div class="ai-studio-placement">
            <select data-ai-studio-placement aria-label="新作品归入的系列和分组">${renderAiStudioPlacementOptions(draftSeries ? draft.series : "", draft.group)}</select>
            ${draftSeries?.style ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-insert-style title="把系列风格追加到提示词，保证整个系列画面统一">插入系列风格</button>` : ""}
          </div>
          ${draftEpisode ? `<small class="ai-studio-hint">属于分集「${escapeHtml(draftEpisode.title)}」${draft.kind === "video" ? ` 第 ${Number(draft.shot || 0) + 1} 镜` : ""}，出好后会显示在分集卡片上。</small>` : draftGroup?.note ? `<small class="ai-studio-hint">${escapeHtml(draftGroup.note)}</small>` : ""}
        </div>
      `)}
      ${model.aiStudioFormError ? `<div class="error toolbox-publish-error">${escapeHtml(model.aiStudioFormError)}</div>` : ""}
      <div class="ai-studio-submit">
        <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-lint ${model.aiStudioBusy ? "disabled" : ""}>检查提示词</button>
        ${lint?.errors?.length ? `<button class="tiny-btn ghost-tiny" type="button" data-ai-studio-submit data-force="1" ${model.aiStudioBusy ? "disabled" : ""}>${imageKind ? "忽略检查仍然出图" : "忽略检查仍然出片"}</button>` : ""}
        <button class="tiny-btn primary-tiny" type="button" data-ai-studio-submit ${model.aiStudioBusy ? "disabled" : ""}>${model.aiStudioBusy === "submit" ? "提交中…" : imageKind ? "直接出图" : "直接出片"}</button>
      </div>
    </form>
  `;
}

function renderAiStudioStatusBar() {
  const line = (kind, text) => `
    <div class="ai-studio-status-line ${kind}" role="${kind === "error" ? "alert" : "status"}">
      <span>${escapeHtml(text)}</span>
      <button type="button" data-ai-studio-status-close="${kind}" title="关闭" aria-label="关闭">×</button>
    </div>`;
  const lines = [model.aiStudioError ? line("error", model.aiStudioError) : "", model.aiStudioMessage ? line("message", model.aiStudioMessage) : ""].join("");
  return lines.trim() ? `<div class="ai-studio-statusbar">${lines}</div>` : "";
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-studio-status-close]");
  if (!button) return;
  if (button.dataset.aiStudioStatusClose === "error") model.aiStudioError = "";
  else model.aiStudioMessage = "";
  const line = button.closest(".ai-studio-status-line");
  const bar = line?.parentElement;
  line?.remove();
  if (bar && !bar.querySelector(".ai-studio-status-line")) bar.remove();
});

function renderToolboxAiStudioPanel() {
  const state = model.aiStudioState;
  if (!state && model.aiStudioError) return `<div class="error toolbox-publish-error">${escapeHtml(model.aiStudioError)}</div>`;
  if (!state || !model.aiStudioConfig) return `<div class="toolbox-cscli-panel"><p class="ai-studio-empty">正在读取 AI Studio…</p></div>`;
  aiStudioGallerySignature = aiStudioGalleryKey();
  return `
    <div class="ai-studio-panel" data-ai-studio-panel>
      <div class="toolbox-publish-toolbar">
        <div>
          <strong>AI Studio · MiniMax H3 视频 / H3-Image 图片</strong>
        </div>
        <div class="toolbox-publish-actions">
          ${renderAiStudioEnginePill()}
          <a class="tiny-btn ghost-tiny" href="/ai-finals.html" target="_blank" rel="noopener" title="新页面：只列出每一集的成片链接">每集成片</a>
          <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-refresh ${model.aiStudioLoading ? "disabled" : ""}>刷新</button>
          ${isToolboxStandalone() ? renderAiKnowledgeToggle("aik-toolbar-toggle") : ""}
        </div>
      </div>
      ${state.missing_models?.length && model.aiStudioDraft?.kind !== "image" ? `<div class="error toolbox-publish-error">ComfyUI 缺少视频模型：${escapeHtml(state.missing_models.join("、"))}</div>` : ""}
      ${state.missing_image_models?.length && model.aiStudioDraft?.kind === "image" ? `<div class="error toolbox-publish-error">图片模型还没准备好（可能还在下载）：${escapeHtml(state.missing_image_models.join("、"))}</div>` : ""}
      <div class="ai-studio-layout${model.aiStudioComposeCollapsed ? " compose-collapsed" : ""}" style="--ai-studio-compose-width: ${model.aiStudioComposeWidth}px">
        ${model.aiStudioComposeCollapsed
          ? `<section class="ai-studio-compose ai-studio-compose-rail" aria-label="创作">
              <button type="button" data-ai-studio-compose-toggle title="展开创作区" aria-expanded="false"><span aria-hidden="true">»</span><b>创作</b></button>
            </section>`
          : `<section class="ai-studio-compose" aria-label="创作">
              <div class="ai-studio-splitter" data-ai-studio-splitter role="separator" aria-orientation="vertical" aria-label="拖动调整创作区宽度" aria-valuemin="${AI_STUDIO_COMPOSE_MIN_WIDTH}" aria-valuemax="${AI_STUDIO_COMPOSE_MAX_WIDTH}" aria-valuenow="${model.aiStudioComposeWidth}" tabindex="0" title="左右拖动调整宽度，拖到最左收起；双击恢复默认"></div>
              <div class="ai-studio-compose-head">
                <h3>创作</h3>
                <button class="tiny-btn ghost-tiny" type="button" data-ai-studio-compose-toggle title="收起创作区，给成片库更多空间" aria-expanded="true">« 收起</button>
              </div>
              ${renderAiStudioForm()}
            </section>`}
        <section class="ai-studio-library" aria-label="成片库">
          <h3>成片库 <small>${escapeHtml(model.aiStudioConfig.library_dir || "")}</small>
            <span class="ai-studio-view-switch" role="group" aria-label="成片库显示方式">
              <button type="button" class="${model.aiStudioThumbs ? "" : "active"}" data-ai-studio-view-mode="cards" aria-pressed="${model.aiStudioThumbs ? "false" : "true"}" title="完整卡片：带操作按钮和说明">卡片</button>
              <button type="button" class="${model.aiStudioThumbs ? "active" : ""}" data-ai-studio-view-mode="thumbs" aria-pressed="${model.aiStudioThumbs ? "true" : "false"}" title="只看缩略图，点开放大播放">缩略图</button>
            </span>
          </h3>
          <div data-ai-studio-active>${renderAiStudioActiveJobs()}</div>
          <div data-ai-studio-gallery>${renderAiStudioGallery()}</div>
        </section>
      </div>
      ${renderAiStudioStatusBar()}
      <p class="toolbox-comfyui-note">渲染引擎：ComfyUI。视频走 H3 FL2VA Pruned Q5 + Parasyte Turbo 8 步；图片走 MiniMax H3-Image（Pruned Q5 GGUF，6 步，文生图 / 参考图编辑）。视频和图片共用一条队列，同一时间只跑一条。公开发布须加 AI 生成标识，并遵守 MiniMax H3 / H3-Image 社区许可。</p>
    </div>
  `;
}

function clampAiStudioComposeWidth(width) {
  return Math.round(Math.min(AI_STUDIO_COMPOSE_MAX_WIDTH, Math.max(AI_STUDIO_COMPOSE_MIN_WIDTH, Number(width) || AI_STUDIO_COMPOSE_DEFAULT_WIDTH)));
}

function setAiStudioComposeWidth(width) {
  model.aiStudioComposeWidth = clampAiStudioComposeWidth(width);
  try {
    localStorage.setItem(AI_STUDIO_COMPOSE_WIDTH_KEY, String(model.aiStudioComposeWidth));
  } catch {}
}

function bindAiStudioSplitter(panel) {
  const handle = panel.querySelector("[data-ai-studio-splitter]");
  const layout = panel.querySelector(".ai-studio-layout");
  if (!handle || !layout) return;
  const apply = (width) => {
    layout.style.setProperty("--ai-studio-compose-width", `${clampAiStudioComposeWidth(width)}px`);
    handle.setAttribute("aria-valuenow", String(clampAiStudioComposeWidth(width)));
  };
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = model.aiStudioComposeWidth;
    let width = startWidth;
    handle.setPointerCapture(event.pointerId);
    layout.classList.add("resizing");
    const onMove = (moveEvent) => {
      width = startWidth + moveEvent.clientX - startX;
      layout.classList.toggle("collapse-hint", width < AI_STUDIO_COMPOSE_COLLAPSE_WIDTH);
      apply(width);
    };
    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      layout.classList.remove("resizing", "collapse-hint");
      if (width < AI_STUDIO_COMPOSE_COLLAPSE_WIDTH) {
        setAiStudioComposeCollapsed(true);
        renderPreservingToolboxBodyPosition();
        return;
      }
      setAiStudioComposeWidth(width);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  });
  handle.addEventListener("dblclick", () => {
    setAiStudioComposeWidth(AI_STUDIO_COMPOSE_DEFAULT_WIDTH);
    apply(model.aiStudioComposeWidth);
  });
  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setAiStudioComposeWidth(model.aiStudioComposeWidth + (event.key === "ArrowLeft" ? -20 : 20));
    apply(model.aiStudioComposeWidth);
  });
}

function setAiStudioComposeCollapsed(collapsed) {
  model.aiStudioComposeCollapsed = Boolean(collapsed);
  try {
    localStorage.setItem(AI_STUDIO_COMPOSE_COLLAPSED_KEY, model.aiStudioComposeCollapsed ? "1" : "0");
  } catch {}
}

function revealAiStudioCompose() {
  if (model.aiStudioComposeCollapsed) {
    setAiStudioComposeCollapsed(false);
    renderPreservingToolboxBodyPosition();
  }
  document.querySelector(".ai-studio-compose")?.scrollIntoView({ block: "start", behavior: "smooth" });
}

function aiStudioPayload(force = false) {
  const draft = model.aiStudioDraft || {};
  const placement = aiStudioSeriesById(draft.series) ? { series: draft.series, group: draft.group || "", episode: draft.episode || "", shot: draft.episode ? Number(draft.shot || 0) : 0 } : { series: "", group: "", episode: "", shot: 0 };
  if (draft.kind === "image") {
    const refs = [];
    for (let index = 1; index <= AI_STUDIO_MAX_REFS; index += 1) if (draft[`ref${index}_image`]) refs.push(draft[`ref${index}_image`]);
    return {
      kind: "image", lang: aiStudioPromptLang(draft.lang), title: draft.title, ...placement, category: draft.category, mode: draft.mode, format: draft.format,
      quality: draft.quality, seed: draft.seed, free_text: draft.free_text, ref_images: draft.mode === "edit" ? refs : [], force,
    };
  }
  return {
    kind: "video", lang: aiStudioPromptLang(draft.lang), title: draft.title, ...placement, category: draft.category, style: draft.style, mode: draft.mode, format: draft.format,
    quality: draft.quality, seconds: Number(draft.seconds) || 5, seed: draft.seed, sections: draft.sections,
    free_text: draft.free_text, first_image: draft.mode !== "t2v" ? draft.first_image : "",
    last_image: draft.mode === "flf" ? draft.last_image : "", fast: Boolean(draft.fast), force,
  };
}

async function aiStudioRequest(path, { method = "POST", body = {} } = {}) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

async function aiStudioLintDraft() {
  model.aiStudioBusy = "lint";
  model.aiStudioFormError = "";
  renderPreservingToolboxBodyPosition();
  try {
    model.aiStudioLint = await aiStudioRequest("/api/tools/ai-studio/lint", { body: aiStudioPayload() });
  } catch (error) {
    model.aiStudioFormError = error.message || "检查失败";
  } finally {
    model.aiStudioBusy = "";
    renderPreservingToolboxBodyPosition();
  }
}

async function aiStudioSubmit(force = false) {
  model.aiStudioBusy = "submit";
  model.aiStudioFormError = "";
  model.aiStudioMessage = "";
  renderPreservingToolboxBodyPosition();
  try {
    const payload = await aiStudioRequest("/api/tools/ai-studio/jobs", { body: aiStudioPayload(force) });
    model.aiStudioState = payload.state;
    model.aiStudioLint = payload.job?.lint || null;
    model.aiStudioMessage = `已提交「${payload.job?.title || ""}」（${payload.job?.width}×${payload.job?.height}），生成进度显示在右侧。`;
    if (model.aiStudioDraft) model.aiStudioDraft.seed = "";
  } catch (error) {
    model.aiStudioFormError = error.message || "提交失败";
    if (/提示词检查未通过/.test(model.aiStudioFormError)) {
      try { model.aiStudioLint = await aiStudioRequest("/api/tools/ai-studio/lint", { body: aiStudioPayload() }); } catch {}
    }
  } finally {
    model.aiStudioBusy = "";
    scheduleAiStudioPoll();
    renderPreservingToolboxBodyPosition();
  }
}

async function aiStudioJobAction(path, options, message) {
  try {
    const payload = await aiStudioRequest(path, options);
    if (payload.state) model.aiStudioState = payload.state;
    model.aiStudioMessage = message || "";
    model.aiStudioError = "";
  } catch (error) {
    model.aiStudioError = error.message || "操作失败";
  }
  scheduleAiStudioPoll();
  renderPreservingToolboxBodyPosition();
}

async function aiStudioMediaDataUrl(job, kind) {
  const response = await fetch(aiStudioMediaUrl(job, kind), { cache: "no-store" });
  if (!response.ok) throw new Error("读取图片失败");
  const blob = await response.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.readAsDataURL(blob);
  });
}

async function aiStudioUseImage(jobId, target) {
  const job = (model.aiStudioState?.jobs || []).find((item) => item.id === jobId);
  if (!job) return;
  try {
    const dataUrl = await aiStudioMediaDataUrl(job, target === "first" ? "preview" : "source");
    if (target === "first") {
      aiStudioSwitchKind("video");
      const draft = model.aiStudioDraft;
      if (draft.mode === "t2v") draft.mode = "i2v";
      if ((model.aiStudioConfig?.formats?.[job.format]?.kinds || []).includes("video")) draft.format = job.format;
      draft.first_image = dataUrl;
      model.aiStudioMessage = `已把「${job.title}」设为视频首帧，写好动作提示词就可以出片。`;
    } else {
      aiStudioSwitchKind("image");
      const draft = model.aiStudioDraft;
      draft.mode = "edit";
      let slot = 1;
      while (slot < AI_STUDIO_MAX_REFS && draft[`ref${slot}_image`]) slot += 1;
      draft[`ref${slot}_image`] = dataUrl;
      if (slot === 1) draft.format = "auto";
      model.aiStudioMessage = `已把「${job.title}」加入参考图 <Picture ${slot}>。`;
    }
    model.aiStudioDraft.dirty = true;
    model.aiStudioError = "";
  } catch (error) {
    model.aiStudioError = error.message || "读取图片失败";
  }
  renderPreservingToolboxBodyPosition();
  revealAiStudioCompose();
}

function aiStudioLoadJobIntoDraft(jobId) {
  const job = (model.aiStudioState?.jobs || []).find((item) => item.id === jobId);
  if (!job) return;
  if (job.kind === "image") {
    aiStudioSwitchKind("image");
    model.aiStudioDraft = aiStudioWithOrigin({
      ...aiStudioDraftFromCategory(job.category, { kind: "image", lang: job.lang || "en" }),
      title: job.title, series: job.series || "", group: job.group || "", mode: job.mode, format: job.format, quality: job.quality, seed: String(job.seed || ""),
      free_text: job.prompt || "", dirty: true,
    });
    model.aiStudioLint = null;
    model.aiStudioMessage = job.mode === "edit" ? "已载入设置和提示词；参考图请重新选择。" : "已载入设置和提示词。";
    renderPreservingToolboxBodyPosition();
    revealAiStudioCompose();
    return;
  }
  aiStudioSwitchKind("video");
  model.aiStudioDraft = aiStudioWithOrigin({
    ...aiStudioDraftFromCategory(job.category, { lang: job.lang || "en" }),
    kind: "video", title: job.title, series: job.series || "", group: job.group || "", style: job.style, mode: job.mode, format: job.format, quality: job.quality,
    seconds: job.seconds, seed: String(job.seed || ""), sections: { ...(job.sections || {}) },
    free_text: job.style === "free" ? job.prompt : "", first_image: "", last_image: "", fast: Boolean(job.fast), dirty: true,
  });
  model.aiStudioLint = null;
  model.aiStudioMessage = job.mode !== "t2v" ? "已载入设置和提示词；首帧/尾帧图片请重新选择。" : "已载入设置和提示词。";
  renderPreservingToolboxBodyPosition();
  revealAiStudioCompose();
}

function aiStudioEpisodeContext(episodeId) {
  const series = aiStudioSeriesById(model.aiStudioNav?.series);
  const episode = (series?.episodes || []).find((item) => item.id === episodeId);
  return episode ? { series, episode } : null;
}

function aiStudioEpisodePayload(series, episode, kind, firstImage = "", index = 0, lastImage = "") {
  const placement = { series: series.id, group: episode.group || "", episode: episode.id, seed: "", force: false };
  if (kind === "image") {
    const shot = aiStudioEpisodeShots(episode)[index] || {};
    const own = index > 0 && shot.image_prompt;
    return {
      ...placement, shot: own ? index : 0, kind: "image", title: `${episode.title} · ${own ? `${aiStudioShotLabel(episode, index)}底图` : "片头"}`,
      category: "keyframe", mode: "t2i", format: episode.image?.format || "portrait", quality: episode.image?.quality || "4mp",
      free_text: own ? shot.image_prompt : episode.image?.prompt || "", ref_images: [],
    };
  }
  const shot = aiStudioEpisodeShots(episode)[index] || {};
  const mode = shot.mode || "i2v";
  return {
    ...placement, shot: index, kind: "video", title: `${episode.title} · ${aiStudioShotLabel(episode, index).replace(" ", "")}`, category: "free", style: "structured", mode,
    format: shot.format || "portrait", quality: shot.quality || "preview", seconds: shot.seconds || 12,
    sections: { ...(shot.sections || {}) }, free_text: "", first_image: mode === "t2v" ? "" : firstImage, last_image: mode === "flf" ? lastImage : "",
  };
}

async function aiStudioSourceUrl(source) {
  if (!source?.job) return "";
  if (source.kind === "tail") return aiStudioMediaDataUrl(source.job, "tail");
  return aiStudioMediaDataUrl(source.job, source.job.has?.source ? "source" : "preview");
}

async function aiStudioEpisodeFrames(episode, index = 0) {
  const { first, last } = aiStudioShotSources(episode, index);
  return { first: await aiStudioSourceUrl(first), last: await aiStudioSourceUrl(last) };
}

async function aiStudioRunEpisode(episodeId, kind, index = 0) {
  const context = aiStudioEpisodeContext(episodeId);
  if (!context || model.aiStudioBusy) return;
  model.aiStudioBusy = "submit";
  model.aiStudioError = "";
  model.aiStudioMessage = "";
  renderPreservingToolboxBodyPosition();
  try {
    const needs = kind === "video" ? aiStudioShotNeeds(context.episode, index) : "";
    if (needs) throw new Error(needs);
    const frames = kind === "video" ? await aiStudioEpisodeFrames(context.episode, index) : { first: "", last: "" };
    const payload = await aiStudioRequest("/api/tools/ai-studio/jobs", { body: aiStudioEpisodePayload(context.series, context.episode, kind, frames.first, index, frames.last) });
    model.aiStudioState = payload.state;
    model.aiStudioMessage = `已提交「${payload.job?.title || ""}」（${payload.job?.width}×${payload.job?.height}），进度显示在分集卡片和右侧「进行中」里。`;
  } catch (error) {
    model.aiStudioError = error.message || "提交失败";
  } finally {
    model.aiStudioBusy = "";
    scheduleAiStudioPoll();
    renderPreservingToolboxBodyPosition();
  }
}

async function aiStudioComposeEpisode(episodeId) {
  const context = aiStudioEpisodeContext(episodeId);
  if (!context || model.aiStudioBusy) return;
  model.aiStudioBusy = "submit";
  model.aiStudioError = "";
  model.aiStudioMessage = "";
  renderPreservingToolboxBodyPosition();
  try {
    const url = `/api/tools/ai-studio/series/${encodeURIComponent(context.series.id)}/episodes/${encodeURIComponent(episodeId)}/compose`;
    const payload = await aiStudioRequest(url, { body: {} });
    model.aiStudioState = payload.state;
    model.aiStudioMessage = `正在合成「${payload.job?.title || ""}」，约 1 分钟，完成后在分集卡片里播放和下载。`;
  } catch (error) {
    model.aiStudioError = error.message || "合成失败";
  } finally {
    model.aiStudioBusy = "";
    scheduleAiStudioPoll();
    renderPreservingToolboxBodyPosition();
  }
}

async function aiStudioVoiceAction(episodeId, body, generate) {
  const context = aiStudioEpisodeContext(episodeId);
  if (!context || model.aiStudioBusy) return;
  model.aiStudioBusy = "submit";
  model.aiStudioError = "";
  renderPreservingToolboxBodyPosition();
  try {
    const url = `/api/tools/ai-studio/series/${encodeURIComponent(context.series.id)}/episodes/${encodeURIComponent(episodeId)}/voice`;
    const payload = await aiStudioRequest(url, { body: { ...body, generate } });
    model.aiStudioState = payload.state;
    model.aiStudioMessage = body.lipsync ? `已提交「${payload.job?.title || ""}」：按配音重新生成这一镜，完成后合成会自动用这条。`
      : !generate ? (body.music !== undefined ? "已换整集背景音乐，点「重新合成」生效（不用重新配音）。"
      : body.narrator !== undefined ? "已设为本集朗读参考，点「整集配音」按它的声音和语气重新读。" : "已保存配音文字，点「生成配音」重新读。")
      : payload.created?.length ? `已提交 ${payload.created.length} 条配音；第一次要加载模型，约 1 分钟，之后每条十几秒。配好后点「重新合成」就会用新配音。`
      : "这些镜头的配音已经在排队了。";
  } catch (error) {
    model.aiStudioError = error.message || "配音失败";
  } finally {
    model.aiStudioBusy = "";
    scheduleAiStudioPoll();
    renderPreservingToolboxBodyPosition();
  }
}

async function aiStudioLoadEpisode(episodeId, kind, index = 0) {
  const context = aiStudioEpisodeContext(episodeId);
  if (!context) return;
  const { series, episode } = context;
  aiStudioSwitchKind(kind);
  const payload = aiStudioEpisodePayload(series, episode, kind, "", index);
  const base = aiStudioDraftFromCategory(payload.category, { series: series.id, group: payload.group, lang: "en" });
  model.aiStudioDraft = aiStudioWithOrigin({
    ...base, title: payload.title, series: series.id, group: payload.group, episode: episode.id, shot: kind === "video" ? index : 0, mode: payload.mode,
    format: payload.format, quality: payload.quality, seed: "", dirty: true,
    ...(kind === "image" ? { free_text: payload.free_text } : { style: "structured", seconds: payload.seconds, sections: payload.sections, free_text: "" }),
  });
  model.aiStudioLint = null;
  model.aiStudioError = "";
  let firstNote = "";
  if (kind === "video" && payload.mode !== "t2v") {
    const sources = aiStudioShotSources(episode, index);
    try {
      const frames = await aiStudioEpisodeFrames(episode, index);
      model.aiStudioDraft.first_image = frames.first;
      if (payload.mode === "flf") model.aiStudioDraft.last_image = frames.last;
    } catch {
      model.aiStudioDraft.first_image = "";
    }
    firstNote = aiStudioShotNeeds(episode, index) || (sources.first?.kind === "tail" ? "首帧已用上一镜的最后一帧。" : "首帧已用片头图 / 底图。")
      + (payload.mode === "flf" && sources.last?.job ? "尾帧已用片头图。" : "");
  }
  model.aiStudioMessage = `已载入「${episode.title}」的${kind === "image" ? "片头图" : aiStudioShotLabel(episode, index)}提示词。${firstNote}`;
  renderPreservingToolboxBodyPosition();
  revealAiStudioCompose();
}

function aiStudioRevealJob(job) {
  if (job.series && aiStudioSeriesById(job.series)) {
    model.aiStudioNav = { series: job.series, group: job.group || "", view: "" };
    model.aiStudioFilter = { kind: "", category: "", format: "", status: "" };
  }
  renderPreservingToolboxBodyPosition();
  const shot = Number(job.shot || 0);
  const key = !job.episode ? "" : job.final ? `${job.episode}:final` : `${job.episode}:${job.kind === "image" ? "image" : "video"}:${shot}`;
  const findTarget = () => (key && (document.querySelector(`[data-ai-studio-target="${CSS.escape(key)}"]`) || document.querySelector(`[data-ai-studio-target-image="${CSS.escape(key)}"]`)))
    || document.querySelector(`[data-ai-studio-active-job="${CSS.escape(job.id)}"]`);
  const reveal = (flash) => {
    const target = findTarget();
    if (!target) return;
    const box = target.getBoundingClientRect();
    if (flash || box.top < 0 || box.bottom > window.innerHeight) target.scrollIntoView({ block: "center" });
    if (!flash && target.classList.contains("ai-studio-flash")) return;
    target.classList.remove("ai-studio-flash");
    void target.offsetWidth;
    target.classList.add("ai-studio-flash");
    setTimeout(() => target.classList.remove("ai-studio-flash"), 2600);
  };
  requestAnimationFrame(() => reveal(true));
  [300, 700, 1300].forEach((delay) => setTimeout(() => reveal(false), delay));
}

async function aiStudioRevealRunningJob() {
  try {
    const payload = await apiJson("/api/tools/ai-studio", { cache: "no-store" });
    if (payload.config) model.aiStudioConfig = payload.config;
    model.aiStudioState = payload;
    if (!model.aiStudioDraft && model.aiStudioConfig) model.aiStudioDraft = aiStudioDraftFromCategory("free");
    model.aiStudioError = "";
  } catch (error) {
    model.aiStudioError = error.message || "无法读取 AI Studio 状态";
  }
  for (let waited = 0; model.aiStudioLoading && waited < 8000; waited += 100) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!aiStudioIsActive()) return;
  const jobs = model.aiStudioState?.jobs || [];
  const job = jobs.find((item) => item.status === "running") || jobs.find((item) => AI_STUDIO_ACTIVE.has(item.status));
  if (!job) {
    model.aiStudioMessage = "AI Studio 里没有正在进行的任务，ComfyUI 当前的任务可能是在 ComfyUI 网页里直接提交的。";
    renderPreservingToolboxBodyPosition();
    return;
  }
  scheduleAiStudioPoll();
  aiStudioRevealJob(job);
}

function aiStudioOpenFolder(series, group = "", view = series === model.aiStudioNav?.series ? model.aiStudioNav?.view || "" : "") {
  model.aiStudioNav = { series, group, view };
  model.aiStudioFilter = { kind: "", category: "", format: "", status: "" };
  syncUrlState("push");
  refreshAiStudioLibraryDom({ force: true });
  document.querySelector(".ai-studio-library")?.scrollIntoView({ block: "start", behavior: "smooth" });
}

async function aiStudioSaveSeries() {
  const editor = model.aiStudioSeriesEditor;
  if (!editor || editor.busy) return;
  editor.busy = true;
  editor.error = "";
  refreshAiStudioLibraryDom({ force: true });
  try {
    const body = {
      name: editor.name, category: editor.category || "", description: editor.description, style: editor.style,
      groups: (editor.groups || []).filter((group) => String(group.name || "").trim()),
    };
    const payload = editor.id
      ? await aiStudioRequest(`/api/tools/ai-studio/series/${encodeURIComponent(editor.id)}`, { method: "PATCH", body })
      : await aiStudioRequest("/api/tools/ai-studio/series", { body });
    model.aiStudioState = payload.state;
    model.aiStudioSeriesEditor = null;
    model.aiStudioNav = { series: payload.series.id, group: "" };
    model.aiStudioMessage = editor.id ? `已保存系列「${payload.series.name}」。` : `已创建系列「${payload.series.name}」，点「在这里创作」开始出片。`;
  } catch (error) {
    editor.busy = false;
    editor.error = error.message || "保存失败";
  }
  renderPreservingToolboxBodyPosition();
}

function aiStudioHandleSeriesClick(target) {
  const data = target.dataset;
  if (data.aiStudioOpenSeries) {
    aiStudioOpenFolder(data.aiStudioOpenSeries);
  } else if (data.aiStudioNavView) {
    aiStudioOpenFolder(model.aiStudioNav?.series || "", model.aiStudioNav?.group || "", data.aiStudioNavView);
  } else if (data.aiStudioEpisodeRun) {
    aiStudioRunEpisode(data.aiStudioEpisodeRun, data.kind, Number(data.shot || 0));
  } else if (data.aiStudioEpisodeLoad) {
    aiStudioLoadEpisode(data.aiStudioEpisodeLoad, data.kind, Number(data.shot || 0));
  } else if (data.aiStudioEpisodeCompose) {
    aiStudioComposeEpisode(data.aiStudioEpisodeCompose);
  } else if (data.aiStudioVoiceRun) {
    aiStudioVoiceAction(data.aiStudioVoiceRun, data.shot === undefined ? {} : { shot: Number(data.shot) }, true);
  } else if (data.aiStudioVoiceEdit) {
    const context = aiStudioEpisodeContext(data.aiStudioVoiceEdit);
    const recap = Number(data.shot) < 0;
    const shot = recap ? (context?.episode?.recap ? { lines: context.episode.recap } : null) : aiStudioEpisodeShots(context?.episode)[Number(data.shot)];
    if (!shot) return true;
    const text = window.prompt(recap ? "承上解说（字幕和配音都用这段文字）：" : "配音读的文字（画面字幕不变）。可以写 <似|SI4> 指定某个字的读音；清空则同朗读文字：", aiStudioVoiceText(shot));
    if (text !== null) aiStudioVoiceAction(data.aiStudioVoiceEdit, { shot: Number(data.shot), text }, false);
  } else if (data.aiStudioVoiceReference) {
    aiStudioVoiceAction(data.aiStudioVoiceReference, { narrator: data.take }, false);
  } else if (data.aiStudioVoiceLipsync) {
    aiStudioVoiceAction(data.aiStudioVoiceLipsync, { shot: Number(data.shot), lipsync: true }, false);
  } else if (data.aiStudioVoiceMusic) {
    aiStudioVoiceAction(data.aiStudioVoiceMusic, { music: data.take }, false);
  } else if (data.aiStudioVoiceDelete) {
    aiStudioJobAction(`/api/tools/ai-studio/voices/${encodeURIComponent(data.aiStudioVoiceDelete)}`, { method: "DELETE" }, "已删除这条配音，合成时回到原片的声音。");
  } else if (data.aiStudioVoiceNarrator !== undefined) {
    const series = aiStudioSeriesById(model.aiStudioNav?.series);
    if (series) aiStudioJobAction(`/api/tools/ai-studio/series/${encodeURIComponent(series.id)}`, { method: "PATCH", body: { narrator: data.aiStudioVoiceNarrator } },
      data.aiStudioVoiceNarrator ? "已设为系列解说音色：序章、承上、承上启下之后都用这个声音；已有的解说配音要重新配才会换。" : "已改回每镜用自己原片的声音。");
  } else if (data.aiStudioPronSave) {
    const pron = document.querySelector("[data-ai-studio-pron]")?.value || "";
    aiStudioJobAction(`/api/tools/ai-studio/series/${encodeURIComponent(data.aiStudioPronSave)}`, { method: "PATCH", body: { pron } },
      "已保存读音表；重新配音后生效。");
  } else if (data.aiStudioNavRoot !== undefined) {
    aiStudioOpenFolder("");
  } else if (data.aiStudioNavGroup !== undefined) {
    aiStudioOpenFolder(model.aiStudioNav?.series || "", data.aiStudioNavGroup);
  } else if (data.aiStudioNewSeries !== undefined) {
    model.aiStudioSeriesEditor = { name: "", description: "", style: "", groups: [{ name: "", note: "" }] };
    refreshAiStudioLibraryDom({ force: true });
  } else if (data.aiStudioEditSeries) {
    const series = aiStudioSeriesById(data.aiStudioEditSeries);
    if (series) model.aiStudioSeriesEditor = JSON.parse(JSON.stringify(series));
    refreshAiStudioLibraryDom({ force: true });
  } else if (data.aiStudioDeleteSeries) {
    const series = aiStudioSeriesById(data.aiStudioDeleteSeries);
    if (!series || !window.confirm(`删除系列「${series.name}」吗？其中的作品和文件都会保留，回到「未归入系列」。`)) return true;
    model.aiStudioNav = { series: "", group: "" };
    aiStudioJobAction(`/api/tools/ai-studio/series/${encodeURIComponent(series.id)}`, { method: "DELETE" }, `已删除系列「${series.name}」。`);
  } else if (data.aiStudioComposeIn !== undefined) {
    const nav = model.aiStudioNav || {};
    const series = aiStudioSeriesById(nav.series);
    if (!series) return true;
    const group = (series.groups || []).find((item) => item.id === nav.group);
    Object.assign(model.aiStudioDraft, { series: series.id, group: group?.id || "", episode: "" });
    model.aiStudioMessage = `左侧新作品会归入「${group ? `${series.name} · ${group.name}` : series.name}」。${series.style ? "可以点「插入系列风格」统一画面。" : ""}`;
    renderPreservingToolboxBodyPosition();
    revealAiStudioCompose();
  } else if (data.aiStudioGroupAdd !== undefined) {
    model.aiStudioSeriesEditor.groups = [...(model.aiStudioSeriesEditor.groups || []), { name: "", note: "" }];
    refreshAiStudioLibraryDom({ force: true });
  } else if (data.aiStudioGroupRemove !== undefined) {
    model.aiStudioSeriesEditor.groups.splice(Number(data.aiStudioGroupRemove), 1);
    refreshAiStudioLibraryDom({ force: true });
  } else if (data.aiStudioSeriesCancel !== undefined) {
    model.aiStudioSeriesEditor = null;
    refreshAiStudioLibraryDom({ force: true });
  } else if (data.aiStudioSeriesSave !== undefined) {
    aiStudioSaveSeries();
  } else {
    return false;
  }
  return true;
}

function bindToolboxAiStudioEvents() {
  const panel = document.querySelector("[data-ai-studio-panel]");
  if (!panel) return;
  panel.querySelector("[data-ai-studio-refresh]")?.addEventListener("click", () => {
    model.aiStudioMessage = "";
    loadAiStudio();
  });
  bindAiStudioSplitter(panel);
  panel.querySelectorAll("[data-ai-studio-zh-ref]").forEach((node) => { node.hidden = !node.innerHTML.trim(); });
  aiStudioZhRefSync();
  panel.querySelector("[data-ai-studio-zh-ref-toggle]")?.addEventListener("click", () => {
    setAiStudioZhRef(!model.aiStudioZhRef?.on);
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelector("[data-ai-studio-zh-switch-template]")?.addEventListener("click", () => {
    const draft = model.aiStudioDraft;
    if (!window.confirm("改用中文模板会替换当前英文提示词，继续吗？")) return;
    try {
      localStorage.setItem(AI_STUDIO_PROMPT_LANG_KEY, "zh");
    } catch {}
    const fresh = aiStudioDraftFromCategory(draft.category, { ...draft, lang: "zh" });
    model.aiStudioDraft = { ...draft, lang: fresh.lang, sections: fresh.sections, free_text: fresh.free_text, dirty: false };
    setAiStudioZhRef(false);
    model.aiStudioLint = null;
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelector("[data-ai-studio-compose-toggle]")?.addEventListener("click", () => {
    setAiStudioComposeCollapsed(!model.aiStudioComposeCollapsed);
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelectorAll("[data-ai-studio-input]").forEach((input) => {
    input.addEventListener("input", () => {
      model.aiStudioDraft[input.dataset.aiStudioInput] = input.value;
      model.aiStudioDraft.dirty = true;
    });
  });
  panel.querySelectorAll("[data-ai-studio-check]").forEach((input) => {
    input.addEventListener("change", () => {
      model.aiStudioDraft[input.dataset.aiStudioCheck] = input.checked;
      model.aiStudioDraft.dirty = true;
    });
  });
  panel.querySelectorAll("[data-ai-studio-section]").forEach((input) => {
    input.addEventListener("input", () => {
      model.aiStudioDraft.sections = { ...(model.aiStudioDraft.sections || {}), [input.dataset.aiStudioSection]: input.value };
      model.aiStudioDraft.dirty = true;
    });
  });
  panel.querySelectorAll("[data-ai-studio-kind]").forEach((button) => {
    button.addEventListener("click", () => {
      aiStudioSwitchKind(button.dataset.aiStudioKind);
      renderPreservingToolboxBodyPosition();
    });
  });
  panel.querySelectorAll("[data-ai-studio-set]").forEach((button) => {
    button.addEventListener("click", () => {
      const draft = model.aiStudioDraft;
      if (button.dataset.aiStudioSet === "lang") {
        if (draft.lang === button.dataset.value) return;
        if (button.dataset.value === "zh" && draft.dirty && aiStudioZhRefKeys().some((key) => /[A-Za-z]{3}/.test(aiStudioZhRefSource(key)))) {
          setAiStudioZhRef(true);
          renderPreservingToolboxBodyPosition();
          return;
        }
        try {
          localStorage.setItem(AI_STUDIO_PROMPT_LANG_KEY, button.dataset.value);
        } catch {}
        const fresh = aiStudioDraftFromCategory(draft.category, { ...draft, lang: button.dataset.value });
        const replace = !draft.dirty || window.confirm("切换语言会用对应语言的模板替换当前提示词，继续吗？\n选“取消”则只切换语言，保留现在的内容。");
        model.aiStudioDraft = replace
          ? { ...draft, lang: fresh.lang, sections: fresh.sections, free_text: fresh.free_text, dirty: false }
          : { ...draft, lang: fresh.lang };
        model.aiStudioLint = null;
        renderPreservingToolboxBodyPosition();
        return;
      }
      draft[button.dataset.aiStudioSet] = button.dataset.value;
      if (button.dataset.aiStudioSet === "style") model.aiStudioLint = null;
      if (button.dataset.aiStudioSet === "mode" && draft.kind === "image") {
        if (draft.mode === "edit" && draft.ref1_image) draft.format = "auto";
        if (draft.mode !== "edit" && draft.format === "auto") draft.format = aiStudioCategory(draft.category)?.format || "square";
      }
      renderPreservingToolboxBodyPosition();
    });
  });
  panel.querySelectorAll("[data-ai-studio-category]").forEach((button) => {
    button.addEventListener("click", () => {
      const draft = model.aiStudioDraft || {};
      if (draft.category === button.dataset.aiStudioCategory) return;
      if (draft.dirty && !window.confirm("切换类别会用新类别的模板替换当前提示词，继续吗？")) return;
      model.aiStudioDraft = aiStudioDraftFromCategory(button.dataset.aiStudioCategory, draft);
      model.aiStudioLint = null;
      renderPreservingToolboxBodyPosition();
    });
  });
  panel.querySelector("[data-ai-studio-template]")?.addEventListener("click", () => {
    const draft = model.aiStudioDraft || {};
    const origin = draft.origin || aiStudioDraftFromCategory(draft.category, draft).origin;
    const changed = draft.style !== origin.style || draft.lang !== origin.lang || (draft.free_text || "") !== origin.free_text
      || JSON.stringify(draft.sections || {}) !== JSON.stringify(origin.sections);
    if (changed && !window.confirm("放弃对提示词的改动，复原到载入时的样子吗？")) return;
    model.aiStudioDraft = { ...draft, style: origin.style, lang: origin.lang, sections: { ...origin.sections }, free_text: origin.free_text, dirty: origin.dirty };
    model.aiStudioLint = null;
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelectorAll("[data-ai-studio-image]").forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (!file) return;
      if (file.size > 15 * 1024 * 1024) {
        model.aiStudioFormError = "图片不能超过 15 MB";
        renderPreservingToolboxBodyPosition();
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const draft = model.aiStudioDraft;
        draft[`${input.dataset.aiStudioImage}_image`] = String(reader.result || "");
        if (input.dataset.aiStudioImage === "ref1" && draft.kind === "image" && draft.mode === "edit") draft.format = "auto";
        model.aiStudioFormError = "";
        renderPreservingToolboxBodyPosition();
      };
      reader.readAsDataURL(file);
    });
  });
  panel.querySelectorAll("[data-ai-studio-image-clear]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const draft = model.aiStudioDraft;
      draft[`${button.dataset.aiStudioImageClear}_image`] = "";
      if (/^ref\d$/.test(button.dataset.aiStudioImageClear)) {
        const refs = [];
        for (let index = 1; index <= AI_STUDIO_MAX_REFS; index += 1) if (draft[`ref${index}_image`]) refs.push(draft[`ref${index}_image`]);
        for (let index = 1; index <= AI_STUDIO_MAX_REFS; index += 1) draft[`ref${index}_image`] = refs[index - 1] || "";
      }
      renderPreservingToolboxBodyPosition();
    });
  });
  panel.querySelector("[data-ai-studio-placement]")?.addEventListener("change", (event) => {
    const [series = "", group = ""] = String(event.target.value || "").split("|");
    Object.assign(model.aiStudioDraft, { series, group, episode: "" });
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelector("[data-ai-studio-insert-style]")?.addEventListener("click", () => {
    const draft = model.aiStudioDraft;
    const style = String(aiStudioSeriesById(draft.series)?.style || "").trim();
    if (!style) return;
    const append = (text) => (String(text || "").includes(style) ? String(text || "") : `${String(text || "").trim()}\n\n${style}`.trim());
    if (draft.kind === "image" || draft.style === "free") draft.free_text = append(draft.free_text);
    else draft.sections = { ...(draft.sections || {}), retention_analysis: append(draft.sections?.retention_analysis) };
    draft.dirty = true;
    model.aiStudioLint = null;
    renderPreservingToolboxBodyPosition();
  });
  panel.querySelector("[data-ai-studio-lint]")?.addEventListener("click", aiStudioLintDraft);
  panel.querySelectorAll("[data-ai-studio-submit]").forEach((button) => {
    button.addEventListener("click", () => aiStudioSubmit(button.dataset.force === "1"));
  });
  const library = panel.querySelector(".ai-studio-library");
  library?.addEventListener("input", (event) => {
    const editor = model.aiStudioSeriesEditor;
    const input = event.target;
    if (!editor || !(input instanceof HTMLElement)) return;
    if (input.dataset.aiStudioSeriesField) editor[input.dataset.aiStudioSeriesField] = input.value;
    if (input.dataset.aiStudioGroupField) {
      const group = editor.groups[Number(input.dataset.index)];
      if (group) group[input.dataset.aiStudioGroupField] = input.value;
    }
  });
  library?.addEventListener("change", (event) => {
    const select = event.target;
    if (!(select instanceof HTMLSelectElement) || !select.dataset.aiStudioMove) return;
    const [series = "", group = ""] = select.value.split("|");
    const job = (model.aiStudioState?.jobs || []).find((item) => item.id === select.dataset.aiStudioMove);
    aiStudioJobAction(`/api/tools/ai-studio/jobs/${encodeURIComponent(select.dataset.aiStudioMove)}`, { method: "PATCH", body: { series, group } },
      `已把「${job?.title || ""}」移到「${aiStudioPlacementLabel({ series, group }) || "未归入系列"}」。`);
  });
  library?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button") : null;
    if (!target) return;
    if (aiStudioHandleSeriesClick(target)) return;
    if (target.dataset.aiStudioFilter) {
      model.aiStudioFilter = { ...(model.aiStudioFilter || {}), [target.dataset.aiStudioFilter]: target.dataset.value || "" };
      if (target.dataset.aiStudioFilter === "kind") model.aiStudioFilter.category = "";
      refreshAiStudioLibraryDom({ force: true });
    } else if (target.dataset.aiStudioUseFirst) {
      aiStudioUseImage(target.dataset.aiStudioUseFirst, "first");
    } else if (target.dataset.aiStudioUseRef) {
      aiStudioUseImage(target.dataset.aiStudioUseRef, "ref");
    } else if (target.dataset.aiStudioCancel) {
      if (!window.confirm("取消这条任务吗？正在生成的部分会被中断。")) return;
      aiStudioJobAction(`/api/tools/ai-studio/jobs/${encodeURIComponent(target.dataset.aiStudioCancel)}/cancel`, {}, "已取消。");
    } else if (target.dataset.aiStudioRerun) {
      aiStudioJobAction(`/api/tools/ai-studio/jobs/${encodeURIComponent(target.dataset.aiStudioRerun)}/rerun`, { body: { new_seed: target.dataset.newSeed === "1" } }, "已换 seed 重新提交。");
    } else if (target.dataset.aiStudioRate !== undefined) {
      aiStudioJobAction(`/api/tools/ai-studio/jobs/${encodeURIComponent(target.dataset.aiStudioRate)}`, { method: "PATCH", body: { rating: target.dataset.rating || "" } });
    } else if (target.dataset.aiStudioEdit) {
      aiStudioLoadJobIntoDraft(target.dataset.aiStudioEdit);
    } else if (target.dataset.aiStudioDelete) {
      if (!window.confirm("删除这条记录和它的成片文件吗？")) return;
      aiStudioJobAction(`/api/tools/ai-studio/jobs/${encodeURIComponent(target.dataset.aiStudioDelete)}`, { method: "DELETE" }, "已删除。");
    }
  });
}

window.addEventListener("popstate", () => {
  model.aiStudioNav = aiStudioNavFromUrl();
  render();
});
render();
