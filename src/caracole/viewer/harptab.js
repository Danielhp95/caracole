(() => {
  "use strict";
  // A harmonica tab's page (harptab_page.py): the harp chosen (−/+ in the bar), each hole's note on it in Notes (♪),
  // a hole tapped or a line's ▶ sounding it with strum.js's reed voice (window.caracoleSound, inlined before this
  // script), the text size (Aa) and scrolling by itself, as the sheet viewer has them. It computes no music theory:
  // each hole's note is looked up in the page's data, which Python made (harptab_page.py says what it holds):
  //
  //   data.holes[harp].blow[hole - 1][bend], .draw[…][bend]   the note a hole sounds, bent or not (null past its bends)
  //   data.holes[harp].over[hole - 1]                         [the breath its overblow takes, its note]
  //   data.names[harp][pitch class]                           the note's name, as the harp's key spells it
  //   data.groups[i][2].fx                                    a group's effects ("wah"), drawn on it as labels
  //
  // What a row's notation couldn't read ("$") is the page's text beside the groups, never redrawn: drawGroup draws
  // a group's holes and effects alone.
  // Where the page is (the harp, Notes, the text size, the scroll's speed) is kept in the address (#harp=A&notes=1)
  // and, where the browser keeps anything, for this page. Every element is made with createElement and textContent;
  // nothing is loaded, and nothing sounds but on a tap.
  //
  // From 1200 px, the overlay on the left (overlay.js, inlined before this script): Harmonica first, its harp this
  // page's both ways (a harp tapped on its circle is the one the page plays; −/+ move the circle's choice), and
  // Guitar, the song's sheet's necks; data.overlay holds what it draws, as overlay.js's rail takes it. Whether it
  // shows is the screen's choice, as the sheet viewer's rail: kept for every page (overlay.js's NECKS) and in the
  // address while hidden (necks=0). Narrower, the phone's sheet, as the viewer's: the bar's neck slides the overlay up
  // from the bar over half the screen, its handle to the whole screen and back, ✕, Escape or the neck again closing it.
  //
  // Under the artist, the song's version line and the list it opens, as on its sheet's viewer (kinds.js, inlined before
  // this script, attached below with this page's layers): "Harmonica · Tab 1 of 2", the song's kinds, and UG's
  // versions, its other tabs and files a tap away, with the screen's choices (as ‹ Chord sheet takes them).
  const $ = (id) => document.getElementById(id);
  const doc = document.documentElement;
  let data;
  try {
    data = JSON.parse($("harp-data").textContent);
  } catch (err) {
    doc.dataset.error = "data";
    return;
  }
  const sound = window.caracoleSound && window.caracoleSound.available ? window.caracoleSound : null;
  const FS = { min: 13, max: 30, step: 2, start: 18 };
  const SPEED = { min: 1, max: 30, start: 6, px: 2 };
  const read = Array.isArray(data.groups) && Array.isArray(data.rows);  // a tab shown as written has neither
  const groups = read ? data.groups : [];
  const rows = read ? data.rows : [];
  const keys = Array.isArray(data.harpKeys) ? data.harpKeys : [];
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // --- where the page is ---------------------------------------------------------------------------------------
  const harpOf = (v) => (typeof v === "string" && keys.indexOf(v) >= 0 ? keys.indexOf(v) : null);
  const sizeOf = (v) => (Number(v) >= FS.min && Number(v) <= FS.max ? Math.round(Number(v)) : null);
  const speedOf = (v) => (Number(v) >= SPEED.min && Number(v) <= SPEED.max ? Math.round(Number(v)) : null);
  const start = Number.isInteger(data.start) && data.start >= 0 && data.start < 12 ? data.start : 0;
  const state = { harp: start, notes: false, fs: FS.start, speed: SPEED.start, necks: true, kn: "scale" };
  const store = "caracole-harmonica:" + location.pathname;
  try {
    const saved = JSON.parse(localStorage.getItem(store) || "null");
    if (saved && typeof saved === "object") {
      if (harpOf(saved.harp) !== null) state.harp = harpOf(saved.harp);
      state.notes = saved.notes === true;
      if (sizeOf(saved.fs) !== null) state.fs = sizeOf(saved.fs);
      if (speedOf(saved.speed) !== null) state.speed = speedOf(saved.speed);
    }
  } catch (err) { /* no storage: the address keeps it */ }
  const hash = new URLSearchParams(location.hash.slice(1));
  if (harpOf(hash.get("harp")) !== null) state.harp = harpOf(hash.get("harp"));
  if (hash.has("notes")) state.notes = hash.get("notes") === "1";
  if (sizeOf(hash.get("fs")) !== null) state.fs = sizeOf(hash.get("fs"));
  if (speedOf(hash.get("speed")) !== null) state.speed = speedOf(hash.get("speed"));
  // A choice kept for every page, read as the sheet viewer reads it (viewer.js choiceOf): the one a link names, else
  // the browser's; on a page come back to (a reload, Back, a tab restored), the browser's over an address written before.
  const returning = (() => {
    try {
      const entry = performance.getEntriesByType("navigation")[0];
      return Boolean(entry) && (entry.type === "reload" || entry.type === "back_forward");
    } catch (err) {
      return false;
    }
  })();
  const choiceOf = (name, named) => {
    let kept = null;
    try {
      kept = localStorage.getItem(name);
    } catch (err) { /* no storage: the address says */ }
    return named !== null && (!returning || kept === null) ? named : kept;
  };
  // The song's names (its title, its artist's, the page's title) in the characters the sheet viewer shows the Chinese
  // in, Simplified at first: its choice, kept for every page (localStorage), else trad=1 in the address; this page has
  // no row of its own. harptab_page.py's song-names block converts each by its text as written (data-zh).
  try {
    const names = JSON.parse($("song-names") ? $("song-names").textContent : "null");
    const trad = choiceOf("caracole-viewer-hanzi", hash.get("trad") === "1" ? "traditional" : null) === "traditional";
    const table = names && typeof names === "object" ? names[trad ? "traditional" : "simplified"] : null;
    for (const el of document.querySelectorAll("[data-zh]")) {
      const written = el.getAttribute("data-zh");
      if (table && typeof table === "object" && Object.prototype.hasOwnProperty.call(table, written)
        && typeof table[written] === "string") el.textContent = table[written];
    }
  } catch (err) { /* none: as written */ }
  const kit = window.caracoleOverlay || null;
  const necksNamed = hash.get("necks") === "0" ? "hidden" : null;
  if ((kit ? choiceOf(kit.NECKS, necksNamed) : necksNamed) === "hidden") state.necks = false;
  const keepNecks = () => {
    try {
      if (kit) localStorage.setItem(kit.NECKS, state.necks ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // ‹ Chord sheet takes the screen's choices back with it (the rail hidden, and as they came in the address, a sheet's
  // viewer's link here having taken them on: the pinyin, the Chinese characters, the instrument), so that where the
  // browser keeps nothing (caracole serve's sandbox) they go both ways. ‹ Library takes none.
  const screenKit = window.caracoleScreen;  // screen.js, inlined in the head: the theme, the keys, the screen on
  const sheetLink = document.querySelector("a.back[data-sheet]");
  const sheetPage = sheetLink ? sheetLink.getAttribute("href") : "";
  // What a link to another page of the song takes along: "#necks=0&py=1", or "".
  const screenChoices = () => {
    const now = new URLSearchParams(location.hash.slice(1)), params = new URLSearchParams();
    if (!state.necks) params.set("necks", "0");
    for (const name of ["py", "trad", "inst"]) if (now.has(name)) params.set(name, now.get(name));
    screenKit.carry(params);
    const fragment = params.toString();
    return fragment ? "#" + fragment : "";
  };
  function backToSheet() {
    if (sheetLink) sheetLink.setAttribute("href", sheetPage + screenChoices());
  }
  const save = () => {
    try {
      localStorage.setItem(store, JSON.stringify({ harp: keys[state.harp], notes: state.notes, fs: state.fs,
        speed: state.speed }));
    } catch (err) { /* private mode, or a server's sandbox */ }
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const keep = (name, value, kept) => (kept ? params.set(name, String(value)) : params.delete(name));
      keep("harp", keys[state.harp], state.harp !== start);
      keep("notes", "1", state.notes);
      keep("fs", state.fs, state.fs !== FS.start);
      keep("speed", state.speed, state.speed !== SPEED.start);
      keep("necks", "0", !state.necks);
      screenKit.carry(params);
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(history.state, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
    backToSheet();
    if (kinds) kinds.links();  // the list's links to the song's other pages, with the choices now
  };

  // --- a hole's note on the harp chosen --------------------------------------------------------------------------
  // A hole as the data writes it: [hole, "b" or "d", bend, overblown]; its MIDI note, or null where the harp can't.
  const noteOf = (h) => {
    const table = data.holes && data.holes[state.harp];
    const i = Number(h[0]) - 1, breath = h[1] === "d" ? "draw" : "blow", bend = Number(h[2]) || 0;
    if (!table || !(i >= 0 && i < 10)) return null;
    if (h[3]) {
      const over = table.over[i];
      return Array.isArray(over) && over[0] === breath ? over[1] : null;
    }
    const list = table[breath][i];
    return Array.isArray(list) && bend < list.length ? list[bend] : null;
  };
  const nameOf = (n) => data.names[state.harp][((n % 12) + 12) % 12];
  const notesOf = (i) => (groups[i] ? groups[i][1].map(noteOf).filter((n) => n !== null) : []);
  const BRACKETS = { chord: ["(", ")"], shake: ["{", "}"], split: ["[", "]"] };
  const holeEls = Array.from(document.querySelectorAll("#sheet .h[data-i]"));
  // A group drawn again: its holes, or with Notes their notes on the harp chosen ("?" for one it can't play), then
  // its effects, each a small label.
  const effectsOf = (g) => (g[2] && Array.isArray(g[2].fx) ? g[2].fx.filter((e) => typeof e === "string") : []);
  const drawGroup = (node) => {
    const g = groups[Number(node.dataset.i)];
    if (!g) return;
    const [open, close] = BRACKETS[g[0]] || ["", ""];
    node.textContent = "";
    if (open) node.append(open);
    const said = [];
    g[1].forEach((h, k) => {
      if (k) node.append(" ");
      const span = el("span", h[1] === "d" ? "d" : "b");
      const n = noteOf(h);
      if (state.notes) {
        span.textContent = n === null ? "?" : nameOf(n);
        if (n !== null) span.appendChild(el("small", "", String(Math.floor(n / 12) - 1)));
      } else {
        if (h[1] === "d") span.appendChild(el("span", "sg", "−"));
        span.append(String(h[0]));
        if (h[2]) span.appendChild(el("span", "bd", "′".repeat(Number(h[2]))));
        if (h[3]) span.appendChild(el("span", "bd", "°"));
      }
      node.appendChild(span);
      said.push((h[1] === "d" ? "draw " : "blow ") + h[0] + (h[2] ? " bent " + h[2] : "") + (h[3] ? " overblown" : "")
        + ", " + (n === null ? "not on this harp" : nameOf(n) + (Math.floor(n / 12) - 1)));
    });
    if (close) node.append(close);
    const effects = effectsOf(g);
    effects.forEach((e) => node.appendChild(el("small", "fx", e)));
    node.setAttribute("aria-label", said.join(" and ") + effects.map((e) => ", " + e).join(""));
    node.classList.toggle("off", g[1].every((h) => noteOf(h) === null));
  };
  const drawHarp = () => {
    if (!$("harp-name")) return;
    $("harp-name").textContent = keys[state.harp] + " harp";
    const why = data.why && typeof data.why[String(state.harp)] === "string" ? data.why[String(state.harp)] : "";
    const where = Array.isArray(data.positions) ? data.positions[state.harp] || "" : "";
    $("harp-why").textContent = [why, where.split(",")[0]].filter(Boolean).join(" · ");
    $("notes").setAttribute("aria-pressed", state.notes ? "true" : "false");
    fitHarp();
  };
  // The harp's name a little smaller where the bar is too narrow for it (320 px, the neck beside it), down to seven
  // tenths of its size, then cut short. Measured to the fraction of a pixel, as the viewer's key is: scrollWidth rounds.
  const fitHarp = () => {
    const name = $("harp-name");
    if (!name || !name.getClientRects().length) return;
    name.style.fontSize = "";
    const text = document.createRange();
    text.selectNodeContents(name);
    const tooWide = () => text.getBoundingClientRect().width > name.getBoundingClientRect().width;
    const full = parseFloat(getComputedStyle(name).fontSize);
    for (let size = full - 0.5; size >= full * 0.7 && tooWide(); size -= 0.5) name.style.fontSize = size + "px";
  };
  window.addEventListener("resize", () => fitHarp());
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitHarp(), () => {});
  const render = () => {
    holeEls.forEach(drawGroup);
    drawHarp();
    doc.style.setProperty("--fs", state.fs + "px");
    $("fs-now").textContent = state.fs + " px";
    for (const choice of ["auto", "light", "dark"]) {
      $("theme-" + choice).setAttribute("aria-pressed", screenKit.theme() === choice ? "true" : "false");
    }
    $("smaller").setAttribute("aria-disabled", state.fs <= FS.min ? "true" : "false");
    $("bigger").setAttribute("aria-disabled", state.fs >= FS.max ? "true" : "false");
    $("pill-speed").textContent = String(state.speed);
    drawRail();
  };

  // --- the overlay: Harmonica and Guitar, on a wide screen ------------------------------------------------------
  const over = data.overlay && typeof data.overlay === "object" && data.overlay.harp ? data.overlay : null;
  const aside = $("necks"), necksButton = $("necks-toggle"), sheetButton = $("necks-open");
  const vList = $("version-list"), verNow = $("ver-now");  // the versions list and its line (kinds.js, below)
  let kinds = null;  // what kinds.js attached: its links() and place()
  const wide = window.matchMedia("(min-width: 1200px)");
  // From 1200 px the bar is a toolbar under the tab's title, as the viewer's (layers.js's toolbar, viewer.css), back at
  // the foot below it.
  const bar = $("bar");
  const toolbar = window.caracoleLayers ? window.caracoleLayers.toolbar(bar, () => document
    .querySelector(".page > header.head")) : { wide: window.matchMedia("not all"), place() {}, edge() {},
    room: () => ({ top: 0, bottom: window.innerHeight }) };
  let sheetAt = null;  // the phone's sheet: "half", "full", or null while it is closed
  const mod12 = (n) => ((n % 12) + 12) % 12;
  const picks = {};  // a shape picked on a chord's neck: the page's alone
  const guitarTab = () => {
    const g = over.guitar;
    if (!g) return null;
    const neck = g.key ? Object.assign({}, g.key, { box: state.kn === "penta", onSwitch: (which) => {
      state.kn = which;
      drawRail();
    } }) : null;
    return Object.assign({}, g, { key: neck, chords: g.chords.map((c) => Object.assign({}, c, { chosen: picks[c.name] || 0 })) });
  };
  const harmonicaTab = () => {
    const h = over.harp;
    if (!h.key) {
      return { key: null, none: h.none, plain: { name: keys[state.harp] + " harp", tonic: state.harp,
        names: data.names[state.harp], holes: h.holes } };
    }
    return Object.assign({}, h, { harpKeys: keys, chosen: mod12(state.harp - h.tonic) });
  };
  const rail = kit && aside && over ? kit.rail(aside, {
    first: "harmonica",
    guitar: guitarTab,
    harmonica: harmonicaTab,
    pick: (name, p) => {
      picks[name] = p;
      drawRail();
    },
    chooseHarp: (offset) => {
      stop();
      state.harp = mod12(over.harp.tonic + offset);
      render();
      save();
    },
    hide: () => {
      showRail(false);
      necksButton.focus();  // the focus where the rail comes back from, not lost with it
    },
    sheet: () => (wide.matches ? null : sheetAt),
    grow: () => {
      sheetAt = sheetAt === "full" ? "half" : "full";
      if (sheetAt === "full") pauseScroll();  // the tab out of sight
      drawRail();
    },
    close: () => closeLayer("sheet"),
  }) : null;
  function drawRail() {
    const full = Boolean(doc.dataset.full);  // full screen: the tab the whole width, no rail and no sheet
    const can = Boolean(rail) && wide.matches, on = can && state.necks && !full;
    const phone = Boolean(rail) && !wide.matches && sheetAt !== null && !full;
    necksButton.hidden = !can;
    necksButton.setAttribute("aria-pressed", on ? "true" : "false");
    sheetButton.hidden = !rail || wide.matches;
    sheetButton.setAttribute("aria-expanded", phone ? "true" : "false");
    aside.hidden = !on && !phone;
    aside.classList.toggle("top", phone && topDocked() !== "list");  // shown below 900 px while on top (viewer.css)
    if (on) doc.dataset.necks = "1";  // the tab and the bar move over for it
    else delete doc.dataset.necks;
    if (on || phone) rail.draw();
    else if (rail) rail.empty();
    else aside.textContent = "";
    dock();
    if (kinds) kinds.place();  // the list's popover clear of the rail as it comes or goes
  }
  // The one docked on the bar, as the viewer's settings are: below 900 px the sheet or the versions list, whichever is
  // on top; up to 1199 px the sheet (from 900 px the list is a popover under its line). The page leaves room under the
  // tab for it, so its end comes up above it, and the pill rides above it (--dock, viewer.css), or over the foot of the
  // whole-screen sheet.
  function docked() {
    if (!apart.matches) {
      const top = topDocked();
      return top === "list" ? vList : top === "sheet" ? aside : null;
    }
    return sheetAt !== null && !wide.matches ? aside : null;
  }
  function dock() {
    const there = docked();
    if (there) {
      doc.dataset.dock = there === vList ? "version-list" : sheetAt === "full" ? "necks-full" : "necks";
      doc.style.setProperty("--dock", there.offsetHeight + "px");
    } else if (doc.dataset.dock) {
      delete doc.dataset.dock;
      doc.style.removeProperty("--dock");
    }
  }
  // Open, the focus on its tab shown; closed, back on the neck when it was in the sheet. The bar stays under it.
  const openSheet = () => {
    if (sheetAt === null) sheetAt = "half";
    pauseScroll();
    bar.classList.remove("away");
    drawRail();
    const to = rail.landing();
    if (to) to.focus({ preventScroll: true });
  };
  function closeSheet(refocus = true) {
    if (sheetAt === null) return;
    const active = document.activeElement;
    const mine = refocus && (!active || active === document.body || aside.contains(active));
    sheetAt = null;
    drawRail();
    if (mine) sheetButton.focus({ preventScroll: true });
  }
  sheetButton.addEventListener("click", () => (sheetAt === null ? openLayer("sheet", sheetButton) : closeLayer("sheet")));
  window.addEventListener("resize", () => {
    dock();
    if (kinds) kinds.place();
    toolbar.edge();
  });
  const showRail = (on) => {
    state.necks = on;
    keepNecks();
    drawRail();
    save();
  };
  necksButton.addEventListener("click", () => showRail(!state.necks));
  // The window narrowed below 1200 px with the keyboard's focus in the rail: it goes to the bar's first control, rather
  // than to nothing. Widened past it with the sheet open: the rail takes its place, on its tab.
  wide.addEventListener("change", () => {
    const had = aside.contains(document.activeElement);
    if (wide.matches) {
      sheetAt = null;
      const at = layers.findIndex((layer) => layer.name === "sheet");
      if (at >= 0) layers.splice(at, 1);
      layerHistory.sync(layers.length);
    }
    drawRail();
    restack();  // the list on top of what docks, if it was under the sheet
    if (had && !aside.contains(document.activeElement)) {
      const first = Array.from($("bar").querySelectorAll("button")).find((b) => b.getClientRects().length > 0);
      if (first) first.focus({ preventScroll: true });
    }
  });

  // --- a hole tapped, a line played ------------------------------------------------------------------------------
  let playing = null, lit = 0;
  const unlight = () => document.querySelectorAll("#sheet .h.on").forEach((n) => n.classList.remove("on"));
  const stop = () => {
    const was = playing;
    playing = null;
    if (was) was.stop();
    clearTimeout(lit);
    unlight();
    document.querySelectorAll('#sheet .rp[aria-pressed="true"]').forEach((b) => b.setAttribute("aria-pressed", "false"));
  };
  const tapHole = (node) => {
    stop();
    const notes = notesOf(Number(node.dataset.i));
    if (!sound || !notes.length || !sound.strum(notes, { voice: "reed" })) return;
    node.classList.add("on");
    lit = setTimeout(unlight, 450);
  };
  const playRow = (button) => {
    const was = button.getAttribute("aria-pressed") === "true";
    stop();
    if (was || !sound) return;
    const list = rows[Number(button.dataset.row)] || [];
    const nodes = list.map((i) => document.querySelector('#sheet .h[data-i="' + i + '"]'));
    const handle = sound.play(list.map((i) => ({ position: notesOf(i), voice: "reed" })), {
      bpm: Number(data.bpm) || 132, beats: 1, every: 1,
      onChord: (k) => {
        unlight();
        if (nodes[k]) nodes[k].classList.add("on");
      },
      onEnd: () => {
        if (playing !== handle) return;
        playing = null;
        unlight();
        button.setAttribute("aria-pressed", "false");
      },
    });
    if (!handle.playing) return;
    playing = handle;
    button.setAttribute("aria-pressed", "true");
  };
  const sheet = $("sheet");
  sheet.addEventListener("click", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    const hole = target && target.closest(".h[data-i]");
    const line = target && target.closest(".rp");
    if (hole) tapHole(hole);
    else if (line) playRow(line);
  });
  sheet.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target instanceof Element && e.target.matches(".h[data-i]")) {
      e.preventDefault();
      tapHole(e.target);
    }
  });
  if (!sound) document.querySelectorAll("#sheet .rp").forEach((b) => { b.hidden = true; });

  // --- the bar: the harp, Notes, Aa -----------------------------------------------------------------------------
  const step = (by) => {
    stop();
    state.harp = (state.harp + by + 12) % 12;
    render();
    save();
  };
  if ($("h-down")) {
    $("h-down").addEventListener("click", () => step(-1));
    $("h-up").addEventListener("click", () => step(1));
    $("notes").addEventListener("click", () => {
      state.notes = !state.notes;
      render();
      save();
    });
  }
  const sizes = $("sizes"), sizeButton = $("size");
  const showSizes = (on) => {
    sizes.hidden = !on;
    sizeButton.setAttribute("aria-expanded", on ? "true" : "false");
  };
  // The layers: what the page opens over its tab (Aa, the overlay's sheet, the versions list, full screen), each one
  // entry of the browser's history while it is open (layers.js, as viewer.js), the last on top. Below 900 px one at a
  // time; Aa gives way to the sheet and the list at every width, full screen to the sheet. A Back that takes k entries
  // off closes the k on top.
  const layers = [];  // {name: "sizes" | "sheet" | "list" | "full", opener}
  const apart = window.matchMedia("(min-width: 900px)");
  // The top of those that dock on the bar on a phone, the sheet and the list: its name, or null.
  const topDocked = () => {
    for (let i = layers.length - 1; i >= 0; i--) {
      if (layers[i].name === "sheet" || layers[i].name === "list") return layers[i].name;
    }
    return null;
  };
  // A layer in sight: open, and on top below 900 px, where one shows at a time (kinds.js's line toggles the list so).
  const inSight = (el) => !el.hidden && (apart.matches || (layers.length > 0 && el === vList
    && layers[layers.length - 1].name === "list"));
  // The list shown or hidden; shown, the tab's scrolling paused and the bar back under it (restack does the rest).
  const showList = (on) => {
    vList.hidden = !on;
    if (!on) return;
    pauseScroll();
    bar.classList.remove("away");
  };
  // After every layer opened or closed: which docked one is on top, the line pressed while the list is open, the dock,
  // and the list placed (a popover from 900 px).
  const restack = () => {
    if (vList) {
      vList.classList.toggle("top", !vList.hidden && topDocked() === "list");
      verNow.setAttribute("aria-expanded", vList.hidden ? "false" : "true");
    }
    const phone = Boolean(rail) && !wide.matches && sheetAt !== null && !doc.dataset.full;  // as drawRail says
    aside.classList.toggle("top", phone && topDocked() !== "list");
    dock();
    if (kinds) kinds.place();
  };
  const layerHistory = window.caracoleLayers ? window.caracoleLayers.history((k) => {
    for (let i = 0; i < k && layers.length; i++) closeLayer(layers[layers.length - 1].name);
    save();
  }) : { sync() {} };
  function openLayer(name, opener) {
    auto.end();  // a short screen's full screen of itself gives way to any layer
    const at = layers.findIndex((layer) => layer.name === name);
    if (at >= 0) layers.splice(at, 1);  // open already: on top again
    for (const layer of layers.slice().reverse()) {
      const givesWay = (name === "sheet" && layer.name !== "list") || (name === "list" && layer.name === "sizes");
      if (!apart.matches || givesWay) closeLayer(layer.name, false);
    }
    layers.push({ name, opener: opener instanceof Element ? opener : null });
    if (name === "sheet") openSheet();
    else if (name === "full") fullScreen(true);
    else if (name === "list") showList(true);
    else showSizes(true);
    restack();
    if (name === "list") $("version-list-title").focus({ preventScroll: true });
    layerHistory.sync(layers.length);
  }
  // ``refocus``: the focus goes back where the layer came from, unless it is somewhere else of yours.
  function closeLayer(name, refocus = true) {
    const at = layers.findIndex((layer) => layer.name === name);
    if (at < 0) return;
    const opener = layers.splice(at, 1)[0].opener;
    if (name === "sheet") closeSheet(refocus);
    else if (name === "list") {
      const active = document.activeElement;
      const mine = refocus && (!active || active === document.body || vList.contains(active));
      showList(false);
      if (mine) (opener && opener.isConnected ? opener : verNow).focus({ preventScroll: true });
    } else {
      if (name === "full") {
        fullScreen(false);
        if (refocus && opener && opener.isConnected) opener.focus({ preventScroll: true });
      } else {
        showSizes(false);
        if (refocus) sizeButton.focus({ preventScroll: true });
      }
    }
    restack();
    layerHistory.sync(layers.length);
  }
  sizeButton.addEventListener("click", () => (sizes.hidden ? openLayer("sizes", sizeButton) : closeLayer("sizes")));
  document.addEventListener("pointerdown", (e) => {
    if (!sizes.hidden && !(e.target instanceof Node && $("size-box").contains(e.target))) closeLayer("sizes", false);
  }, true);
  $("size-box").addEventListener("focusout", (e) => {
    if (e.relatedTarget instanceof Node && !$("size-box").contains(e.relatedTarget)) closeLayer("sizes", false);
  });
  // Escape closes the layer on top.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (layers.length) closeLayer(layers[layers.length - 1].name);
    else if (doc.dataset.full === "auto") auto.end();
  });
  // --- full screen: the tab alone, the controls hidden for reading --------------------------------------------------
  // A double tap beside the tab (layers.js's doubleTap: MARGIN_SKIP and this page's own elements) hides what is
  // marked data-controls (the bar), the header's facts and the rail (drawRail), html[data-full] (viewer.css); a thin
  // handle stays at the window's foot. A layer of the stack above: the handle, Escape or Back brings it all back. A
  // short screen does it by itself, with no entry (layers.js's autoFull). Nothing here is the viewer's own copy.
  const handle = $("handle");
  const fullScreen = (on) => {
    if (on) doc.dataset.full = "on";
    else delete doc.dataset.full;
    handle.hidden = !on;
    drawRail();
    toolbar.edge();  // from 1200 px, the pill under the toolbar again, or at the top with none
  };
  handle.addEventListener("click", () => {
    if (doc.dataset.full === "auto") auto.end();
    else closeLayer("full");
  });
  const auto = window.caracoleLayers ? window.caracoleLayers.autoFull({
    handle, idle: () => layers.length === 0, changed: () => { drawRail(); toolbar.edge(); },
  }) : { end() {} };
  if (window.caracoleLayers) {
    window.caracoleLayers.doubleTap(document, window.caracoleLayers.MARGIN_SKIP + ", .h, .rp, .legend, .why", () => {
      if (!doc.dataset.full) openLayer("full", null);
    });
  }
  const setSize = (to) => {
    state.fs = Math.max(FS.min, Math.min(FS.max, to));
    render();
    save();
  };
  for (const choice of ["auto", "light", "dark"]) {
    $("theme-" + choice).addEventListener("click", () => {
      screenKit.setTheme(choice);
      render();
      save();
    });
  }
  $("smaller").addEventListener("click", () => setSize(state.fs - FS.step));
  $("bigger").addEventListener("click", () => setSize(state.fs + FS.step));

  // --- the version line and its list (kinds.js) -----------------------------------------------------------------
  // The song's line under the artist and the list it opens, a layer of the stack above ("list"): a sheet from the
  // bottom on a phone, docked on the bar; from 900 px a popover under the line, placed by kinds.js. Served (caracole
  // serve sent this page, as viewer.js tells), its versions are kept and chosen on the song's sheet (sheetPath, its
  // path in the library), none for a song with no sheet, and its Guitar Pro files open on caracole serve's Guitar Pro
  // page by the song's folder, this page's own (folder), sheet or none; each link to another of the song's pages
  // takes the screen's choices along, as ‹ Chord sheet does.
  const served = location.protocol !== "file:" && location.hostname !== "appassets.androidplatform.net";
  const libraryPath = (() => {
    try {
      return decodeURIComponent(location.pathname.slice(1));
    } catch (err) { return ""; }
  })();
  const sheetOf = data.kinds && typeof data.kinds === "object" && typeof data.kinds.page === "string" && data.kinds.page
    ? data.kinds.page : null;
  if (vList && window.caracoleKinds) {
    kinds = window.caracoleKinds.attach({
      data, here: libraryPath.split("/").pop(), served,
      sheetPath: sheetOf === null ? undefined : libraryPath.split("/").slice(0, -1).concat([sheetOf]).join("/"),
      folder: libraryPath.split("/").slice(0, -1).join("/") || undefined,
      carry: (page) => encodeURIComponent(page) + screenChoices(),
      open: (el, opener) => openLayer("list", opener),
      close: () => closeLayer("list"),
      inSight,
    });
    vList.querySelector("[data-close]").addEventListener("click", () => closeLayer("list"));
  }

  // --- scrolling by itself, as the viewer does -------------------------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the harp; pressed again, it starts at once), running, or
  // paused; the pill steers it, above the bar's place (from 1200 px under the toolbar). A finger on the page, the
  // wheel, a key that scrolls, a scroll by hand or the end of the tab pauses it.
  const pill = $("pill"), go = $("go");
  // Across 1200 px: the toolbar under the title, or the bar back at the foot, away while the tab moves by itself.
  toolbar.wide.addEventListener("change", () => {
    toolbar.place();
    showScroll();
  });
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;
    bar.classList.toggle("away", moving() && !docked());  // the overlay's sheet, or the list, sits on it
    bar.toggleAttribute("data-asleep", moving());  // from 1200 px the toolbar out of sight, its room kept
    toolbar.edge();  // and the pill under it
    pill.dataset.state = scroll.state;
    $("scroll").setAttribute("aria-pressed", scroll.state === "off" ? "false" : "true");  // lit while it is on
    go.setAttribute("aria-label", LABELS[scroll.state] || "Pause");
    $("tick").textContent = scroll.state === "counting"
      ? String(Math.max(1, Math.ceil((scroll.ends - performance.now()) / 1000))) : "";
    if (said !== undefined) $("scroll-status").textContent = said;
  };
  // The screen stays on while it counts down and scrolls, and as long after the last touch as the sheet pages' Keep
  // the screen on says (this page has no control of its own): screen.js's.
  const awake = screenKit.awake(moving);
  const run = () => {
    clearTimeout(scroll.timer);
    scroll.state = "running";
    scroll.from = scroll.at = window.scrollY;
    scroll.travelled = 0;
    scroll.last = 0;
    const loop = ++scroll.loop;
    const frame = (now) => {
      if (scroll.state !== "running" || loop !== scroll.loop) return;
      if (Math.abs(window.scrollY - scroll.at) > 3) {  // moved some other way: yours to read
        pauseScroll();
        return;
      }
      if (scroll.last) {
        scroll.travelled += (Math.min(now - scroll.last, 250) / 1000) * pace();
        const y = Math.round(scroll.from + scroll.travelled);
        if (y !== Math.round(scroll.at)) {
          window.scrollTo(0, y);
          scroll.at = window.scrollY;
        }
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
          pauseScroll("Paused · end of tab");
          return;
        }
      }
      scroll.last = now;
      requestAnimationFrame(frame);
    };
    showScroll("Scrolling");
    awake();
    requestAnimationFrame(frame);
  };
  const countdown = () => {
    clearTimeout(scroll.timer);
    scroll.state = "counting";
    scroll.ends = performance.now() + COUNTDOWN;
    const tick = () => {
      const left = scroll.ends - performance.now();
      if (left <= 0) {
        run();
        return;
      }
      showScroll();
      scroll.timer = setTimeout(tick, left % 1000 || 1000);
    };
    tick();
    showScroll("Scrolling in " + COUNTDOWN / 1000 + " s");
    awake();
  };
  function pauseScroll(said) {
    if (!moving()) return;
    clearTimeout(scroll.timer);
    scroll.state = "paused";
    showScroll(said || "Paused");
    awake();
  }
  const endScroll = () => {
    const mine = pill.contains(document.activeElement);
    clearTimeout(scroll.timer);
    scroll.state = "off";
    showScroll("");
    awake();
    if (mine) $("scroll").focus({ preventScroll: true });
  };
  // The tab moves only in sight: the sheet over the whole screen goes back to half, the tab moving above it.
  const halfSheet = () => {
    if (sheetAt !== "full") return;
    sheetAt = "half";
    drawRail();
  };
  $("scroll").addEventListener("click", () => {
    closeLayer("sizes", false);
    halfSheet();
    countdown();
    go.focus({ preventScroll: true });
  });
  go.addEventListener("click", () => {
    if (scroll.state !== "running") halfSheet();  // the pill's ▶, as the bar's Scroll
    if (scroll.state === "counting") run();
    else if (scroll.state === "running") pauseScroll();
    else countdown();
  });
  $("pill-end").addEventListener("click", endScroll);
  for (const b of document.querySelectorAll("[data-speed]")) {
    b.addEventListener("click", () => {
      state.speed = Math.max(SPEED.min, Math.min(SPEED.max, state.speed + Number(b.dataset.speed)));
      render();
      save();
    });
  }
  window.addEventListener("touchstart", (e) => {
    if (!(e.target instanceof Element && e.target.closest("#pill"))) pauseScroll();
  }, { passive: true });
  window.addEventListener("wheel", () => pauseScroll(), { passive: true });
  // Home and End pause it; Space, Enter and the four page keys are the key map's, as the viewer's (screen.js keys),
  // left to Aa's box, the rail of necks (or the phone's sheet) and the versions list while one has the focus,
  // full screen's handle not counted.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Home" || e.key === "End") pauseScroll();
  });
  const busy = () => {
    const at = document.activeElement instanceof Element ? document.activeElement : null;
    return Boolean(at) && at !== handle && Boolean(at.closest("#sizes, #necks, #version-list"));
  };
  screenKit.keys({
    toggle: () => (scroll.state === "off" ? $("scroll") : go).click(),
    pause: () => pauseScroll(),
    room: () => toolbar.room(pill, docked()),
    busy,
    sheet,
    steer: [$("scroll"), ...pill.getElementsByTagName("button")],
  });

  // --- the bar: away as you read down the tab, back when you want it ---------------------------------------------
  const reveal = { y: window.scrollY, touched: false };
  for (const kind of ["touchstart", "pointerdown", "wheel", "keydown"]) {
    window.addEventListener(kind, () => { reveal.touched = true; }, { passive: true, capture: true });
  }
  window.addEventListener("scroll", () => {
    const y = window.scrollY, dy = y - reveal.y;
    toolbar.edge();
    if (moving() || toolbar.wide.matches) {  // from 1200 px the toolbar never slides away
      reveal.y = y;
      return;
    }
    if (y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2) {
      bar.classList.remove("away");
      reveal.y = y;
      return;
    }
    if (!reveal.touched || !sizes.hidden || docked() || bar.contains(document.activeElement)) {
      reveal.y = y;
      return;
    }
    if (Math.abs(dy) < 8) return;
    bar.classList.toggle("away", dy > 0);
    reveal.y = y;
  }, { passive: true });
  document.addEventListener("click", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (target && !target.closest("#bar, #pill, a, button, summary, [role=button]")) bar.classList.remove("away");
  });
  bar.addEventListener("focusin", () => bar.classList.remove("away"));

  // --- how the tab is read, changed on caracole serve's page of readings -----------------------------------------
  // Served (caracole serve sent this page, as viewer.js tells), the Read as line's source ("guessed (0.86)", "from the
  // tab's own legend", "as you set it") is a link to the server's own page of the readings caracole weighs for this
  // tab (/harmonica?page=, its library path), and a tab read by harptabs.com's own key, or shown as written, has a
  // "Change how it's read" link at its foot. From a file, or in caracole's Android app, no server answers: no link.
  if (served) {
    const path = libraryPath;  // "" for an address that can't be read: no link
    const href = "/harmonica?page=" + encodeURIComponent(path);
    const source = $("reading-src"), foot = $("reading-foot");
    if (path && source) {
      const link = el("a", "src", source.textContent);
      link.id = "reading-src";
      link.setAttribute("href", href);
      source.replaceWith(link);
    }
    if (path && foot) {
      foot.querySelector("a").setAttribute("href", href);
      foot.hidden = false;
    }
  }

  toolbar.place();  // under the title from 1200 px, before it shows
  bar.hidden = false;
  showScroll();
  render();
  backToSheet();
  doc.dataset.ready = "1";
})();
