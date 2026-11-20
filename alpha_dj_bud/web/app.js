/* Alpha DJ Bud – front end (texts come from i18n.js) */
"use strict";

const $ = (id) => document.getElementById(id);
let S = null;            // last state from server
let lastSig = "";

// Mixed In Key style Camelot colours (1..12)
const CAM_COLORS = {
  1: "#3ff2c0", 2: "#6ff57b", 3: "#a6f25a", 4: "#e5e05a", 5: "#ffb35a", 6: "#ff8a6b",
  7: "#ff6f9e", 8: "#f07fdc", 9: "#c48bff", 10: "#9aa6ff", 11: "#6fc6ff", 12: "#4fe6f0",
};
const keyNum = (k) => parseInt(k, 10);
const keyColor = (k) => (k ? CAM_COLORS[keyNum(k)] || "#888" : "#444");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opt);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast"; el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ---------------- Camelot wheel ---------------- */
function arc(r1, r2, a1, a2) {
  const p = (r, a) => [r * Math.cos(a), r * Math.sin(a)];
  const [x1, y1] = p(r2, a1), [x2, y2] = p(r2, a2), [x3, y3] = p(r1, a2), [x4, y4] = p(r1, a1);
  return `M${x1},${y1} A${r2},${r2} 0 0 1 ${x2},${y2} L${x3},${y3} A${r1},${r1} 0 0 0 ${x4},${y4} Z`;
}
function compatible(k) {
  const n = keyNum(k), L = k.slice(-1), o = L === "A" ? "B" : "A";
  const w = (x) => ((x - 1 + 12) % 12) + 1;
  return [n + L, n + o, w(n - 1) + L, w(n + 1) + L, w(n + 6) + L, w(n + 6) + o];
}
function drawWheel(current) {
  const ok = new Set(current ? compatible(current) : []);
  let out = "";
  for (let n = 1; n <= 12; n++) {
    const a0 = ((n - 1) * 30 - 90 - 15) * Math.PI / 180, a1 = a0 + 30 * Math.PI / 180;
    for (const [L, r1, r2] of [["B", 68, 104], ["A", 34, 68]]) {
      const code = n + L;
      const cls = !current ? "seg-ok" : code === current ? "seg-cur" : ok.has(code) ? "seg-ok" : "seg-dim";
      const mid = (a0 + a1) / 2, rm = (r1 + r2) / 2;
      out += `<path d="${arc(r1, r2, a0 + .01, a1 - .01)}" fill="${CAM_COLORS[n]}" class="${cls}"/>`;
      out += `<text x="${rm * Math.cos(mid)}" y="${rm * Math.sin(mid)}" class="${cls}">${code}</text>`;
    }
  }
  out += `<circle r="30" fill="#0b0a10" stroke="#2d2438"/>`;
  out += `<text y="0" style="fill:${current ? "#3dff8f" : "#555"};font-size:15px">${current || "--"}</text>`;
  $("wheel").innerHTML = out;
}

/* ---------------- rendering ---------------- */
const genreName = (id) => (S && S.genres.find((g) => g.id === id) || { name: id }).name;
const relName = (r) => t("rel." + r);
const reasonText = (r) => t("why." + r.code, { n: r.n });

