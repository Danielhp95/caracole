
// Where each thing came from, and a list's rows and lines (``resultRow``): index.html's, and the results of
// caracole serve's lookup page (web/lookup_page.py), which runs this script before its own. ``does.searchArtist(name)``,
// where a page can search: what an artist's name on a site's row does (ugHit, siteHit), the search for them.
const caracoleRows = (icons, does) => {
  "use strict";
  const searchArtist = does && typeof does.searchArtist === "function" ? does.searchArtist : null;
  const searchesFor = (artist) => (searchArtist && artist ? () => searchArtist(artist) : null);
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
  // A link of an item ({label, href, source}); a file of the library's that is a download (a Guitar Pro file, a
  // score) names the file it saves (``download``: "Eagles - Hotel California (2).gp5"), as caracole serve's header does.
  const link = (item, cls, external) => {
    const a = el("a", cls, String(item.label || "") + (external ? " ↗" : ""));
    a.href = safeHref(item.href, external);
    if (external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    } else if (typeof item.download === "string" && item.download) {
      a.setAttribute("download", item.download);
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
  // Served, an artist's name searches for them (``onSearch``: the search box filled with it, as typing it would): a
  // button, the name alone, which a header and a line show as they show a name.
  const artistSearch = (name, onSearch, cls) => {
    const who = el("button", cls ? "artist artist-search " + cls : "artist artist-search");
    who.type = "button";
    who.title = "Search for " + name;
    who.appendChild(el("span", "artist-name", name));
    who.addEventListener("click", onSearch);
    return who;
  };
  // Beside it, for an artist you have songs of, the funnel: their songs of yours alone (``onArtist``), a button of its
  // own, named for what it does.
  const artistOnly = (whose, onArtist) => {
    const only = el("button", "artist-only");
    only.type = "button";
    only.title = "Only " + whose + "'s songs";
    only.setAttribute("aria-label", "Only " + whose + "'s songs");
    const mark = el("span", "filter-mark");
    mark.setAttribute("aria-hidden", "true");
    only.appendChild(mark);
    only.addEventListener("click", onArtist);
    return only;
  };
  // A row's or a line's artist (``cls``, its place): served, the name that searches for them (``onSearch``) and the
  // funnel beside it (``onArtist``); from a file, which can't search the sites, the name is the funnel's
  // (artistFilter); neither, the name alone.
  const artistOf = (name, onSearch, onArtist, cls) => {
    if (typeof onSearch === "function" && typeof onArtist === "function") {
      const pair = el("span", cls + " artist-pair");
      pair.append(artistSearch(name, onSearch), artistOnly(name, onArtist));
      return pair;
    }
    if (typeof onSearch === "function") return artistSearch(name, onSearch, cls);
    if (typeof onArtist === "function") return artistFilter(name, name, onArtist, cls);
    return el("span", cls, name);
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
  // ``href`` says; then the artist (where no group above names it: ``onSearch`` and ``onArtist`` make it what a
  // group's name is, artistOf), the status's badges, the key and the marks of where it came from (``sources``, else ``source``); its main
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
    if (artist) meta.appendChild(artistOf(artist, r.onSearch, r.onArtist, "line-by"));
    const status = el("span", "line-status");
    for (const badge of listOf(r.badges)) {
      if (badge && badge.text) status.appendChild(el("span", "badge " + String(badge.kind || ""), badge.text));
    }
    if (r.facts) {
      const facts = status.appendChild(el("span", "line-facts", r.facts));
      facts.title = String(r.facts);  // the whole of it, where its column cuts it short
    }
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
    if (artist) sub.appendChild(artistOf(artist, r.onSearch, r.onArtist, "row-artist"));
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
  // caracole serve's lookup page draws each as a row with its site's mark; index.html's search, a song as a line
  // (indexLine, below), its sites' rows on it. ``get(pick, display, row, button)`` is what a Get it does: ``pick``
  // is the form POST /lookup takes (a song of yours by its id, else its artist and title; the UG song, the tab).
  const many = (n, word) => Number(n || 0).toLocaleString("en") + " " + word + (Number(n) === 1 ? "" : "s");
  const button = (label, cls, onclick, aria) => {
    const b = el("button", "btn " + (cls || "small"), label);
    b.type = "button";
    if (aria) b.setAttribute("aria-label", aria);
    b.addEventListener("click", onclick);
    return b;
  };
  // A hit's song name that does what its Get it does (``main``, the button of the row or line ``item``): a button in
  // its heading that looks like the name, underlined under the pointer and at the keyboard's focus, named for what
  // it does (``said``: "Get Oasis - Wonderwall"). Pressed, it presses ``main``, so the same call takes the same pick,
  // display, row and button; it is disabled whenever ``main`` is (its request on its way) or has left the item (its
  // request line in its place), so one song is never two lookups. None where ``main`` is no button or is disabled,
  // or the title opens something already (titleLink): a link is never traded for a fetch.
  const nameDoes = (item, main, said) => {
    if (!(main instanceof HTMLButtonElement) || main.disabled) return;
    const heading = item.querySelector("h2, h3");
    if (!heading || heading.closest("a")) return;
    const name = el("button", "title-get", heading.textContent);
    name.type = "button";
    name.setAttribute("aria-label", said);
    name.title = main.title ? said + ": " + main.title.charAt(0).toLowerCase() + main.title.slice(1) : said;
    name.addEventListener("click", () => {
      if (!main.disabled && item.contains(main)) main.click();
    });
    heading.classList.add("gets");
    heading.replaceChildren(name);
    const mirror = () => {
      const off = main.disabled || !item.contains(main);
      if (name.disabled !== off) name.disabled = off;  // set alike, it would be a change heard again
    };
    new MutationObserver(mirror).observe(item, { subtree: true, childList: true, attributes: true,
      attributeFilter: ["disabled"] });
  };
  const KINDS = { chords: "Chords", tabs: "Tab" };
  const COUNTED = { chords: "chords", tabs: "tabs" };
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
  // An Ultimate Guitar song's versions (``tabs``), under a "⋯": each a button, numbered within its kind ("Chords 2 of
  // 13", of ``totals``), with a link to look at it on UG; ``choose(tab, button)`` is what its button does.
  const versionsOf = (tabs, totals, display, choose) => {
    const versions = el("ul", "versions");
    const nth = {};
    const of = totals && typeof totals === "object" ? totals : {};
    for (const t of tabs) {
      nth[t.type] = (nth[t.type] || 0) + 1;
      const kind = own.call(KINDS, t.type) ? KINDS[t.type] : String(t.type);
      const name = kind + " " + nth[t.type] + " of " + (of[t.type] || nth[t.type]) + (t.label ? " · " + t.label : "");
      const item = el("li", "version");
      item.appendChild(button(name, "small", (e) => choose(t, e.currentTarget), "Get " + name + ", " + display));
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
    return box;
  };
  // An Ultimate Guitar song: Get it (Get it again for a song of yours, looked up as that song), which its name does
  // too (nameDoes), and its versions under "⋯" (versionsOf).
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
    if (tabs.length) more.push(versionsOf(tabs, hit.counts, display, (t, go) => get(pick({ tab: t.url }), display, row, go)));
    const opens = mine ? opener(mine.links) : null;
    if (opens) more.push({ heading: "In your library", links: [{ label: opens.label, href: opens.href, source: opens.source }] });
    // Not under one of UG's misc-… names ("Misc Mashups"): no one's, the song would never be found by it.
    if (later && !mine && !hit.no_ones) more.push(laterGroup(later, { artist, title }, display, () => row));
    row = resultRow({ title, artist, onSearch: searchesFor(artist), source: "ug", facts: counts(hit.counts),
      badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    row.classList.add("hit");
    row.dataset.ug = String(hit.ug || "");
    row.dataset.source = "ug";
    nameDoes(row, main, mine ? "Get " + display + " again" : "Get " + display);
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
  // there), as Add for tonight's run records it for the nightly run. A song's name does what its Get it does
  // (nameDoes).
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
      row = resultRow({ title, artist, onSearch: searchesFor(artist), source: "lacuerda",
        facts: many(Number(hit.versions) || 1, "version") + (chords ? "" : " · no chords"),
        badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
      nameDoes(row, main, mine ? "Get " + display + " again" : "Get " + display);
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
      row = resultRow({ title, artist, onSearch: searchesFor(artist), source: "gtptabs",
        facts: uploads > 1 ? many(uploads, "upload") : "Guitar Pro",
        badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
      nameDoes(row, main, mine ? "Get " + display + " again" : "Get " + display);
    }
    row.classList.add("hit");
    row.dataset.source = String(hit.source || "");
    return row;
  };

  // --- index.html's search: a song of the sites a dense line, under its artist's header --------------------
  // "chords ×9 · tabs ×2": an Ultimate Guitar song's tabs per type, as a line counts them. The index holds no
  // ratings (only the sheets caracole fetched have them), so a line never shows stars.
  const TIMES = { chords: "chords", tabs: "tabs" };
  const tabCounts = (c) => Object.entries(c && typeof c === "object" ? c : {})
    .map(([kind, n]) => (own.call(TIMES, kind) ? TIMES[kind] : kind) + " ×" + Number(n || 0)).join(" · ");
  const https = (url) => /^https:[/][/]/i.test(String(url || ""));
  // One song of the offline indexes (``item``): each site's row of it, as /api/search gives them (``ug``, an Ultimate
  // Guitar song; ``lacuerda`` and ``gtptabs``, a song of theirs; ``removed``, a song caracole removed), on one line
  // with each site's mark and its counts, and its identity (``key``) as the line's ``data-hit``. Get it looks the
  // song up as Ultimate Guitar's song (whose lookup gets gtptabs.com's Guitar Pro file too), else keeping
  // LaCuerda's sheet, else by its names; a removed song's is Add again, which asks for it again as the request form
  // does. Its name does what that button does (nameDoes). Under "⋯": UG's versions, LaCuerda's sheet and page,
  // gtptabs.com's page, Add for tonight's run.
  // ``acts``: { get, later, again }, each called (pick, display, line, button), as ugHit's ``get`` is.
  const indexLine = (item, acts) => {
    const it = item && typeof item === "object" ? item : {};
    const rowOf = (x) => (x && typeof x === "object" ? x : null);
    const ug = rowOf(it.ug);
    const lc = rowOf(it.lacuerda);
    const gtp = rowOf(it.gtptabs);
    const mine = [ug, lc, gtp].map(yours).find(Boolean) || null;  // a song of yours the page has no line of yet
    const gone = mine ? null : rowOf(it.removed);
    const first = ug || lc || gtp || gone || {};
    const title = String(first.title || "");
    const artist = String(first.artist || "");
    const display = mine ? String(mine.display || "") : artist + " - " + title;
    const pick = (extra) => Object.assign(mine ? { song: mine.id } : { artist, title }, extra);
    const chords = Boolean(lc) && https(lc.sheet) && https(lc.url);
    const sheet = chords ? { lacuerda: String(lc.url) } : {};
    const a = acts && typeof acts === "object" ? acts : {};
    let line = null;
    const here = () => line;
    let main;
    if (gone) {
      const back = { artist, title };
      main = button("Add again", "small primary", (e) => a.again(back, display, here(), e.currentTarget),
        "Add " + display + " again");
      main.title = "Into wanted.txt again, as Request does, and looked up now: a wanted.txt line brings it back";
    } else {
      const chosen = ug ? pick({ ug: ug.ug }) : pick(sheet);
      main = button(mine ? "Get it again" : "Get it", "small primary", (e) => a.get(chosen, display, here(), e.currentTarget),
        (mine ? "Get " + display + " again" : "Get " + display) + (ug ? " from Ultimate Guitar" : chords ? " from LaCuerda"
          : gtp ? ", with a Guitar Pro file from gtptabs.com" : ""));
      main.title = ug ? "Looks the song up now, as caracole get does, on Ultimate Guitar first"
        : chords ? "Looks the song up now, and keeps this LaCuerda sheet"
        : gtp ? "Looks the song up now, as caracole get does: its sheet, then a Guitar Pro file from gtptabs.com"
        : "Looks the song up now: LaCuerda has no chords for it";
    }
    const more = [];
    const tabs = ug ? listOf(ug.tabs).filter((t) => t && typeof t === "object") : [];
    if (tabs.length) {
      more.push(versionsOf(tabs, ug.counts, display, (t, go) => a.get(pick({ ug: ug.ug, tab: t.url }), display, here(), go)));
    }
    if (lc) {
      const box = el("div", "row-group");
      box.appendChild(el("p", "subhead", "On LaCuerda"));
      const actions = el("div", "actions");
      if (chords && (ug || gone)) {  // the line's own button is another's: this one keeps LaCuerda's sheet
        actions.appendChild(button("Get it with this sheet", "small", (e) => a.get(pick(sheet), display, here(), e.currentTarget),
          "Get " + display + ", keeping LaCuerda's sheet"));
      }
      actions.appendChild(link({ label: "Its page", href: lc.url, source: "lacuerda" }, "btn small", true));
      box.appendChild(actions);
      more.push(box);
    }
    if (gtp) more.push({ heading: "On gtptabs.com", links: [{ label: "Its page", href: gtp.url, source: "gtptabs" }] });
    const opens = mine ? opener(mine.links) : null;
    if (opens) more.push({ heading: "In your library", links: [{ label: opens.label, href: opens.href, source: opens.source }] });
    // Not under one of UG's misc-… names ("Misc Mashups"): no one's, the song would never be found by it.
    if (a.later && !mine && !(ug && ug.no_ones)) more.push(laterGroup(a.later, pick(ug ? {} : sheet), display, here));
    const facts = [ug ? tabCounts(ug.counts) : "",
      lc ? "LaCuerda ×" + (Number(lc.versions) || 1) + (chords ? "" : ", no chords") : "",
      gtp ? "Guitar Pro file" + ((Number(gtp.uploads) || 1) > 1 ? " ×" + Number(gtp.uploads) : "") : ""];
    const badges = gone ? [{ kind: "removed", text: "Removed " + String(gone.removed_at || "").slice(0, 10) }]
      : mine ? [{ kind: "found", text: "In your library" }] : [];
    line = resultRow({ dense: true, title, artist, sources: [ug && "ug", lc && "lacuerda", gtp && "gtptabs"].filter(Boolean),
      facts: facts.filter(Boolean).join(" · "), badges, action: main, more, status: gone ? "removed" : "" });
    line.classList.add("hit");
    if (gone) line.classList.add("removed-hit");
    line.dataset.hit = String(it.key || "");
    line.dataset.source = ug ? "ug" : lc ? "lacuerda" : gtp ? "gtptabs" : "removed";
    if (ug) line.dataset.ug = String(ug.ug || "");
    nameDoes(line, main, gone ? "Add " + display + " again" : mine ? "Get " + display + " again" : "Get " + display);
    return line;
  };
  // A MuseScore page, its title alone (its sitemaps name no artist), so a possible match: a link to open, as caracole
  // never fetches from MuseScore.
  const titleLine = (h) => {
    const hit = h && typeof h === "object" ? h : {};
    const title = String(hit.title || "");
    const line = resultRow({ dense: true, title, sources: ["musescore"], facts: "same title, maybe another song",
      action: { label: "Open", href: hit.url } });
    const open = line.querySelector(".line-action a");
    if (open) open.setAttribute("aria-label", "Open " + title + " on MuseScore, in a new tab");
    line.classList.add("hit");
    line.dataset.source = "musescore";
    line.dataset.hit = "musescore:" + String(hit.url || "");
    return line;
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
  // A job of LaCuerda's index queued (POST ``address``, the form ``body``), then followed until it is over;
  // ``said(text)`` hears how it goes, in ``words`` (``asking``, ``running``; ``failed``, a refusal without words).
  // Resolves with the job, or with why there is none.
  const queueAndFollow = (address, body, said, words) => new Promise((resolve) => {
    const gone = () => resolve({ error: "caracole serve can't be reached: is it still running?" });
    said(words.asking);
    fetch(address, { method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => r.json().catch(() => null).then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || !data || typeof data.url !== "string" || !/^[/]api[/]jobs[/]\d+$/.test(data.url)) {
          resolve({ error: (data && data.error) || words.failed });
          return;
        }
        const follow = () => fetch(data.url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } })
          .then((r) => (r.ok ? r.json() : null))
          .then((job) => {
            if (!job || typeof job !== "object") {
              resolve({ error: "That request is gone: caracole serve restarted, maybe." });
            } else if (job.active) {
              said(job.state === "queued" ? "Waiting for the request before it…" : words.running);
              setTimeout(follow, 700);
            } else {
              resolve({ job });
            }
          }, gone);
        follow();
      }, gone);
  });
  // Read a LaCuerda artist's page now (POST lacuerda/artist: caracole lacuerda --artist, a job in the queue), by
  // the slug of a page the index lists (``who.slug``) or by a name (``who.name``), then follow the job until it
  // is over; ``said(text)`` hears how it goes. Resolves with the job, or with why there is none.
  const readArtistPage = (csrf, who, said) => {
    const w = who && typeof who === "object" ? who : {};
    const body = new URLSearchParams(w.slug ? { csrf: String(csrf || ""), slug: String(w.slug) }
      : { csrf: String(csrf || ""), name: String(w.name || "") });
    return queueAndFollow("lacuerda/artist", body, said, { asking: "Asking for the page…",
      running: "Reading the page on LaCuerda…", failed: "caracole didn't read the page." });
  };
  // LaCuerda's own search for a query, now (POST lacuerda/search: caracole lacuerda --search, a job in the queue),
  // sent by the page by itself, or ``byHand`` (its button); then the job followed, as readArtistPage does.
  const searchLaCuerda = (csrf, query, byHand, said) => {
    const body = new URLSearchParams({ csrf: String(csrf || ""), q: String(query || "") });
    if (byHand) body.set("by_hand", "1");
    const searching = "Searching LaCuerda for “" + String(query || "") + "”…";
    return queueAndFollow("lacuerda/search", body, said, { asking: searching, running: searching,
      failed: "caracole didn't search LaCuerda." });
  };
  // LaCuerda's own search for the query a page shows the results of (/api/search's ``lacuerda_search``, the gate:
  // its ``state``, the ``query`` and its ``key``), one line under the results. State "auto": sent by itself once
  // the query has settled, the box unchanged for ``SETTLE`` ms (``typed()`` hears each key; a query is new to the
  // box when its first answer is shown) and still what ``current()`` gives, its line then put under the results
  // (``place(line)``). Enter (``enter(query, shown)``) sends it at once, by hand as the button does, when the gate
  // says "auto" or "button" (not "failed": its button asks again): for the answer on the screen (``shown``), its
  // line given back, else with the query's next answer, which ``show`` then gives; the settle's wait for it ends.
  // ``leave()``, the results left before that answer, takes such an Enter back. Never twice for one query in a page. State "button", the hour's share of such searches spent: "Search
  // LaCuerda for “…” (1 request)", by hand; state "failed", its search failed lately (or three did): the gate's
  // ``why``, and the button. While it runs the line says so ("Searching LaCuerda for “…”…"), then what LaCuerda
  // answered, or why the search was refused, and ``done(query)`` asks the page's search again, whose answer the
  // job's end left fresh: that query's line stays under its results, with the button when the gate offers it now
  // (a search refused or failed: the words name it). ``show(gate, query)`` gives the line to put under them, or
  // null.
  const SETTLE = 1500;
  const lacuerdaSearcher = (csrf, current, done, place) => {
    const lines = new Map();  // the line of each query's key, the same node from one draw to the next
    const keys = new Map();  // each query's key, as its first gate gave it: a later answer may have none
    const sent = new Set();
    const running = new Set();  // the keys whose search is on its way
    const gates = new Map();  // each query's gate, as its newest answer gave it (null: none)
    let entered = null;  // the query an Enter waits for the answer of
    const firstShown = new Map();
    let lastKey = 0;
    let timer = 0;
    let pending = null;  // { key, query, gate } the timer waits to send
    const lineOf = (key) => {
      if (!lines.has(key)) lines.set(key, el("div", "lacuerda-search"));
      return lines.get(key);
    };
    const send = (gate, query, byHand) => {
      const key = String(gate.key);
      sent.add(key);
      running.add(key);
      const line = lineOf(key);
      const words = el("p", "hint lacuerda-search-said", "Searching LaCuerda for “" + query + "”…");
      words.setAttribute("role", "status");
      line.replaceChildren(words);
      searchLaCuerda(csrf, query, byHand, (text) => { words.textContent = text; }).then((asked) => {
        running.delete(key);
        if (asked.error) {
          words.textContent = asked.error;
        } else {
          const job = asked.job && typeof asked.job === "object" ? asked.job : {};
          const said = job.line && typeof job.line === "object" && typeof job.line.text === "string"
            ? job.line.text : "";
          words.textContent = said || "LaCuerda's search is over.";
        }
        done(query);  // its rows; or, refused or failed, what the gate says now
      });
      return line;
    };
    // The button that sends it by hand, under what the line says: the gate's ``why``, or what the search this page
    // sent said.
    const offer = (gate, query) => {
      const key = String(gate.key);
      const line = lineOf(key);
      if (line.querySelector(".lacuerda-search-go")) return line;
      const go = button("Search LaCuerda for “" + query + "” (1 request)", "small lacuerda-search-go", () => {
        go.disabled = true;
        send(gate, query, true);
      }, "Search LaCuerda for “" + query + "”: one request");
      go.title = "LaCuerda's own search, one request at a lookup's pace: its songs go into caracole's copy of its index.";
      if (!sent.has(key)) {
        const why = gate.state === "failed" && typeof gate.why === "string" ? gate.why : "";
        line.replaceChildren(...(why ? [el("p", "hint lacuerda-search-said", why)] : []));
      }
      line.appendChild(go);
      return line;
    };
    const fire = () => {
      timer = 0;
      const wait = pending;
      if (!wait) return;
      if (current() !== wait.query || sent.has(wait.key)) {  // typed on: the next answer says
        pending = null;
        return;
      }
      const settled = Math.max(lastKey, firstShown.get(wait.query) || 0) + SETTLE - performance.now();
      if (settled > 0) {
        timer = setTimeout(fire, settled);
        return;
      }
      pending = null;
      place(send(wait.gate, wait.query, false));
    };
    // Enter's search, by hand, when the gate sends one (and none went for the query yet): the settle's wait ends.
    const entering = (g, query) => {
      if (!g || (g.state !== "auto" && g.state !== "button") || sent.has(String(g.key))) return null;
      if (pending && pending.key === String(g.key)) {
        clearTimeout(timer);
        timer = 0;
        pending = null;
      }
      return send(g, query, true);
    };
    const show = (gate, query) => {
      const g = gate && typeof gate === "object" && typeof gate.key === "string" && gate.key ? gate : null;
      if (!firstShown.has(query)) firstShown.set(query, performance.now());
      if (g && !keys.has(query)) keys.set(query, String(g.key));
      gates.set(query, g);
      if (entered !== null && current() !== entered) entered = null;  // the box holds another query now
      const wanted = entered === query;
      if (wanted) entered = null;
      const key = g ? String(g.key) : keys.get(query);
      const byHand = g && (g.state === "button" || g.state === "failed");
      if (key && running.has(key)) return lineOf(key);
      const now = wanted ? entering(g, query) : null;  // Enter came before the answer
      if (now) return now;
      // Over: what it said, and the button when the gate still offers a search (refused, failed or cancelled).
      if (key && sent.has(key)) return g && (byHand || g.state === "auto") ? offer(g, query) : lineOf(key);
      if (key && lines.has(key) && lines.get(key).firstChild) return lineOf(key);  // offered already
      if (!g) return null;
      if (byHand) return offer(g, query);
      if (g.state === "spent") {  // said afresh each time: in an hour, the same query may be sent
        const line = el("div", "lacuerda-search");
        line.appendChild(el("p", "hint lacuerda-search-said", "LaCuerda's search waits: it cools down after a " +
          "block, or this hour's lookups to it are spent."));
        return line;
      }
      if (g.state === "auto" && !(pending && pending.key === key && pending.query === query)) {
        clearTimeout(timer);
        pending = { key, query, gate: g };
        timer = setTimeout(fire, SETTLE);
      }
      return null;
    };
    const typed = () => {
      lastKey = performance.now();
      entered = null;
    };
    // Enter for ``query``: its search now, when the answer on the screen is the query's (``shown``) and its gate
    // sends one (the line, to put under the results), else null; or, its answer on its way, with that answer.
    const enter = (query, shown) => {
      if (shown) return gates.has(query) ? entering(gates.get(query), query) : null;
      entered = query;
      return null;
    };
    // The results left (Escape) before the answer an Enter waits for: that Enter is taken back.
    const leave = () => {
      entered = null;
    };
    return { show, typed, enter, leave };
  };
  // A read that left no songs to list: what LaCuerda answered, as its request's line says it ("Not read: LaCuerda is
  // cooling down…", "Not found: …"), and its output on the requests page.
  const readOutcome = (job) => {
    const j = job && typeof job === "object" ? job : {};
    const line = j.line && typeof j.line === "object" && typeof j.line.text === "string" ? j.line.text : "";
    const said = /^(Read|Not read|Not found|Searched|Not searched|Nothing found|Found already): /.test(line)
      ? line + " "
      : "LaCuerda gave caracole no songs of theirs this time. ";
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
  // --- what a search says beside its results (/api/search) ------------------------------------------------------
  // The closest artists' names the offline indexes have (``suggest``: each { source, artist, songs, and artist_key
  // or slug }), most likely first, for a query that may be a typo: a line each, "Lynyrd Skynyrd · artist · 212 songs
  // on UG", whose Their songs is ``open(s, button)``. None for none: null.
  const SITE_NAMES = { ug: "UG", lacuerda: "LaCuerda", gtptabs: "gtptabs.com", musescore: "MuseScore" };
  const didYouMean = (suggest, open) => {
    const names = listOf(suggest).filter((s) => s && typeof s === "object" && s.artist);
    if (!names.length) return null;
    const box = el("section", "did-you-mean");
    rowSerial += 1;
    const head = el("h2", "nothing-head", "Did you mean");
    head.id = "did-you-mean-" + rowSerial;
    box.setAttribute("aria-labelledby", head.id);
    const list = el("ul", "suggestions");
    for (const s of names) {
      const name = String(s.artist);
      const item = el("li", "suggestion");
      const said = el("span", "suggest-said");
      said.appendChild(el("span", "suggest-name", name));
      const where = own.call(SITE_NAMES, s.source) ? " on " + SITE_NAMES[s.source] : "";
      said.appendChild(el("span", "suggest-facts", "artist" + (Number(s.songs) ? " · " + many(s.songs, "song") + where : "")));
      item.appendChild(said);
      item.appendChild(button("Their songs", "small their-songs", (e) => open(s, e.currentTarget), "Songs by " + name));
      list.appendChild(item);
    }
    box.append(head, list);
    return box;
  };
  // Where caracole looked (``looked``: a site each, its ``state``, ``label`` and one line of ``detail``), as chips:
  // green searched whole, amber in part, red empty or blocked, grey turned off. A chip is no control: its detail is
  // its tooltip and its description.
  const lookedChips = (looked) => {
    const list = el("ul", "looked");
    list.setAttribute("aria-label", "Where caracole looked");
    for (const s of listOf(looked).filter((x) => x && typeof x === "object")) {
      const state = ["done", "partial", "empty", "blocked", "off"].indexOf(s.state) >= 0 ? s.state : "off";
      const chip = el("li", "site-chip", String(s.label || s.name || ""));
      chip.dataset.state = state;
      chip.dataset.source = String(s.source || "");
      if (s.detail) {
        chip.title = String(s.detail);
        chip.setAttribute("aria-description", String(s.detail));
      }
      list.appendChild(chip);
    }
    return list;
  };
  // Why the query may name an artist the Ultimate Guitar index can't see (``unseen``), folded: what to paste into
  // overrides.toml, and the line that adds a song by its title.
  const whyUnseen = (unseen, query) => {
    const u = unseen && typeof unseen === "object" ? unseen : null;
    if (!u) return null;
    const fold = el("details", "why-unseen");
    fold.appendChild(el("summary", null, "Why can't caracole find it?"));
    fold.appendChild(el("p", null, "Ultimate Guitar's sitemaps name some artists only by a number, mostly those with " +
      "accents or non-Latin letters (Joaquín Sabina, Maná, 宋冬野), so caracole can't see their tabs. If “" + query +
      "” is such an artist, find their page on ultimate-guitar.com and paste its address into overrides.toml:"));
    const entry = el("pre");
    entry.appendChild(el("code", null, String(u.entry || "")));
    fold.appendChild(entry);
    fold.appendChild(el("p", null, "The nightly run then looks there for the songs you add by them."));
    if (u.add) {
      const title = el("p", null, "If it's a title, caracole needs its artist too: ");
      title.appendChild(el("code", null, String(u.add)));
      title.appendChild(document.createTextNode("."));
      fold.appendChild(title);
    }
    return fold;
  };
  // The read of a name LaCuerda's listings don't reach yet (``lacuerda_unlisted``: { name, letter }), one request:
  // ``ask(button, box)``; ``named``, the button says the name (beside results, which may name others).
  const askLaCuerda = (unlisted, ask, box, named) => {
    const u = unlisted && typeof unlisted === "object" ? unlisted : null;
    if (!u) return null;
    const name = String(u.name || "");
    const go = button(named ? "Ask LaCuerda for “" + name + "” (1 request)" : "Ask LaCuerda (1 request)",
      "small ask-lacuerda", (e) => ask(e.currentTarget, box),
      "Ask LaCuerda for “" + name + "”: one request");
    go.title = "LaCuerda's list doesn't reach " + String(u.letter || "") + " yet: caracole reads its page for “" +
      name + "”, one request at a lookup's pace.";
    return go;
  };
  // A search that found nothing (``data``, for ``query``): one card, "Not it?" under the artists it may have meant
  // (didYouMean, drawn above it), else "No song or artist matches “query”": its actions, the request by name first
  // (``does.request``, labelled ``does.requestLabel``) and, while LaCuerda's listings don't reach the name, Ask
  // LaCuerda (``does.ask(button, card)``); where caracole looked; and why it may not see an artist, folded.
  const nothingFound = (data, query, does) => {
    const d = data && typeof data === "object" ? data : {};
    const meant = listOf(d.suggest).some((s) => s && typeof s === "object" && s.artist);
    const card = el("section", "nothing");
    rowSerial += 1;
    const head = el("h2", "nothing-head", meant ? "Not it?" : "No song or artist matches “" + query + "”");
    head.id = "nothing-" + rowSerial;
    card.setAttribute("aria-labelledby", head.id);
    const actions = el("div", "nothing-actions");
    actions.appendChild(button(String(does.requestLabel || "Request “" + query + "” by name"), "small primary",
      () => does.request()));
    const ask = d.lacuerda_unlisted && does.ask ? askLaCuerda(d.lacuerda_unlisted, does.ask, card) : null;
    if (ask) actions.appendChild(ask);
    card.append(head, actions, lookedChips(d.looked));
    const why = whyUnseen(d.unseen, query);
    if (why) card.appendChild(why);
    return card;
  };
  // Under results: where caracole looked, in one muted line, when a site wasn't searched whole; Ask LaCuerda while its
  // listings don't reach the name; the fold for an artist the index may not see. None when all went well: null.
  const lookedLine = (data, query, does) => {
    const d = data && typeof data === "object" ? data : {};
    const looked = listOf(d.looked).filter((x) => x && typeof x === "object");
    const ask = Boolean(d.lacuerda_unlisted && does.ask);
    if (!ask && !d.unseen && looked.every((s) => s.state === "done")) return null;
    const line = el("div", "looked-line");
    line.appendChild(lookedChips(looked));
    if (ask) line.appendChild(askLaCuerda(d.lacuerda_unlisted, does.ask, line, true));
    const why = whyUnseen(d.unseen, query);
    if (why) line.appendChild(why);
    return line;
  };
  return { resultRow, sourceMark, link, titleLink, artistFilter, artistSearch, artistOnly, button, many, counts, opener, ugHit, artistHit,
    siteHit, siteArtist, siteArtistSongs, readArtistPage, searchLaCuerda, lacuerdaSearcher, readOutcome, indexLine, titleLine,
    didYouMean, lookedChips, nothingFound, lookedLine };
};
