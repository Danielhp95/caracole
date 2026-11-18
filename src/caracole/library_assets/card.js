// A song of yours on index.html: on its line, a button for each thing to play from (``plays``, rows.js puts them right
// after its title), and opened, what card.css draws as a card under its line (library.js lineFor puts these parts in
// its panel): what you play from it as tiles, each with a chevron that opens its drawer right under it (its downloads,
// then a part a source of its versions), which sites have it, its progressions, the links that find it elsewhere, and
// its foot. Drawn from the song's data alone, with createElement, createElementNS and textContent: a button opens a
// file of the library's, and opening a drawer asks nothing of anyone. ``icons``: the data's sources (icons.py);
// ``rows``: caracoleRows', whose marks, glyphs and links it shares.
//
// ``caracoleMenus``, card.js's one listener of the browser's history: on a touch screen a card's ⋯ menu opened is a
// step of its own, { caracoleMenu: n } (n a serial; while searching, one more of search's steps than the entry under
// it, ``search`` the count under it + 1, never a copy of that entry's), at the address as it is, so that Back closes
// the menu and leaves its card open. Closed otherwise (a choice in it, Escape, a press elsewhere, its card drawn
// again), its entry is taken back, once the press's own handlers ran: one of the page's that pushed an entry of its
// own keeps it. A press that leaves the page (a link opened in this window, a download but on a page opened as a
// file) or goes back through the history (search's ←, whose steps count the menu's) is left to do it: the entry
// stays, marked { caracoleMenu: "closed" }, never taken back then, which would cancel the one or add a step to the
// other. Back and Forward pass over a closed menu's entry, the way the browser went. A menu opened as another closes
// takes that one's entry. A reload with a menu open leaves its entry the page's (one Back spent on it). With a mouse a
// menu is no step, and a browser that refuses the step opens and closes it all the same.
const caracoleMenus = (() => {
  "use strict";
  const MENU = "caracoleMenu";
  const CLOSED = "closed";
  // The serial of the last menu's entry, counted from the page's load time, so that an entry a reload left in the
  // history (the page reloaded with a menu open) is never taken for a new one's.
  let menus = Date.now();
  let shown = null;  // { more, n }: the menu open whose entry is the history's
  let closing = 0;  // the serial of a menu closed whose entry is still to be taken back
  let press = null;  // the last press while a menu is open or closing
  let leaving = false;  // the page began to leave meanwhile (the Navigation API's word for it, or pagehide)
  const nav = typeof window.navigation === "object" && window.navigation ? window.navigation : null;
  let from = -1;  // the history's index the last change came from, where the Navigation API tells it
  const ours = (n) => Boolean(history.state && history.state[MENU] === n);
  // A press that leaves the page or steps back through the history, its handlers run: a link opened in this window
  // (a download stays, but on a page opened as a file, which downloads nothing and opens it), or search's ←, while
  // the entry it goes back from is search's (its steps then count the menu's).
  const leaves = (e) => {
    const at = e && e.target instanceof Element ? e.target : null;
    if (!at || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return false;
    if (at.closest("#leave")) return Number(history.state && history.state.search) > 0;
    const a = at.closest("a[href]");
    if (!a || (a.target && a.target !== "_self")) return false;
    return !a.hasAttribute("download") || location.protocol === "file:";
  };
  addEventListener("click", (e) => { if (shown || closing) press = e; }, true);
  const left = () => { if (shown || closing) leaving = true; };
  addEventListener("pagehide", left);
  if (nav && typeof nav.addEventListener === "function") {
    nav.addEventListener("navigate", (e) => {  // a download's name may be "": a string all the same
      if (typeof e.downloadRequest !== "string" && e.navigationType !== "replace") left();
    });
    nav.addEventListener("currententrychange", (e) => { from = e.from && e.from.index >= 0 ? e.from.index : -1; });
  }
  // A menu open whose card is drawn again (its request over) goes with the card it was in: its entry too, as when it
  // closes. Watched while it is open; a card moved (from its line to the pane) is back in the page by then.
  const gone = typeof MutationObserver === "function"
    ? new MutationObserver(() => { if (shown && !shown.more.isConnected) closed(shown.more); }) : null;
  const show = (more, n) => {
    shown = { more, n };
    press = null;
    leaving = false;
    if (gone) gone.observe(document.body, { childList: true, subtree: true });
  };
  const hide = () => {
    shown = null;
    if (gone) gone.disconnect();
  };
  addEventListener("popstate", () => {
    if (shown && !ours(shown.n)) {  // Back, or the ← of search, took its entry: it closes
      const was = shown.more;
      hide();
      was.open = false;
    }
    if (shown || !(history.state && history.state[MENU])) return;
    // A closed menu's entry, or one a reload left: passed over, Forward's way where the Navigation API says so.
    const at = nav && nav.currentEntry ? nav.currentEntry.index : -1;
    if (at >= 0 && from >= 0 && from < at) history.forward();
    else history.back();
  });
  const opened = (more) => {
    if (!matchMedia("(pointer: coarse)").matches) return;
    if (closing && ours(closing)) {  // the entry of a menu that closed as this one opened: this one's now
      show(more, closing);
      closing = 0;
      return;
    }
    const n = menus + 1;
    const entry = { [MENU]: n };
    if (document.body.classList.contains("search-mode")) {
      entry.search = (Number(history.state && history.state.search) || 0) + 1;
    }
    try {
      history.pushState(entry, "");
      menus = n;
      show(more, n);
    } catch (err) {
      // A browser that refuses the step: the menu opens all the same, with none.
    }
  };
  const closed = (more) => {
    if (!shown || shown.more !== more) return;
    const n = shown.n;
    hide();
    closing = n;
    setTimeout(() => {  // after the press's own handlers: one that pushed an entry of its own keeps it
      if (closing !== n) return;  // another menu took it
      closing = 0;
      const by = press;
      press = null;
      if (!ours(n)) return;  // the history is elsewhere: Back's, or another entry of the page's
      if (leaving || leaves(by)) {  // the press goes on: the entry stays, closed, for Back and Forward to pass over
        try {
          history.replaceState(Object.assign({}, history.state, { [MENU]: CLOSED }), "");
        } catch (err) {
          // Left as it is: Back passes over it all the same.
        }
      } else {
        history.back();
      }
    }, 0);
  };
  return { opened, closed };
})();

const caracoleCard = (icons, rows) => {
  "use strict";
  const own = Object.prototype.hasOwnProperty;
  const ICONS = icons && typeof icons === "object" ? icons : {};
  const { glyph, sourceMark, siteMarks, safeHref, link, many } = rows;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const nameOf = (key) => (typeof key === "string" && own.call(ICONS, key) && ICONS[key] && ICONS[key].name
    ? String(ICONS[key].name) : "this folder");
  let serial = 0;
  const idFor = (what) => {
    serial += 1;
    return "card-" + what + "-" + serial;
  };
  // A link of the library's (``href``, relative); a download (``download``, the name it saves under, else the
  // file's own), or one to another site, opened in a new tab (``external``).
  const anchor = (href, cls, how) => {
    const h = how || {};
    const a = el("a", cls);
    a.href = safeHref(href, Boolean(h.external));
    if (h.external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    } else if (typeof h.download === "string") {
      a.setAttribute("download", h.download);
    }
    return a;
  };
  const withGlyph = (node, name, text) => {
    node.appendChild(glyph(name));
    if (text) node.appendChild(document.createTextNode(text));
    return node;
  };
  const percent = (share) => Math.round(Number(share) * 100) + "%";
  // How much of the song's lyrics a sheet has, as caracole scored it (coverage.py): every line, or its share; ""
  // for one never scored. Enough to count as whole (``complete``, rank.py's threshold): in the found colour.
  const lyricsShare = (complete, coverage) => {
    if (typeof coverage !== "number") return "";
    const said = coverage >= 0.995 ? "All the lyrics" : percent(coverage) + " of the lyrics";
    return complete === true ? el("b", null, said) : said;
  };
  // A version's rating with its votes, as the sheet's versions list writes it: "★ 4.85 (12,629)", "New" for none.
  const rated = (v) => typeof v.rating === "number" && isFinite(v.rating) && Number(v.votes) > 0
    ? "★ " + v.rating.toFixed(2) + " (" + Number(v.votes).toLocaleString("en") + ")" : "New";

  // --- the files, by what they are -----------------------------------------------------------------------------
  const SHEET_FILES = [["sheet.pdf", "PDF"], ["sheet.txt", "Text"], ["sheet.cho", "ChordPro"]];
  const AUTO_FILES = [["sheet (auto).pdf", "PDF"], ["sheet (auto).txt", "Text"], ["sheet (auto).cho", "ChordPro"]];
  const HUMAN = /^sheet[.](html|pdf|txt|cho)$/;
  const AUTO = /^sheet [(]auto[)][.](html|pdf|txt|cho)$/;
  const GUITAR = /^guitar-\d+[.]([A-Za-z0-9]+)$/;
  const HARMONICA = /^harmonica-\d+[.]txt$/;
  // A harmonica tab's page beside it (``harmonicaPage``: render.py's harmonica-N.html), which its tile and its row open.
  const harpPage = (f) => (f && f.harmonicaPage && typeof f.harmonicaPage.href === "string" ? f.harmonicaPage.href : "");
  const SCORE = /^score-\d+[.]([a-z]+)$/;
  const GAMETAB = /^gametab-\d+[.]txt$/;  // a text tab of game music from gametabs.net
  const SCORE_FORMATS = { mscz: "MuseScore", mxl: "MusicXML", musicxml: "MusicXML", pdf: "PDF", mid: "MIDI",
    midi: "MIDI" };
  const LYRICS = ["lyrics.txt", "lyrics.lrc"];
  // A file's label without where it came from ("Guitar Pro 1 · gtptabs.com": "Guitar Pro 1").
  const plainLabel = (f) => String(f.label || f.name || "").split(" · ")[0];
  // The files of one kind, by where each came from, in their order: [{ source, files }].
  const bySource = (files) => {
    const groups = [];
    for (const f of files) {
      const key = typeof f.source === "string" && f.source ? f.source : "";
      let group = groups.find((g) => g.source === key);
      if (!group) groups.push(group = { source: key, files: [] });
      group.files.push(f);
    }
    return groups;
  };

  // --- a tile's drawer: a part a source of its versions --------------------------------------------------------
  // A part's head (the source's mark, what it lists, what it counts, and its ``extra``: Back to our pick, the pin's
  // note), then a row a version: a { ver, stars, note, actions, cls } versionRow draws, each of ``note`` and
  // ``actions`` a Node or a text.
  const drawerHead = (source, what, said, extra) => {
    const head = el("div", "drawer-head");
    const mark = sourceMark(source);
    if (mark) head.appendChild(mark);
    head.appendChild(el("h4", "drawer-what", what));
    if (said) head.appendChild(el("span", "drawer-said", said));
    for (const node of listOf(extra)) if (node) head.appendChild(node);
    return head;
  };
  const versionRow = (r) => {
    const row = el("li", "vrow" + (r.cls ? " " + r.cls : ""));
    row.appendChild(el("span", "ver", r.ver));
    const stars = el("span", "stars");
    const cut = String(r.stars || "").indexOf(" (");
    if (r.stars === "New") stars.appendChild(el("span", "new", "New"));
    else if (!r.stars) { /* a file with no rating: an empty cell */ }
    else if (cut < 0) stars.appendChild(el("b", null, r.stars));
    else {
      stars.appendChild(el("b", null, r.stars.slice(0, cut)));
      stars.appendChild(document.createTextNode(r.stars.slice(cut)));
    }
    row.appendChild(stars);
    const note = el("span", "note");
    listOf(r.note).filter(Boolean).forEach((part, n) => {
      if (n) note.appendChild(document.createTextNode(" · "));
      note.appendChild(part instanceof Node ? part : document.createTextNode(String(part)));
    });
    if (note.textContent) note.title = note.textContent;
    row.appendChild(note);
    const acts = el("span", "vbtns");
    for (const node of listOf(r.actions)) if (node) acts.appendChild(node);
    row.appendChild(acts);
    return row;
  };
  const inUse = () => withGlyph(el("span", "inuse"), "check", "In use");
  const openLink = (href, said, how) => {
    const a = anchor(href, "btn small go", how);
    a.textContent = how && how.external ? "Its page ↗" : "Open";
    a.setAttribute("aria-label", said);
    return a;
  };
  const downloadLink = (f, label, said) => {
    const a = anchor(f.href, "dl", { download: typeof f.download === "string" ? f.download : "" });
    withGlyph(a, "download", label);
    a.setAttribute("aria-label", said);
    a.title = said;
    return a;
  };

  // Whether the sheet's drawer has a part of Ultimate Guitar's versions (``versions``, the data's): UG has some, or
  // caracole keeps some.
  const ugListed = (v) => Boolean(v && typeof v === "object" && (Number(v.total) > 0 || listOf(v.list).length));
  // Ultimate Guitar's versions of the sheet (the data's ``versions``): the kept ones in rank order, the one in use,
  // and the rest counted, with what fetches them (``acts``).
  const ugDrawer = (s, part, acts) => {
    const v = s.versions;
    const list = listOf(v.list).filter((x) => x && typeof x === "object");
    const title = String(s.title);
    const ukulele = listOf(s.instruments).indexOf("ukulele") >= 0;
    const extra = [];
    if (v.pinned && acts.clear) extra.push(acts.clear());
    part.appendChild(drawerHead("ug", "UG · " + (ukulele ? "ukulele chords" : "chord sheets"),
      Number(v.total || 0).toLocaleString("en") + " on UG · " + list.length + " in your logbook", extra));
    const ol = el("ol", "vrows");
    for (const x of list) {
      const ver = "Ver " + (Number(x.number) || "?");
      const share = lyricsShare(x.complete, x.coverage);
      const note = [];
      if (x.gone) note.push("gone from UG");
      if (typeof x.label === "string" && x.label) note.push(x.label.charAt(0).toUpperCase() + x.label.slice(1));
      if (share) note.push(share);
      if (x.note) note.push(String(x.note));
      if (x.chosen) note.push(v.pinned ? "your choice" : "our pick");
      const actions = [];
      if (x.chosen) actions.push(inUse());
      else if (!x.gone && acts.choose) actions.push(acts.choose(x, ver));
      actions.push(openLink(x.href, "Open " + ver + " of " + title));
      ol.appendChild(versionRow({ ver, stars: rated(x), note, actions,
        cls: (x.chosen ? "cur" : "") + (x.gone ? " gone" : "") }));
    }
    part.appendChild(ol);
    const rest = Number(v.rest) || 0;
    if (rest > 0) {
      const more = el("div", "drawer-rest");
      more.appendChild(el("span", "rest-said", rest + " more on UG, not kept"));
      const fetch = acts.keepMore ? acts.keepMore(rest, Number(v.keepMore) || 0) : null;
      if (fetch) {
        more.appendChild(fetch);
      } else if (acts.keepMoreCommand) {
        const said = el("span", "rest-command", "Keep them: ");
        said.appendChild(el("code", null, acts.keepMoreCommand));
        more.appendChild(said);
      }
      part.appendChild(more);
    }
  };
  // The LaCuerda sheets caracole met for the song (``lacuerdaVersions``), best first: each its page on LaCuerda, its
  // share of the lyrics, and In use for the sheet, else what keeps it (``acts.useLaCuerda``). A UG version you chose
  // (a [pin]) outranks a LaCuerda pick: while one does, its part says so and keeps none; what takes the pin out is the
  // UG part's Back to our pick, right above it, which its note points to (one button in the drawer), or its own when
  // the drawer has no UG part.
  const lacuerdaDrawer = (s, part, acts) => {
    const met = listOf(s.lacuerdaVersions).filter((x) => x && typeof x === "object");
    const title = String(s.title);
    const pinned = Boolean(s.versions && s.versions.pinned) && Boolean(acts.useLaCuerda);
    const extra = [];
    if (pinned && ugListed(s.versions)) {
      extra.push(el("p", "pin-note", "Your UG choice is in use: Back to our pick, above, first."));
    } else if (pinned) {
      extra.push(el("p", "pin-note", "Your UG choice is in use. Back to our pick first."));
      if (acts.clear) extra.push(acts.clear());
    }
    part.appendChild(drawerHead("lacuerda", "LaCuerda · chord sheets", many(met.length, "version") + " seen",
      extra));
    const ol = el("ol", "vrows");
    met.forEach((x, n) => {
      const ver = "Version " + (n + 1);
      const actions = [];
      if (x.sheet) actions.push(inUse());
      else if (acts.useLaCuerda && !pinned) actions.push(acts.useLaCuerda(x, ver));
      actions.push(openLink(x.href, ver + " of " + title + " on LaCuerda, new tab", { external: true }));
      ol.appendChild(versionRow({ ver, note: [lyricsShare(null, x.coverage) || "not scored"], actions,
        cls: x.sheet ? "cur" : "" }));
    });
    part.appendChild(ol);
  };
  // The auto sheet beside a human one (``autoSheet``): its viewer, and its files.
  const autoDrawer = (s, part) => {
    const a = s.autoSheet;
    const title = String(s.title);
    part.appendChild(drawerHead("auto", "Auto sheet · from the recording", "made by us from the audio"));
    const ol = el("ol", "vrows");
    const downloads = listOf(a.files).filter((f) => f && f.href)
      .map((f) => downloadLink(f, String(f.label), "Download the auto sheet's " + String(f.label) + " of " + title));
    ol.appendChild(versionRow({ ver: "Auto sheet", note: downloads.length ? downloads : [],
      actions: [openLink(a.href, "Open the auto sheet of " + title)] }));
    part.appendChild(ol);
  };
  // One source's files of a tile (``group``): a row each, its label, Open where the page shows it, and Download.
  const filesDrawer = (s, part, t, group) => {
    const title = String(s.title);
    part.appendChild(drawerHead(group.source, nameOf(group.source) + " · " + t.plural,
      many(group.files.length, t.unit)));
    const ol = el("ol", "vrows");
    for (const f of group.files) {
      const label = plainLabel(f);
      const actions = [];
      const opens = t.opener ? t.opener(f) : null;
      if (opens) actions.push(openLink(opens.href, "Open " + label + " of " + title, opens));
      actions.push(downloadLink(f, "Download", "Download " + label + " of " + title));
      ol.appendChild(versionRow({ ver: label, note: [String(f.name)], actions }));
    }
    part.appendChild(ol);
  };

  // --- the tiles ----------------------------------------------------------------------------------------------
  // A tile, one thing to play from (``things``): its body opens what it holds (``open``, ``said`` its name for a screen
  // reader), its subtitle says which (``from``); after it the marks of where its versions came from (``sources``, two
  // at most, as its line's button), or, for one source that links back to its page (a fixed chip's ``href``:
  // Megalobiz's or AZLyrics' lyrics), that link; then a chevron, which opens its drawer (``tiles``), when that would
  // hold anything: its downloads (``downloads``), then a part a source of its versions (``partsOf``). More than one
  // version: a small stack. Every tile alike, none first; an auto sheet's in its own colour.
  const MARKS_SHOWN = 2;  // a tile's marks, and its line's button's
  const UNIT_WORDS = { version: "versions", file: "files", tab: "tabs" };
  // The parts of a tile's drawer: its chips that list something (``fill``), but a tile's one chip with one version,
  // which its mark says all of.
  const partsOf = (t) => {
    const chips = listOf(t.chips);
    return chips.length === 1 && chips[0].fixed ? [] : chips.filter((c) => typeof c.fill === "function");
  };
  const tileOf = (t) => {
    const box = el("div", "tile tile-" + t.kind + (t.auto ? " auto" : ""));
    const chips = listOf(t.chips);
    if (chips.reduce((n, c) => n + (Number(c.count) || 0), 0) > 1) box.classList.add("stack");
    const open = anchor(t.open.href, "tile-open", t.open);
    open.setAttribute("aria-label", t.said);
    const ico = el("span", "tile-ico");
    ico.appendChild(glyph(t.glyph));
    const words = el("span", "tile-words");
    const name = words.appendChild(el("span", "tile-name", t.name));
    name.id = idFor("tile");
    if (t.version) {  // the sheet's version in use: its number, its rating whole or not at all, and "in use"
      const from = words.appendChild(el("span", "tile-from", t.version.ver));
      if (t.version.rated) from.append(" · ", el("span", "tile-rated", t.version.rated));
      from.appendChild(el("span", "tile-in-use", " · in use"));
      from.id = idFor("from");
      open.setAttribute("aria-describedby", from.id);
    } else if (t.from) {
      const from = words.appendChild(el("span", "tile-from", t.from));
      from.id = idFor("from");
      open.setAttribute("aria-describedby", from.id);
    }
    const go = el("span", "tile-go");
    go.appendChild(glyph(t.open.download !== undefined ? "download" : "open"));
    open.append(ico, words, go);
    box.appendChild(open);
    const one = chips.length === 1 && chips[0].fixed ? chips[0] : null;
    if (one && one.href) {
      const back = anchor(one.href, "tile-source", { external: true });
      back.setAttribute("aria-label", t.name + ": its page on " + nameOf(one.source));
      const mark = sourceMark(one.source);
      if (mark) back.appendChild(mark);
      back.appendChild(el("span", "tile-source-name", nameOf(one.source)));
      box.appendChild(back);
    } else {
      const marks = el("span", "tile-source");
      for (const key of listOf(t.sources).slice(0, MARKS_SHOWN)) {
        const mark = sourceMark(key);
        if (mark) marks.appendChild(mark);
      }
      if (marks.childNodes.length) box.appendChild(marks);
    }
    const holds = [partsOf(t).length ? UNIT_WORDS[t.unit] || "versions" : "",
      listOf(t.downloads).length ? "downloads" : ""].filter(Boolean);
    if (holds.length) {
      const more = el("button", "tile-more");
      more.type = "button";
      const said = t.name + ": its " + holds.join(" and ");
      more.setAttribute("aria-label", said);
      more.title = said;
      more.setAttribute("aria-expanded", "false");
      more.appendChild(glyph("chevron"));
      box.appendChild(more);
    }
    return box;
  };

  // What a song of yours holds to play from, in this order: its chord sheet (the human one, else the auto one; UG's
  // Ukulele Chords), its Guitar Pro files, its text tab, its harmonica tabs, its tabs of game music, its lyrics and the
  // scores you filed; a tile each in its card (tiles), and but its lyrics a button each on its line (plays). Each
  // { kind, glyph, name, open, said, from, version, chips, downloads, opener, auto, sources, count, unit }: ``from``,
  // which it is; ``version``, the sheet's version in use ({ ver, rated }), which its tile's from line is made of;
  // ``chips``, its versions a source each ({ source, count, unit, fixed, href, fill(part) }: ``fixed``, one version
  // and nothing to choose; ``href``, a fixed source's page to link back to; ``fill``, what draws that source's part
  // of its drawer);
  // ``downloads``, its formats' links; ``sources``, where its versions came from, the one in use first; ``count``, how
  // many versions of it the card lists (in its drawer, or as files), in ``unit``s. ``opts``: ``guitar``, caracole
  // serve shows Guitar Pro files (alphaTab); ``acts``, what a drawer's versions do (Use this one, Fetch them, Back to
  // our pick, LaCuerda's Use this one: each makes its control; or, from the file, ``keepMoreCommand``, the command
  // that fetches them). ``claimed``, given, gets every file a tile shows.
  const things = (s, opts) => {
    const o = opts || {};
    const acts = o.acts || {};
    const title = String(s.title);
    const files = listOf(s.files).filter((f) => f && typeof f.name === "string" && f.href);
    const named = (n) => files.find((f) => f.name === n) || null;
    const claim = (f) => {
      if (f && o.claimed) o.claimed.add(f);
      return f;
    };
    const made = [];

    // The chord sheet: the human one, else the auto one; its versions from each source.
    const primary = files.find((f) => f.primary) || null;
    const autoOnly = s.auto === true;
    if (primary && (HUMAN.test(primary.name) || AUTO.test(primary.name))) {
      const auto = s.autoSheet && typeof s.autoSheet === "object" && !autoOnly ? s.autoSheet : null;
      files.filter((f) => (autoOnly ? AUTO : HUMAN).test(f.name) || (auto && AUTO.test(f.name))).forEach(claim);
      const ukulele = listOf(s.instruments).indexOf("ukulele") >= 0;
      const name = autoOnly ? "Auto sheet" : ukulele ? "Ukulele chords" : "Chord sheet";
      const v = s.versions && typeof s.versions === "object" ? s.versions : null;
      const one = v ? listOf(v.list).find((x) => x && x.chosen) : null;
      const version = one ? { ver: "Ver " + (Number(one.number) || "?"), rated: rated(one) } : null;
      const from = version ? [version.ver, version.rated, "in use"].filter(Boolean).join(" · ")
        : autoOnly || s.source === "auto" || s.source === "youtube" ? "from the recording"
        : s.source ? nameOf(s.source) : "";
      const chips = [];
      if (ugListed(v)) {
        chips.push({ source: "ug", count: Number(v.total) || listOf(v.list).length, unit: "version",
          fixed: Number(v.total) <= 1 && !(Number(v.rest) > 0), fill: (part) => ugDrawer(s, part, acts) });
      }
      const met = listOf(s.lacuerdaVersions);
      if (met.length) {
        chips.push({ source: "lacuerda", count: met.length, unit: "version",
          fixed: met.length === 1 && Boolean(met[0] && met[0].sheet),
          fill: (part) => lacuerdaDrawer(s, part, acts) });
      }
      if (auto) {
        chips.push({ source: "auto", count: 1, unit: "version", fixed: false, fill: (part) => autoDrawer(s, part) });
      }
      if (!chips.length && s.source) chips.push({ source: String(s.source), count: 1, fixed: true });
      const downloads = (autoOnly ? AUTO_FILES : SHEET_FILES).map(([n, label]) => [named(n), label])
        .filter(([f]) => f).map(([f, label]) => downloadLink(f, label, "Download the " + label + " of " + title));
      for (const f of files.filter((x) => typeof x.version === "string" && x.version)) {
        claim(f);
        downloads.push(downloadLink(f, "PDF · " + f.version, "Download the PDF of " + title + " in " + f.version));
      }
      // Its versions the card lists: UG's kept, LaCuerda's met, the auto sheet beside it; and the one in use, if none
      // of those is it (a sheet from your inbox, say). Where they came from, the one in use first.
      const kept = v ? listOf(v.list).filter((x) => x && typeof x === "object").length : 0;
      const listed = kept + met.length + (auto ? 1 : 0);
      const inUse = (s.source === "ug" && kept > 0) || (s.source === "lacuerda" && met.some((x) => x && x.sheet));
      const sources = [s.source, kept ? "ug" : "", met.length ? "lacuerda" : "", auto ? "auto" : ""];
      made.push({ kind: "sheet", glyph: ukulele ? "ukulele" : "sheet", name, auto: autoOnly,
        open: { href: primary.href }, said: "Open the " + name.toLowerCase() + " of " + title, from, version,
        chips, downloads, sources: distinct(sources), count: listed + (inUse ? 0 : 1),
        unit: "version" });
    }

    // Guitar Pro files (or a Power Tab file); and a text tab, a thing of its own.
    const guitar = files.filter((f) => GUITAR.test(f.name));
    const tab = named("tab.txt");
    const browser = (f) => (o.guitar && typeof f.guitarPage === "string" && f.guitarPage ? { href: f.guitarPage }
      : null);
    if (guitar.length) {
      guitar.forEach(claim);
      const first = guitar[0];
      const shown = browser(first);
      const ext = "." + GUITAR.exec(first.name)[1].toLowerCase();
      const t = { kind: "guitar", glyph: "guitar", name: "Guitar Pro", plural: "Guitar Pro files", unit: "file",
        open: shown || { href: first.href, download: typeof first.download === "string" ? first.download : "" },
        said: (shown ? "Open the Guitar Pro tab of " : "Download the Guitar Pro file of ") + title,
        from: String(first.name),
        downloads: [downloadLink(first, ext, "Download " + plainLabel(first) + " of " + title)],
        opener: (f) => browser(f), count: guitar.length };
      t.chips = bySource(guitar).map((g) => ({ source: g.source, count: g.files.length, unit: "file",
        fixed: g.files.length === 1, fill: (part) => filesDrawer(s, part, t, g) }));
      made.push(t);
    }
    if (tab) {
      claim(tab);
      made.push({ kind: "tab", glyph: "guitar", name: "Guitar tab", open: { href: tab.href },
        said: "Open the guitar tab of " + title, from: tab.source ? nameOf(tab.source) : "a text tab",
        chips: tab.source ? [{ source: tab.source, count: 1, fixed: true }] : [],
        downloads: [downloadLink(tab, "Text", "Download the guitar tab of " + title)], count: 1, unit: "tab" });
    }

    // Harmonica tabs.
    const harp = files.filter((f) => HARMONICA.test(f.name));
    if (harp.length) {
      harp.forEach(claim);
      const first = harp[0];
      const t = { kind: "harmonica", glyph: "harmonica", name: "Harmonica tab", plural: "harmonica tabs", unit: "tab",
        open: { href: harpPage(first) || first.href }, said: "Open the harmonica tab of " + title,
        from: plainLabel(first).replace(/^Harmonica tab/, "Tab"),
        downloads: [downloadLink(first, "Text", "Download " + plainLabel(first) + " of " + title)],
        opener: (f) => ({ href: harpPage(f) || f.href }), count: harp.length };
      t.chips = bySource(harp).map((g) => ({ source: g.source, count: g.files.length, unit: "tab",
        fixed: g.files.length === 1, fill: (part) => filesDrawer(s, part, t, g) }));
      made.push(t);
    }

    // Text tabs of game music from gametabs.net, opened as text, as Ultimate Guitar's tab.txt is.
    const games = files.filter((f) => GAMETAB.test(f.name));
    if (games.length) {
      games.forEach(claim);
      const first = games[0];
      const t = { kind: "gametab", glyph: "guitar", name: "Game music tab", plural: "game music tabs", unit: "tab",
        open: { href: first.href }, said: "Open the game music tab of " + title,
        from: plainLabel(first).replace(/^Game music tab/, "Tab"),
        downloads: [downloadLink(first, "Text", "Download " + plainLabel(first) + " of " + title)],
        opener: (f) => ({ href: f.href }), count: games.length };
      t.chips = bySource(games).map((g) => ({ source: g.source, count: g.files.length, unit: "tab",
        fixed: g.files.length === 1, fill: (part) => filesDrawer(s, part, t, g) }));
      made.push(t);
    }

    // Lyrics, plain and timed: LRCLIB's, or Megalobiz's or AZLyrics', whose tile links to their page there
    // (``lyricsFrom``).
    const lyrics = LYRICS.map(named).filter(Boolean);
    if (lyrics.length) {
      lyrics.forEach(claim);
      const plain = named("lyrics.txt");
      const timed = named("lyrics.lrc");
      const downloads = [];
      if (plain) downloads.push(downloadLink(plain, "Text", "Download the lyrics of " + title));
      if (timed) downloads.push(downloadLink(timed, "Timed (.lrc)", "Download the timed lyrics of " + title));
      const source = lyrics[0].source;
      const from = s.lyricsFrom && s.lyricsFrom.source === source && typeof s.lyricsFrom.href === "string"
        ? s.lyricsFrom.href : null;
      made.push({ kind: "lyrics", glyph: "lyrics", name: "Lyrics", open: { href: lyrics[0].href },
        said: "Open the lyrics of " + title, from: timed ? "timed" : "plain",
        chips: source ? [{ source, count: 1, fixed: true, href: from }] : [], downloads });
    }

    // Scores you filed.
    const scores = files.filter((f) => SCORE.test(f.name));
    if (scores.length) {
      scores.forEach(claim);
      const first = scores[0];
      const format = (f) => SCORE_FORMATS[SCORE.exec(f.name)[1]] || f.name;
      const pdf = /[.]pdf$/i.test(first.name);
      const t = { kind: "score", glyph: "score", name: "Score", plural: "scores", unit: "file",
        open: pdf ? { href: first.href } : { href: first.href, download: typeof first.download === "string"
          ? first.download : "" },
        said: (pdf ? "Open the score of " : "Download the score of ") + title, from: plainLabel(first),
        downloads: scores.map((f) => downloadLink(f, format(f), "Download " + plainLabel(f) + " of " + title)),
        opener: (f) => (/[.]pdf$/i.test(f.name) ? { href: f.href } : null), count: scores.length };
      t.chips = bySource(scores).map((g) => ({ source: g.source, count: g.files.length, unit: "file",
        fixed: g.files.length === 1, fill: (part) => filesDrawer(s, part, t, g) }));
      made.push(t);
    }

    for (const t of made) {  // where each came from, as its chips say, but where it said already (the sheet's)
      if (!t.sources) t.sources = distinct(listOf(t.chips).map((c) => c.source));
      if (!t.count) t.count = 1;
    }
    return made;
  };
  const distinct = (keys) => keys.filter((k, n) => typeof k === "string" && k && keys.indexOf(k) === n);

  // A tile each (``things``, the same ``opts``), and one drawer, which a tile's chevron opens right after its tile
  // (closing it under another), the chevron again closes, and so do its ✕ and Escape (in the drawer, or on the chevron
  // while it shows), the focus back on the chevron:
  // made each time it opens (``fill``), its tile's downloads (made once, in ``things``, and moved into it), then a part
  // a source (each chip's ``fill``, so a version's buttons are as the song is now), and emptied as it closes. Null for
  // no tile.
  const tiles = (s, opts) => {
    const made = things(s, opts);
    if (!made.length) return null;
    const box = el("div", "tiles");
    const drawer = el("div", "drawer");  // a region, named by its tile; no section, as a line's group has one
    drawer.setAttribute("role", "region");
    drawer.id = idFor("drawer");
    drawer.hidden = true;
    let opened = null;  // the { tile, more } whose drawer shows
    const close = (focusBack) => {
      const was = opened;
      opened = null;
      drawer.hidden = true;
      drawer.replaceChildren();
      drawer.removeAttribute("aria-labelledby");
      delete drawer.dataset.tile;
      if (!was) return;
      was.tile.classList.remove("open");
      was.more.setAttribute("aria-expanded", "false");
      if (focusBack) was.more.focus();
    };
    const fill = (t, tile, more) => {
      const shut = el("button", "drawer-close");
      shut.type = "button";
      shut.title = "Close";
      shut.setAttribute("aria-label", "Close: " + t.name);
      shut.appendChild(glyph("close"));
      shut.addEventListener("click", () => close(true));
      drawer.replaceChildren(shut);
      const downloads = listOf(t.downloads);
      if (downloads.length) {
        const files = el("div", "drawer-files");
        files.appendChild(el("span", "lead", "Download"));
        for (const d of downloads) files.appendChild(d);
        drawer.appendChild(files);
      }
      for (const c of partsOf(t)) {
        const part = el("section", "drawer-part");
        part.dataset.source = typeof c.source === "string" ? c.source : "";
        c.fill(part);
        drawer.appendChild(part);
      }
      const name = tile.querySelector(".tile-name");
      if (name) drawer.setAttribute("aria-labelledby", name.id);
      drawer.dataset.tile = t.kind;
      tile.after(drawer);
      tile.classList.add("open");
      more.setAttribute("aria-expanded", "true");
      drawer.hidden = false;
      opened = { tile, more };
    };
    const escape = (e) => {
      if (e.key !== "Escape" || !opened) return;
      e.preventDefault();
      e.stopPropagation();
      close(true);
    };
    drawer.addEventListener("keydown", escape);
    for (const t of made) {
      const tile = tileOf(t);
      const more = tile.querySelector(":scope > .tile-more");
      if (more) {
        more.setAttribute("aria-controls", drawer.id);
        more.addEventListener("click", () => {
          const was = Boolean(opened) && opened.more === more;
          close(false);
          if (!was) fill(t, tile, more);
        });
        more.addEventListener("keydown", (e) => {  // its own drawer's: another chevron's Escape is the page's
          if (opened && opened.more === more) escape(e);
        });
      }
      box.appendChild(tile);
    }
    box.appendChild(drawer);
    return box;
  };

  // --- the line's buttons -------------------------------------------------------------------------------------
  // A song's line has a button for each thing it holds to play from but its lyrics (``things``, the same ``opts``),
  // in their order, none first: a link that opens it at once (its viewer, its harmonica tab's page, the Guitar Pro
  // page, the file: what its tile opens). Each its instrument's glyph (an auto sheet's in its own colour), the marks
  // of the sites its versions came from at its foot (two at most, the one in use first), how many versions the card
  // lists of it at its corner when more than one; named for all of it ("Open the harmonica tab of Creep, from
  // harptabs.com, 2 tabs"), and ``data-inst`` the Filter panel's instruments it is one of (library.js INSTRUMENTS),
  // which filter.css lights while one is on. None: null.
  const PLAYS = ["sheet", "guitar", "tab", "harmonica", "gametab", "score"];
  const listed = (names) => (names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names[names.length - 1]
    : names.join(""));
  const instOf = (s, t) => (t.kind === "sheet"
    ? (listOf(s.instruments).indexOf("ukulele") >= 0 ? "sheet ukulele" : "sheet")
    : t.kind === "harmonica" || t.kind === "score" ? t.kind : "guitar");
  // With a mouse each button is a chip that says what it is and where it came from ("Chords · UG"): the kind, then
  // the site of its first source (the one in use); the words are for the eye (aria-hidden), the name is the label.
  const PLAY_KIND = { sheet: "Chords", ukulele: "Ukulele", auto: "Auto sheet", guitar: "Guitar Pro", tab: "Tab",
    harmonica: "Harmonica", gametab: "Game tab", score: "Score" };
  const PLAY_SITE = { auto: "", inbox: "inbox" };
  const playWords = (t) => {
    const words = el("span", "play-words");
    words.setAttribute("aria-hidden", "true");
    const key = t.kind === "sheet" ? (t.auto ? "auto" : t.glyph === "ukulele" ? "ukulele" : "sheet") : t.kind;
    words.appendChild(el("span", "play-kind", PLAY_KIND[key]));
    const first = t.sources[0];
    const site = typeof first !== "string" ? "" : own.call(PLAY_SITE, first) ? PLAY_SITE[first]
      : own.call(ICONS, first) && ICONS[first] && ICONS[first].name ? String(ICONS[first].name) : "";
    if (site) words.appendChild(el("span", "play-site", " · " + site));
    return words;
  };
  const plays = (s, opts) => {
    const shown = things(s, opts).filter((t) => PLAYS.indexOf(t.kind) >= 0);
    if (!shown.length) return null;
    const box = el("span", "line-plays");
    for (const t of shown) {
      const a = anchor(t.open.href, "play play-" + t.kind + (t.auto ? " auto" : ""), t.open);
      const from = t.sources.map(nameOf);
      const said = t.said + (from.length ? ", from " + listed(from) : "") +
        (t.count > 1 ? ", " + many(t.count, t.unit || "version") : "");
      a.setAttribute("aria-label", said);
      a.title = said;
      a.dataset.kind = t.kind;
      a.dataset.inst = instOf(s, t);
      a.appendChild(glyph(t.glyph));
      a.appendChild(playWords(t));
      if (t.count > 1) {
        const n = el("span", "n", t.count);
        n.setAttribute("aria-hidden", "true");
        a.appendChild(n);
      }
      const marks = el("span", "marks");
      marks.setAttribute("aria-hidden", "true");
      for (const key of t.sources.slice(0, MARKS_SHOWN)) {
        const mark = sourceMark(key);
        if (!mark) continue;
        mark.removeAttribute("title");
        marks.appendChild(mark);
      }
      if (marks.childNodes.length) a.appendChild(marks);
      box.appendChild(a);
    }
    return box;
  };

  // Which sites have the song (``sites``, song_sites.py, rows.js siteMarks), under its tiles: each site's mark in its
  // colours where it has it, grey where it had nothing, fainter on a dashed edge where it wasn't asked yet. None: null.
  const sitesOf = (sites) => {
    const marks = siteMarks(sites);
    if (!marks.childNodes.length) return null;
    const box = el("div", "card-sites");
    box.append(el("p", "card-label", "On the sites"), marks);
    return box;
  };

  // The song's progressions (``items``: { text, said, go }): chips that find your songs that play each.
  // The song's progressions, a chip each: four of them, the rest one press away ("+2"); a long string of numerals is
  // cut short in its chip (rows.css, ``prog-text``), the whole of it in its tooltip and for a screen reader.
  const PROGS_SHOWN = 4;
  const progressions = (items) => {
    const found = listOf(items).filter((p) => p && p.text);
    if (!found.length) return null;
    const box = el("div", "progressions");
    const label = el("p", "card-label", "Progressions");
    label.title = "Find songs that play one";
    box.appendChild(label);
    const row = el("div", "progs");
    const chips = found.map((p) => {
      const go = el("button", "prog");
      go.type = "button";
      go.append(glyph("search"), el("span", "prog-text", String(p.text)));
      go.title = String(p.said || p.text);
      go.setAttribute("aria-label", String(p.said || p.text));
      go.addEventListener("click", p.go);
      row.appendChild(go);
      return go;
    });
    const rest = chips.slice(PROGS_SHOWN);
    if (rest.length) {
      for (const c of rest) c.hidden = true;
      const more = el("button", "progs-more", "+" + rest.length);
      more.type = "button";
      more.setAttribute("aria-label", "Show " + rest.length + " more");
      more.addEventListener("click", () => {
        for (const c of rest) c.hidden = false;
        more.remove();
        rest[0].focus();
      });
      row.appendChild(more);
    }
    box.appendChild(row);
    return box;
  };
  // Where else to find it (``groups``: { heading, links }, those with links alone): links that leave caracole.
  const findElsewhere = (groups) => {
    const shown = listOf(groups).filter((g) => g && listOf(g.links).some((x) => x && x.href));
    if (!shown.length) return null;
    const box = el("div", "find-elsewhere");
    box.appendChild(el("p", "card-label", "Elsewhere"));
    for (const g of shown) {
      const group = el("div", "row-group");
      group.appendChild(el("p", "subhead", String(g.heading)));
      const line = el("div", "actions");
      for (const x of listOf(g.links).filter((y) => y && y.href)) line.appendChild(link(x, "btn small", true));
      group.appendChild(line);
      box.appendChild(group);
    }
    return box;
  };
  // The card's foot: what changes the song (``actions``, then ``book``, Add to a songbook…), and at its far end a "⋯"
  // that opens ``info``, info.json, a quiet download, and ``remove``, Remove, alone: neither is what you came to do.
  // Escape, or a press anywhere else, closes it; on a touch screen it is a step of the browser's history, so Back
  // does too (caracoleMenus).
  const foot = (s, parts) => {
    const p = parts || {};
    const box = el("div", "foot");
    for (const node of listOf(p.actions)) if (node) box.appendChild(node);
    if (p.book) box.appendChild(p.book);
    const behind = [];
    if (p.info && p.info.href) {
      const info = downloadLink(p.info, "info.json", String(s.title) + "'s entry, info.json");
      info.replaceChild(glyph("info"), info.firstChild);
      info.classList.add("info-file");
      behind.push(info);
    }
    if (p.remove) behind.push(p.remove);
    if (behind.length) {
      const more = el("details", "foot-more");
      const summary = el("summary", "btn small foot-more-btn");
      const said = "More: " + String(s.title);
      summary.setAttribute("aria-label", said);
      summary.title = said;
      const dots = el("span", null, "⋯");
      dots.setAttribute("aria-hidden", "true");
      summary.appendChild(dots);
      const menu = el("div", "foot-menu");
      for (const node of behind) menu.appendChild(node);
      more.append(summary, menu);
      more.addEventListener("toggle", () => {
        if (!more.open) {
          caracoleMenus.closed(more);
          return;
        }
        caracoleMenus.opened(more);
        const away = (e) => { if (!more.contains(e.target)) more.open = false; };
        document.addEventListener("click", away, true);
        more.addEventListener("toggle", () => document.removeEventListener("click", away, true), { once: true });
      });
      menu.addEventListener("click", (e) => {  // what it was opened for is chosen: it goes
        if (e.target.closest("button, a")) more.open = false;
      });
      more.addEventListener("keydown", (e) => {
        if (e.key !== "Escape" || !more.open) return;
        e.stopPropagation();
        more.open = false;
        summary.focus();
      });
      box.appendChild(more);
    }
    return box.childNodes.length ? box : null;
  };
  return { plays, tiles, sites: sitesOf, progressions, findElsewhere, foot };
};
