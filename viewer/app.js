// Viewer: connect WS, drive screen + tree + reward curve + evolution anim.
const $ = (id) => document.getElementById(id);
const screen = $("screen").getContext("2d");
const screenImg = new Image();
const SCREEN_URL = "/screen.png";

let cumR = 0;
let rewardSeries = [];      // [{t, cum_r, version}]
let versions = ["v0"];
let activeVersion = "v0";
let tree = { nodes: [], links: [] }; // simple list-of-decisions

function refreshScreen() {
  screenImg.onload = () => screen.drawImage(screenImg, 0, 0, 160, 144);
  screenImg.src = SCREEN_URL + "?t=" + Date.now();
}
setInterval(refreshScreen, 250);

function pushThought(button, why, version) {
  const ol = $("thought-stream");
  const li = document.createElement("li");
  li.innerHTML = `<span class="b">${button.toUpperCase()}</span> <span class="why">[${version}] ${escapeHtml(why)}</span>`;
  ol.insertBefore(li, ol.firstChild);
  while (ol.children.length > 80) ol.removeChild(ol.lastChild);
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function setVersion(v) {
  activeVersion = "v" + v;
  $("version").textContent = activeVersion;
  if (!versions.includes(activeVersion)) versions.push(activeVersion);
  renderVersions();
}
function renderVersions() {
  const ol = $("versions");
  ol.innerHTML = "";
  versions.forEach(v => {
    const li = document.createElement("li");
    li.textContent = v;
    if (v === activeVersion) li.classList.add("active");
    ol.appendChild(li);
  });
}

function setHud(state, cum_r) {
  $("badges").textContent = state.badges;
  $("pokedex").textContent = state.pokedex_seen;
  $("map").textContent = state.map_id;
  if (cum_r !== undefined) $("cumr").textContent = cum_r.toFixed(2);
}

function evolveAnim() {
  const ov = $("evolution-overlay");
  ov.classList.remove("hidden");
  setTimeout(() => ov.classList.add("hidden"), 2400);
}

function drawRewardCurve() {
  const svg = $("reward-curve");
  const W = 600, H = 140, pad = 8;
  if (rewardSeries.length < 2) { svg.innerHTML = ""; return; }
  const xs = rewardSeries.map(p => p.t);
  const ys = rewardSeries.map(p => p.cum_r);
  const xMin = xs[0], xMax = xs[xs.length - 1];
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const sx = t => pad + (W - 2*pad) * (t - xMin) / Math.max(1, xMax - xMin);
  const sy = r => H - pad - (H - 2*pad) * (r - yMin) / Math.max(0.001, yMax - yMin);
  const d = rewardSeries.map((p,i) => (i?"L":"M") + sx(p.t).toFixed(1) + " " + sy(p.cum_r).toFixed(1)).join(" ");

  // version dividers
  const dividers = [];
  let lastV = rewardSeries[0].version;
  for (const p of rewardSeries) {
    if (p.version !== lastV) {
      dividers.push(`<line x1="${sx(p.t)}" x2="${sx(p.t)}" y1="${pad}" y2="${H-pad}" stroke="#ffcb05" stroke-dasharray="3 3" opacity=".7"/>`);
      dividers.push(`<text x="${sx(p.t)+3}" y="${pad+10}" fill="#ffcb05" font-size="10">v${p.version}</text>`);
      lastV = p.version;
    }
  }

  svg.innerHTML = `
    <path d="${d}" fill="none" stroke="#4ade80" stroke-width="1.6"/>
    ${dividers.join("")}
  `;
}

function drawTree() {
  const svg = $("tree");
  const W = 420, H = 300;
  const decisions = tree.nodes.length;
  if (decisions === 0) { svg.innerHTML = ""; return; }

  const stepX = Math.min(40, (W - 20) / Math.max(1, decisions));
  let html = "";
  for (let i = 0; i < decisions; i++) {
    const n = tree.nodes[i];
    const x = 20 + i * stepX;
    const yMain = H/2;
    // main spine
    if (i > 0) html += `<line x1="${x-stepX}" y1="${yMain}" x2="${x}" y2="${yMain}" stroke="#ffcb05" stroke-width="2"/>`;
    // K forks at this decision
    const k = n.scores ? n.scores.length : 0;
    if (k) {
      const sMin = Math.min(...n.scores), sMax = Math.max(...n.scores);
      n.scores.forEach((s, j) => {
        const yf = 30 + (H - 60) * (j / Math.max(1, k - 1));
        const isWin = s === sMax;
        const color = isWin ? "#4ade80" : (s === sMin ? "#ee1515" : "#8b949e");
        html += `<line x1="${x}" y1="${yMain}" x2="${x+12}" y2="${yf}" stroke="${color}" stroke-width="1" opacity="0.7"/>`;
        html += `<circle cx="${x+12}" cy="${yf}" r="${isWin?4:2.5}" fill="${color}"/>`;
      });
    }
    html += `<circle cx="${x}" cy="${yMain}" r="4" fill="#ffcb05"/>`;
  }
  svg.innerHTML = html;
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen   = () => { $("status").style.color = "#4ade80"; };
  ws.onclose  = () => { $("status").style.color = "#ee1515"; setTimeout(connect, 1500); };
  ws.onerror  = () => { $("status").style.color = "#ee1515"; };
  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    switch (e.event) {
      case "boot":
        setVersion(e.version);
        setHud(e.state, 0);
        break;
      case "step":
        setVersion(e.v);
        setHud(e.state, e.cum_r);
        $("last-btn").textContent = e.button.toUpperCase();
        $("last-why").textContent = e.why;
        pushThought(e.button, e.why, "v" + e.v);
        cumR = e.cum_r;
        rewardSeries.push({ t: e.t, cum_r: e.cum_r, version: e.v });
        if (rewardSeries.length > 1200) rewardSeries.shift();
        if (e.t % 4 === 0) drawRewardCurve();
        break;
      case "fork_start":
        tree.nodes.push({ snapshot: e.snapshot, scores: null });
        drawTree();
        break;
      case "fork_done":
        const last = tree.nodes[tree.nodes.length - 1];
        if (last) last.scores = e.scores;
        drawTree();
        break;
      case "training_start":
        // pre-evolution sparkle
        $("status").style.color = "#3b4cca";
        break;
      case "policy_bump":
        evolveAnim();
        setVersion(e.version);
        pushThought("EVO", `policy → v${e.version}: ${e.prompt_preview.slice(0, 80)}…`, "trainer");
        break;
      case "done":
        $("status").style.color = "#8b949e";
        break;
    }
  };
}
connect();
