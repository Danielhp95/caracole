(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const doc = document.documentElement;
  let data;
  try {
    data = JSON.parse($("song").textContent);
  } catch (err) {
    doc.dataset.error = "data";
    return;
  }
  const own = Object.prototype.hasOwnProperty;
  const mod12 = (n) => ((n % 12) + 12) % 12;
  const signed = (n) => (n > 0 ? "+" + n : n < 0 ? "−" + -n : "0");
  const key = data.key;
  const chordEls = Array.from(document.querySelectorAll("#sheet .c"));
  const written = {};  // each chord as the sheet writes it, by index
  for (const el of chordEls) if (!own.call(written, el.dataset.c)) written[el.dataset.c] = el.textContent;
  const count = data.chords.length;
  const MODES = {
    ionian: ["Major", "bright and settled"],
    dorian: ["Dorian", "minor, with a brighter sixth"],
    phrygian: ["Phrygian", "minor and dark, with a Spanish half step"],
    lydian: ["Lydian", "major and dreamy, with a raised fourth"],
    mixolydian: ["Mixolydian", "major and bluesy, with a flat seventh"],
    aeolian: ["Minor", "the natural minor"],
    locrian: ["Locrian", "tense and unstable"],
  };
  const FS = { min: 13, max: 30, step: 2, start: 18 };
  // The scroll's speed, 1 to 30: ``px`` pixels a second a step at the usual text size (see pace()).
  const SPEED = { min: 1, max: 30, start: 6, px: 2 };
  // The capo goes on any fret up to the 11th (past it the shapes come round again), or the sheet's.
  const CAPO_MAX = Math.max(11, Number(data.capoSheet) || 0);

  // --- the state: where the song is played, kept per page ------------------------------------
  // capo: the fret the capo is on (0 for none), or null for the sheet's own. It stays there
  // through a transposition, as on a guitar: the shapes move instead.
  const state = { t: Number(data.transpose) || 0, mode: null, alt: {}, capo: null, fs: FS.start, strip: false,
    speed: SPEED.start };
  const store = "caracole-viewer:" + location.pathname;
  // Chords chosen instead of others are kept for the sheet's chords by index: they only hold
  // while the sheet's chords do.
  const sheetChords = Object.keys(written).map((i) => written[i]).join("|");
  const validMode = (m) => Boolean(key) && data.modes.indexOf(m) >= 0;
  const clampT = (t) => Math.max(-11, Math.min(11, Math.round(Number(t) || 0)));
  const fretOf = (v) => (v === null || v === undefined || v === "" || !(Number(v) >= 0) ? null
    : Math.min(CAPO_MAX, Math.round(Number(v))));
  const sizeOf = (v) => (Number(v) >= FS.min && Number(v) <= FS.max ? Math.round(Number(v)) : null);
  const speedOf = (v) => (Number(v) >= SPEED.min && Number(v) <= SPEED.max ? Math.round(Number(v)) : null);
  try {
    const saved = JSON.parse(localStorage.getItem(store) || "null");
    if (saved && typeof saved === "object") {
      if (saved.base === data.transpose) state.t = clampT(saved.t);  // a new [transpose] starts afresh
      if (validMode(saved.mode)) state.mode = saved.mode;
      if (saved.alt && typeof saved.alt === "object" && saved.chords === sheetChords) state.alt = saved.alt;
      if (sizeOf(saved.fs) !== null) state.fs = sizeOf(saved.fs);
      if (speedOf(saved.speed) !== null) state.speed = speedOf(saved.speed);
      state.strip = saved.strip === true;
      state.capo = fretOf(saved.capo);
    }
  } catch (err) { /* no storage: the page still works */ }
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has("t")) state.t = clampT(hash.get("t"));
  if (validMode(hash.get("mode"))) state.mode = hash.get("mode");
  if (hash.has("capo")) state.capo = fretOf(hash.get("capo"));
  if (sizeOf(hash.get("fs")) !== null) state.fs = sizeOf(hash.get("fs"));
  if (speedOf(hash.get("speed")) !== null) state.speed = speedOf(hash.get("speed"));
  const save = () => {
    try {
      localStorage.setItem(store, JSON.stringify(Object.assign({ base: data.transpose, chords: sheetChords }, state)));
    } catch (err) { /* private mode, or a server's sandbox */ }
    // The address keeps where the song is played too, and the text size and the scroll speed,
    // read back above: without storage (a server's sandbox), a reload and Back still keep them.
    // Replaced, so Back isn't a step per tap.
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const keep = (name, value, kept) => (kept ? params.set(name, String(value)) : params.delete(name));
      keep("t", state.t, state.t !== (Number(data.transpose) || 0));
      keep("mode", state.mode, state.mode !== null);
      keep("capo", state.capo, state.capo !== null);
      keep("fs", state.fs, state.fs !== FS.start);
      keep("speed", state.speed, state.speed !== SPEED.start);
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(null, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
  };

  // --- naming chords -------------------------------------------------------------------------
  const modeNow = () => (key ? state.mode || key.mode : "");
  const asWritten = () => !state.mode || (key && state.mode === key.mode);
  const sheetCapo = Number(data.capoSheet) || 0;
  const capoNow = () => (state.capo === null ? sheetCapo : state.capo);
  // The chords are named for the shapes played: with another capo, as many semitones off.
  const shift = () => state.t - (capoNow() - sheetCapo);
  const names = (s) => (key ? data.names[modeNow()][mod12(key.tonic + s)] : data.names[""]).split(" ");
  const keyName = (s) => (key ? data.keyNames[modeNow()][mod12(key.tonic + s)] : "");
  const choices = () => state.alt[modeNow()] || {};
  // A chord chosen instead of another is kept as itself ([root, suffix, bass]) and found again
  // among the alternatives offered now: once the key or caracole's alternatives change, a
  // chord no longer offered is dropped rather than another one played in its place.
  const sameChord = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const choice = (i) => {
    const chosen = own.call(choices(), i) ? choices()[i] : null;
    return Array.isArray(chosen) ? alts(i).findIndex((rep) => sameChord(rep, chosen)) : -1;
  };
  const alts = (i) => (key && data.alts[modeNow()] ? data.alts[modeNow()][i] || [] : []);
  const base = (i) => (asWritten() ? data.chords[i] : data.mapped[modeNow()][i]);
  const current = (i) => {
    const j = choice(i);
    return j >= 0 && alts(i)[j] ? alts(i)[j] : base(i);
  };
  const nameOf = (rep, s) => {
    const n = names(s);
    return n[mod12(rep[0] + s)] + rep[1] + (rep[2] === null ? "" : "/" + n[mod12(rep[2] + s)]);
  };
  const label = (i, rep) => {
    if (!rep) return written[i];
    if (shift() === 0 && asWritten() && rep === data.chords[i]) return written[i];
    return nameOf(rep, shift());
  };
  const capoHints = () => (key ? data.capo[modeNow()][mod12(state.t)] : []);
  // Where the song is played, as Cifra Club's key line says it: with a capo, the key of the
  // shapes, the capo and the key the song sounds in ("Em shapes · capo 2 · sounds F#m"), as
  // "Key Em" alone would read as the song's key; with none, the key. Each part is
  // [before, in bold, after, where the key came from]; ``moved`` says the transposition.
  // page.py writes the same line for the sheet as written.
  const keyLine = (moved) => {
    const capo = capoNow();
    if (!key) return capo ? [["Capo ", String(capo), "", ""]] : sheetCapo ? [["No capo", "", "", ""]] : [];
    const sounds = keyName(state.t + sheetCapo);
    if (!capo) return [["Key ", sounds, moved, key.from]].concat(sheetCapo ? [["no capo", "", "", ""]] : []);
    return [["", keyName(shift()), " shapes", ""], ["capo ", String(capo), "", ""], ["sounds ", sounds, moved, ""]]
      .concat(key.from ? [["", "", "", "key " + key.from]] : []);
  };
  // The same as one line of text, for the key button (``moved``: with the transposition) and
  // the settings' heading; without a key, the button says Transpose and the capo.
  const keyLabel = (moved) => {
    const shown = moved && state.t ? signed(state.t) : "";
    if (!key) {
      const capo = capoNow();
      return ["Transpose" + (shown ? " " + shown : "")]
        .concat(capo ? ["capo " + capo] : sheetCapo ? ["no capo"] : []).join(" · ");
    }
    return keyLine("").filter((part) => part[1] || !part[3]).map((part) => part[0] + part[1] + part[2])
      .concat(shown ? [shown] : []).join(" · ");
  };

  // --- chord diagrams --------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(node);
    return node;
  };
  const shapesOf = (rep, s) => {
    if (!rep) return { list: [], note: "" };
    const pc = mod12(rep[0] + s);
    const n = names(s);
    const slash = rep[5] && data.voicings[rep[5]] ? data.voicings[rep[5]][pc] : null;
    if (slash && slash.length) return { list: slash, note: "" };
    const list = data.voicings[rep[3]] ? data.voicings[rep[3]][pc] || [] : [];
    let note = "";
    if (rep[4]) {
      const q = own.call(data.qualities, rep[3]) ? data.qualities[rep[3]] : rep[3];
      note = "No shape for this chord here: " + n[pc] + q + " is the closest.";
    }
    if (rep[2] !== null) note = (note ? note + " " : "") + "Play " + n[mod12(rep[2] + s)] + " in the bass.";
    return { list, note };
  };
  const diagram = (position, title) => {
    const frets = String(position[0]);
    const fingers = String(position[1]);
    const first = Number(position[2]) || 1;
    const barres = Array.isArray(position[3]) ? position[3] : [];
    const deepest = Math.max(4, ...Array.from(frets).map((f) => (f === "x" ? 0 : Number(f))));
    const left = 16, top = 16, gap = 10, row = 13;
    const width = left + gap * 5 + 10, height = top + row * deepest + 6;
    const root = svg("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": title });
    for (let s = 0; s < 6; s++) {
      svg("line", { class: "dg-grid", x1: left + s * gap, y1: top, x2: left + s * gap, y2: top + row * deepest }, root);
    }
    for (let f = 0; f <= deepest; f++) {
      svg("line", { class: "dg-grid", x1: left, y1: top + f * row, x2: left + gap * 5, y2: top + f * row }, root);
    }
    if (first === 1) svg("rect", { class: "dg-nut", x: left - 0.5, y: top - 2.5, width: gap * 5 + 1, height: 3 }, root);
    else svg("text", { class: "dg-fret", x: left - 4, y: top + row / 2 }, root).textContent = first + "fr";
    for (const b of barres) {
      const on = [];
      for (let s = 0; s < 6; s++) if (Number(frets[s]) === b) on.push(s);
      if (on.length < 2) continue;
      const x1 = left + on[0] * gap, x2 = left + on[on.length - 1] * gap, y = top + (b - 0.5) * row;
      svg("rect", { class: "dg-barre", x: x1 - 4.2, y: y - 4.2, width: x2 - x1 + 8.4, height: 8.4, rx: 4.2 }, root);
    }
    for (let s = 0; s < 6; s++) {
      const x = left + s * gap;
      const f = frets[s];
      if (f === "x") {
        svg("path", { class: "dg-mute", d: `M${x - 2.6} ${top - 9.6}l5.2 5.2m0 -5.2l-5.2 5.2` }, root);
      } else if (f === "0") {
        svg("circle", { class: "dg-open", cx: x, cy: top - 7, r: 2.8 }, root);
      } else {
        const y = top + (Number(f) - 0.5) * row;
        svg("circle", { class: "dg-dot", cx: x, cy: y, r: 4.2 }, root);
        if (fingers[s] && fingers[s] !== "0") {
          svg("text", { class: "dg-finger", x: x, y: y + 0.3 }, root).textContent = fingers[s];
        }
      }
    }
    return root;
  };

  // --- drawing the page --------------------------------------------------------------------------
  const fab = $("fab"), panel = $("panel"), card = $("card"), scrim = $("scrim"), pill = $("pill"), go = $("go");
  const button = (text, pressed, onClick, small) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = text;
    if (small) {
      const s = document.createElement("small");
      s.textContent = small;
      b.appendChild(s);
    }
    b.setAttribute("aria-pressed", pressed ? "true" : "false");
    b.addEventListener("click", onClick);
    return b;
  };

  const render = () => {
    if (state.capo === sheetCapo) state.capo = null;  // the sheet's own again
    for (const el of chordEls) {
      const i = el.dataset.c;
      el.textContent = label(i, current(i));
      el.classList.toggle("changed", choice(i) >= 0);
    }
    doc.style.setProperty("--fs", state.fs + "px");

    fab.textContent = keyLabel(true);
    $("panel-title").textContent = key ? keyLabel(false) : "Transpose";
    const box = $("facts");
    box.textContent = "";
    keyLine(state.t ? " (" + signed(state.t) + ")" : "").forEach((f, n) => {
      if (n) box.appendChild(document.createTextNode(" · "));
      if (f[0]) box.appendChild(document.createTextNode(f[0]));
      if (f[1]) {
        const b = document.createElement("b");
        b.textContent = f[1];
        box.appendChild(b);
      }
      if (f[2]) box.appendChild(document.createTextNode(f[2]));
      if (f[3]) {
        const from = document.createElement("span");
        from.className = "from";
        from.textContent = (f[0] || f[1] ? " " : "") + f[3];
        box.appendChild(from);
      }
    });

    $("shift").textContent = signed(state.t);
    $("shift-hint").textContent = data.transpose
      ? "Your PDF is transposed " + signed(data.transpose) + "; Reset goes back there." : "";
    $("capo-at").textContent = String(capoNow());
    const hints = capoHints();
    const capoBox = $("capo");
    capoBox.textContent = "";
    for (const [fret, shapesKey] of hints) {
      capoBox.appendChild(button(fret ? "Capo " + fret : "No capo", state.capo === fret, () => {
        state.capo = state.capo === fret ? null : fret;
        render();
      }, shapesKey + " shapes"));
    }
    // The same words wherever the capo is, so the row keeps its height under your thumb.
    $("capo-hint").textContent = "Wherever the capo is, the song sounds the same: the chords show the shapes to play."
      + (hints.length ? " Easier shapes:" : "");

    $("mode-row").hidden = !key;
    const modeBox = $("modes");
    modeBox.textContent = "";
    if (key) {
      for (const mode of data.modes) {
        const info = MODES[mode] || [mode, ""];
        modeBox.appendChild(button(info[0], modeNow() === mode, () => {
          state.mode = mode === key.mode ? null : mode;
          render();
          if (!card.hidden) drawCard();
        }, mode === key.mode ? "as written" : ""));
      }
      const info = MODES[modeNow()] || ["", ""];
      $("mode-hint").textContent = keyName(state.t + sheetCapo) + ": " + info[1] + "." +
        (asWritten() ? "" : " Each chord moves to the same degree of the new scale.");
    }

    $("strip-toggle").setAttribute("aria-pressed", state.strip ? "true" : "false");
    $("strip-toggle").textContent = state.strip ? "Hide" : "Show all";
    drawSpeed();
    drawStrip();
    fit();
    save();
  };

  // A chord may reach over the words after it, up to the next chord on its row: lyrics then
  // read without gaps. Where two chords would touch, the first one's column is widened.
  const sheetEl = $("sheet");
  const fit = () => {
    sheetEl.classList.add("tight");
    for (const y of sheetEl.querySelectorAll(".s > .y")) y.style.minWidth = "";
    const space = parseFloat(getComputedStyle(sheetEl).fontSize) * 0.45;
    for (const line of sheetEl.querySelectorAll(".l")) {
      const kids = Array.from(line.children);
      const right = line.getBoundingClientRect().right;
      kids.forEach((col, k) => {
        if (!col.classList.contains("s")) return;
        const box = col.getBoundingClientRect();
        const need = col.firstElementChild.offsetWidth + space;
        let room = right - box.left;  // no chord after it on its row: up to the edge
        for (let m = k + 1; m < kids.length; m++) {
          const next = kids[m].getBoundingClientRect();
          if (Math.abs(next.bottom - box.bottom) > 2) break;  // wrapped onto the next row
          if (kids[m].classList.contains("s")) {
            room = next.left - box.left;
            break;
          }
        }
        if (room < need) col.lastElementChild.style.minWidth = Math.ceil(box.width + need - room) + "px";
      });
    }
  };
  let fitting = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(fitting);
    fitting = requestAnimationFrame(fit);
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit, () => {});

  const drawStrip = () => {
    const strip = $("strip");
    strip.hidden = !state.strip;
    strip.textContent = "";
    if (!state.strip) return;
    for (let i = 0; i < count; i++) {
      const rep = current(String(i));
      const shapes = shapesOf(rep, shift());
      const b = document.createElement("button");
      b.type = "button";
      const name = label(String(i), rep);
      if (shapes.list.length) b.appendChild(diagram(shapes.list[0], name));
      b.appendChild(document.createTextNode(name));
      b.addEventListener("click", () => openCard(String(i)));
      strip.appendChild(b);
    }
  };

  // --- the chord card: shapes, and chords to play instead ----------------------------------------
  const shown = { i: null, pick: -1, at: 0 };
  const openCard = (i) => {
    if (!own.call(written, i)) return;
    shown.i = i;
    shown.pick = choice(i);
    shown.at = 0;
    for (const el of chordEls) el.classList.toggle("on", el.dataset.c === i);
    open(card);
    drawCard();
  };
  const drawCard = () => {
    const i = shown.i;
    const list = alts(i);
    if (shown.pick >= list.length) shown.pick = -1;
    const rep = shown.pick >= 0 ? list[shown.pick] : base(i);
    const name = label(i, rep);
    $("card-name").textContent = name;
    const shapes = shapesOf(rep, shift());
    const box = $("diagram");
    box.textContent = "";
    if (shapes.list.length) {
      shown.at = Math.min(shown.at, shapes.list.length - 1);
      box.appendChild(diagram(shapes.list[shown.at], name));
      const c = document.createElement("span");
      c.className = "count";
      c.textContent = shapes.list.length > 1 ? shown.at + 1 + " of " + shapes.list.length : "";
      box.appendChild(c);
    } else {
      box.textContent = rep ? "No shape to show for this chord." : "caracole can't read this chord.";
    }
    $("prev").disabled = shown.at <= 0;
    $("next").disabled = shown.at >= shapes.list.length - 1;
    const capoNote = capoNow() ? " With the capo on fret " + capoNow() + "." : sheetCapo ? " With no capo." : "";
    const note = shapes.note + capoNote;
    $("shape-note").textContent = note.trim();

    const altBox = $("alts");
    altBox.textContent = "";
    $("alts-title").hidden = !list.length;
    if (list.length) {
      altBox.appendChild(button(label(i, base(i)), shown.pick < 0, () => pick(-1), "as written"));
      list.forEach((alt, j) => altBox.appendChild(button(label(i, alt), shown.pick === j, () => pick(j))));
    }
    const use = $("use");
    use.hidden = shown.pick === choice(i);
    const was = label(i, base(i));
    use.textContent = shown.pick >= 0 ? "Play " + name + " for every " + was : "Back to " + was + " everywhere";
  };
  const pick = (j) => {
    shown.pick = j;
    shown.at = 0;
    drawCard();
  };
  $("use").addEventListener("click", () => {
    const mode = modeNow();
    const mine = Object.assign({}, state.alt[mode] || {});
    if (shown.pick >= 0) mine[shown.i] = alts(shown.i)[shown.pick].slice(0, 3);
    else delete mine[shown.i];
    state.alt[mode] = mine;
    render();
    drawCard();
  });
  $("prev").addEventListener("click", () => { shown.at = Math.max(0, shown.at - 1); drawCard(); });
  $("next").addEventListener("click", () => { shown.at += 1; drawCard(); });
  let touchX = null;
  $("diagram").addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
  $("diagram").addEventListener("touchend", (e) => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    touchX = null;
    if (Math.abs(dx) > 36) (dx < 0 ? $("next") : $("prev")).click();
  });

  // --- the sheets that slide up ------------------------------------------------------------------
  // Each is a modal dialog: it takes the focus (its heading), the page behind is out of reach
  // (inert) while it is open, and closing it gives the focus back to what opened it.
  const pageEl = document.querySelector(".page");
  let opener = null;
  const open = (which) => {
    if (panel.hidden && card.hidden) opener = document.activeElement;
    for (const other of [panel, card]) if (other !== which) other.hidden = true;
    which.hidden = false;
    scrim.hidden = false;
    pageEl.inert = true;
    fab.inert = true;
    pill.inert = true;
    fab.setAttribute("aria-expanded", which === panel ? "true" : "false");
    pauseScroll();
    which.querySelector("h2").focus({ preventScroll: true });
  };
  const close = () => {
    const wasOpen = !(panel.hidden && card.hidden);
    panel.hidden = true;
    card.hidden = true;
    scrim.hidden = true;
    pageEl.inert = false;
    fab.inert = false;
    pill.inert = false;
    fab.setAttribute("aria-expanded", "false");
    for (const el of chordEls) el.classList.remove("on");
    if (wasOpen && opener && opener !== document.body && opener.isConnected) {
      opener.focus({ preventScroll: true });
    }
    opener = null;
  };
  scrim.addEventListener("click", close);
  for (const x of document.querySelectorAll("[data-close]")) x.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  fab.addEventListener("click", () => (panel.hidden ? open(panel) : close()));

  const sheet = $("sheet");
  sheet.addEventListener("click", (e) => {
    const el = e.target.closest(".c");
    if (el) openCard(el.dataset.c);
  });
  sheet.addEventListener("keydown", (e) => {
    const el = e.target.closest(".c");
    if (el && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openCard(el.dataset.c);
    }
  });

  const step = (t) => {
    state.t = clampT(t);
    render();
  };
  $("down").addEventListener("click", () => step(state.t - 1));
  $("up").addEventListener("click", () => step(state.t + 1));
  $("reset-t").addEventListener("click", () => step(data.transpose));
  const moveCapo = (fret) => {
    state.capo = Math.max(0, Math.min(CAPO_MAX, fret));
    render();
  };
  $("capo-down").addEventListener("click", () => moveCapo(capoNow() - 1));
  $("capo-up").addEventListener("click", () => moveCapo(capoNow() + 1));
  $("reset-capo").addEventListener("click", () => moveCapo(sheetCapo));
  $("smaller").addEventListener("click", () => { state.fs = Math.max(FS.min, state.fs - FS.step); render(); });
  $("bigger").addEventListener("click", () => { state.fs = Math.min(FS.max, state.fs + FS.step); render(); });
  $("strip-toggle").addEventListener("click", () => { state.strip = !state.strip; render(); });
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, capo: null });
    render();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the guitar; pressed again, it starts at
  // once), running, or paused. While it is on, the pill takes the key button's place: − and +
  // change the speed as it runs, ❚❚ pauses and ▶ resumes (after a countdown again), × ends it. A
  // finger on the page, the wheel, a key that scrolls, a scroll by hand or a card opening pauses
  // it: the page is yours to read until you press ▶.
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  // Pixels a second: a bigger text scrolls as much faster, so a speed keeps its pace through the song.
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start now", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    fab.hidden = count === 0 || scroll.state !== "off";  // nothing to transpose, or the pill there
    pill.dataset.state = scroll.state;
    go.setAttribute("aria-label", LABELS[scroll.state] || "Pause");
    $("tick").textContent = scroll.state === "counting"
      ? String(Math.max(1, Math.ceil((scroll.ends - performance.now()) / 1000))) : "";
    if (said !== undefined) $("scroll-status").textContent = said;
  };
  const drawSpeed = () => {
    $("speed").textContent = String(state.speed);
    $("pill-speed").textContent = String(state.speed);
  };
  const setSpeed = (n) => {
    state.speed = Math.max(SPEED.min, Math.min(SPEED.max, n));
    drawSpeed();
    save();
  };

  // The screen stays on while it counts down and scrolls. A browser lets go of the lock when the
  // page is hidden; it is asked for again when the page shows.
  let wake = null, asking = false;
  const holdScreen = () => {
    if (wake || asking || !navigator.wakeLock) return;
    asking = true;
    try {
      navigator.wakeLock.request("screen").then((lock) => {
        asking = false;
        if (!moving()) {
          lock.release().catch(() => {});
          return;
        }
        wake = lock;
        lock.addEventListener("release", () => { if (wake === lock) wake = null; });
      }, () => { asking = false; });
    } catch (err) {
      asking = false;  // no wake lock here
    }
  };
  const letScreenSleep = () => {
    const lock = wake;
    wake = null;
    if (lock) lock.release().catch(() => {});
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && moving()) holdScreen();
  });

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
  // Each frame scrolls to a whole pixel counted from where it began, Math.round(from + travelled),
  // never a pixel on from where the page is: a browser that rounds a scroll to its device pixels
  // (WebKit at a zoom other than 100 %, bug 281786) would lose every such step and stall.
  const run = () => {
    clearTimeout(scroll.timer);
    scroll.state = "running";
    scroll.from = scroll.at = window.scrollY;
    scroll.travelled = 0;
    scroll.last = 0;
    const loop = ++scroll.loop;
    const frame = (now) => {
      if (scroll.state !== "running" || loop !== scroll.loop) return;
      // Moved some other way (the scroll bar, a search in the page, a link): yours to read.
      if (Math.abs(window.scrollY - scroll.at) > 3) {
        pauseScroll();
        return;
      }
      if (scroll.last) {
        // A frame long in coming (a tab in the background) moves no further than a quarter second.
        scroll.travelled += (Math.min(now - scroll.last, 250) / 1000) * pace();
        const y = Math.round(scroll.from + scroll.travelled);
        if (y !== Math.round(scroll.at)) {
          window.scrollTo(0, y);
          scroll.at = window.scrollY;
        }
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
          pauseScroll("Paused at the end of the song");
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
    if (mine) fab.focus({ preventScroll: true });
  };

  $("scroll").addEventListener("click", () => {
    close();
    countdown();
    go.focus({ preventScroll: true });  // press it again, or Enter, to start at once
  });
  go.addEventListener("click", () => {
    if (scroll.state === "counting") run();
    else if (scroll.state === "running") pauseScroll();
    else countdown();
  });
  $("pill-end").addEventListener("click", endScroll);
  for (const b of document.querySelectorAll("[data-speed]")) {
    b.addEventListener("click", () => setSpeed(state.speed + Number(b.dataset.speed)));
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

  showScroll();
  render();
  if (hash.get("panel") === "1") open(panel);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
