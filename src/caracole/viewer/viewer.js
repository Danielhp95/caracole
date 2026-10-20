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
  const FS = { min: 13, max: 30, step: 2 };

  // --- the state: where the song is played, kept per page ------------------------------------
  // capo: the fret chosen among the hints (0 for no capo), or null to play the sheet's shapes.
  const state = { t: Number(data.transpose) || 0, mode: null, alt: {}, capo: null, fs: 18, strip: false };
  const store = "caracole-viewer:" + location.pathname;
  // Chords chosen instead of others are kept for the sheet's chords by index: they only hold
  // while the sheet's chords do.
  const sheetChords = Object.keys(written).map((i) => written[i]).join("|");
  const validMode = (m) => Boolean(key) && data.modes.indexOf(m) >= 0;
  const clampT = (t) => Math.max(-11, Math.min(11, Math.round(Number(t) || 0)));
  const fretOf = (v) => (v === null || v === undefined || v === "" || !(Number(v) >= 0) ? null
    : Math.round(Number(v)));
  try {
    const saved = JSON.parse(localStorage.getItem(store) || "null");
    if (saved && typeof saved === "object") {
      if (saved.base === data.transpose) state.t = clampT(saved.t);  // a new [transpose] starts afresh
      if (validMode(saved.mode)) state.mode = saved.mode;
      if (saved.alt && typeof saved.alt === "object" && saved.chords === sheetChords) state.alt = saved.alt;
      if (Number(saved.fs) >= FS.min && Number(saved.fs) <= FS.max) state.fs = Number(saved.fs);
      state.strip = saved.strip === true;
      state.capo = fretOf(saved.capo);
    }
  } catch (err) { /* no storage: the page still works */ }
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has("t")) state.t = clampT(hash.get("t"));
  if (validMode(hash.get("mode"))) state.mode = hash.get("mode");
  if (hash.has("capo")) state.capo = fretOf(hash.get("capo"));
  const save = () => {
    try {
      localStorage.setItem(store, JSON.stringify(Object.assign({ base: data.transpose, chords: sheetChords }, state)));
    } catch (err) { /* private mode, or a server's sandbox */ }
    // The address keeps where the song is played too, read back above: without storage (a
    // server's sandbox), a reload and Back still keep it. Replaced, so Back isn't a step per tap.
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const keep = (name, value, kept) => (kept ? params.set(name, String(value)) : params.delete(name));
      keep("t", state.t, state.t !== (Number(data.transpose) || 0));
      keep("mode", state.mode, state.mode !== null);
      keep("capo", state.capo, state.capo !== null);
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
  // The chords are named for the shapes played: with another capo, as many semitones off.
  const shift = () => state.t - (state.capo === null ? 0 : state.capo - sheetCapo);
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
  const fab = $("fab"), panel = $("panel"), card = $("card"), scrim = $("scrim");
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
    // A capo no longer on offer (after a transposition or a mode change) goes before the
    // chords are named: they are named for the shapes played with it.
    if (state.capo !== null && !capoHints().some((h) => h[0] === state.capo)) state.capo = null;
    for (const el of chordEls) {
      const i = el.dataset.c;
      el.textContent = label(i, current(i));
      el.classList.toggle("changed", choice(i) >= 0);
    }
    doc.style.setProperty("--fs", state.fs + "px");

    const shapes = state.capo === null ? null : capoHints().find((h) => h[0] === state.capo);
    fab.textContent = key ? "Key " + keyName(state.t) + (state.t ? " · " + signed(state.t) : "")
      : state.t ? "Transpose " + signed(state.t) : "Transpose";
    $("key-now").textContent = key ? keyName(state.t) : "";
    $("panel-title").firstChild.textContent = key ? "Key " : "Transpose";
    const facts = [];
    if (key) facts.push(["Key ", keyName(state.t), state.t ? " (" + signed(state.t) + ")" : "", key.from]);
    if (shapes && shapes[0]) facts.push(["Capo ", String(shapes[0]), ", " + shapes[1] + " shapes", ""]);
    else if (shapes) facts.push(["", "No capo", ", " + shapes[1] + " shapes", ""]);
    else if (sheetCapo) facts.push(["Capo ", String(sheetCapo), "", ""]);
    const box = $("facts");
    box.textContent = "";
    facts.forEach((f, n) => {
      if (n) box.appendChild(document.createTextNode(" · "));
      box.appendChild(document.createTextNode(f[0]));
      const b = document.createElement("b");
      b.textContent = f[1];
      box.appendChild(b);
      if (f[2]) box.appendChild(document.createTextNode(f[2]));
      if (f[3]) {
        const from = document.createElement("span");
        from.className = "from";
        from.textContent = " " + f[3];
        box.appendChild(from);
      }
    });

    $("shift").textContent = signed(state.t);
    $("shift-hint").textContent = data.transpose
      ? "Your PDF is transposed " + signed(data.transpose) + "; Reset goes back there." : "";
    const hints = capoHints();
    $("capo-row").hidden = !hints.length;
    const capoBox = $("capo");
    capoBox.textContent = "";
    for (const [fret, shapesKey] of hints) {
      capoBox.appendChild(button(fret ? "Capo " + fret : "No capo", state.capo === fret, () => {
        state.capo = state.capo === fret ? null : fret;
        render();
      }, shapesKey + " shapes"));
    }
    $("capo-hint").textContent = hints.length
      ? (state.capo === null
        ? (sheetCapo ? "Easier shapes with the capo elsewhere: tap one to show them."
          : "Easier shapes with a capo: tap one to show them.")
        : "The chords show the shapes to play " + (state.capo ? "with the capo on." : "with no capo."))
      : "";

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
      $("mode-hint").textContent = keyName(state.t) + ": " + info[1] + "." +
        (asWritten() ? "" : " Each chord moves to the same degree of the new scale.");
    }

    $("strip-toggle").setAttribute("aria-pressed", state.strip ? "true" : "false");
    $("strip-toggle").textContent = state.strip ? "Hide" : "Show all";
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
    const capoNote = state.capo === null ? "" : state.capo ? " With the capo on fret " + state.capo + "." : " With no capo.";
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
    fab.setAttribute("aria-expanded", which === panel ? "true" : "false");
    stopScroll();
    which.querySelector("h2").focus({ preventScroll: true });
  };
  const close = () => {
    const wasOpen = !(panel.hidden && card.hidden);
    panel.hidden = true;
    card.hidden = true;
    scrim.hidden = true;
    pageEl.inert = false;
    fab.inert = false;
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
  $("reset-t").addEventListener("click", () => { state.capo = null; step(data.transpose); });
  $("smaller").addEventListener("click", () => { state.fs = Math.max(FS.min, state.fs - FS.step); render(); });
  $("bigger").addEventListener("click", () => { state.fs = Math.min(FS.max, state.fs + FS.step); render(); });
  $("strip-toggle").addEventListener("click", () => { state.strip = !state.strip; render(); });
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, capo: null });
    render();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  let scrolling = false, last = 0, carry = 0, wake = null;
  const scrollButton = $("scroll");
  const frame = (now) => {
    if (!scrolling) return;
    if (last) {
      carry += ((now - last) / 1000) * Number($("speed").value) * 9;
      const px = Math.floor(carry);
      if (px > 0) {
        window.scrollBy(0, px);
        carry -= px;
      }
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) stopScroll();
    }
    last = now;
    if (scrolling) requestAnimationFrame(frame);
  };
  const startScroll = () => {
    scrolling = true;
    last = 0;
    carry = 0;
    scrollButton.setAttribute("aria-pressed", "true");
    scrollButton.textContent = "Stop";
    try {
      if (navigator.wakeLock) navigator.wakeLock.request("screen").then((l) => { wake = l; }, () => {});
    } catch (err) { /* no wake lock here */ }
    close();
    requestAnimationFrame(frame);
  };
  function stopScroll() {
    if (!scrolling) return;
    scrolling = false;
    scrollButton.setAttribute("aria-pressed", "false");
    scrollButton.textContent = "Start";
    if (wake) wake.release().catch(() => {});
    wake = null;
  }
  scrollButton.addEventListener("click", () => (scrolling ? stopScroll() : startScroll()));
  window.addEventListener("touchstart", (e) => {
    if (scrolling && !e.target.closest(".fab")) stopScroll();
  }, { passive: true });

  fab.hidden = count === 0;  // nothing to transpose
  render();
  if (hash.get("panel") === "1") open(panel);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
