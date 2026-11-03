// Trace screen: intake (photo, text, phone, rehearsal) and the verdict.
import { api, h, s, icon, ICON, ribbon, stampSVG, serialRoll, STATUS, clock } from "./ui.js";
import { refresh, highlightFor, feedList } from "./app.js";

let root, resultHost, historyHost, dropEl, mode = "photo", textArea, busy = false;
let current = null;

export function init(App) {
  root = document.getElementById("s-trace");
  const fileIn = h("input", { type: "file", accept: "image/*", class: "hidden", onchange: e => {
    const f = e.target.files[0];
    if (f) sendPhoto(App, f);
    e.target.value = "";
  } });
  const photoPane = h("div", { class: "photo-pane" },
    h("strong", {}, "Drop a photo or screenshot"),
    h("div", { class: "row" },
      h("button", { class: "btn primary", type: "button", onclick: () => fileIn.click() }, icon("upload"), "Choose image"),
      h("span", { class: "muted" }, "or paste with Ctrl V")), fileIn);
  textArea = h("textarea", { placeholder: "Paste the leaked text", "aria-label": "Leaked text", spellcheck: "false" });
  const textPane = h("div", { class: "text-pane hidden", style: "width:100%" }, textArea,
    h("div", { class: "row", style: "justify-content:flex-end;margin-top:12px" },
      h("button", { class: "btn quiet", type: "button", onclick: () => { textArea.value = ""; textArea.focus(); } }, "Clear"),
      h("button", { class: "btn primary", type: "button", onclick: () => sendText(App, textArea.value) }, "Trace text")));
  dropEl = h("div", { class: "drop" }, photoPane, textPane);

  const seg = h("div", { class: "seg", role: "group", "aria-label": "Leak type" });
  const setMode = (m) => {
    mode = m;
    photoPane.classList.toggle("hidden", m !== "photo");
    textPane.classList.toggle("hidden", m !== "text");
    seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.m === m ? "true" : "false"));
    if (m === "text") textArea.focus();
  };
  [["photo", "Photo"], ["text", "Text"]].forEach(([m, l]) =>
    seg.append(h("button", { type: "button", "data-m": m, "aria-pressed": m === "photo" ? "true" : "false", onclick: () => setMode(m) }, l)));
  init.setMode = setMode;

  ["dragenter", "dragover"].forEach(ev => dropEl.addEventListener(ev, e => { e.preventDefault(); dropEl.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dropEl.addEventListener(ev, e => { e.preventDefault(); dropEl.classList.remove("over"); }));
  dropEl.addEventListener("drop", async e => {
    const f = e.dataTransfer.files[0];
    if (!f) return;
    if (f.type.startsWith("image/")) sendPhoto(App, f);
    else if (f.type.startsWith("text/") || f.name.endsWith(".txt")) { setMode("text"); textArea.value = await f.text(); sendText(App, textArea.value); }
  });
  document.addEventListener("paste", e => {
    if (App.route !== "trace" || e.target === textArea) return;
    const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); sendPhoto(App, item.getAsFile()); return; }
    const txt = e.clipboardData?.getData("text");
    if (txt && txt.length > 60) { setMode("text"); textArea.value = txt; sendText(App, txt); }
  });

  const rehearse = h("div", { class: "rehearse" }, h("span", {}, "Rehearse"),
    h("button", { class: "btn quiet", type: "button", onclick: () => simulate(App, "/api/simulate/photo", { fragment: false }) }, "Phone photo"),
    h("button", { class: "btn quiet", type: "button", onclick: () => simulate(App, "/api/simulate/photo", { fragment: true }) }, "Torn piece"),
    h("button", { class: "btn quiet", type: "button", onclick: () => simulateText(App) }, "Retyped leak"));

  const phone = h("aside", { class: "phonecard" },
    h("img", { src: "/api/phone-qr.svg", alt: "QR code for the phone capture page", width: 170, height: 170 }),
    h("b", {}, "Send from a phone"),
    h("div", { class: "url", id: "t-phoneurl" }));

  resultHost = h("div", { id: "t-result" });
  historyHost = h("div");
  root.append(
    h("div", { class: "intake" },
      h("div", {},
        h("div", { class: "row", style: "justify-content:space-between;margin-bottom:18px" }, h("h1", {}, "Trace a leak"), seg),
        dropEl, rehearse),
      phone),
    resultHost,
    h("div", { class: "history" }, h("h2", {}, "History"), historyHost));
}

