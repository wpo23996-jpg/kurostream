/* ================================================================ KuroStream
 * 单页应用：hash 路由 + 原生组件（无框架）
 *   #/                    首页（频道行）
 *   #/c/{channel}         频道网格
 *   #/s/{query}           搜索结果
 *   #/v/{channel}/{id}    详情与播放
 *   #/saved               我的收藏
 *   #/terms #/privacy #/about
 * ======================================================================== */

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

/* 网页版为空（同源）；iOS / Android 外壳里由构建时的 __KS_CONFIG__ 注入服务器地址；
   装到手机后也可以在 App 内「连点 logo 5 次」现场改，存进 localStorage，优先级最高。 */
const CONFIG_BASE = ((window.__KS_CONFIG__ && window.__KS_CONFIG__.apiBase) || "").replace(/\/+$/, "");
const LOCAL_BASE = (localStorage.getItem("ks_api_base") || "").replace(/\/+$/, "");
const API_BASE = LOCAL_BASE || CONFIG_BASE;
const apiUrl = (p) => (p && (p.startsWith("http") || p.startsWith("data:")) ? p : API_BASE + p);

const uid =
  localStorage.getItem("ks_uid") ||
  (crypto.randomUUID ? crypto.randomUUID() : "u" + Date.now().toString(36) + Math.random().toString(36).slice(2));
localStorage.setItem("ks_uid", uid);

/* 店主令牌：填了就不会计入免费额度、不会被限制画质 */
let ADMIN_TOKEN = localStorage.getItem("ks_admin") || "";

const state = {
  channels: [],
  site: "KuroStream",
  tagline: "高清片库 · 极速播放",
  tier: "free",
  member: null,
  players: [],
  keyHandlers: [],
  reqToken: 0,
};

/* ------------------------------------------------------------------- utils */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

