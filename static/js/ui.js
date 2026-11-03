// Small DOM and drawing helpers shared by every screen.
export const NS = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

export function clock(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function stamp(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export const STATUS = {
  traced: "Traced",
  probable: "Probable",
  stage: "Stage found",
  inconclusive: "No match",
  unregistered: "Not this paper",
  unreadable: "Unreadable",
};

export const CHANNEL = { web: "Web", phone: "Phone", telegram: "Telegram", rehearsal: "Rehearsal" };

function gcd(a, b) { return b ? gcd(b, a % b) : a; }

function trochoid(R, r, d, scale, cx, cy, steps = 1400) {
  const k = (R - r) / r;
  const turns = r / gcd(R, r);
  let p = "";
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * Math.PI * 2 * turns;
    const x = cx + scale * ((R - r) * Math.cos(t) + d * Math.cos(k * t));
    const y = cy + scale * ((R - r) * Math.sin(t) - d * Math.sin(k * t));
    p += (i ? "L" : "M") + x.toFixed(2) + " " + y.toFixed(2);
  }
  return p;
}

// Guilloche rosette used as the brand mark.
export function rosette(size = 42) {
  const c = size / 2;
  return s("svg", { viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true" },
    s("circle", { cx: c, cy: c, r: c - 0.8, fill: "#fbfcfa", stroke: "#131a3a", "stroke-width": 1.2 }),
    s("path", { d: trochoid(24, 9, 13, (c - 3) / 28, c, c), fill: "none", stroke: "#2140b0", "stroke-width": 0.55 }),
    s("path", { d: trochoid(20, 7, 5, (c - 3) / 18, c, c), fill: "none", stroke: "#c21d3b", "stroke-width": 0.5 }),
    s("circle", { cx: c, cy: c, r: 2.2, fill: "#131a3a" }));
}

// Security-print ribbon along the top edge of a verdict.
export function ribbon(width = 1400, height = 22) {
  const svg = s("svg", { class: "ribbon", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  for (let i = 0; i < 7; i++) {
    let p = "";
    for (let x = 0; x <= width; x += 4) {
      const y = height / 2 + Math.sin(x / 19 + i * 0.9) * (height / 2 - 3) * Math.cos(x / 150 + i * 0.4);
      p += (x ? "L" : "M") + x + " " + y.toFixed(2);
    }
    svg.append(s("path", { d: p, fill: "none", stroke: i % 2 ? "#2140b0" : "#131a3a", "stroke-width": 0.6, opacity: 0.55 }));
  }
  return svg;
}

// Rubber stamp for a verdict.
export function stampSVG(status, ts) {
  const col = status === "traced" || status === "probable" ? "#c21d3b" : status === "stage" ? "#8a5a00" : "#646c8a";
  const word = { traced: "Traced", probable: "Probable", stage: "Stage", inconclusive: "No match", unregistered: "Unknown", unreadable: "Unread" }[status] || "Checked";
  const id = "rough" + Math.random().toString(36).slice(2, 7);
  const when = new Date((ts || Date.now() / 1000) * 1000);
  const dateTxt = when.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" });
  return s("svg", { class: "stamp", viewBox: "0 0 150 150", role: "img", "aria-label": word },
    s("defs", {},
      s("filter", { id, x: "-10%", y: "-10%", width: "120%", height: "120%" },
        s("feTurbulence", { type: "fractalNoise", baseFrequency: "0.9", numOctaves: "2", seed: "7", result: "n" }),
        s("feDisplacementMap", { in: "SourceGraphic", in2: "n", scale: "2.2", result: "d" }),
        s("feColorMatrix", { in: "n", type: "matrix", values: "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.6 1.25", result: "m" }),
        s("feComposite", { in: "d", in2: "m", operator: "in" }))),
    s("g", { filter: `url(#${id})`, fill: "none", stroke: col },
      s("circle", { cx: 75, cy: 75, r: 70, "stroke-width": 4 }),
      s("circle", { cx: 75, cy: 75, r: 62, "stroke-width": 1.5 }),
      s("text", { x: 75, y: 84, "text-anchor": "middle", fill: col, stroke: "none", "font-size": word.length > 7 ? 24 : 31, "font-weight": 800, style: "font-stretch:92%" }, word),
      s("text", { x: 75, y: 112, "text-anchor": "middle", fill: col, stroke: "none", "font-size": 17, "font-weight": 600 }, dateTxt),
      s("text", { x: 75, y: 50, "text-anchor": "middle", fill: col, stroke: "none", "font-size": 17, "font-weight": 700, style: "font-stretch:118%" }, "Nishaan")));
}

// Odometer roll for booklet numbers, like a numbering machine.
export function serialRoll(text, animate = true) {
  const wrap = h("div", { class: "serial", "aria-label": text });
  [...text].forEach((ch, i) => {
    const d = h("span", { class: "d" });
    if (!/\d/.test(ch) || !animate) {
      d.append(h("span", {}, ch));
    } else {
      const n = +ch;
      const loops = 10 + n + i * 3;
      const col = h("span", {});
      for (let k = 0; k <= loops; k++) col.append(h("span", {}, String((n - loops + k + 100) % 10)));
      col.style.transform = `translateY(-${loops}em)`;
      col.style.setProperty("--t", `${0.7 + i * 0.09}s`);
      d.classList.add("roll");
      d.append(col);
    }
    wrap.append(d);
  });
  return wrap;
}

export const ICON = {
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/></svg>',
  spinner: '<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="none" stroke="#c9d3cc" stroke-width="4"/><path d="M20 4a16 16 0 0 1 16 16" fill="none" stroke="#2140b0" stroke-width="4" stroke-linecap="round"/></svg>',
  sealOk: '<svg viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 3l4.2 3.1 5.2-.4 1.6 5 4.4 2.8-1.2 5.1 2.4 4.6-3.9 3.5-.3 5.2-5.1 1.3-3 4.3-4.9-1.8-4.9 1.8-3-4.3-5.1-1.3-.3-5.2-3.9-3.5 2.4-4.6L6.6 14.5 11 11.7l1.6-5 5.2.4z"/><path d="M15 22.5l4.6 4.5L29.5 17"/></svg>',
  sealBad: '<svg viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 3l4.2 3.1 5.2-.4 1.6 5 4.4 2.8-1.2 5.1 2.4 4.6-3.9 3.5-.3 5.2-5.1 1.3-3 4.3-4.9-1.8-4.9 1.8-3-4.3-5.1-1.3-.3-5.2-3.9-3.5 2.4-4.6L6.6 14.5 11 11.7l1.6-5 5.2.4z"/><path d="M16.5 16.5l11 11m0-11l-11 11"/></svg>',
};

export function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = ICON[name];
  return t.content.firstChild;
}

export function toast(title, line, onclick) {
  const t = h("div", { class: "toast", role: "status", onclick: () => { onclick && onclick(); t.remove(); } },
    h("i"), h("div", {}, h("b", {}, title), h("span", {}, line)));
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), 7000);
}