function render(s) {
  S = s;
  if (s.language && s.language !== LANG) setLanguage(s.language);
  $("ver").textContent = "v" + s.app.version;
  const up = s.update || {};
  $("btnUpdate").hidden = !up.available;
  $("btnUpdate").textContent = up.installing ? t("upd.installing") : "⬆ v" + (up.latest || "");
  $("btnUpdate").title = t("upd.available", { v: up.latest || "" });

  // status
  const db = s.db;
  const gname = genreName(s.genre);
  $("ledDjay").className = "led " + (db.ok ? "on" : "err");
  $("ledBrain").className = "led purple" + (s.brain.transitions ? " on" : "");
  let status;
  if (!db.ok) status = "⚠ " + (db.error === "notFound" ? t("status.notFound") : (db.error || t("status.noLib")));
  else if (!s.playlistByGenre[s.genre]) status = t("status.choose", { genre: gname });
  else if (!s.current) status = t("status.lib", { n: db.tracks });
  else status = t("status.playing", { genre: gname.toUpperCase(), pool: s.poolSize, played: s.played.length });
  $("statusLcd").textContent = status;

  // setup
  fillSelect($("selEvent"), s.events.map((e) => [e.id, t("event." + e.id)]), s.event);
  const allowed = s.event === "mista" ? s.mixedGenres : [s.event];
  $("genreSeg").innerHTML = s.genres.map((g) =>
    `<button data-g="${g.id}" class="${g.id === s.genre ? "on" : ""}" ${allowed.includes(g.id) ? "" : "disabled"}>${g.name.toUpperCase()}</button>`).join("");
  const opts = [["", t("setup.choose")]].concat(
    s.playlists.map((p) => [p.id, `${"  ".repeat(p.depth)}${p.type === "folder" ? "📁" : "♫"} ${p.name} (${p.count})`]));
  fillSelect($("selPlaylist"), opts, s.playlistByGenre[s.genre] || "");
  $("poolCount").textContent = s.poolSize ? `· ${s.poolSize} ${t("setup.tracks")}` : "";

  // now playing
  const c = s.current;
  $("nowTitle").textContent = c ? c.title : "—";
  $("nowArtist").textContent = c ? (c.artist || t("now.unknownArtist")) : (db.ok ? t("now.startTrack") : t("now.notConnected"));
  $("nowKey").textContent = c && c.key ? c.key : "--";
  $("nowKey").className = "seg7 key";
  $("nowKey").style.color = c && c.key ? keyColor(c.key) : "";
  $("nowMusical").textContent = c && c.musicalKey ? c.musicalKey : "";
  $("nowBpm").textContent = c && c.bpm ? c.bpm.toFixed(1) : "---";
  $("nowDeck").textContent = c && c.deck != null ? t("now.deck") + " " + (c.deck + 1) : "";
  $("nowSource").textContent = c ? (c.source === "djay" ? t("now.fromDjay") : t("now.manual")) + (c.inPool ? "" : t("now.outside")) : "";
  drawWheel(c && c.key);

  renderSuggestions(s);

  // brain
  const b = s.brain;
  $("brainConf").textContent = b.confidence + "%";
  $("brainFollow").textContent = b.followedPct + "%";
  $("knobConf").style.transform = `rotate(${-135 + 2.7 * b.confidence}deg)`;
  $("knobFollow").style.transform = `rotate(${-135 + 2.7 * b.followedPct}deg)`;
  $("brainTxt").innerHTML = b.transitions
    ? t("brain.learned", { t: b.transitions, genre: esc(gname), k: b.tracksKnown, s: b.sets }) +
      (b.favouriteRelation ? "<br>" + t("brain.prefers", { rel: esc(relName(b.favouriteRelation)) }) : "")
    : t("brain.empty", { genre: esc(gname) });

  $("playedList").innerHTML = s.played.map((tr) =>
    `<li><span class="k" style="background:${keyColor(tr.key)}">${tr.key || "--"}</span>${esc(tr.title)}${tr.artist ? " · " + esc(tr.artist) : ""}</li>`).join("");
  $("playedList").scrollTop = 1e6;
}

function renderSuggestions(s) {
  const list = $("nextList");
  const st = s.filterStats || {};
  $("nextInfo").textContent = s.suggestions.length ? `· ${s.suggestions.length}` : "";
  const empty = (html) => (list.innerHTML = `<div class="empty">${html}</div>`);
  if (!s.db.ok) empty(t("next.noLib"));
  else if (!s.playlistByGenre[s.genre]) empty(t("next.choosePl", { genre: esc(genreName(s.genre)) }));
  else if (!s.current) empty(t("next.waiting"));
  else if (!s.current.key || !s.current.bpm) empty(t("next.notAnalyzed"));
  else if (!s.suggestions.length) empty(t("next.none"));
  else {
    list.innerHTML = s.suggestions.map((tr, i) => {
      const d = tr.bpmDelta, dcls = d > 0.05 ? "up" : d < -0.05 ? "down" : "";
      const ds = (d > 0 ? "+" : "") + d.toFixed(1);
      const why = tr.reasons && tr.reasons.length ? `<i>★ ${esc(tr.reasons.map(reasonText).join(" · "))}</i>` : "";
      return `<div class="trk${i < 3 ? " top" : ""}${tr.hasFile ? " can-drag" : " no-file"}" data-id="${tr.id}"
        ${tr.hasFile ? 'draggable="true"' : ""} title="${esc(tr.hasFile ? t("drag.hint") : t("drag.noFile"))}">
        <div class="rank">${i + 1}</div>
        <div><span class="badge" style="background:${keyColor(tr.key)}">${tr.key}</span></div>
        <div class="ti"><b title="${esc(tr.title)}">${esc(tr.title)}</b><span>${esc(tr.artist || "—")} ${why}</span></div>
        <div class="bpm">${tr.bpm.toFixed(1)}<small class="${dcls}">${ds}</small></div>
        <div class="score"><div class="meter"><i style="width:${tr.score}%"></i></div><div class="rel">${esc(relName(tr.relation))}</div></div>
        <div class="acts">
          <button class="like" title="${esc(t("next.like"))}">♥</button>
          <button class="hide" title="${esc(t("next.hide"))}">✕</button>
        </div></div>`;
    }).join("");
  }
  const ex = ["key", "bpm", "artist", "played", "noData"].filter((k) => st[k]).map((k) => t("ex." + k, { n: st[k] }));
  $("filterNote").textContent = ex.length ? t("next.excluded") + ": " + ex.join(" · ") : "";
}

