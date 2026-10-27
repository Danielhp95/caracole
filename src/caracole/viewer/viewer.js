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
  // The chords of a chord legend's lines ("Am x02210", page.py's "legend"): each names the shape beside it, so it
  // stays as the sheet writes it, whatever the version (version.py's apply_version leaves them so too).
  const legendEls = new Set(chordEls.filter((el) => el.closest(".legend")));
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
  // The Harmony panel's tempo, in beats a minute: a chord a bar of four.
  const BPM = { min: 40, max: 200, start: 80, step: 5 };
  // The capo goes on any fret up to the 11th (past it the shapes come round again), or the sheet's.
  const CAPO_MAX = Math.max(11, Number(data.capoSheet) || 0);
  // A chord heard (strum.js), as loud as this: the setting's names and caracoleSound's volumes; each drawn as a
  // speaker (viewer.css .icons), crossed out, then with one, two and three waves.
  const VOLUMES = [["Off", 0], ["Soft", 0.3], ["Medium", 0.6], ["Loud", 1]];
  const SPEAKER = "M11 5 6 9H2v6h4l5 4z";
  const WAVES = [["m22 9-6 6M16 9l6 6"], ["M15.5 8.5a5 5 0 0 1 0 7"], ["M15 9.5a3.5 3.5 0 0 1 0 5", "M18 7a7 7 0 0 1 0 10"],
    ["M14.5 10a2.5 2.5 0 0 1 0 4", "M17 8a5.5 5.5 0 0 1 0 8", "M19.5 5.5a9.5 9.5 0 0 1 0 13"]];
  const VOL = 2;
  // Whether caracole serve sent this page, so that its controls may link to the server's own pages: Export PDF
  // (/export), a version made the one or kept (/versions), a Guitar Pro file drawn in the browser (/guitar). From a
  // file they show the command to run, or the file itself, instead; and so in caracole's Android app, whose offline
  // copy of the library (androidx.webkit's WebViewAssetLoader, always at appassets.androidplatform.net) reads like
  // a file: no server answers there. The one place the page tells the two apart.
  const served = location.protocol !== "file:" && location.hostname !== "appassets.androidplatform.net";

  // --- the state: where the song is played, kept per page ------------------------------------
  // capo: the fret the capo is on (0 for none), or null for the sheet's own. It stays there
  // through a transposition, as on a guitar: the shapes move instead.
  // nm: the chord names as numerals beside them ("both") or in their place ("numerals"), null for the
  // chords alone; roles: the numerals in their families' colours; necks: the rail of necks shown, on a screen
  // wide enough for it; py: each Chinese character's reading over it (pinyin), on a sheet with Chinese.
  // inst: the instrument the chords are drawn and heard for (data.instruments' id), the player's: kept once for every
  // page, as the rail of necks is.
  const state = { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null, fs: FS.start, strip: false,
    speed: SPEED.start, nm: null, roles: true, kn: "scale", bpm: BPM.start, vol: VOL, necks: true, py: false,
    inst: "guitar" };
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
  const nmOf = (v) => (v === "both" || v === "numerals" ? v : null);
  const volOf = (v) => (/^[0-3]$/.test(String(v)) ? Number(v) : null);
  // The address spells the chords swapped as alt=<mode>.<i>.<root>.<suffix>.<bass>,… (suffix
  // URL-encoded, bass empty for none) and the shapes chosen as at=<i>.<n>,….
  const swapsOf = (text) => {
    const out = {};
    for (const part of String(text || "").split(",")) {
      const [mode, i, root, suffix, bass] = part.split(".");
      if (!validMode(mode) || !/^\d+$/.test(i || "") || !/^\d+$/.test(root || "") || !/^(\d+)?$/.test(bass || "")) continue;
      let text;
      try { text = decodeURIComponent(suffix || ""); } catch (err) { continue; }
      out[mode] = out[mode] || {};
      out[mode][i] = [Number(root), text, bass === "" || bass === undefined ? null : Number(bass)];
    }
    return out;
  };
  const swapsText = (alt) => Object.keys(alt).map((mode) => Object.keys(alt[mode]).filter((i) => Array.isArray(alt[mode][i]))
    .map((i) => [mode, i, alt[mode][i][0], encodeURIComponent(alt[mode][i][1]).replace(/\./g, "%2E"),
      alt[mode][i][2] === null ? "" : alt[mode][i][2]].join("."))).reduce((all, one) => all.concat(one), []).join(",");
  const positionsOf = (text) => {
    const out = {};
    for (const part of String(text || "").split(",")) {
      const [i, n] = part.split(".");
      if (/^\d+$/.test(i || "") && /^\d+$/.test(n || "") && Number(n) > 0) out[i] = Number(n);
    }
    return out;
  };
  // The shapes kept chosen, each with the chord it was chosen for (atSigns): read back once the chords
  // can be named (below setAt), as only a chord still named so gets its shape back.
  let keptAt = null;
  // Where an address (or the song's own version) plays the song: what it names of it.
  const adopt = (params) => {
    if (params.has("alt")) state.alt = swapsOf(params.get("alt"));
    if (params.has("at")) {
      state.at = positionsOf(params.get("at"));
      keptAt = null;  // the address says which
    }
    if (params.has("t")) state.t = clampT(params.get("t"));
    if (validMode(params.get("mode"))) state.mode = params.get("mode");
    if (params.has("capo")) state.capo = fretOf(params.get("capo"));
    if (params.has("nm")) state.nm = nmOf(params.get("nm"));
  };
  // The song's own version (overrides.toml's [version], "Make this my version"), which its PDF is in: the page
  // starts there when its address names no version of its own, and Reset everything goes back there.
  const start = new URLSearchParams(data.start || "");
  const hash = new URLSearchParams(location.hash.slice(1));
  if (data.start && !["t", "mode", "capo", "alt", "at"].some((name) => hash.has(name))) adopt(start);
  // What the browser kept was for this song as its PDF then was: a new [transpose] or version starts afresh.
  const keptFor = data.start || data.transpose;
  try {
    const saved = JSON.parse(localStorage.getItem(store) || "null");
    if (saved && typeof saved === "object") {
      const same = saved.base === keptFor;
      if (same) state.t = clampT(saved.t);
      if (same || !data.start) {  // in place of the version's: the sheet's own mode and shapes too
        state.mode = validMode(saved.mode) ? saved.mode : null;
        if (saved.alt && typeof saved.alt === "object" && saved.chords === sheetChords) state.alt = saved.alt;
        if (saved.at && typeof saved.at === "object" && saved.atSigns && typeof saved.atSigns === "object"
          && saved.chords === sheetChords) {
          state.at = {};
          keptAt = { at: saved.at, signs: saved.atSigns };
        }
        state.capo = fretOf(saved.capo);
        state.nm = nmOf(saved.nm);
      }
      if (saved.roles === false) state.roles = false;
      if (saved.kn === "penta") state.kn = "penta";
      if (Number(saved.bpm) >= BPM.min && Number(saved.bpm) <= BPM.max) state.bpm = Math.round(Number(saved.bpm));
      if (sizeOf(saved.fs) !== null) state.fs = sizeOf(saved.fs);
      if (speedOf(saved.speed) !== null) state.speed = speedOf(saved.speed);
      if (volOf(saved.vol) !== null) state.vol = volOf(saved.vol);
      state.strip = saved.strip === true;
    }
  } catch (err) { /* no storage: the page still works */ }
  // The rail of necks is the screen's choice, not a song's: kept once for every sheet, songbook and harmonica tab's
  // page (a name no page's own settings have, as theirs end in its path: overlay.js's), and in the address too, where
  // there is no storage.
  const overlay = window.caracoleOverlay || null;
  const NECKS = overlay ? overlay.NECKS : "caracole-viewer-necks";
  try {
    if (localStorage.getItem(NECKS) === "hidden") state.necks = false;
  } catch (err) { /* no storage: shown, unless the address says otherwise */ }
  if (hash.get("necks") === "0") state.necks = false;
  const keepNecks = () => {
    try {
      localStorage.setItem(NECKS, state.necks ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // So is pinyin over the Chinese (the settings' Pinyin): the reader's, kept once for every page, and in the
  // address while it is on (py=1, as it starts off).
  const PINYIN = "caracole-viewer-pinyin";
  try {
    if (localStorage.getItem(PINYIN) === "shown") state.py = true;
  } catch (err) { /* no storage: off, unless the address says otherwise */ }
  if (hash.get("py") === "1") state.py = true;
  const keepPinyin = () => {
    try {
      localStorage.setItem(PINYIN, state.py ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // And so is the instrument (the settings' Instrument menu): the player's, kept once for every page, and in the address
  // (inst=ukulele) while it is another than the guitar, or always for a song whose own version names one (a songbook's
  // entry played on another instrument): that song starts on it when its address names no version, as it starts in
  // that version, whatever instrument the page before it was on.
  const INSTRUMENT = "caracole-viewer-instrument";
  const kit = window.caracoleInstruments || null;
  const INSTRUMENTS = Array.isArray(data.instruments) && data.instruments.length ? data.instruments
    : [{ id: "guitar", name: "Guitar", kind: "strings", capo: true, shapes: "", tuning: [40, 45, 50, 55, 59, 64] }];
  const instOf = (id) => INSTRUMENTS.find((i) => i && i.id === id) || null;
  // The viewer draws strings and keys itself; any other kind once a script registers it (instruments.js).
  const drawn = (i) => Boolean(i) && (i.kind === "strings" || i.kind === "keys" || Boolean(kit && kit.registered(i.id)));
  const startInst = drawn(instOf(start.get("inst"))) ? start.get("inst") : null;
  try {
    const mine = localStorage.getItem(INSTRUMENT);
    if (drawn(instOf(mine))) state.inst = mine;
  } catch (err) { /* no storage: the guitar, unless the address says otherwise */ }
  if (drawn(instOf(hash.get("inst")))) state.inst = hash.get("inst");
  if (startInst && data.start && !["t", "mode", "capo", "alt", "at"].some((name) => hash.has(name))) state.inst = startInst;
  const keepInst = () => {
    try {
      localStorage.setItem(INSTRUMENT, state.inst);
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  adopt(hash);
  if (sizeOf(hash.get("fs")) !== null) state.fs = sizeOf(hash.get("fs"));
  if (speedOf(hash.get("speed")) !== null) state.speed = speedOf(hash.get("speed"));
  if (volOf(hash.get("vol")) !== null) state.vol = volOf(hash.get("vol"));
  const save = () => {
    try {
      // Each shape chosen with the chord it was chosen for, so that only that chord gets it back.
      const atSigns = {};
      for (const i of Object.keys(state.at)) if (own.call(atSeen, i)) atSigns[i] = atSeen[i];
      localStorage.setItem(store, JSON.stringify(Object.assign({ base: keptFor, chords: sheetChords }, state,
        { atSigns })));
    } catch (err) { /* private mode, or a server's sandbox */ }
    // The address keeps where the song is played too, and the text size and the scroll speed,
    // read back above: without storage (a server's sandbox), a reload and Back still keep them.
    // Replaced, so Back isn't a step per tap.
    try {
      const params = new URLSearchParams(location.hash.slice(1));
      const keep = (name, value, kept) => (kept ? params.set(name, String(value)) : params.delete(name));
      // With a version of its own, t always: an address naming none would start in that version again.
      keep("t", state.t, Boolean(data.start) || state.t !== (Number(data.transpose) || 0));
      keep("mode", state.mode, state.mode !== null);
      keep("capo", state.capo, state.capo !== null);
      keep("nm", state.nm, state.nm !== null);
      keep("alt", swapsText(state.alt), swapsText(state.alt) !== "");
      keep("at", Object.keys(state.at).map((i) => i + "." + state.at[i]).join(","), Object.keys(state.at).length > 0);
      keep("fs", state.fs, state.fs !== FS.start);
      keep("speed", state.speed, state.speed !== SPEED.start);
      keep("vol", state.vol, state.vol !== VOL);
      keep("necks", "0", !state.necks);
      keep("py", "1", state.py);
      keep("inst", state.inst, state.inst !== "guitar" || Boolean(startInst));
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(null, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
    exportLink();
    versionLinks();
  };

  // Export PDF of this version, named at its right ("D Dorian, capo 2"): served, a link to the server's export page
  // for this very address, followed in this tab (the sandbox has no popups); from a file, a row that unfolds the
  // command that makes it, with Copy.
  const exportLink = () => {
    const link = $("export");
    const cmd = $("export-cmd");
    if (!link || !cmd) return;
    const words = versionWords().filter(Boolean).join(", ");
    for (const v of $("export-row").querySelectorAll(".export-v")) v.textContent = words;
    const version = new URLSearchParams(location.hash.slice(1));
    if (!served) {
      const quoted = (text) => "'" + text.replace(/'/g, "'\\''") + "'";
      for (const name of ["fs", "speed", "vol", "necks", "py"]) version.delete(name);
      cmd.textContent = "caracole render --song " + songNamed()
        + " --version " + quoted(version.toString().replace(/%2C/g, ","));
      link.hidden = true;
      $("export-fold").hidden = false;
      cmd.hidden = false;
      $("export-copy").hidden = false;
      $("export-hint").textContent = "Run this where caracole is installed; the PDF is written beside the sheet. "
        + "With --mine, it is your version instead: the song's own PDF, its viewer and its songbooks.";
      return;
    }
    const query = new URLSearchParams();
    query.set("sheet", sheetPath());
    version.forEach((value, name) => query.append(name, value));
    link.setAttribute("href", "/export?" + query.toString());
  };
  // The page's path in the library, as caracole serve serves it ("Artist/Title/sheet.html"); its file name.
  const sheetPath = () => decodeURIComponent(location.pathname.slice(1));
  const pageName = () => {
    try {
      return decodeURIComponent(location.pathname.split("/").pop());
    } catch (err) { return ""; }
  };
  // The song's name as a command names it, quoted for the shell: "Artist - Title".
  const songNamed = () => {
    const title = (document.querySelector("h1") || {}).textContent || "";
    const artist = (document.querySelector(".artist") || {}).textContent || "";
    return "'" + (artist ? artist + " - " + title : title).replace(/'/g, "'\\''") + "'";
  };
  if ($("export-fold")) {
    $("export-fold").addEventListener("click", () => {
      const open = $("export-file").hidden;
      $("export-file").hidden = !open;
      $("export-fold").setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  if ($("export-copy")) {
    $("export-copy").addEventListener("click", () => {
      const done = () => { $("export-copy").textContent = "Copied"; };
      try {
        navigator.clipboard.writeText($("export-cmd").textContent).then(done, () => {});
      } catch (err) { /* no clipboard: the command is selectable */ }
    });
  }

  // The song's Guitar Pro files (``guitar``: their names, beside the sheet), in the settings, a row each, ↗: served,
  // each opens caracole serve's Guitar Pro page for it (/guitar?file=…, "in the browser"), in this tab, as Export
  // does; from a file, each is the file itself, a download saved under the song's name (``guitarDownload``: "Eagles -
  // Hotel California (2).gp5").
  (() => {
    const row = $("guitar-row");
    const box = $("guitar-links");
    const names = Array.isArray(data.guitar) ? data.guitar.filter((n) => typeof n === "string" && n) : [];
    if (!row || !box || !names.length) return;
    const saved = Array.isArray(data.guitarDownload) && data.guitarDownload.length === names.length
      ? data.guitarDownload : [];
    const folder = served ? sheetPath().split("/").slice(0, -1).join("/") : "";
    const OUT = ["M7 17 17 7", "M8 7h9v9"];  // ↗, a place away from the page
    names.forEach((name, i) => {
      const a = box.appendChild(document.createElement("a"));
      a.className = "goto";
      const words = a.appendChild(document.createElement("span"));
      words.className = "goto-lab";
      words.textContent = "Guitar Pro tab" + (names.length > 1 ? " " + (i + 1) : "");
      const where = a.appendChild(document.createElement("span"));
      where.className = "goto-v";
      where.textContent = served ? "in the browser" : "download";
      const icon = where.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "svg"));
      icon.setAttribute("viewBox", "0 0 24 24");
      icon.setAttribute("aria-hidden", "true");
      for (const d of OUT) icon.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "path")).setAttribute("d", d);
      a.setAttribute("href", served ? "/guitar?file=" + encodeURIComponent(folder + "/" + name)
        : encodeURIComponent(name));
      if (!served && typeof saved[i] === "string" && saved[i]) a.setAttribute("download", saved[i]);
    });
    row.hidden = false;
  })();

  // --- naming chords -------------------------------------------------------------------------
  const modeNow = () => (key ? state.mode || key.mode : "");
  const asWritten = () => !state.mode || (key && state.mode === key.mode);
  const sheetCapo = Number(data.capoSheet) || 0;
  const inst = () => (drawn(instOf(state.inst)) ? instOf(state.inst) : instOf("guitar") || INSTRUMENTS[0]);
  // An instrument with no capo (the piano) plays the chords as they sound: the capo folded in, the chords named a
  // capo's frets up, the key the one the song sounds in. The capo set stays, for the guitar.
  const takesCapo = () => inst().capo !== false;
  const capoNow = () => (!takesCapo() ? 0 : state.capo === null ? sheetCapo : state.capo);
  const saysNoCapo = () => takesCapo() && sheetCapo > 0;  // "no capo", on an instrument that could take the sheet's
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
  // A chord named ``s`` semitones from the sheet's key (by default, where the chords are named: shift()): as written
  // when it is the chord as written, unmoved.
  const label = (i, rep, s = shift()) => {
    if (!rep) return written[i];
    if (s === 0 && asWritten() && rep === data.chords[i]) return written[i];
    return nameOf(rep, s);
  };
  // The frets where a guitar's open shapes play the key (page.py's ``capo``): on an instrument with shapes of its own
  // (a ukulele), its Easy keys instead.
  const capoHints = () => (key && !inst().shapes ? data.capo[modeNow()][mod12(state.t)] : []);
  // Where the song is played, as Cifra Club's key line says it: with a capo, the key of the
  // shapes, the capo and the key the song sounds in ("Em shapes · capo 2 · sounds F#m"), as
  // "Key Em" alone would read as the song's key; with none, the key. Each part is
  // [before, in bold, after, where the key came from]; ``moved`` says the transposition.
  // page.py writes the same line for the sheet as written.
  const keyLine = (moved) => {
    const capo = capoNow();
    if (!key) return capo ? [["Capo ", String(capo), "", ""]] : saysNoCapo() ? [["No capo", "", "", ""]] : [];
    const sounds = keyName(state.t + sheetCapo);
    if (!capo) return [["Key ", sounds, moved, key.from]].concat(saysNoCapo() ? [["no capo", "", "", ""]] : []);
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
        .concat(capo ? ["capo " + capo] : saysNoCapo() ? ["no capo"] : []).join(" · ");
    }
    return keyLine("").filter((part) => part[1] || !part[3]).map((part) => part[0] + part[1] + part[2])
      .concat(shown ? [shown] : []).join(" · ");
  };
  // In short, for the bar, between − and +: the key you play, and under it what it is, the capo
  // and the transposition (["Em", "shapes", ["capo 2"]], ["Em", "key", ["+1"]]); the key it sounds
  // in is the key line's.
  const keyShort = () => {
    const capo = capoNow();
    const rest = (capo ? ["capo " + capo] : saysNoCapo() ? ["no capo"] : []).concat(state.t ? [signed(state.t)] : []);
    if (!key) return ["Transpose", "", rest];
    if (capo) return [keyName(shift()), "shapes", rest];
    return [keyName(state.t + sheetCapo), "key", rest];
  };
  // What is set, in words, as version.py's played_label names a version: the key of the shapes played, in the mode
  // played ("D Dorian"; on an instrument with no capo, the key the song sounds in, the capo folded in), or how far a
  // sheet with no key moved ("As written", "Transposed +2"); and the capo, where there is one ("capo 2"), else "".
  const versionWords = () => {
    const s = shift(), moved = takesCapo() ? state.t : s;
    const words = key ? names(s)[mod12(key.tonic + s)] + " " + (MODES[modeNow()] || [modeNow()])[0]
      : moved ? "Transposed " + signed(moved) : "As written";
    return [words, capoNow() ? "capo " + capoNow() : ""];
  };
  // The key in short and the line under it, fitted to the room between − and +. The key a little
  // smaller where it is too long ("Ab mixolydian" at 360 px), down to three quarters of its size, then
  // cut short. The line whole where there is room ("shapes · capo 2 · +1"); on a narrow screen the capo
  // and the transposition alone ("capo 2 · +1"); on the narrowest, each on a line of its own, "capo 2"
  // over "+1", so that neither is cut off. Fitted again when the bar comes back into view or the window
  // changes. Measured to the fraction of a pixel, which scrollWidth rounds away: a line 0.4 px too wide
  // would end in an ellipsis.
  let keyUnder = ["", []];
  const tooWide = (el) => {
    const text = document.createRange();
    text.selectNodeContents(el);
    return text.getBoundingClientRect().width > el.getBoundingClientRect().width;
  };
  const fitKey = () => {
    const now = $("key-now"), main = now.querySelector(".k"), line = now.querySelector(".d");
    main.style.fontSize = "";
    if (tooWide(main)) {
      const full = parseFloat(getComputedStyle(main).fontSize);
      for (let size = full - 0.5; size >= full * 0.75 && tooWide(main); size -= 0.5) main.style.fontSize = size + "px";
    }
    const [what, rest] = keyUnder;
    line.classList.remove("stack");
    line.textContent = (what ? [what] : []).concat(rest).join(" · ");
    if (what && rest.length && tooWide(line)) line.textContent = rest.join(" · ");
    if (rest.length > 1 && tooWide(line)) {
      line.textContent = "";
      for (const part of rest) {
        const one = document.createElement("span");
        one.textContent = part;
        line.append(one);
      }
      line.classList.add("stack");
    }
  };

  // --- numerals: what each chord is in the key ---------------------------------------------------
  // page.py's tables (harmony_tables.py), by mode: a chord's reading is its index, or the one ``places``
  // names for its place on the sheet (its index among the sheet's chords, k); a chord chosen instead of
  // another has its numeral and its role alone. A text that names notes names them in the key shown.
  const numbered = () => Boolean(key) && Boolean(data.numerals) && state.nm !== null;
  const table = (name) => (data[name] && data[name][modeNow()]) || null;
  const textOf = (text) => {
    if (typeof text === "string") return text;
    if (Array.isArray(text)) {
      const n = names(shift());
      return text.map((part) => (typeof part === "number" ? n[mod12(part + shift())] : part)).join("");
    }
    return text && Array.isArray(text.by) ? String(text.by[mod12(shift())] || "") : "";
  };
  // {text, parts, role, line}: role is the family's first letter (h, a, p) or the relation's (b, s, l, o).
  // ``j``: the chord among its alternatives (-1: the chord itself), by default the one played.
  const reading = (i, k, j = choice(i)) => {
    if (!key || !data.numerals) return null;
    if (j >= 0) {
      const code = ((table("altNumerals") || [])[i] || [])[j];
      return code ? { text: code.slice(1), parts: null, role: code[0], line: null } : null;
    }
    const places = table("places") || {};
    const r = k !== undefined && k !== null && own.call(places, String(k)) ? places[String(k)] : Number(i);
    const n = (table("numerals") || [])[r];
    if (!n) return null;
    const family = table("families")[r];
    return { text: n[0], parts: n, role: family ? family[0] : String(table("relations")[r] || "o")[0],
      line: table("explains")[r] };
  };
  // A numeral as the sheet shows it: its degree and quality, then its extension and what follows a slash,
  // each in a class of its own; in its family's colour (r-h, r-a, r-p), or marked from outside the key (out).
  const numeralEl = (found) => {
    const span = document.createElement("span");
    span.className = "nm r-" + found.role + ("hap".indexOf(found.role) < 0 ? " out" : "");
    const parts = found.parts;
    if (!parts) {
      span.textContent = found.text;
      return span;
    }
    const head = parts[1] + parts[2] + parts[3];
    span.appendChild(document.createTextNode(head));
    const rest = [[parts[4], "nm-x"], [found.text.slice(head.length + parts[4].length), "nm-b"]];
    for (const [text, cls] of rest) {
      if (!text) continue;
      const part = span.appendChild(document.createElement("span"));
      part.className = cls;
      part.textContent = text;
    }
    return span;
  };
  // A chord on the sheet, as the chord names setting shows it: its name, its name and numeral, or its
  // numeral (a chord with none, N.C., as written). A screen reader hears both.
  const drawChord = (el, k) => {
    const i = el.dataset.c;
    if (legendEls.has(el)) {
      el.textContent = written[i];
      return;
    }
    const name = label(i, current(i));
    const found = numbered() ? reading(i, k) : null;
    if (!found) {
      el.textContent = name;
      el.removeAttribute("aria-label");
      return;
    }
    el.textContent = "";
    if (state.nm === "both") el.appendChild(document.createTextNode(name));
    el.appendChild(numeralEl(found));
    el.setAttribute("aria-label", name + ", " + found.text);
  };

  // --- chord diagrams --------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(node);
    return node;
  };
  // The strum's loudness ``v`` (VOLUMES) as a speaker and its waves, for its button.
  const speaker = (v) => {
    const icon = svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
    for (const d of [SPEAKER].concat(WAVES[v])) svg("path", { d }, icon);
    return icon;
  };
  // A chord's shapes on the instrument played (``it``: another, the overlay's guitar). On the guitar: those the sheet gives that very chord first (page.py's
  // "shapes", "mine" of them: the first so many), then chords-db's; the note goes with chords-db's. On a ukulele: its
  // table's for the quality the guitar files the chord under (data.voicings[shapes + quality], the instrument's
  // ``near`` naming the one it shows instead, read ``offset`` roots on: the baritone's), a slash chord's bass left
  // out. On the piano: its positions (data.voicings["piano:<suffix>|<bass interval>"]): root position and two
  // inversions, the bass first. An instrument the page doesn't draw itself has none: its script draws the chord.
  const pianoKey = (rep) => "piano:" + rep[1] + "|" + (rep[2] === null ? "" : mod12(rep[2] - rep[0]));
  const INVERSIONS = ["Root position", "1st inversion", "2nd inversion"];
  const qualityName = (q) => (own.call(data.qualities, q) ? data.qualities[q] : q);
  const shapesOf = (rep, s, it = inst()) => {
    if (!rep) return { list: [], note: "", mine: 0 };
    const pc = mod12(rep[0] + s);
    const n = names(s);
    if (it.kind === "keys") {
      const table = data.voicings[pianoKey(rep)];
      const list = table ? table[pc] || [] : [];
      const bass = n[mod12((rep[2] === null ? rep[0] : rep[2]) + s)];
      return { list, note: "", mine: 0, each: list.map((_, k) => INVERSIONS[k] + "; " + bass + " in the bass, left hand.") };
    }
    if (it.kind !== "strings") return { list: [], note: "", mine: 0 };
    if (it.shapes) {
      const near = it.near && own.call(it.near, rep[3]) ? it.near[rep[3]] : null;
      const quality = near === null ? rep[3] : near;
      const table = data.voicings[it.shapes + quality];
      const list = table ? table[mod12(pc + (Number(it.offset) || 0))] || [] : [];
      let note = rep[4] || near !== null ? "No shape for this chord here: " + n[pc] + qualityName(quality) + " is the closest." : "";
      if (rep[2] !== null) note = (note ? note + " " : "") + "Shown without its bass, " + n[mod12(rep[2] + s)] + ".";
      return { list, note, mine: 0 };
    }
    const which = pc + "," + rep[1] + "," + (rep[2] === null ? "" : mod12(rep[2] + s));
    const given = data.shapes && own.call(data.shapes, which) ? data.shapes[which] : { list: null, mine: 0 };
    const slash = rep[5] && data.voicings[rep[5]] ? data.voicings[rep[5]][pc] : null;
    if (slash && slash.length) return { list: given.list || slash, note: "", mine: given.mine };
    const list = data.voicings[rep[3]] ? data.voicings[rep[3]][pc] || [] : [];
    let note = "";
    if (rep[4]) note = "No shape for this chord here: " + n[pc] + qualityName(rep[3]) + " is the closest.";
    if (rep[2] !== null) note = (note ? note + " " : "") + "Play " + n[mod12(rep[2] + s)] + " in the bass.";
    return { list: given.list || list, note, mine: given.mine };
  };
  // A position as its instrument draws it (instruments.js): a chord box, or a keyboard (``span``: every position of
  // the chord, so the card keeps its width from one to the next); the strip's (bare) leave the fingers out, too
  // small to read there.
  const diagram = (position, title, bare, span) => (inst().kind === "keys"
    ? kit.keyboard(position, title, bare, span) : kit.box(position, title, bare));

  // --- the instrument: what the chords are drawn and heard for ------------------------------------------
  // The settings' Instrument menu offers each instrument of data.instruments the page draws (``drawn``); one drawn by
  // its own script (instruments.js register) draws its chords, a line under the key line, and a row of the settings.
  // Where the page is played, for such a script (its ``view``, documented in instruments.js).
  const view = () => {
    const chords = [], seen = new Set(), s = shift();
    for (let i = 0; i < count; i++) {
      const c = String(i);
      const rep = own.call(written, c) ? current(c) : null;
      if (!rep) continue;
      const name = label(c, rep);
      if (seen.has(name)) continue;
      seen.add(name);
      chords.push(Object.freeze({ i: c, name, rep: Object.freeze(rep.slice()), root: mod12(rep[0] + s),
        bass: rep[2] === null ? null : mod12(rep[2] + s) }));
    }
    return Object.freeze({ data, instrument: inst(), mode: modeNow(), shift: s, key: key ? keyName(s) : "",
      names: Object.freeze(names(s)), chords: Object.freeze(chords) });
  };
  const partsOf = () => (kit && inst().kind !== "strings" && inst().kind !== "keys" ? kit.registered(inst().id) : null);
  // A chord as its instrument's script draws it (``bare``: the strip's), or null; and the notes it sounds there.
  const chordFor = (i, rep) => {
    const s = shift();
    return Object.freeze({ i, name: label(i, rep), rep: Object.freeze(rep.slice()), root: mod12(rep[0] + s),
      bass: rep[2] === null ? null : mod12(rep[2] + s) });
  };
  const drawnBy = (i, rep, bare) => {
    const parts = partsOf();
    if (!parts || typeof parts.diagram !== "function") return null;
    try {
      const el = parts.diagram(view(), chordFor(i, rep), Boolean(bare));
      return el instanceof Element ? el : null;
    } catch (err) {
      return null;  // its script's fault: the chord has no picture
    }
  };
  const notesBy = (i, rep) => {
    const parts = partsOf();
    if (!parts || typeof parts.notes !== "function" || !rep) return null;
    try {
      const notes = parts.notes(view(), chordFor(i, rep));
      return Array.isArray(notes) && notes.length && notes.every((n) => Number.isInteger(n)) ? notes.slice() : null;
    } catch (err) {
      return null;
    }
  };
  // Its line under the key line: "" for none.
  const headerLine = () => {
    const parts = partsOf();
    if (!parts || typeof parts.header !== "function") return "";
    try {
      const line = parts.header(view());
      return typeof line === "string" ? line : "";
    } catch (err) {
      return "";
    }
  };
  const wrapT = (t) => (t > 11 ? t - 12 : t < -11 ? t + 12 : t);
  // The Instrument menu, what it says of the one chosen (its title), and what follows the instrument in the settings:
  // Capo on one that takes a capo; Easy keys, nearest the key played first, on one that has them (instruments.py EASY:
  // the ukulele's C, F, G, Bb, Am, Dm), each moving the song there as Transpose does; the row an instrument's script
  // fills. The menu's options are made again only when the instruments offered change (one registered).
  function drawInstruments() {
    const offered = INSTRUMENTS.filter(drawn);
    $("inst-row").hidden = offered.length < 2;
    const menu = $("insts"), ids = offered.map((i) => i.id).join(" ");
    if (menu.dataset.ids !== ids) {
      menu.textContent = "";
      for (const i of offered) {
        const option = menu.appendChild(document.createElement("option"));
        option.value = i.id;
        option.textContent = String(i.name || i.id);
      }
      menu.dataset.ids = ids;
    }
    menu.value = inst().id;
    menu.title = String(inst().about || "");
    $("capo-row").hidden = !takesCapo();
    const table = key && inst().easy && data.easy && data.easy[inst().easy] ? data.easy[inst().easy][modeNow()] || [] : [];
    $("easy-row").hidden = table.length === 0;
    const here = key ? mod12(key.tonic + shift()) : 0;  // the tonic of the shapes played
    const moves = table.map(([tonic, name]) => [mod12(tonic - here + 6) - 6, String(name)])
      .sort((a, b) => Math.abs(a[0]) - Math.abs(b[0]) || a[0] - b[0]);
    refill($("easy"), moves.map(([move, name]) => button(name, move === 0, () => {
      if (move) step(wrapT(state.t + move));
    }, move ? signed(move) : "now")));
    $("easy-hint").textContent = table.length ? "Keys whose chords sit well on the " + String(inst().name).toLowerCase()
      + ": each moves the song there, as Transpose does." : "";
    const panelBox = $("inst-panel");
    panelBox.textContent = "";
    const parts = partsOf();
    if (parts && typeof parts.panel === "function") {
      try {
        parts.panel(view(), panelBox);
      } catch (err) { /* its script's fault: no row */ }
    }
    panelBox.hidden = panelBox.childNodes.length === 0;
  }
  // Another instrument, from the Instrument menu: the song stays where it is played, its chords drawn and heard anew.
  const setInst = (id) => {
    if (!drawn(instOf(id)) || id === state.inst) return;
    state.inst = id;
    keepInst();
    render();
    place();
  };
  $("insts").addEventListener("change", () => setInst($("insts").value));
  // An instrument registered once the page is drawn: the row offers it, and a page on it draws it.
  document.addEventListener("caracole:instruments", () => {
    if (doc.dataset.ready === "1") render();
  });

  // --- drawing the page --------------------------------------------------------------------------
  const bar = $("bar"), panel = $("panel"), card = $("card"), pill = $("pill"), go = $("go"), harmony = $("harmony");
  const vList = $("version-list");  // a sheet's versions (below); the songbook has none
  const rails = [panel, harmony, vList].filter(Boolean);  // from 900 px wide, beside the song: one at a time
  const more = $("more"), sizes = $("sizes"), sizeButton = $("size"), shapesButton = $("shapes");
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
  // A row of chips drawn anew, as one of them is pressed: the focus, when it was on one, goes to the
  // one in its place, and stays in the settings or the card rather than falling back to the page.
  const refill = (box, chips) => {
    const at = Array.prototype.indexOf.call(box.children, document.activeElement);
    box.textContent = "";
    for (const chip of chips) box.appendChild(chip);
    const to = at >= 0 ? box.children[Math.min(at, box.children.length - 1)] : null;
    if (to) to.focus({ preventScroll: true });
  };
  // The head of the settings, under "Settings": what is set, the key and mode in bold, then the capo and the
  // instrument ("D Dorian · capo 2 · Guitar").
  const drawHead = () => {
    const [words, capo] = versionWords();
    const line = $("panel-sum");
    line.textContent = "";
    line.appendChild(document.createElement("b")).textContent = words;
    for (const part of [capo, String(inst().name || inst().id)]) {
      if (part) line.appendChild(document.createTextNode(" · " + part));
    }
  };
  // A Reset by its label while its value differs from where the page starts it, its stepper's edge in the accent;
  // pressed, it hides, and the focus goes to its stepper rather than out of the settings.
  const showReset = (reset, shown) => {
    const stepper = reset.closest(".num").querySelector(".stepper");
    const had = !shown && document.activeElement === reset;
    reset.hidden = !shown;
    stepper.classList.toggle("changed", shown);
    if (had) stepper.querySelector("button").focus({ preventScroll: true });
  };

  // A chord's chosen position holds while the chord is the same: once its name or its number of
  // shapes changes (a transposition, a mode, a capo, a swap), it starts at its first shape again.
  const atSeen = {};
  // Another instrument's shapes are others: on any but the guitar, the sign names it.
  const atSign = (i) => {
    const rep = own.call(written, i) ? current(i) : null;
    return rep ? label(i, rep) + "|" + shapesOf(rep, shift()).list.length + (state.inst === "guitar" ? "" : "|" + state.inst)
      : "";
  };
  const keepPositions = () => {
    for (const i of Object.keys(state.at)) {
      const sign = atSign(i);
      if (!sign || state.at[i] >= Number(sign.split("|")[1]) || (i in atSeen && atSeen[i] !== sign)) {
        delete state.at[i];
        delete atSeen[i];
      } else atSeen[i] = sign;
    }
  };
  // A position chosen now, for the chord as it is now: it holds until that changes.
  const setAt = (i, n) => {
    if (n > 0) {
      state.at[i] = n;
      atSeen[i] = atSign(i);
    } else {
      delete state.at[i];
      delete atSeen[i];
    }
  };
  // The shapes the browser kept (no address said which): each chord named now as it was when its shape was
  // chosen plays it again. One named otherwise (an address with another key, mode or capo, or a swap)
  // starts at its first shape, as it would have, rather than take a shape chosen for another chord.
  if (keptAt) {
    for (const i of Object.keys(keptAt.at)) {
      const n = Number(keptAt.at[i]);
      const sign = atSign(i);
      if (Number.isInteger(n) && n > 0 && sign !== "" && keptAt.signs[i] === sign) setAt(i, n);
    }
  }
  const render = () => {
    if (state.capo === sheetCapo) state.capo = null;  // the sheet's own again
    keepPositions();
    hideTip();
    if (numbered()) doc.dataset.nm = state.nm;
    else delete doc.dataset.nm;
    if (state.roles) delete doc.dataset.roles;
    else doc.dataset.roles = "off";
    chordEls.forEach((el, k) => {
      drawChord(el, k);
      el.classList.toggle("changed", !legendEls.has(el) && choice(el.dataset.c) >= 0);
    });
    doc.style.setProperty("--fs", state.fs + "px");
    $("fs-now").textContent = state.fs + " px";
    $("smaller").setAttribute("aria-disabled", state.fs <= FS.min ? "true" : "false");
    $("bigger").setAttribute("aria-disabled", state.fs >= FS.max ? "true" : "false");

    const [main, what, rest] = keyShort();
    $("key-now").querySelector(".k").textContent = main;
    keyUnder = [what, rest];
    fitKey();
    $("key-full").textContent = keyLabel(true);
    drawHead();
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
    const header = headerLine();  // an instrument's own line (instruments.js register): under the key line
    if (header) {
      const line = box.appendChild(document.createElement("span"));
      line.className = "inst-line";
      line.textContent = header;
    }

    $("shift").textContent = signed(state.t);
    showReset($("reset-t"), state.t !== (Number(data.transpose) || 0));  // the PDF's transposition, else none
    $("capo-at").textContent = String(capoNow());
    showReset($("reset-capo"), capoNow() !== sheetCapo);
    const hints = capoHints();
    $("capo-opts").hidden = hints.length === 0;
    refill($("capo"), hints.map(([fret, shapesKey]) => button(fret ? "Capo " + fret : "No capo", state.capo === fret, () => {
      state.capo = state.capo === fret ? null : fret;
      render();
    }, shapesKey + " shapes")));

    // A pill a mode, the one played pressed, the song's own marked (orig: a thicker edge, viewer.css), and named so
    // for a screen reader; over them, what the mode played sounds like.
    $("mode-row").hidden = !key;
    refill($("modes"), key ? data.modes.map((mode) => {
      const pill = button((MODES[mode] || [mode])[0], modeNow() === mode, () => {
        state.mode = mode === key.mode ? null : mode;
        render();
      });
      if (mode === key.mode) {
        pill.classList.add("orig");
        const own = pill.appendChild(document.createElement("span"));
        own.className = "vh";
        own.textContent = ", the song's own";
      }
      return pill;
    }) : []);
    if (key) $("mode-hint").textContent = (MODES[modeNow()] || ["", ""])[1];

    drawNames();
    drawInstruments();
    // The places to go, after their rule, only where there is one (a songbook's song with no key has none).
    $("places").hidden = !Array.prototype.some.call($("places").children, (row) => !row.hidden);
    $("sound-row").hidden = !sound || count === 0;
    if (sound) sound.setVolume(VOLUMES[state.vol][1]);
    refill($("volumes"), sound ? VOLUMES.map(([name], v) => {
      const level = button("", state.vol === v, () => {
        state.vol = v;
        render();
      });
      level.removeAttribute("class");  // a segment, not a chip
      level.setAttribute("aria-label", name);
      level.title = "Strum: " + name.toLowerCase();
      level.appendChild(speaker(v));
      return level;
    }) : []);
    $("strip-toggle").setAttribute("aria-pressed", state.strip ? "true" : "false");
    shapesButton.setAttribute("aria-pressed", state.strip ? "true" : "false");  // the guitar says the same
    drawSpeed();
    drawStrip();
    drawNecks();  // before layout(), which measures the song beside the rail
    drawPinyin();  // and the words with their readings
    layout();  // fit() too
    drawHeadings();
    if (!harmony.hidden) drawHarmony();
    if (!card.hidden) drawCard();  // an open card follows the key, the mode and the capo
    dock();
    save();
    hush();  // the lines moved under the page's scroll position, not by your hand
  };

  // A chord may reach over the words after it, up to the next chord on its row: lyrics then
  // read without gaps. Where two chords would touch, the first one's column is widened. A chord
  // never reaches past the line's edge, which would widen the page: where the row has less room
  // left than the chord is wide, its column takes the chord's width, and goes on to the next row.
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
        const chord = col.firstElementChild.offsetWidth;
        const need = chord + space;
        let room = right - box.left;  // no chord after it on its row: up to the edge
        for (let m = k + 1; m < kids.length; m++) {
          const next = kids[m].getBoundingClientRect();
          if (Math.abs(next.bottom - box.bottom) > 2) break;  // wrapped onto the next row
          if (kids[m].classList.contains("s")) {
            room = next.left - box.left;
            break;
          }
        }
        let width = room < need ? box.width + need - room : 0;
        if (box.left + chord > right + 0.5) width = Math.max(width, chord);  // past the edge: on to the next row
        if (width) col.lastElementChild.style.minWidth = Math.ceil(width) + "px";
      });
    }
  };
  // One column, or two side by side where viewer.css offers them (a wide screen), only for a song
  // the window then shows whole: the song's end in the second column, and the sheet no taller than
  // the window above the room the page keeps at its foot for the controls.
  const layout = () => {
    const y = window.scrollY;
    doc.dataset.columns = "2";
    if (getComputedStyle(sheetEl).columnCount !== "2") {  // not offered here
      doc.dataset.columns = "1";
      fit();
      return;
    }
    fit();
    const box = sheetEl.getBoundingClientRect();
    const end = sheetEl.lastElementChild && sheetEl.lastElementChild.lastElementChild;
    const page = sheetEl.closest(".page") || document.body;
    const room = window.innerHeight - (parseFloat(getComputedStyle(page).paddingBottom) || 0);
    const fits = Boolean(end) && end.getBoundingClientRect().left > box.left + box.width / 2 && box.height <= room;
    if (!fits) {
      doc.dataset.columns = "1";
      fit();
    }
    // Two columns are shorter than one: measuring them may have moved the page. Back to where it was.
    if (window.scrollY !== y) window.scrollTo(0, y);
  };
  let fitting = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(fitting);
    fitting = requestAnimationFrame(() => {
      layout();
      fitKey();
      place();
      placeTip();
      dock();
    });
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { layout(); fitKey(); }, () => {});
  // The tab's preamble opened or folded again (page.py): the song moves, and may no longer fit two
  // columns; an open card goes with its chord.
  for (const fold of sheetEl.querySelectorAll("details")) fold.addEventListener("toggle", () => { layout(); place(); });
  // Printed, the notes print whole: where the stylesheet can't show a folded one's text (no
  // ::details-content), they open for the printout and fold again after it.
  if (!(window.CSS && CSS.supports && CSS.supports("selector(::details-content)"))) {
    let unfolded = [];
    window.addEventListener("beforeprint", () => {
      unfolded = [...document.querySelectorAll("details.pre:not([open])")];
      for (const fold of unfolded) fold.open = true;
    });
    window.addEventListener("afterprint", () => {
      for (const fold of unfolded) fold.open = false;
      unfolded = [];
    });
  }

  const drawStrip = () => {
    const strip = $("strip");
    strip.hidden = !state.strip;
    strip.textContent = "";
    if (!state.strip) return;
    for (let i = 0; i < count; i++) {
      const rep = current(String(i));
      const shapes = shapesOf(rep, shift());
      const shape = shapes.list[Math.min(state.at[String(i)] || 0, shapes.list.length - 1)];
      const b = document.createElement("button");
      b.type = "button";
      const name = label(String(i), rep);
      const drawing = rep && own.call(written, String(i)) ? drawnBy(String(i), rep, true) : null;
      if (drawing) b.appendChild(drawing);
      else if (shape) b.appendChild(diagram(shape, name, true));
      b.appendChild(document.createTextNode(name));
      b.addEventListener("click", () => {
        openCard(String(i), b);
        hear();
      });
      strip.appendChild(b);
    }
  };

  // --- the key's neck: its scale, or its pentatonic box, across the frets, the tonic marked ------------
  // In the key shown, of the shapes played on the instrument ``it`` (``s`` semitones from the sheet's key): with a
  // capo, the frets count from it, as the chords' necks do. The rail's first neck (overlay.js draws it); on a phone,
  // the Harmony panel's. Scale or Pentatonic switches it.
  const keySpec = (s = shift(), it = inst()) => ({
    name: keyName(s), tonic: mod12(key.tonic + s), tonicName: names(s)[mod12(key.tonic + s)],
    scale: table("keyScale") || [], pentatonic: table("pentatonic") || [],
    pentaName: String(table("pentatonicName") || "pentatonic"),
    // The instrument's strings, each open note's pitch class (data.instruments' tuning, as MIDI notes).
    tuning: Array.isArray(it.tuning) && it.tuning.length ? it.tuning : data.tuning,
    box: state.kn === "penta", onSwitch: (which) => setKeyNeck(which) });
  const keyNeck = () => overlay.keyNeck(keySpec());
  const setKeyNeck = (which) => {
    const active = document.activeElement;
    const from = active && active.closest ? active.closest(".kn") : null;
    const holder = from ? from.parentElement : null;
    state.kn = which;
    render();
    const to = holder && holder.querySelector('.kn [aria-pressed="true"]');
    if (to) to.focus({ preventScroll: true });
  };

  // --- the overlay: a wide screen's rail, on the left, Guitar and Harmonica ---------------------------
  // From 1200 px wide (viewer.css), overlay.js draws it, its Guitar tab first and shown when the page opens. Guitar:
  // the key's neck, then each chord the sheet shows, once, in the order it first comes (two chords shown by one name
  // are one), with every position of it along a neck and a legend naming them, on the instrument played (a ukulele's
  // four strings), or the guitar's on one with no neck (the piano, the harmonica, the winds: then at the guitar's
  // capo). Picking one, on the neck or in the legend, makes it the shape the strip and the chord's card show, at
  // every place of that chord, kept with the rest (state.at); one of the guitar's for another instrument holds for
  // the rail alone. Harmonica: the harps for the song as it sounds (a harmonica takes no capo; a transposition moves
  // every harp), the harp chosen (harpAt, above the tonic; until one is tapped, the one the song's harmonica tab
  // plays on, else the first harp.py's choices pick), the key on it and each chord's holes, harp.py's tables looked
  // up. Narrower, the card alone. Hide, at the rail's top, the bar's button (first in it, from 1200 px) and the
  // settings' Chord necks row show it or hide it (state.necks), the three always in step; hidden, the song has the
  // whole width.
  const necksEl = $("necks");
  const railWide = window.matchMedia("(min-width: 1200px)");
  const necksButton = $("necks-toggle"), necksChip = $("necks-chip");
  const railCan = () => Boolean(necksEl) && Boolean(overlay) && count > 0 && railWide.matches;
  const railOn = () => railCan() && state.necks;
  const shownAs = (name) => {  // the chords the sheet shows by this name, by index
    const out = [];
    for (let i = 0; i < count; i++) {
      const rep = own.call(written, String(i)) ? current(String(i)) : null;
      if (rep && label(String(i), rep) === name) out.push(String(i));
    }
    return out;
  };
  // The chords the sheet shows, once a name, in the order they first come (named ``s`` from the sheet's key): [index,
  // its chord as played, its name].
  const shownOnce = (s = shift()) => {
    const out = [], seen = new Set();
    for (let i = 0; i < count; i++) {
      const c = String(i);
      const rep = own.call(written, c) ? current(c) : null;
      if (!rep) continue;  // a chord caracole can't read: nothing to play
      const name = label(c, rep, s);
      if (seen.has(name)) continue;
      seen.add(name);
      out.push([c, rep, name]);
    }
    return out;
  };
  const GUITAR = instOf("guitar") || INSTRUMENTS[0];
  const railAt = {};  // a shape picked on the guitar's necks while another instrument is played: the rail's alone
  const necksOf = () => (inst().kind === "strings" ? inst() : GUITAR);
  // The guitar at its capo (the one set, else the sheet's), as the chords would be named were it played.
  const guitarShift = () => state.t - ((state.capo === null ? sheetCapo : state.capo) - sheetCapo);
  const guitarTab = () => {
    const it = necksOf(), played = it === inst(), s = played ? shift() : guitarShift();
    const chords = shownOnce(s).map(([c, rep, name]) => {
      const shapes = shapesOf(rep, s, it);
      return { name, list: shapes.list, mine: shapes.mine, chosen: played ? state.at[c] || 0 : railAt[name] || 0 };
    });
    return { name: String(it.name || "Guitar"), strings: (it.tuning || []).length || 6, chords,
      key: key && data.keyScale ? keySpec(s, it) : null };
  };
  // A chord's row in one of harp.py's tables by chord: the sheet's in the mode played, else its alternative's.
  const sameRep = (a, b) => Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const harpRow = (byChord, byAlt, i, rep) => {
    const mode = modeNow();
    if (!byChord || !byChord[mode]) return null;
    if (sameRep(data.mapped[mode][i], rep)) return byChord[mode][i];
    const j = alts(i).findIndex((a) => sameRep(a, rep));
    return j >= 0 && byAlt && byAlt[mode] && byAlt[mode][i] ? byAlt[mode][i][j] : null;
  };
  let harpAt = null;  // the harp tapped on the circle, semitones above the tonic as it sounds; null: none yet
  const harmonicaTab = () => {
    if (!key || !data.harpRing || !data.harps || !data.harps[modeNow()]) {
      return { key: null, none: "With no key, caracole can't tell which harp plays the song.", plain: null };
    }
    const s = state.t + sheetCapo;  // the song as it sounds: a harmonica takes no capo
    const mode = modeNow(), n = names(s), choices = data.harps[mode] || [];
    const tabs = Array.isArray(data.harpTabs) ? data.harpTabs : [];
    const chords = shownOnce().map(([c, rep, shape]) => {
      const sounds = label(c, rep, s), f = harpRow(data.harpChords, data.harpAlts, c, rep);
      return { name: sounds, shape: shape === sounds ? "" : shape, root: n[mod12(rep[0] + s)],
        entries: f === null || f === undefined ? null : data.harpForms[f] || null,
        notes: harpRow(data.harpNotes, data.harpAltNotes, c, rep) };
    });
    return { key: keyName(s), tonic: mod12(key.tonic + s), names: n, harpKeys: data.harpKeys, ring: data.harpRing,
      holes: data.harpHoles, scales: data.harpScales[mode], outside: data.harpOutside[mode], choices, chords, tabs,
      chosen: harpAt !== null ? harpAt : tabs.length ? tabs[0] : choices.length ? choices[0][1] : 0 };
  };
  const rail = overlay && necksEl ? overlay.rail(necksEl, {
    first: "guitar",
    guitar: guitarTab,
    harmonica: harmonicaTab,
    pick: (name, p) => {
      if (necksOf() === inst()) {
        pickPosition(name, p);
        return;
      }
      railAt[name] = p;
      drawNecks();
    },
    chooseHarp: (offset) => {
      harpAt = offset;
      drawNecks();
    },
    hide: () => {
      showNecks(false);
      if (necksButton) necksButton.focus();  // the focus where the rail comes back from, not lost with it
    },
  }) : null;
  const drawNecks = () => {
    const can = railCan(), on = railOn();
    if (necksButton) {
      necksButton.hidden = !can;
      necksButton.setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (necksChip) {
      $("necks-row").hidden = !can;
      necksChip.setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (!necksEl) return;
    necksEl.hidden = !on;
    if (on) doc.dataset.necks = "1";  // the song and the bar move over for it
    else delete doc.dataset.necks;
    if (on) rail.draw();
    else necksEl.textContent = "";
  };
  // A position picked for a chord: every place the sheet shows it plays it, and its card, when it shows
  // that chord as it is played, turns to it.
  const pickPosition = (name, p) => {
    const places = shownAs(name);
    for (const i of places) setAt(i, p);
    if (!card.hidden && places.indexOf(shown.i) >= 0 && shown.pick === choice(shown.i)) shown.at = p;
    drawStrip();
    drawNecks();
    if (!card.hidden) drawCard();
    save();
  };
  // Shown or hidden: the song and the bar move back, or over, and the card follows its chord.
  const showNecks = (on) => {
    state.necks = on;
    keepNecks();
    render();
    place();
  };
  if (necksButton) necksButton.addEventListener("click", () => showNecks(!state.necks));
  if (necksChip) necksChip.addEventListener("click", () => showNecks(!state.necks));
  if (necksEl) {
    // The window widened past 1200 px, or narrowed under it: the rail comes or goes, and the song with it.
    railWide.addEventListener("change", () => {
      drawNecks();
      if (!harmony.hidden) drawHarmony();  // the key's neck: in the rail, or in the panel
      layout();
      place();
    });
  }

  // --- pinyin: each Chinese character's reading over it ------------------------------------------------
  // data.pinyin (page.py, pinyin.py: read in context at render time): for each line of the song's sections, in
  // the page's order, each of its characters' reading, "" for a letter, a space or punctuation, or null for a
  // line with no Chinese; none for a sheet with none, which has no Pinyin row. Shown (state.py: the settings'
  // Pinyin), each character with a reading is a ruby, the reading over it, between its chord and it
  // (viewer.css: a chord stays over its character's column); hidden, the words are again as the page wrote them.
  const pyLines = Array.isArray(data.pinyin) ? data.pinyin : [];
  const pyCan = pyLines.some((line) => Array.isArray(line));
  const pyChip = $("pinyin-chip");
  const pyWritten = new Map();  // each element drawn with readings: its text as the page wrote it
  let pyDrawn = false;
  const ruby = (character, reading) => {
    const out = document.createElement("ruby");
    out.className = "py";
    out.appendChild(document.createTextNode(character));
    const rt = out.appendChild(document.createElement("rt"));
    rt.textContent = reading;
    rt.lang = "zh-Latn-pinyin";
    rt.setAttribute("aria-hidden", "true");  // a screen reader reads the characters themselves
    return out;
  };
  // One line's words (a sung line's columns, or a line of text whole) with their characters' readings.
  const withReadings = (line, readings) => {
    const words = line.querySelector(".y, .w") ? Array.from(line.querySelectorAll(".y, .w")) : [line];
    const texts = words.map((word) => Array.from(word.textContent));
    if (texts.reduce((n, chars) => n + chars.length, 0) !== readings.length) return;  // not this page's lines
    let at = 0;
    words.forEach((word, k) => {
      const parts = [];
      let plain = "";
      for (const character of texts[k]) {
        const reading = readings[at++];
        if (typeof reading === "string" && reading) {
          if (plain) parts.push(document.createTextNode(plain));
          plain = "";
          parts.push(ruby(character, reading));
        } else {
          plain += character;
        }
      }
      if (plain) parts.push(document.createTextNode(plain));
      if (!parts.some((part) => part.nodeName === "RUBY")) return;
      pyWritten.set(word, word.textContent);
      word.textContent = "";
      for (const part of parts) word.appendChild(part);
    });
    line.classList.add("py");  // its columns keep the readings' room (viewer.css)
  };
  function drawPinyin() {
    if (pyChip) {
      $("pinyin-row").hidden = !pyCan;
      pyChip.setAttribute("aria-pressed", state.py ? "true" : "false");
    }
    const on = pyCan && state.py;
    if (on === pyDrawn) return;
    pyDrawn = on;
    if (on) {
      sheetEl.querySelectorAll(":scope > section.sec > p.l").forEach((line, n) => {
        if (Array.isArray(pyLines[n])) withReadings(line, pyLines[n]);
      });
      return;
    }
    pyWritten.forEach((text, word) => { word.textContent = text; });
    pyWritten.clear();
    for (const line of sheetEl.querySelectorAll(".l.py")) line.classList.remove("py");
  }
  if (pyChip) {
    pyChip.addEventListener("click", () => {
      state.py = !state.py;
      keepPinyin();
      render();
      place();  // an open card goes with its chord
    });
  }

  // --- the chord card: shapes, and chords to play instead ----------------------------------------
  // ``el`` is the chord tapped (or the strip's button): the card is placed by it, from 900 px wide,
  // and the focus goes back to it. Another chord tapped while the card is open fills it in its place.
  const shown = { i: null, pick: -1, at: 0, el: null, position: null };
  const openCard = (i, el) => {
    if (!own.call(written, i)) return;
    shown.i = i;
    shown.pick = choice(i);
    shown.at = state.at[i] || 0;
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
    const found = numbered() ? reading(i, chordEls.indexOf(shown.el), shown.pick) : null;
    $("card-name").textContent = found ? name + " · " + found.text : name;
    const shapes = shapesOf(rep, shift());
    const box = $("diagram");
    box.textContent = "";
    card.dataset.kind = box.dataset.kind = inst().kind;  // a keyboard is wider than a box (viewer.css)
    shown.position = null;
    const drawing = rep ? drawnBy(i, rep, false) : null;  // an instrument its script draws
    if (drawing) {
      box.appendChild(drawing);
      shown.position = notesBy(i, rep);  // a list of notes: struck together
    } else if (shapes.list.length) {
      shown.at = Math.min(shown.at, shapes.list.length - 1);
      shown.position = shapes.list[shown.at];
      box.appendChild(diagram(shapes.list[shown.at], name, false, shapes.list));
      const c = document.createElement("span");
      c.className = "count";
      c.textContent = shapes.list.length > 1 ? shown.at + 1 + " of " + shapes.list.length : "";
      box.appendChild(c);
    } else {
      box.textContent = rep ? "No shape to show for this chord." : "caracole can't read this chord.";
    }
    heardBy(box, name);
    $("prev").disabled = shown.at <= 0;
    $("next").disabled = shown.at >= shapes.list.length - 1;
    const capoNote = capoNow() ? " With the capo on fret " + capoNow() + "." : saysNoCapo() ? " With no capo." : "";
    // The shape's note, and a hidden copy of the note on the chord's other shapes (viewer.css): from the
    // tab's shapes to chords-db's, the card keeps its height, and ‹ › stay under the thumb.
    const tabs = shown.at < shapes.mine;
    const said = (mine) => ((mine ? "As the tab plays it." : shapes.each ? shapes.each[shown.at] || "" : shapes.note)
      + capoNote).trim();
    const noteBox = $("shape-note");
    noteBox.textContent = "";
    const line = (text, room) => {
      if (!text) return;
      const span = noteBox.appendChild(document.createElement("span"));
      span.textContent = text;
      if (room) span.className = "room";
    };
    line(said(tabs));
    if (shapes.mine && shapes.mine < shapes.list.length) line(said(!tabs), true);
    drawNotes(i, rep);

    const altBox = $("alts");
    $("alts-title").hidden = !list.length;
    refill(altBox, list.length ? [button(label(i, base(i)), shown.pick < 0, () => pick(-1), "as written")]
      .concat(list.map((alt, j) => button(label(i, alt), shown.pick === j, () => pick(j)))) : []);
    const use = $("use");
    const using = document.activeElement === use;
    use.hidden = shown.pick === choice(i);
    // Played for every one, it hides: the focus goes to the chord now played.
    if (using && use.hidden) {
      const played = altBox.querySelector('[aria-pressed="true"]');
      if (played) played.focus({ preventScroll: true });
    }
    const was = label(i, base(i));
    use.textContent = shown.pick >= 0 ? "Play " + name + " for every " + was : "Back to " + was + " everywhere";
    place();
    dock();
  };
  // The card's chord: its notes, each with its interval, and the scale for a solo over it, by page.py's tables
  // (the chord's name, and the scale's, on the transposition shown).
  const lead = (box, text) => {
    const words = box.appendChild(document.createElement("span"));
    words.className = "lab2";
    words.textContent = text;
  };
  function drawNotes(i, rep) {
    const tones = $("card-tones"), scale = $("card-scale");
    tones.textContent = "";
    scale.textContent = "";
    const found = rep && data.tones ? data.tones[nameOf(rep, shift())] : null;
    if (found) {
      const [notes, steps] = found.split("|").map((text) => text.split(" "));
      lead(tones, "Notes");
      notes.forEach((note, n) => {
        const pair = tones.appendChild(document.createElement("span"));
        pair.className = "tn";
        pair.appendChild(document.createTextNode(note));
        pair.appendChild(document.createElement("small")).textContent = steps[n] || "";
      });
    }
    const index = !rep || !key ? null
      : shown.pick >= 0 ? ((table("altSolo") || [])[i] || [])[shown.pick] : (table("solo") || [])[i];
    const named = index === null || index === undefined || !data.scales ? null
      : data.scales[names(shift())[mod12(rep[0] + shift())] + " " + data.scaleWords[index]];
    if (named) {
      const [name, notes] = named.split("|");
      lead(scale, "Solo");
      scale.appendChild(document.createElement("span")).textContent = name;
      scale.lastChild.className = "sn";
      scale.appendChild(document.createElement("span")).textContent = notes;
      scale.lastChild.className = "sx";
    }
  }
  // --- hearing it (strum.js): a tap on a chord, or on its card's diagram, strums the shape the card shows,
  // at the capo; nothing sounds otherwise. The diagram is a button only while it has a shape to play.
  const sound = window.caracoleSound && window.caracoleSound.available ? window.caracoleSound : null;
  const hearable = () => Boolean(sound) && state.vol > 0 && Boolean(shown.position);
  const hear = () => {
    if (hearable()) sound.strum(shown.position, { capo: capoNow(), tuning: inst().tuning, voice: inst().voice });
  };
  function heardBy(box, name) {
    if (hearable()) {
      box.setAttribute("role", "button");
      box.tabIndex = 0;
      box.setAttribute("aria-label", "Hear " + name);
    } else {
      for (const attr of ["role", "tabindex", "aria-label"]) box.removeAttribute(attr);
    }
  }
  $("diagram").addEventListener("click", hear);
  $("diagram").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      hear();
    }
  });
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
  // The position shown is kept for the chord played now (not one tried among the alternatives).
  const keepAt = () => {
    if (shown.pick !== choice(shown.i)) return;
    for (const i of shownAs(label(shown.i, current(shown.i)))) setAt(i, shown.at);  // the rail's one chord
    drawStrip();
    drawNecks();
    save();
  };
  $("prev").addEventListener("click", () => { shown.at = Math.max(0, shown.at - 1); drawCard(); keepAt(); });
  $("next").addEventListener("click", () => { shown.at += 1; drawCard(); keepAt(); });
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
  // the song comes up above it, and the pill rides above it (--dock: its height). The bar is out of
  // the way while the song moves by itself, unless one is docked on it: then nothing moves as the
  // scroll pauses and resumes. Paused, or at the end of the song, it is back, under the pill.
  function dock() {
    const there = wide.matches ? null : topLayer();
    const away = moving() && !there;
    if (bar.hidden !== away) {
      bar.hidden = away;
      if (!away) {
        slide(false);
        fitKey();
      }
    }
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
    for (const which of [panel, card, harmony, vList]) if (which) which.classList.toggle("top", which === topLayer());
    more.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    if (vList) $("ver-now").setAttribute("aria-expanded", vList.hidden ? "false" : "true");
    if (rails.every((which) => which.hidden)) delete doc.dataset.panel;  // the settings', the Harmony panel's, the versions'
    else doc.dataset.panel = "open";
    if (wide.matches && rail !== doc.dataset.panel) layout();  // the song's column narrows beside the rail
    place();
    dock();
  };
  const open = (which, opener) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at >= 0) layers.splice(at, 1);  // open already: on top again
    if (rails.indexOf(which) >= 0) for (const other of rails) if (other !== which) close(other);
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
    if (which === harmony) stopPlaying(true);
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
    if (!tip.hidden) {
      hideTip();
      return;
    }
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
  // The settings and the Harmony panel take one place: either opens in the other's.
  more.addEventListener("click", () => {
    if (inSight(panel)) {
      close(panel);
      return;
    }
    close(harmony);
    open(panel, more);
  });

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

  // --- the chord names setting and a numeral's line --------------------------------------------------
  // The chord names, a segmented control: each segment's words, and what a screen reader hears.
  const NAMES = [[null, "Chords", "Chords"], ["both", "+ Numerals", "Chords + numerals"],
    ["numerals", "Numerals", "Numerals only"]];
  const keyWords = () => "the key of " + keyName(shift()) + (key && key.from ? " (" + key.from + ")" : "");
  // A song whose key caracole can't tell has its chords alone: the numerals' segments greyed, and the hint says why.
  function drawNames() {
    const can = Boolean(key) && Boolean(data.numerals);
    refill($("names"), NAMES.map(([nm, words, said]) => {
      const segment = button(words, (can ? state.nm : null) === nm, () => {
        state.nm = nm;
        render();
      });
      segment.removeAttribute("class");  // a segment, not a chip
      segment.setAttribute("aria-label", said);
      segment.disabled = !can && nm !== null;
      return segment;
    }));
    $("roles").hidden = !can;
    $("roles").setAttribute("aria-pressed", state.roles ? "true" : "false");
    $("names-hint").textContent = can ? "" : "caracole can't tell this song's key, so it can't number its chords.";
    $("harmony-row").hidden = !can || !data.progressions;
  }
  $("roles").addEventListener("click", () => {
    state.roles = !state.roles;
    render();
  });
  // A numeral's tooltip, by it: on a finger's tap, or while the mouse is over it. Escape, a tap anywhere else,
  // or the mouse moving away closes it; it goes with the page as it scrolls. It heads with the chord as the sheet
  // names it, its numeral as the sheet draws it and its role in words; then the numeral's line and the key it is
  // read in; then the chord's notes, on a twelve-note circle, C at the top, beside their list, or as tiles over a
  // keyboard, and a button to the other view (← and → too, while the focus is in the tooltip), with ▶ Hear it beside
  // it, which strums the chord as its card would. Every note, interval and pitch class is the page's data
  // (data.tones: harmony_tables.py), and the key's notes are its scale (data.keyScale) above the tonic shown: a
  // note of the chord is outside the key when it isn't one of them, and the line under the picture names it, with
  // the key's note of its letter.
  const tip = $("tip");
  let tipOf = null, leaving = 0;
  function hideTip() {
    clearTimeout(leaving);
    if (tip.hidden) return;
    const inside = tip.contains(document.activeElement);
    tip.hidden = true;
    if (tipOf) tipOf.removeAttribute("aria-describedby");
    if (inside && tipOf && tipOf.isConnected) tipOf.focus({ preventScroll: true });  // not lost with the tooltip
    tipOf = null;
  }
  const ROLES = { h: "home", a: "away", p: "pull" };
  const MODE_WORDS = { ionian: "major", aeolian: "minor" };
  // The chord's notes, each [name, interval, pitch class], from the root up by degree as data.tones lists them, or
  // null where the tables don't name the chord.
  const tonesOf = (rep) => {
    const found = rep && data.tones ? data.tones[nameOf(rep, shift())] : null;
    if (typeof found !== "string") return null;
    const [notes, steps, pcs] = found.split("|").map((text) => text.split(" "));
    if (!pcs || pcs.length !== notes.length || pcs.some((pc) => !/^\d+$/.test(pc))) return null;
    return notes.map((note, n) => [note, steps[n] || "", mod12(Number(pcs[n]))]);
  };
  // The key's notes, as pitch classes, in the key shown; null without a key.
  const keyNotes = () => {
    const steps = key ? table("keyScale") : null;
    return Array.isArray(steps) ? new Set(steps.map((step) => mod12(key.tonic + shift() + step))) : null;
  };
  // "G major", "E minor", "D Dorian": the key shown, as the numerals' lines name it.
  const keyWordsShort = () => names(shift())[mod12(key.tonic + shift())] + " "
    + (MODE_WORDS[modeNow()] || (MODES[modeNow()] || [modeNow()])[0]);
  // The twelve notes as a clock, C at the top, each named as the page names it in the key shown (the chord's own
  // as the chord spells them): the key's ringed, the others faint; the chord's larger, joined round the circle in
  // its role's colour; the root in the accent; a note from outside the key dashed (viewer.css). Each dot and name
  // carries its pitch class (data-pc).
  const CLOCK = { mid: 75, r: 56 };
  const clock = (notes, inKey) => {
    const out = svg("svg", { viewBox: "0 0 150 150", class: "tc", focusable: "false" });
    const at = (pc) => [CLOCK.mid + CLOCK.r * Math.sin(pc * Math.PI / 6), CLOCK.mid - CLOCK.r * Math.cos(pc * Math.PI / 6)]
      .map((v) => Math.round(v * 100) / 100);
    svg("circle", { class: "tc-ring", cx: CLOCK.mid, cy: CLOCK.mid, r: CLOCK.r }, out);
    const corners = Array.from(new Set(notes.map((note) => note[2]))).sort((a, b) => a - b);
    if (corners.length > 1) svg("polygon", { class: "tc-shape", points: corners.map((pc) => at(pc).join(",")).join(" ") }, out);
    const n = names(shift());
    for (let pc = 0; pc < 12; pc++) {
      const mine = notes.find((note) => note[2] === pc);
      const marks = [inKey.has(pc) ? "in" : "", mine ? "on" : "", mine && mine[1] === "R" ? "root" : "",
        mine && !inKey.has(pc) ? "off" : ""].filter(Boolean).join(" ");
      const [x, y] = at(pc);
      svg("circle", { class: ("tc-dot " + marks).trim(), cx: x, cy: y, r: mine ? 9 : 7, "data-pc": pc }, out);
      svg("text", { class: ("tc-name " + marks).trim(), x, y, "data-pc": pc }, out).textContent = mine ? mine[0] : n[pc];
    }
    return out;
  };
  // The chord's notes as a list, each with its interval: the root's row in the accent, an outside note's dashed.
  const noteList = (box, notes, inKey) => {
    box.textContent = "";
    for (const [name, step, pc] of notes) {
      const row = box.appendChild(document.createElement("li"));
      const off = !inKey.has(pc);
      row.className = [step === "R" ? "root" : "", off ? "off" : ""].filter(Boolean).join(" ");
      row.appendChild(document.createElement("b")).textContent = name;
      row.appendChild(document.createElement("span")).textContent = (step === "R" ? "root" : step) + (off ? " · off key" : "");
    }
  };
  // "F isn't in G major (it has F#).": the notes from outside the key, and the key's notes of their letters.
  const offWords = (notes, inKey) => {
    const off = notes.filter((note) => !inKey.has(note[2])).map((note) => note[0]);
    if (!off.length) return "";
    const n = names(shift());
    const mine = Array.from(inKey).map((pc) => n[pc]);
    const has = off.map((name) => mine.find((other) => other.charAt(0) === name.charAt(0))).filter(Boolean);
    const and = (words) => (words.length > 1 ? words.slice(0, -1).join(", ") + " and " + words[words.length - 1] : words[0]);
    return and(off) + (off.length > 1 ? " aren't" : " isn't") + " in " + keyWordsShort()
      + (has.length === off.length ? " (it has " + and(has) + ")" : "") + ".";
  };
  // The chord's notes as tiles, each its name over its interval, the root's in the accent, an outside note's dashed.
  const noteTiles = (box, notes, inKey) => {
    box.textContent = "";
    for (const [name, step, pc] of notes) {
      const tile = box.appendChild(document.createElement("li"));
      tile.className = [step === "R" ? "root" : "", inKey.has(pc) ? "" : "off"].filter(Boolean).join(" ");
      tile.appendChild(document.createElement("b")).textContent = name;
      tile.appendChild(document.createElement("small")).textContent = step === "R" ? "root" : step;
    }
  };
  // The chord's notes stacked up from its root, each above the one before, from the C at or below the root (C4,
  // MIDI 60), as MIDI notes.
  const stacked = (notes) => {
    const out = [];
    for (const note of notes) {
      let midi = 60 + note[2];
      while (out.length && midi <= out[out.length - 1]) midi += 12;
      out.push(midi);
    }
    return out;
  };
  // Those notes on a keyboard from that C, two octaves of it or more (instruments.js keyboard): the root's key in
  // the accent (its "bass"), the others' in the role's colour, an outside note's red (viewer.css).
  const keyboardOf = (notes, inKey) => {
    if (!kit) return null;
    const midis = stacked(notes);
    const board = kit.keyboard(midis, "", true, [[60, Math.max(83, ...midis)]]);
    for (const attr of ["role", "aria-label"]) board.removeAttribute(attr);
    board.setAttribute("class", "kb");
    board.setAttribute("preserveAspectRatio", "none");  // the tooltip's width, and keys no taller than it needs
    for (const rect of board.querySelectorAll("rect[data-role]")) {
      const k = midis.indexOf(Number(rect.dataset.note));
      if (k >= 0 && !inKey.has(notes[k][2])) rect.classList.add("off");
    }
    return board;
  };
  const drawTipNotes = (rep) => {
    const notes = tonesOf(rep), inKey = keyNotes();
    const can = Boolean(notes) && Boolean(inKey);
    $("tip-pic").hidden = $("tip-view").hidden = $("tip-dots").hidden = !can;  // Hear it stays: the chord sounds all the same
    for (const box of ["tip-clock", "tip-notes", "tip-tiles", "tip-kb"]) $(box).textContent = "";
    const off = can ? offWords(notes, inKey) : "";
    $("tip-off").hidden = !off;
    $("tip-off").textContent = off;
    if (!can) return;
    $("tip-clock").appendChild(clock(notes, inKey));
    noteList($("tip-notes"), notes, inKey);
    noteTiles($("tip-tiles"), notes, inKey);
    const board = keyboardOf(notes, inKey);
    if (board) $("tip-kb").appendChild(board);
  };
  // The view shown, the circle or the keyboard: the reader's, kept once for every sheet and songbook, as the rail of
  // necks is; the circle when nothing is kept, or the page has no storage (a server's sandbox: the choice then lasts
  // as long as the page).
  const TIPVIEW = "caracole-viewer-tipview";
  const VIEWS = { circle: ["Keyboard ›", "Show the notes on a keyboard", "keys"],
    keys: ["‹ Circle", "Show the notes on a circle", "circle"] };
  let tipView = "circle";
  try {
    if (localStorage.getItem(TIPVIEW) === "keys") tipView = "keys";
  } catch (err) { /* no storage: the circle */ }
  const drawTipView = () => {
    tip.dataset.view = tipView;
    $("tip-circle").hidden = tipView !== "circle";
    $("tip-keys").hidden = tipView !== "keys";
    $("tip-view").textContent = VIEWS[tipView][0];
    $("tip-view").setAttribute("aria-label", VIEWS[tipView][1]);
  };
  const showTipView = (view) => {
    if (view === tipView) return;
    tipView = view;
    try {
      localStorage.setItem(TIPVIEW, view);
    } catch (err) { /* private mode, or a server's sandbox: for this page alone */ }
    drawTipView();
    placeTip();  // the other view's height: still by its numeral
  };
  $("tip-view").addEventListener("click", () => showTipView(VIEWS[tipView][2]));
  tip.addEventListener("keydown", (e) => {
    if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    e.stopPropagation();  // in a songbook the arrows go from song to song (book.js), but not from here
    if (!$("tip-view").hidden) showTipView(e.key === "ArrowLeft" ? "circle" : "keys");
  });
  // What Hear it strums: the shape the chord's card shows for it now, on the instrument played, or null where
  // nothing would sound (no Web Audio, the strum off, no shape).
  const tipSound = (i) => {
    const rep = current(i);
    if (!sound || state.vol <= 0 || !rep) return null;
    if (partsOf()) {
      const notes = notesBy(i, rep);
      return notes ? { position: notes, capo: capoNow() } : null;
    }
    const shapes = shapesOf(rep, shift());
    if (!shapes.list.length) return null;
    return { position: shapes.list[Math.min(state.at[i] || 0, shapes.list.length - 1)], capo: capoNow() };
  };
  const placeTip = () => {
    if (!tipOf || tip.hidden) return;
    const a = (tipOf.querySelector(".nm") || tipOf).getBoundingClientRect();
    const width = tip.offsetWidth, height = tip.offsetHeight, gap = 8;
    const floor = bar.hidden || bar.classList.contains("away") ? window.innerHeight : bar.getBoundingClientRect().top;
    let top = a.bottom + gap;
    if (top + height > floor - gap && a.top - gap - height >= gap) top = a.top - gap - height;
    const left = Math.max(gap, Math.min(a.left - 12, doc.clientWidth - gap - width));
    tip.style.setProperty("--tip-top", Math.round(top + window.scrollY) + "px");
    tip.style.setProperty("--tip-left", Math.round(left + window.scrollX) + "px");
  };
  function showTip(el) {
    const i = el.dataset.c;
    const found = reading(i, chordEls.indexOf(el));
    if (!found) return;
    clearTimeout(leaving);
    if (tipOf && tipOf !== el) tipOf.removeAttribute("aria-describedby");
    const name = label(i, current(i));
    $("tip-chord").textContent = name;
    $("tip-nm").textContent = "";
    $("tip-nm").appendChild(numeralEl(found));
    $("tip-role").textContent = own.call(ROLES, found.role) ? ROLES[found.role] : "outside the key";
    tip.dataset.role = found.role;
    $("tip-line").textContent = found.line ? textOf(found.line)
      : found.text + ": the chord you chose in place of " + label(i, base(i)) + ".";
    $("tip-key").textContent = "In " + keyWords() + ".";
    drawTipNotes(current(i));
    drawTipView();
    $("tip-hear").hidden = !tipSound(i);
    $("tip-switch").hidden = $("tip-view").hidden && $("tip-hear").hidden;  // nothing to switch, nothing to hear
    tip.hidden = false;
    tipOf = el;
    el.setAttribute("aria-describedby", "tip");
    placeTip();
  }
  $("tip-hear").addEventListener("click", () => {
    const heard = tipOf ? tipSound(tipOf.dataset.c) : null;
    if (heard) sound.strum(heard.position, { capo: heard.capo, tuning: inst().tuning, voice: inst().voice });
  });
  document.addEventListener("pointerdown", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (!tip.hidden && !(target && (tip.contains(target) || (tipOf && tipOf.contains(target))))) hideTip();
  }, true);
  const leave = (e) => {
    if (e.pointerType !== "mouse" || tip.hidden) return;
    const to = e.relatedTarget instanceof Element ? e.relatedTarget : null;
    if (to && (tip.contains(to) || (tipOf && tipOf.contains(to) && to.closest(".nm")))) return;
    clearTimeout(leaving);
    leaving = setTimeout(hideTip, 300);
  };
  $("sheet").addEventListener("pointerover", (e) => {
    const nm = e.pointerType === "mouse" && e.target instanceof Element ? e.target.closest(".nm") : null;
    if (!nm) return;
    clearTimeout(leaving);
    if (tipOf !== nm.closest(".c")) showTip(nm.closest(".c"));
  });
  $("sheet").addEventListener("pointerout", (e) => {
    if (e.target instanceof Element && e.target.closest(".nm")) leave(e);
  });
  tip.addEventListener("pointerover", () => clearTimeout(leaving));
  tip.addEventListener("pointerout", leave);

  // --- the Harmony panel: each section's progression, named, played ------------------------------------
  // In the settings' place (docked on a phone, a rail from 900 px): the key the numerals are read in, its
  // neck on a phone (the rail of necks has it on a laptop), and each section's progression (page.py's
  // ``progressions``): its numerals, one cycle, the times it is played (and how many of those vary it), its
  // name, the named progressions it plays within it, and how it ends. Tap one to go to its section; ▶ plays it
  // with strum.js's synthesis (window.caracoleSound, when the page has it), a chord a bar at the tempo set (− and
  // + change it as it plays), each chord as the page shows it, its shape and the capo, and marks the one playing;
  // ■ stops it, and closing the panel every sound. Songs with this progression is the library's page, with it
  // filtered (#prog=), and so is Songs with each one it contains.
  const ENDINGS = { authentic: "an authentic cadence (V–I)", plagal: "a plagal cadence (IV–I)",
    half: "a half cadence (on V)", deceptive: "a deceptive cadence (V–vi)" };
  const COUNTS = ["no", "one", "two", "three"];
  const counted = (n, word) => (n < COUNTS.length ? COUNTS[n] : String(n)) + " " + word + (n === 1 ? "" : "s");
  // The named progressions a section plays within it, each [name, times, key].
  const containedOf = (found) => (Array.isArray(found[8]) ? found[8] : [])
    .filter((c) => Array.isArray(c) && typeof c[0] === "string" && c[0] && typeof c[2] === "string");
  // "contains the pop progression ×2 and ii–V–I".
  const containsWords = (found) => {
    const names = containedOf(found).map((c) => c[0] + (Number(c[1]) > 1 ? " ×" + Number(c[1]) : ""));
    if (!names.length) return "";
    const last = names.pop();
    return "contains " + (names.length ? names.join(", ") + " and " + last : last);
  };
  const sectionEls = () => Array.from(sheetEl.querySelectorAll(":scope > section.sec"));
  const sectionName = (n) => {
    const head = (sectionEls()[n] || document.body).querySelector(":scope > h2.lbl");
    return head && head.firstChild ? head.firstChild.textContent : "Section " + (n + 1);
  };
  // With the numerals shown, each section's heading names its progression, when it has a name, or those it
  // plays within it.
  function drawHeadings() {
    const named = {};
    if (numbered()) {
      for (const found of table("progressions") || []) {
        const said = found[3] || containsWords(found);
        if (said) named[found[0]] = said;
      }
    }
    sectionEls().forEach((sec, n) => {
      const head = sec.querySelector(":scope > h2.lbl");
      if (!head) return;
      let tag = head.querySelector(".prog-of");
      if (!own.call(named, n)) {
        if (tag) tag.remove();
        return;
      }
      if (!tag) {
        tag = head.appendChild(document.createElement("span"));
        tag.className = "prog-of";
      }
      tag.textContent = " · " + named[n];
    });
  }
  // Looked up as it plays, not with strum.js's ``sound`` above, which the chord taps use.
  const synthesis = () => {
    const found = window.caracoleSound;
    return found && found.available !== false && typeof found.play === "function" ? found : null;
  };
  let playing = null;  // {n: the section, at: the numeral sounding, handle}
  const drawPlaying = () => {
    for (const li of $("progs").children) {
      const mine = Boolean(playing) && playing.n === Number(li.dataset.n);
      const play = li.querySelector(".prog-play");
      play.textContent = mine ? "■" : "▶";
      play.setAttribute("aria-label", mine ? "Stop" : "Play " + li.querySelector(".prog-sec").textContent);
      li.querySelectorAll(".pn").forEach((pn, k) => pn.classList.toggle("on", mine && playing.at === k));
    }
  };
  // ■, another ▶ or the panel closed: the progression stops; the panel closed (``all``), every sound strum.js
  // still makes too, a chord tapped among them.
  function stopPlaying(all) {
    const was = playing;
    playing = null;
    if (was && was.handle) {
      try {
        was.handle.stop();
      } catch (err) { /* already over */ }
    }
    const synth = all ? synthesis() : null;
    if (synth && typeof synth.stop === "function") synth.stop();
    drawPlaying();
  }
  const playSection = (n, repeats, chords) => {
    const again = Boolean(playing) && playing.n === n;
    stopPlaying();
    const synth = state.vol > 0 ? synthesis() : null;
    if (again || !synth) return;
    const cycle = chords.map((i) => {
      const c = String(i);
      if (partsOf()) return { position: notesBy(c, current(c)), capo: 0, voice: inst().voice };
      const shapes = shapesOf(current(c), shift());
      const at = Math.min(state.at[c] || 0, shapes.list.length - 1);
      return { position: shapes.list.length ? shapes.list[at] : null, capo: capoNow(), tuning: inst().tuning,
        voice: inst().voice };
    });
    const all = [];
    for (let r = 0; r < repeats; r++) all.push(...cycle);
    const me = { n, at: -1, handle: null };
    playing = me;
    drawPlaying();
    me.handle = synth.play(all, { bpm: state.bpm,
      onChord: (k) => {
        if (playing !== me) return;
        me.at = k % cycle.length;
        drawPlaying();
      },
      onEnd: () => {
        if (playing !== me) return;
        playing = null;
        drawPlaying();
      } });
    if (!me.handle || me.handle.playing === false) {
      if (playing === me) playing = null;
      drawPlaying();
    }
  };
  const drawHarmony = () => {
    if (!key) return;
    $("harmony-key").textContent = "Read in " + keyWords() + ".";
    const neckBox = $("harmony-neck");
    const inNeck = neckBox.contains(document.activeElement);
    neckBox.textContent = "";
    if (!railOn() && data.keyScale && inst().kind === "strings") neckBox.appendChild(keyNeck());  // not in the rail: here
    if (inNeck) {
      const to = neckBox.querySelector('[aria-pressed="true"]');
      if (to) to.focus({ preventScroll: true });
    }
    const synth = state.vol > 0 ? synthesis() : null;  // Sound off: no ▶ that would play nothing
    $("tempo-row").hidden = !synth;
    $("bpm").textContent = String(state.bpm);
    const list = $("progs");
    // The focus comes back to the same control of the same row: its row, its class, and which of the row's
    // controls of that class it is (a row has a Songs with … link for each progression it contains).
    const active = list.contains(document.activeElement) ? document.activeElement : null;
    const cls = active && ["prog-go", "prog-play", "prog-songs", "prog-named"].find((c) => active.classList.contains(c));
    const row = active && active.closest(".prog");
    const back = cls && row ? [Array.prototype.indexOf.call(list.children, row), cls,
      Array.prototype.indexOf.call(row.querySelectorAll("." + cls), active)] : null;
    list.textContent = "";
    const found = table("progressions") || [];
    $("progs-none").hidden = found.length > 0;
    for (const row of found) {
      const [n, numerals, repeats, name, ending, pkey, chords, variations] = row;
      const li = list.appendChild(document.createElement("li"));
      li.className = "prog";
      li.dataset.n = String(n);
      const go = li.appendChild(document.createElement("button"));
      go.type = "button";
      go.className = "prog-go";
      const part = (cls, text) => {
        const span = go.appendChild(document.createElement("span"));
        span.className = cls;
        if (text !== undefined) span.textContent = text;
        return span;
      };
      part("prog-sec", sectionName(n));
      const nums = part("prog-nums");
      numerals.forEach((numeral, k) => {
        if (k) nums.appendChild(document.createTextNode("–"));
        const pn = nums.appendChild(document.createElement("span"));
        pn.className = "pn";
        pn.textContent = numeral;
      });
      if (repeats > 1) {
        const times = nums.appendChild(document.createElement("span"));
        times.className = "prog-x";
        times.textContent = "×" + repeats;
        if (variations > 0) {  // "×8, one variation", the words kept together
          times.appendChild(document.createTextNode(", "));
          const varied = times.appendChild(document.createElement("span"));
          varied.className = "prog-var";
          varied.textContent = counted(variations, "variation");
        }
      }
      part("prog-about", [name, containsWords(row), ending && ENDINGS[ending] ? "ends on " + ENDINGS[ending] : ""]
        .filter(Boolean).join(" · "));
      go.addEventListener("click", () => {
        const sec = sectionEls()[n];
        if (sec) sec.scrollIntoView({ block: "start", behavior: calm.matches ? "auto" : "smooth" });
      });
      const play = li.appendChild(document.createElement("button"));
      play.type = "button";
      play.className = "round prog-play";
      play.hidden = !synth || !Array.isArray(chords);
      play.addEventListener("click", () => playSection(n, repeats, chords || []));
      const songs = li.appendChild(document.createElement("a"));
      songs.className = "link prog-songs";
      songs.href = String(data.library || "") + "#prog=" + encodeURIComponent(pkey);
      songs.textContent = "Songs with this progression";
      for (const [cname, , ckey] of containedOf(row)) {
        const more = li.appendChild(document.createElement("a"));
        more.className = "link prog-named";
        more.href = String(data.library || "") + "#prog=" + encodeURIComponent(ckey);
        more.textContent = "Songs with " + cname;
      }
    }
    drawPlaying();
    const again = back && list.children[back[0]] && list.children[back[0]].querySelectorAll("." + back[1])[back[2]];
    if (again) again.focus({ preventScroll: true });
  };
  $("harmony-open").addEventListener("click", () => {
    close(panel);
    drawHarmony();
    open(harmony, more);
  });
  // The progression playing takes the new tempo from its next strum on.
  const setBpm = (n) => {
    state.bpm = Math.max(BPM.min, Math.min(BPM.max, n));
    $("bpm").textContent = String(state.bpm);
    if (playing && playing.handle && typeof playing.handle.tempo === "function") playing.handle.tempo(state.bpm);
    save();
  };
  $("bpm-down").addEventListener("click", () => setBpm(state.bpm - BPM.step));
  $("bpm-up").addEventListener("click", () => setBpm(state.bpm + BPM.step));
  // --- the versions of the sheet -----------------------------------------------------------------
  // UG's chords versions of the song (data.versions: sheet_versions.as_data, with ``sheet``, the provider of
  // the sheet the title opens, and each entry's ``this``, whether it is this page's), on the sheet's own
  // viewer and on each kept version's. Under the key line, the line says which of them this page is and opens the list
  // of them all; ‹ and › open the version kept before or after this one, in rank order (first the sheet the
  // title opens, when it is none of UG's), in this tab: the served viewer's sandbox opens no other, and
  // they take the text size and the scroll speed along (the key and the rest are this sheet's chords'). In
  // the list a kept version opens; one not kept is kept by caracole serve's /versions page, which reads it
  // on UG now, or, from a file, links to UG's page and shows the command that keeps it, with Copy; a version
  // gone from UG opens nothing. Make this the one, and Back to caracole's pick (while your [pin] chooses the sheet),
  // the same way.
  const vSource = data.versions && typeof data.versions === "object" ? data.versions : {};
  const vRows = (Array.isArray(vSource.list) ? vSource.list : [])
    .filter((v) => v && typeof v === "object" && typeof v.tab === "string")
    .sort((a, b) => (Number(a.rank) || 0) - (Number(b.rank) || 0));
  const vOn = Boolean(vList && $("versions")) && vRows.length > 0;
  const here = pageName();
  const vChosen = vRows.find((v) => v.chosen) || null;
  // This page's version: the one its data says, or, where it says none, the one whose page this is.
  const vHere = vRows.some((v) => typeof v.this === "boolean") ? vRows.find((v) => v.this === true) || null
    : vRows.find((v) => v.page === here && v.chosen) || vRows.find((v) => v.page === here) || null;
  // The sheet the title opens when it is none of UG's versions: LaCuerda's, or an auto sheet standing alone.
  const OTHERS = { lacuerda: { label: "LaCuerda's sheet", page: "sheet.html" },
    auto: { label: "the auto sheet", page: "sheet (auto).html" } };
  const vOne = vChosen || !own.call(OTHERS, vSource.sheet) ? null : OTHERS[vSource.sheet];
  const vTotal = Number.isInteger(vSource.total) && vSource.total >= vRows.length ? vSource.total : vRows.length;
  const vCount = (n) => n + (n === 1 ? " version" : " versions");
  const vName = (v) => (Number.isInteger(v.number) ? "Ver " + v.number : "No. " + v.rank);
  const vRating = (v) => (typeof v.rating !== "number" || !isFinite(v.rating) ? ""
    : v.rating.toFixed(2) + "★" + (Number.isInteger(v.votes) ? " (" + v.votes.toLocaleString("en-US") + ")" : ""));
  // The pages ‹ and › go through, each once.
  const vPages = vOne ? [vOne.page] : [];
  for (const v of vRows) if (v.page && (!v.gone || v === vHere) && vPages.indexOf(v.page) < 0) vPages.push(v.page);
  const vAt = vPages.indexOf(here);
  const vAddress = (page) => {
    const params = new URLSearchParams();
    if (state.fs !== FS.start) params.set("fs", String(state.fs));
    if (state.speed !== SPEED.start) params.set("speed", String(state.speed));
    if (!state.necks) params.set("necks", "0");  // the rail hidden there too
    if (state.py) params.set("py", "1");  // and the pinyin shown
    if (state.inst !== "guitar") params.set("inst", state.inst);  // and the instrument
    const fragment = params.toString();
    return encodeURIComponent(page) + (fragment ? "#" + fragment : "");
  };
  // Each link to a version again, as the text size or the speed changes (save()).
  function versionLinks() {
    if (!vOn) return;
    const step = (link, page) => {
      if (page) {
        link.setAttribute("href", vAddress(page));
        link.removeAttribute("aria-disabled");
      } else {
        link.removeAttribute("href");
        link.setAttribute("aria-disabled", "true");
      }
    };
    step($("ver-prev"), vAt > 0 ? vPages[vAt - 1] : null);
    step($("ver-next"), vAt >= 0 && vAt + 1 < vPages.length ? vPages[vAt + 1] : null);
    for (const link of vList.querySelectorAll("a[data-page]")) link.setAttribute("href", vAddress(link.dataset.page));
  }
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const apart = () => make("span", "vh", " · ");  // heard between the parts a row shows apart
  const SAYS = {
    keep: "it reads this version on UG now and keeps it beside the sheet.",
    choose: "this version becomes the sheet the title opens, and the PDF's and the songbooks'.",
    clear: "the title opens caracole's pick again: the best rated of the versions with the lyrics.",
  };
  // Served, a link to caracole serve's page that asks for it; from a file, a button that shows the command.
  const vCommand = (box, what, tab) => {
    for (const old of vList.querySelectorAll(".vcmd")) old.remove();
    const shown = make("div", "vcmd");
    const code = make("code", "cmd", "caracole versions " + songNamed() + " --" + what + (tab ? " " + tab : ""));
    const copy = make("button", "chip", "Copy");
    copy.type = "button";
    copy.addEventListener("click", () => {
      try {
        navigator.clipboard.writeText(code.textContent).then(() => { copy.textContent = "Copied"; }, () => {});
      } catch (err) { /* no clipboard: the command is selectable */ }
    });
    shown.append(code, copy, make("p", "hint", "Run this where caracole is installed: " + SAYS[what]));
    box.appendChild(shown);
  };
  const vAction = (box, text, what, tab, primary, where) => {
    const control = make(served ? "a" : "button", primary ? "btn primary" : "link", text);
    if (served) {
      const query = new URLSearchParams();
      query.set("sheet", sheetPath());
      if (tab) query.set("tab", tab);
      query.set("do", what);
      control.setAttribute("href", "/versions?" + query.toString());
    } else {
      control.type = "button";
      control.addEventListener("click", () => vCommand(where || box, what, tab));
    }
    box.appendChild(control);
  };
  // A version in the list: its name, its rating, what it is (the one, kept, this page, gone) and the
  // tabber's note, a link to its page when it opens; under it, what you can do with it.
  const vItem = (title, rating, tags, note, page, current) => {
    const li = make("li", "ver");
    const main = make(page && !current ? "a" : "div", "ver-main");
    if (page && !current) main.dataset.page = page;
    if (current) main.setAttribute("aria-current", "page");
    main.appendChild(make("span", "ver-name", title));
    if (rating) main.append(apart(), make("span", "ver-rate", rating));
    const said = tags.concat(current ? ["this page"] : []).filter(Boolean);
    if (said.length) {
      const box = make("span", "ver-tags");
      said.forEach((tag, n) => {
        if (n) box.appendChild(apart());
        box.appendChild(make("span", tag === "the one" ? "tag one" : "tag", tag));
      });
      main.append(apart(), box);
    }
    if (note) main.append(apart(), make("span", "ver-note", note));
    const acts = make("div", "ver-acts");
    li.append(main, acts);
    return [li, acts];
  };
  const drawVersions = () => {
    $("versions").hidden = false;
    // The line: which version this is and its rating, then what it is, in a tag that wraps whole.
    const line = $("ver-line");
    line.textContent = "";
    line.appendChild(make("span", "", vHere ? [vName(vHere) + " of " + vTotal, vHere.label, vRating(vHere)]
      .filter(Boolean).join(" · ") : vCount(vTotal) + " on UG"));
    const what = vHere ? [vHere.chosen ? "the one" : "", vHere.gone ? "gone from UG" : ""]
      : [vOne && vOne.page === here ? "the one: " + vOne.label : ""];
    for (const tag of what.filter(Boolean)) line.append(apart(), make("span", tag === "gone from UG" ? "tag" : "tag one", tag));
    $("version-list-title").textContent = vCount(vTotal) + " on Ultimate Guitar";
    const acts = $("ver-acts");
    acts.textContent = "";
    if (vHere && !vHere.chosen && !vHere.gone) vAction(acts, "Make this the one", "choose", vHere.tab, true);
    // While a [pin] of yours chooses the sheet (the data's ``pinned``, the pin caracole versions --clear takes
    // out); on a page whose data has no ``pinned`` (written before it), while your choice isn't caracole's first.
    const pick = vRows.find((v) => !v.gone);
    const pinned = typeof vSource.pinned === "boolean" ? vSource.pinned : Boolean(vChosen && pick && pick !== vChosen);
    if (pinned) vAction(acts, "Back to caracole's pick", "clear", null, false);
    acts.hidden = acts.children.length === 0;
    const items = $("ver-items");
    items.textContent = "";
    if (vOne) items.appendChild(vItem(vOne.label, "", ["the one"], null, vOne.page, !vHere && vOne.page === here)[0]);
    for (const v of vRows) {
      const [li, todo] = vItem(vName(v) + (v.label ? " · " + v.label : ""), vRating(v),
        [v.chosen ? "the one" : v.page ? "kept" : "", v.gone ? "gone from UG" : ""],
        typeof v.note === "string" ? v.note : "", v.page && !v.gone ? v.page : null, v === vHere);
      if (!v.page && !v.gone) {
        if (!served && /^https:\/\//.test(String(v.url || ""))) {
          const ug = make("a", "link", "On UG");
          ug.setAttribute("href", v.url);
          todo.appendChild(ug);
        }
        vAction(todo, "Keep it", "keep", v.tab, false, li);
      }
      todo.hidden = todo.children.length === 0;
      items.appendChild(li);
    }
  };
  if (vOn) {
    drawVersions();
    $("ver-now").addEventListener("click", () => {
      if (inSight(vList)) {
        close(vList);
        return;
      }
      open(vList, $("ver-now"));
      const mine = vList.querySelector("[aria-current]");  // this page's, in sight
      if (mine) vList.scrollTop = Math.max(0, mine.parentElement.offsetTop - vList.clientHeight / 3);
    });
  }

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
  // A finger on a numeral shows its line (with numerals only, on any part of the chord), as the mouse over
  // one does; the chord's name, or a click, opens its card.
  let pointer = "mouse";
  document.addEventListener("pointerdown", (e) => { pointer = e.pointerType || "mouse"; }, true);
  sheet.addEventListener("click", (e) => {
    const el = e.target.closest(".c");
    if (!el) return;
    if (pointer !== "mouse" && el.querySelector(".nm") && (state.nm === "numerals" || e.target.closest(".nm"))) {
      showTip(el);
      return;
    }
    openCard(el.dataset.c, el);
    hear();
  });
  sheet.addEventListener("keydown", (e) => {
    const el = e.target.closest(".c");
    if (el && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openCard(el.dataset.c, el);
      hear();
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
  // The guitar in the bar shows the strip, or hides it, as the settings' chip does. The strip is above
  // the song: shown from further down, the page goes up to it, so the shapes are in view above the bar
  // (from there, a shape's card; back down by hand). Hidden, the page stays where it is.
  shapesButton.addEventListener("click", () => {
    state.strip = !state.strip;
    render();
    if (!state.strip) return;
    const strip = $("strip"), r = strip.getBoundingClientRect();
    if (r.top < 0 || r.bottom > bar.getBoundingClientRect().top) {
      strip.scrollIntoView({ block: "nearest", behavior: calm.matches ? "auto" : "smooth" });
    }
  });
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null, nm: null,
      necks: true, py: false });
    for (const i of Object.keys(atSeen)) delete atSeen[i];  // the version's shapes are for its own chords
    adopt(start);  // the song's own version, if it has one
    if (startInst) state.inst = startInst;  // and its instrument; else the instrument stays the player's
    keepNecks();  // the rail of necks back, on every sheet
    keepPinyin();  // and the pinyin off
    render();
    place();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the guitar; pressed again, it starts at
  // once), running, or paused. While it is on, the pill steers it, above the bar's place: − and +
  // change the speed as it runs, ❚❚ pauses and ▶ resumes (after a countdown again), × ends it; the
  // bar is out of the way while it counts down and runs (dock()). A finger on the page, the wheel, a
  // key that scrolls, a scroll by hand, a card opening or the end of the song pauses it: the page and
  // the bar are yours until you press ▶, which stays within reach with the card open.
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  // Pixels a second: a bigger text scrolls as much faster, so a speed keeps its pace through the song.
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start now", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;  // room under the song for the pill
    dock();  // the bar, away or back
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
        || !harmony.hidden || (vList && !vList.hidden)
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

  // Nothing to transpose, no shapes and no other setting for a sheet without chords: Aa and ▶ alone.
  $("keys").hidden = count === 0;
  shapesButton.hidden = count === 0;
  more.hidden = count === 0;
  showScroll();
  render();
  if (hash.get("panel") === "1") open(panel, null);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
