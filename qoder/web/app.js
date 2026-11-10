/* 读伴前端：原生 JS，无构建步骤，所有数据来自 /api/*。 */

const S = { state: null, busy: false, modal: null };

const $ = (id) => document.getElementById(id);
const esc = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => (node.hidden = true), 2200);
}

/* --------------------------------------------------------------- 渲染状态 */

function renderState(state) {
  S.state = state;
  const stats = state.stats;
  $("stats").innerHTML = [
    [stats.documents, "资料"],
    [stats.chunks, "片段"],
    [stats.weak, "薄弱点"],
  ]
    .map(([value, label]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`)
    .join("");
  $("scope").textContent = `scope · ${state.scope}`;
  $("corpus-hint").textContent = `${stats.documents} 篇 · ${stats.turns} 次问答`;

  $("doc-list").innerHTML = state.documents
    .map((doc) => {
      const ratio = doc.progress ? Math.round(doc.progress.ratio * 100) : 0;
      const unit = doc.page_count ? `${doc.page_count} 页` : `${doc.chunk_count} 段`;
      return `<li data-doc="${esc(doc.doc_id)}" data-path="${esc(doc.path)}" data-page="${doc.progress ? doc.progress.page : 1}">
        <span class="name">${esc(doc.title)}</span>
        <span class="meta">${unit} · ${doc.progress ? `读到 ${ratio}%` : "未开始"}</span>
        <span class="bar"><i style="width:${ratio}%"></i></span>
      </li>`;
    })
    .join("");

  $("review-list").innerHTML = state.review.length
    ? state.review
        .map(
          (item, index) => `<li data-review="${index}">
            <div class="kind">${labelOf(item.kind)}</div>
            <div class="r-title">${esc(item.title)}</div>
            <div class="r-detail">${esc(item.detail)}</div>
          </li>`
        )
        .join("")
    : `<li class="muted">读几页、标几个薄弱点，这里就有内容了</li>`;

  const memory = state.memory;
  $("weak-list").innerHTML = memory.weak.length
    ? memory.weak
        .map(
          (item) => `<li><span>${esc(item.term)} <span class="muted">×${item.count}</span></span>
            <button data-unmark="${esc(item.term)}" title="划掉">×</button></li>`
        )
        .join("")
    : `<li class="muted">还没有标记</li>`;
  $("last-turn").textContent = memory.turns.length
    ? `「${memory.turns[memory.turns.length - 1].question}」`
    : "—";
  const ids = (memory.artifact_ids || []).slice(-3);
  $("artifacts").textContent = ids.length ? ids.join("\n") : "—";

  const depth = memory.profile.depth || "standard";
  document.querySelectorAll("#depth button").forEach((button) => {
    button.classList.toggle("on", button.dataset.depth === depth);
  });
}

const labelOf = (kind) => ({ weak: "薄弱点", unfinished: "没读完", unread: "未开始" }[kind] || kind);

/* ------------------------------------------------------------------- 问答 */

function renderTurn(payload) {
  const answer = payload.answer;
  const bullets = answer.bullets
    .map(
      (bullet, index) => `<li>
        <span class="idx">${index + 1}</span>
        <span class="text">${esc(bullet.text)}
          <button class="cite" data-cite="${esc(bullet.citation)}" style="margin-left:6px">
            <b>${esc(shortCitation(bullet.citation))}</b>
          </button>
        </span>
      </li>`
    )
    .join("");

  const cites = answer.citations
    .map(
      (cite) => `<button class="cite" data-cite="${esc(cite.citation)}">
        <b>${esc(shortCitation(cite.citation))}</b>
        <span class="src">${esc(cite.doc_title)}</span>
      </button>`
    )
    .join("");

  const primer = answer.primer
    ? `<div class="primer"><b>先补一条基础说明</b>（来自你的薄弱点）<br />
        ${esc(answer.primer.snippet)}
        <br /><button class="cite" data-cite="${esc(answer.primer.citation)}">${esc(shortCitation(answer.primer.citation))}</button>
      </div>`
    : "";

  const followups = answer.followups
    .map((idea) => `<button class="chip" data-ask="${esc(idea)}">${esc(idea)}</button>`)
    .join("");

  const stats = answer.stats || {};
  const variants = Object.entries(stats.variants || {})
    .map(([name, count]) => `${name} ${count}`)
    .join(" / ");

  const html = `<div class="turn">
    <div class="q-row"><div class="q">${esc(answer.question)}</div></div>
    <div class="card">
      <h4>回答 · ${esc(answer.mode)}</h4>
      <p class="headline">${esc(answer.headline)}</p>
      ${answer.memory_note ? `<div class="mem-note">${esc(answer.memory_note)}</div>` : ""}
      <ul class="bullets">${bullets || `<li class="muted">没有可引用的句子</li>`}</ul>
      ${cites ? `<div class="cites">${cites}</div>` : ""}
      ${primer}
      <div class="followups">${followups}</div>
      <div class="stats-line">
        <span>候选 ${stats.candidates ?? 0} → 引用 ${stats.hits ?? 0}</span>
        <span>词项：${esc((stats.terms || []).slice(0, 8).join(" · "))}</span>
        <span>召回：${esc(variants)}</span>
      </div>
    </div>
  </div>`;
  const thread = $("thread");
  const empty = $("empty");
  if (empty) empty.remove();
  thread.insertAdjacentHTML("beforeend", html);
  thread.scrollTop = thread.scrollHeight;
}

const shortCitation = (citation) => {
  const [path, anchor] = String(citation).split("#");
  const name = path.split("/").pop();
  return `${name}#${anchor}`;
};

async function ask(question) {
  if (!question.trim() || S.busy) return;
  S.busy = true;
  $("send").disabled = true;
  const thread = $("thread");
  const pending = document.createElement("div");
  pending.className = "turn";
  pending.innerHTML = `<div class="q-row"><div class="q">${esc(question)}</div></div>
    <div class="card"><span class="muted">检索中…</span></div>`;
  thread.appendChild(pending);
  thread.scrollTop = thread.scrollHeight;
  try {
    const payload = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
    pending.remove();
    renderTurn(payload);
    $("question").value = "";
    const state = await api("/api/state");
    renderState(state);
  } catch (error) {
    pending.remove();
    toast(`出错：${error.message}`);
  } finally {
    S.busy = false;
    $("send").disabled = false;
  }
}

/* ------------------------------------------------------------------- 原文 */

async function openCitation(citation) {
  const [path, anchor] = String(citation).split("#");
  const docId = path.replace(/\.(pdf|md|txt)$/i, "");
  const payload = await api(`/api/resolve?doc_id=${encodeURIComponent(docId)}&anchor=${encodeURIComponent(anchor)}`);
  S.modal = { citation, docId, anchor, payload };
  $("modal-title").textContent = shortCitation(citation);
  $("modal-sub").textContent = payload.location || "";
  $("modal-body").textContent = payload.body || "（原文为空）";
  $("modal").hidden = false;
}

/* ------------------------------------------------------------------- 事件 */

function bind() {
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    ask($("question").value);
  });

  $("thread").addEventListener("click", (event) => {
    const cite = event.target.closest("[data-cite]");
    if (cite) return void openCitation(cite.dataset.cite).catch((error) => toast(error.message));
    const chip = event.target.closest("[data-ask]");
    if (chip) return void ask(chip.dataset.ask);
  });

  $("doc-list").addEventListener("click", (event) => {
    const item = event.target.closest("li[data-doc]");
    if (!item) return;
    const doc = (S.state?.documents || []).find((d) => d.doc_id === item.dataset.doc);
    const anchor = doc && doc.page_count ? `p${item.dataset.page}` : "";
    void openCitation(`${item.dataset.path}#${anchor}`).catch((error) => toast(error.message));
  });

  $("review-list").addEventListener("click", (event) => {
    const item = event.target.closest("li[data-review]");
    if (!item || !S.state) return;
    const entry = S.state.review[Number(item.dataset.review)];
    if (!entry) return;
    if (entry.action.type === "ask") return void ask(entry.action.question);
    if (entry.action.type === "open") {
      const doc = S.state.documents.find((d) => d.doc_id === entry.action.doc_id);
      const anchor = doc && doc.page_count ? `p${entry.action.page || 1}` : "";
      void openCitation(`${doc ? doc.path : entry.action.doc_id}#${anchor}`).catch((error) => toast(error.message));
    }
  });

  $("weak-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-unmark]");
    if (!button) return;
    const state = await api("/api/unmark", { method: "POST", body: JSON.stringify({ term: button.dataset.unmark }) });
    renderState(state);
    toast(`已划掉：${button.dataset.unmark}`);
  });

  document.querySelectorAll("#depth button").forEach((button) => {
    button.addEventListener("click", async () => {
      const state = await api("/api/profile", { method: "POST", body: JSON.stringify({ depth: button.dataset.depth }) });
      renderState(state);
      toast(`解释深度：${button.textContent}`);
    });
  });

  $("modal-close").addEventListener("click", () => ($("modal").hidden = true));
  $("modal").addEventListener("click", (event) => {
    if (event.target.id === "modal") $("modal").hidden = true;
  });

  $("mark-weak").addEventListener("click", async () => {
    if (!S.modal) return;
    const term = S.modal.payload.section || S.modal.docId;
    const state = await api("/api/mark", {
      method: "POST",
      body: JSON.stringify({ term, note: `来自 ${S.modal.citation}`, source: S.modal.citation }),
    });
    renderState(state);
    $("modal").hidden = true;
    toast(`已记下薄弱点：${term}`);
  });

  $("mark-read").addEventListener("click", async () => {
    if (!S.modal) return;
    const doc = (S.state?.documents || []).find((d) => d.doc_id === S.modal.docId);
    const page = S.modal.payload.page || 1;
    const total = doc?.page_count || 1;
    await api("/api/progress", {
      method: "POST",
      body: JSON.stringify({ doc_id: S.modal.docId, page, anchor: S.modal.anchor, ratio: Math.min(1, page / total) }),
    });
    const state = await api("/api/state");
    renderState(state);
    $("modal").hidden = true;
    toast(`已记录：${doc?.title || S.modal.docId} 第 ${page} 页`);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("modal").hidden = true;
  });
}

const docSuffix = (docId) => (/^papers\//.test(docId) ? ".pdf" : ".md");
async function boot() {
  bind();
  const view = new URLSearchParams(location.search).get("view");
  if (view) document.body.dataset.view = view;
  const preloaded = window.__PRELOAD__;
  if (preloaded) {
    try {
      renderState(preloaded.state);
      if (preloaded.answer) renderTurn(preloaded.answer);
      prepareSeeds();
      return;
    } catch (error) {
      console.warn("preload failed, falling back", error);
    }
  }
  try {
    const state = await api("/api/state");
    renderState(state);
    prepareSeeds();
    const seed = new URLSearchParams(location.search).get("q");
    if (seed) ask(seed);
  } catch (error) {
    toast(`无法加载状态：${error.message}`);
  }
}

function prepareSeeds() {
  const seeds = ["Raft 的 Figure 8 说明了什么问题？", "Dynamo 为什么不用时间戳判断数据新旧？", "CAP 定理到底限制了什么？"];
  $("seed-chips").innerHTML = seeds.map((text) => `<button class="chip" data-ask="${esc(text)}">${esc(text)}</button>`).join("");
  $("seed-chips").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-ask]");
    if (chip) ask(chip.dataset.ask);
  });
}

boot();
