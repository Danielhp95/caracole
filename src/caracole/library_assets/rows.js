
// Where each thing came from, and a list's rows and lines (``resultRow``): index.html's, and the results of
// caracole serve's lookup page (web/lookup_page.py), which runs this script before its own.
const caracoleRows = (icons) => {
  "use strict";
  const own = Object.prototype.hasOwnProperty;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const keyName = (key) => (/ minor$/.test(key) ? key : key + " major");
  // Its site's own icon, inlined as a data: URI, else its lettered badge; a glyph for the audio model
  // and the inbox (icons.py). Each is named for a screen reader: "from LaCuerda".
  const ICONS = icons && typeof icons === "object" ? icons : {};
  const PNG_URI = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;
  const sourceMark = (key) => {
    if (typeof key !== "string" || !key) return null;
    const info = own.call(ICONS, key) && ICONS[key] && typeof ICONS[key] === "object" ? ICONS[key] : {};
    const name = "from " + String(info.name || key);
    let mark;
    if (typeof info.src === "string" && PNG_URI.test(info.src)) {
      mark = el("img", "source");
      mark.setAttribute("src", info.src);
      mark.setAttribute("alt", name);
      mark.setAttribute("width", "16");
      mark.setAttribute("height", "16");
    } else {
      mark = el("span", info.glyph ? "source glyph" : "source letters",
        String(info.letters || key.slice(0, 2).toUpperCase()));
      mark.setAttribute("role", "img");
      mark.setAttribute("aria-label", name);
    }
    mark.title = name;
    mark.dataset.source = key;
    return mark;
  };
  const safeHref = (href, external) => {
    const value = String(href || "");
    if (external) return /^https?:/i.test(value) ? value : "#";
    return /^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("/") ? "#" : value;
  };
  const link = (item, cls, external) => {
    const a = el("a", cls, String(item.label || "") + (external ? " ↗" : ""));
    a.href = safeHref(item.href, external);
    if (external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    const mark = sourceMark(item.source);  // after the label, so the link reads "Sheet PDF from LaCuerda"
    if (mark) {
      a.classList.add("sourced");
      a.appendChild(mark);
    }
    return a;
  };
  let rowSerial = 0;
  const isWeb = (href) => /^https?:/i.test(String(href || ""));
  // A title that opens what its row's or its line's main button opens: around the heading, so the heading
  // stays the song's name alone. Out of the Tab order: the button, which says what it opens, is the keyboard's.
  const titleLink = (href, heading) => {
    const external = isWeb(href);
    const a = el("a", "title-link");
    a.href = safeHref(href, external);
    if (external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    a.tabIndex = -1;
    a.appendChild(heading);
    return a;
  };
  // An artist's name that shows that artist's songs alone (``whose``, for its title): a button, the name and a
  // filter's mark (a funnel, drawn by the stylesheet), which a screen reader skips.
  const artistFilter = (name, whose, onArtist, cls) => {
    const who = el("button", cls ? "artist " + cls : "artist");
    who.type = "button";
    who.title = "Show only " + whose + "'s songs";
    who.appendChild(el("span", "artist-name", name));
    const mark = el("span", "filter-mark");
    mark.setAttribute("aria-hidden", "true");
    who.appendChild(mark);
    who.addEventListener("click", onArtist);
    return who;
  };
  const shortKey = (key) => String(key).replace(/ minor$/, "m").replace(/ major$/, "");
  // A key as a row or a line shows it ("Am"), and as a screen reader hears it ("Key A minor (from the tab)").
  const keyMark = (cls, r) => {
    const said = String(r.keyText || "Key " + keyName(r.key));
    const key = el("span", cls);
    key.title = said;
    const shown = el("span", null, shortKey(r.key));
    shown.setAttribute("aria-hidden", "true");
    key.appendChild(shown);
    key.appendChild(el("span", "visually-hidden", said));
    return key;
  };
  const linkGroup = (group) => {
    if (group instanceof Node) return group;
    const items = listOf(group && group.links).filter((item) => item && typeof item === "object");
    if (!items.length) return null;
    const box = el("div", "row-group");
    if (group.heading) box.appendChild(el("p", "subhead", group.heading));
    const line = el("div", "actions");
    for (const item of items) line.appendChild(link(item, "btn small", isWeb(item.href)));
    box.appendChild(line);
    return box;
  };
  // What a row's or a line's "⋯" button shows (``more``), folded under it: the button and its panel, named for the
  // ``kind`` of item ("row-more", "row-panel"), go at the item's end; nothing more to show, no button.
  const foldMore = (item, title, more, kind) => {
    const extra = listOf(more).map(linkGroup).filter(Boolean);
    if (!extra.length) return;
    const panel = el("div", kind + "-panel");
    rowSerial += 1;
    panel.id = kind + "-more-" + rowSerial;
    panel.hidden = true;
    for (const node of extra) panel.appendChild(node);
    const button = el("button", kind + "-more");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", panel.id);
    button.title = "More for " + title;
    const dots = el("span", null, "⋯");
    dots.setAttribute("aria-hidden", "true");
    button.appendChild(dots);
    button.appendChild(el("span", "visually-hidden", "More for " + title));
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      panel.hidden = !open;
    });
    item.appendChild(button);
    item.appendChild(panel);
  };
  const mainAction = (r) => (r.action instanceof Node ? r.action
    : r.action && typeof r.action === "object" ? link(r.action, "btn small primary", isWeb(r.action.href)) : null);
  // A dense list's line (``dense``): index.html's songs, under their artist's name. Its title, which opens what
  // ``href`` says; then the artist (where no group above names it: ``onArtist`` makes it the filter a group's name
  // is), the status's badges, the key and the marks of where it came from (``sources``, else ``source``); its main
  // action and "⋯". One line from 720px; on a phone two, the title and the action, then the rest.
  const denseLine = (r) => {
    const title = String(r.title || "");
    const artist = String(r.artist || "");
    const line = el("article", "line");
    line.tabIndex = -1;
    if (r.status) line.dataset.status = String(r.status);
    const heading = el("h3", null, title);
    heading.title = title;
    let named = el("div", "line-title");
    if (r.href) {
      named = titleLink(r.href, heading);
      named.className = "line-title";
    } else {
      named.appendChild(heading);
    }
    line.appendChild(named);
    const meta = el("div", "line-meta");
    if (artist && typeof r.onArtist === "function") meta.appendChild(artistFilter(artist, artist, r.onArtist, "line-by"));
    else if (artist) meta.appendChild(el("span", "line-by", artist));
    const status = el("span", "line-status");
    for (const badge of listOf(r.badges)) {
      if (badge && badge.text) status.appendChild(el("span", "badge " + String(badge.kind || ""), badge.text));
    }
    if (r.facts) status.appendChild(el("span", "line-facts", r.facts));
    if (status.childNodes.length) meta.appendChild(status);
    if (typeof r.key === "string" && r.key) meta.appendChild(keyMark("line-key", r));
    const marks = el("span", "line-sources");
    const sources = listOf(r.sources).length ? listOf(r.sources) : [r.source];
    for (const key of sources.filter((k, n) => sources.indexOf(k) === n)) {
      const mark = sourceMark(key);
      if (mark) marks.appendChild(mark);
    }
    if (marks.childNodes.length) meta.appendChild(marks);
    line.appendChild(meta);
    const action = el("div", "line-action");
    const main = mainAction(r);
    if (main) action.appendChild(main);
    line.appendChild(action);
    foldMore(line, title, r.more, "line");
    return line;
  };
  const resultRow = (result) => {
    const r = result && typeof result === "object" ? result : {};
    if (r.dense) return denseLine(r);
    const title = String(r.title || "");
    const artist = String(r.artist || "");
    const row = el("article", "row");
    row.tabIndex = -1;
    if (r.status) row.dataset.status = String(r.status);
    const heading = el("h2", "row-title", title);
    heading.title = title;
    row.appendChild(r.href ? titleLink(r.href, heading) : heading);
    // The artist and the key, the status and the badges: one wrapping line under the title on a phone,
    // where badges that don't fit go under the artist, never over it; their own columns on a desktop.
    const sub = el("div", "row-sub");
    if (artist && typeof r.onArtist === "function") {
      sub.appendChild(artistFilter(artist, artist, r.onArtist, "row-artist"));
    } else if (artist) {
      sub.appendChild(el("span", "row-artist", artist));
    }
    const meta = el("p", "row-meta");
    if (typeof r.key === "string" && r.key) meta.appendChild(keyMark("row-key", r));
    for (const badge of listOf(r.badges)) {
      if (badge && badge.text) meta.appendChild(el("span", "badge " + String(badge.kind || ""), badge.text));
    }
    if (r.facts) meta.appendChild(el("span", "row-facts", r.facts));
    if (meta.childNodes.length) sub.appendChild(meta);
    if (sub.childNodes.length) row.appendChild(sub);
    const mark = sourceMark(r.source);
    if (mark) row.appendChild(mark);
    const action = el("div", "row-action");
    const main = mainAction(r);
    if (main) action.appendChild(main);
    row.appendChild(action);
    foldMore(row, title, r.more, "row");
    return row;
  };

  // --- the offline indexes' hits, as /api/search and /api/artist give them --------------------------
  // index.html's search of the sites and caracole serve's lookup page draw them alike: each is a row with
  // its site's mark. ``get(pick, display, row, button)`` is what a Get it does: ``pick`` is the form
  // POST /lookup takes (a song of yours by its id, else its artist and title; the UG song, the tab).
  const many = (n, word) => Number(n || 0).toLocaleString("en") + " " + word + (Number(n) === 1 ? "" : "s");
  const button = (label, cls, onclick, aria) => {
    const b = el("button", "btn " + (cls || "small"), label);
    b.type = "button";
    if (aria) b.setAttribute("aria-label", aria);
    b.addEventListener("click", onclick);
    return b;
  };
  const KINDS = { chords: "Chords", tabs: "Tab", "guitar-pro": "Guitar Pro", power: "Power Tab" };
  const COUNTED = { chords: "chords", tabs: "tabs", "guitar-pro": "Guitar Pro", power: "Power Tab" };
  const counts = (c) => Object.entries(c && typeof c === "object" ? c : {})
    .map(([kind, n]) => n + " " + (own.call(COUNTED, kind) ? COUNTED[kind] : kind)).join(" · ");
  // A song's sheet viewer or PDF, as its line opens it: a link of the library's, relative to the page.
  const opener = (files) => listOf(files).find((f) => f && f.primary && /[.](html|pdf)$/i.test(String(f.name || "")))
    || null;
  const yours = (hit) => (hit && hit.library && typeof hit.library === "object" ? hit.library : null);
  // Under a hit's "⋯", given ``later(pick, display, row, button)``: the song into wanted.txt under the site's
  // names, for the nightly run to look up (index.html's results; /lookup gets songs now alone).
  const laterGroup = (later, pick, display, row) => {
    const box = el("div", "row-group later");
    box.appendChild(el("p", "subhead", "Later"));
    const go = button("Add for tonight's run", "small", (e) => later(pick, display, row(), e.currentTarget),
      "Add " + display + " for tonight's run");
    go.title = "Into wanted.txt, as caracole add writes it: the nightly run looks it up";
    box.appendChild(go);
    return box;
  };
  // An Ultimate Guitar song: Get it (Get it again for a song of yours, looked up as that song), and its
  // versions under "⋯", each numbered within its kind ("Chords 2 of 13"), with a link to look at it on UG.
  const ugHit = (h, get, later) => {
    const hit = h && typeof h === "object" ? h : {};
    const mine = yours(hit);
    const artist = String(hit.artist || "");
    const title = String(hit.title || "");
    const display = mine ? String(mine.display || "") : artist + " - " + title;
    const pick = (extra) => Object.assign(mine ? { song: mine.id } : { artist, title }, { ug: hit.ug }, extra);
    let row = null;
    const main = button(mine ? "Get it again" : "Get it", "small primary", (e) => get(pick({}), display, row, e.currentTarget),
      (mine ? "Get " + display + " again" : "Get " + display) + " from Ultimate Guitar");
    const more = [];
    const tabs = listOf(hit.tabs).filter((t) => t && typeof t === "object");
    if (tabs.length) {
      const versions = el("ul", "versions");
      const nth = {};
      const totals = hit.counts && typeof hit.counts === "object" ? hit.counts : {};
      for (const t of tabs) {
        nth[t.type] = (nth[t.type] || 0) + 1;
        const kind = own.call(KINDS, t.type) ? KINDS[t.type] : String(t.type);
        const name = kind + " " + nth[t.type] + " of " + (totals[t.type] || nth[t.type]) + (t.label ? " · " + t.label : "");
        const item = el("li", "version");
        item.appendChild(button(name, "small", (e) => get(pick({ tab: t.url }), display, row, e.currentTarget),
          "Get " + name + ", " + display));
        const ug = el("a", "on-ug", "on UG");
        ug.href = /^https:[/][/]/i.test(String(t.url || "")) ? String(t.url) : "#";
        ug.target = "_blank";
        ug.rel = "noopener noreferrer";
        ug.setAttribute("aria-label", name + ", " + display + ", on Ultimate Guitar");
        item.appendChild(ug);
        versions.appendChild(item);
      }
      const box = el("div", "row-group");
      box.appendChild(el("p", "subhead", "Versions"));
      box.appendChild(versions);
      more.push(box);
    }
    const opens = mine ? opener(mine.links) : null;
    if (opens) more.push({ heading: "In your library", links: [{ label: opens.label, href: opens.href, source: opens.source }] });
    // Not under one of UG's misc-… names ("Misc Mashups"): no one's, the song would never be found by it.
    if (later && !mine && !hit.no_ones) more.push(laterGroup(later, { artist, title }, display, () => row));
    row = resultRow({ title, artist, source: "ug", facts: counts(hit.counts),
      badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    row.classList.add("hit");
    row.dataset.ug = String(hit.ug || "");
    row.dataset.source = "ug";
    const dots = row.querySelector(".row-more");
    if (dots && tabs.length) {  // what "⋯" holds, said: its versions
      dots.title = "Versions of " + display;
      dots.setAttribute("aria-label", "Versions of " + display);
    }
    return row;
  };
  // An artist of the offline index, with their most tabbed songs said: ``open(a)`` lists every one.
  const artistHit = (a, open) => {
    const top = listOf(a && a.top).map((t) => t && t.title).filter(Boolean);
    const go = button("Songs", "small primary", () => open(a), "Songs by " + String(a.artist) + " on Ultimate Guitar");
    const row = resultRow({ title: a.artist, artist: top.length ? "Artist · " + top.join(", ") : "Artist", source: "ug",
      facts: many(a.songs, "song"), action: go });
    row.classList.add("hit", "artist-hit");
    row.dataset.artist = String(a.artist_key || "");
    row.dataset.source = "ug";
    return row;
  };
  // A page of gtptabs.com's index (a song with a Guitar Pro file there): Get it looks the song up as
  // caracole get does, whose gtptabs.com stage downloads one file for a song that has none; or MuseScore's,
  // a title alone, which caracole never fetches: a link to open; or a song of LaCuerda's index, whose Get it
  // looks the song up and keeps that LaCuerda sheet (``lacuerda``: the song's page, for one with chords
  // there), as Add for tonight's run records it for the nightly run.
  const siteHit = (h, get, later) => {
    const hit = h && typeof h === "object" ? h : {};
    const title = String(hit.title || "");
    let row = null;
    if (hit.source === "lacuerda") {
      const mine = yours(hit);
      const artist = String(hit.artist || "");
      const display = mine ? String(mine.display || "") : artist + " - " + title;
      const chords = /^https:[/][/]/i.test(String(hit.sheet || "")) && /^https:[/][/]/i.test(String(hit.url || ""));
      const picked = chords ? { lacuerda: String(hit.url) } : {};
      const pick = Object.assign(mine ? { song: mine.id } : { artist, title }, picked);
      const main = button(mine ? "Get it again" : "Get it", "small primary", (e) => get(pick, display, row, e.currentTarget),
        (mine ? "Get " + display + " again" : "Get " + display) + (chords ? " from LaCuerda" : ""));
      main.title = chords ? "Looks the song up now, and keeps this LaCuerda sheet"
        : "Looks the song up now: LaCuerda has no chords for it";
      const more = [{ heading: "On LaCuerda", links: [{ label: "Its page", href: hit.url, source: "lacuerda" }] }];
      const opens = mine ? opener(mine.links) : null;
      if (opens) more.push({ heading: "In your library", links: [{ label: opens.label, href: opens.href, source: opens.source }] });
      if (later && !mine) more.push(laterGroup(later, Object.assign({ artist, title }, picked), display, () => row));
      row = resultRow({ title, artist, source: "lacuerda",
        facts: many(Number(hit.versions) || 1, "version") + (chords ? "" : " · no chords"),
        badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    } else if (hit.source === "musescore") {
      row = resultRow({ title, artist: "Same title: maybe another song", source: "musescore",
        action: { label: "Open", href: hit.url } });
      const open = row.querySelector(".row-action a");
      if (open) open.setAttribute("aria-label", "Open " + title + " on MuseScore, in a new tab");
    } else {
      const mine = yours(hit);
      const artist = String(hit.artist || "");
      const display = mine ? String(mine.display || "") : artist + " - " + title;
      const pick = mine ? { song: mine.id } : { artist, title };
      const main = button(mine ? "Get it again" : "Get it", "small primary", (e) => get(pick, display, row, e.currentTarget),
        (mine ? "Get " + display + " again" : "Get " + display) + ", with a Guitar Pro file from gtptabs.com");
      main.title = "Looks the song up now, as caracole get does: its sheet, then a Guitar Pro file from gtptabs.com";
      const uploads = Number(hit.uploads) || 1;
      const more = [{ heading: "On gtptabs.com", links: [{ label: "Its page", href: hit.url, source: "gtptabs" }] }];
      if (later && !mine) more.push(laterGroup(later, { artist, title }, display, () => row));
      row = resultRow({ title, artist, source: "gtptabs", facts: uploads > 1 ? many(uploads, "upload") : "Guitar Pro",
        badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    }
    row.classList.add("hit");
    row.dataset.source = String(hit.source || "");
    return row;
  };
  // An artist of LaCuerda's index, with their most popular songs said: ``open(a)`` lists the songs the index
  // holds of theirs, or offers to read their page when caracole never has.
  const siteArtist = (a, open) => {
    const x = a && typeof a === "object" ? a : {};
    const name = String(x.artist || "");
    const top = listOf(x.top).map((t) => t && t.title).filter(Boolean);
    const go = button("Songs", "small primary", () => open(x), "Songs by " + name + " on LaCuerda");
    const row = resultRow({ title: name, artist: top.length ? "Artist · " + top.join(", ") : "Artist", source: "lacuerda",
      facts: many(x.songs, "song"), action: go });
    row.classList.add("hit", "artist-hit");
    row.dataset.source = "lacuerda";
    row.dataset.slug = String(x.slug || "");
    return row;
  };
  // A LaCuerda artist's songs, as /api/artist?lacuerda= gives them, under ``group(title, rows)``; or, while
  // caracole hasn't read their page, what it lists and the button that reads it (``read(button, box)``).
  const siteArtistSongs = (page, group, get, later, read) => {
    const p = page && typeof page === "object" ? page : {};
    const songs = listOf(p.songs).filter((h) => h && typeof h === "object");
    if (p.read) return group("LaCuerda, the most popular first · " + many(songs.length, "song"), songs.map((h) => siteHit(h, get, later)));
    const name = String(p.artist || "");
    const box = el("div", "read-page");
    box.appendChild(el("p", null, "caracole hasn't read the page of " + name + " on LaCuerda yet, which lists " +
      many(p.listed, "song") + ". Reading it is one request to LaCuerda, at a lookup's pace."));
    box.appendChild(button("Read their page", "small primary", (e) => read(e.currentTarget, box),
      "Read the page of " + name + " on LaCuerda"));
    return [el("h2", "group", "LaCuerda"), box];
  };
  // A query LaCuerda's index has no artist by, under a letter its listings aren't read to yet (/api/search's
  // lacuerda_unlisted): the index can't tell whether LaCuerda has them, their page can (``read(button, box)``).
  const siteUnlisted = (u, read) => {
    const x = u && typeof u === "object" ? u : {};
    const name = String(x.name || "");
    const box = el("div", "read-page unlisted");
    box.appendChild(el("p", null, "LaCuerda hasn't listed " + String(x.letter || "") + " yet, so caracole can't " +
      "tell whether it has “" + name + "”. Reading the page of that name is a request to LaCuerda (one per " +
      "spelling of it tried, usually one), at a lookup's pace."));
    box.appendChild(button("Read LaCuerda's page for “" + name + "”", "small primary", (e) => read(e.currentTarget, box)));
    return [el("h2", "group", "LaCuerda"), box];
  };
  // Read a LaCuerda artist's page now (POST lacuerda/artist: caracole lacuerda --artist, a job in the queue), by
  // the slug of a page the index lists (``who.slug``) or by a name (``who.name``), then follow the job until it
  // is over; ``said(text)`` hears how it goes. Resolves with the job, or with why there is none.
  const readArtistPage = (csrf, who, said) => new Promise((resolve) => {
    const gone = () => resolve({ error: "caracole serve can't be reached: is it still running?" });
    const w = who && typeof who === "object" ? who : {};
    const body = new URLSearchParams(w.slug ? { csrf: String(csrf || ""), slug: String(w.slug) }
      : { csrf: String(csrf || ""), name: String(w.name || "") });
    said("Asking for the page…");
    fetch("lacuerda/artist", { method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => r.json().catch(() => null).then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || !data || typeof data.url !== "string" || !/^[/]api[/]jobs[/]\d+$/.test(data.url)) {
          resolve({ error: (data && data.error) || "caracole didn't read the page." });
          return;
        }
        const follow = () => fetch(data.url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } })
          .then((r) => (r.ok ? r.json() : null))
          .then((job) => {
            if (!job || typeof job !== "object") {
              resolve({ error: "That request is gone: caracole serve restarted, maybe." });
            } else if (job.active) {
              said(job.state === "queued" ? "Waiting for the request before it…" : "Reading the page on LaCuerda…");
              setTimeout(follow, 700);
            } else {
              resolve({ job });
            }
          }, gone);
        follow();
      }, gone);
  });
  // A read that left no songs to list: what LaCuerda answered, as its request's line says it ("Not read: LaCuerda is
  // cooling down…", "Not found: …"), and its output on the requests page.
  const readOutcome = (job) => {
    const j = job && typeof job === "object" ? job : {};
    const line = j.line && typeof j.line === "object" && typeof j.line.text === "string" ? j.line.text : "";
    const said = /^(Read|Not read|Not found): /.test(line) ? line + " " : "LaCuerda gave caracole no songs of theirs this time. ";
    const why = el("p", "hint read-outcome", said);
    const id = Number(j.id);
    if (Number.isInteger(id) && id > 0) {
      const details = el("a", null, "See what it answered");
      details.href = "jobs?job=" + id + "#job-" + id;
      why.appendChild(details);
      why.appendChild(document.createTextNode("."));
    }
    return why;
  };
  // A paragraph of the server's, its commands in backticks as the terminal prints them: those as code.
  const prose = (cls, text) => {
    const p = el("p", cls);
    const parts = String(text).split("`");
    if (parts.length % 2 === 0) p.textContent = String(text);  // a backtick unpaired: as it is
    else parts.forEach((part, i) => { if (part) p.appendChild(i % 2 ? el("code", null, part) : document.createTextNode(part)); });
    return p;
  };
  return { resultRow, sourceMark, link, titleLink, artistFilter, button, many, counts, opener, ugHit, artistHit,
    siteHit, siteArtist, siteArtistSongs, siteUnlisted, readArtistPage, readOutcome, prose };
};
