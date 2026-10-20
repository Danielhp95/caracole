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
  // The same as one line of text, for a screen reader in the bar (``moved``: with the
  // transposition) and the settings' heading; without a key, Transpose and the capo.
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
  // In short, for the bar, between − and +: the key you play, and under it what it is
  // (["Em", "shapes · capo 2"], ["Em", "key · +1"]); the key it sounds in is the key line's.
  const keyShort = () => {
    const capo = capoNow();
    const moved = state.t ? [signed(state.t)] : [];
    const capoPart = capo ? ["capo " + capo] : sheetCapo ? ["no capo"] : [];
    if (!key) return ["Transpose", capoPart.concat(moved).join(" · ")];
    if (capo) return [keyName(shift()), ["shapes"].concat(capoPart, moved).join(" · ")];
    return [keyName(state.t + sheetCapo), ["key"].concat(capoPart, moved).join(" · ")];
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
  const bar = $("bar"), panel = $("panel"), card = $("card"), pill = $("pill"), go = $("go");
  const more = $("more"), sizes = $("sizes"), sizeButton = $("size");
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
    $("fs-now").textContent = state.fs + " px";
    $("smaller").setAttribute("aria-disabled", state.fs <= FS.min ? "true" : "false");
    $("bigger").setAttribute("aria-disabled", state.fs >= FS.max ? "true" : "false");

    const [main, sub] = keyShort();
    $("key-now").querySelector(".k").textContent = main;
    $("key-now").querySelector(".d").textContent = sub;
    $("key-full").textContent = keyLabel(true);
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
    if (!card.hidden) drawCard();  // an open card follows the key, the mode and the capo
    dock();
    save();
    hush();  // the lines moved under the page's scroll position, not by your hand
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
    fitting = requestAnimationFrame(() => {
      fit();
      place();
      dock();
    });
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
      b.addEventListener("click", () => openCard(String(i), b));
      strip.appendChild(b);
    }
  };

  // --- the chord card: shapes, and chords to play instead ----------------------------------------
  // ``el`` is the chord tapped (or the strip's button): the card is placed by it, from 900 px wide,
  // and the focus goes back to it. Another chord tapped while the card is open fills it in its place.
  const shown = { i: null, pick: -1, at: 0, el: null };
  const openCard = (i, el) => {
    if (!own.call(written, i)) return;
    shown.i = i;
    shown.pick = choice(i);
    shown.at = 0;
    shown.el = el || chordEls.find((c) => c.dataset.c === i) || null;
    for (const c of chordEls) c.classList.toggle("on", c.dataset.c === i);
    drawCard();  // filled before it takes the focus, so a screen reader hears the chord
    open(card, el || null);
    // On a phone, a chord tapped where the card now docks comes up above it (the dock's scroll padding),
    // lit, with the words of its line; one in sight already stays where it is.
    if (!wide.matches && shown.el && el) {
      (shown.el.closest(".l") || shown.el).scrollIntoView({ block: "nearest", behavior: calm.matches ? "auto" : "smooth" });
    }
  };
  // What the card is placed by: the chord, or the strip's button for it, which the strip draws anew.
  const anchor = () => {
    if (shown.el && shown.el.isConnected) return shown.el;
    const again = $("strip").children[Number(shown.i)];
    if (shown.el && again) return (shown.el = again);
    return chordEls.find((c) => c.dataset.c === shown.i) || $("sheet");
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
    place();
    dock();
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

  // --- the settings and a chord's card: beside the song, never over it ------------------------------
  // Neither is modal: nothing dims the song and the page stays within reach, so you see the chords
  // change as you transpose and tap one chord after another. On a phone each docks at the foot, above
  // the bar, the one opened last over the other, and the song scrolls under it; from 900 px wide
  // (viewer.css) the settings are a rail beside the song and the card a popover by its chord. Each
  // takes the focus as it opens (its heading); Escape closes the one on top, and the focus goes back
  // to what opened it when it was in there.
  const pageEl = document.querySelector(".page");
  const wide = window.matchMedia("(min-width: 900px)");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const layers = [];  // the open ones, the last on top: {el, opener}
  const topLayer = () => (layers.length ? layers[layers.length - 1].el : null);
  const inSight = (which) => !which.hidden && (wide.matches || topLayer() === which);
  // On a phone the page leaves room under the song for the one docked at its foot, so the end of
  // the song comes up above it, and the pill rides above it (--dock: its height).
  function dock() {
    const there = wide.matches ? null : topLayer();
    if (there) {
      doc.dataset.dock = there.id;
      doc.style.setProperty("--dock", there.offsetHeight + "px");
    } else if (doc.dataset.dock) {
      delete doc.dataset.dock;
      doc.style.removeProperty("--dock");
    }
  }
  // From 900 px wide the card is a popover by its chord: under it, or above it where the bar leaves
  // no room below, and across it, within the song's column. It is placed in the page, so it goes
  // with its chord as the page scrolls.
  function place() {
    if (card.hidden || !wide.matches) return;
    const a = anchor().getBoundingClientRect();
    const column = pageEl.getBoundingClientRect();
    const width = card.offsetWidth, height = card.offsetHeight, gap = 8;
    const floor = bar.hidden || bar.classList.contains("away") ? window.innerHeight : bar.getBoundingClientRect().top;
    let top = a.bottom + gap;
    if (top + height > floor - gap && a.top - gap - height >= gap) top = a.top - gap - height;
    const left = Math.max(column.left + gap, Math.min(a.left - 16, column.right - gap - width));
    card.style.setProperty("--pop-top", Math.round(top + window.scrollY) + "px");
    card.style.setProperty("--pop-left", Math.round(left + window.scrollX) + "px");
  }
  const restack = () => {
    const rail = doc.dataset.panel;
    for (const which of [panel, card]) which.classList.toggle("top", which === topLayer());
    more.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    if (panel.hidden) delete doc.dataset.panel;
    else doc.dataset.panel = "open";
    if (wide.matches && rail !== doc.dataset.panel) fit();  // the song's column narrows beside the rail
    place();
    dock();
  };
  const open = (which, opener) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at >= 0) layers.splice(at, 1);  // open already: on top again
    layers.push({ el: which, opener: opener instanceof Element && opener !== document.body ? opener : null });
    showSizes(false);
    which.hidden = false;
    slide(false);  // the bar it sits on
    restack();
    pauseScroll();
    which.querySelector("h2").focus({ preventScroll: true });
  };
  const close = (which) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at < 0) return;
    const opener = layers.splice(at, 1)[0].opener;
    const active = document.activeElement;
    const mine = !active || active === document.body || which.contains(active);
    which.hidden = true;
    if (which === card) for (const el of chordEls) el.classList.remove("on");
    restack();
    if (!mine) return;  // the focus is somewhere else of yours: it stays there
    let to = opener && opener.isConnected ? opener : null;
    if (!to && opener && which === card) to = anchor();  // the strip drew its button anew
    if (!to && topLayer()) to = topLayer().querySelector("h2");
    if (to) to.focus({ preventScroll: true });
  };
  const closeAll = () => {
    while (layers.length) close(topLayer());
  };
  for (const x of document.querySelectorAll("[data-close]")) x.addEventListener("click", () => close(x.closest(".sheet-ui")));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!sizes.hidden) {
      // The size box first, and the focus back to Aa when it was in there.
      const inside = $("size-box").contains(document.activeElement);
      showSizes(false);
      if (inside) sizeButton.focus({ preventScroll: true });
      return;
    }
    if (layers.length) close(topLayer());
  });
  // ⋯ closes the settings where you see them, and brings them up from under a card on a phone.
  more.addEventListener("click", () => (inSight(panel) ? close(panel) : open(panel, more)));

  // In the focus order the card comes after its chord, wherever it is on the page: Tab from its last
  // control goes on to what follows the chord, and Shift+Tab from its first back to the chord.
  const reachable = (el) => el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0
    && getComputedStyle(el).visibility === "visible";
  const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex]";
  card.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
    const from = anchor();
    if (!from || from === $("sheet") || card.contains(from)) return;
    const mine = Array.from(card.querySelectorAll(FOCUSABLE)).filter(reachable);
    const here = document.activeElement;
    const edge = e.shiftKey ? here === $("card-name") || here === mine[0] : here === mine[mine.length - 1];
    if (!edge) return;
    const to = e.shiftKey ? from : Array.from(document.querySelectorAll(FOCUSABLE)).find((el) => !card.contains(el)
      && !from.contains(el) && Boolean(from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) && reachable(el));
    if (!to) return;
    e.preventDefault();
    to.focus();
  });

  // --- Aa: the text size, in a box beside the song -------------------------------------------------
  // Not a dialog: the song stays in view and within reach, and the box closes on Escape, on a tap
  // anywhere else, or when the focus leaves it.
  function showSizes(on) {
    sizes.hidden = !on;
    sizeButton.setAttribute("aria-expanded", on ? "true" : "false");
  }
  sizeButton.addEventListener("click", () => showSizes(sizes.hidden));
  document.addEventListener("pointerdown", (e) => {
    if (!sizes.hidden && !(e.target instanceof Node && $("size-box").contains(e.target))) showSizes(false);
  }, true);
  $("size-box").addEventListener("focusout", (e) => {
    if (e.relatedTarget instanceof Node && !$("size-box").contains(e.relatedTarget)) showSizes(false);
  });

  const sheet = $("sheet");
  sheet.addEventListener("click", (e) => {
    const el = e.target.closest(".c");
    if (el) openCard(el.dataset.c, el);
  });
  sheet.addEventListener("keydown", (e) => {
    const el = e.target.closest(".c");
    if (el && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openCard(el.dataset.c, el);
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
  $("t-down").addEventListener("click", () => step(state.t - 1));
  $("t-up").addEventListener("click", () => step(state.t + 1));
  $("smaller").addEventListener("click", () => { state.fs = Math.max(FS.min, state.fs - FS.step); render(); });
  $("bigger").addEventListener("click", () => { state.fs = Math.min(FS.max, state.fs + FS.step); render(); });
  $("strip-toggle").addEventListener("click", () => { state.strip = !state.strip; render(); });
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, capo: null });
    render();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the guitar; pressed again, it starts at
  // once), running, or paused. While it is on, the pill takes the bar's place: − and +
  // change the speed as it runs, ❚❚ pauses and ▶ resumes (after a countdown again), × ends it. A
  // finger on the page, the wheel, a key that scrolls, a scroll by hand or a card opening pauses
  // it: the page is yours to read until you press ▶, which stays within reach with the card open.
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  // Pixels a second: a bigger text scrolls as much faster, so a speed keeps its pace through the song.
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start now", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    bar.hidden = scroll.state !== "off";  // the pill there
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;  // a docked card sits at the very foot, the pill over it
    if (!bar.hidden) slide(false);
    dock();
    pill.dataset.state = scroll.state;
    go.setAttribute("aria-label", LABELS[scroll.state] || "Pause");
    $("tick").textContent = scroll.state === "counting"
      ? String(Math.max(1, Math.ceil((scroll.ends - performance.now()) / 1000))) : "";
    if (said !== undefined) $("scroll-status").textContent = said;
  };
  const drawSpeed = () => {
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
    if (mine) $("scroll").focus({ preventScroll: true });
  };

  $("scroll").addEventListener("click", () => {
    closeAll();
    showSizes(false);
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

  // --- the bar: away as you read down the song, back when you want it -----------------------------
  // It slides away as you scroll down, and comes back as you scroll up, at the top and the end of
  // the song, on a tap on the page (not on one of its controls) or when the keyboard's focus comes to
  // it. Only your own scrolling moves it: none before you first touch the page (the browser, or the
  // songbook, putting you back where you were), and none just after a change of key or text size,
  // when the browser keeps the line you were reading in place by scrolling. It stays while the size
  // box or a sheet is open, and while one of its controls has the keyboard's focus, which would
  // otherwise go out of sight.
  const reveal = { y: window.scrollY, quiet: 0, touched: false };
  function hush() {
    if (doc.dataset.ready === "1") reveal.quiet = performance.now() + 400;
  }
  function slide(away) {
    bar.classList.toggle("away", away);
    if (away) showSizes(false);
  }
  const keyboardIn = (el) => {
    try {
      return Boolean(el.querySelector(":focus-visible"));
    } catch (err) {  // a browser without :focus-visible: any focus counts
      return el.contains(document.activeElement);
    }
  };
  for (const kind of ["touchstart", "pointerdown", "wheel", "keydown"]) {
    window.addEventListener(kind, () => { reveal.touched = true; }, { passive: true, capture: true });
  }
  window.addEventListener("scroll", () => {
    const y = window.scrollY, dy = y - reveal.y;
    if (y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2) {
      slide(false);
      reveal.y = y;
      return;
    }
    if (!reveal.touched || performance.now() < reveal.quiet || !sizes.hidden || !panel.hidden || !card.hidden
        || keyboardIn(bar)) {
      reveal.y = y;
      return;
    }
    if (Math.abs(dy) < 8) return;  // a few pixels add up before they count
    slide(dy > 0);
    reveal.y = y;
  }, { passive: true });
  document.addEventListener("click", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (target && !target.closest("#bar, #pill, .sheet-ui, a, button, summary, input, [role=button]")) slide(false);
  });
  bar.addEventListener("focusin", () => slide(false));

  // Nothing to transpose and no other setting for a sheet without chords: Aa and ▶ alone.
  $("keys").hidden = count === 0;
  more.hidden = count === 0;
  showScroll();
  render();
  if (hash.get("panel") === "1") open(panel, null);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
