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
    ionian: ["Major", "bright, settled"],
    dorian: ["Dorian", "minor, brighter 6th"],
    phrygian: ["Phrygian", "minor, dark, Spanish half step"],
    lydian: ["Lydian", "major, dreamy, raised 4th"],
    mixolydian: ["Mixolydian", "major, bluesy, flat 7th"],
    aeolian: ["Minor", "natural minor"],
    locrian: ["Locrian", "tense, unstable"],
  };
  const FS = { min: 13, max: 30, step: 2, start: 18 };
  // The scroll's speed, 1 to 30: ``px`` pixels a second a step at the usual text size (see pace()).
  const SPEED = { min: 1, max: 30, start: 6, px: 2 };
  // The Harmony tab's tempo, in beats a minute: a chord a bar of four.
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
  // (/export.pdf), a version made the one or kept (/versions), a Guitar Pro file drawn in the browser (/guitar). From a
  // file they show the command to run, or the file itself, instead; and so in caracole's Android app, whose offline
  // copy of the library (androidx.webkit's WebViewAssetLoader, always at appassets.androidplatform.net) reads like
  // a file: no server answers there. The one place the page tells the two apart.
  const served = location.protocol !== "file:" && location.hostname !== "appassets.androidplatform.net";

  // --- the state: where the song is played, kept per page ------------------------------------
  // capo: the fret the capo is on (0 for none), or null for the sheet's own. It stays there
  // through a transposition, as on a guitar: the shapes move instead.
  // nm: the chord names as numerals beside them ("both") or in their place ("numerals"), null for the
  // chords alone; roles: the numerals in their families' colours; necks: the rail of necks shown, on a screen
  // wide enough for it; py: each Chinese character's reading over it (pinyin), on a sheet with Chinese; trad: its
  // Chinese in Traditional characters, else in Simplified ones.
  // inst: the instrument the chords are drawn and heard for (data.instruments' id), the player's: kept once for every
  // page, as the rail of necks is.
  const state = { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null, fs: FS.start, shapes: null,
    speed: SPEED.start, nm: null, roles: true, kn: "scale", bpm: BPM.start, vol: VOL, necks: true, py: false,
    trad: false, inst: "guitar" };
  // Where its settings are kept: the page's name, or the one a songbook gives its song (book.js songStore).
  const store = typeof data.store === "string" && data.store ? data.store : "caracole-viewer:" + location.pathname;
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
  // Where an address (or the song's own version) plays the song: what it names of it, into the state (or ``into``).
  const adopt = (params, into = state) => {
    if (params.has("alt")) into.alt = swapsOf(params.get("alt"));
    if (params.has("at")) {
      into.at = positionsOf(params.get("at"));
      if (into === state) keptAt = null;  // the address says which
    }
    if (params.has("t")) into.t = clampT(params.get("t"));
    if (validMode(params.get("mode"))) into.mode = params.get("mode");
    if (params.has("capo")) into.capo = fretOf(params.get("capo"));
    if (params.has("nm")) into.nm = nmOf(params.get("nm"));
  };
  // The song's own version (overrides.toml's [version], "Make this my version"), which its PDF is in: the page
  // starts there when its address names no version of its own, and Reset all goes back there.
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
      if (typeof saved.shapes === "boolean") state.shapes = saved.shapes;  // an old record's `strip` says nothing
    }
  } catch (err) { /* no storage: the page still works */ }
  // The screen's choices screen.js keeps for every viewer page (the theme, Aa's), applied before this script ran, and
  // its key map, which this script binds (below): inlined on every viewer page, so never missing.
  const screenKit = window.caracoleScreen;
  // The rail of necks is the screen's choice, not a song's: kept once for every sheet, songbook and harmonica tab's
  // page (a name no page's own settings have, as theirs end in its path: overlay.js's), and in the address too, where
  // there is no storage.
  const overlay = window.caracoleOverlay || null;
  const NECKS = overlay ? overlay.NECKS : "caracole-viewer-necks";
  // Each such choice: the one a link names (followed, typed), else the browser's where it keeps one, else the
  // address's. A page come back to (a reload, Back or Forward, a tab restored, a songbook's next song) has an address
  // written before: there the browser's wins over it, and the address counts only where it keeps none (a server's
  // sandbox, a choice never made in this browser).
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
  if (choiceOf(NECKS, hash.get("necks") === "0" ? "hidden" : null) === "hidden") state.necks = false;
  const keepNecks = () => {
    try {
      localStorage.setItem(NECKS, state.necks ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // So is pinyin over the Chinese (the settings' Pinyin): the reader's, kept once for every page, and in the
  // address while it is on (py=1, as it starts off).
  const PINYIN = "caracole-viewer-pinyin";
  if (choiceOf(PINYIN, hash.get("py") === "1" ? "shown" : null) === "shown") state.py = true;
  const keepPinyin = () => {
    try {
      localStorage.setItem(PINYIN, state.py ? "shown" : "hidden");
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  // So are the characters the Chinese is shown in (the settings' Chinese characters): kept once for every page, and
  // in the address while they are Traditional (trad=1, as they start Simplified).
  const HANZI = "caracole-viewer-hanzi";
  if (choiceOf(HANZI, hash.get("trad") === "1" ? "traditional" : null) === "traditional") state.trad = true;
  const keepHanzi = () => {
    try {
      localStorage.setItem(HANZI, state.trad ? "traditional" : "simplified");
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
  const instChosen = choiceOf(INSTRUMENT, drawn(instOf(hash.get("inst"))) ? hash.get("inst") : null);
  if (drawn(instOf(instChosen))) state.inst = instChosen;
  else if (drawn(instOf(hash.get("inst")))) state.inst = hash.get("inst");  // kept: one this page doesn't draw
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
      // At the song's own version, where the page opens, nobody chose one here: the address names none, so that the
      // page made again in another own version (Make mine elsewhere, a songbook's setting) opens in that one. Away
      // from it, or on another instrument than the one it names, t always: an address naming none would start in the
      // own version (and on its instrument) again.
      const chosen = !data.start || musicOf(state) !== musicOf(startVersion())
        || (startInst !== null && state.inst !== startInst);
      keep("t", state.t, chosen && (Boolean(data.start) || state.t !== (Number(data.transpose) || 0)));
      keep("mode", state.mode, chosen && state.mode !== null);
      keep("capo", state.capo, chosen && state.capo !== null);
      keep("nm", state.nm, state.nm !== null);
      keep("alt", swapsText(state.alt), chosen && swapsText(state.alt) !== "");
      keep("at", Object.keys(state.at).map((i) => i + "." + state.at[i]).join(","),
        chosen && Object.keys(state.at).length > 0);
      keep("fs", state.fs, state.fs !== FS.start);
      keep("speed", state.speed, state.speed !== SPEED.start);
      keep("vol", state.vol, state.vol !== VOL);
      keep("necks", "0", !state.necks);
      keep("py", "1", state.py);
      keep("trad", "1", state.trad);
      keep("inst", state.inst, state.inst !== "guitar" || Boolean(startInst));
      screenKit.carry(params);  // the theme while it isn't Auto, the minutes the screen stays on while they aren't 10
      const fragment = params.toString();
      if (fragment !== location.hash.slice(1)) {
        history.replaceState(history.state, "", fragment ? "#" + fragment : location.pathname + location.search);
      }
    } catch (err) { /* an address the page can't change */ }
    exportLink();
    if (kinds) kinds.links();  // each link to another version, with the text size and the screen's choices now
  };

  // Export PDF of this version, named at its right ("D Dorian, capo 2"): served, a link to the PDF itself for this very
  // address (caracole serve's /export.pdf, which answers it as a download: the sandbox allows downloads, and the page
  // stays where it is); from a file, a row that unfolds the command that makes it, with Copy.
  const exportLink = () => {
    const link = $("export");
    const cmd = $("export-cmd");
    if (!link || !cmd) return;
    // A Chinese sheet's export is in the characters its Chinese is shown in (render.py: trad=1, its label says so)
    const traditional = Boolean(data.hanzi) && state.trad;
    const words = versionWords().filter(Boolean).concat(traditional ? ["Traditional"] : []).join(", ");
    for (const v of $("export-row").querySelectorAll(".export-v")) v.textContent = words;
    const version = new URLSearchParams(location.hash.slice(1));
    if (!traditional) version.delete("trad");
    // What an export is asked for is the page's to say, never the address's: Make mine alone adds mine=1.
    for (const name of ["mine", "sheet"]) version.delete(name);
    if (!served) {
      const quoted = (text) => "'" + text.replace(/'/g, "'\\''") + "'";
      for (const name of ["fs", "speed", "vol", "necks", "py", "theme", "awake"]) version.delete(name);
      cmd.textContent = "caracole render --song " + songNamed()
        + " --version " + quoted(version.toString().replace(/%2C/g, ","));
      link.hidden = true;
      $("export-fold").hidden = false;
      cmd.hidden = false;
      $("export-copy").hidden = false;
      $("export-hint").textContent = "Run this where caracole is installed. The PDF lands beside the sheet. "
        + "With --mine it becomes your version: the song's PDF, sheet and songbooks start there.";
      return;
    }
    const query = new URLSearchParams();
    query.set("sheet", sheetPath());
    version.forEach((value, name) => query.append(name, value));
    link.setAttribute("href", "/export.pdf?" + query.toString());
  };
  // What of where the song is played makes its music (the key, the mode, the capo, the chords swapped in that mode and
  // the shapes chosen), never how it is read (the text size, the scroll, the chord names, the necks, the pinyin, the
  // strum, and the instrument, the player's): two states that play the song alike say the same.
  const musicOf = (s) => {
    const mode = key ? s.mode || key.mode : "";
    const swaps = (s.alt && s.alt[mode]) || {};
    const alt = Object.keys(swaps).filter((i) => Array.isArray(swaps[i])).sort((a, b) => a - b)
      .map((i) => [i].concat(swaps[i]).join("."));
    const at = Object.keys(s.at || {}).filter((i) => Number(s.at[i]) > 0).sort((a, b) => a - b)
      .map((i) => i + "." + s.at[i]);
    return [s.t, mode, s.capo === null ? sheetCapo : s.capo, alt.join(","), at.join(",")].join("|");
  };
  // The song's own version, where the page opens with no version in its address (data.start over the sheet at its
  // [transpose]), or the one made the song's own on this page since (Make mine), which its job saves: where Reset all
  // goes back to (``ownVersion``).
  let madeMine = null;
  function startVersion() {  // the one the page was written with
    const mine = { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null };
    adopt(start, mine);
    return mine;
  }
  const ownVersion = () => (madeMine !== null ? JSON.parse(JSON.stringify(madeMine)) : startVersion());
  const ownMusic = () => musicOf(ownVersion());
  // Served, Export PDF pressed on a version other than the song's own asks first: make it your version too (the
  // download with mine=1, which queues `caracole render --mine`: its PDF, its viewer and its songbooks then start
  // there), just download it, or neither. A modal dialog, the song dimmed under it: its focus goes round within it, and
  // Escape, ×, Cancel or a tap beside its box closes it, the focus back on Export PDF. On the song's own, the download
  // at once.
  const ask = $("export-ask");
  if (ask && $("export")) {
    const title = (document.querySelector("h1") || {}).textContent || "";
    $("export").addEventListener("click", (e) => {
      if (!served || musicOf(state) === ownMusic()) return;
      e.preventDefault();
      const href = $("export").getAttribute("href");
      $("ask-title").textContent = "Make this your version of " + title + "?";
      $("ask-version").textContent = versionWords().filter(Boolean).join(", ");
      $("ask-just").setAttribute("href", href);
      $("ask-mine").setAttribute("href", href + "&mine=1");
      open(ask, $("export"), true);
      $("ask-title").focus({ preventScroll: true });
    });
    ask.addEventListener("click", (e) => {
      if (e.target === ask) close(ask);  // beside its box: the backdrop
    });
    for (const id of ["ask-x", "ask-cancel", "ask-just"]) $(id).addEventListener("click", () => close(ask));
    $("ask-mine").addEventListener("click", () => {
      madeMine = JSON.parse(JSON.stringify({ t: state.t, mode: state.mode, alt: state.alt, at: state.at,
        capo: state.capo }));
      close(ask);
    });
    // However it closes (Escape, ×, Cancel, the backdrop, an answer), it leaves the stack and its entry goes.
    ask.addEventListener("close", () => {
      if (ask.open) return;  // the event of an earlier close, come after it opened again
      const at = layers.findIndex((layer) => layer.el === ask);
      const opener = at >= 0 ? layers.splice(at, 1)[0].opener : null;
      restack();
      const active = document.activeElement;
      if (opener && opener.isConnected && (!active || active === document.body || ask.contains(active))) opener.focus({ preventScroll: true });
    });
    ask.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();  // it closes, and nothing under it
        e.preventDefault();
        close(ask);  // at once, the focus back on Export PDF
        return;
      }
      if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
      const mine = Array.from(ask.querySelectorAll(FOCUSABLE)).filter(reachable);
      const here = mine.indexOf(document.activeElement);
      const to = e.shiftKey ? (here <= 0 ? mine[mine.length - 1] : null) : (here === mine.length - 1 ? mine[0] : null);
      if (!to) return;
      e.preventDefault();
      to.focus();
    });
  }
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

  // The YouTube video an auto sheet's audio came from (``video``, render.py), under the notice: YouTube's mark (its
  // icon, a data: URI, else its letters, as the library page draws a source: rows.js sourceMark), named "from YouTube"
  // for a screen reader; the video's title, a plain link to it, in this tab, as the page's other links (the sandbox
  // caracole serve gives the page opens no other window); its channel, muted. A watch address alone is a link.
  (() => {
    const box = $("credit");
    const video = data.video && typeof data.video === "object" ? data.video : null;
    const WATCH = /^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/;
    if (!box || !video || typeof video.href !== "string" || !WATCH.test(video.href)) return;
    const info = video.mark && typeof video.mark === "object" ? video.mark : {};
    const named = "from " + String(info.name || "YouTube");
    let mark;
    if (typeof info.src === "string" && /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(info.src)) {
      mark = document.createElement("img");
      mark.className = "source";
      mark.setAttribute("src", info.src);
      mark.setAttribute("alt", named);
      mark.setAttribute("width", "16");
      mark.setAttribute("height", "16");
    } else {
      mark = document.createElement("span");
      mark.className = "source letters";
      mark.textContent = String(info.letters || "YT");
      mark.setAttribute("role", "img");
      mark.setAttribute("aria-label", named);
    }
    mark.title = named;
    box.appendChild(mark);
    const a = box.appendChild(document.createElement("a"));
    a.setAttribute("href", video.href);
    a.textContent = String(video.title || "the video");
    if (typeof video.channel === "string" && video.channel) {
      const channel = box.appendChild(document.createElement("span"));
      channel.className = "channel";
      channel.textContent = video.channel;
    }
    box.hidden = false;
  })();

  // --- naming chords -------------------------------------------------------------------------
  const modeNow = () => (key ? state.mode || key.mode : "");
  const asWritten = () => !state.mode || (key && state.mode === key.mode);
  const sheetCapo = Number(data.capoSheet) || 0;
  const inst = () => (drawn(instOf(state.inst)) ? instOf(state.inst) : instOf("guitar") || INSTRUMENTS[0]);
  // An instrument in words, as version.py's instrument_words says it: "baritone ukulele", "low-G ukulele".
  const instWords = (i) => (i.id === "ukulele-low-g" ? "low-G ukulele" : String(i.name).toLowerCase());
  // An instrument with no capo (the piano) plays the chords as they sound: the capo folded in, the chords named a
  // capo's frets up, the key the one the song sounds in. The capo set stays, for the guitar.
  const takesCapo = () => inst().capo !== false;
  const capoNow = () => (!takesCapo() ? 0 : state.capo === null ? sheetCapo : state.capo);
  const saysNoCapo = () => takesCapo() && sheetCapo > 0;  // "no capo", on an instrument that could take the sheet's
  // The chords are named for the shapes played: with another capo, as many semitones off.
  const shift = () => state.t - (capoNow() - sheetCapo);
  const wrapT = (t) => (t > 11 ? t - 12 : t < -11 ? t + 12 : t);
  // How far the chords you see moved from the sheet as written, by your hand, in semitones: the shapes' move on an
  // instrument that takes a capo (so a sheet's capo taken off moves them up as many frets: "no capo · +2"), the
  // transposition alone on one that takes none (the sheet's capo folded in is no move of yours). Within an octave, as
  // the bar, the settings and the header's Key say it (whatever the count, the remainder: 26 is "+2"); 0 for none.
  const moved = () => {
    const s = takesCapo() ? shift() : state.t;
    return s - 12 * Math.trunc(s / 12);
  };
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
  // (a ukulele), its Easy keys instead; on one with no capo (the harmonica, the winds), none.
  const capoHints = () => (key && takesCapo() && !inst().shapes ? data.capo[modeNow()][mod12(state.t)] : []);
  // Where the song is played, as Cifra Club's key line says it: with a capo, the key of the
  // shapes, the capo and the key the song sounds in ("Em shapes · capo 2 · sounds F#m"), as
  // "Key Em" alone would read as the song's key; with none, the key. Each part is
  // [before, in bold, after, where the key came from]; ``after`` follows the shapes with a capo, the key with none
  // (how far the chords you see moved: never by the key it sounds in, which a capo may keep). keyLabel's,
  // as the PDF's line under the title is (page.py key_line_text); the header says it on two lines,
  // Capo and Key (keyFacts).
  const keyLine = (after) => {
    const capo = capoNow();
    if (!key) return capo ? [["Capo ", String(capo), "", ""]] : saysNoCapo() ? [["No capo", "", "", ""]] : [];
    const sounds = keyName(state.t + sheetCapo);
    if (!capo) return [["Key ", sounds, after, key.from]].concat(saysNoCapo() ? [["no capo", "", "", ""]] : []);
    return [["", keyName(shift()), " shapes" + after, ""], ["capo ", String(capo), "", ""], ["sounds ", sounds, "", ""]]
      .concat(key.from ? [["", "", "", "key " + key.from]] : []);
  };
  // The same as one line of text, for a screen reader in the bar (``withMove``: with how far the chords moved,
  // moved()): with a capo, the move by the shapes ("Ab shapes (+1) · capo 2 · sounds Bb"); with none, last ("Key A ·
  // no capo · +2"); without a key, Transpose, then the capo and the move in the bar's order ("Transpose · no capo ·
  // +1").
  const keyLabel = (withMove) => {
    const move = withMove && moved() ? signed(moved()) : "";
    if (!key) return ["Transpose"].concat(capoWords(), move ? [move] : []).join(" · ");
    const byShapes = capoNow() > 0;
    return keyLine(move && byShapes ? " (" + move + ")" : "").filter((part) => part[1] || !part[3])
      .map((part) => part[0] + part[1] + part[2]).concat(move && !byShapes ? [move] : []).join(" · ");
  };
  // The header's Key line, in keyLine's parts, with no capo in it (its Capo line says it), as page.py's facts_html
  // writes it for the sheet as written: with no capo the key the song sounds in ("A · from the tab"); with one the key
  // of the shapes and the key it sounds in ("G shapes · sounds A · key from the tab"); ``after``, how far the chords
  // moved (moved(), " (+1)"), after the key with no capo ("A (+2)"), after the shapes with one ("Ab shapes (+1) ·
  // sounds A"): the move is the chords', never the sound's.
  const keyFacts = (after) => {
    const sounds = keyName(state.t + sheetCapo);
    if (!capoNow()) return [["", sounds, after, key.from]];
    return [["", keyName(shift()), " shapes" + after, ""], ["sounds ", sounds, "", ""]]
      .concat(key.from ? [["", "", "", "key " + key.from]] : []);
  };
  // The header's Tuning line: the instrument's open strings, in the order its box draws them, each named as a sheet
  // with no key names a note (data.names[""]): the guitar's "E A D G B E", a ukulele's "G C E A"; on the guitar the
  // tuning the sheet's notes name (data.tuningName, "Drop D"), as its PDF says it. "" on one with no strings (the
  // piano, the harmonica, the winds).
  const tuningNow = () => {
    const i = inst();
    if (i.kind !== "strings") return "";
    if (i.id === "guitar" && typeof data.tuningName === "string" && data.tuningName) return data.tuningName;
    const plain = String((data.names && data.names[""]) || "").split(" ");
    const notes = (Array.isArray(i.tuning) ? i.tuning : []).map((n) => plain[mod12(n)] || "");
    return notes.length && notes.every(Boolean) ? notes.join(" ") : "";
  };
  // What changed the chords you see from the sheet as written, in words: the capo that plays them ("capo 2"; "no
  // capo" for a sheet's capo taken off), then how far they moved (moved(): "+2").
  const capoWords = () => (takesCapo() && capoNow() > 0 ? ["capo " + capoNow()] : saysNoCapo() && capoNow() === 0
    ? ["no capo"] : []);
  const changes = () => capoWords().concat(moved() ? [signed(moved())] : []);
  // In short, for the bar, between − and +: [the key you play, the words under it, whether you changed it]. The key of
  // the shapes ("Transpose" for a sheet with no key), and under it what changed (changes()), else "key"
  // (["G", ["capo 2"], false], ["A", ["no capo", "+2"], true], ["Cm", ["key"], false]); changed once you moved the
  // chords or the capo, the words then in the accent. The key it sounds in is the key line's.
  const keyShort = () => {
    const words = changes();
    return [key ? keyName(shift()) : "Transpose", words.length ? words : key ? ["key"] : [],
      moved() !== 0 || (takesCapo() && capoNow() !== sheetCapo)];
  };
  // What is set, in words, as version.py's played_label names a version: the key of the shapes played, in the mode
  // played ("D Dorian"; on an instrument with no capo, the key the song sounds in, the capo folded in), or how far a
  // sheet with no key moved ("As written", "Transposed +2"); and the capo, where there is one ("capo 2"), else "".
  const versionWords = () => {
    const s = shift(), by = takesCapo() ? state.t : s;
    const words = key ? names(s)[mod12(key.tonic + s)] + " " + (MODES[modeNow()] || [modeNow()])[0]
      : by ? "Transposed " + signed(by) : "As written";
    return [words, capoNow() ? "capo " + capoNow() : ""];
  };
  // The key in short and the line under it, fitted to the room between − and +. The key a little
  // smaller where it is too long ("Ab mixolydian" at 360 px), down to three quarters of its size, then
  // cut short. The line whole where there is room ("capo 2 · +1"); on the narrowest, each word on a line
  // of its own, "capo 2" over "+1", so that neither is cut off. Fitted again when the bar comes back into
  // view or the window changes. Measured to the fraction of a pixel, which scrollWidth rounds away: a line
  // 0.4 px too wide would end in an ellipsis.
  let keyUnder = [[], false];
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
    const [words, changed] = keyUnder;
    line.classList.remove("stack");
    line.classList.toggle("changed", changed);
    line.textContent = words.join(" · ");
    if (words.length > 1 && tooWide(line)) {
      line.textContent = "";
      for (const part of words) {
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
      return { list, note: "", mine: 0, each: list.map((_, k) => INVERSIONS[k] + " · " + bass + " in the bass, left hand") };
    }
    if (it.kind !== "strings") return { list: [], note: "", mine: 0 };
    if (it.shapes) {
      const near = it.near && own.call(it.near, rep[3]) ? it.near[rep[3]] : null;
      const quality = near === null ? rep[3] : near;
      const table = data.voicings[it.shapes + quality];
      const list = table ? table[mod12(pc + (Number(it.offset) || 0))] || [] : [];
      let note = rep[4] || near !== null ? "No shape for this chord. Closest: " + n[pc] + qualityName(quality) + "." : "";
      if (rep[2] !== null) note = (note ? note + " " : "") + "Without its bass, " + n[mod12(rep[2] + s)] + ".";
      return { list, note, mine: 0 };
    }
    const which = pc + "," + rep[1] + "," + (rep[2] === null ? "" : mod12(rep[2] + s));
    const given = data.shapes && own.call(data.shapes, which) ? data.shapes[which] : { list: null, mine: 0 };
    const slash = rep[5] && data.voicings[rep[5]] ? data.voicings[rep[5]][pc] : null;
    if (slash && slash.length) return { list: given.list || slash, note: "", mine: given.mine };
    const list = data.voicings[rep[3]] ? data.voicings[rep[3]][pc] || [] : [];
    let note = "";
    if (rep[4]) note = "No shape for this chord. Closest: " + n[pc] + qualityName(rep[3]) + ".";
    if (rep[2] !== null) note = (note ? note + " " : "") + "Play " + n[mod12(rep[2] + s)] + " in the bass.";
    return { list: given.list || list, note, mine: given.mine };
  };
  // A position as its instrument draws it (instruments.js): a chord box, or a keyboard (``span``: every position of
  // the chord, so the card keeps its width from one to the next); the strip's (bare) leave the fingers out, too
  // small to read there.
  const diagram = (position, title, bare, span) => (inst().kind === "keys"
    ? kit.keyboard(position, title, bare, span) : kit.box(position, title, bare));

  // The screen's choices, kept once for every page (the rail of necks hidden, the pinyin shown, the Chinese in
  // Traditional characters, the instrument, and screen.js's: the theme, the minutes the screen stays on), set in
  // ``params`` as the address keeps them: a link to another page of the song takes them on (a version's in the list, a
  // harmonica tab's page, and back), so that where the browser keeps nothing (caracole serve's sandbox) they go with
  // it.
  function screenChoices(params) {
    if (!state.necks) params.set("necks", "0");
    if (state.py) params.set("py", "1");
    if (state.trad) params.set("trad", "1");
    if (state.inst !== "guitar") params.set("inst", state.inst);
    return screenKit.carry(params);
  }

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
    const carry = screenChoices(new URLSearchParams()).toString();
    return Object.freeze({ data, instrument: inst(), mode: modeNow(), shift: s, key: key ? keyName(s) : "",
      names: Object.freeze(names(s)), chords: Object.freeze(chords), carry: carry ? "#" + carry : "" });
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
  // Its line in the header's facts, under the Key line (drawFacts): "" for none.
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
  // The Instrument menu, what it says of the one chosen (its title), and what follows the instrument in the settings:
  // Capo on one that takes a capo; Easy keys, nearest the key played first, on one that has them (instruments.py EASY:
  // the ukulele's C, F, G, Bb, Am, Dm), each moving the song there as Transpose does; the row an instrument's script
  // fills. The menu's options are made again only when the instruments offered change (one registered).
  function drawInstruments() {
    const offered = INSTRUMENTS.filter(drawn);
    $("inst-row").hidden = offered.length < 2;
    const menu = $("insts"), ids = offered.map((i) => i.id).join(" ");
    if (menu.dataset.ids !== ids) {
      menu.autocomplete = "off";  // never the browser's restored choice on Back: the one kept for every page
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
    $("easy-hint").textContent = table.length ? "Keys that sit well on the " + instWords(inst())
      + ". Each transposes the song there." : "";
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
  const bar = $("bar"), panel = $("panel"), card = $("card"), pill = $("pill"), go = $("go");
  // From 1200 px the bar is a toolbar under the song's title (layers.js's toolbar: right after the song's header, a
  // songbook's shown song's own; viewer.css), back at the foot below it.
  const toolbar = window.caracoleLayers ? window.caracoleLayers.toolbar(bar, () => sheetEl.parentElement
    .querySelector(":scope > header.head")) : { wide: window.matchMedia("not all"), place() {}, edge() {},
    room: () => ({ top: 0, bottom: window.innerHeight }) };
  const vList = $("version-list");  // a sheet's versions (below); the songbook has none
  let kinds = null;  // its line and its list, kinds.js's (below)
  const keyList = $("key-list"), keyNow = $("key-now");  // the twelve keys, and the bar's key that opens them (below)
  // From 900 px wide, beside the song, one at a time: the settings, the key list.
  const rails = [panel, keyList].filter(Boolean);
  const more = $("more"), sizes = $("sizes"), sizeButton = $("size");
  const handle = $("handle");  // full screen's, at the window's foot (below)
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
  // The song's facts under its title as it is played, drawn again on every change in page.py's facts_html markup
  // (which writes them for the sheet as written, on the guitar), so that nothing moves as the script runs: a
  // div.fact a line, named by its data-fact, a dt and a dd. Tuning on an instrument with strings (tuningNow), Capo on
  // one that takes a capo ("none", or its fret), Key where the sheet has one (keyFacts, how far the chords you see
  // moved said after the key it sounds in, as the bar says it: " (+1)"), and the instrument's own line where its
  // script gives one (instruments.js register's header), the instrument's name its label: "Harmonica  G harp (1st
  // position) · C harp (2nd)". A sheet with no chords (a tab alone), with nothing to transpose or to play on another
  // instrument, keeps what page.py wrote: its Capo line as written, where it names a capo, else no facts.
  const drawFacts = () => {
    const box = $("facts");
    if (!box || count === 0) return;
    box.textContent = "";
    const fact = (name, label) => {
      const row = box.appendChild(document.createElement("div"));
      row.className = "fact";
      row.dataset.fact = name;
      row.appendChild(document.createElement("dt")).textContent = label;
      return row.appendChild(document.createElement("dd"));
    };
    const strings = tuningNow();
    if (strings) fact("tuning", "Tuning").textContent = strings;
    if (takesCapo()) fact("capo", "Capo").textContent = capoNow() ? String(capoNow()) : "none";
    if (key) {
      const said = fact("key", "Key");
      keyFacts(moved() ? " (" + signed(moved()) + ")" : "").forEach((f, n) => {
        if (n) said.appendChild(document.createTextNode(" · "));
        if (f[0]) said.appendChild(document.createTextNode(f[0]));
        if (f[1]) said.appendChild(document.createElement("b")).textContent = f[1];
        if (f[2]) said.appendChild(document.createTextNode(f[2]));
        if (f[3]) {
          if (f[0] || f[1]) said.appendChild(document.createTextNode(" · "));  // "A · from the tab"
          const from = said.appendChild(document.createElement("span"));
          from.className = "from";
          from.textContent = f[3];
        }
      });
    }
    const line = headerLine();
    if (line) fact("inst", String(inst().name || inst().id)).textContent = line;
  };
  // The key's whole line said to a screen reader as it moves (#key-status, a status line outside the bar: the key is
  // the key list's button, no live region): as − and + move it. Nothing as the page opens (its first line is where it
  // starts) nor for a render that moves nothing (the text size); and nothing where something else says it: the
  // settings' Transpose and Capo (outputs) while they are open, and the key's own name as a key chosen from the list
  // gives it the focus back (``keyQuiet``). Then the line is cleared, so the next one said is a change, even to the
  // line said last.
  let keySaid = null, keyQuiet = false;
  const sayKey = (line) => {
    if (keySaid === null || line === keySaid) {
      keySaid = line;
      return;
    }
    keySaid = line;
    $("key-status").textContent = keyQuiet || !panel.hidden ? "" : line;
  };
  // Aa's theme, the one screen.js has pressed.
  const drawTheme = () => {
    for (const b of $("theme").querySelectorAll("button")) {
      b.setAttribute("aria-pressed", b.id === "theme-" + screenKit.theme() ? "true" : "false");
    }
  };
  // More's Keep the screen on: the minutes screen.js keeps for every page, Off to 60, each end greyed where it stops
  // (aria-disabled, as Aa's text size: a button pressed to its end keeps the focus).
  const drawAwake = () => {
    const n = screenKit.minutes(), all = screenKit.MINUTES;
    $("awake-at").textContent = n ? n + " min" : "Off";
    $("awake-down").setAttribute("aria-disabled", n <= all[0] ? "true" : "false");
    $("awake-up").setAttribute("aria-disabled", n >= all[all.length - 1] ? "true" : "false");
  };
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
    drawTheme();
    drawAwake();

    const [main, words, changed] = keyShort();
    $("key-now").querySelector(".k").textContent = main;
    keyUnder = [words, changed];
    fitKey();
    $("key-full").textContent = keyLabel(true);
    sayKey(keyLabel(true));
    drawHead();
    drawFacts();

    // The settings' Transpose says it as the bar does: the key over its words; with no key, how far the chords moved.
    $("shift").querySelector(".k").textContent = key ? main : signed(moved());
    $("shift").querySelector(".d").textContent = key ? words.join(" · ") : "";
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
    drawSpeed();
    drawStrip();
    drawWords();  // the words in the characters chosen, with their readings: the Harmony tab names its sections so
    drawNecks();  // before layout(), which measures the song beside the rail
    layout();  // fit() too
    drawHeadings();
    if (!keyList.hidden) drawKeyList();  // the key played pressed, the keys named in the mode played
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
  const CHORD_SPACE = 0.45;  // em: the room a chord keeps after it, before the next one or the line's edge
  const fit = () => {
    sheetEl.classList.add("tight");
    for (const y of sheetEl.querySelectorAll(".s > .y")) {
      y.style.minWidth = "";
      y.style.removeProperty("--ink");
      y.classList.remove("ext");
    }
    const space = parseFloat(getComputedStyle(sheetEl).fontSize) * CHORD_SPACE;
    for (const line of sheetEl.querySelectorAll(".l")) {
      const kids = Array.from(line.querySelectorAll(".s, .w"));  // its columns, a word's group's (.word) among them
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
        if (width) {
          col.lastElementChild.style.minWidth = Math.ceil(width) + "px";
          // The gap opened inside a word ("wo[G][D]rd"): a leader fills it, so the word reads as one.
          const after = kids[k + 1];
          if (after && after.parentElement === col.parentElement && col.parentElement.classList.contains("word")) {
            const y = col.lastElementChild;
            const ink = document.createRange();  // where the column's own text ends: the leader starts there
            ink.selectNodeContents(y);
            y.style.setProperty("--ink", Math.ceil(ink.getBoundingClientRect().width) + "px");
            y.classList.add("ext");
          }
        }
      });
    }
  };
  // The song's widest line, in px, as it would run unwrapped: each line of its sections (sung, of chords, a row of
  // bar cells) and each tab for a moment as wide as its content (viewer.css .measure), a chord past the end of its
  // line's words with the room a chord keeps after it. The notes before the song (.pre) wrap, and count for none.
  const widest = () => {
    sheetEl.classList.add("measure");
    const space = parseFloat(getComputedStyle(sheetEl).fontSize) * CHORD_SPACE;
    let most = 0;
    for (const row of sheetEl.querySelectorAll(".sec > .l, .sec > .tab")) {
      const box = row.getBoundingClientRect();
      let right = box.right;
      for (const head of row.querySelectorAll(".s > .c, .s > .m")) {
        right = Math.max(right, head.getBoundingClientRect().right + space);
      }
      most = Math.max(most, right - box.left);
    }
    sheetEl.classList.remove("measure");
    return most;
  };
  // One column, or columns side by side where viewer.css offers them (a wide screen), only for a song the window
  // then shows whole: the song's end in the last column, and the sheet no taller than the window less the room the
  // page keeps at its foot for the controls and, from 1200 px, the toolbar's at its top (--toolbar). The fewest
  // columns that do, from two up to as many as fit side by side (MOST_COLUMNS at most), each at least as wide as the
  // song's widest line within COLUMN_EM: at least 16 em, so that a song of short lines makes no slivers, and never
  // asked to be more than 24 em, so that a song of long lines reads as it did in two (the owner's narrower columns,
  // D8), its long lines wrapping. The columns share the page's width
  // (viewer.css): the room over widens each. At the reader's own text size, never a smaller one to fit; one column is
  // 3 px larger, and so is a song no count shows whole.
  const MOST_COLUMNS = 5;  // viewer.css lays out two to five
  const COLUMN_EM = [16, 24];  // a column's least width, of a song of short lines and of long ones
  // fit() in one column ``px`` wide: as in a column of that width, without laying the columns out again (and
  // balancing them) for each chord it moves.
  const fitIn = (px) => {
    sheetEl.style.columnCount = "1";
    sheetEl.style.width = px + "px";
    fit();
    sheetEl.style.width = "";
    sheetEl.style.columnCount = "";
  };
  // The toolbar's room at the window's top, from 1200 px where it shows (none in full screen): its height, viewer.css's
  // --toolbar (no such token below 1200 px).
  const toolbarRoom = () => (toolbar.wide.matches && !doc.dataset.full
    ? parseFloat(getComputedStyle(doc).getPropertyValue("--toolbar")) || 0 : 0);
  const layout = () => {
    const y = window.scrollY;
    let count = 1;
    doc.dataset.columns = "2";
    if (getComputedStyle(sheetEl).columnCount === "2") {  // offered here
      // The page's width for columns, the song across it in one at the reader's own size: its lines measured there.
      sheetEl.style.columnCount = "1";
      fit();
      const line = widest();
      const width = sheetEl.getBoundingClientRect().width;
      sheetEl.style.columnCount = "";
      const em = parseFloat(getComputedStyle(sheetEl).fontSize);
      const least = Math.min(COLUMN_EM[1] * em, Math.max(COLUMN_EM[0] * em, line));
      const page = sheetEl.closest(".page") || document.body;
      const room = window.innerHeight - (parseFloat(getComputedStyle(page).paddingBottom) || 0) - toolbarRoom();
      for (let n = 2; n <= MOST_COLUMNS; n++) {
        doc.dataset.columns = String(n);
        const gap = parseFloat(getComputedStyle(sheetEl).columnGap) || 0;
        const column = (width - (n - 1) * gap) / n;
        if (column < least - 0.5) break;  // n such columns don't fit side by side
        if (line > column) fitIn(column);  // its long lines wrap in these: their chords fitted where they wrap
        const box = sheetEl.getBoundingClientRect();
        const end = sheetEl.lastElementChild && sheetEl.lastElementChild.lastElementChild;
        const last = box.left + (n - 1) * (box.width + gap) / n;  // where the last column starts
        if (end && end.getBoundingClientRect().left > last - gap / 2 && box.height <= room) {
          count = n;
          break;
        }
      }
    }
    if (count === 1) {
      doc.dataset.columns = "1";
      fit();
    }
    // Columns are shorter than one: measuring them may have moved the page. Back to where it was.
    if (window.scrollY !== y) window.scrollTo(0, y);
  };
  let fitting = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(fitting);
    fitting = requestAnimationFrame(() => {
      layout();
      fitKey();
      fitKeys();
      place();
      placeTip();
      dock();
      toolbar.edge();
    });
  });
  // Across 1200 px the bar moves: under the title as a toolbar, or back at the foot, never slid away there.
  toolbar.wide.addEventListener("change", () => {
    toolbar.place();
    slide(false);
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { layout(); fitKey(); }, () => {});
  // The tab's preamble opened or folded again (page.py): the song moves, and may take other columns,
  // or none; an open card goes with its chord.
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

  // The strip of every chord's shape: shown by default where no rail holds the shapes (below 1200 px), else by its
  // switch; the song's own choice, kept, wins either way.
  const stripShown = () => (state.shapes === null ? !railWide.matches : state.shapes);
  const drawStrip = () => {
    const strip = $("strip");
    const on = stripShown();
    strip.hidden = !on;
    strip.textContent = "";
    $("strip-toggle").setAttribute("aria-pressed", on ? "true" : "false");
    if (!on) return;
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
  // capo, the frets count from it, as the chords' necks do. The Harmony tab's first (overlay.js draws it), or the
  // Guitar tab's on a sheet with no Harmony tab or an instrument with no neck (the guitar's then, at its capo). Scale
  // or Pentatonic switches it; the overlay's draw keeps the focus on the switch (its data-f).
  const keySpec = (s = shift(), it = inst()) => ({
    name: keyName(s), tonic: mod12(key.tonic + s), tonicName: names(s)[mod12(key.tonic + s)],
    scale: table("keyScale") || [], pentatonic: table("pentatonic") || [],
    pentaName: String(table("pentatonicName") || "pentatonic"),
    // The instrument's strings, each open note's pitch class (data.instruments' tuning, as MIDI notes).
    tuning: Array.isArray(it.tuning) && it.tuning.length ? it.tuning : data.tuning,
    box: state.kn === "penta", onSwitch: (which) => setKeyNeck(which) });
  const setKeyNeck = (which) => {
    state.kn = which;
    render();
  };

  // --- the overlay: a wide screen's rail, on the left, Guitar, Harmonica and Harmony -------------------
  // From 1200 px wide (viewer.css), overlay.js draws it, its Guitar tab first and shown when the page opens. Guitar:
  // each chord the sheet shows, once, in the order it first comes (two chords shown by one name are one; on a sheet
  // with no Harmony tab or an instrument with no neck, the key's neck first), with every position of it along a neck
  // and a legend naming them, on the instrument played (a ukulele's four strings), or the guitar's on one with no neck
  // (the piano, the harmonica, the winds: then at the guitar's capo). Picking one, on the neck or in the legend, makes
  // it the shape the strip and the chord's card show, at every place of that chord, kept with the rest (state.at); one
  // of the guitar's for another instrument holds for the rail alone. Harmonica: the harps for the song as it sounds (a
  // harmonica takes no capo; a transposition moves every harp), the harp chosen (harpAt, above the tonic; until one is
  // tapped, the one the song's harmonica tab plays on, else the first harp.py's choices pick), the key on it and each
  // chord's holes, harp.py's tables looked up. Harmony, on a sheet with a key to read numerals in (hasHarmony): the
  // key's neck (on the instrument played's necks), then each section's progression (harmonyPane, below). Hide, at the
  // rail's top, and the bar's button (after the key, from 1200 px) show it or hide it (state.necks), the two always in
  // step; hidden, the song has the whole width.
  // Narrower, the phone's sheet: the bar's neck (after the key) slides the same overlay up from the bar over half the
  // screen (sheetAt), docked there as the settings are (a layer, on a phone in the place of the one open), the song
  // readable and scrollable above it and its end coming up above it; its handle takes it to the whole screen and back,
  // and ✕, Escape, Back or the neck again close it, the focus back on the neck. Each page opens with it closed; the
  // rail's Hide and the bar's button are the rail's alone. Widened past 1200 px, the rail takes its place, on its tab.
  const necksEl = $("necks");
  const railWide = window.matchMedia("(min-width: 1200px)");
  const necksButton = $("necks-toggle"), sheetButton = $("necks-open");
  const railCan = () => Boolean(necksEl) && Boolean(overlay) && count > 0 && railWide.matches;
  const railOn = () => railCan() && state.necks && !doc.dataset.full;  // full screen: the song the whole width
  const sheetCan = () => Boolean(necksEl) && Boolean(overlay) && count > 0 && !railWide.matches;
  let sheetAt = null;  // the phone's sheet: "half", "full", or null while it is closed
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
  // The necks' instrument and how far its chords are from the sheet's: the one played, else the guitar at its capo.
  const necksAt = () => {
    const it = necksOf(), played = it === inst();
    return { it, played, s: played ? shift() : guitarShift() };
  };
  // A Harmony tab where the settings' Harmony row was: a key to read the numerals in, and each section's progression.
  const hasHarmony = Boolean(key) && Boolean(data.numerals) && Boolean(data.progressions);
  // Its progression playing (below), which drawing the overlay may stop as early as a short screen's full screen:
  // {n: the section, at: the numeral sounding, handle, sounds: soundsNow() as it started}.
  let playing = null;
  const guitarTab = () => {
    const { it, played, s } = necksAt();
    const chords = shownOnce(s).map(([c, rep, name]) => {
      const shapes = shapesOf(rep, s, it);
      return { name, list: shapes.list, mine: shapes.mine, chosen: played ? state.at[c] || 0 : railAt[name] || 0 };
    });
    // The key's neck: Harmony's where the necks are the instrument's played, else the Guitar tab's head still.
    return { name: String(it.tab || it.name || "Guitar"), strings: (it.tuning || []).length || 6, chords,
      key: key && data.keyScale && !(hasHarmony && played) ? keySpec(s, it) : null };
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
      return { key: null, none: "No key, so no harp to suggest.", plain: null };
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
    harmony: hasHarmony ? (pane) => harmonyPane(pane) : undefined,
    left: (tab) => {
      if (tab === "harmony") stopPlaying(true);  // as the Harmony panel closed did: every sound, a chord tapped too
    },
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
    sheet: () => (railWide.matches ? null : sheetAt),
    grow: () => {
      sheetAt = sheetAt === "full" ? "half" : "full";
      if (sheetAt === "full") pauseScroll();  // the song out of sight
      drawNecks();
      dock();
    },
    close: () => close(necksEl),
  }) : null;
  const drawNecks = () => {
    // Full screen hides the sheet, as it does the rail: open under it, it is back with the controls.
    const can = railCan(), on = railOn(), phone = sheetCan() && sheetAt !== null && !doc.dataset.full;
    if (necksButton) {
      necksButton.hidden = !can;
      necksButton.setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (sheetButton) {
      sheetButton.hidden = !sheetCan();
      sheetButton.setAttribute("aria-expanded", phone ? "true" : "false");
    }
    if (!necksEl) return;
    necksEl.hidden = !on && !phone;
    if (on) doc.dataset.necks = "1";  // the song and the bar move over for it
    else delete doc.dataset.necks;
    if (on || phone) rail.draw();
    else if (rail) rail.empty();
    else necksEl.textContent = "";
    // The window across 1200 px with the sheet closed, or full screen: no Harmony tab drawn, nothing of it playing.
    if (playing && !harmonyShown()) stopPlaying(true);
  };
  // Whether the overlay shows its Harmony tab now.
  const harmonyShown = () => Boolean(necksEl) && necksEl.querySelector("#harmony") !== null;
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
  // Shown or hidden: the song and the bar move back, or over, and the card follows its chord. Hidden on its Harmony
  // tab, every sound stops with it.
  const showNecks = (on) => {
    if (!on && harmonyShown()) stopPlaying(true);
    state.necks = on;
    keepNecks();
    render();
    place();
  };
  if (necksButton) necksButton.addEventListener("click", () => showNecks(!state.necks));
  if (sheetButton) {
    // The neck: the sheet up (on a phone in the place of the settings or a card), or closed where you see it.
    sheetButton.addEventListener("click", () => {
      if (sheetAt !== null && inSight(necksEl)) {
        close(necksEl);
        return;
      }
      if (sheetAt === null) sheetAt = "half";
      open(necksEl, sheetButton);
    });
  }
  if (necksEl) {
    // The window widened past 1200 px, or narrowed under it: the rail comes or goes, and the song with it. Widened with
    // the sheet open, the rail takes its place (where it is shown), on its tab, the focus kept in it. Narrowed with the
    // keyboard's focus in the rail, the focus goes to the bar's first control, rather than to nothing; the sheet stays
    // closed until the neck is pressed.
    railWide.addEventListener("change", () => {
      const had = necksEl.contains(document.activeElement);
      if (railWide.matches && sheetAt !== null) dropSheet();
      drawStrip();
      drawNecks();
      layout();
      place();
      if (had && !necksEl.contains(document.activeElement)) {
        const first = Array.from(bar.querySelectorAll("button")).find((b) => b.getClientRects().length > 0);
        if (first) first.focus({ preventScroll: true });
      }
    });
  }

  // --- the Chinese: in Simplified or Traditional characters, each character's reading over it ---------------
  // data.hanzi (page.py, hanzi.py: converted at render time, word by word), for a sheet with Chinese: each text the
  // sheet writes in its words (a line's, a section's label, a tab, a line of the notes' peek) in Simplified
  // characters and in Traditional ones, where that isn't the text as written, each as long as its text. Shown
  // (state.trad: the settings' Chinese characters, Simplified at first), each text is in the characters chosen, cut
  // again where the page cut it (into a line's columns, under its chords), and the sheet's language says which.
  // data.pinyin (page.py, pinyin.py: read in context at render time): for each line of the song's sections, in the
  // page's order, each of its characters' reading, "" for a letter, a space or punctuation, or null for a line with
  // no Chinese; none for a sheet with none, which has neither row. Shown (state.py: the settings' Pinyin), each
  // character with a reading is a ruby, the reading over it, between its chord and it (viewer.css: a chord stays
  // over its character's column), in either script: a character's reading is its own in both.
  const pyLines = Array.isArray(data.pinyin) ? data.pinyin : [];
  const pyCan = pyLines.some((line) => Array.isArray(line));
  const pyChip = $("pinyin-chip");
  const hanzi = data.hanzi && typeof data.hanzi === "object" ? data.hanzi : null;
  const hanRow = $("hanzi-row");
  // Where the sheet writes words, each with its text as the page wrote it: a line's words (its columns, .y and .w,
  // or a line of text whole), with its readings where it is a line of the song's; and a section's label, a tab and
  // a line of the notes' peek, each a text node (a label's progression, which the numerals name, follows it).
  const units = [];
  // The lines of the song's sections, as the page draws them (page.py _drawn_lines): the lines data.pinyin reads and
  // data.sung lights, by their index.
  const songLines = Array.from(sheetEl.querySelectorAll(":scope > section.sec > p.l"));
  if (pyCan || hanzi) {
    for (const line of sheetEl.querySelectorAll("p.l:not(.chords)")) {
      const nodes = line.querySelector(".y, .w") ? Array.from(line.querySelectorAll(".y, .w"))
        : line.firstElementChild ? [] : [line];
      const n = songLines.indexOf(line);
      if (nodes.length) {
        units.push({ line, nodes, texts: nodes.map((node) => node.textContent),
          readings: n >= 0 && Array.isArray(pyLines[n]) ? pyLines[n] : null });
      }
    }
    for (const box of sheetEl.querySelectorAll("h2.lbl, pre.tab, .peek")) {
      for (const node of Array.from(box.childNodes)) {
        if (node.nodeType === Node.TEXT_NODE) units.push({ line: null, nodes: [node], texts: [node.data], readings: null });
      }
    }
  }
  const chars = (text) => Array.from(text);  // a character a code point, as hanzi.py and pinyin.py count them
  // A unit's texts in ``script``'s characters: the whole converted, then cut where the page cut it; as written where
  // the data has none, or one of another length (not this page's).
  const inScript = (unit, script) => {
    const whole = unit.texts.join("");
    const table = script && hanzi && hanzi[script] && typeof hanzi[script] === "object" ? hanzi[script] : null;
    const shown = table && own.call(table, whole) && typeof table[whole] === "string" ? chars(table[whole]) : null;
    if (!shown || shown.length !== chars(whole).length) return unit.texts;
    let at = 0;
    return unit.texts.map((text) => {
      const part = shown.slice(at, at + chars(text).length).join("");
      at += chars(text).length;
      return part;
    });
  };
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
  // A unit drawn with ``texts``, and ``readings`` (one a character, of its texts together) over its characters.
  const drawUnit = (unit, texts, readings) => {
    const read = readings && readings.length === texts.reduce((n, text) => n + chars(text).length, 0) ? readings : null;
    let at = 0;
    let rubies = false;
    unit.nodes.forEach((node, k) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.data !== texts[k]) node.data = texts[k];
        return;
      }
      const parts = [];
      let plain = "";
      for (const character of chars(texts[k])) {
        const reading = read ? read[at++] : "";
        if (typeof reading === "string" && reading) {
          if (plain) parts.push(document.createTextNode(plain));
          plain = "";
          parts.push(ruby(character, reading));
        } else {
          plain += character;
        }
      }
      if (!parts.length) {
        if (node.firstElementChild || node.textContent !== plain) node.textContent = plain;
        return;
      }
      if (plain) parts.push(document.createTextNode(plain));
      node.textContent = "";
      for (const part of parts) node.appendChild(part);
      rubies = true;
    });
    if (unit.line) unit.line.classList.toggle("py", rubies);  // its columns keep the readings' room (viewer.css)
  };
  // The song's names (its title, its artist's, the page's title; in a songbook, every Chinese song's, in its pagers
  // too) follow the choice, on any song: page.py's song-names block (book.py's), by each name as written (data-zh).
  const songNames = (() => {
    try {
      const found = JSON.parse($("song-names") ? $("song-names").textContent : "null");
      return found && typeof found === "object" ? found : null;
    } catch (err) { return null; }
  })();
  // So does the PDF the page links (its foot's; a songbook's), the one in Traditional characters beside it (render.py,
  // songbook.py; page.py pdf_line: data-trad) while they are chosen.
  const pdfLinks = Array.from(document.querySelectorAll("a.pdf[data-trad]")).map((a) => [a, a.getAttribute("href")]);
  let namesDrawn = null;  // as the page wrote them
  const drawNamesShown = () => {
    if (namesDrawn === state.trad) return;
    namesDrawn = state.trad;
    for (const [link, href] of pdfLinks) link.setAttribute("href", state.trad ? link.getAttribute("data-trad") : href);
    if (!songNames) return;
    const table = songNames[state.trad ? "traditional" : "simplified"];
    for (const el of document.querySelectorAll("[data-zh]")) {
      const written = el.getAttribute("data-zh");
      const shown = table && typeof table === "object" && own.call(table, written) && typeof table[written] === "string"
        ? table[written] : written;
      if (el.textContent !== shown) el.textContent = shown;
    }
  };
  let wordsDrawn = "";  // as the page wrote them
  function drawWords() {
    drawNamesShown();
    if (pyChip) {
      $("pinyin-row").hidden = !pyCan;
      pyChip.setAttribute("aria-pressed", state.py ? "true" : "false");
    }
    if (hanRow) {
      hanRow.hidden = !hanzi;
      $("hanzi-s").setAttribute("aria-pressed", state.trad ? "false" : "true");
      $("hanzi-t").setAttribute("aria-pressed", state.trad ? "true" : "false");
    }
    const script = hanzi ? (state.trad ? "traditional" : "simplified") : "";
    const py = pyCan && state.py;
    const now = script + (py ? "+py" : "");
    if (now === wordsDrawn) return;
    wordsDrawn = now;
    if (hanzi) sheetEl.lang = state.trad ? "zh-Hant" : "zh-Hans";
    for (const unit of units) drawUnit(unit, inScript(unit, script), py ? unit.readings : null);
  }
  if (pyChip) {
    pyChip.addEventListener("click", () => {
      state.py = !state.py;
      keepPinyin();
      render();
      place();  // an open card goes with its chord
    });
  }
  for (const [id, trad] of [["hanzi-s", false], ["hanzi-t", true]]) {
    if (!$(id)) continue;
    $(id).addEventListener("click", () => {
      if (state.trad === trad) return;
      state.trad = trad;
      keepHanzi();
      render();
      place();
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
    $("card-tip").hidden = !tipDraws(i, chordEls.indexOf(shown.el));
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
      box.textContent = rep ? "No shape for this chord." : "We can't read this chord.";
    }
    heardBy(box, name);
    $("prev").disabled = shown.at <= 0;
    $("next").disabled = shown.at >= shapes.list.length - 1;
    const capoNote = capoNow() ? " Capo on fret " + capoNow() + "." : saysNoCapo() ? " No capo." : "";
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
  // the bar, one at a time (opening one closes the one open), and the song scrolls under it; from 900 px wide
  // (viewer.css) the settings are a rail beside the song, the card a popover by its chord and the versions list
  // one under its line. Each takes the focus as it opens (its heading); Escape closes the one on top, and the focus
  // goes back to what opened it when it was in there. The overlay's sheet is one of them below 1200 px (above), docked
  // at the foot up to 1199 px, the focus on its tab shown as it opens. Each one open is an entry of the browser's
  // history (layers.js): Back, a phone's or the app's, closes the one on top as Escape does, and leaves the page only
  // once none is open. Full screen is one too (below), its element the handle, which takes the focus as it opens.
  const pageEl = document.querySelector(".page");
  const wide = window.matchMedia("(min-width: 900px)");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const layers = [];  // the open ones, the last on top: {el, opener, nested}
  const topLayer = () => (layers.length ? layers[layers.length - 1].el : null);
  const inSight = (which) => !which.hidden && (wide.matches || topLayer() === which);
  const landing = (which) => (which === necksEl ? rail.landing()
    : which === handle ? handle : which.querySelector("h2"));
  // Those that dock at the foot on a phone, above the bar: the one of them on top is docked.
  const DOCKED = [panel, card, vList, necksEl, keyList].filter(Boolean);
  const dockedTop = () => {
    for (let i = layers.length - 1; i >= 0; i--) if (DOCKED.indexOf(layers[i].el) >= 0) return layers[i].el;
    return null;
  };
  // A Back takes k layers' entries off: the k on top close, and the entry it came to, written before what changed
  // since (a key changed with the settings open), gets the page's address again (a layer the page closes itself takes
  // its address down with it: layers.js).
  const layerHistory = window.caracoleLayers ? window.caracoleLayers.history((k) => {
    for (let i = 0; i < k && layers.length; i++) close(topLayer());
    save();
  }) : { sync() {} };
  // On a phone the page leaves room under the song for the one docked at its foot, so the end of
  // the song comes up above it, and the pill rides above it (--dock: its height). The bar is out of
  // the way while the song moves by itself, unless one is docked on it: then nothing moves as the
  // scroll pauses and resumes. Paused, or at the end of the song, it is back, under the pill. The overlay's
  // sheet docks there up to 1199 px; over the whole screen, the pill rides over its foot (necks-full, viewer.css).
  // From 1200 px the toolbar under the title is asleep meanwhile (data-asleep: out of sight, its room kept, so the
  // song doesn't jump), never hidden.
  function dockedNow() {
    return !wide.matches ? dockedTop()
      : sheetAt !== null && !railWide.matches && !doc.dataset.full ? necksEl : null;  // full screen hides the sheet
  }
  function dock() {
    const there = dockedNow();
    const away = moving() && !there;
    const hide = away && !toolbar.wide.matches;
    if (bar.hidden !== hide) {
      bar.hidden = hide;
      if (!hide) {
        slide(false);
        fitKey();
      }
    }
    bar.toggleAttribute("data-asleep", away);
    if (there) {
      doc.dataset.dock = there === necksEl && sheetAt === "full" ? "necks-full" : there.id;
      doc.style.setProperty("--dock", there.offsetHeight + "px");
    } else if (doc.dataset.dock) {
      delete doc.dataset.dock;
      doc.style.removeProperty("--dock");
    }
  }
  // The bar's top, or the window's foot where it isn't at the foot: out of sight (away, hidden, or full screen's), or,
  // from 1200 px, the toolbar at the top.
  const barTop = () => (toolbar.wide.matches || bar.hidden || bar.classList.contains("away") || doc.dataset.full
    ? window.innerHeight : bar.getBoundingClientRect().top);
  // The top of the window's room for a popover: from 1200 px, while the toolbar is stuck to the window's top, its foot;
  // else the window's top (the toolbar unstuck under the title is the page's, and a card open over it is a layer over
  // the page, which shows its pills again as it closes; in full screen it shows nothing). 0 narrower.
  const barFoot = () => {
    if (!toolbar.wide.matches) return 0;
    const r = bar.getBoundingClientRect();
    return r.top <= 0.5 ? Math.max(0, r.bottom) : 0;
  };
  // From 900 px wide the card is a popover by its chord: under it, or above it where the bar leaves
  // no room below and the room above clears the stuck toolbar, and across it, within the song's column. It is placed in
  // the page, so it goes with its chord as the page scrolls. So is the versions list, a popover under its line
  // (kinds.js's place).
  function place() {
    if (kinds) kinds.place();
    if (card.hidden || !wide.matches) return;
    const a = anchor().getBoundingClientRect();
    const column = pageEl.getBoundingClientRect();
    const width = card.offsetWidth, height = card.offsetHeight, gap = 8;
    const floor = barTop(), ceiling = barFoot();
    let top = a.bottom + gap;
    if (top + height > floor - gap && a.top - gap - height >= ceiling + gap) top = a.top - gap - height;
    const left = Math.max(column.left + gap, Math.min(a.left - 16, column.right - gap - width));
    card.style.setProperty("--pop-top", Math.round(top + window.scrollY) + "px");
    card.style.setProperty("--pop-left", Math.round(left + window.scrollX) + "px");
  }
  const restack = () => {
    const rail = doc.dataset.panel;
    for (const which of [panel, card, vList, necksEl, keyList]) {
      if (which) which.classList.toggle("top", which === topLayer());
    }
    more.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    keyNow.setAttribute("aria-expanded", keyList.hidden ? "false" : "true");
    sizeButton.setAttribute("aria-expanded", sizes.hidden ? "false" : "true");
    if (vList) $("ver-now").setAttribute("aria-expanded", vList.hidden ? "false" : "true");
    if (rails.every((which) => which.hidden)) delete doc.dataset.panel;  // the settings', the key list's
    else doc.dataset.panel = "open";
    if (wide.matches && rail !== doc.dataset.panel) layout();  // the song's column narrows beside the rail
    place();
    dock();
    layerHistory.sync(layers.length);  // an entry each, once this task is done
  };
  // ``nested``: one that opens over another and leaves it open (Export PDF's question over the settings). On a phone
  // any other closes every one open first; from 900 px the rails (the settings, the key list) are one at a time, a
  // card and the versions list beside them.
  const open = (which, opener, nested = false) => {
    auto.end();  // a short screen's full screen of itself gives way to any layer
    const at = layers.findIndex((layer) => layer.el === which);
    if (at >= 0) layers.splice(at, 1);  // open already: on top again
    if (!wide.matches && !nested) {
      for (const layer of layers.slice().reverse()) close(layer.el);
    } else if (rails.indexOf(which) >= 0) {
      for (const other of rails) if (other !== which) close(other);
    }
    layers.push({ el: which, opener: opener instanceof Element && opener !== document.body ? opener : null, nested });
    if (which !== sizes) close(sizes, false);  // Aa gives way to any other, at every width
    if (which === necksEl) drawNecks();  // drawn as the sheet, sheetAt set
    else if (which === ask) ask.showModal();
    else if (which === handle) fullScreen(true);
    else which.hidden = false;
    slide(false);  // the bar it sits on
    restack();
    if (which !== handle) pauseScroll();  // full screen is for reading: a song scrolling by itself goes on
    const to = landing(which);
    if (to) to.focus({ preventScroll: true });
  };
  const close = (which, refocus = true) => {
    const at = layers.findIndex((layer) => layer.el === which);
    if (at < 0) return;
    const opener = layers.splice(at, 1)[0].opener;
    const active = document.activeElement;
    const mine = refocus && (!active || active === document.body || which.contains(active));
    if (which === necksEl) {
      if (harmonyShown()) stopPlaying(true);  // closed on its Harmony tab: every sound stops, as the panel's did
      sheetAt = null;
      drawNecks();
    } else if (which === ask) {
      ask.close();
    } else if (which === handle) {
      fullScreen(false);
    } else {
      which.hidden = true;
    }
    if (which === card) for (const el of chordEls) el.classList.remove("on");
    restack();
    if (!mine) return;  // the focus is somewhere else of yours: it stays there
    let to = opener && opener.isConnected ? opener : null;
    if (!to && opener && which === card) to = anchor();  // the strip drew its button anew
    if (!to && topLayer()) to = landing(topLayer());
    if (to) to.focus({ preventScroll: true });
  };
  // Full screen on or off (below): its handle, and the rail and the song's columns in the width it leaves.
  const fullScreen = (on) => {
    if (on) doc.dataset.full = "on";
    else delete doc.dataset.full;
    handle.hidden = !on;
    drawNecks();
    layout();
    if (!on) fitKey();  // the bar back: its key measured again
    toolbar.edge();  // from 1200 px, the pill under the toolbar again, or at the top with none
  };
  // Every one but those in ``keep``.
  const closeAll = (...keep) => {
    for (const layer of layers.slice().reverse()) if (keep.indexOf(layer.el) < 0) close(layer.el);
  };
  // The sheet gone with the window widened past 1200 px, where the rail takes its place: the focus left where it is.
  const dropSheet = () => {
    sheetAt = null;
    const at = layers.findIndex((layer) => layer.el === necksEl);
    if (at >= 0) layers.splice(at, 1);
    restack();
  };
  for (const x of document.querySelectorAll("[data-close]")) x.addEventListener("click", () => close(x.closest(".sheet-ui")));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!tip.hidden) {
      hideTip();
      return;
    }
    if (layers.length) close(topLayer());
    else if (doc.dataset.full === "auto") auto.end();
  });
  // ⋯ closes the settings where you see them, and opens them otherwise (on a phone in the place of the one open).
  more.addEventListener("click", () => {
    if (inSight(panel)) {
      close(panel);
      return;
    }
    open(panel, more);
  });

  // --- the key list: the twelve keys, a tap away -----------------------------------------------------------------
  // The bar's key opens it (page.py _KEY_LIST), and closes it where you see it, as ⋯ the settings: the twelve keys in
  // the mode played, as data.keyNames names them, from the chords as written on this instrument (writtenAt: on one
  // with no capo the sheet's capo folded in, the key the song sounds in), the first "· as written", the one the chords
  // shown moved to pressed (moved()). A layer as the settings are: docked on the bar on a phone, from 900 px the rail
  // in the settings' place (one rail at a time). A sheet with no key has none to list: the key is disabled.
  const writtenAt = () => (takesCapo() ? 0 : sheetCapo);
  const drawKeyList = () => {
    const box = $("key-items"), at = mod12(moved());
    for (let k = 0; k < 12; k++) {
      let item = box.children[k];
      if (!item) {
        item = box.appendChild(document.createElement("button"));
        item.type = "button";
        item.dataset.k = String(k);
        if (k === 0) item.className = "key-as";
        item.addEventListener("click", () => chooseKey(k));
      }
      item.textContent = keyName(writtenAt() + k) + (k === 0 ? " · as written" : "");
      item.setAttribute("aria-pressed", k === at ? "true" : "false");
    }
    fitKeys();
  };
  // Each key whole in its cell: where a name is too long for four a row (a mode's, "Ab mixolydian", its two words on
  // two lines, in the rail or on a phone), the eleven a little smaller, all alike, down to three quarters of their
  // size, as the bar's key is (fitKey); as written has its row. Measured to the fraction of a pixel, in the room
  // within each one's padding; fitted again as the list opens and as the window changes.
  const spills = (el) => {
    const text = document.createRange(), s = getComputedStyle(el);
    text.selectNodeContents(el);
    return text.getBoundingClientRect().width > el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
  };
  const fitKeys = () => {
    const items = Array.prototype.slice.call($("key-items").children, 1);
    for (const item of items) item.style.fontSize = "";
    if (keyList.hidden || !items.some(spills)) return;
    const full = parseFloat(getComputedStyle(items[0]).fontSize);
    for (let size = full - 0.5; size >= full * 0.75 && items.some(spills); size -= 0.5) {
      for (const item of items) item.style.fontSize = size + "px";
    }
  };
  // A key chosen: the song transposed there the nearest way, as Easy keys moves it (a tritone at most, up or down; the
  // capo stays where it is), so the bar says what moved (keyShort); then the list closed, the focus on the key.
  const chooseKey = (k) => {
    keyQuiet = true;  // the key's name says it as it takes the focus
    try {
      step(wrapT(state.t + mod12(k - moved() + 6) - 6));
    } finally {
      keyQuiet = false;
    }
    close(keyList);
    keyNow.focus({ preventScroll: true });
  };
  keyNow.disabled = !key;
  if (!key) keyNow.removeAttribute("aria-haspopup");  // it opens nothing
  keyNow.addEventListener("click", () => {
    if (inSight(keyList)) {
      close(keyList);
      return;
    }
    drawKeyList();
    open(keyList, keyNow);
    fitKeys();  // laid out now
  });

  // --- full screen: the song alone, the controls hidden for reading ----------------------------------------------
  // The settings' Hide controls, or a double tap beside the song (layers.js's doubleTap: on none of the song's own
  // elements nor a control, MARGIN_SKIP), hides every control marked data-controls (the bar), the header's facts and
  // the rail of necks (railOn: the song takes the width), html[data-full] (viewer.css); a thin handle stays at the
  // window's foot. It is a layer of the stack above: the handle, Escape or Back brings everything back, the focus on
  // ⋯ when Hide controls hid them. On a phone a layer opened over it (a chord's card) takes its place, the controls
  // back; from 900 px one opens over it. A double tap in full screen does nothing.
  $("full-open").addEventListener("click", () => {
    close(panel);
    open(handle, more);
  });
  handle.addEventListener("click", () => {
    if (doc.dataset.full === "auto") auto.end();
    else close(handle);
  });
  // A short screen (a phone on its side): full screen by itself, with no history entry (layers.js's autoFull).
  const auto = window.caracoleLayers ? window.caracoleLayers.autoFull({
    handle, idle: () => layers.length === 0, changed: () => { drawNecks(); layout(); toolbar.edge(); },
  }) : { end() {} };
  if (window.caracoleLayers) {
    window.caracoleLayers.doubleTap(document, window.caracoleLayers.MARGIN_SKIP, () => {
      if (!doc.dataset.full) open(handle, null);
    });
  }

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
    $("names-hint").textContent = can ? "" : "No key found, so no numerals.";
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
  let tipOf = null, tipI = null, leaving = 0;  // what the tooltip is by (a chord, or the strip's button), its chord
  function hideTip() {
    clearTimeout(leaving);
    if (tip.hidden) return;
    const inside = tip.contains(document.activeElement);
    tip.hidden = true;
    if (tipOf) tipOf.removeAttribute("aria-describedby");
    if (inside && tipOf && tipOf.isConnected) tipOf.focus({ preventScroll: true });  // not lost with the tooltip
    tipOf = tipI = null;
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
  const VIEWS = { circle: ["Keyboard ›", "Notes on a keyboard", "keys"],
    keys: ["‹ Circle", "Notes on a circle", "circle"] };
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
    const floor = barTop(), ceiling = barFoot();
    let top = a.bottom + gap;
    if (top + height > floor - gap && a.top - gap - height >= ceiling + gap) top = a.top - gap - height;
    const left = Math.max(gap, Math.min(a.left - 12, doc.clientWidth - gap - width));
    tip.style.setProperty("--tip-top", Math.round(top + window.scrollY) + "px");
    tip.style.setProperty("--tip-left", Math.round(left + window.scrollX) + "px");
  };
  // The chord ``i`` (by default the chord ``el``'s), read at its place on the sheet ``k``, as the one played now:
  // its tooltip by ``el``, a chord on the sheet or the strip's button the card was opened from.
  function showTip(el, i = el.dataset.c, k = chordEls.indexOf(el)) {
    const found = reading(i, k);
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
      : found.text + ": your swap for " + label(i, base(i)) + ".";
    $("tip-key").textContent = "In " + keyWords() + ".";
    drawTipNotes(current(i));
    drawTipView();
    $("tip-hear").hidden = !tipSound(i);
    $("tip-switch").hidden = $("tip-view").hidden && $("tip-hear").hidden;  // nothing to switch, nothing to hear
    tip.hidden = false;
    tipOf = el;
    tipI = i;
    el.setAttribute("aria-describedby", "tip");
    placeTip();
  }
  $("tip-hear").addEventListener("click", () => {
    const heard = tipOf ? tipSound(tipI) : null;
    if (heard) sound.strum(heard.position, { capo: heard.capo, tuning: inst().tuning, voice: inst().voice });
  });
  // Whether the tooltip has the chord ``i``'s notes to draw, as it is played now (at its place ``k``): its numeral, its
  // notes in the tables and the key's. The card offers Circle & keyboard where it has, which closes the card and opens
  // the tooltip by the chord the card is by (its numeral where the sheet shows one, else its name), the focus on its
  // first button: the chords' names alone have no numeral to hover or tap.
  const tipDraws = (i, k) => Boolean(reading(i, k)) && Boolean(tonesOf(current(i))) && Boolean(keyNotes());
  $("card-tip").addEventListener("click", () => {
    const i = shown.i, k = chordEls.indexOf(shown.el), by = anchor();
    close(card);
    showTip(by, i, k);
    const first = ["tip-view", "tip-hear"].map($).find((b) => !b.hidden && b.getClientRects().length > 0);
    if (!tip.hidden && first) first.focus({ preventScroll: true });
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

  // --- the Harmony tab: each section's progression, named, played ---------------------------------------
  // The overlay's third tab (the rail from 1200 px, the phone's sheet narrower), on a sheet with a key (hasHarmony):
  // the key the numerals are read in, its neck, and each section's progression (page.py's ``progressions``): its
  // numerals, one cycle, the times it is played (and how many of those vary it), its name, the named progressions it
  // plays within it, and how it ends. Tap one to go to its section; ▶ plays it with strum.js's synthesis
  // (window.caracoleSound, when the page has it), a chord a bar at the tempo set (− and + change it as it plays),
  // each chord as the page shows it, its shape and the capo, and marks the one playing; ■ stops it, and leaving the
  // tab every sound (another tab, the sheet closed, the rail hidden or gone). Songs with this progression is the
  // library's page, with it filtered (#prog=), and so is Songs with each one it contains.
  const ENDINGS = { authentic: "an authentic cadence (V–I)", plagal: "a plagal cadence (IV–I)",
    half: "a half cadence (on V)", deceptive: "a deceptive cadence (V–vi)" };
  const counted = (n, word) => n + " " + word + (n === 1 ? "" : "s");
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
  const soundsNow = () => musicOf(state) + "|" + state.inst;
  // The one playing marked, and the tab's data-playing while one plays (book.js keeps a songbook's arrows for it).
  const drawPlaying = () => {
    const box = document.getElementById("harmony");
    if (box) box.toggleAttribute("data-playing", Boolean(playing));
    for (const li of document.querySelectorAll("#progs > .prog")) {
      const mine = Boolean(playing) && playing.n === Number(li.dataset.n);
      const play = li.querySelector(".prog-play");
      play.textContent = mine ? "■" : "▶";
      play.setAttribute("aria-label", mine ? "Stop" : "Play " + li.querySelector(".prog-sec").textContent);
      li.querySelectorAll(".pn").forEach((pn, k) => pn.classList.toggle("on", mine && playing.at === k));
    }
  };
  // ■, another ▶, the song played otherwise (harmonyPane) or the tab left: the progression stops; the tab left
  // (``all``), every sound strum.js still makes too, a chord tapped among them.
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
    const me = { n, at: -1, handle: null, sounds: soundsNow() };
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
  // Drawn into the overlay's pane (overlay.js) each time it draws the tab, every control with the data-f the focus
  // comes back to: bpm-down, bpm-up, and of section n prog-go:n, prog-play:n, prog-songs:n and prog-named:n:j (its
  // j-th Songs with …); the neck's switch keeps keyNeck's. The key's neck only on the necks of the instrument played.
  const harmonyPane = (pane) => {
    // Transposed, or another capo, mode, swap, shape or instrument: what it plays is no longer the page's chords.
    if (playing && playing.sounds !== soundsNow()) stopPlaying();
    const box = pane.appendChild(document.createElement("div"));
    box.id = "harmony";
    box.className = "harmony";
    const make = (parent, tag, cls, text) => {
      const node = parent.appendChild(document.createElement(tag));
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    make(box, "p", "hint", "In " + keyWords() + ".").id = "harmony-key";
    const necks = necksAt();  // on an instrument with no neck, the guitar's key neck heads the Guitar tab instead
    if (data.keyScale && necks.played) box.appendChild(overlay.keyNeck(keySpec(necks.s, necks.it)));
    const synth = state.vol > 0 ? synthesis() : null;  // Sound off: no ▶ that would play nothing
    const tempo = make(box, "div", "row");
    tempo.id = "tempo-row";
    tempo.hidden = !synth;
    make(tempo, "span", "lab", "Tempo");
    const stepper = make(tempo, "span", "stepper");
    const stepButton = (id, said, text, by) => {
      const b = make(stepper, "button", "", text);
      b.type = "button";
      b.id = id;
      b.dataset.f = id;
      b.setAttribute("aria-label", said);
      b.addEventListener("click", () => setBpm(state.bpm + by));
    };
    stepButton("bpm-down", "Slower", "−", -BPM.step);
    make(stepper, "output", "", String(state.bpm)).id = "bpm";
    stepButton("bpm-up", "Faster", "+", BPM.step);
    make(tempo, "span", "hint-inline", "bpm · 1 chord a bar");
    const list = make(box, "ol", "progs");
    list.id = "progs";
    const found = table("progressions") || [];
    const none = make(box, "p", "hint", "No chords we can read.");
    none.id = "progs-none";
    none.hidden = found.length > 0;
    for (const row of found) {
      const [n, numerals, repeats, name, ending, pkey, chords, variations] = row;
      const li = make(list, "li", "prog");
      li.dataset.n = String(n);
      const go = make(li, "button", "prog-go");
      go.type = "button";
      go.dataset.f = "prog-go:" + n;
      make(go, "span", "prog-sec", sectionName(n));
      const nums = make(go, "span", "prog-nums");
      numerals.forEach((numeral, k) => {
        if (k) nums.appendChild(document.createTextNode("–"));
        make(nums, "span", "pn", numeral);
      });
      if (repeats > 1) {
        const times = make(nums, "span", "prog-x", "×" + repeats);
        if (variations > 0) {  // "×8, 1 variation", the words kept together
          times.appendChild(document.createTextNode(", "));
          make(times, "span", "prog-var", counted(variations, "variation"));
        }
      }
      make(go, "span", "prog-about", [name, containsWords(row), ending && ENDINGS[ending] ? "ends on " + ENDINGS[ending]
        : ""].filter(Boolean).join(" · "));
      go.addEventListener("click", () => {
        const sec = sectionEls()[n];
        if (sec) sec.scrollIntoView({ block: "start", behavior: calm.matches ? "auto" : "smooth" });
      });
      const play = make(li, "button", "round prog-play");
      play.type = "button";
      play.dataset.f = "prog-play:" + n;
      play.hidden = !synth || !Array.isArray(chords);
      play.addEventListener("click", () => playSection(n, repeats, chords || []));
      const songs = make(li, "a", "link prog-songs", "Songs with this progression");
      songs.href = String(data.library || "") + "#prog=" + encodeURIComponent(pkey);
      songs.dataset.f = "prog-songs:" + n;
      containedOf(row).forEach(([cname, , ckey], j) => {
        const link = make(li, "a", "link prog-named", "Songs with " + cname);
        link.href = String(data.library || "") + "#prog=" + encodeURIComponent(ckey);
        link.dataset.f = "prog-named:" + n + ":" + j;
      });
    }
    drawPlaying();
  };
  // The progression playing takes the new tempo from its next strum on; the tab shows it where it is drawn.
  const setBpm = (n) => {
    state.bpm = Math.max(BPM.min, Math.min(BPM.max, n));
    const out = $("bpm");
    if (out) out.textContent = String(state.bpm);
    if (playing && playing.handle && typeof playing.handle.tempo === "function") playing.handle.tempo(state.bpm);
    save();
  };
  // --- the version line and its list (kinds.js) --------------------------------------------------
  // Under the artist, which of the song's versions this page is and an icon a kind it keeps to play from; the line
  // opens the list of them (a layer: a sheet from the bottom on a phone, a popover under the line from 900 px, placed
  // by place() above). A link to another of the song's pages takes the text size and the scroll speed along, and the
  // screen's choices (the key and the rest are each sheet's own): vAddress, kinds.js's carry.
  const vAddress = (page) => {
    const params = new URLSearchParams();
    if (state.fs !== FS.start) params.set("fs", String(state.fs));
    if (state.speed !== SPEED.start) params.set("speed", String(state.speed));
    screenChoices(params);  // the rail, the pinyin, the characters, the instrument and the theme there too
    const fragment = params.toString();
    return encodeURIComponent(page) + (fragment ? "#" + fragment : "");
  };
  kinds = window.caracoleKinds ? window.caracoleKinds.attach({ data, here: pageName(), served,
    sheetPath: sheetPath(), carry: vAddress, open, close, inSight }) : null;

  // --- Aa: the text size, in a box beside the song -------------------------------------------------
  // Not a dialog: the song stays in view and within reach, and the box closes on Escape, on a tap
  // anywhere else, or when the focus leaves it.
  // A layer (the stack above): Back closes it, and so does Escape, with the focus back on Aa when it was in the box.
  sizeButton.addEventListener("click", () => (sizes.hidden ? open(sizes, sizeButton) : close(sizes)));
  document.addEventListener("pointerdown", (e) => {
    if (!sizes.hidden && !(e.target instanceof Node && $("size-box").contains(e.target))) close(sizes, false);
  }, true);
  $("size-box").addEventListener("focusout", (e) => {
    if (e.relatedTarget instanceof Node && !$("size-box").contains(e.relatedTarget)) close(sizes, false);
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
  // Aa's theme: Auto (the system's), Light or Dark, kept for every page by screen.js, and in the address (save()).
  for (const b of $("theme").querySelectorAll("button")) {
    b.addEventListener("click", () => { screenKit.setTheme(b.id.slice("theme-".length)); render(); });
  }
  $("strip-toggle").addEventListener("click", () => { state.shapes = !stripShown(); render(); });
  // Keep the screen on, a step of the minutes screen.js offers (none past either end), kept for every page by it, and
  // in the address (save()).
  const stepAwake = (by) => {
    const all = screenKit.MINUTES, next = all[all.indexOf(screenKit.minutes()) + by];
    if (next === undefined) return;
    screenKit.setMinutes(next);
    render();
  };
  $("awake-down").addEventListener("click", () => stepAwake(-1));
  $("awake-up").addEventListener("click", () => stepAwake(1));
  $("reset-all").addEventListener("click", () => {
    Object.assign(state, { t: Number(data.transpose) || 0, mode: null, alt: {}, at: {}, capo: null, nm: null,
      necks: true, py: false, trad: false });
    for (const i of Object.keys(atSeen)) delete atSeen[i];  // the version's shapes are for its own chords
    Object.assign(state, ownVersion());  // the song's own version, if it has one (the one made yours here, else its)
    if (startInst) state.inst = startInst;  // and its instrument; else the instrument stays the player's
    keepNecks();  // the rail of necks back, on every sheet
    keepPinyin();  // and the pinyin off
    keepHanzi();  // and the Chinese in Simplified characters
    render();
    place();
  });

  // --- scrolling by itself, hands on the guitar ----------------------------------------------------
  // Off, counting down (3 s, for your hands to get to the guitar; pressed again, it starts at
  // once), running, or paused. While it is on, the pill steers it, above the bar's place (from 1200 px under the
  // toolbar): − and + change the speed as it runs, ❚❚ pauses and ▶ resumes (after a countdown again), × ends it; the
  // bar is out of the way while it counts down and runs (dock()). A finger on the page, the wheel, a
  // key that scrolls, a scroll by hand, a card opening or the end of the song pauses it (a song in columns, read in
  // place, stops moving once it is all in view, and pauses there once its timed lyrics are over: columnsEnd): the page and
  // the bar are yours until you press ▶, which stays within reach with the card open. The bar's Scroll (pressed
  // while it is on) closes the settings and the card, and leaves the overlay's sheet at half the screen, the bar
  // under it and the pill above it.
  const COUNTDOWN = 3000;
  const scroll = { state: "off", from: 0, travelled: 0, last: 0, at: 0, ends: 0, timer: 0, loop: 0 };
  const moving = () => scroll.state === "counting" || scroll.state === "running";
  // Pixels a second: a bigger text scrolls as much faster, so a speed keeps its pace through the song.
  const pace = () => (state.speed * SPEED.px * state.fs) / FS.start;
  const LABELS = { counting: "Start", running: "Pause", paused: "Resume" };
  const showScroll = (said) => {
    pill.hidden = scroll.state === "off";
    if (scroll.state === "off") delete doc.dataset.pill;
    else doc.dataset.pill = scroll.state;  // room under the song for the pill
    dock();  // the bar, away or back
    toolbar.edge();  // from 1200 px the pill under the toolbar, wherever it is now
    pill.dataset.state = scroll.state;
    $("scroll").setAttribute("aria-pressed", scroll.state === "off" ? "false" : "true");  // lit while it is on
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

  // The screen stays on while it counts down and scrolls, and as long after the last touch as More's Keep the screen
  // on says: screen.js's (awake), asked again whenever the scroll starts, pauses or ends.
  const awake = screenKit.awake(moving);

  // The line being sung, lit while it scrolls. data.sung (page.py, sung.py: the song's timed lyrics matched to its
  // lines at render time): for each timed line, in time order, [ms, n], its time and the index in songLines of the
  // line it is sung on, or null for one the sheet writes nowhere (a chorus sung again, a break); none for a song with
  // no timed lyrics, or whose lyrics meet too few of its lines, which lights nothing. The lyrics' clock, sungClock
  // (in ms: at, and since, when it last went on, null while it stands), starts once the count-in is over, stands
  // while the scroll is paused or counts in again (the line lit stays) and while the page is hidden, and is back at
  // the start, none lit, once autoscroll ends. The line lit is the one the last timed line at or before the clock
  // names: none before the first, nor for one sung nowhere. A tap on a timed line's words while autoscroll is on
  // (never on its chords, whose card opens) sets the clock at that line's first time; a finger pauses the scroll as
  // ever, a mouse click pauses nothing, so the clock goes on from there. No recording plays: it is a guide at the
  // song's own times, and the scroll keeps its own speed.
  const SUNG = (Array.isArray(data.sung) ? data.sung : [])
    .filter((e) => Array.isArray(e) && Number.isFinite(e[0])
      && (e[1] === null || (Number.isInteger(e[1]) && e[1] >= 0 && e[1] < songLines.length)))
    .sort((a, b) => a[0] - b[0]);
  const timeOf = new Map();  // each line lit, its first time
  for (const [ms, n] of SUNG) if (n !== null && !timeOf.has(songLines[n])) timeOf.set(songLines[n], ms);
  const sungClock = { at: 0, since: null, started: false };
  // The clock stands where the song is (a pause, a count-in again, the page hidden), or goes on from there: never
  // while the page is hidden, which draws no frames, so the song scrolls no further and the light keeps with it.
  const standClock = () => {
    if (sungClock.since === null) return;
    sungClock.at += performance.now() - sungClock.since;
    sungClock.since = null;
  };
  const goClock = () => {
    sungClock.started = true;
    if (document.visibilityState !== "hidden") sungClock.since = performance.now();
  };
  document.addEventListener("visibilitychange", () => {
    if (scroll.state !== "running") return;
    if (document.visibilityState === "hidden") standClock();
    else if (sungClock.since === null) goClock();
  });
  let lit = null;
  const clockNow = () => sungClock.at + (sungClock.since === null ? 0 : performance.now() - sungClock.since);
  // When the lyrics are over, on their clock: the last timed line's time where the sheet sings it nowhere (LRCLIB's
  // empty stamp at the lyrics' end, which marks the song's end), else the last timed line's and a grace after it, the
  // median gap between timed lines, 3 s at least, for that line to be sung; 0 for a song with no timed lyrics.
  const SUNG_END = (() => {
    if (!SUNG.length) return 0;
    const [last, n] = SUNG[SUNG.length - 1];
    if (n === null) return last;
    const gaps = SUNG.slice(1).map((e, i) => e[0] - SUNG[i][0]).sort((a, b) => a - b);
    const half = Math.floor(gaps.length / 2);
    const median = !gaps.length ? 0 : gaps.length % 2 ? gaps[half] : (gaps[half - 1] + gaps[half]) / 2;
    return last + Math.max(3000, median);
  })();
  const lightSung = () => {
    let line = null;
    if (scroll.state !== "off" && sungClock.started) {
      const now = clockNow();
      for (const [ms, n] of SUNG) {
        if (ms > now) break;
        line = n === null ? null : songLines[n];
      }
    }
    if (line === lit) return;
    if (lit) lit.classList.remove("sung");
    if (line) line.classList.add("sung");
    lit = line;
  };
  sheet.addEventListener("click", (e) => {
    const line = scroll.state === "off" || e.target.closest(".c") ? null : e.target.closest("p.l");
    if (!line || !timeOf.has(line)) return;
    sungClock.at = timeOf.get(line);
    sungClock.started = true;
    if (sungClock.since !== null) sungClock.since = performance.now();  // still scrolling: on from there
    lightSung();
  });

  const countdown = () => {
    clearTimeout(scroll.timer);
    standClock();  // pressed again while it runs: the clock stands through the count-in, then goes on
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
  // A song in columns (html[data-columns] above 1: the window shows it whole, layout()), whose lines run down one
  // column and back up the next, is read in place: the scroll goes no further than brings the sheet's top to the top
  // of the room the controls leave it (layers.js toolbar's room, as the key map's turn in columns does, screen.js),
  // never back up, nor past the page's end, and stays there running while the lyrics' clock lights its lines, until it
  // passes their end (SUNG_END); then, or at once for a song with no timed lyrics, it pauses at the song's end, as a
  // song in one column does at the page's (the screen back to its minutes, the bar back, the loop stopped; the line lit
  // stays). The page's scroll position it stops at, a whole pixel; none (Infinity) in one column.
  const columnsEnd = () => {
    if (!(Number(doc.dataset.columns) > 1)) return Infinity;
    const { top } = toolbar.room(pill, dockedNow());
    const end = document.documentElement.scrollHeight - window.innerHeight;
    const up = Math.max(0, sheetEl.getBoundingClientRect().top - top);
    return Math.max(0, Math.min(end, Math.round(window.scrollY + up)));
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
    goClock();  // the lyrics' clock goes on, from where it stood
    const loop = ++scroll.loop;
    const frame = (now) => {
      if (scroll.state !== "running" || loop !== scroll.loop) return;
      lightSung();
      // Moved some other way (the scroll bar, a search in the page, a link): yours to read.
      if (Math.abs(window.scrollY - scroll.at) > 3) {
        pauseScroll();
        return;
      }
      if (scroll.last) {
        // A frame long in coming (a tab in the background) moves no further than a quarter second.
        scroll.travelled += (Math.min(now - scroll.last, 250) / 1000) * pace();
        let y = Math.round(scroll.from + scroll.travelled);
        const most = columnsEnd();
        if (y > most) {  // held there: on from it at once should the columns go (a window made narrower)
          y = most;
          scroll.travelled = most - scroll.from;
        }
        if (y !== Math.round(scroll.at)) {
          window.scrollTo(0, y);
          scroll.at = window.scrollY;
        }
        const end = most === Infinity
          ? window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
          : y >= most && clockNow() >= SUNG_END;  // in columns, at the cap once the lyrics are over
        if (end) {
          pauseScroll("Paused · end of song");
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
  function pauseScroll(said) {
    if (!moving()) return;
    clearTimeout(scroll.timer);
    standClock();
    scroll.state = "paused";
    showScroll(said || "Paused");
    awake();
    lightSung();
  }
  const endScroll = () => {
    const mine = pill.contains(document.activeElement);
    clearTimeout(scroll.timer);
    scroll.state = "off";
    sungClock.at = 0;  // back at the song's start
    sungClock.since = null;
    sungClock.started = false;
    showScroll("");
    awake();
    lightSung();
    if (mine) $("scroll").focus({ preventScroll: true });
  };

  // The song moves only in sight: the overlay's sheet over the whole screen goes back to half, the song above it.
  const halfSheet = () => {
    if (sheetAt !== "full") return;
    sheetAt = "half";
    drawNecks();
  };
  $("scroll").addEventListener("click", () => {
    // Pressed by the keyboard (its own focus, which a pointer's press never gives it: screen.js steer), its focus would
    // go as the bar hides: the pill's ▶ takes it, to be pressed again, or Enter, to start at once. Pressed by the key
    // map (toggle(), the focus on the page or full screen's handle), it leaves the focus where it is, so that a
    // pedal's next Space or Enter is the map's again, once however long it is held, never ▶'s own press.
    const keyed = document.activeElement === $("scroll");
    // The overlay's sheet stays, at half the screen, the song moving above it; and so does full screen, where the key
    // map's Space presses it (the bar hidden).
    closeAll(necksEl, handle);
    halfSheet();
    close(sizes, false);
    countdown();
    if (keyed) go.focus({ preventScroll: true });
  });
  go.addEventListener("click", () => {
    if (scroll.state !== "running") halfSheet();  // the pill's ▶, as the bar's Scroll
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
  // Home and End scroll the page: they pause it. Space, Enter and the four page keys are the key map's (screen.js
  // keys): Space or Enter starts and stops it (the bar's Scroll while it is off, else the pill's ▶), and a page key
  // pauses it and turns a screen keeping two lines, measured in the room the bar, the pill and a docked layer leave
  // (layers.js toolbar's room; in full screen, where the keys work, the bar counts for nothing). They are left to a
  // layer with the focus (busy: one of the stack's, Aa's box, a numeral's tooltip, the rail of necks or a dialog),
  // full screen's handle not counted.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Home" || e.key === "End") pauseScroll();
  });
  const busy = () => {
    const at = document.activeElement instanceof Element ? document.activeElement : null;
    if (!at || at === handle) return false;
    return layers.some((layer) => layer.el.contains(at)) || Boolean(at.closest("#sizes, #tip, #necks, dialog"));
  };
  screenKit.keys({
    toggle: () => (scroll.state === "off" ? $("scroll") : go).click(),
    pause: () => pauseScroll(),
    room: () => toolbar.room(pill, dockedNow()),
    busy,
    sheet: sheetEl,
    steer: [$("scroll"), ...pill.getElementsByTagName("button")],
  });

  // --- the bar: away as you read down the song, back when you want it -----------------------------
  // It slides away as you scroll down, and comes back as you scroll up, at the top and the end of
  // the song, on a tap on the page (not on one of its controls) or when the keyboard's focus comes to
  // it. Only your own scrolling moves it: none before you first touch the page (the browser, or the
  // songbook, putting you back where you were), and none just after a change of key or text size,
  // when the browser keeps the line you were reading in place by scrolling. It stays while the size
  // box or a sheet is open (the overlay's too), and while one of its controls has the keyboard's focus, which would
  // otherwise go out of sight. Below 1200 px alone: from 1200 px the toolbar under the title never slides away (and
  // Aa's box stays open as you scroll), and goes with the page as it scrolls, the pill under it (toolbar.edge()).
  const reveal = { y: window.scrollY, quiet: 0, touched: false };
  function hush() {
    if (doc.dataset.ready === "1") reveal.quiet = performance.now() + 400;
  }
  function slide(away) {
    bar.classList.toggle("away", away);
    if (away) close(sizes, false);
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
    toolbar.edge();
    if (toolbar.wide.matches) {
      reveal.y = y;
      return;
    }
    if (y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2) {
      slide(false);
      reveal.y = y;
      return;
    }
    if (!reveal.touched || performance.now() < reveal.quiet || layers.length > 0 || !sizes.hidden || keyboardIn(bar)) {
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

  // Nothing to transpose, no shapes and no other setting for a sheet without chords: Aa and Scroll alone.
  $("keys").hidden = count === 0;
  more.hidden = count === 0;
  toolbar.place();  // under the title from 1200 px, before it shows
  showScroll();
  render();
  if (hash.get("panel") === "1") open(panel, null);
  if (hash.has("chord")) openCard(String(hash.get("chord")));
  doc.dataset.ready = "1";
})();
