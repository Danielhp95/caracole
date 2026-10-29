// The Sites tab (sites.py gives its data, the page's "sites"): each website caracole reads, a line a site. A line says
// what its index holds, what your library keeps from it, the last nightly run's requests and its status; pressed, it
// opens under itself to robots.txt in words (the closed paths worth naming, each with what it closes), the site's
// terms, how far its index has got, caracole's pace and its last request. Drawn once, from the page's data alone: in
// the file read from disk as when served, it asks nothing of anyone. Every text is put in with textContent.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const panel = byId("sites");
  if (!panel) return;
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const sites = data && data.sites && typeof data.sites === "object" ? data.sites : null;
  if (!sites) return;
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const kit = typeof caracoleRows === "function" ? caracoleRows(data.icons && typeof data.icons === "object"
    ? data.icons : {}) : null;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const number = (n) => Number(n || 0).toLocaleString("en-US");
  // A big count in a pill: 1.92 M, 642k.
  const short = (n) => {
    const v = Number(n || 0);
    if (v >= 1e6) return (v / 1e6).toFixed(2).replace(/\.?0+$/, "") + " M";
    return v >= 1e4 ? Math.round(v / 1e3) + "k" : number(v);
  };
  const share = (part, whole) => (whole ? Math.round((100 * part) / whole) : 0);
  // "<b>1,284</b> words": a figure and its unit.
  const figure = (parent, n, unit) => {
    parent.append(el("b", "", number(n)), " " + String(unit || ""));
    return parent;
  };
  const meter = (done, of, cls, label) => {
    const bar = el("span", "meter" + (cls ? " " + cls : ""));
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", label);
    bar.title = label;
    const fill = el("span");
    fill.style.width = Math.min(100, Math.max(done ? 2 : 0, share(done, of))) + "%";
    bar.append(fill);
    return bar;
  };
  const pill = (parent, parts) => {
    const p = el("span", "stat");
    for (const part of parts) p.append(typeof part === "string" ? part : el("b", "", part.b));
    parent.append(p);
  };

  const head = el("div", "sites-head");
  head.append(el("h2", "", "Sites"));
  const totals = sites.totals || {};
  pill(head, [{ b: number(totals.sites) }, " sites"]);
  pill(head, [{ b: short(totals.indexed) }, " songs indexed"]);
  pill(head, [{ b: number(totals.kept) }, " things kept from them"]);
  const run = sites.run;
  if (run && run.started) {
    pill(head, run.finished ? ["Last run ", { b: run.started + " – " + run.finished }, ", ", { b: number(run.requests) },
      " requests"] : ["Last run from ", { b: run.started }, ", ", { b: number(run.requests) }, " requests so far"]);
  } else {
    pill(head, ["No run yet"]);
  }

  const ledger = el("div", "ledger");
  const columns = el("div", "site-row head");
  columns.setAttribute("aria-hidden", "true");
  for (const name of ["Site", "Indexed", "In your library", "Last run", "Status", ""]) columns.append(el("span", "", name));
  ledger.append(columns);

  const indexedCell = (s, cls) => {
    const cell = el("span", cls);
    if (s.indexed) {
      figure(cell, s.indexed.songs, s.indexed.unit);
      if (s.progress) {
        cell.append(meter(s.progress.done, s.progress.of, "index",
          number(s.progress.done) + " of " + number(s.progress.of) + " " + s.progress.what));
      }
    } else {
      cell.append(el("span", "none", s.asked || "—"));
    }
    return cell;
  };
  const keptCell = (s, cls) => {
    const cell = el("span", cls);
    const kept = s.kept || {};
    figure(cell, kept.count, kept.unit);
    cell.append(el("small", "", share(kept.songs, sites.songs) + "% of your songs"));
    return cell;
  };
  const nightCell = (s, cls) => {
    const cell = el("span", cls);
    if (s.night) {
      cell.append(el("b", "", number(s.night.used) + " / " + number(s.night.budget)));
      cell.append(meter(s.night.used, s.night.budget, "",
        number(s.night.used) + " of " + number(s.night.budget) + " " + s.night.unit));
    } else {
      cell.append(el("span", "none", "—"));
    }
    return cell;
  };

  for (const s of listOf(sites.list)) {
    if (!s || typeof s.key !== "string") continue;
    const status = s.status || {};
    const wrap = el("div", "site" + (status.state === "off" ? " is-off" : ""));
    const line = el("button", "site-row site-line");
    line.type = "button";
    line.dataset.site = s.key;
    line.setAttribute("aria-expanded", "false");
    line.setAttribute("aria-controls", "site-more-" + s.key);
    const id = el("span", "site-id");
    const icon = el("span", "site-icon");
    const mark = kit ? kit.sourceMark(s.key) : null;
    if (mark) {
      mark.setAttribute("alt", "");  // the name beside it says which
      mark.removeAttribute("title");
      mark.setAttribute("aria-hidden", "true");
      icon.append(mark);
    }
    const names = el("span", "site-names");
    names.append(el("span", "site-name", s.name), el("span", "site-role", s.role));
    id.append(icon, names);
    line.append(id, indexedCell(s, "site-cell indexed"), keptCell(s, "site-cell kept"),
      nightCell(s, "site-cell night"));
    const badge = el("span", "badge " + String(status.state || "ok"), status.label || "OK");
    if (status.detail) badge.title = status.detail;
    const chev = el("span", "chev", "⌄");
    chev.setAttribute("aria-hidden", "true");
    line.append(badge, chev);

    const more = el("div", "site-more");
    more.id = "site-more-" + s.key;
    more.setAttribute("role", "region");
    more.setAttribute("aria-label", String(s.name) + ": more");
    more.hidden = true;
    // On a phone the line keeps the site and its status alone: its figures are here.
    const figures = el("dl", "more-figures");
    for (const [name, cell] of [["Indexed", indexedCell(s, "")], ["In your library", keptCell(s, "")],
      ["Last run", nightCell(s, "")]]) {
      const row = el("div");
      const dd = el("dd");
      dd.append(cell);
      row.append(el("dt", "", name), dd);
      figures.append(row);
    }
    const robots = s.robots || {};
    const said = el("div", "more-robots");
    const title = el("h3");
    title.append(el("span", "robots-tag", "robots.txt"));
    said.append(title, el("p", "", robots.text));
    const paths = listOf(robots.paths);
    if (paths.length) {
      const closed = el("div", "closed");
      for (const [path, words] of paths) {
        const code = el("code", "", path);
        code.title = words;
        closed.append(code);
      }
      if (robots.more) closed.append(el("span", "more", "and " + number(robots.more) + " more"));
      said.append(closed);
    }
    if (s.terms) said.append(el("p", "terms", s.terms));
    const facts = el("div", "more-facts");
    if (s.indexed && s.indexed.detail) {
      const what = el("div");
      what.append(el("h3", "", "Its index"), el("p", "", s.indexed.detail));
      if (s.progress) {
        what.append(el("p", "", number(s.progress.done) + " of " + number(s.progress.of) + " " + s.progress.what),
          meter(s.progress.done, s.progress.of, "index", s.progress.what));
      }
      facts.append(what);
    }
    if (s.kept && s.kept.detail) {
      const kept = el("div");
      kept.append(el("h3", "", "In your library"), el("p", "", s.kept.detail));
      facts.append(kept);
    }
    if (status.detail) {
      const why = el("div");
      why.append(el("h3", "", status.label), el("p", "", status.detail));
      facts.append(why);
    }
    const pace = el("div");
    pace.append(el("h3", "", "Pace"), el("p", "", s.pace));
    const last = el("div");
    last.append(el("h3", "", "Last request"), el("p", "", s.last || "None yet"));
    facts.append(pace, last);
    more.append(figures, said, facts);

    line.addEventListener("click", () => {
      const open = line.getAttribute("aria-expanded") !== "true";
      line.setAttribute("aria-expanded", String(open));
      more.hidden = !open;
    });
    wrap.append(line, more);
    ledger.append(wrap);
  }
  panel.replaceChildren(head, ledger);
})();
