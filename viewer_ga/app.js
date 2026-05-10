// GA viewer — population grid, lineage tree, fitness ranking, generational gain curve.
const $ = (id) => document.getElementById(id);
let popState = [];
let curGen = 0, totalGen = 8;
let bestEver = -Infinity;
let history = []; // [{gen, max, mean, min, vals}]
let lineage = []; // [{gen, parents, child, mutated}]
let rankOrder = [0,1,2,3,4,5,6,7];

function buildGrid(n = 8) {
  const grid = $("grid");
  grid.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const card = document.createElement("div");
    card.className = "panel";
    card.id = `panel-${i}`;
    card.innerHTML = `
      <div class="panel-header">
        <span class="id" id="pid-${i}">G0-${i+1}</span>
      </div>
      <div class="panel-screen">
        <img id="pimg-${i}" alt="">
      </div>
      <div class="panel-fit">
        <span class="num" id="pfit-${i}">+0.00</span>
        <div class="bar"><div id="pbar-${i}" style="width:0%"></div></div>
      </div>
    `;
    grid.appendChild(card);
  }
}

function refreshPanels() {
  for (let i = 0; i < 8; i++) {
    const im = $(`pimg-${i}`);
    if (im) im.src = `/panel/${i}.png?t=${Date.now()}`;
  }
}
setInterval(refreshPanels, 250);

function updatePopVisuals(pop) {
  popState = pop;
  // find min/max for normalization in the panel fitness bars
  const fits = pop.map(p => p.fitness);
  const mn = Math.min(...fits, 0);
  const mx = Math.max(...fits, 1);
  const span = Math.max(0.5, mx - mn);
  pop.forEach(p => {
    const card = $(`panel-${p.slot}`);
    if (!card) return;
    card.classList.remove("elite", "mutated", "child", "parent");
    if (p.highlight) card.classList.add(p.highlight === "elite-carry" ? "elite" : p.highlight);

    const idEl = $(`pid-${p.slot}`);
    const hdr = card.querySelector(".panel-header");
    idEl.textContent = p.id;
    // tag chips
    let tagHtml = "";
    if (p.highlight === "elite" || p.highlight === "elite-carry") tagHtml = '<span class="badge">ELITE</span>';
    else if (p.highlight === "mutated") tagHtml = '<span class="badge mut">⚡ MUT</span>';
    else if (p.highlight === "child") tagHtml = '<span class="badge child">CHILD</span>';
    let existing = hdr.querySelector(".badge");
    if (existing) existing.remove();
    if (tagHtml) hdr.insertAdjacentHTML("beforeend", tagHtml);

    const fitEl = $(`pfit-${p.slot}`);
    fitEl.textContent = (p.fitness >= 0 ? "+" : "") + p.fitness.toFixed(2);
    fitEl.classList.toggle("high", p.fitness > 5);
    fitEl.classList.toggle("low", p.fitness < 0);

    const pct = Math.max(0, Math.min(100, ((p.fitness - mn) / span) * 100));
    $(`pbar-${p.slot}`).style.width = pct + "%";

    if (p.milestone) {
      // show transient milestone chip
      let chip = card.querySelector(".panel-milestone");
      if (!chip) {
        chip = document.createElement("div");
        chip.className = "panel-milestone";
        card.appendChild(chip);
      }
      chip.textContent = p.milestone.toUpperCase();
      // auto-remove after a moment
      setTimeout(() => chip.remove(), 2200);
    }
  });
}

function updateRanking(fits, ranking, elites) {
  const wrap = $("rank-bars");
  wrap.innerHTML = "";
  const mx = Math.max(...fits, 1);
  ranking.forEach((slot, idx) => {
    const p = popState[slot];
    const isElite = elites.includes(slot);
    const bar = document.createElement("div");
    bar.className = "rank-bar" + (isElite ? " elite" : "");
    const fit = fits[slot];
    const pct = Math.max(2, ((fit - Math.min(0, ...fits)) / Math.max(1, mx - Math.min(0, ...fits))) * 100);
    bar.innerHTML = `
      <span class="rank">#${idx + 1}</span>
      <span class="id">${p.id}</span>
      <div class="bar"><div style="width:${pct}%"></div></div>
      <span class="fit">${(fit >= 0 ? "+" : "") + fit.toFixed(2)}</span>
      ${isElite ? '<span class="tag">ELITE</span>' : ''}
    `;
    wrap.appendChild(bar);
  });
}

