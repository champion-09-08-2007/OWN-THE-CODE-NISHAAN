// Phone capture page: photograph a leak, send it, read the verdict.
import { h, rosette, ICON, stampSVG, serialRoll } from "./ui.js";

document.getElementById("mark").replaceWith(rosette(38));
document.getElementById("spin").innerHTML = ICON.spinner;

const show = id => ["idle", "busy", "done"].forEach(x => document.getElementById(x).classList.toggle("on", x === id));

async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const k = Math.min(1, 2600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k);
    c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise(res => c.toBlob(res, "image/jpeg", 0.92));
  } catch (_) {
    return file;
  }
}

async function send(file) {
  if (!file) return;
  show("busy");
  document.getElementById("prev").src = URL.createObjectURL(file);
  const msg = document.getElementById("busymsg");
  msg.textContent = "Sending";
  const blob = await shrink(file);
  const fd = new FormData();
  fd.append("file", blob, "leak.jpg");
  fd.append("channel", "phone");
  msg.textContent = "Tracing";
  let r;
  try {
    r = await (await fetch("/api/trace/photo", { method: "POST", body: fd })).json();
  } catch (e) {
    r = { status: "failed" };
  }
  render(r);
}

function fact(label, value) {
  return h("div", {}, h("dt", {}, label), h("dd", {}, value));
}

function render(r) {
  const done = document.getElementById("done");
  const again = h("button", { class: "btn primary", type: "button", onclick: () => show("idle") }, "Trace another");
  const ok = r.status === "traced" || r.status === "probable";
  const st = stampSVG(r.status === "failed" ? "inconclusive" : r.status, Date.now() / 1000);
  st.classList.add("drop-in");
  if (r.kind === "photo" && ok && r.custody) {
    const c = r.custody;
    done.replaceChildren(st, h("div", { class: "v-label" }, "Booklet"), serialRoll(r.booklet, true),
      h("dl", { class: "facts" },
        fact("Centre", `${c.city} (${c.centre})`), fact("Room", c.room), fact("Seat", c.seat),
        fact("Strength", `${r.z.toFixed(1)}σ`)), again);
  } else if (r.kind === "text" && ["traced", "probable"].includes(r.status) && r.best) {
    const cu = r.custody || {};
    done.replaceChildren(st, h("div", { class: "v-label" }, "Leaked from"),
      h("div", { class: "source-name", style: "font-size:40px" }, cu.type === "centre" ? `${cu.city}, ${cu.area}` : r.best.label),
      h("dl", { class: "facts" }, fact("Canary marks", `${r.best.matched} of ${r.best.total}`)), again);
  } else {
    const msg = {
      unregistered: "This photo does not show a page of this paper.",
      inconclusive: "Too little of the page is readable. Photograph more of it, flat and in focus.",
      failed: "Could not reach the server.",
    }[r.status] || "No match.";
    done.replaceChildren(st, h("div", { class: "m-msg" }, msg), again);
  }
  show("done");
}

["cam", "gal"].forEach(id => document.getElementById(id).addEventListener("change", e => {
  send(e.target.files[0]);
  e.target.value = "";
}));
