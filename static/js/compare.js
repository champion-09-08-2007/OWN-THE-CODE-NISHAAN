// Compare screen: blink two booklets over the same region to show the
// fingerprint is invisible, then reveal the difference.
import { h } from "./ui.js";

let root, built = false, timer = null;
const st = { a: null, b: null, page: 0, mode: "blink", sel: { x0: 56, y0: 236, x1: 318, y1: 372 } };
const PAGE_W = 595.28, PAGE_H = 841.89;

export function init() { root = document.getElementById("s-compare"); }

export function enter(App) {
  if (!App.copies.length) return;
  if (!built || !App.copies.find(c => c.booklet === st.a)) build(App);
  else start();
}

window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#/compare")) stop(); });

function stop() { clearInterval(timer); timer = null; }

function build(App) {
  built = true;
  const copies = App.copies;
  st.a = copies[0].booklet;
  st.b = (copies.find(c => c.centre === copies[0].centre && c.booklet !== st.a) || copies[1]).booklet;
  const opt = sel => copies.map(c => h("option", { value: c.booklet, selected: c.booklet === sel ? "" : null }, `${c.booklet}  ${c.centre}`));
  const selA = h("select", { "aria-label": "Booklet A", onchange: e => { st.a = e.target.value; load(); } }, opt(st.a));
  const selB = h("select", { "aria-label": "Booklet B", onchange: e => { st.b = e.target.value; load(); } }, opt(st.b));
  const selP = h("select", { "aria-label": "Page", onchange: e => { st.page = +e.target.value; load(true); } },
    Array.from({ length: App.state.exam.pages }, (_, i) => h("option", { value: i }, `Page ${i + 1}`)));
  const seg = h("div", { class: "seg", role: "group", "aria-label": "View" });
  [["blink", "Blink"], ["a", "A"], ["b", "B"], ["diff", "Difference"]].forEach(([m, l]) =>
    seg.append(h("button", { type: "button", "aria-pressed": m === st.mode ? "true" : "false", onclick: e => {
      st.mode = m;
      seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", "false"));
      e.currentTarget.setAttribute("aria-pressed", "true");
      start();
    } }, l)));

  const thumb = h("img", { alt: "Page overview" });
  const box = h("div", { class: "sel" });
  const picker = h("div", { class: "picker", title: "Drag to choose a region" }, thumb, box);
  const imgA = h("img", { alt: "Region of booklet A" }), imgB = h("img", { alt: "Region of booklet B", class: "hidden" });
  const imgD = h("img", { alt: "Difference between the two booklets", class: "hidden" });
  const tag = h("span", { class: "tag" });
  const viewer = h("div", { class: "viewer" }, imgA, imgB, imgD, tag);
  const legend = h("div", { class: "cmp-legend hidden" },
    h("span", {}, h("i", { style: "background:#c41e3a" }), "Only in A"),
    h("span", {}, h("i", { style: "background:#2442b5" }), "Only in B"),
    h("span", {}, h("i", { style: "background:#b0b8be" }), "In both"));

  root.replaceChildren(
    h("div", { class: "row", style: "justify-content:space-between;margin-bottom:22px" }, h("h1", {}, "Compare booklets")),
    h("div", { class: "cmp-tools" },
      h("div", { class: "field" }, h("label", {}, "Booklet A"), selA),
      h("div", { class: "field" }, h("label", {}, "Booklet B"), selB),
      h("div", { class: "field" }, h("label", {}, "Page"), selP),
      seg),
    h("div", { class: "cmp" }, picker, h("div", {}, viewer, legend)));

  const placeBox = () => {
    const k = picker.clientWidth / PAGE_W;
    Object.assign(box.style, { left: `${st.sel.x0 * k}px`, top: `${st.sel.y0 * k}px`,
      width: `${(st.sel.x1 - st.sel.x0) * k}px`, height: `${(st.sel.y1 - st.sel.y0) * k}px` });
  };
  thumb.onload = placeBox;
  let drag = null;
  picker.addEventListener("pointerdown", e => {
    const r = picker.getBoundingClientRect(), k = r.width / PAGE_W;
    drag = { x: (e.clientX - r.left) / k, y: (e.clientY - r.top) / k };
    picker.setPointerCapture(e.pointerId);
  });
  picker.addEventListener("pointermove", e => {
    if (!drag) return;
    const r = picker.getBoundingClientRect(), k = r.width / PAGE_W;
    const x = Math.max(0, Math.min(PAGE_W, (e.clientX - r.left) / k));
    const y = Math.max(0, Math.min(PAGE_H, (e.clientY - r.top) / k));
    st.sel = { x0: Math.min(drag.x, x), y0: Math.min(drag.y, y), x1: Math.max(drag.x, x), y1: Math.max(drag.y, y) };
    placeBox();
  });
  picker.addEventListener("pointerup", () => {
    if (!drag) return;
    drag = null;
    if (st.sel.x1 - st.sel.x0 < 30 || st.sel.y1 - st.sel.y0 < 20) {
      const cx = (st.sel.x0 + st.sel.x1) / 2, cy = (st.sel.y0 + st.sel.y1) / 2;
      st.sel = { x0: Math.max(0, cx - 130), y0: Math.max(0, cy - 60), x1: Math.min(PAGE_W, cx + 130), y1: Math.min(PAGE_H, cy + 60) };
      placeBox();
    }
    load();
  });
  window.addEventListener("resize", placeBox);

  const q = (b) => `booklet=${b}&page=${st.page}&dpi=300&x0=${st.sel.x0.toFixed(1)}&y0=${st.sel.y0.toFixed(1)}&x1=${st.sel.x1.toFixed(1)}&y1=${st.sel.y1.toFixed(1)}`;
  function load(newPage) {
    if (newPage || !thumb.src) thumb.src = `/api/render?booklet=${st.a}&page=${st.page}&dpi=50`;
    imgA.src = `/api/render?${q(st.a)}`;
    imgB.src = `/api/render?${q(st.b)}`;
    imgD.src = `/api/diff?a=${st.a}&b=${st.b}&page=${st.page}&dpi=300&x0=${st.sel.x0.toFixed(1)}&y0=${st.sel.y0.toFixed(1)}&x1=${st.sel.x1.toFixed(1)}&y1=${st.sel.y1.toFixed(1)}`;
    start();
  }
  let showA = true;
  function paint() {
    const m = st.mode;
    const a = m === "a" || (m === "blink" && showA);
    imgA.classList.toggle("hidden", m === "diff" || !a);
    imgB.classList.toggle("hidden", m === "diff" || a);
    imgD.classList.toggle("hidden", m !== "diff");
    legend.classList.toggle("hidden", m !== "diff");
    tag.classList.toggle("b", !a && m !== "diff");
    tag.textContent = m === "diff" ? `${st.a} vs ${st.b}` : a ? `A ${st.a}` : `B ${st.b}`;
  }
  start = () => {
    stop();
    paint();
    if (st.mode === "blink" && location.hash.startsWith("#/compare")) {
      timer = setInterval(() => { showA = !showA; paint(); }, 700);
    }
  };
  load(true);
}

let start = () => {};
