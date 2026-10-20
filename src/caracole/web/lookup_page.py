"""The lookup page of ``caracole serve``: search as you type, pick the song or the tab, read its sheet.

It searches your library and the offline Ultimate Guitar index as you type
(``GET /api/search``, a few milliseconds a query on a full index), so finding
a song costs no request to any site. Picking a song, or one of its versions,
looks it up now (``POST /lookup``: one ``caracole get``, which records the
pick in overrides.toml), and the page follows the request
(``GET /api/jobs/<id>``) stage by stage: the sheet shows the moment it is
kept, then the PDF, the lyrics and the rest arrive. A song of your library
with a sheet opens at once, with no request at all.

Like index.html it builds every element with ``createElement`` and
``textContent``, never ``innerHTML``: names come from UG's slugs and your own
wanted.txt. Its one script and stylesheet are allowed by their hashes, it may
connect to the server alone, and it loads nothing else.
"""

from __future__ import annotations

from html import escape

from caracole.library_page import BASE_STYLE, sha256_source

STYLE = BASE_STYLE + """
.page { max-width: 980px; }
.lede { max-width: 72ch; margin: 2px 0 14px; color: var(--muted); }
.search { position: sticky; top: 0; z-index: 2; padding: 10px 0; background: var(--bg); }
.search input { width: 100%; height: 54px; padding: 0 16px; border-radius: 14px; border: 1px solid var(--border-strong);
  background: var(--surface); color: var(--text); font: inherit; font-size: 1.15rem; box-shadow: var(--shadow); }
.search input:focus { border-color: var(--focus); outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 30%, transparent); }
.status { min-height: 1.4em; margin: 6px 2px 0; color: var(--muted); font-size: .85rem; }
.group { margin: 18px 0 6px; color: var(--muted); font-size: .78rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; }
.hits { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.hit { padding: 10px 12px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }
.hit-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.names { flex: 1 1 14rem; min-width: 0; }
.title { font-weight: 650; overflow-wrap: anywhere; }
.artist { color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
.counts { color: var(--muted); font-size: .8rem; }
.acts { display: flex; flex-wrap: wrap; gap: 6px; }
.versions { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 2px; padding: 0; list-style: none; }
.hint { max-width: 72ch; color: var(--muted); font-size: .85rem; white-space: pre-wrap; }
details.by-name { margin: 22px 0 0; }
details.by-name summary { color: var(--muted); font-size: .9rem; font-weight: 600; cursor: pointer; }
.by-name form { display: grid; gap: 10px; margin-top: 10px; grid-template-columns: 1fr; }
.reader { margin: 22px 0 0; padding: 14px 16px; border: 1px solid var(--border); border-radius: 16px;
  background: var(--surface); box-shadow: var(--shadow); }
.reader h2 { margin: 0; font-size: 1.25rem; overflow-wrap: anywhere; }
.said { margin: 4px 0 10px; color: var(--muted); font-size: .9rem; }
.stages { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; padding: 0; list-style: none; }
.stage { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px;
  background: var(--raised); font-size: .78rem; }
.stage.running { color: var(--wanted); background: var(--wanted-bg); font-weight: 650; }
.stage.done { color: var(--found); background: var(--found-bg); }
.stage.failed { color: var(--failed); background: var(--failed-bg); }
.stage.skipped, .stage.waiting { color: var(--ignored); }
.files { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
pre.sheet { margin: 0; padding: 12px; overflow-x: auto; border-radius: 10px; background: var(--bg);
  font: .88rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre; }
@media (min-width: 720px) {
  .by-name form { grid-template-columns: 1fr 1fr auto; align-items: end; }
  pre.sheet { font-size: .95rem; }
}
"""

