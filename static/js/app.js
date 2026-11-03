import { api, h, rosette, clock, STATUS, CHANNEL, toast, icon } from "./ui.js";
import { drawChain } from "./chain.js";
import * as Trace from "./trace.js";
import * as Issue from "./issue.js";
import * as Compare from "./compare.js";
import * as Ledger from "./ledger.js";

export const App = {
  state: null,
  copies: [],
  highlight: null,
  route: "overview",
  unseen: 0,
};

document.getElementById("brandmark").replaceWith(rosette(42));

export async function refresh() {
  const [st, copies] = await Promise.all([api("/api/state"), api("/api/copies")]);
  App.state = st;
  App.copies = copies;
  if (App.highlight === null && st.traces.length) App.highlight = highlightFor(st.traces[0].summary);
  renderAll();
}

export function highlightFor(sum) {
  if (!sum || !["traced", "probable", "stage"].includes(sum.status)) return null;
  if (sum.kind === "photo") return { kind: "photo", booklet: sum.booklet, centre: sum.centre };
  return { kind: "text", source: sum.status === "stage" ? null : sum.source, stage: sum.stage };
}

function renderAll() {
  renderOverview();
  Issue.render(App);
  Trace.renderHistory(App);
  Ledger.renderHead(App);
  const pq = document.getElementById("phoneqr");
  if (!pq.src) pq.src = "/api/phone-qr.svg";
  document.getElementById("phoneurl").textContent = App.state.phone_url;
}

// ------------------------------------------------------------ overview
const ov = document.getElementById("s-overview");

export function summaryLine(t) {
  const sm = t.summary || t;
  if (sm.kind === "photo") {
    if (sm.booklet && sm.status !== "inconclusive") return [`Booklet ${sm.booklet}`, `${sm.centre}, room ${sm.room}`];
    return ["Photo", STATUS[sm.status] || sm.status];
  }
  if (sm.status === "stage") return ["Text leak", `${sm.stage} stage`];
  if (sm.label && sm.status !== "inconclusive") return [sm.label, `${sm.matched} of ${sm.total} marks match`];
  return ["Text leak", STATUS[sm.status] || sm.status];
}

export function feedList(traces, onPick) {
  if (!traces.length) {
    return h("div", { class: "empty" }, "No leaks traced yet.",
      h("a", { class: "btn primary", href: "#/trace" }, "Trace a leak"));
  }
  return h("ul", { class: "feed" }, traces.map(t => {
    const [a, b] = summaryLine(t);
    return h("li", { onclick: () => onPick(t) },
      h("span", { class: "when" }, clock(t.ts)),
      h("span", { class: "what" }, h("b", {}, a), h("span", {}, `${b}, ${CHANNEL[t.channel] || t.channel}`)),
      h("span", { class: `chip ${t.status}` }, STATUS[t.status] || t.status));
  }));
}

function renderOverview() {
  const st = App.state;
  const presses = st.holders.filter(x => x.stage === 3).length;
  const led = st.ledger;
  const head = h("div", { class: "ov-head" },
    h("div", {},
      h("h1", {}, st.exam.title),
      h("div", { class: "sub" }, st.exam.subtitle)),
    h("dl", { class: "docket" },
      h("div", {}, h("dt", {}, "Booklets"), h("dd", {}, st.copies_total)),
      h("div", {}, h("dt", {}, "Centres"), h("dd", {}, st.centres.length)),
      h("div", {}, h("dt", {}, "Leaks traced"), h("dd", {}, st.leak_count)),
      h("div", {}, h("dt", {}, "Custody chain"), h("dd", { class: "ok", id: "ov-chainstate" }, "Intact"))));
  const chainHost = h("div", { class: "chain-wrap" });
  const feed = h("div", {}, h("h2", {}, "Recent traces"),
    feedList(st.traces.slice(0, 7), t => openTrace(t.id)));
  const ledger = h("div", {}, h("h2", {}, "Ledger"),
    h("div", { class: "seal", id: "ov-seal" }, icon("sealOk"),
      h("div", {}, h("b", {}, `${led.count} entries sealed`), h("span", { class: "hash" }, led.head.slice(0, 32)))),
    h("ul", { class: "mini-ledger", id: "ov-mini" }));
  ov.replaceChildren(head, chainHost, h("div", { class: "ov-grid" }, feed, ledger));
  requestAnimationFrame(() => drawChain(chainHost, st, App.copies, App.highlight));
  Ledger.fillMini(document.getElementById("ov-mini"));
  api("/api/ledger/verify").then(v => {
    const dd = document.getElementById("ov-chainstate");
    const seal = document.getElementById("ov-seal");
    if (!v.ok && dd) {
      dd.textContent = "Broken";
      dd.className = "bad";
      seal.className = "seal bad";
      seal.firstChild.replaceWith(icon("sealBad"));
    }
  }).catch(() => {});
}

window.addEventListener("resize", () => {
  if (App.route === "overview" && App.state) {
    const host = ov.querySelector(".chain-wrap");
    if (host) drawChain(host, App.state, App.copies, App.highlight);
  }
});

// ------------------------------------------------------------ routing
const SCREENS = ["overview", "issue", "trace", "compare", "ledger"];

function go() {
  const r = (location.hash.replace("#/", "") || "overview").split("?")[0];
  App.route = SCREENS.includes(r) ? r : "overview";
  SCREENS.forEach(x => {
    document.getElementById(`s-${x}`).classList.toggle("on", x === App.route);
    document.querySelector(`.tab[data-route="${x}"]`).setAttribute("aria-current", x === App.route ? "page" : "false");
  });
  if (App.route === "trace") setUnseen(0);
  if (App.route === "compare") Compare.enter(App);
  if (App.route === "ledger") Ledger.enter(App);
  if (App.route === "overview" && App.state) renderOverview();
}
window.addEventListener("hashchange", go);

function setUnseen(n) {
  App.unseen = n;
  const c = document.getElementById("tracecount");
  c.textContent = n;
  c.classList.toggle("hidden", !n);
}

export async function openTrace(id) {
  const r = await api(`/api/trace/${id}`);
  location.hash = "#/trace";
  Trace.show(App, r, false);
}

// ------------------------------------------------------------ live events
function connect() {
  const live = document.getElementById("live");
  const es = new EventSource("/api/events");
  es.onopen = () => live.classList.add("on");
  es.onerror = () => live.classList.remove("on");
  es.onmessage = async (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "trace") {
      const sm = ev.summary;
      const hl = highlightFor(sm);
      if (hl) App.highlight = hl;
      await refresh();
      const remote = sm.channel === "phone" || sm.channel === "telegram";
      if (remote) {
        const [a, b] = summaryLine(sm);
        if (App.route !== "trace") setUnseen(App.unseen + 1);
        toast(`${CHANNEL[sm.channel]}: ${a}`, b, () => openTrace(sm.id));
        if (App.route === "trace" || App.route === "overview") {
          const r = await api(`/api/trace/${sm.id}`);
          location.hash = "#/trace";
          Trace.show(App, r, true);
        }
      }
    } else if (ev.type === "issued") {
      await refresh();
    }
  };
}

// ------------------------------------------------------------ phone popover
const pop = document.getElementById("phonepop");
document.getElementById("phonebtn").addEventListener("click", (e) => {
  e.stopPropagation();
  pop.classList.toggle("hidden");
});
document.addEventListener("click", (e) => { if (!pop.contains(e.target)) pop.classList.add("hidden"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") pop.classList.add("hidden"); });

Trace.init(App);
Issue.init(App);
Compare.init(App);
Ledger.init(App);
refresh().then(() => { go(); connect(); });
