// Ledger screen: hash-chained custody events.
import { api, h, icon, stamp, clock } from "./ui.js";

let root, tbody, headHost, expanded = new Set();

const TYPE = {
  exam_created: "Exam created",
  paper_sealed: "Master sealed",
  softcopy_issued: "Soft copy issued",
  print_run: "Print run",
  booklets_dispatched: "Booklets dispatched",
  leak_traced: "Leak traced",
  trace_attempt: "Trace attempt",
};

export function init() {
  root = document.getElementById("s-ledger");
  headHost = h("div", { class: "led-head" });
  tbody = h("tbody");
  root.append(
    h("div", { class: "row", style: "justify-content:space-between;margin-bottom:22px" }, h("h1", {}, "Custody ledger")),
    headHost,
    h("div", { class: "table-wrap", style: "max-height:none" },
      h("table", {}, h("thead", {}, h("tr", {}, ["No.", "Time", "Event", "By", "Subject", "Hash"].map(t => h("th", {}, t)))), tbody)));
}

function detail(ev) {
  const p = ev.payload || {};
  switch (ev.type) {
    case "softcopy_issued": return p.holder;
    case "print_run": return `${p.copies} booklets for ${p.centres.join(", ")}`;
    case "booklets_dispatched": return `${p.first} to ${p.last}, rooms ${p.rooms.join(" and ")}`;
    case "leak_traced":
    case "trace_attempt":
      if (p.booklet) return `Booklet ${p.booklet}, ${Number(p.z).toFixed(1)}σ, via ${p.channel}`;
      if (p.source) return `${p.source}, ${p.matched} of ${p.total} marks, via ${p.channel}`;
      return `No match, via ${p.channel}`;
    case "paper_sealed": return "SHA-256 of master recorded";
    default: return "";
  }
}

export async function enter() {
  const [data, ver] = await Promise.all([api("/api/ledger?limit=300"), api("/api/ledger/verify")]);
  const ok = ver.ok;
  const reverify = h("button", { class: "btn quiet", type: "button" }, "Verify again");
  reverify.onclick = async () => { reverify.disabled = true; await enter(); };
  headHost.replaceChildren(
    h("div", { class: "seal" + (ok ? "" : " bad") }, icon(ok ? "sealOk" : "sealBad"),
      h("div", {}, h("b", {}, ok ? `Chain intact, ${ver.count} entries` : `Chain broken at entry ${ver.broken_at}`),
        h("span", { class: "hash" }, `Head ${data.head}`))),
    h("div", { class: "row" }, reverify, h("a", { class: "btn", href: "/files/ledger.json" }, icon("download"), "Export")));
  tbody.replaceChildren(...data.events.flatMap(ev => {
    const open = expanded.has(ev.seq);
    const tr = h("tr", { class: open ? "exp" : "", style: "cursor:pointer", onclick: () => {
      open ? expanded.delete(ev.seq) : expanded.add(ev.seq);
      enter();
    } },
      h("td", {}, ev.seq),
      h("td", {}, stamp(ev.ts)),
      h("td", {}, h("span", { class: "ev-type" + (ev.type === "leak_traced" ? " traced" : "") }, TYPE[ev.type] || ev.type),
        h("div", { class: "ev-detail" }, detail(ev))),
      h("td", {}, ev.actor),
      h("td", {}, ev.subject),
      h("td", { class: "hash" }, ev.hash.slice(0, 12)));
    if (!open) return [tr];
    const more = h("tr", { class: "exp" }, h("td", {}),
      h("td", { colspan: 5 }, h("div", { class: "ev-detail" },
        h("div", {}, "Hash ", h("code", {}, ev.hash)),
        h("div", {}, "Previous ", h("code", {}, ev.prev)),
        h("div", {}, "Payload ", h("code", {}, JSON.stringify(ev.payload))))));
    return [tr, more];
  }));
}

export function renderHead() {}

export async function fillMini(ul) {
  const data = await api("/api/ledger?limit=5");
  ul.replaceChildren(...data.events.map(ev =>
    h("li", {}, h("span", {}, TYPE[ev.type] || ev.type, ` ${ev.subject}`), h("span", {}, clock(ev.ts)))));
}
