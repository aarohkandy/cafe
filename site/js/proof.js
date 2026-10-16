// Every validation receipt, grouped by subject, built with DOM methods (the data never goes through innerHTML).
const num = v => Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? +v.toPrecision(4) + "" : +v.toPrecision(3) + "";

export function initProof(receipts) {
  const scored = receipts.filter(r => r.kind !== "context");
  const pass = scored.filter(r => r.ok).length;
  document.getElementById("proof-count").textContent = `Right now ${pass} of ${scored.length} pass.`;
  const groups = [...new Set(receipts.map(r => r.group))];
  const filters = document.getElementById("proof-filters"), tbody = document.querySelector("#proof-table tbody");
  let active = "All";

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  for (const name of ["All", ...groups]) {
    const b = el("button", null, name);
    b.type = "button";
    b.setAttribute("aria-pressed", String(name === active));
    b.addEventListener("click", () => { active = name; [...filters.children].forEach(x => x.setAttribute("aria-pressed", String(x === b))); render(); });
    filters.append(b);
  }

  function render() {
    tbody.replaceChildren();
    let group = null;
    for (const r of receipts) {
      if (active !== "All" && r.group !== active) continue;
      if (r.group !== group) {
        group = r.group;
        const tr = el("tr", "group"), td = el("td", null, group);
        td.colSpan = 4; tr.append(td); tbody.append(tr);
      }
      const tr = el("tr");
      const claim = el("td");
      if (r.kind === "context") claim.append(el("span", "ctx", "for context  "));
      else claim.append(el("span", r.ok ? "mark" : "mark fail", r.ok ? "✓" : "✗"));
      claim.append(document.createTextNode(r.claim));
      const val = el("td", "num", num(r.value) + (r.unit ? " " + r.unit : ""));
      const ref = el("td", "num");
      if (r.kind === "bracket") ref.textContent = `${num(r.lo)} to ${num(r.hi)}`;
      else {
        ref.textContent = num(r.reference);
        if (r.kind !== "context" && r.reference) ref.append(el("span", "err",
          r.rel === false ? `off by ${num(Math.abs(r.value - r.reference))}` : `${((r.value / r.reference - 1) * 100).toFixed(1)} %`));
      }
      tr.append(claim, val, ref, el("td", "src", r.source || ""));
      tbody.append(tr);
    }
  }
  render();
}
