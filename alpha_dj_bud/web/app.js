/* Alpha DJ Bud – front end */
"use strict";

const $ = (id) => document.getElementById(id);
let S = null;            // last state from server
let lastVersion = -1;
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
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* ---------------- Camelot wheel ---------------- */
function arc(r1, r2, a1, a2) {
  const p = (r, a) => [r * Math.cos(a), r * Math.sin(a)];
  const [x1, y1] = p(r2, a1), [x2, y2] = p(r2, a2), [x3, y3] = p(r1, a2), [x4, y4] = p(r1, a1);
  return `M${x1},${y1} A${r2},${r2} 0 0 1 ${x2},${y2} L${x3},${y3} A${r1},${r1} 0 0 0 ${x4},${y4} Z`;
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
function compatible(k) {
  const n = keyNum(k), L = k.slice(-1), o = L === "A" ? "B" : "A";
  const w = (x) => ((x - 1 + 12) % 12) + 1;
  return [n + L, n + o, w(n - 1) + L, w(n + 1) + L, w(n + 6) + L, w(n + 6) + o];
}

/* ---------------- rendering ---------------- */
function render(s) {
  S = s;
  $("ver").textContent = "v" + s.app.version;

  // status
  const db = s.db;
  $("ledDjay").className = "led " + (db.ok ? "on" : "err");
  $("ledBrain").className = "led purple" + (s.brain.transitions ? " on" : "");
  let status;
  if (!db.ok) status = "⚠ " + (db.error || "libreria djay non disponibile");
  else if (!s.playlistByGenre[s.genre]) status = "Scegli la cartella playlist per " + genreName(s.genre);
  else if (!s.current) status = `Libreria OK · ${db.tracks} brani · in attesa del primo brano da djay…`;
  else status = `${genreName(s.genre).toUpperCase()} · ${s.poolSize} brani in cartella · ${s.played.length} suonati nel set`;
  $("statusLcd").textContent = status;

  // setup
  fillSelect($("selEvent"), s.events.map((e) => [e.id, e.name]), s.event);
  const allowed = s.event === "mista" ? s.genres.map((g) => g.id) : [s.event];
  $("genreSeg").innerHTML = s.genres.map((g) =>
    `<button data-g="${g.id}" class="${g.id === s.genre ? "on" : ""}" ${allowed.includes(g.id) ? "" : "disabled"}>${g.name.toUpperCase()}</button>`).join("");
  const opts = [["", "— scegli cartella / playlist —"]].concat(
    s.playlists.map((p) => [p.id, `${"  ".repeat(p.depth)}${p.type === "folder" ? "📁" : "♫"} ${p.name} (${p.count})`]));
  fillSelect($("selPlaylist"), opts, s.playlistByGenre[s.genre] || "");
  $("poolCount").textContent = s.poolSize ? `· ${s.poolSize} BRANI` : "";

  // now playing
  const c = s.current;
  $("nowTitle").textContent = c ? c.title : "—";
  $("nowArtist").textContent = c ? (c.artist || "artista sconosciuto") : (db.ok ? "Fai partire un brano in djay" : "djay non collegato");
  $("nowKey").textContent = c && c.key ? c.key : "--";
  $("nowKey").className = "seg7 key";
  $("nowKey").style.color = c && c.key ? keyColor(c.key) : "";
  $("nowMusical").textContent = c && c.musicalKey ? c.musicalKey : "";
  $("nowBpm").textContent = c && c.bpm ? c.bpm.toFixed(1) : "---";
  $("nowDeck").textContent = c && c.deck != null ? "DECK " + (c.deck + 1) : "";
  $("nowSource").textContent = c ? (c.source === "djay" ? "· DA DJAY" : "· SCELTO A MANO") + (c.inPool ? "" : " · FUORI CARTELLA") : "";
  drawWheel(c && c.key);

  // suggestions
  renderSuggestions(s);

  // brain
  const b = s.brain;
  $("brainConf").textContent = b.confidence + "%";
  $("brainFollow").textContent = b.followedPct + "%";
  $("knobConf").style.transform = `rotate(${-135 + 2.7 * b.confidence}deg)`;
  $("knobFollow").style.transform = `rotate(${-135 + 2.7 * b.followedPct}deg)`;
  $("brainTxt").innerHTML = b.transitions
    ? `<b>${b.transitions}</b> passaggi imparati in ${esc(genreName(s.genre))}<br><b>${b.tracksKnown}</b> brani conosciuti · <b>${b.sets}</b> set` +
      (b.favouriteRelation ? `<br>Preferisci: <b>${esc(b.favouriteRelation)}</b>` : "")
    : `Bud non conosce ancora i tuoi gusti in <b>${esc(genreName(s.genre))}</b>. Impara mentre suoni.`;

  $("playedList").innerHTML = s.played.map((t) =>
    `<li><span class="k" style="background:${keyColor(t.key)}">${t.key || "--"}</span>${esc(t.title)}${t.artist ? " · " + esc(t.artist) : ""}</li>`).join("");
  $("playedList").scrollTop = 1e6;
}

function renderSuggestions(s) {
  const list = $("nextList");
  const st = s.filterStats || {};
  $("nextInfo").textContent = s.suggestions.length ? `· ${s.suggestions.length}` : "";
  if (!s.db.ok) {
    list.innerHTML = `<div class="empty">Libreria djay non trovata.<br>Apri <b>⚙ Impostazioni</b> per indicare il percorso.</div>`;
  } else if (!s.playlistByGenre[s.genre]) {
    list.innerHTML = `<div class="empty">Scegli la <b>cartella playlist</b> di ${esc(genreName(s.genre))} qui sopra.</div>`;
  } else if (!s.current) {
    list.innerHTML = `<div class="empty">Fai partire un brano in <b>djay Pro</b><br>oppure sceglilo a mano con la ricerca.</div>`;
  } else if (!s.current.key || !s.current.bpm) {
    list.innerHTML = `<div class="empty">djay non ha ancora analizzato <b>key/BPM</b> di questo brano.<br>Analizzalo in djay e i consigli appariranno.</div>`;
  } else if (!s.suggestions.length) {
    list.innerHTML = `<div class="empty">Nessun brano compatibile nella cartella.<br>Prova ad aumentare la tolleranza BPM nelle impostazioni.</div>`;
  } else {
    list.innerHTML = s.suggestions.map((t, i) => {
      const d = t.bpmDelta, dcls = d > 0.05 ? "up" : d < -0.05 ? "down" : "";
      const ds = (d > 0 ? "+" : "") + d.toFixed(1);
      const why = t.reasons && t.reasons.length ? `<i>★ ${esc(t.reasons.join(" · "))}</i>` : "";
      return `<div class="trk${i < 3 ? " top" : ""}" data-id="${t.id}">
        <div class="rank">${i + 1}</div>
        <div><span class="badge" style="background:${keyColor(t.key)}">${t.key}</span></div>
        <div class="ti"><b title="${esc(t.title)}">${esc(t.title)}</b><span>${esc(t.artist || "—")} ${why}</span></div>
        <div class="bpm">${t.bpm.toFixed(1)}<small class="${dcls}">${ds}</small></div>
        <div class="score"><div class="meter"><i style="width:${t.score}%"></i></div><div class="rel">${esc(t.relation)}</div></div>
        <div class="acts">
          <button class="play" title="Lo sto suonando (imposta a mano)">▶</button>
          <button class="like" title="Mi piace: proponilo di più">♥</button>
          <button class="hide" title="Non proporlo in questo set">✕</button>
        </div></div>`;
    }).join("");
  }
  const ex = [];
  if (st.key) ex.push(`${st.key} key`);
  if (st.bpm) ex.push(`${st.bpm} BPM`);
  if (st.artist) ex.push(`${st.artist} stesso artista`);
  if (st.played) ex.push(`${st.played} già suonati`);
  if (st.noData) ex.push(`${st.noData} senza key/BPM`);
  $("filterNote").textContent = ex.length ? "Esclusi: " + ex.join(" · ") : "";
}

function fillSelect(sel, items, value) {
  const sig = JSON.stringify(items);
  if (sel.dataset.sig !== sig) {
    sel.innerHTML = items.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
    sel.dataset.sig = sig;
  }
  if (document.activeElement !== sel) sel.value = value;
}
const genreName = (id) => (S && S.genres.find((g) => g.id === id) || { name: id }).name;

/* ---------------- polling ---------------- */
async function refresh(force) {
  try {
    const s = await api("state");
    const sig = s.version + "|" + JSON.stringify(s.current) + "|" + s.suggestions.map((x) => x.id + x.score).join(",");
    if (force || sig !== lastSig) { lastSig = sig; render(s); }
  } catch (e) {
    $("statusLcd").textContent = "⚠ Alpha DJ Bud non risponde (" + e.message + ")";
    $("ledDjay").className = "led err";
  }
}
async function act(name, body, msg) {
  try {
    const r = await api(name, body || {});
    if (msg) toast(typeof msg === "function" ? msg(r) : msg);
  } catch (e) { toast("Errore: " + e.message); }
  refresh(true);
}

/* ---------------- events ---------------- */
$("selEvent").onchange = (e) => act("event", { event: e.target.value });
$("genreSeg").onclick = (e) => { const g = e.target.dataset.g; if (g) act("genre", { genre: g }); };
$("selPlaylist").onchange = (e) => act("playlist", { id: e.target.value });
$("btnNewSet").onclick = () => { if (confirm("Iniziare un nuovo set? Brani suonati ed esclusi verranno azzerati.")) act("newset", {}, "Nuovo set pronto"); };
$("btnEndSet").onclick = () => act("endset", {}, (r) => `Set chiuso: ${r.tracks} brani. Bud ha salvato le tue scelte.`);
$("btnImport").onclick = () => act("import-history", {}, (r) => r.imported ? `Imparato da ${r.imported} set della cronologia djay` : "Nessun nuovo set da importare per questa cartella");
$("btnCompact").onclick = () => {
  const compact = !(S && S.compact);
  act("window", { compact });
  if (!(S && S.hasWindow)) { try { compact ? window.resizeTo(380, 600) : window.resizeTo(1100, 800); } catch (e) {} }
};
$("nextList").onclick = (e) => {
  const row = e.target.closest(".trk"); const b = e.target.closest("button");
  if (!row || !b) return;
  const id = row.dataset.id;
  if (b.classList.contains("play")) act("current", { id });
  else if (b.classList.contains("like")) act("like", { id, value: 1 }, "Bud lo proporrà più spesso");
  else if (b.classList.contains("hide")) act("hide", { id });
};

let searchTimer;
$("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(doSearch, 200); };
async function doSearch() {
  const q = $("search").value.trim();
  if (!q) { $("searchList").innerHTML = ""; return; }
  const res = await api("search?q=" + encodeURIComponent(q));
  $("searchList").innerHTML = res.length ? res.map((t) =>
    `<div class="trk" data-id="${t.id}" title="Imposta come brano in riproduzione"><div><span class="badge" style="background:${keyColor(t.key)}">${t.key || "--"}</span></div>
     <div class="ti"><b>${esc(t.title)}</b><span>${esc(t.artist || "—")}</span></div><div class="bpm">${t.bpm ? t.bpm.toFixed(0) : "--"}</div></div>`).join("")
    : `<div class="empty">Nessun brano nella cartella</div>`;
}
$("searchList").onclick = (e) => {
  const row = e.target.closest(".trk");
  if (row) { act("current", { id: row.dataset.id }, "Brano impostato a mano"); $("search").value = ""; $("searchList").innerHTML = ""; }
};

/* settings */
$("btnSettings").onclick = () => {
  const o = S.options;
  $("optTol").value = o.bpmTolerance; $("optArtist").value = o.artistWindow; $("optLimit").value = o.limit;
  $("optTritone").checked = o.includeTritone; $("optHalf").checked = o.halfDouble; $("optReplays").checked = o.avoidReplays;
  $("optComments").checked = S.keyFromComments; $("optAutoGenre").checked = S.autoGenre;
  $("optDb").value = "";
  $("dbInfo").textContent = S.db.path ? "In uso: " + S.db.path + ` (${S.db.tracks} brani)` : "Nessuna libreria trovata";
  $("settings").hidden = false;
};
$("btnCloseSettings").onclick = () => ($("settings").hidden = true);
$("btnSaveSettings").onclick = () => {
  const body = {
    options: {
      bpmTolerance: parseFloat($("optTol").value) || 0, artistWindow: parseInt($("optArtist").value, 10) || 0,
      limit: parseInt($("optLimit").value, 10) || 15, includeTritone: $("optTritone").checked,
      halfDouble: $("optHalf").checked, avoidReplays: $("optReplays").checked,
    },
    keyFromComments: $("optComments").checked, autoGenre: $("optAutoGenre").checked,
  };
  if ($("optDb").value.trim()) body.dbPath = $("optDb").value.trim();
  $("settings").hidden = true;
  act("options", body, "Impostazioni salvate");
};

refresh(true);
setInterval(refresh, 1500);
