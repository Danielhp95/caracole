// caracole serve's Guitar Pro page (guitar_page.py): the song's Guitar Pro file, drawn and played by alphaTab.
//
// The file's bytes are in the page (#gp, base64); alphaTab, its music font and its SoundFont come in the one
// script caracole serve sends with it (window.caracoleAlphaTab, web/alphatab.py). The page runs in a sandbox, an
// origin of its own, and loads nothing else: the font is a data: URI, the SoundFont is handed over as bytes, and
// alphaTab's synthesizer runs in a worker made from a blob: of the library's own text. Its audio goes through a
// ScriptProcessor, since an AudioWorklet module can't be loaded here. Every element is made with createElement and
// textContent. The page says where it stands on <html> (data-rendered, the times the score was drawn;
// data-player: loading, ready, playing, paused; data-track, the tracks shown, their indexes joined by commas), for
// the tests.
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
  const percussion = (track) => track.staves.some((staff) => staff.isPercussion) ||
    (track.playbackInfo && track.playbackInfo.primaryChannel === 9);  // MIDI's channel 10
  const hasTab = (track) => Boolean(track) && !percussion(track) && track.staves.some((staff) =>
    staff.showTablature && staff.tuning && staff.tuning.length > 0);
  // A drum kit: a percussion track, or one written as strings that are all tuned to MIDI's note 0, as Guitar Pro 5
  // files from elsewhere carry the drums (on channel 10, which alphaTab moves when the track isn't marked as drums):
  // its tab's numbers are the drums' notes, so its tab is still shown.
  const drums = (track) => percussion(track) || track.staves.some((staff) =>
    staff.tuning && staff.tuning.length > 0 && staff.tuning.every((note) => note === 0));
  let score = null;
  let shown = [0];  // the indexes of the tracks shown, in the score's order
  const viewSwitch = $("view");
  const look = (s) => {
    s.fillFromJson(colours());
    const tab = score === null || shown.every((index) => hasTab(score.tracks[index]));
    viewSwitch.disabled = !tab;
    s.display.staveProfile = tabOnly() && tab ? lib.StaveProfile.Tab : lib.StaveProfile.Default;
    s.display.scale = narrow.matches ? 0.8 : 1;
  };

  // alphaTab's canvas (1.8.4) draws each part of the score (the header, the tuning's box, each line of bars, its
  // name at the foot) on a fresh <canvas> the size of the part's box, and some of what it draws reaches past that
  // box: the header's first line, drawn hanging from the box's very top in a font whose letters rise above that
  // line, a tempo's note over the bars. A canvas cuts it. So each one is made ROOM px taller above the box and below
  // it, its drawing moved down by as much and the canvas itself up by as much: what alphaTab draws lands where it
  // put it, and what reaches past the box shows, in the room between two parts, as in alphaTab's SVG (whose parts
  // are overflow: visible). The fresh 2D context starts black, too, and alphaTab gives it a colour only when that
  // differs from the last colour it set: a part that starts in the colour the one before ended in (the score's
  // header, after notes drawn in the same --text) was drawn black, unreadable on the dark page. Each fresh context
  // is given the colour alphaTab takes it to have.
  const ROOM = 12;
  const contexts = (canvas) => Object.values(canvas).filter((v) => v instanceof CanvasRenderingContext2D);
  const mend = (canvas) => {
    const proto = Object.getPrototypeOf(canvas);
    if (proto.caracoleMended) return;
    proto.caracoleMended = true;
    const begin = proto.beginRender;
    proto.beginRender = function (width, height, ...rest) {
      const before = contexts(this);
      const result = begin.call(this, width, height + 2 * ROOM, ...rest);
      const context = contexts(this).find((c) => !before.includes(c));
      if (context) {
        const element = context.canvas;
        const m = context.getTransform();  // alphaTab's scale: the page's pixel ratio times the score's
        context.setTransform(m.a, m.b, m.c, m.d, m.e, m.f + ROOM * element.height / (height + 2 * ROOM));
        element.style.position = "relative";
        element.style.top = -ROOM + "px";
        context.fillStyle = context.strokeStyle = this.color.rgba;
      }
      return result;
    };
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
  shown = [Math.max(0, score.tracks.findIndex(hasTab))];
  look(settings);

  const api = new lib.AlphaTabApi($("score"), settings);
  window.caracoleGuitar = api;
  if (api.renderer.instance && api.renderer.instance.canvas) mend(api.renderer.instance.canvas);
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

  // The tracks, laid out: a button for each, its name and its instrument, pressed while it is shown, and a speaker
  // on it that mutes it. A tap shows that track alone; with Shift, Ctrl or ⌘ held it is shown beside those shown, or
  // taken away from them (the last one stays). A track stays muted, whichever is shown, while the page is open: the
  // synthesizer mutes its channels at once, playing or not, and keeps them muted (alphaTab never resets them; and
  // the track's playbackInfo says so too).
  const bar = $("tracks");
  const trackName = (track, index) => String(track.name || "").trim() || "Track " + (index + 1);
  const trackKind = (track) => {
    if (drums(track)) return "drums";
    const staff = track.staves[0];
    const strings = staff && staff.tuning ? staff.tuning.length : 0;
    return strings ? strings + " strings" : "";
  };
  const SVG = "http://www.w3.org/2000/svg";
  const speaker = () => {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const shape = (d, cls) => {
      const path = svg.appendChild(document.createElementNS(SVG, "path"));
      path.setAttribute("d", d);
      if (cls) path.setAttribute("class", cls);
    };
    shape("M4 9h4l5-4v14l-5-4H4z", "cone");
    shape("M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12", "waves");
    shape("M16 9l6 6M22 9l-6 6", "cross");
    return svg;
  };
  const buttons = [];
  const mark = () => {
    root.dataset.track = shown.join(",");
    buttons.forEach(({ show }, index) => show.setAttribute("aria-pressed", String(shown.includes(index))));
  };
  const showTracks = (indexes) => {
    shown = indexes;
    mark();
    say("Drawing the tab…");
    look(api.settings);
    api.updateSettings();
    api.renderTracks(shown.map((index) => score.tracks[index]));
  };
  const mute = (index, muted) => {
    const track = score.tracks[index];
    track.playbackInfo.isMute = muted;
    api.changeTrackMute([track], muted);
    const { item, button } = buttons[index];
    item.classList.toggle("muted", muted);
    button.setAttribute("aria-pressed", String(muted));
  };
  score.tracks.forEach((track, index) => {
    const name = trackName(track, index);
    const item = bar.appendChild(document.createElement("div"));
    item.className = "track";
    const button = item.appendChild(document.createElement("button"));
    button.type = "button";
    button.className = "mute";
    button.setAttribute("aria-label", "Mute " + name);
    button.setAttribute("aria-pressed", "false");
    button.title = "Mute " + name;
    button.appendChild(speaker());
    const show = item.appendChild(document.createElement("button"));
    show.type = "button";
    show.className = "show";
    show.appendChild(document.createElement("span")).textContent = name;
    show.firstChild.className = "name";
    const kind = trackKind(track);
    if (kind) {
      const small = show.appendChild(document.createElement("span"));
      small.className = "kind";
      small.textContent = kind;
    }
    buttons.push({ item, button, show });
    button.addEventListener("click", () => mute(index, button.getAttribute("aria-pressed") !== "true"));
    show.addEventListener("click", (e) => {
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        const next = shown.includes(index) ? shown.filter((i) => i !== index) : shown.concat(index).sort((a, b) => a - b);
        if (next.length && next.join() !== shown.join()) showTracks(next);
      } else if (shown.length !== 1 || shown[0] !== index) {
        showTracks([index]);
      }
    });
  });
  bar.hidden = score.tracks.length < 2;
  mark();

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
  api.renderScore(score, shown);
})();
