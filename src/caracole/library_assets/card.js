// A song of yours opened on index.html, which card.css draws as a card under its line (library.js lineFor puts these
// parts in its panel): what you play from it as tiles, each source's versions of each as chips that open a drawer,
// its progressions, the links that find it elsewhere, and its foot. Drawn from the song's data alone, with
// createElement, createElementNS and textContent: opening a chip or a drawer asks nothing of anyone.
// ``icons``: the data's sources (icons.py); ``rows``: caracoleRows', whose marks, glyphs and links it shares.
const caracoleCard = (icons, rows) => {
  "use strict";
  const own = Object.prototype.hasOwnProperty;
  const ICONS = icons && typeof icons === "object" ? icons : {};
  const { glyph, sourceMark, safeHref, link, many } = rows;
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
    const said = coverage >= 0.995 ? "Every line of the lyrics" : percent(coverage) + " of the lyrics";
    return complete === true ? el("b", null, said) : said;
  };
  const stars = (v) => (typeof v.rating === "number" ? v.rating.toFixed(2) + "★" : "");

  // --- the files, by what they are -----------------------------------------------------------------------------
  const SHEET_FILES = [["sheet.pdf", "PDF"], ["sheet.txt", "Text"], ["sheet.cho", "ChordPro"]];
  const AUTO_FILES = [["sheet (auto).pdf", "PDF"], ["sheet (auto).txt", "Text"], ["sheet (auto).cho", "ChordPro"]];
  const HUMAN = /^sheet[.](html|pdf|txt|cho)$/;
  const AUTO = /^sheet [(]auto[)][.](html|pdf|txt|cho)$/;
  const GUITAR = /^guitar-\d+[.]([A-Za-z0-9]+)$/;
  const HARMONICA = /^harmonica-\d+[.]txt$/;
  const SCORE = /^score-\d+[.]([a-z]+)$/;
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

  // --- the drawer: one source's versions of what a tile holds, under the row of tiles that holds its tile -------
  // Its head (the source's mark, what it lists, what it counts, and a ✕), then a row a version: each part of
  // ``rowsOf`` a Node, or a { ver, stars, note, actions, cls } it draws.
  const drawerHead = (drawer, source, what, said, extra) => {
    const head = el("div", "drawer-head");
    const mark = sourceMark(source);
    if (mark) head.appendChild(mark);
    const title = el("h4", "drawer-what", what);
    title.id = idFor("drawer-what");
    drawer.setAttribute("aria-labelledby", title.id);
    head.appendChild(title);
    if (said) head.appendChild(el("span", "drawer-said", said));
    for (const node of listOf(extra)) if (node) head.appendChild(node);
    return head;
  };
  const versionRow = (r) => {
    const row = el("li", "vrow" + (r.cls ? " " + r.cls : ""));
    row.appendChild(el("span", "ver", r.ver));
    const rated = el("span", "stars");
    if (r.stars) rated.appendChild(el("b", null, r.stars));
    if (r.votes) rated.appendChild(document.createTextNode((r.stars ? " · " : "") + r.votes));
    row.appendChild(rated);
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

  // Ultimate Guitar's versions of the sheet (the data's ``versions``): the kept ones in rank order, the one in use,
  // and the rest counted, with what fetches them (``acts``).
  const ugDrawer = (s, drawer, acts) => {
    const v = s.versions;
    const list = listOf(v.list).filter((x) => x && typeof x === "object");
    const title = String(s.title);
    const ukulele = listOf(s.instruments).indexOf("ukulele") >= 0;
    const extra = [];
    if (v.pinned && acts.clear) extra.push(acts.clear());
    drawer.appendChild(drawerHead(drawer, "ug", "Ultimate Guitar · " + (ukulele ? "ukulele chords" : "chord sheets"),
      many(v.total, "version") + " on the site · " + list.length + " kept in your library", extra));
    const ol = el("ol", "vrows");
    for (const x of list) {
      const ver = "Ver " + (Number(x.number) || "?");
      const share = lyricsShare(x.complete, x.coverage);
      const note = [];
      if (x.gone) note.push("gone from Ultimate Guitar");
      if (share) note.push(share);
      if (x.note) note.push(String(x.note));
      if (x.chosen) note.push(v.pinned ? "your choice" : "caracole's pick");
      const actions = [];
      if (x.chosen) actions.push(inUse());
      else if (!x.gone && acts.choose) actions.push(acts.choose(x, ver));
      actions.push(openLink(x.href, "Open " + ver + " of " + title));
      ol.appendChild(versionRow({ ver, stars: stars(x),
        votes: typeof x.votes === "number" ? many(x.votes, "vote") : "", note, actions,
        cls: (x.chosen ? "cur" : "") + (x.gone ? " gone" : "") }));
    }
    drawer.appendChild(ol);
    const rest = Number(v.rest) || 0;
    if (rest > 0) {
      const more = el("div", "drawer-rest");
      more.appendChild(el("span", "rest-said", rest + " more on Ultimate Guitar, not kept"));
      const fetch = acts.keepMore ? acts.keepMore(rest, Number(v.keepMore) || 0) : null;
      if (fetch) {
        more.appendChild(fetch);
      } else if (acts.keepMoreCommand) {
        const said = el("span", "rest-command", "Keep them with ");
        said.appendChild(el("code", null, acts.keepMoreCommand));
        more.appendChild(said);
      }
      drawer.appendChild(more);
    }
  };
  // The LaCuerda sheets caracole met for the song (``lacuerdaVersions``), best first: each its page on LaCuerda, its
  // share of the lyrics, and In use for the sheet, else what keeps it (``acts.useLaCuerda``). A UG version you chose
  // (a [pin]) outranks a LaCuerda pick: while one does, the drawer says so, with what takes it out, and keeps none.
  const lacuerdaDrawer = (s, drawer, acts) => {
    const met = listOf(s.lacuerdaVersions).filter((x) => x && typeof x === "object");
    const title = String(s.title);
    const pinned = Boolean(s.versions && s.versions.pinned) && Boolean(acts.useLaCuerda);
    const extra = [];
    if (pinned) {
      extra.push(el("p", "pin-note", "Your choice on Ultimate Guitar is in use: Back to caracole's pick first."));
      if (acts.clear) extra.push(acts.clear());
    }
    drawer.appendChild(drawerHead(drawer, "lacuerda", "LaCuerda · chord sheets", many(met.length, "version") +
      " caracole met", extra));
    const ol = el("ol", "vrows");
    met.forEach((x, n) => {
      const ver = "Version " + (n + 1);
      const actions = [];
      if (x.sheet) actions.push(inUse());
      else if (acts.useLaCuerda && !pinned) actions.push(acts.useLaCuerda(x, ver));
      actions.push(openLink(x.href, ver + " of " + title + " on LaCuerda, in a new tab", { external: true }));
      ol.appendChild(versionRow({ ver, note: [lyricsShare(null, x.coverage) || "not scored"], actions,
        cls: x.sheet ? "cur" : "" }));
    });
    drawer.appendChild(ol);
  };
  // The auto sheet beside a human one (``autoSheet``): its viewer, and its files.
  const autoDrawer = (s, drawer) => {
    const a = s.autoSheet;
    const title = String(s.title);
    drawer.appendChild(drawerHead(drawer, "auto", "Auto sheet · from the recording", "made by caracole from the audio"));
    const ol = el("ol", "vrows");
    const downloads = listOf(a.files).filter((f) => f && f.href)
      .map((f) => downloadLink(f, String(f.label), "Download the auto sheet's " + String(f.label) + " of " + title));
    ol.appendChild(versionRow({ ver: "Auto sheet", note: downloads.length ? downloads : [],
      actions: [openLink(a.href, "Open the auto sheet of " + title)] }));
    drawer.appendChild(ol);
  };
  // One source's files of a tile (``group``): a row each, its label, Open where the page shows it, and Download.
  const filesDrawer = (s, drawer, t, group) => {
    const title = String(s.title);
    drawer.appendChild(drawerHead(drawer, group.source, nameOf(group.source) + " · " + t.plural,
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
    drawer.appendChild(ol);
  };

  // --- the tiles ----------------------------------------------------------------------------------------------
  // A tile: its body opens what it holds (``open``, ``said`` its name for a screen reader), its subtitle says which
  // (``from``); its row of chips, one a source (``chips``: { source, count, unit, fixed, fill(drawer) }, after its
  // ``lead``); its formats as downloads (``downloads``). More than one version: a small stack.
  const tileOf = (t, card) => {
    const box = el("div", "tile tile-" + t.kind + (t.primary ? " primary" : "") + (t.auto ? " auto" : ""));
    const chips = listOf(t.chips);
    if (chips.reduce((n, c) => n + (Number(c.count) || 0), 0) > 1) box.classList.add("stack");
    const open = anchor(t.open.href, "tile-open", t.open);
    open.setAttribute("aria-label", t.said);
    const ico = el("span", "tile-ico");
    ico.appendChild(glyph(t.glyph));
    const words = el("span", "tile-words");
    words.appendChild(el("span", "tile-name", t.name));
    if (t.from) {
      const from = words.appendChild(el("span", "tile-from", t.from));
      from.id = idFor("from");
      open.setAttribute("aria-describedby", from.id);
    }
    const go = el("span", "tile-go");
    go.appendChild(glyph(t.open.download !== undefined ? "download" : "open"));
    open.append(ico, words, go);
    box.appendChild(open);
    if (chips.length) {
      const row = el("div", "tile-versions");
      if (chips.length === 1 && chips[0].fixed) {
        const c = chips[0];
        row.appendChild(el("span", "lead", "From"));
        const one = el("span", "vchip one");
        const mark = sourceMark(c.source);
        if (mark) one.appendChild(mark);
        one.appendChild(el("span", "vchip-name", nameOf(c.source)));
        row.appendChild(one);
      } else {
        row.appendChild(el("span", "lead", t.lead));
        for (const c of chips) row.appendChild(card.chip(box, c));
      }
      box.appendChild(row);
    }
    const downloads = listOf(t.downloads);
    if (downloads.length) {
      const strip = el("div", "tile-downloads");
      for (const d of downloads) strip.appendChild(d);
      box.appendChild(strip);
    }
    return box;
  };

  // What a song of yours holds, a tile each, in this order: its sheet, its Guitar Pro file (else its text tab), its
  // harmonica tab, its lyrics and a score you filed; and the drawer their chips open, one at a time. ``opts``:
  // ``guitar``, caracole serve shows Guitar Pro files (alphaTab); ``acts``, what a drawer's versions do (Use this
  // one, Fetch them, Back to caracole's pick, LaCuerda's Use this one: each makes its control; or, from the file,
  // ``keepMoreCommand``, the command that fetches them). ``claimed``, given, gets every file a tile shows.
  const tiles = (s, opts) => {
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
      const from = one ? ["Ver " + (Number(one.number) || "?"), stars(one), "in use"].filter(Boolean).join(" · ")
        : autoOnly || s.source === "auto" || s.source === "youtube" ? "from the recording"
        : s.source ? nameOf(s.source) : "";
      const chips = [];
      if (v && (Number(v.total) > 0 || listOf(v.list).length)) {
        chips.push({ source: "ug", count: Number(v.total) || listOf(v.list).length, unit: "version",
          fixed: Number(v.total) <= 1 && !(Number(v.rest) > 0), fill: (d) => ugDrawer(s, d, acts) });
      }
      const met = listOf(s.lacuerdaVersions);
      if (met.length) {
        chips.push({ source: "lacuerda", count: met.length, unit: "version",
          fixed: met.length === 1 && Boolean(met[0] && met[0].sheet), fill: (d) => lacuerdaDrawer(s, d, acts) });
      }
      if (auto) {
        chips.push({ source: "auto", count: 1, unit: "version", fixed: false, fill: (d) => autoDrawer(s, d) });
      }
      if (!chips.length && s.source) chips.push({ source: String(s.source), count: 1, fixed: true });
      const downloads = (autoOnly ? AUTO_FILES : SHEET_FILES).map(([n, label]) => [named(n), label])
        .filter(([f]) => f).map(([f, label]) => downloadLink(f, label, "Download the " + label + " of " + title));
      for (const f of files.filter((x) => typeof x.version === "string" && x.version)) {
        claim(f);
        downloads.push(downloadLink(f, "PDF · " + f.version, "Download the PDF of " + title + " in " + f.version));
      }
      made.push({ kind: "sheet", glyph: "sheet", name, primary: !autoOnly, auto: autoOnly,
        open: { href: primary.href }, said: "Open the " + name.toLowerCase() + " of " + title, from,
        lead: "Versions", chips, downloads });
    }

    // Guitar Pro files (or a Power Tab file), else a text tab.
    const guitar = files.filter((f) => GUITAR.test(f.name));
    const tab = named("tab.txt");
    const browser = (f) => (o.guitar && typeof f.guitarPage === "string" && f.guitarPage ? { href: f.guitarPage }
      : null);
    if (guitar.length) {
      guitar.forEach(claim);
      claim(tab);
      const first = guitar[0];
      const shown = browser(first);
      const ext = "." + GUITAR.exec(first.name)[1].toLowerCase();
      const downloads = [downloadLink(first, ext, "Download " + plainLabel(first) + " of " + title)];
      if (tab) downloads.push(downloadLink(tab, "Text tab", "Download the text tab of " + title));
      const t = { kind: "guitar", glyph: "guitar", name: "Guitar Pro", plural: "Guitar Pro files", unit: "file",
        open: shown || { href: first.href, download: typeof first.download === "string" ? first.download : "" },
        said: (shown ? "Open the Guitar Pro tab of " : "Download the Guitar Pro file of ") + title,
        from: String(first.name), lead: "Files", downloads,
        opener: (f) => browser(f) };
      t.chips = bySource(guitar).map((g) => ({ source: g.source, count: g.files.length, unit: "file",
        fixed: g.files.length === 1, fill: (d) => filesDrawer(s, d, t, g) }));
      made.push(t);
    } else if (tab) {
      claim(tab);
      made.push({ kind: "guitar", glyph: "guitar", name: "Guitar tab", open: { href: tab.href },
        said: "Open the guitar tab of " + title, from: tab.source ? nameOf(tab.source) : "a text tab", lead: "From",
        chips: tab.source ? [{ source: tab.source, count: 1, fixed: true }] : [],
        downloads: [downloadLink(tab, "Text", "Download the guitar tab of " + title)] });
    }

    // Harmonica tabs.
    const harp = files.filter((f) => HARMONICA.test(f.name));
    if (harp.length) {
      harp.forEach(claim);
      const first = harp[0];
      const t = { kind: "harmonica", glyph: "harmonica", name: "Harmonica tab", plural: "harmonica tabs", unit: "tab",
        open: { href: first.href }, said: "Open the harmonica tab of " + title,
        from: plainLabel(first).replace(/^Harmonica tab/, "Tab"), lead: "Tabs",
        downloads: [downloadLink(first, "Text", "Download " + plainLabel(first) + " of " + title)],
        opener: (f) => ({ href: f.href }) };
      t.chips = bySource(harp).map((g) => ({ source: g.source, count: g.files.length, unit: "tab",
        fixed: g.files.length === 1, fill: (d) => filesDrawer(s, d, t, g) }));
      made.push(t);
    }

    // Lyrics, plain and timed: LRCLIB's.
    const lyrics = LYRICS.map(named).filter(Boolean);
    if (lyrics.length) {
      lyrics.forEach(claim);
      const plain = named("lyrics.txt");
      const timed = named("lyrics.lrc");
      const downloads = [];
      if (plain) downloads.push(downloadLink(plain, "Text", "Download the lyrics of " + title));
      if (timed) downloads.push(downloadLink(timed, "Timed (.lrc)", "Download the timed lyrics of " + title));
      const source = lyrics[0].source;
      made.push({ kind: "lyrics", glyph: "lyrics", name: "Lyrics", open: { href: lyrics[0].href },
        said: "Open the lyrics of " + title, from: timed ? "synced to the recording" : "plain", lead: "From",
        chips: source ? [{ source, count: 1, fixed: true }] : [], downloads });
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
        said: (pdf ? "Open the score of " : "Download the score of ") + title, from: plainLabel(first), lead: "Files",
        downloads: scores.map((f) => downloadLink(f, format(f), "Download " + plainLabel(f) + " of " + title)),
        opener: (f) => (/[.]pdf$/i.test(f.name) ? { href: f.href } : null) };
      t.chips = bySource(scores).map((g) => ({ source: g.source, count: g.files.length, unit: "file",
        fixed: g.files.length === 1, fill: (d) => filesDrawer(s, d, t, g) }));
      made.push(t);
    }

    if (!made.length) return null;
    const box = el("div", "tiles");
    const drawer = el("div", "drawer");  // a region, named by its head; no section, as a line's group has one
    drawer.setAttribute("role", "region");
    drawer.id = idFor("drawer");
    drawer.hidden = true;
    let opened = null;  // the chip whose drawer shows
    const close = (focusBack) => {
      const chip = opened;
      opened = null;
      drawer.hidden = true;
      drawer.replaceChildren();
      if (chip) {
        chip.setAttribute("aria-expanded", "false");
        if (focusBack) chip.focus();
      }
    };
    const card = {
      chip: (tileBox, c) => {
        const chip = el("button", "vchip");
        chip.type = "button";
        const said = nameOf(c.source) + ": " + many(c.count, c.unit || "version");
        chip.title = said;
        chip.setAttribute("aria-label", said);
        chip.setAttribute("aria-expanded", "false");
        chip.setAttribute("aria-controls", drawer.id);
        chip.dataset.source = c.source;
        const mark = sourceMark(c.source);
        if (mark) {
          mark.removeAttribute("title");
          chip.appendChild(mark);
        }
        chip.appendChild(el("span", "n", c.count));
        chip.appendChild(glyph("chevron"));
        chip.addEventListener("click", () => {
          const was = opened === chip;
          close(false);
          if (was) return;
          const shut = el("button", "drawer-close");
          shut.type = "button";
          shut.title = "Close";
          shut.setAttribute("aria-label", "Close " + said);
          shut.appendChild(glyph("close"));
          shut.addEventListener("click", () => close(true));
          c.fill(drawer);
          const head = drawer.querySelector(".drawer-head");
          if (head) head.appendChild(shut);
          opened = chip;
          chip.setAttribute("aria-expanded", "true");
          drawer.hidden = false;
          place(drawer, tileBox);
        });
        return chip;
      },
    };
    drawer.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      close(true);
    });
    for (const t of made) box.appendChild(tileOf(t, card));
    box.appendChild(drawer);
    drawers.add(box);
    return box;
  };
  // The drawer under the row of tiles that holds its tile (on a phone, one tile a row, right under it), its pointer
  // over the tile: placed when it opens, and again when the window's width moves the tiles.
  const drawers = new Set();
  const place = (drawer, tileBox) => {
    const box = drawer.parentNode;
    if (!box || !tileBox.isConnected) return;
    drawer.hidden = true;  // out of the rows while they are measured
    const top = Math.round(tileBox.getBoundingClientRect().top);
    let last = tileBox;
    for (const t of box.querySelectorAll(":scope > .tile")) {
      if (Math.round(t.getBoundingClientRect().top) === top) last = t;
    }
    last.after(drawer);
    drawer.hidden = false;
    const at = tileBox.getBoundingClientRect();
    drawer.style.setProperty("--point", Math.round(at.left + at.width / 2 - box.getBoundingClientRect().left) + "px");
    drawer.dataset.tile = String(Array.from(box.querySelectorAll(":scope > .tile")).indexOf(tileBox));
  };
  window.addEventListener("resize", () => {
    for (const box of Array.from(drawers)) {
      if (!box.isConnected) {
        drawers.delete(box);
        continue;
      }
      const drawer = box.querySelector(":scope > .drawer");
      const tileBox = drawer && !drawer.hidden ? box.querySelectorAll(":scope > .tile")[Number(drawer.dataset.tile)] : null;
      if (tileBox) place(drawer, tileBox);
    }
  });

  // The song's progressions (``items``: { text, said, go }): chips that find your songs that play each.
  const progressions = (items) => {
    const found = listOf(items).filter((p) => p && p.text);
    if (!found.length) return null;
    const box = el("div", "progressions");
    const label = el("p", "card-label", "Progressions");
    label.appendChild(el("em", null, "find your songs that play one"));
    box.appendChild(label);
    const row = el("div", "progs");
    for (const p of found) {
      const go = withGlyph(el("button", "prog"), "search", String(p.text));
      go.type = "button";
      go.title = String(p.said || p.text);
      go.setAttribute("aria-label", String(p.said || p.text));
      go.addEventListener("click", p.go);
      row.appendChild(go);
    }
    box.appendChild(row);
    return box;
  };
  // Where else to find it (``groups``: { heading, links }, those with links alone): links that leave caracole.
  const findElsewhere = (groups) => {
    const shown = listOf(groups).filter((g) => g && listOf(g.links).some((x) => x && x.href));
    if (!shown.length) return null;
    const box = el("div", "find-elsewhere");
    box.appendChild(el("p", "card-label", "Find it elsewhere"));
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
  // The card's foot: what changes the song (``actions``, then ``book``, Add to a songbook…), and at its far end
  // ``info``, info.json, a quiet download, and ``remove``, Remove, alone.
  const foot = (s, parts) => {
    const p = parts || {};
    const box = el("div", "foot");
    for (const node of listOf(p.actions)) if (node) box.appendChild(node);
    if (p.book) box.appendChild(p.book);
    let pushed = false;
    if (p.info && p.info.href) {
      const info = downloadLink(p.info, "info.json", "Download what caracole knows of " + String(s.title) +
        ", info.json");
      info.replaceChild(glyph("info"), info.firstChild);
      info.classList.add("info-file", "push");
      pushed = true;
      box.appendChild(info);
    }
    if (p.remove) {
      if (!pushed) p.remove.classList.add("push");
      box.appendChild(p.remove);
    }
    return box.childNodes.length ? box : null;
  };
  return { tiles, progressions, findElsewhere, foot };
};
