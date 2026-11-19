(() => {
  "use strict";
  // The screen's choices: how the reader has the screen, whatever the song, kept once for every viewer page (a sheet,
  // a kept version's page, a songbook and a harmonica tab's page), each of which inlines this script in its head
  // (page.py's _page, head_scripts), so that the theme is the page's before its body is drawn: a slow phone never
  // paints the other palette first. The page's own script (viewer.js, harptab.js), after the body, calls it. The one
  // place a viewer page keeps them: the theme now (Auto, Light or Dark, Aa's); the keys and keeping the screen on come
  // here too. It makes no element and loads nothing: the standard library alone.
  //
  // At start-up there is no body yet: what runs as the script runs touches document.documentElement, location,
  // localStorage and performance alone, and looks up no element. Anything added here that needs the body waits for
  // DOMContentLoaded, or is a function the page's own script calls.
  //
  // A choice is read as viewer.js reads the others kept for every page (its choiceOf): the one a link names (followed,
  // typed: theme=light or theme=dark in the address), else the browser's (localStorage); on a page come back to (a
  // reload, Back or Forward, a tab restored, a songbook's next song), whose address was written before, the browser's
  // wins over it, and the address counts only where the browser keeps none (caracole serve's sandbox, a songbook's
  // there, a choice never made in this browser). Storage refused (a sandbox, private mode) is no error: the address
  // keeps the choice, as the page's own script writes it (carry). It is applied at once, as the script runs in the
  // head: a songbook's contents, where viewer.js doesn't run, follow it too.
  //
  // The theme is html[data-theme]: "light" or "dark", the palette viewer.css picks on screen whatever the system's
  // scheme; no attribute for Auto, the system's. Paper is light whatever it is (viewer.css's print rule).
  //
  // window.caracoleScreen (frozen):
  //   THEME            "caracole-viewer-theme", localStorage's name for the theme: "auto", "light" or "dark"
  //   theme()          the theme now: "auto", "light" or "dark"
  //   setTheme(choice) the theme chosen ("auto", "light" or "dark"), applied at once and kept in localStorage for
  //                    every page; a value not of the three is ignored
  //   carry(params)    the screen's choices set in params, a URLSearchParams, as an address keeps them: theme=light or
  //                    theme=dark while the theme is Light or Dark, none for Auto (deleted); returns params. The page's
  //                    own script calls it where it writes its address and its links to another page of the song, so
  //                    that where the browser keeps nothing the choices go with them.
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
  let named = null;
  try {
    const asked = new URLSearchParams(location.hash.slice(1)).get("theme");
    if (asked === "light" || asked === "dark") named = asked;
  } catch (err) { /* an address it can't read names none */ }
  let theme = choiceOf(THEME, named, THEMES) || "auto";
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
  const carry = (params) => {
    if (theme === "auto") params.delete("theme");
    else params.set("theme", theme);
    return params;
  };
  window.caracoleScreen = Object.freeze({ THEME, theme: () => theme, setTheme, carry });
})();