SCRIPT = r"""
"use strict";
const root = document.getElementById("lookup");
const csrf = root.dataset.csrf;
const q = document.getElementById("q");
const status = document.getElementById("status");
const results = document.getElementById("results");
const reader = document.getElementById("reader");
const MIN = 3;
let typed = 0, inflight = null, timer = null, polling = null, shown = "", lastStages = "";

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function href(path) { return "/" + path.split("/").map(encodeURIComponent).join("/"); }
function letters(s) { return (s.match(/[\p{L}\p{N}]/gu) || []).length; }
function han(s) { return /\p{Script=Han}/u.test(s); }
function button(label, cls, onclick) {
  const b = el("button", "btn " + (cls || "small"), label);
  b.type = "button";
  b.addEventListener("click", onclick);
  return b;
}
function counts(c) {
  const names = {"chords": "chords", "tabs": "tabs", "guitar-pro": "Guitar Pro", "power": "Power Tab"};
  return Object.entries(c).map(([k, n]) => n + " " + (names[k] || k)).join(" · ");
}

// --- searching ------------------------------------------------------------------------------

function search() {
  const text = q.value.trim().replace(/\s+/g, " ");
  if (letters(text) < (han(text) ? 2 : MIN)) {
    results.replaceChildren();
    status.textContent = text ? "Keep typing…" : "";
    return;
  }
  const mine = ++typed;
  if (inflight) inflight.abort();
  inflight = new AbortController();
  status.textContent = "Searching…";
  fetch("/api/search?q=" + encodeURIComponent(text), {signal: inflight.signal, headers: {"Accept": "application/json"}})
    .then(r => r.json())
    .then(data => {
      if (mine !== typed) return;
      if (data.superseded) { timer = setTimeout(search, 150); return; }
      show(data);
    })
    .catch(e => { if (e.name !== "AbortError") status.textContent = "The search failed: " + e.message; });
}

function show(data) {
  results.replaceChildren();
  const n = data.library.length + data.index.length;
  status.textContent = n ? "" : "Nothing matches.";
  if (data.library.length) {
    results.append(el("h2", "group", "In your library"));
    const list = el("ul", "hits");
    for (const s of data.library) list.append(librarySong(s));
    results.append(list);
  }
  if (data.index.length) {
    results.append(el("h2", "group", "On Ultimate Guitar"));
    const list = el("ul", "hits");
    for (const h of data.index) list.append(ugSong(h));
    results.append(list);
  }
  if (data.hint) results.append(el("p", "hint", data.hint));
}

function librarySong(s) {
  const li = el("li", "hit"), head = el("div", "hit-head"), names = el("div", "names"), acts = el("div", "acts");
  names.append(el("div", "title", s.title), el("div", "artist", s.artist));
  head.append(names, el("span", "badge " + s.status, s.status));
  if (s.files.sheet) acts.append(button("Read", "small primary", () => read(s.display, s.files)));
  acts.append(button(s.files.sheet ? "Fetch again" : "Get it now", "small",
                     () => lookUp({artist: s.artist, title: s.title}, s.display)));
  head.append(acts);
  li.append(head);
  return li;
}

function ugSong(h) {
  const li = el("li", "hit"), head = el("div", "hit-head"), names = el("div", "names"), acts = el("div", "acts");
  names.append(el("div", "title", h.title), el("div", "artist", h.artist), el("div", "counts", counts(h.counts)));
  head.append(names);
  acts.append(button(h.song ? "Get it again" : "Get it", "small primary",
                     () => lookUp({artist: h.artist, title: h.title, ug: h.ug}, h.artist + " - " + h.title)));
  const versions = el("ul", "versions");
  versions.hidden = true;
  for (const t of h.tabs) {
    const name = (t.type === "guitar-pro" ? "Guitar Pro" : t.type === "power" ? "Power Tab" : t.type)
      + (t.label ? " · " + t.label : "") + " #" + t.id;
    const item = el("li");
    item.append(button(name, "small", () => lookUp({artist: h.artist, title: h.title, ug: h.ug, tab: t.url},
                                                     h.artist + " - " + h.title)));
    versions.append(item);
  }
  if (h.tabs.length) {
    const toggle = button("Versions", "small", () => {
      versions.hidden = !versions.hidden;
      toggle.setAttribute("aria-expanded", String(!versions.hidden));
    });
    toggle.setAttribute("aria-expanded", "false");
    acts.append(toggle);
  }
  head.append(acts);
  li.append(head, versions);
  return li;
}

q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 120); });
q.addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const first = results.querySelector("button.primary");
  if (first) { e.preventDefault(); first.click(); }
});

// --- looking up, and reading -----------------------------------------------------------------

function lookUp(pick, display) {
  const body = new URLSearchParams({csrf, artist: pick.artist, title: pick.title});
  if (pick.ug) body.set("ug", pick.ug);
  if (pick.tab) body.set("tab", pick.tab);
  openReader(display, "Asking for it…");
  fetch("/lookup", {method: "POST", body, headers: {"Accept": "application/json"}})
    .then(r => r.json().then(data => ({ok: r.ok, data})))
    .then(({ok, data}) => {
      if (!ok) { said(data.error || "caracole refused it."); return; }
      history.replaceState(null, "", "/lookup?job=" + data.job);
      follow(data.url);
    })
    .catch(e => said("The request failed: " + e.message));
}

function openReader(display, words) {
  reader.hidden = false;
  reader.replaceChildren(el("h2", null, display), el("p", "said", words), el("ul", "stages"), el("div", "files"),
                         el("pre", "sheet"));
  reader.querySelector("pre").hidden = true;
  shown = ""; lastStages = "";
  if (polling) clearTimeout(polling);
  reader.scrollIntoView({block: "start", behavior: "smooth"});
}
function said(words) { const p = reader.querySelector(".said"); if (p) p.textContent = words; }

function follow(url) {
  fetch(url, {headers: {"Accept": "application/json"}})
    .then(r => r.ok ? r.json() : Promise.reject(new Error("that request is gone")))
    .then(job => {
      progress(job);
      if (job.active) polling = setTimeout(() => follow(url), 500);
    })
    .catch(e => said(e.message));
}

function progress(job) {
  if (job.song && reader.querySelector("h2")) reader.querySelector("h2").textContent = job.song.display;
  const stages = reader.querySelector(".stages");
  stages.replaceChildren();
  for (const s of job.steps) {
    const li = el("li", "stage " + s.state, s.label);
    if (s.detail) li.title = s.detail;
    stages.append(li);
  }
  const running = job.steps.find(s => s.state === "running");
  if (job.files.sheet) {
    said(job.active ? "Here it is" + (job.seconds_to_sheet !== null ? ", in " + job.seconds_to_sheet.toFixed(1) + " s" : "")
         + (running ? "; still getting: " + running.label.toLowerCase() : "") : "Done.");
  } else if (job.active) {
    said(job.state === "queued" ? "Waiting for the request before it…" : (running ? running.label + "…" : "Working…"));
  } else {
    const why = job.steps.filter(s => s.detail && s.state !== "done").map(s => s.label + ": " + s.detail);
    said("No sheet this time. " + why.join(" "));
  }
  const now = job.steps.map(s => s.state).join(",");
  links(job.files);
  if (job.files.sheet && (now !== lastStages || !shown)) sheet(job.files.sheet);
  lastStages = now;
}

function links(files) {
  const box = reader.querySelector(".files");
  box.replaceChildren();
  for (const [name, label] of [["viewer", "Viewer"], ["pdf", "PDF"], ["sheet", "Text"]]) {
    if (!files[name]) continue;
    const a = el("a", "btn small", label);
    a.href = href(files[name]);
    box.append(a);
  }
  const jobs = el("a", "btn small", "Requests");
  jobs.href = "/jobs";
  box.append(jobs);
}

function sheet(path) {
  fetch(href(path)).then(r => r.ok ? r.text() : Promise.reject(new Error(r.status))).then(text => {
    const pre = reader.querySelector("pre");
    if (!pre || text === shown) return;
    shown = text;
    pre.textContent = text;
    pre.hidden = false;
  }).catch(() => {});
}

function read(display, files) {
  openReader(display, "From your library.");
  links(files);
  sheet(files.sheet);
}

// --- by name, for a song the index doesn't know -----------------------------------------------

document.getElementById("by-name").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  const artist = f.artist.value.trim(), title = f.title.value.trim();
  if (artist && title) lookUp({artist, title}, artist + " - " + title);
});

const params = new URLSearchParams(location.search);
const job = params.get("job");
if (job && /^\d+$/.test(job)) { openReader("Your request", "Following it…"); follow("/api/jobs/" + job); }
if (params.get("q")) { q.value = params.get("q"); search(); }
q.focus();
"""

