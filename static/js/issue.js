// Issue screen: print runs, downloads, soft copies and the booklet register.
import { api, h, icon, stamp } from "./ui.js";
import { refresh } from "./app.js";

let root, filter = "", centreFilter = "";

export function init() {
  root = document.getElementById("s-issue");
}

function stepper(value) {
  const input = h("input", { type: "number", min: 1, max: 400, value, "aria-label": "Booklets per centre", inputmode: "numeric" });
  const bump = d => { input.value = Math.max(1, Math.min(400, (+input.value || 1) + d)); };
  return { el: h("div", { class: "stepper" },
    h("button", { type: "button", "aria-label": "Fewer", onclick: () => bump(-1) }, "−"), input,
    h("button", { type: "button", "aria-label": "More", onclick: () => bump(1) }, "+")), input };
}

export function render(App) {
  const st = App.state;
  const run = st.run;
  const sp = stepper(run ? run.per_centre : 8);
  const issueBtn = h("button", { class: "btn primary", type: "button" }, "Issue new run");
  issueBtn.onclick = async () => {
    issueBtn.disabled = true;
    issueBtn.textContent = "Typesetting booklets";
    try { await api("/api/issue", { json: { per_centre: +sp.input.value } }); await refresh(); }
    finally { issueBtn.disabled = false; issueBtn.textContent = "Issue new run"; }
  };

  const left = h("div", {},
    h("div", { class: "panel" },
      h("h2", {}, "Print run"),
      h("div", { class: "field" }, h("label", {}, "Booklets per centre"), sp.el),
      issueBtn,
      run ? h("div", { class: "runline" }, `Run ${run.id}, ${run.total} booklets, issued ${stamp(run.created_at)}`) : null,
      h("div", { class: "dl" },
        h("a", { href: "/files/print.pdf", target: "_blank", rel: "noopener" }, "Print-ready booklets", h("span", {}, `${st.copies_total * st.exam.pages} pages`)),
        h("a", { href: "/files/answer-keys.csv" }, "Answer keys by centre", h("span", {}, "CSV")))),
    h("div", { class: "panel" },
      h("h2", {}, "Soft copies"),
      h("div", { class: "holders" },
        st.holders.filter(x => x.stage <= 2).map(x =>
          h("a", { href: `/files/softcopy/${x.id}.pdf`, target: "_blank", rel: "noopener" },
            h("b", {}, x.id), h("span", {}, x.label))))),
    h("div", { class: "panel" }, newExam(App)));

  const right = h("div", {}, h("h2", { style: "margin-bottom:16px" }, "Booklet register"), register(App));
  root.replaceChildren(h("div", { class: "cols" }, left, right));
}

function register(App) {
  const st = App.state;
  const centres = Object.fromEntries(st.centres.map(c => [c.code, c]));
  const tbody = h("tbody");
  const fill = () => {
    const q = filter.trim().toLowerCase();
    const rows = App.copies.filter(c => (!centreFilter || c.centre === centreFilter) &&
      (!q || c.booklet.includes(q) || c.roll.includes(q) || centres[c.centre].city.toLowerCase().includes(q)));
    tbody.replaceChildren(...rows.map(c => h("tr", {},
      h("td", {}, h("span", { class: "b" }, c.booklet)),
      h("td", {}, `${c.centre}`, h("div", { class: "muted" }, centres[c.centre].city)),
      h("td", {}, c.room), h("td", {}, c.seat), h("td", {}, c.roll),
      h("td", {}, h("a", { href: `/files/booklet/${c.booklet}.pdf`, target: "_blank", rel: "noopener" }, "PDF")))));
    count.textContent = `${rows.length} of ${App.copies.length}`;
  };
  const count = h("span", { class: "muted" });
  const search = h("input", { type: "search", placeholder: "Booklet, roll no. or city", value: filter, "aria-label": "Search booklets",
    oninput: e => { filter = e.target.value; fill(); } });
  const sel = h("select", { "aria-label": "Centre", onchange: e => { centreFilter = e.target.value; fill(); } },
    h("option", { value: "" }, "All centres"),
    st.centres.map(c => h("option", { value: c.code, selected: c.code === centreFilter ? "" : null }, `${c.code} ${c.city}`)));
  fill();
  return h("div", {},
    h("div", { class: "reg-tools" }, search, sel, count),
    h("div", { class: "table-wrap" },
      h("table", {}, h("thead", {}, h("tr", {}, ["Booklet", "Centre", "Room", "Seat", "Roll no.", ""].map(t => h("th", {}, t)))), tbody)));
}

function newExam(App) {
  const title = h("input", { type: "text", value: App.state.exam.title, maxlength: 80 });
  const sub = h("input", { type: "text", value: App.state.exam.subtitle, maxlength: 120 });
  const go = h("button", { class: "btn danger", type: "button" }, "Start new exam");
  go.onclick = async () => {
    if (!confirm("Start a new exam? The current booklets stop being traceable.")) return;
    go.disabled = true;
    go.textContent = "Setting up";
    try {
      await api("/api/exam", { json: { title: title.value, subtitle: sub.value, per_centre: 8 } });
      App.highlight = null;
      await refresh();
    } finally { go.disabled = false; go.textContent = "Start new exam"; }
  };
  return h("details", { class: "new-exam" },
    h("summary", {}, "Start a new exam"),
    h("div", { class: "field" }, h("label", {}, "Title"), title),
    h("div", { class: "field" }, h("label", {}, "Paper"), sub),
    go);
}