function fillSelect(sel, items, value) {
  const sig = JSON.stringify(items);
  if (sel.dataset.sig !== sig) {
    sel.innerHTML = items.map(([v, txt]) => `<option value="${esc(v)}">${esc(txt)}</option>`).join("");
    sel.dataset.sig = sig;
  }
  if (document.activeElement !== sel) sel.value = value;
}

/* ---------------- polling ---------------- */
async function refresh(force) {
  try {
    const s = await api("state");
    const sig = s.version + "|" + s.language + "|" + JSON.stringify(s.current) + "|" + s.suggestions.map((x) => x.id + x.score).join(",");
    if (force || sig !== lastSig) { lastSig = sig; render(s); }
  } catch (e) {
    $("statusLcd").textContent = "⚠ " + t("status.down", { e: e.message });
    $("ledDjay").className = "led err";
  }
}
async function act(name, body, msg) {
  try {
    const r = await api(name, body || {});
    if (msg) toast(typeof msg === "function" ? msg(r) : msg);
  } catch (e) { toast(t("toast.error", { e: e.message })); }
  refresh(true);
}

/* ---------------- events ---------------- */
$("selEvent").onchange = (e) => act("event", { event: e.target.value });
$("genreSeg").onclick = (e) => { const g = e.target.dataset.g; if (g) act("genre", { genre: g }); };
$("selPlaylist").onchange = (e) => act("playlist", { id: e.target.value });
$("btnNewSet").onclick = () => { if (confirm(t("toast.newSetConfirm"))) act("newset", {}, t("toast.newSet")); };
$("btnEndSet").onclick = () => act("endset", {}, (r) => t("toast.endSet", { n: r.tracks }));
$("btnImport").onclick = () => act("import-history", {}, (r) => r.imported ? t("toast.imported", { n: r.imported }) : t("toast.noImport"));
$("btnCompact").onclick = () => {
  const compact = !(S && S.compact);
  act("window", { compact });
  if (!(S && S.hasWindow)) { try { compact ? window.resizeTo(380, 600) : window.resizeTo(1100, 800); } catch (e) {} }
};
$("nextList").onclick = (e) => {
  const row = e.target.closest(".trk"); const b = e.target.closest("button");
  if (!row || !b) return;
  const id = row.dataset.id;
  if (b.classList.contains("like")) act("like", { id, value: 1 }, t("toast.liked"));
  else if (b.classList.contains("hide")) act("hide", { id });
};

/* ---------------- drag a suggestion onto a djay deck ---------------- */
const nativeDrag = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.drag_track);
let dragRow = null;
$("nextList").addEventListener("mousedown", (e) => {
  const row = e.target.closest(".trk.can-drag");
  if (!row || e.button !== 0 || e.target.closest("button") || !nativeDrag()) return;
  e.preventDefault();               // native window: macOS takes over the drag
  dragRow = row;
  row.classList.add("dragging");
  window.pywebview.api.drag_track(row.dataset.id).then((r) => {
    if (!r || !r.ok) {
      row.classList.remove("dragging");
      toast(t("drag." + ((r && r.code) || "failed")) + (r && r.path ? " — " + r.path : "") + (r && r.detail ? " (" + r.detail + ")" : ""));
    }
  }).catch((err) => { row.classList.remove("dragging"); toast(t("drag.failed") + " (" + err + ")"); });
});
const endDrag = () => {
  if (!dragRow) return;
  const row = dragRow; dragRow = null;
  row.classList.remove("dragging");
  // tell the DJ why, if the drag never started
  setTimeout(async () => {
    try {
      const st = await window.pywebview.api.drag_status();
      if (st && st.armed && !st.started) {
        let why = st.error || (!st.monitor ? (st.install_error || "monitor not installed")
                 : st.dragged_events === 0 ? "no mouse-drag events" : "too short");
        if (why !== "too short") toast(t("drag.notStarted") + " (" + why + ")");
      }
    } catch (e) {}
  }, 250);
};
document.addEventListener("mouseup", endDrag);
window.addEventListener("focus", () => { if (dragRow) { dragRow.classList.remove("dragging"); dragRow = null; } });
$("nextList").addEventListener("dragstart", (e) => {   // browser mode fallback
  const row = e.target.closest(".trk.can-drag");
  if (!row || nativeDrag()) { e.preventDefault(); return; }
  const tr = S.suggestions.find((x) => x.id === row.dataset.id);
  if (!tr || !tr.fileUrl) { e.preventDefault(); return; }
  const path = decodeURIComponent(tr.fileUrl.replace("file://", ""));
  const name = path.split("/").pop();
  e.dataTransfer.effectAllowed = "copy";
  e.dataTransfer.setData("text/uri-list", tr.fileUrl);
  e.dataTransfer.setData("text/plain", path);
  e.dataTransfer.setData("DownloadURL", `audio/mpeg:${name}:${location.origin}/api/file?id=${encodeURIComponent(tr.id)}`);
});

