(() => {
  "use strict";
  // The screen's choices: how the reader has the screen, whatever the song, kept once for every viewer page (a sheet,
  // a kept version's page, a songbook and a harmonica tab's page), each of which inlines this script in its head
  // (page.py's _page, head_scripts), so that the theme is the page's before its body is drawn: a slow phone never
  // paints the other palette first. The page's own script (viewer.js, harptab.js), after the body, calls it. The one
  // place a viewer page keeps them: the theme (Auto, Light or Dark, Aa's), the keys a pedal sends, and how long the
  // screen stays on (More's Keep the screen on), the one place a page asks for a screen wake lock. It makes no element
  // and loads nothing: the standard library alone.
  //
  // At start-up there is no body yet: what runs as the script runs touches document.documentElement, location,
  // localStorage and performance alone, and looks up no element. Anything added here that needs the body waits for
  // DOMContentLoaded, or is a function the page's own script calls: the key map reads the page only as a key comes,
  // through what the page's script gave keys(), and looks up no element of its own; keeping the screen on listens to
  // the page only once the page's script calls awake().
  //
  // A choice is read as viewer.js reads the others kept for every page (its choiceOf): the one a link names (followed,
  // typed: theme=light or theme=dark, awake=15 in the address), else the browser's (localStorage); on a page come back
  // to (a reload, Back or Forward, a tab restored, a songbook's next song), whose address was written before, the
  // browser's wins over it, and the address counts only where the browser keeps none (caracole serve's sandbox, a
  // songbook's there, a choice never made in this browser). Storage refused (a sandbox, private mode) is no error: the
  // address keeps the choice, as the page's own script writes it (carry). The theme is applied at once, as the script
  // runs in the head: a songbook's contents, where viewer.js doesn't run, follow it too.
  //
  // The theme is html[data-theme]: "light" or "dark", the palette viewer.css picks on screen whatever the system's
  // scheme; no attribute for Auto, the system's. Paper is light whatever it is (viewer.css's print rule).
  //
  // The screen is kept on (the Screen Wake Lock API) while the page shows and either it moves by itself (the page's
  // moving(): autoscroll counting in or scrolling) or the minutes chosen haven't passed since the last touch, key,
  // wheel or scroll (the page being shown counts as one, its first showing too): 10 by default, Off (0) to 60 by 5.
  // The time is performance.now() alone; one timeout waits for the minutes to run out, set again at each touch. A
  // lock is asked for when wanted and none is held or asked, and let go of when not; one the browser lets go of (the
  // page hidden) is asked for again as the page shows again. It never asks navigator.permissions.query first: Android's
  // WebView answers it "denied" while it grants the lock. A request refused waits for the next touch, key or wheel
  // (never for a scroll, which comes a frame at a time) to be asked again. html[data-awake="1"] while a lock is held.
  //
  // window.caracoleScreen (frozen):
  //   THEME            "caracole-viewer-theme", localStorage's name for the theme: "auto", "light" or "dark"
  //   theme()          the theme now: "auto", "light" or "dark"
  //   setTheme(choice) the theme chosen ("auto", "light" or "dark"), applied at once and kept in localStorage for
  //                    every page; a value not of the three is ignored
  //   AWAKE            "caracole-viewer-awake", localStorage's name for the minutes the screen stays on
  //   MINUTES          the minutes offered, in order: 0 (Off), 5, 10 … 60
  //   minutes()        the minutes now, 10 by default
  //   setMinutes(n)    the minutes chosen, one of MINUTES, applied at once (counted from the last touch) and kept in
  //                    localStorage for every page; any other value is ignored
  //   carry(params)    the screen's choices set in params, a URLSearchParams, as an address keeps them: theme=light or
  //                    theme=dark while the theme is Light or Dark, none for Auto (deleted); awake=N while the
  //                    minutes aren't 10 (awake=0 for Off), none at 10; returns params. The page's own script calls it
  //                    where it writes its address and its links to another page of the song, so that where the
  //                    browser keeps nothing the choices go with them.
  //   awake(moving)    the screen kept on for this page: moving, the page's own function, true while it moves by
  //                    itself. The first call (the page's script's, once its body is there) listens for the touches,
  //                    keys, wheels and scrolls (on the window, captured, passive) and the page shown again, counts
  //                    the page's showing as the last touch and asks for the lock; a later one changes moving alone.
  //                    It returns sync(), which the page calls whenever moving() may have changed (autoscroll
  //                    started, paused, ended): the lock asked for or let go of as it is wanted now.
  //   keys({ toggle, pause, room, busy, sheet, steer })
  //                    the key map, for a keyboard and a Bluetooth page turner alike (a pedal is a keyboard): one
  //                    keydown listener on the document, bound by the first call (the page's script's, once its body
  //                    is there; a later one changes what it calls, never binds again). It leaves a key alone that
  //                    another handler took (defaultPrevented) or an input method composes, with Alt, Ctrl, Meta or
  //                    Shift held (the browser's), with a text field focused (input, textarea, select,
  //                    [contenteditable]), and while busy(): a layer of the page has the focus. Space and Enter call
  //                    toggle(), the page's start and stop (the bar's ▶ while autoscroll is off, else the pill's: at
  //                    once while it counts in, a pause while it runs, a count-in again while paused), once however
  //                    long they are held; but not on a focused control (button, a[href], summary, [role=button],
  //                    [tabindex]), whose own press they are, other than full screen's handle (#handle): full screen is
  //                    for reading, the keys work there, and a tap on the handle, Escape or Back brings the controls
  //                    back. PageDown and ArrowDown turn a screen on, PageUp and ArrowUp one back, once however long
  //                    they are held (each repeat taken, doing nothing): pause() (autoscroll paused if it moves,
  //                    its bar back with it), then, measured after it, room() → { top, bottom },
  //                    the CSS px of the window the page's controls leave the song (layers.js toolbar's room), and
  //                    the lines of sheet (its p and pre, shown) wholly between them, a pixel either way: with more
  //                    than KEPT, PageDown brings the KEPT-th last to top and PageUp the KEPT-th to bottom, so that the
  //                    lines last read stay in view; with KEPT alone, the same where it moves the page a line (LINE em)
  //                    or more (the title over them, the strip of chord shapes); else the page goes on by the room less
  //                    KEPT lines of LINE em of the sheet's text, by half the room at least. A song in columns
  //                    (html[data-columns] above 1: the window shows it whole, viewer.js layout), whose lines in
  //                    order run down one column and up the next, turns down at most to bring the sheet's top to top
  //                    (never back up), and up to the page's top. One window.scrollTo, to a whole pixel, never smooth.
  //                    ArrowLeft and ArrowRight are no key of the map (a songbook's songs, book.js), nor is anything
  //                    the version line does: no key changes the page. steer, the buttons that steer autoscroll (the
  //                    bar's ▶ and the pill's): a pointer's press on one takes no focus (its pointerdown and mousedown
  //                    prevented, its click as ever), so that the next Space or Enter is still the map's, never that
  //                    button's own press again; the keyboard reaches them by Tab and presses them as ever.
  //   KEPT             2, the lines a turn keeps in view
  //   LINE             2.6, a line in the em of the sheet's text (a row of chords and its words), for a turn with
  //                    KEPT lines or fewer wholly in view
  const doc = document.documentElement;
  const THEME = "caracole-viewer-theme";
  const THEMES = ["auto", "light", "dark"];
  const returning = (() => {
    try {
      const entry = performance.getEntriesByType("navigation")[0];
      return Boolean(entry) && (entry.type === "reload" || entry.type === "back_forward");
    } catch (err) {
      return false;
    }
  })();
  const choiceOf = (name, named, valid) => {
    let kept = null;
    try {
      kept = localStorage.getItem(name);
    } catch (err) { /* no storage: the address says */ }
    if (!valid.includes(kept)) kept = null;
    return named !== null && (!returning || kept === null) ? named : kept;
  };
  let address = new URLSearchParams();
  try {
    address = new URLSearchParams(location.hash.slice(1));
  } catch (err) { /* an address it can't read names none */ }
  const named = (name, valid) => (valid.includes(address.get(name)) ? address.get(name) : null);
  let theme = choiceOf(THEME, named("theme", ["light", "dark"]), THEMES) || "auto";
  const apply = () => {
    if (theme === "auto") delete doc.dataset.theme;
    else doc.dataset.theme = theme;
  };
  apply();
  const setTheme = (choice) => {
    if (!THEMES.includes(choice)) return;
    theme = choice;
    apply();
    try {
      localStorage.setItem(THEME, theme);
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
  };
  const AWAKE = "caracole-viewer-awake";
  const MINUTES = Object.freeze(Array.from({ length: 13 }, (_, i) => i * 5));  // Off, then 5 to 60
  const SAID = MINUTES.map(String);
  const BY_DEFAULT = 10;
  let minutes = Number(choiceOf(AWAKE, named("awake", SAID), SAID) || BY_DEFAULT);
  const carry = (params) => {
    if (theme === "auto") params.delete("theme");
    else params.set("theme", theme);
    if (minutes === BY_DEFAULT) params.delete("awake");
    else params.set("awake", String(minutes));
    return params;
  };

  // --- the screen kept on ----------------------------------------------------------------------------------------
  let moving = null;  // what awake() was given: nothing until the page's script calls it
  let last = 0, timer = 0, lock = null, asking = false, refused = false;
  const within = () => minutes > 0 && performance.now() - last < minutes * 60000;
  const wanted = () => document.visibilityState !== "hidden" && (moving() || within());
  const forget = (held) => {
    if (lock !== held) return;
    lock = null;
    delete doc.dataset.awake;
  };
  const ask = () => {
    if (!navigator.wakeLock) return;  // a browser without it: the screen as the system has it
    asking = true;
    const no = () => {
      asking = false;
      refused = true;
    };
    try {
      navigator.wakeLock.request("screen").then((got) => {
        asking = false;
        if (!wanted()) {  // no longer, by the time it came
          got.release().catch(() => {});
          return;
        }
        lock = got;
        doc.dataset.awake = "1";
        got.addEventListener("release", () => forget(got));  // the browser let go of it (the page hidden)
      }, no);
    } catch (err) {
      no();
    }
  };
  const sync = () => {
    if (!moving) return;
    if (wanted()) {
      if (!lock && !asking && !refused) ask();
    } else if (lock) {
      const held = lock;
      forget(held);
      held.release().catch(() => {});
    }
  };
  // One timeout for the moment the minutes run out, set again at each touch (none while they are Off): a long one,
  // which a browser may run a little early, is set again for what is left.
  const expire = () => {
    timer = 0;
    if (within()) wait();
    sync();
  };
  const wait = () => {
    clearTimeout(timer);
    timer = 0;
    if (within()) timer = setTimeout(expire, Math.ceil(minutes * 60000 - (performance.now() - last)));
  };
  const touched = (e) => {
    if (!e || e.type !== "scroll") refused = false;  // asked again on a touch, a key, a wheel, the page shown
    last = performance.now();
    wait();
    sync();
  };
  const awake = (given) => {
    const first = moving === null;
    moving = given;
    if (first) {
      for (const kind of ["touchstart", "pointerdown", "keydown", "wheel", "scroll"]) {
        window.addEventListener(kind, touched, { capture: true, passive: true });
      }
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") sync();
        else touched();
      });
      window.addEventListener("pageshow", (e) => { if (e.persisted) touched(); });  // back from the browser's cache
      touched();  // the page shown: the first touch
    }
    return sync;
  };
  const setMinutes = (n) => {
    if (!MINUTES.includes(n)) return;
    minutes = n;
    try {
      localStorage.setItem(AWAKE, String(minutes));
    } catch (err) { /* private mode, or a server's sandbox: the address keeps it */ }
    wait();
    sync();
  };

  const KEPT = 2, LINE = 2.6;
  const TEXT = "input, textarea, select, [contenteditable]";
  const CONTROL = "button, a[href], summary, [role=button], [tabindex]";
  const ON = ["PageDown", "ArrowDown"], BACK = ["PageUp", "ArrowUp"];
  let page = null;  // what keys() was given: nothing until the page's script calls it
  const turn = (way) => {
    const { top, bottom } = page.room();
    const span = bottom - top;
    if (!(span > 0)) return;  // the song out of sight (a sheet over the whole screen): nothing to turn
    const lines = Array.from(page.sheet.getElementsByTagName("p"));
    const tabs = page.sheet.getElementsByTagName("pre");
    if (tabs.length) {  // in the sheet's order
      lines.push(...tabs);
      lines.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    }
    const whole = [];
    for (const el of lines) {
      const r = el.getBoundingClientRect();
      if (r.height && r.top >= top - 1 && r.bottom <= bottom + 1) whole.push(r);
    }
    const em = parseFloat(getComputedStyle(page.sheet).fontSize) || 16;
    let by = null;
    if (whole.length >= KEPT) {
      by = way > 0 ? whole[whole.length - KEPT].top - top : whole[KEPT - 1].bottom - bottom;
      if (whole.length === KEPT && Math.abs(by) < LINE * em) by = null;  // two that fill the room: they'd hardly move
    }
    if (by === null) by = way * Math.max(span / 2, span - KEPT * LINE * em);
    if (Number(doc.dataset.columns) > 1) {  // the whole song shows: its top under the controls, or the page's
      by = way > 0 ? Math.max(0, Math.min(by, page.sheet.getBoundingClientRect().top - top)) : -window.scrollY;
    }
    window.scrollTo(0, Math.round(window.scrollY + by));
  };
  const onKey = (e) => {
    if (!page || e.defaultPrevented || e.isComposing || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const start = e.key === " " || e.key === "Enter";
    const way = ON.includes(e.key) ? 1 : BACK.includes(e.key) ? -1 : 0;
    if (!start && !way) return;
    const at = document.activeElement instanceof Element ? document.activeElement : null;
    if ((at && at.closest(TEXT)) || page.busy()) return;
    if (start) {
      const control = at && at.closest(CONTROL);
      if (control && control.id !== "handle") return;
      e.preventDefault();  // never Space's own screen down, nor the handle's press
      if (!e.repeat) page.toggle();
      return;
    }
    e.preventDefault();  // a repeat too: never the browser's own screen down
    if (e.repeat) return;  // held, as a pedal may: one turn
    page.pause();
    turn(way);
  };
  const steady = (e) => e.preventDefault();  // a pointer's press, with no focus taken
  const keys = (given) => {
    if (page === null) document.addEventListener("keydown", onKey);
    page = given;
    for (const el of given.steer || []) {
      el.addEventListener("pointerdown", steady);
      el.addEventListener("mousedown", steady);
    }
  };
  window.caracoleScreen = Object.freeze({ THEME, theme: () => theme, setTheme, AWAKE, MINUTES, minutes: () => minutes,
    setMinutes, carry, awake, keys, KEPT, LINE });
})();