function drawGainCurve() {
  const svg = $("gain-curve");
  if (history.length === 0) { svg.innerHTML = ""; return; }
  const W = 480, H = 200, pad = 24;
  const xs = history.map(h => h.gen);
  const allY = history.flatMap(h => [h.max, h.mean, h.min]);
  const yMax = Math.max(...allY) + 1;
  const yMin = Math.min(...allY, 0) - 1;
  const xMin = 1, xMax = totalGen;
  const sx = g => pad + (W - 2 * pad) * (g - xMin) / Math.max(0.5, xMax - xMin);
  const sy = v => H - pad - (H - 2 * pad) * (v - yMin) / Math.max(0.001, yMax - yMin);

  function path(key, color, w = 2) {
    if (history.length < 1) return "";
    const d = history.map((h, i) => (i ? "L" : "M") + sx(h.gen).toFixed(1) + " " + sy(h[key]).toFixed(1)).join(" ");
    const dots = history.map(h => `<circle cx="${sx(h.gen)}" cy="${sy(h[key])}" r="3" fill="${color}"/>`).join("");
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}"/>${dots}`;
  }

  // gridlines
  let grid = "";
  for (let g = 1; g <= totalGen; g++) {
    grid += `<line x1="${sx(g)}" y1="${pad}" x2="${sx(g)}" y2="${H-pad}" stroke="#30363d" stroke-dasharray="2 4" opacity=".4"/>`;
    grid += `<text x="${sx(g)}" y="${H-8}" text-anchor="middle" fill="#8b949e" font-size="9">G${g}</text>`;
  }
  // y-axis labels
  for (let i = 0; i < 5; i++) {
    const v = yMin + (yMax - yMin) * (i / 4);
    grid += `<text x="6" y="${sy(v)+3}" fill="#8b949e" font-size="9">${v.toFixed(1)}</text>`;
  }

  svg.innerHTML = grid + path("min", "#ee1515", 1.5) +
    path("mean", "#ffcb05", 2) + path("max", "#4ade80", 2.5);
}

function drawLineage() {
  const svg = $("lineage");
  const W = 360, H = 460, pad = 18;
  const rowH = (H - 2 * pad) / Math.max(1, totalGen + 1);
  const colW = (W - 2 * pad) / 9;
  let html = "";
  // generation labels
  for (let g = 0; g <= totalGen; g++) {
    const y = pad + g * rowH;
    html += `<text x="6" y="${y + 4}" fill="#8b949e" font-size="9">G${g}</text>`;
    // dots for each population slot
    for (let s = 0; s < 8; s++) {
      const x = pad + (s + 1) * colW;
      const isCur = g === curGen;
      html += `<circle cx="${x}" cy="${y}" r="${isCur ? 4 : 3}" fill="${isCur ? '#ffcb05' : '#30363d'}"/>`;
    }
  }
  // lineage edges
  lineage.forEach(l => {
    const childGen = l.gen;
    const childRow = pad + childGen * rowH;
    const parentRow = pad + (childGen - 1) * rowH;
    // child slot is the slot in the child's id
    const childSlot = parseInt(l.child.split("-")[1]) - 1;
    const cx = pad + (childSlot + 1) * colW;
    l.parents.forEach(pid => {
      const pSlot = parseInt(pid.split("-")[1]) - 1;
      const px = pad + (pSlot + 1) * colW;
      const color = l.mutated ? "#d946ef" : "#4ade80";
      html += `<line x1="${px}" y1="${parentRow}" x2="${cx}" y2="${childRow}" stroke="${color}" stroke-width="1" opacity="0.55"/>`;
    });
  });
  svg.innerHTML = html;
}

function setStatus(s) { $("status-text").textContent = s; }

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    switch (e.event) {
      case "boot":
        totalGen = e.n_generations;
        $("totalgen").textContent = totalGen;
        buildGrid(e.pop_size);
        popState = e.pop;
        updatePopVisuals(e.pop);
        setStatus("population initialized — generation 1 starting…");
        drawLineage();
        break;
      case "gen_start":
        curGen = e.gen;
        $("gen").textContent = curGen;
        popState = e.pop;
        updatePopVisuals(e.pop);
        setStatus(`generation ${curGen} — 8 sandboxes rolling out in parallel`);
        drawLineage();
        break;
      case "pop_state":
        updatePopVisuals(e.pop);
        break;
      case "milestone":
        setStatus(`${e.id} reached milestone: ${e.kind.toUpperCase()}`);
        break;
      case "gen_complete":
        history = e.history;
        const max = e.max;
        if (max > bestEver) {
          bestEver = max;
          $("best").textContent = (max >= 0 ? "+" : "") + max.toFixed(2);
        }
        updateRanking(e.fits, e.ranking, e.elites);
        drawGainCurve();
        setStatus(`generation ${curGen} complete — best: ${e.max.toFixed(2)}, mean: ${e.mean.toFixed(2)} — selecting elites…`);
        // mark elites in the population grid
        e.elites.forEach(s => {
          const c = $(`panel-${s}`);
          if (c) { c.classList.add("elite"); }
        });
        break;
      case "selection":
        setStatus(`elites selected: ${e.elite_ids.join(", ")} — beginning crossover…`);
        break;
      case "crossover":
        lineage.push({ gen: e.gen, parents: e.parents, child: e.child, mutated: e.mutated });
        drawLineage();
        setStatus(`crossover: ${e.parents.join(" × ")} → ${e.child}${e.mutated ? "  ⚡ mutated" : ""}`);
        break;
      case "gen_advance":
        popState = e.pop;
        updatePopVisuals(e.pop);
        // re-render rank to reflect new pop ids (zeroed bars)
        $("rank-bars").innerHTML = "";
        setStatus(`generation ${e.next_gen} ready — fanning out 8 fresh sandboxes`);
        break;
      case "done":
        setStatus(`done — best fitness: ${e.final_best.toFixed(2)} after ${totalGen} generations`);
        break;
    }
  };
  ws.onclose = () => setTimeout(connect, 1500);
}
buildGrid(8);
connect();