export function renderHistory(App) {
  document.getElementById("t-phoneurl").textContent = App.state.phone_url;
  historyHost.replaceChildren(feedList(App.state.traces.slice(0, 12), async t => {
    const r = await api(`/api/trace/${t.id}`);
    show(App, r, false);
    resultHost.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function working(msg) {
  const w = h("div", { class: "working", role: "status" });
  w.innerHTML = ICON.spinner;
  w.append(msg);
  resultHost.replaceChildren(w);
}

async function run(App, fn, msg) {
  if (busy) return;
  busy = true;
  working(msg);
  try {
    const r = await fn();
    show(App, r, true);
    App.highlight = highlightFor({ ...r, ...(r.kind === "photo" ? { booklet: r.booklet, centre: r.custody?.centre } : { source: r.best?.id, stage: r.stage }) });
    await refresh();
  } catch (err) {
    resultHost.replaceChildren(h("div", { class: "note-bar" }, `Trace failed: ${err.message}`));
  } finally {
    busy = false;
  }
}

function sendPhoto(App, file) {
  init.setMode && init.setMode("photo");
  const fd = new FormData();
  fd.append("file", file);
  fd.append("channel", "web");
  run(App, () => fetch("/api/trace/photo", { method: "POST", body: fd }).then(r => r.json()),
    `Matching against ${App.state.copies_total} issued copies`);
}

function sendText(App, text) {
  if (text.trim().length < 20) { textArea.focus(); return; }
  run(App, () => api("/api/trace/text", { json: { text, channel: "web" } }), "Reading canary marks");
}

function simulate(App, path, body) {
  run(App, () => api(path, { json: body }), "Photographing a random booklet, then tracing it");
}

async function simulateText(App) {
  const r = await api("/api/simulate/text");
  init.setMode("text");
  textArea.value = r.text;
  sendText(App, r.text);
}

// ------------------------------------------------------------ verdicts
export function show(App, r, animate) {
  current = r;
  if (r.kind === "photo") resultHost.replaceChildren(photoVerdict(App, r, animate));
  else resultHost.replaceChildren(textVerdict(App, r, animate));
}

function fact(label, value) {
  return h("div", {}, h("dt", {}, label), h("dd", {}, value));
}

function photoVerdict(App, r, animate) {
  const ok = r.status === "traced" || r.status === "probable";
  const top = h("div", { class: "v-top" });
  const st = stampSVG(r.status, Date.now() / 1000);
  if (animate) st.classList.add("drop-in");
  top.append(st);
  if (ok && r.custody) {
    const c = r.custody;
    top.append(h("div", {},
      h("div", { class: "v-label" }, r.status === "traced" ? "Booklet" : "Probable booklet"),
      serialRoll(r.booklet, animate),
      h("dl", { class: "facts" },
        fact("Centre", `${c.city}, ${c.area} (${c.centre})`),
        fact("Room", c.room), fact("Seat", c.seat), fact("Roll no.", c.roll))));
    const odds = r.log10_odds > 0 ? r.log10_odds : 0;
    top.append(h("div", { class: "v-side" },
      h("div", {}, h("div", { class: "v-label" }, "Match strength"),
        h("div", { class: "strength" }, r.z.toFixed(1), h("small", {}, "σ"))),
      h("div", { class: "odds" }, "Odds that another copy fits this well ",
        h("b", { html: odds >= 1 ? `1 in 10<sup>${Math.floor(odds)}</sup>` : "high" })),
      h("div", { class: "odds" }, `Page ${r.page}, ${r.words_used} words read in ${r.elapsed} s`)));
  } else {
    const msg = {
      unregistered: "This image does not show a page of this paper.",
      inconclusive: "Too little of the page is readable. Photograph more of it, flat and in focus.",
      unreadable: "The file is not an image.",
    }[r.status] || "No match.";
    top.append(h("div", {}, h("div", { class: "source-name", style: "font-size:36px" }, STATUS[r.status] || "No match"),
      h("div", { class: "sub" }, msg)));
    top.append(h("div"));
  }
  const v = h("article", { class: "verdict" }, ribbon(), top);
  if (r.truth) {
    const hit = r.truth.booklet === r.booklet && ok;
    v.append(h("div", { class: "note-bar", style: "margin:0 32px 18px" },
      `Rehearsal photo of booklet ${r.truth.booklet}, page ${r.truth.page}. ${hit ? "Traced correctly." : "Not traced."}`));
  }
  if (r.viz && r.registered) {
    const left = h("div", {});
    const evid = evidence(r);
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Overlay" });
    [["photo", "Photo"], ["words", "Words"], ["shifts", "Shifts"]].forEach(([m, l]) =>
      seg.append(h("button", { type: "button", "aria-pressed": m === "words" ? "true" : "false", onclick: (e) => {
        seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", "false"));
        e.currentTarget.setAttribute("aria-pressed", "true");
        evid.setMode(m);
      } }, l)));
    left.append(h("h3", {}, "Evidence", seg), evid.el, evid.legend);
    const right = h("div", {}, h("h3", {}, "Every issued copy"), bars(r));
    if (ok && r.custody) right.append(h("h3", { style: "margin-top:26px" }, "Custody of this booklet"), custodyList(r.custody));
    v.append(h("div", { class: "v-body" }, left, right));
  } else if (r.photo) {
    v.append(h("div", { class: "v-body" }, h("div", {}, h("h3", {}, "Received"),
      h("div", { class: "evidence-img" }, h("img", { src: r.photo, alt: "Received image" }))), h("div")));
  }
  return v;
}

function evidence(r) {
  const vz = r.viz;
  const [x0, y0, x1, y1] = vz.crop;
  const w = x1 - x0, hh = y1 - y0;
  const img = h("img", { src: r.registered, alt: "Photo aligned to the master page" });
  const svg = s("svg", { viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: "none" });
  const legend = h("div", { class: "legend" });
  const gain = 28;
  const setMode = (m) => {
    svg.replaceChildren();
    legend.replaceChildren();
    if (m === "words") {
      let agreeN = 0;
      vz.words.forEach(wd => {
        const [bx0, by0, bx1, by1] = wd.b;
        const mx = wd.m[0] ?? null, ex = wd.e[0] ?? null, my = wd.m[1], ey = wd.e[1];
        const dot = (mx !== null && ex !== null ? mx * ex : 0) + (my !== null && ey !== null ? my * ey : 0);
        const agree = dot >= 0;
        if (agree) agreeN++;
        svg.append(s("rect", { class: "wb" + (agree ? "" : " off"), x: bx0 - x0, y: by0 - y0, width: bx1 - bx0, height: by1 - by0, rx: 2 }));
      });
      const n = vz.words.length;
      legend.append(h("span", {}, h("i", { style: "background:#2140b0" }), "Shift agrees with this booklet"),
        h("span", {}, h("i", { style: "background:#c21d3b" }), "Disagrees"),
        h("span", {}, `${agreeN} of ${n} words agree`));
    } else if (m === "shifts") {
      vz.words.forEach(wd => {
        const [bx0, by0, bx1, by1] = wd.b;
        const cx = (bx0 + bx1) / 2 - x0, cy = (by0 + by1) / 2 - y0;
        const mx = wd.m[0] ?? 0, my = wd.m[1] ?? 0, ex = wd.e[0] ?? 0, ey = wd.e[1] ?? 0;
        svg.append(s("line", { class: "ae", x1: cx, y1: cy, x2: cx + ex * gain, y2: cy + ey * gain, "stroke-linecap": "round" }));
        svg.append(s("line", { class: "am", x1: cx, y1: cy, x2: cx + mx * gain, y2: cy + my * gain, "stroke-linecap": "round" }));
      });
      legend.append(h("span", {}, h("i", { style: "background:#c21d3b" }), "Measured in photo"),
        h("span", {}, h("i", { style: "background:#8d92a8" }), "Expected for this booklet"),
        h("span", {}, `Magnified ${gain}×`));
    } else {
      legend.append(h("span", {}, `Aligned to page ${r.page} of the master`));
    }
  };
  setMode("words");
  return { el: h("div", { class: "evidence-img" }, img, svg), legend, setMode };
}

function bars(r) {
  const host = h("div", { class: "bars-host" });
  const draw = () => {
    const W = Math.max(280, Math.round(host.clientWidth || 560));
    if (host.dataset.w === String(W)) return;
    host.dataset.w = W;
    host.replaceChildren(barsSVG(r, W));
  };
  new ResizeObserver(draw).observe(host);
  return host;
}

function barsSVG(r, W) {
  const data = r.ranking.slice().sort((a, b) => a.booklet.localeCompare(b.booklet));
  const H = 260, pl = 40, pb = 34, pt = 32;
  const max = Math.max(...data.map(d => d.score), 6);
  const bw = (W - pl - 6) / data.length;
  const y = v => pt + (H - pt - pb) * (1 - Math.max(0, v) / max);
  const svg = s("svg", { class: "bars", width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Match score of every issued copy" });
  const step = max > 12 ? 5 : 2;
  for (let t = 0; t <= max; t += step) {
    svg.append(s("line", { class: "axis", x1: pl, x2: W, y1: y(t), y2: y(t), "stroke-dasharray": t ? "2 4" : null }));
    svg.append(s("text", { x: pl - 8, y: y(t) + 6, "text-anchor": "end" }, t));
  }
  data.forEach((d, i) => {
    const win = d.booklet === r.booklet && (r.status === "traced" || r.status === "probable");
    const x = pl + 3 + i * bw;
    svg.append(s("rect", { class: "bar" + (win ? " win" : ""), x, y: y(d.score), width: Math.max(1, bw - (bw > 4 ? 1.5 : 0.3)), height: Math.max(1, y(0) - y(d.score)) },
      s("title", {}, `${d.booklet}: ${d.score}`)));
    if (win) svg.append(s("text", { x: Math.min(W - 80, Math.max(pl + 4, x - 32)), y: y(d.score) - 9, style: "fill:#c21d3b;font-weight:700" }, d.booklet));
  });
  svg.append(s("text", { x: pl, y: H - 6 }, `${data.length} booklets in issue order`));
  return svg;
}

function custodyList(c) {
  return h("ol", { class: "custody" },
    h("li", {}, h("b", {}, c.press_label), h("span", {}, `Printed ${clock(c.printed_at)}`)),
    h("li", {}, h("b", {}, `Centre superintendent ${c.superintendent}`), h("span", {}, `${c.city}, ${c.area}`)),
    h("li", {}, h("b", {}, `Invigilator ${c.invigilator}`), h("span", {}, `Room ${c.room}`)),
    h("li", {}, h("b", {}, `Seat ${c.seat}`), h("span", {}, `Roll no. ${c.roll}`)));
}

function textVerdict(App, r, animate) {
  const ok = ["traced", "probable"].includes(r.status);
  const top = h("div", { class: "v-top" });
  const st = stampSVG(r.status, Date.now() / 1000);
  if (animate) st.classList.add("drop-in");
  top.append(st);
  const best = r.best;
  const cu = r.custody || {};
  const stageName = { setting: "Paper setting", moderation: "Moderation", translation: "Translation", print: "Printing" };
  if (ok && best) {
    const name = cu.type === "centre" ? `${cu.city}, ${cu.area}` : best.label;
    const exposure = cu.type === "centre" ? `${cu.id} only, ${cu.copies} booklets` :
      (cu.stage === "setting" ? "Master copy" : "Every centre");
    top.append(h("div", {},
      h("div", { class: "v-label" }, r.status === "traced" ? "Leaked from" : "Probably leaked from"),
      h("div", { class: "source-name" }, name),
      h("dl", { class: "facts" },
        fact("Holder", best.id),
        fact("Stage", stageName[cu.stage] || cu.stage),
        fact("Exposed", exposure),
        fact("Questions found", `${r.questions_found} of ${r.questions_total}`))));
    const second = r.ranking[1];
    top.append(h("div", { class: "v-side" },
      h("div", {}, h("div", { class: "v-label" }, "Canary marks"),
        h("div", { class: "strength" }, `${best.matched}/${best.total}`)),
      second ? h("div", { class: "odds" }, "Next best ", h("b", {}, second.label), ` at ${second.matched} of ${second.total}`) : null));
  } else if (r.status === "stage") {
    top.append(h("div", {},
      h("div", { class: "v-label" }, "Leaked during"),
      h("div", { class: "source-name" }, r.stage_label || r.stage),
      h("dl", { class: "facts" }, fact("Questions found", `${r.questions_found} of ${r.questions_total}`))));
    top.append(h("div"));
  } else {
    top.append(h("div", {}, h("div", { class: "source-name", style: "font-size:36px" }, "No match"),
      h("div", { class: "sub" }, r.questions_found ? "The questions match this paper but the wording carries too few marks." : "This text does not match this paper.")));
    top.append(h("div"));
  }
  const v = h("article", { class: "verdict" }, ribbon(), top);
  if (r.via_ocr) v.append(h("div", { class: "note-bar", style: "margin:0 32px 18px" }, "Text read from the image."));
  const left = h("div", {}, h("h3", {}, "Leaked text"), highlighted(r));
  const right = h("div", {}, h("h3", {}, "Every holder"), rankList(r));
  if (ok && cu.type === "centre") right.append(h("h3", { style: "margin-top:26px" }, "Custody"),
    h("ol", { class: "custody" },
      h("li", {}, h("b", {}, cu.press_label), h("span", {}, "Printed this centre's booklets")),
      h("li", {}, h("b", {}, `Centre superintendent ${cu.superintendent}`), h("span", {}, `${cu.city}, ${cu.area}`))));
  v.append(h("div", { class: "v-body" }, left, right));
  return v;
}

function highlighted(r) {
  const box = h("div", { class: "leak-text" });
  const text = r.text || "";
  let pos = 0;
  (r.marks || []).forEach(m => {
    const [a, b] = m.span;
    if (a < pos) return;
    box.append(text.slice(pos, a));
    box.append(h("mark", { class: m.kind === "order" ? (m.ok ? "order" : "off") : (m.ok ? "" : "off"), title: `Question ${m.q}` }, text.slice(a, b)));
    pos = b;
  });
  box.append(text.slice(pos));
  return box;
}

function rankList(r) {
  const max = Math.max(...r.ranking.map(x => x.total), 1);
  return h("ul", { class: "rank" }, r.ranking.slice(0, 9).map((x, i) =>
    h("li", { class: i === 0 && r.status !== "inconclusive" ? "win" : "" },
      h("span", { class: "nm" }, `${x.label}`),
      h("span", { class: "ct" }, `${x.matched} of ${x.total}`),
      h("span", { class: "meter" }, h("i", { style: `width:${(100 * x.matched / max).toFixed(1)}%` })))));
}
