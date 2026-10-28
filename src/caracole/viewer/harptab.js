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
  // The song's names (its title, its artist's, the page's title) in the characters the sheet viewer shows the Chinese
  // in, Simplified at first: its choice, kept for every page (localStorage), else trad=1 in the address; this page has
  // no row of its own. harptab_page.py's song-names block converts each by its text as written (data-zh).
  try {
    const names = JSON.parse($("song-names") ? $("song-names").textContent : "null");
    let trad = hash.get("trad") === "1";
    try {
      if (localStorage.getItem("caracole-viewer-hanzi") === "traditional") trad = true;
    } catch (err) { /* no storage: the address says */ }
    const table = names && typeof names === "object" ? names[trad ? "traditional" : "simplified"] : null;
    for (const el of document.querySelectorAll("[data-zh]")) {
      const written = el.getAttribute("data-zh");
      if (table && typeof table === "object" && Object.prototype.hasOwnProperty.call(table, written)
        && typeof table[written] === "string") el.textContent = table[written];
    }
  } catch (err) { /* none: as written */ }
  const kit = window.caracoleOverlay || null;
  try {
    if (kit && localStorage.getItem(kit.NECKS) === "hidden") state.necks = false;
  } catch (err) { /* no storage: shown, unless the address says otherwise */ }
  if (hash.get("necks") === "0") state.necks = false;
  const keepNecks = () => {
    try {
      if (kit) localStorage.setItem(kit.NECKS, state.necks ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // ‹ Chord sheet takes the screen's choices back with it (the rail hidden, and as they came in the address, a sheet's
  // viewer's link here having taken them on: the pinyin, the Chinese characters, the instrument), so that where the
  // browser keeps nothing (caracole serve's sandbox) they go both ways. ‹ Library takes none.
  const sheetLink = document.querySelector("a.back[data-sheet]");
  const sheetPage = sheetLink ? sheetLink.getAttribute("href") : "";
  function backToSheet() {
    if (!sheetLink) return;
    const now = new URLSearchParams(location.hash.slice(1)), params = new URLSearchParams();
    if (!state.necks) params.set("necks", "0");
    for (const name of ["py", "trad", "inst"]) if (now.has(name)) params.set(name, now.get(name));
    const fragment = params.toString();
    sheetLink.setAttribute("href", sheetPage + (fragment ? "#" + fragment : ""));
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
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(null, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
    backToSheet();
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
    $("smaller").setAttribute("aria-disabled", state.fs <= FS.min ? "true" : "false");
    $("bigger").setAttribute("aria-disabled", state.fs >= FS.max ? "true" : "false");
    $("pill-speed").textContent = String(state.speed);
    drawRail();
  };

  // --- the overlay: Harmonica and Guitar, on a wide screen ------------------------------------------------------
  const over = data.overlay && typeof data.overlay === "object" && data.overlay.harp ? data.overlay : null;
  const aside = $("necks"), necksButton = $("necks-toggle"), sheetButton = $("necks-open");
  const wide = window.matchMedia("(min-width: 1200px)");
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
    close: () => closeSheet(),
  }) : null;
  function drawRail() {
    const can = Boolean(rail) && wide.matches, on = can && state.necks;
    const phone = Boolean(rail) && !wide.matches && sheetAt !== null;
    necksButton.hidden = !can;
    necksButton.setAttribute("aria-pressed", on ? "true" : "false");
    sheetButton.hidden = !rail || wide.matches;
    sheetButton.setAttribute("aria-expanded", phone ? "true" : "false");
    aside.hidden = !on && !phone;
    aside.classList.toggle("top", phone);  // the one sheet here: always on top (viewer.css)
    if (on) doc.dataset.necks = "1";  // the tab and the bar move over for it
    else delete doc.dataset.necks;
    if (on || phone) rail.draw();
    else if (rail) rail.empty();
    else aside.textContent = "";
    dockSheet();
  }
  // The sheet docked on the bar, as the viewer's settings are: the page leaves room under the tab for it, so its end
  // comes up above it, and the pill rides above it (--dock, viewer.css), or over the foot of the whole-screen one.
  function dockSheet() {
    if (sheetAt !== null && !wide.matches) {
      doc.dataset.dock = sheetAt === "full" ? "necks-full" : "necks";
      doc.style.setProperty("--dock", aside.offsetHeight + "px");
    } else if (doc.dataset.dock) {
      delete doc.dataset.dock;
      doc.style.removeProperty("--dock");
    }
  }
  // Open, the focus on its tab shown; closed, back on the neck when it was in the sheet. The bar stays under it.
  const openSheet = () => {
    if (sheetAt === null) sheetAt = "half";
    showSizes(false);
    pauseScroll();
    bar.classList.remove("away");
    drawRail();
    const to = rail.landing();
    if (to) to.focus({ preventScroll: true });
  };
  function closeSheet() {
    if (sheetAt === null) return;
    const active = document.activeElement;
    const mine = !active || active === document.body || aside.contains(active);
    sheetAt = null;
    drawRail();
    if (mine) sheetButton.focus({ preventScroll: true });
  }
  sheetButton.addEventListener("click", () => (sheetAt === null ? openSheet() : closeSheet()));
  window.addEventListener("resize", () => dockSheet());
  const showRail = (on) => {
    state.necks = on;
    keepNecks();
    drawRail();
    save();
  };
  necksButton.addEventListener("click", () => showRail(!state.necks));
  // The window narrowed below 1200 px with the keyboard's focus in the rail: it goes to the bar's first control, where
  // the rail's button was. Widened past it with the sheet open: the rail takes its place, on its tab.
  wide.addEventListener("change", () => {
    const had = aside.contains(document.activeElement);
    if (wide.matches) sheetAt = null;
    drawRail();
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
  sizeButton.addEventListener("click", () => showSizes(sizes.hidden));
  document.addEventListener("pointerdown", (e) => {
    if (!sizes.hidden && !(e.target instanceof Node && $("size-box").contains(e.target))) showSizes(false);
  }, true);
  $("size-box").addEventListener("focusout", (e) => {
    if (e.relatedTarget instanceof Node && !$("size-box").contains(e.relatedTarget)) showSizes(false);
  });
  // Escape: the size box first, then the overlay's sheet.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !sizes.hidden) {
      showSizes(false);
      sizeButton.focus({ preventScroll: true });
    } else if (e.key === "Escape" && sheetAt !== null) {
      closeSheet();
    }
  });
  const setSize = (to) => {
    state.fs = Math.max(FS.min, Math.min(FS.max, to));
    render();
    save();
  };
  $("smaller").addEventListener("click", () => setSize(state.fs - FS.step));
  $("bigger").addEventListener("click", () => setSize(state.fs + FS.step));

  // --- scrolling by itself, as the viewer does -------------------------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the harp; pressed again, it starts at once), running, or
  // paused; the pill steers it, above the bar's place. A finger on the page, the wheel, a key that scrolls, a scroll
  // by hand or the end of the tab pauses it.
  const bar = $("bar"), pill = $("pill"), go = $("go");
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start now", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;
    bar.classList.toggle("away", moving() && sheetAt === null);  // the overlay's sheet sits on it
    pill.dataset.state = scroll.state;
    go.setAttribute("aria-label", LABELS[scroll.state] || "Pause");
    $("tick").textContent = scroll.state === "counting"
      ? String(Math.max(1, Math.ceil((scroll.ends - performance.now()) / 1000))) : "";
    if (said !== undefined) $("scroll-status").textContent = said;
  };
  let wake = null;
  const holdScreen = () => {
    if (wake || !navigator.wakeLock) return;
    try {
      navigator.wakeLock.request("screen").then((lock) => {
        if (!moving()) {
          lock.release().catch(() => {});
          return;
        }
        wake = lock;
        lock.addEventListener("release", () => { if (wake === lock) wake = null; });
      }, () => {});
    } catch (err) { /* no wake lock here */ }
  };
  const letScreenSleep = () => {
    const lock = wake;
    wake = null;
    if (lock) lock.release().catch(() => {});
  };
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
          pauseScroll("Paused at the end of the tab");
          return;
        }
      }
      scroll.last = now;
      requestAnimationFrame(frame);
    };
    showScroll("Scrolling");
    holdScreen();
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
    showScroll("Scrolling in " + COUNTDOWN / 1000 + " seconds");
    holdScreen();
  };
  function pauseScroll(said) {
    if (!moving()) return;
    clearTimeout(scroll.timer);
    scroll.state = "paused";
    showScroll(said || "Paused");
    letScreenSleep();
  }
  const endScroll = () => {
    const mine = pill.contains(document.activeElement);
    clearTimeout(scroll.timer);
    scroll.state = "off";
    showScroll("");
    letScreenSleep();
    if (mine) $("scroll").focus({ preventScroll: true });
  };
  $("scroll").addEventListener("click", () => {
    showSizes(false);
    if (sheetAt === "full") {  // the sheet stays, at half the screen, the tab moving above it
      sheetAt = "half";
      drawRail();
    }
    countdown();
    go.focus({ preventScroll: true });
  });
  go.addEventListener("click", () => {
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
  const SCROLL_KEYS = ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"];
  document.addEventListener("keydown", (e) => {
    const control = e.target instanceof Element && e.target.closest("button, a, [role=button], summary, input");
    if (SCROLL_KEYS.indexOf(e.key) >= 0 || (e.key === " " && !control)) pauseScroll();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && moving()) holdScreen();
  });

  // --- the bar: away as you read down the tab, back when you want it ---------------------------------------------
  const reveal = { y: window.scrollY, touched: false };
  for (const kind of ["touchstart", "pointerdown", "wheel", "keydown"]) {
    window.addEventListener(kind, () => { reveal.touched = true; }, { passive: true, capture: true });
  }
  window.addEventListener("scroll", () => {
    const y = window.scrollY, dy = y - reveal.y;
    if (moving()) {
      reveal.y = y;
      return;
    }
    if (y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2) {
      bar.classList.remove("away");
      reveal.y = y;
      return;
    }
    if (!reveal.touched || !sizes.hidden || sheetAt !== null || bar.contains(document.activeElement)) {
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
  const served = location.protocol !== "file:" && location.hostname !== "appassets.androidplatform.net";
  if (served) {
    let path = "";
    try {
      path = decodeURIComponent(location.pathname.slice(1));
    } catch (err) { /* an address that can't be read: no link */ }
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

  bar.hidden = false;
  showScroll();
  render();
  backToSheet();
  doc.dataset.ready = "1";
})();