LOOKUP_CSP = (
    f"default-src 'none'; script-src {sha256_source(SCRIPT)}; style-src {sha256_source(STYLE)}; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

_BODY = """<body>
<div class="page" id="lookup" data-csrf="__CSRF__">
<header class="masthead">
  <div>
    <p class="app"><a href="/">caracole</a></p>
    <h1>Look up a song</h1>
  </div>
  <nav class="links" aria-label="Pages"><a class="navlink" href="/">Library</a><a class="navlink" href="/jobs">Requests</a></nav>
</header>
<p class="lede">Type a song or an artist. caracole searches your library and its offline copy of Ultimate Guitar's
  index as you type, asking no site anything; pick a song, or one of its versions, and its sheet is here in
  seconds.</p>
<div class="search" role="search">
  <label class="visually-hidden" for="q">Song or artist</label>
  <input id="q" type="search" placeholder="Song or artist" autocomplete="off" autocapitalize="off" autocorrect="off"
    spellcheck="false" enterkeyhint="search">
  <p class="status" id="status" aria-live="polite"></p>
</div>
<div id="results"></div>
<details class="by-name">
  <summary>Not in the list? Look it up by name</summary>
  <form id="by-name" method="post" action="/lookup">
    <input type="hidden" name="csrf" value="__CSRF__">
    <label class="f">Artist<input name="artist" required maxlength="200" autocomplete="off"></label>
    <label class="f">Title<input name="title" required maxlength="300" autocomplete="off"></label>
    <button class="btn primary" type="submit">Look it up</button>
  </form>
</details>
<section class="reader" id="reader" aria-live="polite" hidden></section>
</div>
"""


def lookup_page(csrf: str) -> str:
    """The whole page, with the form token every POST carries."""
    token = escape(csrf, quote=True)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="no-referrer">\n'
        f"<title>Look up · caracole</title>\n<style>{STYLE}</style>\n</head>\n"
        + _BODY.replace("__CSRF__", token)
        + f"<script>{SCRIPT}</script>\n</body>\n</html>\n"
    )
