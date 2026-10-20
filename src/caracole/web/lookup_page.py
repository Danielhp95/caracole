"""The lookup page of ``caracole serve``: search as you type, pick the song or the tab, read its sheet.

It searches your library and the offline Ultimate Guitar index as you type
(``GET /api/search``: 5–25 ms a query on a full index, up to about 0.15 s for
very common words, ug/key_search.py), so finding
a song costs no request to any site. Enter picks the first result of the
query typed, never of an older one still on the screen. Picking a song, or
one of its versions, looks it up now (``POST /lookup``: one ``caracole get``,
which records the pick in overrides.toml; a song your library has, under any
name, is posted as that song, by its id), and the page follows the request
(``GET /api/jobs/<id>``) stage by stage, the results set aside so that it sits
under the search box: the sheet shows the moment it is kept, scrolled into
view once, then the PDF, the lyrics and the rest arrive. The progress line
says what the running stage waits for, and the reasons of the stages left are
listed, not hidden in tooltips. A song of your library with a sheet opens at
once, with no request at all.

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
  background: var(--surface); box-shadow: var(--shadow); scroll-margin-top: var(--bar, 112px); }
.reader-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 12px; }
.reader h2 { margin: 0; font-size: 1.25rem; overflow-wrap: anywhere; }
.version { display: inline-flex; align-items: center; gap: 4px; }
.on-ug { color: var(--muted); font-size: .78rem; }
details.why { margin: 0 0 10px; color: var(--muted); font-size: .85rem; }
details.why summary { cursor: pointer; }
details.why ul { margin: 6px 0 0; padding-left: 1.2em; }
details.why li.failed { color: var(--failed); }
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
const bar = document.querySelector(".search");
const status = document.getElementById("status");
const results = document.getElementById("results");
const byName = document.getElementById("by-name-box");
const reader = document.getElementById("reader");
// The reader's parts stay the same nodes: only the progress line is a live region, read out as it changes.
const heading = document.getElementById("reader-title");
const backToResults = document.getElementById("back");
const saying = document.getElementById("said");
const stageList = document.getElementById("stages");
const whyBox = document.getElementById("why");
const whyList = document.getElementById("why-list");
const fileLinks = document.getElementById("files");
const sheetText = document.getElementById("sheet");
const MIN = 3;
const KINDS = {"chords": "Chords", "tabs": "Tab", "guitar-pro": "Guitar Pro", "power": "Power Tab"};
let typed = 0, inflight = null, timer = null, polling = null, shown = "", lastStages = "";
let shownFor = null;  // the query the results on the screen answer
let enterFor = null;  // a query Enter was pressed for before its results came: its first one is picked then
let scrolled = false;  // the sheet was brought into view once already

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function href(path) { return "/" + path.split("/").map(encodeURIComponent).join("/"); }
function letters(s) { return (s.match(/[\p{L}\p{N}]/gu) || []).length; }
function han(s) { return /\p{Script=Han}/u.test(s); }
function typedText() { return q.value.trim().replace(/\s+/g, " "); }
function button(label, cls, onclick, aria) {
  const b = el("button", "btn " + (cls || "small"), label);
  b.type = "button";
  if (aria) b.setAttribute("aria-label", aria);
  b.addEventListener("click", onclick);
  return b;
}
function counts(c) {
  const names = {"chords": "chords", "tabs": "tabs", "guitar-pro": "Guitar Pro", "power": "Power Tab"};
  return Object.entries(c).map(([k, n]) => n + " " + (names[k] || k)).join(" · ");
}
// The sticky search box covers the top of the page: what is scrolled into view lands below it.
function measureBar() { document.documentElement.style.setProperty("--bar", Math.ceil(bar.offsetHeight + 8) + "px"); }

// --- searching ------------------------------------------------------------------------------

function search() {
  const text = typedText();
  if (letters(text) < (han(text) ? 2 : MIN)) {
    results.replaceChildren();
    shownFor = null;
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
      if (data.error) { status.textContent = data.error; return; }  // the database, or signing in
      show(data, text);
    })
    .catch(e => { if (e.name !== "AbortError") status.textContent = "The search failed: " + e.message; });
}

function show(data, text) {
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
  shownFor = text;
  if (enterFor === text) { enterFor = null; pickFirst(); }
}

function pickFirst() {
  const first = results.querySelector("button.primary");
  if (first) first.click();
}

function librarySong(s) {
  const li = el("li", "hit"), head = el("div", "hit-head"), names = el("div", "names"), acts = el("div", "acts");
  names.append(el("div", "title", s.title), el("div", "artist", s.artist));
  head.append(names, el("span", "badge " + s.status, s.status));
  if (s.files.sheet) acts.append(button("Read", "small primary", () => read(s.display, s.files), "Read " + s.display));
  const again = s.files.sheet ? "Fetch again" : "Get it now";
  acts.append(button(again, "small", () => lookUp({song: s.id}, s.display),
                     s.files.sheet ? "Fetch " + s.display + " again" : "Get " + s.display + " now"));
  head.append(acts);
  li.append(head);
  return li;
}

function ugSong(h) {
  const li = el("li", "hit"), head = el("div", "hit-head"), names = el("div", "names"), acts = el("div", "acts");
  names.append(el("div", "title", h.title), el("div", "artist", h.artist), el("div", "counts", counts(h.counts)));
  head.append(names);
  // A song your library has (under its own names, maybe): looked up as that song, never as a second one.
  const mine = h.library;
  const display = mine ? mine.display : h.artist + " - " + h.title;
  const pick = extra => Object.assign(mine ? {song: mine.id} : {artist: h.artist, title: h.title}, {ug: h.ug}, extra);
  acts.append(button(mine ? "Get it again" : "Get it", "small primary", () => lookUp(pick({}), display),
                     (mine ? "Get " + display + " again" : "Get " + display) + " from Ultimate Guitar"));
  const versions = el("ul", "versions");
  versions.hidden = true;
  const nth = {};
  for (const t of h.tabs) {
    // Numbered within its kind, in the index's order (no ratings there): "Chords 2 of 13 · acoustic".
    nth[t.type] = (nth[t.type] || 0) + 1;
    const kind = KINDS[t.type] || t.type;
    const name = kind + " " + nth[t.type] + " of " + (h.counts[t.type] || nth[t.type]) + (t.label ? " · " + t.label : "");
    const item = el("li", "version");
    item.append(button(name, "small", () => lookUp(pick({tab: t.url}), display), "Get " + name + ", " + display));
    const ug = el("a", "on-ug", "on UG");
    ug.href = t.url;
    ug.target = "_blank";
    ug.rel = "noopener noreferrer";
    ug.setAttribute("aria-label", name + ", " + display + ", on Ultimate Guitar");
    item.append(ug);
    versions.append(item);
  }
  if (h.tabs.length) {
    const toggle = button("Versions", "small", () => {
      versions.hidden = !versions.hidden;
      toggle.setAttribute("aria-expanded", String(!versions.hidden));
    }, "Versions of " + display);
    toggle.setAttribute("aria-expanded", "false");
    acts.append(toggle);
  }
  head.append(acts);
  li.append(head, versions);
  return li;
}

q.addEventListener("input", () => {
  enterFor = null;
  expand();
  clearTimeout(timer);
  timer = setTimeout(search, 120);
});
q.addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  if (results.hidden) { expand(); return; }  // after a pick: the results again, not the pick again
  const text = typedText();
  if (text === shownFor) { pickFirst(); return; }
  // The results on the screen answer an older query: search now, and pick the first of its answer.
  enterFor = text;
  clearTimeout(timer);
  search();
});

// While a sheet is read the results step aside, so it sits right under the search box; typing brings them back.
function collapse() {
  results.hidden = true;
  byName.hidden = true;
  backToResults.hidden = !results.childElementCount;
}
function expand() {
  if (!results.hidden) return;
  results.hidden = false;
  byName.hidden = false;
  backToResults.hidden = true;
}
backToResults.addEventListener("click", () => { expand(); window.scrollTo({top: 0}); q.focus(); });

// --- looking up, and reading -----------------------------------------------------------------

function lookUp(pick, display) {
  const body = new URLSearchParams({csrf});
  for (const name of ["song", "artist", "title", "ug", "tab"]) if (pick[name]) body.set(name, pick[name]);
  openReader(display, "Asking for it…");
  fetch("/lookup", {method: "POST", body, headers: {"Accept": "application/json"}})
    .then(r => r.text().then(text => ({r, text})))
    .then(({r, text}) => {
      let data = null;
      try { data = JSON.parse(text); } catch (e) { data = null; }
      if (!r.ok || !data) { refused(r.status, data, text); return; }
      history.replaceState(null, "", "/lookup?job=" + data.job);
      follow(data.url);
    })
    .catch(e => said("The request failed: " + e.message));
}

// A refusal: its sentence; a page's, as its text. A form token older than the server, or signing in, needs a reload.
function refused(code, data, text) {
  let why = data && data.error;
  if (!why) {
    const page = new DOMParser().parseFromString(text || "", "text/html");
    const words = (page.querySelector("main, .page, body") || page.documentElement).textContent || "";
    why = words.replace(/\s+/g, " ").trim().slice(0, 240) || "caracole answered " + code + ".";
  }
  said(why);
  if ((data && data.reload) || code === 401 || code === 403) {
    const again = el("a", "btn small primary", "Reload the page");
    again.href = location.pathname + location.search;
    fileLinks.replaceChildren(again);
  }
}

function openReader(display, words) {
  collapse();
  reader.hidden = false;
  heading.textContent = display;
  saying.textContent = words;
  stageList.replaceChildren();
  whyList.replaceChildren();
  whyBox.hidden = true;
  fileLinks.replaceChildren();
  sheetText.textContent = "";
  sheetText.hidden = true;
  shown = ""; lastStages = ""; scrolled = false;
  if (polling) clearTimeout(polling);
  measureBar();
  reader.scrollIntoView({block: "start"});
}
function said(words) { if (saying.textContent !== words) saying.textContent = words; }

function follow(url) {
  fetch(url, {headers: {"Accept": "application/json"}})
    .then(r => r.ok ? r.json() : Promise.reject(new Error("that request is gone")))
    .then(job => {
      progress(job);
      if (job.active) polling = setTimeout(() => follow(url), 500);
    })
    .catch(e => said(e.message));
}

function doing(stage) { return stage.detail ? stage.label + ": " + stage.detail : stage.label + "…"; }

function progress(job) {
  if (job.song) heading.textContent = job.song.display;
  stageList.replaceChildren();
  for (const s of job.steps) {
    const li = el("li", "stage " + s.state, s.label);
    if (s.detail) li.title = s.detail;
    stageList.append(li);
  }
  // What was left, and why, where touch and keys reach it too (a title shows on hovering alone).
  const why = job.steps.filter(s => s.detail && (s.state === "skipped" || s.state === "failed"));
  whyList.replaceChildren(...why.map(s => el("li", s.state, s.label + ": " + s.detail)));
  whyBox.hidden = !why.length;
  const running = job.steps.find(s => s.state === "running");
  if (job.files.sheet) {
    said(job.active ? "Here it is" + (job.seconds_to_sheet !== null ? ", in " + job.seconds_to_sheet.toFixed(1) + " s" : "")
         + (running ? "; still getting: " + running.label.toLowerCase() : "") : "Done.");
  } else if (job.active) {
    said(job.state === "queued" ? "Waiting for the request before it…" : (running ? doing(running) : "Working…"));
  } else {
    const failed = job.steps.filter(s => s.detail && s.state !== "done").map(s => s.label + ": " + s.detail);
    said("No sheet this time. " + failed.join(" "));
  }
  const now = job.steps.map(s => s.state).join(",");
  links(job.files);
  if (job.files.sheet && (now !== lastStages || !shown)) sheet(job.files.sheet);
  lastStages = now;
}

function links(files) {
  const box = fileLinks;
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
    if (text === shown) return;
    shown = text;
    sheetText.textContent = text;
    sheetText.hidden = false;
    if (!scrolled) {  // once, the moment it can be read, laid out: later sheets leave your place alone
      scrolled = true;
      requestAnimationFrame(() => { measureBar(); reader.scrollIntoView({block: "start"}); });
    }
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

window.addEventListener("resize", measureBar);
measureBar();
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
<details class="by-name" id="by-name-box">
  <summary>Not in the list? Look it up by name</summary>
  <form id="by-name" method="post" action="/lookup">
    <input type="hidden" name="csrf" value="__CSRF__">
    <label class="f">Artist<input name="artist" required maxlength="200" autocomplete="off"></label>
    <label class="f">Title<input name="title" required maxlength="300" autocomplete="off"></label>
    <button class="btn primary" type="submit">Look it up</button>
  </form>
</details>
<section class="reader" id="reader" aria-labelledby="reader-title" hidden>
  <div class="reader-head">
    <h2 id="reader-title"></h2>
    <button class="btn small" id="back" type="button" hidden>Back to the results</button>
  </div>
  <p class="said" id="said" role="status" aria-live="polite"></p>
  <ul class="stages" id="stages"></ul>
  <details class="why" id="why" hidden>
    <summary>What was left, and why</summary>
    <ul id="why-list"></ul>
  </details>
  <div class="files" id="files"></div>
  <pre class="sheet" id="sheet" hidden></pre>
</section>
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
