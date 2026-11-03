// Custody chain: who held the paper, from setter to every printed booklet.
import { s } from "./ui.js";

const SHORT = { setter: "Setter", moderator: "Moderator", press: "Press" };

function nodeLabel(hd) {
  if (hd.role === "translator") return hd.label.split(",").pop().trim();
  if (hd.role === "press") return hd.label.replace("Press ", "");
  if (hd.role === "moderator") return "Moderator";
  return SHORT[hd.role] || hd.label;
}

export function drawChain(host, st, copies, hl) {
  const W = Math.max(1180, host.clientWidth || 1180);
  const centres = st.centres;
  const holders = st.holders;
  const rowH = 52, top = 40, n = centres.length;
  const H = top + n * rowH + 8;
  const nodeW = 128, cW = 192;
  const maxCount = Math.max(1, ...centres.map(c => copies.filter(x => x.centre === c.code).length));
  const need = Math.min(W * 0.42, Math.max(260, maxCount * 24 + 30));
  const gap = Math.max(36, Math.min(130, (W - 4 * nodeW - cW - need - 8) / 4.7));
  const colX = [0, 1, 2, 3].map(i => i * (nodeW + gap));
  const cX = colX[3] + nodeW + gap;
  const bX = cX + cW + gap * 0.7;
  const bW = W - bX - 4;

  const svg = s("svg", { class: "chain", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": "Custody chain from paper setter to printed booklets" });
  const heads = ["Setting", "Moderation", "Translation", "Printing"];
  heads.forEach((t, i) => svg.append(s("text", { class: "colhead", x: colX[i], y: 18 }, t)));
  svg.append(s("text", { class: "colhead", x: cX, y: 18 }, "Centres"));
  svg.append(s("text", { class: "colhead", x: bX, y: 18 }, "Booklets"));

  const area = n * rowH;
  const rowY = i => top + i * rowH + rowH / 2;
  const pos = {};
  for (let stage = 0; stage < 4; stage++) {
    const col = holders.filter(x => x.stage === stage);
    col.forEach((hd, j) => {
      let cy = top + (j + 0.5) * (area / col.length);
      if (stage === 3) {
        const idx = centres.map((c, i) => (c.press === hd.id ? i : -1)).filter(i => i >= 0);
        if (idx.length) cy = idx.reduce((a, i) => a + rowY(i), 0) / idx.length;
      }
      pos[hd.id] = { x: colX[stage], y: cy, w: nodeW, h: 56, stage, hd };
    });
  }
  centres.forEach((c, i) => { pos[c.code] = { x: cX, y: rowY(i), w: cW, h: 40, stage: 4, c }; });

  // highlight sets
  const hot = new Set(), exposed = new Set(), hotLinks = new Set();
  let hotBooklet = null, exposedCentres = new Set();
  if (hl && hl.kind === "photo" && hl.booklet) {
    const c = centres.find(x => x.code === hl.centre);
    if (c) {
      hot.add(c.code); hot.add(c.press);
      hotLinks.add(`${c.press}>${c.code}`); hotLinks.add(`${c.code}>cells`);
      hotBooklet = hl.booklet;
    }
  } else if (hl && hl.kind === "text") {
    const src = holders.find(x => x.id === hl.source);
    if (src) {
      hot.add(src.id);
      if (src.stage >= 1) hotLinks.add(`S1>${src.id}`);
      if (src.stage === 2) holders.filter(x => x.stage === 1).forEach(m => hotLinks.add(`${m.id}>${src.id}`));
      holders.filter(x => x.stage > src.stage).forEach(x => exposed.add(x.id));
      centres.forEach(c => { exposed.add(c.code); exposedCentres.add(c.code); });
    } else {
      const c = centres.find(x => x.code === hl.source);
      if (c) {
        hot.add(c.code); exposed.add(c.press); exposedCentres.add(c.code);
        hotLinks.add(`${c.press}>${c.code}`);
      } else if (hl.stage) {
        const stageIdx = { setting: 0, moderation: 1, translation: 2, print: 3 }[hl.stage];
        holders.filter(x => x.stage >= stageIdx).forEach(x => exposed.add(x.id));
        centres.forEach(c => { exposed.add(c.code); exposedCentres.add(c.code); });
      }
    }
  }

  const links = s("g");
  const link = (a, b, key) => {
    const A = pos[a], B = pos[b];
    if (!A || !B) return;
    const x1 = A.x + A.w, y1 = A.y, x2 = B.x, y2 = B.y, mx = (x1 + x2) / 2;
    const isHot = hotLinks.has(key || `${a}>${b}`);
    const p = s("path", { class: "link" + (isHot ? " hot" : ""), d: `M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}` });
    if (isHot) {
      p.style.strokeDasharray = "600";
      p.style.strokeDashoffset = "600";
      p.animate([{ strokeDashoffset: 600 }, { strokeDashoffset: 0 }], { duration: 700, fill: "forwards", easing: "ease-out" });
    }
    (isHot ? hotG : links).append(p);
  };
  const hotG = s("g");
  const byStage = k => holders.filter(x => x.stage === k);
  byStage(1).forEach(m => byStage(0).forEach(sx => link(sx.id, m.id)));
  byStage(2).forEach(t => byStage(1).forEach(m => link(m.id, t.id)));
  byStage(3).forEach(p => byStage(2).forEach(t => link(t.id, p.id)));
  centres.forEach(c => link(c.press, c.code));
  svg.append(links);

  // booklet cells per centre
  const cells = s("g");
  const byCentre = {};
  copies.forEach(cp => (byCentre[cp.centre] = byCentre[cp.centre] || []).push(cp));
  centres.forEach((c, i) => {
    const list = (byCentre[c.code] || []).slice().sort((a, b) => a.room.localeCompare(b.room) || a.seat - b.seat);
    const rooms = [...new Set(list.map(x => x.room))];
    const count = list.length || 1;
    const roomGap = 14;
    let cs = Math.floor((bW - roomGap * (rooms.length - 1)) / count);
    cs = Math.max(3, Math.min(24, cs));
    const pad = cs >= 9 ? 3 : 1;
    const y = rowY(i) - (cs - pad) / 2;
    let x = bX, lastRoom = null;
    const startX = x;
    list.forEach(cp => {
      if (lastRoom !== null && cp.room !== lastRoom) x += roomGap;
      lastRoom = cp.room;
      const cls = "cell" + (cp.booklet === hotBooklet ? " hot" : exposedCentres.has(c.code) ? " exposed" : "");
      const r = s("rect", { class: cls, x, y, width: cs - pad, height: cs - pad, rx: 1.5 },
        s("title", {}, `Booklet ${cp.booklet}, room ${cp.room}, seat ${cp.seat}`));
      cells.append(r);
      if (cp.booklet === hotBooklet) {
        const ring = s("rect", { class: "ring", x: x - 4, y: y - 4, width: cs - pad + 8, height: cs - pad + 8, rx: 3 });
        cells.append(ring);
      }
      x += cs;
    });
    const key = `${c.code}>cells`;
    const lx1 = cX + cW, ly = rowY(i);
    const line = s("path", { class: "link" + (hotLinks.has(key) ? " hot" : ""), d: `M${lx1} ${ly}H${startX - 6}` });
    (hotLinks.has(key) ? hotG : links).append(line);
  });
  svg.append(cells, hotG);

  // nodes on top
  const nodes = s("g");
  Object.entries(pos).forEach(([id, p]) => {
    const cls = "node" + (hot.has(id) ? " hot" : exposed.has(id) ? " exposed" : "");
    const g = s("g", { class: cls, transform: `translate(${p.x},${p.y - p.h / 2})` });
    g.append(s("rect", { width: p.w, height: p.h, rx: 3 }));
    if (p.hd) {
      g.append(s("text", { class: "id", x: 12, y: 23 }, id));
      g.append(s("text", { class: "lab", x: 12, y: 44 }, nodeLabel(p.hd)));
      g.append(s("title", {}, p.hd.label));
    } else {
      g.append(s("text", { class: "id", x: 12, y: 26 }, id));
      g.append(s("text", { class: "lab", x: 92, y: 26 }, p.c.city));
      g.append(s("title", {}, `${p.c.city}, ${p.c.area}`));
    }
    nodes.append(g);
  });
  svg.append(nodes);
  host.replaceChildren(svg);
}
