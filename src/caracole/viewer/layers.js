(() => {
  "use strict";
  // A page's layers: what a viewer page opens over its sheet (the settings, Aa, a chord's card, the necks' sheet, the
  // versions list), each one entry of the browser's history while it is open, so that Back, a phone's or the app's,
  // closes the one on top rather than leaving the page. Inlined on every viewer page (sheet.html and a kept version's
  // page, a songbook, a harmonica tab's page) before the page's own script, which calls it. It makes no element of its
  // own and loads nothing: the standard library alone.
  //
  // window.caracoleLayers:
  //   history(back)    the history's side of a page's layers: { sync(count) }. sync(count) says how many layers are
  //                    open now (a count that is no whole number above 0, none: never fewer entries than the page's
  //                    own); at the end of the task (a microtask) the entries above the page's own are made that
  //                    many: history.pushState({ caracoleLayer: n }, "") for each one more (n its depth, 1 for the
  //                    first), with no address (the document's own, which caracole serve's sandbox allows), and
  //                    history.go(-k) for k fewer. A Back that takes k entries off calls back(k): the page closes its
  //                    k top layers and calls sync again (then nothing to do). Forward onto a layer's entry, or the
  //                    page loaded at one (a reload, Back from a page a layer's link opened), goes back to the entry
  //                    of what is open. A go the page asked for (k layers closed, or the page loaded at a layer's
  //                    entry) takes the page's address down with it to the entry it comes to (history.replaceState), so
  //                    what the page wrote there while a layer was open (a key changed with the settings open) stays;
  //                    after a Back the page writes its own (back(k)). A step down to an entry under a layer leaves the
  //                    page scrolled where it is: history.scrollRestoration is "manual" from the first layer's entry on
  //                    (the song scrolled under a layer stays where it is as the layer closes), "auto" again once the
  //                    page is back at its own entry (a reload restores the place). A pushState or a go that throws (a
  //                    browser's history refused on file:) turns it off for good: the layers still open and close, and
  //                    Back leaves the page.
  //
  //   doubleTap(root, skip, then)
  //                    then(event) on a double tap on root: two clicks within DOUBLE_MS (350) ms and DOUBLE_PX
  //                    (30) px of each other, neither on an element inside what the selector skip matches (a click
  //                    there starts none), a keyboard's click (detail 0) never counting. The sheet viewer's full
  //                    screen, by a double tap beside the song.
  //   MARGIN_SKIP      the selector of what a double tap beside the song skips: the song's own elements (a chord, a
  //                    word, a tab, the title, the facts, the notes, the credit, the foot) and every control. The
  //                    sheet viewer passes it as it is, the harmonica tab's page with its own elements added.
  //
  //   SHORT            the media query of a short screen, a phone on its side: (max-height: 499.98px).
  //   autoFull({ handle, idle, changed })
  //                    the short screen's rule, written once for the pages: while SHORT matches, at start and as it
  //                    changes, html's data-full is "auto" (the page in full screen of itself, "on" being the reader's
  //                    own) and handle shown, when idle() says no layer is open, no data-full is set and the reader
  //                    has not ended it; when it stops matching the "auto" is deleted and the handle hidden. changed()
  //                    is called after either. It makes no history entry. Returns { end() }: ends an "auto" (the
  //                    handle's tap, Escape, any layer opened) and keeps it ended until SHORT changes again.
  //
  // The marker is an entry's state's caracoleLayer, an integer from 1; every history.replaceState in viewer/'s
  // scripts passes history.state, never null, so that an entry keeps its depth through what the page writes into its
  // address.

  const depthOf = (s) => (s && Number.isInteger(s.caracoleLayer) && s.caracoleLayer > 0 ? s.caracoleLayer : 0);

  const layerHistory = (back) => {
    // pushed: the depth of the entry the tab is at, as the page last heard; wanted: the layers open; pending: a go
    // of ours on its way, until its popstate; queued: a settle due at the task's end; off: the history refused us;
    // carry: the page's address as a go of ours left it, for the entry the go comes to.
    let pushed = depthOf(history.state), wanted = 0, pending = false, queued = false, off = false, carry = null;
    const scrolls = (mode) => {
      try {
        history.scrollRestoration = mode;
      } catch (err) { /* a browser without it: as it scrolls */ }
    };
    // ``carrying``: a go the page asked for (a layer closed, or the page loaded at a layer's entry) takes its address
    // down with it; a Forward's takes none, its entry's address older than the one it goes back to.
    const settle = (carrying = true) => {
      queued = false;
      if (off || pending || wanted === pushed) return;
      try {
        if (wanted > pushed) {
          scrolls("manual");  // a step down to the entry under a layer leaves the page scrolled where it is
          for (; pushed < wanted; pushed++) history.pushState({ caracoleLayer: pushed + 1 }, "");
        } else {
          carry = carrying ? location.href : null;
          pending = true;
          history.go(wanted - pushed);
        }
      } catch (err) {
        off = true;
        pending = false;
        carry = null;
        scrolls("auto");
      }
    };
    // Down at the page's own entry, a task after the step (which scrolled nothing): a reload restores the place.
    const landed = () => {
      if (pushed === 0) setTimeout(() => { if (pushed === 0) scrolls("auto"); }, 0);
    };
    addEventListener("popstate", (e) => {
      const depth = depthOf(e.state);
      let ours = false;
      if (pending) {  // our own go, arrived: the page's address with it
        pending = false;
        ours = true;
        if (carry !== null && carry !== location.href) {
          try {
            history.replaceState(history.state, "", carry);
          } catch (err) { /* an address the page can't change */ }
        }
        carry = null;
      } else if (depth < pushed) {
        const k = pushed - depth;
        pushed = depth;
        back(k);
        settle();
        landed();
        return;
      }
      pushed = depth;  // a Forward onto a layer's entry, or our go: back to what is open
      settle(ours);
      landed();
    });
    settle();  // a page loaded at a layer's entry, with none open yet
    return Object.freeze({
      sync(count) {
        wanted = Number.isInteger(count) && count > 0 ? count : 0;  // never below the page's own entry
        if (!queued) { queued = true; queueMicrotask(settle); }
      },
    });
  };

  const DOUBLE_MS = 350, DOUBLE_PX = 30;
  const MARGIN_SKIP = "a, button, input, select, textarea, summary, label, [role=button], [tabindex], .c, .s, .w, .y, .m, "
    + "pre, h1, h2, h3, .artist, .facts, .versions, .sheet-ui, .bar, .pill, .handle, .necks, .strip, .tip, details, .notice, "
    + ".credit, .foot, .pager";
  const doubleTap = (root, skip, then) => {
    let last = null;  // the click before, a double tap's first: when and where
    // On what skip matches, by the click's path as it was dispatched: a handler before this one may have drawn its
    // target anew (a neck's dot picked), out of the page.
    const skipped = (e) => Boolean(skip) && e.composedPath().some((n) => n instanceof Element && n.matches(skip));
    root.addEventListener("click", (e) => {
      if (!e.detail || !(e.target instanceof Element) || skipped(e)) {
        last = null;
        return;
      }
      if (last && e.timeStamp - last.t <= DOUBLE_MS && Math.hypot(e.clientX - last.x, e.clientY - last.y) <= DOUBLE_PX) {
        last = null;
        then(e);
        return;
      }
      last = { t: e.timeStamp, x: e.clientX, y: e.clientY };
    });
  };

  const SHORT = "(max-height: 499.98px)";
  const autoFull = ({ handle, idle, changed }) => {
    const doc = document.documentElement, mq = matchMedia(SHORT);
    let slimmed = false;  // the reader ended it: no "auto" again until SHORT changes
    const sync = (first) => {
      if (mq.matches) {
        if (!first) slimmed = false;
        if (!idle() || doc.dataset.full || slimmed) return;
        doc.dataset.full = "auto";
        handle.hidden = false;
      } else {
        slimmed = false;
        if (doc.dataset.full !== "auto") return;
        delete doc.dataset.full;
        handle.hidden = true;
      }
      changed();
    };
    mq.addEventListener("change", () => sync(false));
    sync(true);
    return Object.freeze({
      end() {
        slimmed = true;
        if (doc.dataset.full !== "auto") return;
        delete doc.dataset.full;
        handle.hidden = true;
        changed();
      },
    });
  };

  window.caracoleLayers = Object.freeze({ history: layerHistory, doubleTap, autoFull, SHORT, DOUBLE_MS, DOUBLE_PX,
    MARGIN_SKIP });
})();
