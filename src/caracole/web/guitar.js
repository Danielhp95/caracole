// caracole serve's Guitar Pro page (guitar_page.py): the song's Guitar Pro file, drawn and played by alphaTab.
//
// The file's bytes are in the page (#gp, base64); alphaTab, its music font and its SoundFont come in the one
// script caracole serve sends with it (window.caracoleAlphaTab, web/alphatab.py). The page runs in a sandbox, an
// origin of its own, and loads nothing else: the font is a data: URI, the SoundFont is handed over as bytes, and
// alphaTab's synthesizer runs in a worker made from a blob: of the library's own text. Its audio goes through a
// ScriptProcessor, since an AudioWorklet module can't be loaded here. Every element is made with createElement and
// textContent. The page says where it stands on <html> (data-rendered, the times the score was drawn;
// data-player: loading, ready, playing, paused; data-track, the track shown), for the tests.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const status = $("gp-status");
  const say = (text, failed) => {
    status.textContent = text;
    status.classList.toggle("failed", Boolean(failed));
  };
  const at = window.caracoleAlphaTab;
  const lib = window.alphaTab;
  if (!at || !lib) {
    say("alphaTab didn't load, so the tab can't be drawn here: download the file instead.", true);
    return;
  }
  const bytesOf = (text) => {
    const raw = atob(text);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes;
  };

  // alphaTab's workers run the library itself, the very text the bundle holds, as a blob: the sandbox lets the
  // page load no script from the server into a worker, and one of the page's own is allowed (worker-src blob:).
  const workerUrl = URL.createObjectURL(new Blob(["(" + at.library.toString() + ")();"],
    { type: "text/javascript" }));
  lib.Environment.initializeMain(
    (settings, name) => new Worker(workerUrl, { name }),
    () => Promise.reject(new Error("no audio worklet on this page")));

  const narrow = window.matchMedia("(max-width: 599px)");
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  const views = Array.from(document.querySelectorAll("input[name=view]"));
  const tabOnly = () => (views.find((v) => v.checked) || {}).value !== "score";
  (views.find((v) => v.value === (narrow.matches ? "tab" : "score")) || views[0]).checked = true;

  // The score's colours, the page's own tokens (base.css), light or dark.
  const token = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const colours = () => ({
    display: {
      resources: {
        mainGlyphColor: token("--text"),
        secondaryGlyphColor: token("--muted"),
        scoreInfoColor: token("--text"),
        barNumberColor: token("--muted"),
        staffLineColor: token("--border-strong"),
        barSeparatorColor: token("--control-edge"),
      },
    },
  });
  // Tab only shows a track's tablature alone, which a track without one (a piano's, the drums') hasn't got: that
  // one is shown as a score, whatever the switch says, and the switch waits for a track with a tab.
  const drums = (track) => track.staves.some((staff) => staff.isPercussion) ||
    (track.playbackInfo && track.playbackInfo.primaryChannel === 9);  // MIDI's channel 10
  const hasTab = (track) => Boolean(track) && !drums(track) && track.staves.some((staff) =>
    staff.showTablature && staff.tuning && staff.tuning.length > 0);
  let score = null;
  let current = 0;
  const viewSwitch = $("view");
  const look = (s) => {
    s.fillFromJson(colours());
    const tab = score === null || hasTab(score.tracks[current]);
    viewSwitch.disabled = !tab;
    s.display.staveProfile = tabOnly() && tab ? lib.StaveProfile.Tab : lib.StaveProfile.Default;
    s.display.scale = narrow.matches ? 0.8 : 1;
  };

  const settings = new lib.Settings();
  settings.core.engine = "html5";  // a canvas: SVG would set thousands of style attributes
  settings.core.useWorkers = true;
  settings.core.enableLazyLoading = false;
  settings.core.fontDirectory = "";
  settings.core.smuflFontSources = new Map([[lib.FontFileFormat.Woff2, at.font]]);
  settings.player.playerMode = lib.PlayerMode.EnabledSynthesizer;
  settings.player.outputMode = lib.PlayerOutputMode.WebAudioScriptProcessor;
  settings.player.enableCursor = true;
  settings.player.scrollMode = lib.ScrollMode.Off;  // the page stays where it is until Play
  settings.display.layoutMode = lib.LayoutMode.Page;

  const failed = (e) => say("alphaTab couldn't read this file (" + String((e && (e.message || e)) || "an error") +
    "): download it instead.", true);
  try {
    score = lib.importer.ScoreLoader.loadScoreFromBytes(bytesOf($("gp").textContent.trim()), settings);
  } catch (e) {
    failed(e);
    return;
  }
  // The first track with a tab (a guitar's, a bass'), else the first.
  current = Math.max(0, score.tracks.findIndex(hasTab));
  look(settings);

  const api = new lib.AlphaTabApi($("score"), settings);
  window.caracoleGuitar = api;
  let drawn = 0;
  let ready = false;
  root.dataset.rendered = "0";
  root.dataset.player = "loading";
  const play = $("play");
  const stop = $("stop");
  const redraw = () => {
    look(api.settings);
    api.updateSettings();
    api.render();
  };
  api.error.on(failed);
  say("Drawing the tab…");

  // The track picker: each track of the score, the one shown ticked.
  const picker = $("tracks");
  const list = $("track-list");
  const shown = $("track-name");
  const trackName = (track, index) => String(track.name || "").trim() || "Track " + (index + 1);
  const trackKind = (track) => {
    const staff = track.staves[0];
    if (drums(track)) return "drums";
    const strings = staff && staff.tuning ? staff.tuning.length : 0;
    return strings ? strings + " strings" : "";
  };
  const showTrack = (index) => {
    current = index;
    root.dataset.track = String(index);
    shown.textContent = trackName(score.tracks[index], index);
    for (const input of list.querySelectorAll("input")) input.checked = Number(input.value) === index;
  };
  score.tracks.forEach((track, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "track";
    input.value = String(index);
    label.appendChild(input);
    label.appendChild(document.createElement("span")).textContent = trackName(track, index);
    const kind = trackKind(track);
    if (kind) {
      const small = label.appendChild(document.createElement("span"));
      small.className = "kind";
      small.textContent = kind;
    }
    input.addEventListener("change", () => {
      if (!input.checked) return;
      picker.open = false;
      showTrack(index);
      say("Drawing the tab…");
      look(api.settings);
      api.updateSettings();
      api.renderTracks([track]);
    });
    list.appendChild(label);
  });
  picker.hidden = score.tracks.length < 2;
  showTrack(current);
  document.addEventListener("click", (e) => {
    if (picker.open && !picker.contains(e.target)) picker.open = false;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && picker.open) {
      picker.open = false;
      picker.querySelector("summary").focus();
    }
  });

  api.renderFinished.on(() => {
    drawn += 1;
    root.dataset.rendered = String(drawn);
    say(ready ? "" : "Loading the sound…");
  });
  api.playerReady.on(() => {
    ready = true;
    play.disabled = false;
    stop.disabled = false;
    if (root.dataset.player === "loading") root.dataset.player = "ready";
    if (drawn) say("");
  });
  api.playerStateChanged.on((e) => {
    const playing = e.state === lib.synth.PlayerState.Playing;
    if (ready && (playing || root.dataset.player !== "ready")) root.dataset.player = playing ? "playing" : "paused";
    play.textContent = playing ? "Pause" : "Play";
    play.setAttribute("aria-pressed", String(playing));
  });
  play.addEventListener("click", () => {
    // Playing, the page follows the cursor, each line it reaches under the bar of controls.
    const player = api.settings.player;
    if (player.scrollMode === lib.ScrollMode.Off) {
      player.scrollMode = lib.ScrollMode.Continuous;
      player.scrollOffsetY = -($("gp-bar").offsetHeight + 12);
      api.updateSettings();
    }
    api.playPause();
  });
  stop.addEventListener("click", () => api.stop());

  const tempo = $("tempo");
  const tempoNow = $("tempo-now");
  tempo.addEventListener("input", () => {
    const percent = Math.min(125, Math.max(50, Number(tempo.value) || 100));
    tempoNow.textContent = percent + "%";
    api.playbackSpeed = percent / 100;
  });
  for (const view of views) view.addEventListener("change", () => { say("Drawing the tab…"); redraw(); });
  dark.addEventListener("change", redraw);
  narrow.addEventListener("change", redraw);

  api.loadSoundFont(bytesOf(at.soundFont), false);
  api.renderScore(score, [current]);
})();