async function api(path, opts = {}) {
  const headers = { "X-KS-UID": uid, ...(opts.headers || {}) };
  if (ADMIN_TOKEN) headers["X-Admin-Token"] = ADMIN_TOKEN;
  const resp = await fetch(apiUrl(path), { ...opts, headers });
  if (!resp.ok) {
    let msg = resp.statusText;
    try {
      const j = await resp.json();
      msg = typeof j.detail === "object" ? j.detail.message || JSON.stringify(j.detail) : j.detail || msg;
    } catch (_) {}
    const err = new Error(msg);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

function fmtDuration(s) {
  return s || "";
}

/* ------------------------------------------------------------------- cards */
function cardEl(item, opts = {}) {
  const a = el("a", "card");
  a.href = `#/v/${encodeURIComponent(item.provider)}/${encodeURIComponent(item.id)}`;
  a.dataset.key = `${item.provider}:${item.id}`;

  const thumb = el("div", "thumb");
  if (item.cover_proxy) {
    const img = el("img");
    img.loading = "lazy";
    img.alt = item.title || "";
    img.onload = () => img.classList.add("loaded");
    img.onerror = () => img.remove();
    img.src = apiUrl(item.cover_proxy);
    thumb.append(img);
  }
  if (item.duration) thumb.append(el("span", "dur", esc(item.duration)));
  if (opts.showChannel !== false) {
    const ch = state.channels.find((c) => c.key === item.provider);
    if (ch) thumb.append(el("span", "chan", esc(ch.label)));
  }

  const body = el("div", "card-title", esc(item.title || item.id));
  a.append(thumb, body);

  if (item.badges && item.badges.length) {
    const b = el("div", "badges");
    item.badges.forEach((t) => b.append(el("span", null, esc(t))));
    a.append(b);
  }
  return a;
}

function skeletonRow() {
  const row = el("div", "row sk-row");
  for (let i = 0; i < 6; i++) {
    const c = el("div", "sk sk-card");
    c.append(el("div", "sk sk-thumb"), el("div", "sk sk-line"), el("div", "sk sk-line short"));
    row.append(c);
  }
  return row;
}

function skeletonPage() {
  const frag = document.createDocumentFragment();
  for (let r = 0; r < 3; r++) {
    frag.append(el("div", "sk sk-head"));
    frag.append(skeletonRow());
  }
  return frag;
}

function emptyState(title, sub = "") {
  return el("div", "empty", `<div class="big">◍</div><div>${esc(title)}</div>${sub ? `<div style="margin-top:6px;font-size:12px;color:var(--fg-mute)">${esc(sub)}</div>` : ""}`);
}

function errorState(msg) {
  return el("div", "error-box", `加载失败：${esc(msg)}<div style="margin-top:10px"><button class="qbtn" onclick="location.reload()">重试</button></div>`);
}

/* ------------------------------------------------------------------- chips */
function renderChannels(active) {
  const nav = $("#channels");
  nav.innerHTML = "";
  const all = el("a", "chip" + (active === "all" ? " active" : ""), "全部");
  all.href = "#/";
  nav.append(all);
  for (const c of state.channels) {
    const a = el("a", "chip" + (active === c.key ? " active" : ""), esc(c.label));
    a.href = `#/c/${encodeURIComponent(c.key)}`;
    if (c.blurb) a.title = c.blurb;
    nav.append(a);
  }
}

/* ------------------------------------------------------------------ router */
function parseHash() {
  const raw = (location.hash || "#/").replace(/^#/, "");
  const [path, queryStr] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = new URLSearchParams(queryStr || "");
  return { parts, query };
}

async function router() {
  destroyPlayers();
  const token = ++state.reqToken;
  const { parts, query } = parseHash();
  const app = $("#app");

  const root = parts[0] || "";

  if (!root) {
    renderChannels("all");
    return viewHome(app, token);
  }
  if (root === "c" && parts[1]) {
    renderChannels(parts[1]);
    return viewChannel(app, parts[1], token);
  }
  if (root === "s" && parts[1]) {
    renderChannels("");
    return viewSearch(app, parts[1], token);
  }
  if (root === "v" && parts[1] && parts[2]) {
    renderChannels("");
    return viewDetail(app, parts[1], parts[2], token);
  }
  if (root === "saved") {
    renderChannels("");
    return viewSaved(app);
  }
  if (["terms", "privacy", "about"].includes(root)) {
    renderChannels("");
    return viewLegal(app, root);
  }
  app.replaceChildren(emptyState("页面不存在", "返回首页看看吧"));
}

/* -------------------------------------------------------------------- home */
async function viewHome(app, token) {
  app.replaceChildren(skeletonPage());

  const playable = state.channels.filter((c) => c.kinds.includes("media"));
  const meta = state.channels.filter((c) => !c.kinds.includes("media"));
  const order = [...playable, ...meta];

  const container = el("div");
  app.replaceChildren(container);

  // 逐行渲染：哪个频道先返回先显示，不互相等待
  order.forEach((ch) => {
    const section = el("section", "row");
    const head = el("div", "row-head");
    head.append(
      el("h2", "row-title", esc(ch.label)),
      el("a", "row-more", "查看全部 →")
    );
    head.querySelector("a").href = `#/c/${encodeURIComponent(ch.key)}`;
    const track = el("div", "row-track");
    for (let i = 0; i < 5; i++) track.append(skeletonRow().children[0].cloneNode(true));
    section.append(head, track);
    container.append(section);

    api(`/api/browse?provider=${encodeURIComponent(ch.key)}&limit=14&sort=new`)
      .then((data) => {
        if (token !== state.reqToken) return;
        const g = data.groups[0];
        track.innerHTML = "";
        if (!g.items.length) {
          section.remove();
          return;
        }
        g.items.forEach((it) => track.append(cardEl(it, { showChannel: false })));
        if (g.error) head.append(el("span", "qbtn", "该频道暂不可用"));
        head.querySelector("h2").innerHTML =
          `${esc(ch.label)} <small>${g.items.length} 部</small>`;
      })
      .catch(() => {
        if (token === state.reqToken) section.remove();
      });
  });
}

/* ----------------------------------------------------------------- channel */
async function viewChannel(app, key, token) {
  const ch = state.channels.find((c) => c.key === key);
  const title = ch ? ch.label : key;
  const head = el("div", "page-head", `<h1>${esc(title)}</h1><p>${esc(ch ? ch.blurb : "")}</p>`);
  const toolbar = el("div", "toolbar");
  ["new:最新", "trending:热门", "chinese:中文字幕"].forEach((pair) => {
    const [k, label] = pair.split(":");
    const b = el("button", "sort-btn" + (state.sort === k ? " active" : ""), label);
    b.onclick = () => {
      state.sort = k;
      $$(".sort-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      load(1);
    };
    toolbar.append(b);
  });
  const grid = el("div", "grid");
  const foot = el("div", "section");
  app.replaceChildren(head, toolbar, grid, foot);

  let page = 1;
  let loading = false;
  let done = false;
  const seen = new Set();

  async function load(p) {
    if (loading || done) return;
    loading = true;
    if (p === 1) {
      seen.clear();
      grid.replaceChildren(...Array.from({ length: 8 }, () => {
        const c = el("div", "sk sk-card");
        c.append(el("div", "sk sk-thumb"), el("div", "sk sk-line"));
        return c;
      }));
    }
    try {
      const data = await api(
        `/api/browse?provider=${encodeURIComponent(key)}&page=${p}&sort=${state.sort}&limit=48`
      );
      if (token !== state.reqToken) return;
      const g = data.groups[0];
      if (p === 1) grid.innerHTML = "";
      if (g.error && !g.items.length) {
        grid.replaceChildren(errorState(g.error));
        done = true;
        return;
      }
      let added = 0;
      g.items.forEach((it) => {
        const k = `${it.provider}:${it.id}`;
        if (seen.has(k)) return;
        seen.add(k);
        grid.append(cardEl(it, { showChannel: false }));
        added++;
      });
      page = p;

      const exhausted = !g.items.length || added === 0 || p >= (g.total_pages || 1);
      if (p === 1 && added === 0) {
        grid.replaceChildren(emptyState("这个频道暂时没有内容"));
        done = true;
        foot.innerHTML = "";
        return;
      }
      const more = el("button", "load-more", exhausted ? "已经到底了" : "加载更多");
      more.disabled = exhausted;
      more.onclick = () => load(p + 1);
      foot.innerHTML = "";
      foot.append(more);
      if (exhausted) done = true;
    } catch (err) {
      if (token === state.reqToken) grid.replaceChildren(errorState(err.message));
    } finally {
      loading = false;
    }
  }

  await load(1);
}

/* ------------------------------------------------------------------ search */
async function viewSearch(app, query, token) {
  const head = el("div", "page-head", `<h1>搜索「${esc(query)}」</h1><p>正在检索全部频道…</p>`);
  const wrap = el("div");
  app.replaceChildren(head, wrap);

  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    if (token !== state.reqToken) return;
    wrap.innerHTML = "";
    let total = 0;
    let shown = 0;

    data.groups.forEach((g) => {
      if (!g.items.length) return;
      total += g.items.length;
      shown++;
      const sec = el("section", "row");
      const h = el("div", "row-head");
      h.append(el("h2", "row-title", `${esc(g.label)} <small>${g.items.length} 条</small>`));
      const more = el("a", "row-more", "进入频道 →");
      more.href = `#/c/${encodeURIComponent(g.provider)}`;
      h.append(more);
      const grid = el("div", "grid");
      g.items.forEach((it) => grid.append(cardEl(it, { showChannel: false })));
      sec.append(h, grid);
      wrap.append(sec);
    });

    head.querySelector("p").textContent = total
      ? `在 ${shown} 个频道中找到 ${total} 条结果`
      : "没有找到相关结果";
    if (!total) wrap.append(emptyState("换个关键词试试", "可以试试番号、演员名或题材"));
  } catch (err) {
    wrap.replaceChildren(errorState(err.message));
  }
}

/* ------------------------------------------------------------------ detail */
async function viewDetail(app, provider, id, token) {
  app.replaceChildren(el("div", "detail", '<div class="sk sk-head" style="margin:20px 0"></div><div class="sk" style="aspect-ratio:16/9;width:100%"></div>'));

  let data;
  try {
    data = await api(`/api/detail?provider=${encodeURIComponent(provider)}&id=${encodeURIComponent(id)}`);
  } catch (err) {
    if (err.status === 402) {
      app.replaceChildren(
        el("div", "empty", `
          <div class="big">🔒</div>
          <div>${esc(err.message)}</div>
          <div style="margin-top:16px"><button class="load-more" id="go-vip">开通会员，无限观看</button></div>`)
      );
      $("#go-vip").onclick = openPricing;
      return;
    }
    app.replaceChildren(el("div", "detail", errorState(err.message).outerHTML));
    return;
  }
  if (token !== state.reqToken) return;

  const item = data.item;
  const root = el("div", "detail");

  /* --- 播放器 --- */
  const shell = el("div", "player-shell");
  const video = el("video");
  video.id = "player";
  video.controls = true;
  video.playsInline = true;
  video.preload = "metadata";
  video.crossOrigin = "anonymous";
  if (item.cover_proxy) video.poster = apiUrl(item.cover_proxy);
  const msg = el("div", "player-msg");
  shell.append(video, msg);
  root.append(shell);

  /* --- 画质 --- */
  const qrow = el("div", "quality-row");
  const media = (data.media || []).filter((m) => m.play);
  if (!media.length) {
    msg.textContent = "该片暂未接入在线播放";
    msg.classList.add("show");
  } else {
    media.forEach((m, i) => {
      const b = el("button", "qbtn" + (i === 0 ? " active" : ""), esc(m.quality && m.quality !== "auto" ? m.quality : m.label || m.kind.toUpperCase()));
      b.onclick = () => {
        $$(".qbtn", qrow).forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        play(media[i], item);
      };
      qrow.append(b);
    });
    if (data.tier === "free") {
      qrow.append(el("span", "qhint", `游客画质上限 ${data.max_height}p`));
      const up = el("button", "qbtn", "解锁 1080p");
      up.onclick = openPricing;
      qrow.append(up);
    }
  }
  root.append(qrow);

  /* --- 信息 --- */
  const info = el("div", "info");
  info.append(el("h1", null, esc(item.title || item.id)));

  const meta = el("div", "info-meta");
  const bits = [`频道：<b>${esc(data.provider_label || provider)}</b>`];
  if (data.date) bits.push(`发行：<b>${esc(data.date)}</b>`);
  if (data.duration) bits.push(`时长：<b>${esc(data.duration)}</b>`);
  if (data.maker) bits.push(`片商：<b>${esc(data.maker)}</b>`);
  bits.push(`编号：<b>${esc(item.id)}</b>`);
  meta.innerHTML = bits.map((b) => `<span>${b}</span>`).join("");
  info.append(meta);

  const tags = [...(data.actresses || []), ...(data.genres || [])];
  if (tags.length) {
    const tr = el("div", "tag-row");
    tags.slice(0, 14).forEach((t) => tr.append(el("span", "tag", esc(t))));
    info.append(tr);
  }

  if (data.description) info.append(el("p", "desc", esc(data.description)));

  const saveBtn = el("button", "qbtn", savedHas(provider, item.id) ? "★ 已收藏" : "☆ 收藏");
  saveBtn.onclick = () => {
    const on = toggleSaved(data, provider, item);
    saveBtn.textContent = on ? "★ 已收藏" : "☆ 收藏";
  };
  qrow.append(saveBtn);

  if (data.magnets && data.magnets.length) {
    const box = el("div", "magnets");
    const det = el("details");
    det.append(el("summary", null, `下载资源（${data.magnets.length}）`));
    const list = el("div", "mlist");
    data.magnets.slice(0, 40).forEach((m) => {
      const a = el("a", null, esc(m.name || m.magnet));
      a.href = m.magnet;
      list.append(a);
    });
    det.append(list);
    box.append(det);
    info.append(box);
  }

  root.append(info);

  /* --- 推荐 --- */
  const rel = (data.related || []).filter((r) => r.id !== item.id);
  if (rel.length) {
    const sec = el("section", "row");
    const h = el("div", "row-head");
    h.append(el("h2", "row-title", "相关推荐"));
    const tr = el("div", "row-track");
    rel.slice(0, 14).forEach((r) => tr.append(cardEl(r)));
    sec.append(h, tr);
    root.append(sec);
  }

  app.replaceChildren(root);
  document.title = `${item.title || item.id} · ${state.site}`;

  if (media.length) play(media[0], item, { restore: true });
  bindPlayerKeys(video);
}

/* ------------------------------------------------------------------ player */
const P = {
  segs: [],
  media: null,
  item: null,
  previewTimer: null,
  lastPreview: "",
};

async function loadSegments(media) {
  P.segs = [];
  if (media.kind !== "hls") return;
  try {
    const r = await fetch(apiUrl(media.play));
    if (!r.ok) return;
    const text = await r.text();
    let t = 0;
    let dur = 4;
    const out = [];
    for (const raw of text.split("\n")) {
      const s = raw.trim();
      if (!s) continue;
      if (s.startsWith("#EXTINF:")) {
        dur = parseFloat(s.slice(8)) || 4;
        continue;
      }
      if (s.startsWith("#")) continue;
      const q = s.includes("?") ? new URLSearchParams(s.split("?")[1]) : null;
      if (!q || !q.get("u")) continue;
      out.push({ start: t, end: t + dur, u: q.get("u"), r: q.get("r") || "" });
      t += dur;
    }
    P.segs = out;
  } catch (_) {
    P.segs = [];
  }
}

function findSeg(t) {
  const segs = P.segs;
  if (!segs.length) return null;
  let lo = 0;
  let hi = segs.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = segs[mid];
    if (t < s.start) hi = mid - 1;
    else if (t >= s.end) lo = mid + 1;
    else return s;
  }
  return segs[Math.min(segs.length - 1, Math.max(0, lo))];
}

function fmtTime(s) {
  if (!isFinite(s) || s < 0) s = 0;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function buildControls(shell, video) {
  const bar = el("div", "ctrl-bar");
  bar.innerHTML = `
    <button class="c-btn pp" title="播放/暂停 (空格)">▶</button>
    <div class="progress-wrap">
      <div class="ptrack">
        <div class="pbuf"></div>
        <div class="pplayed"></div>
      </div>
      <div class="preview"><div class="pv-img"></div><div class="pv-time">00:00</div></div>
    </div>
    <span class="ptime">00:00 / 00:00</span>
    <button class="c-btn mute" title="静音">🔊</button>
    <button class="c-btn fs" title="全屏 (F)">⛶</button>`;
  shell.append(bar);

  const pp = bar.querySelector(".pp");
  const track = bar.querySelector(".ptrack");
  const buf = bar.querySelector(".pbuf");
  const played = bar.querySelector(".pplayed");
  const timeEl = bar.querySelector(".ptime");
  const mute = bar.querySelector(".mute");
  const fsBtn = bar.querySelector(".fs");
  const pv = bar.querySelector(".preview");
  const pvImg = bar.querySelector(".pv-img");
  const pvTime = bar.querySelector(".pv-time");
  const wrap = bar.querySelector(".progress-wrap");

  const toggle = () => (video.paused ? video.play().catch(() => {}) : video.pause());
  pp.onclick = toggle;
  video.addEventListener("click", toggle);
  video.addEventListener("play", () => (pp.textContent = "❚❚"));
  video.addEventListener("pause", () => (pp.textContent = "▶"));

  const render = () => {
    const d = video.duration || 0;
    const p = d ? (video.currentTime / d) * 100 : 0;
    played.style.width = p + "%";
    try {
      if (video.buffered.length) {
        buf.style.width = (video.buffered.end(video.buffered.length - 1) / (d || 1)) * 100 + "%";
      }
    } catch (_) {}
    timeEl.textContent = `${fmtTime(video.currentTime)} / ${fmtTime(d)}`;
  };
  video.addEventListener("timeupdate", render);
  video.addEventListener("progress", render);
  video.addEventListener("loadedmetadata", render);

  /* 拖动 / 点击跳转 */
  let dragging = false;
  const seekTo = (clientX) => {
    const rect = track.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    if (video.duration) video.currentTime = pct * video.duration;
  };
  track.addEventListener("pointerdown", (e) => {
    dragging = true;
    track.setPointerCapture(e.pointerId);
    seekTo(e.clientX);
  });
  track.addEventListener("pointermove", (e) => {
    if (dragging) seekTo(e.clientX);
  });
  track.addEventListener("pointerup", (e) => {
    dragging = false;
    try {
      track.releasePointerCapture(e.pointerId);
    } catch (_) {}
  });

  /* 悬停预览：按时间找到分片，向后端要一帧 */
  const showPreview = (clientX) => {
    const rect = track.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const d = video.duration || 0;
    if (!d) {
      pv.classList.remove("on");
      return;
    }
    const t = pct * d;
    const left = pct * rect.width;
    pv.classList.add("on");
    pv.style.left = Math.max(40, Math.min(rect.width - 40, left)) + "px";
    pvTime.textContent = fmtTime(t);

    const seg = findSeg(t);
    if (!seg) return;
    const off = Math.max(0, t - seg.start);
    const url = `/api/thumb?u=${encodeURIComponent(seg.u)}&t=${off.toFixed(2)}&r=${encodeURIComponent(seg.r)}&w=320`;
    if (url === P.lastPreview) return;
    P.lastPreview = url;
    const img = new Image();
    img.onload = () => {
      if (P.lastPreview === url) pvImg.style.backgroundImage = `url("${apiUrl(url)}")`;
    };
    img.src = apiUrl(url);
  };

  let pvRaf = 0;
  wrap.addEventListener("pointermove", (e) => {
    if (pvRaf) return;
    pvRaf = requestAnimationFrame(() => {
      pvRaf = 0;
      showPreview(e.clientX);
    });
  });
  wrap.addEventListener("pointerleave", () => {
    pv.classList.remove("on");
    P.lastPreview = "";
  });

  mute.onclick = () => {
    video.muted = !video.muted;
    mute.textContent = video.muted ? "🔇" : "🔊";
  };
  fsBtn.onclick = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (shell.requestFullscreen) shell.requestFullscreen();
    else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
  };
  video.addEventListener("volumechange", () => {
    mute.textContent = video.muted || video.volume === 0 ? "🔇" : "🔊";
  });

  return { bar, render };
}

function play(media, item, opts = {}) {
  const video = $("#player");
  if (!video) return;
  const shell = video.closest(".player-shell") || video.parentElement;
  const msg = $(".player-msg");
  const posKey = `ks_pos:${item.provider}:${item.id}`;
  const keep = opts.restore ? Number(localStorage.getItem(posKey) || 0) : video.currentTime || 0;

  destroyPlayers();
  msg.classList.remove("show");
  video.removeAttribute("controls");
  video.pause();
  video.removeAttribute("src");
  video.load();

  if (!shell.querySelector(".ctrl-bar")) buildControls(shell, video);
  document.querySelectorAll(".ctrl-bar").forEach((b) => {
    if (!shell.contains(b)) b.remove();
  });

  P.media = media;
  P.item = item;
  loadSegments(media);

  const onMeta = () => {
    video.removeEventListener("loadedmetadata", onMeta);
    if (keep > 5 && keep < (video.duration || 1e9) - 10) video.currentTime = keep;
    video.play().catch(() => {});
  };
  video.addEventListener("loadedmetadata", onMeta);

  if (media.kind === "hls") {
    if (window.Hls && Hls.isSupported()) {
      const h = new Hls({ maxBufferLength: 30, maxMaxBufferLength: 120, enableWorker: true });
      state.players.push(h);
      h.loadSource(apiUrl(media.play));
      h.attachMedia(video);
      h.on(Hls.Events.ERROR, (_e, d) => {
        if (!d || !d.fatal) return;
        if (d.type === Hls.ErrorTypes.NETWORK_ERROR) {
          h.startLoad();
        } else if (d.type === Hls.ErrorTypes.MEDIA_ERROR) {
          h.recoverMediaError();
        } else {
          msg.textContent = "播放中断，请切换画质或刷新重试";
          msg.classList.add("show");
        }
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = apiUrl(media.play);
    } else {
      msg.textContent = "当前浏览器不支持 HLS，建议使用 Chrome / Edge / Safari";
      msg.classList.add("show");
      return;
    }
  } else {
    video.src = apiUrl(media.play);
  }

  let lastSave = 0;
  video.addEventListener("timeupdate", () => {
    if (video.currentTime - lastSave < 5) return;
    lastSave = video.currentTime;
    try {
      localStorage.setItem(posKey, String(Math.floor(video.currentTime)));
    } catch (_) {}
  });
}

function destroyPlayers() {
  state.keyHandlers.forEach((h) => document.removeEventListener("keydown", h));
  state.keyHandlers = [];
  state.players.forEach((h) => {
    try {
      h.destroy();
    } catch (_) {}
  });
  state.players = [];
  const v = $("#player");
  if (v) {
    v.pause();
    v.removeAttribute("src");
    try {
      v.load();
    } catch (_) {}
  }
  P.segs = [];
  P.lastPreview = "";
}

function bindPlayerKeys(video) {
  const handler = (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.code === "Space") {
      e.preventDefault();
      video.paused ? video.play() : video.pause();
    } else if (e.code === "ArrowLeft") {
      video.currentTime = Math.max(0, video.currentTime - 10);
    } else if (e.code === "ArrowRight") {
      video.currentTime = Math.min(video.duration || 0, video.currentTime + 10);
    } else if (e.code === "KeyF") {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (video.requestFullscreen) video.requestFullscreen();
    }
  };
  document.addEventListener("keydown", handler);
  state.keyHandlers.push(handler);
}

/* ------------------------------------------------------------------- saved */
function readSaved() {
  try {
    return JSON.parse(localStorage.getItem("ks_saved") || "[]");
  } catch (_) {
    return [];
  }
}
function savedHas(provider, id) {
  return readSaved().some((x) => x.provider === provider && x.id === id);
}
function toggleSaved(data, provider, item) {
  const list = readSaved();
  const i = list.findIndex((x) => x.provider === provider && x.id === item.id);
  if (i >= 0) {
    list.splice(i, 1);
    localStorage.setItem("ks_saved", JSON.stringify(list));
    return false;
  }
  list.unshift({
    provider,
    id: item.id,
    title: item.title,
    cover_proxy: item.cover_proxy,
    duration: item.duration,
    label: data.provider_label,
    at: Date.now(),
  });
  localStorage.setItem("ks_saved", JSON.stringify(list.slice(0, 200)));
  return true;
}

function viewSaved(app) {
  const list = readSaved();
  const head = el("div", "page-head", `<h1>我的收藏</h1><p>${list.length} 部，仅保存在本机浏览器</p>`);
  const grid = el("div", "grid");
  if (!list.length) {
    app.replaceChildren(head, emptyState("还没有收藏", "在详情页点「☆ 收藏」即可保存"));
    return;
  }
  list.forEach((x) => grid.append(cardEl({ ...x, badges: [] })));
  app.replaceChildren(head, grid);
}

/* ------------------------------------------------------------------- legal */
const LEGAL = {
  terms: {
    title: "用户协议",
    body: `
      <h2>一、服务说明</h2>
      <p>本站提供影视内容索引与在线播放服务。用户在注册或使用本服务前，应完整阅读并同意本协议。</p>
      <h2>二、年龄限制</h2>
      <p>本站内容仅面向年满 18 周岁（或所在司法辖区法定成年年龄）的用户。未成年人禁止访问。</p>
      <h2>三、账号与会员</h2>
      <ul>
        <li>会员权益自开通之时生效，到期自动失效。</li>
        <li>已开通的会员服务不支持跨账号转移。</li>
        <li>同一账号同时播放设备数上限见定价页说明。</li>
        <li>老用户续费永久保留开通时的价格。</li>
      </ul>
      <h2>四、退款政策</h2>
      <p>开通后 7 日内，且观看影片不超过 3 部的，可申请全额退款。超出上述条件不予退款。</p>
      <h2>五、禁止行为</h2>
      <ul>
        <li>转售、出租、共享账号或批量下载后二次分发。</li>
        <li>使用自动化工具抓取、镜像本站内容或接口。</li>
        <li>规避画质与额度限制。</li>
      </ul>
      <h2>六、免责</h2>
      <p>因网络、上游内容源变更等不可控因素导致的服务中断，本站将在合理范围内恢复，但不承担由此产生的间接损失。</p>`,
  },
  privacy: {
    title: "隐私政策",
    body: `
      <h2>我们收集什么</h2>
      <ul>
        <li>设备标识：一份随机生成的匿名 ID，保存在你的浏览器中，用于识别会员状态与观看额度。</li>
        <li>访问日志：IP、时间、请求路径，用于安全防护与故障排查，保留 30 天。</li>
        <li>订单信息：订单号、套餐、金额、支付渠道，用于开通会员与对账。</li>
      </ul>
      <h2>我们不做什么</h2>
      <ul>
        <li>不收集你的真实姓名、身份证号等身份信息。</li>
        <li>不向第三方出售或共享你的观看记录。</li>
        <li>不在页面中植入第三方行为追踪脚本。</li>
      </ul>
      <h2>数据保存</h2>
      <p>收藏与播放进度仅保存在你的浏览器本地（localStorage），清除浏览器数据即删除。</p>
      <h2>联系</h2>
      <p>如需删除订单或会员数据，请通过站点客服渠道联系我们。</p>`,
  },
  about: {
    title: "关于我们",
    body: `
      <p>KuroStream 是一个高清影视聚合平台，把分散在各处的片源整合成统一、干净的观看入口：</p>
      <ul>
        <li><b>统一索引</b>：番号、演员、题材一次搜全站。</li>
        <li><b>原生播放</b>：自建流媒体代理，无插件、无跳转、可拖进度。</li>
        <li><b>干净界面</b>：无弹窗、无跳转广告，会员全程无广告。</li>
      </ul>
      <p>我们不做内容生产，只做观看体验。如果你发现某个片源无法播放，欢迎通过客服反馈，我们会尽快修复。</p>
      <h2>联系</h2>
      <p>客服与商务：请通过站内会员页面获取联系方式。</p>`,
  },
};

function viewLegal(app, kind) {
  const doc = LEGAL[kind];
  app.replaceChildren(el("div", "legal", `
    <h1>${esc(doc.title)}</h1>
    <div class="upd">最后更新：2026 年 11 月</div>
    ${doc.body}`));
  document.title = `${doc.title} · ${state.site}`;
}

/* ------------------------------------------------------------------ pricing */
let plansLoaded = null;

async function openPricing() {
  $("#pricing").classList.remove("hidden");
  const grid = $("#plan-grid");
  grid.innerHTML = '<div class="hint" style="grid-column:1/-1;text-align:center;color:var(--fg-dim)">加载中…</div>';
  try {
    if (!plansLoaded) plansLoaded = await api("/api/plans");
    renderPlans(plansLoaded);
  } catch (err) {
    grid.innerHTML = `<div class="error-box" style="grid-column:1/-1">${esc(err.message)}</div>`;
  }
}

function renderPlans(data) {
  const grid = $("#plan-grid");
  grid.innerHTML = "";
  for (const p of data.plans) {
    const card = el("div", "plan" + (p.featured ? " featured" : ""));
    const per = p.per_day ? `¥${p.per_day}/天` : "一次买断，永久可用";
    card.innerHTML = `
      <div class="p-name">${esc(p.name)}</div>
      <div class="p-price">¥${p.price}${p.days ? `<small> / ${p.days} 天</small>` : ""}</div>
      <div class="p-per">${per}</div>
      <div class="p-badge">${esc(p.badge || "")}</div>
      <button class="p-cta">立即开通</button>`;
    card.querySelector(".p-cta").onclick = () => choosePlan(p);
    grid.append(card);
  }
  const free = data.free || {};
  $("#feature-table").innerHTML =
    `<tr><th>权益</th><th>游客</th><th>会员</th></tr>` +
    (data.matrix || [])
      .map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.free)}</td><td>${esc(r.member)}</td></tr>`)
      .join("");
  $("#pricing-sub").textContent =
    `周卡 / 月卡 / 年卡 / 终身，全部解锁 1080p 与无广告（游客：${free.height || 480}p · 每日 ${free.daily || 5} 部）`;
}

function choosePlan(plan) {
  $("#pricing").classList.add("hidden");
  const channels = (plansLoaded && plansLoaded.channels) || [];
  const channel = (plansLoaded && plansLoaded.default_channel) || (channels[0] && channels[0].key) || "manual";
  createOrder(plan, channel);
}

/* -------------------------------------------------------------------- order */
let currentOrder = null;
let pollTimer = null;

async function createOrder(plan, channel) {
  $("#order").classList.remove("hidden");
  $("#order-title").textContent = `开通「${plan.name}」`;
  $("#order-body").innerHTML = '<div style="color:var(--fg-dim);padding:20px 0">创建订单…</div>';
  stopPolling();
  try {
    const r = await api("/api/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier: plan.key, channel }),
    });
    currentOrder = r.order;
    renderOrder(r.order, r.pay);
    startPolling(r.order.order_no);
  } catch (err) {
    $("#order-body").innerHTML = `<div class="error-box">下单失败：${esc(err.message)}</div>`;
  }
}

function renderOrder(order, pay) {
  const channels = (plansLoaded && plansLoaded.channels) || [];
  const body = $("#order-body");
  body.innerHTML = `
    <div class="order-row"><span>订单号</span><b>${esc(order.order_no)}</b></div>
    <div class="order-row"><span>套餐</span><b>${esc(order.tier_name)}</b></div>
    <div class="order-row"><span>应收</span><b class="order-amount">¥${Number(order.amount).toFixed(2)}</b></div>
    <div class="channel-row">${channels
      .map((c) => `<button class="qbtn${c.key === order.channel ? " active" : ""}" data-ch="${c.key}">${esc(c.label)}</button>`)
      .join("")}</div>
    <div class="pay-box">
      <div>${esc(pay.title || "")}</div>
      <div class="acct">${esc(pay.account || "（未配置收款账号，请联系客服）")}</div>
      <div class="hintline">${esc(pay.note || "")}</div>
    </div>
    <div class="order-actions">
      <button class="btn-primary" id="claim-btn">我已完成支付</button>
      <button class="btn-ghost" id="copy-btn">复制订单号</button>
    </div>
    <div class="order-status" id="order-status">等待支付…</div>`;

  body.querySelectorAll("[data-ch]").forEach((btn) => {
    btn.onclick = () => createOrder({ key: order.tier, name: order.tier_name }, btn.dataset.ch);
  });
  $("#claim-btn").onclick = claimOrder;
  $("#copy-btn").onclick = () => {
    if (navigator.clipboard) navigator.clipboard.writeText(order.order_no);
    $("#copy-btn").textContent = "已复制";
  };
}

async function claimOrder() {
  if (!currentOrder) return;
  try {
    const r = await api(`/api/order/${currentOrder.order_no}/claim`, { method: "POST" });
    if (r.order.status === "paid") return onPaid();
    const st = $("#order-status");
    st.className = "order-status warn";
    st.textContent = r.message || "已提交，等待客服确认…";
    const btn = $("#claim-btn");
    btn.disabled = true;
    btn.textContent = "等待确认中…";
  } catch (err) {
    $("#order-status").textContent = err.message;
  }
}

function startPolling(no) {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const r = await api(`/api/order/${no}`);
      if (r.order.status === "paid") onPaid();
    } catch (_) {}
  }, 4000);
}
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function onPaid() {
  stopPolling();
  await syncMember();
  const st = $("#order-status");
  if (st) {
    st.className = "order-status";
    st.textContent = `✅ 已开通，${(state.member && state.member.expires_text) || ""} 到期`;
  }
  const btn = $("#claim-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "已开通";
  }
  setTimeout(() => {
    $("#order").classList.add("hidden");
    router();
  }, 1600);
}

/* --------------------------------------------------------------------- boot */
async function syncMember() {
  try {
    const me = await api("/api/me");
    state.tier = me.tier;
    state.member = me;
    if (me.owner) {
      $("#vip-btn").textContent = "店主";
      $("#vip-btn").style.borderColor = "#3ecf8e";
      $("#vip-btn").style.color = "#8ff0c4";
    } else {
      $("#vip-btn").textContent = me.active ? me.label : "会员";
    }
    ADMIN_TOKEN = ADMIN_TOKEN || "";
  } catch (_) {}
}

async function boot() {
  try {
    const data = await api("/api/providers");
    state.channels = data.providers || [];
    state.site = data.site || state.site;
    state.tagline = data.tagline || state.tagline;
    $("#site-name").textContent = state.site;
    $("#footer-name").textContent = state.site;
    $("#footer-tagline").textContent = state.tagline;
    document.title = `${state.site} · 高清片库`;
  } catch (err) {
    $("#app").replaceChildren(errorState("无法连接服务器：" + err.message));
    return;
  }
  syncMember();
  await router();
}

/* ------------------------------------------------------------------- events */
$("#search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  location.hash = `#/s/${encodeURIComponent(q)}`;
});
$("#vip-btn").onclick = openPricing;
$("#pricing-close").onclick = () => $("#pricing").classList.add("hidden");
$("#pricing").addEventListener("click", (e) => {
  if (e.target.id === "pricing") $("#pricing").classList.add("hidden");
});
$("#order-close").onclick = () => {
  stopPolling();
  $("#order").classList.add("hidden");
};
$("#order").addEventListener("click", (e) => {
  if (e.target.id === "order") {
    stopPolling();
    $("#order").classList.add("hidden");
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  $("#pricing").classList.add("hidden");
  stopPolling();
  $("#order").classList.add("hidden");
});

window.addEventListener("hashchange", router);

/* 连点 logo 5 次 → 改服务器地址 / 填店主令牌（装到手机后不用重新打包） */
(() => {
  const logo = $(".logo");
  if (!logo) return;
  let taps = 0;
  let timer = null;
  logo.addEventListener("click", (e) => {
    taps += 1;
    clearTimeout(timer);
    timer = setTimeout(() => (taps = 0), 1500);
    if (taps < 5) return;
    taps = 0;
    e.preventDefault();

    const current = API_BASE || location.origin;
    const input = prompt("服务器地址（留空 = 使用当前站点）\n例如 https://kuro.example.com", current);
    if (input === null) return;
    const val = input.trim().replace(/\/+$/, "");
    if (val) localStorage.setItem("ks_api_base", val);
    else localStorage.removeItem("ks_api_base");

    const token = prompt("店主令牌（留空 = 普通访客）\n填了不限额度、全画质", ADMIN_TOKEN);
    if (token !== null) {
      const t = token.trim();
      if (t) localStorage.setItem("ks_admin", t);
      else localStorage.removeItem("ks_admin");
    }
    alert("已保存，即将刷新");
    location.reload();
  });
})();

/* PWA：只在网页版注册，原生外壳里由系统缓存层负责，跳过避免冲突 */
if ("serviceWorker" in navigator && !API_BASE && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

boot();