let searchTimer;
$("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(doSearch, 200); };
async function doSearch() {
  const q = $("search").value.trim();
  if (!q) { $("searchList").innerHTML = ""; return; }
  const res = await api("search?q=" + encodeURIComponent(q));
  $("searchList").innerHTML = res.length ? res.map((tr) =>
    `<div class="trk" data-id="${tr.id}" title="${esc(t("side.setCurrent"))}"><div><span class="badge" style="background:${keyColor(tr.key)}">${tr.key || "--"}</span></div>
     <div class="ti"><b>${esc(tr.title)}</b><span>${esc(tr.artist || "—")}</span></div><div class="bpm">${tr.bpm ? tr.bpm.toFixed(0) : "--"}</div></div>`).join("")
    : `<div class="empty">${t("side.noResults")}</div>`;
}
$("searchList").onclick = (e) => {
  const row = e.target.closest(".trk");
  if (row) { act("current", { id: row.dataset.id }, t("toast.manual")); $("search").value = ""; $("searchList").innerHTML = ""; }
};

/* updates */
function updInfoText(u) {
  if (!u) return "";
  let txt = t("upd.current", { v: S.app.version });
  if (u.available) txt += " · " + t("upd.available", { v: u.latest });
  else if (u.error) txt += " · " + t("upd.err." + u.error);
  else if (u.checkedAt) txt += " · " + t("upd.upToDate");
  return txt;
}
$("btnUpdate").onclick = async () => {
  const u = S.update || {};
  if (u.installing) return;
  if (!u.installedApp) { toast(t("upd.err.notInstalled")); return; }
  if (!confirm(t("upd.confirm", { v: u.latest }))) return;
  $("btnUpdate").textContent = t("upd.installing");
  try {
    const r = await api("update-install", {});
    if (r.ok) toast(t("upd.done", { v: r.version }));
    else toast(t("upd.err." + r.code) + (r.detail ? " (" + r.detail.slice(0, 120) + ")" : ""));
  } catch (e) { toast(t("upd.done", { v: u.latest })); }   // app is restarting
};
$("btnCheckUpdate").onclick = async () => {
  $("updInfo").textContent = t("upd.checking");
  try { const r = await api("update-check", {}); S.update = r; $("updInfo").textContent = updInfoText(r); refresh(true); }
  catch (e) { $("updInfo").textContent = t("upd.err.network"); }
};

/* settings */
$("btnSettings").onclick = () => {
  const o = S.options;
  $("optLang").value = LANG;
  $("optAutoUpdate").checked = S.autoUpdateCheck !== false;
  $("updInfo").textContent = updInfoText(S.update);
  $("optTol").value = o.bpmTolerance; $("optArtist").value = o.artistWindow; $("optLimit").value = o.limit;
  $("optVariety").value = String(o.variety ?? 50);
  $("optTritone").checked = o.includeTritone; $("optHalf").checked = o.halfDouble; $("optReplays").checked = o.avoidReplays;
  $("optComments").checked = S.keyFromComments; $("optAutoGenre").checked = S.autoGenre;
  $("optDb").value = "";
  $("dbInfo").textContent = S.db.path ? t("set.inUse", { path: S.db.path, n: S.db.tracks }) : t("set.noDb");
  $("settings").hidden = false;
};
// live preview of the language inside the dialog
$("optLang").onchange = (e) => setLanguage(e.target.value);
$("btnCloseSettings").onclick = () => { $("settings").hidden = true; if (S) setLanguage(S.language); render(S); };
$("btnSaveSettings").onclick = () => {
  const body = {
    language: $("optLang").value,
    options: {
      bpmTolerance: parseFloat($("optTol").value) || 0, artistWindow: parseInt($("optArtist").value, 10) || 0,
      limit: parseInt($("optLimit").value, 10) || 15, includeTritone: $("optTritone").checked,
      halfDouble: $("optHalf").checked, avoidReplays: $("optReplays").checked,
      variety: parseInt($("optVariety").value, 10),
    },
    keyFromComments: $("optComments").checked, autoGenre: $("optAutoGenre").checked,
    autoUpdateCheck: $("optAutoUpdate").checked,
  };
  if ($("optDb").value.trim()) body.dbPath = $("optDb").value.trim();
  $("settings").hidden = true;
  setLanguage(body.language);
  act("options", body, t("toast.saved"));
};

setLanguage("en");
refresh(true);
setInterval(refresh, 1500);
