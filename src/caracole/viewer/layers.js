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
  //                    of what is open. A pushState or a go that throws (a browser's history refused on file:) turns
  //                    it off for good: the layers still open and close, and Back leaves the page.
  //
  // The marker is an entry's state's caracoleLayer, an integer from 1; every history.replaceState in viewer/'s
  // scripts passes history.state, never null, so that an entry keeps its depth through what the page writes into its
  // address.

  const depthOf = (s) => (s && Number.isInteger(s.caracoleLayer) && s.caracoleLayer > 0 ? s.caracoleLayer : 0);

  const layerHistory = (back) => {
    // pushed: the depth of the entry the tab is at, as the page last heard; wanted: the layers open; pending: a go
    // of ours on its way, until its popstate; queued: a settle due at the task's end; off: the history refused us.
    let pushed = depthOf(history.state), wanted = 0, pending = false, queued = false, off = false;
    const settle = () => {
      queued = false;
      if (off || pending || wanted === pushed) return;
      try {
        if (wanted > pushed) for (; pushed < wanted; pushed++) history.pushState({ caracoleLayer: pushed + 1 }, "");
        else { pending = true; history.go(wanted - pushed); }
      } catch (err) { off = true; pending = false; }
    };
    addEventListener("popstate", (e) => {
      const depth = depthOf(e.state);
      if (pending) pending = false;  // our own go, arrived
      else if (depth < pushed) { const k = pushed - depth; pushed = depth; back(k); return settle(); }
      pushed = depth;  // a Forward onto a layer's entry, or our go: back to what is open
      settle();
    });
    settle();  // a page loaded at a layer's entry, with none open yet
    return Object.freeze({
      sync(count) {
        wanted = Number.isInteger(count) && count > 0 ? count : 0;  // never below the page's own entry
        if (!queued) { queued = true; queueMicrotask(settle); }
      },
    });
  };

  window.caracoleLayers = Object.freeze({ history: layerHistory });
})();
