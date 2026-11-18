"""A chosen theme picks the viewer's palette on screen, whatever the system's scheme (viewer.css).

``html[data-theme="light"|"dark"]`` wins over ``prefers-color-scheme``; no attribute is Auto, today's rule. The dark
palette is written twice (a media query and an attribute can't share a selector): this test fails on any token one
copy lacks.
"""

from __future__ import annotations

from helpers.browser import CHROMIUM_MARKS
from helpers.viewer_pages import viewer, written

pytestmark = CHROMIUM_MARKS

SONG = """{title: Theme Song}
{key: C}
{start_of_verse: Verse}
[C]First line of the [G]song
[Am]Second line goes [F]on
[C]Third line of the [G]song
{end_of_verse}
{start_of_chorus: Chorus}
[F]Fourth line to [C]sing
[G]Fifth line to [Am]sing
[F]Sixth line to [C]end
{end_of_chorus}
"""

PALETTE = """(() => { const root = [...document.styleSheets].flatMap((s) => [...s.cssRules])
    .find((r) => r.selectorText === ":root" && r.style.getPropertyValue("--bg"));
  const css = getComputedStyle(document.documentElement);
  return {scheme: css.colorScheme, vars: Object.fromEntries([...root.style].filter((n) => n.startsWith("--"))
    .map((n) => [n, css.getPropertyValue(n).trim()]))}; })()"""


def test_a_chosen_theme_wins_over_the_system_on_screen(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        own, chosen = {}, {}
        for system in ("light", "dark"):
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system}])
            b.js("delete document.documentElement.dataset.theme")
            own[system] = b.js(PALETTE)
            for theme in ("light", "dark"):
                b.js(f"document.documentElement.dataset.theme = '{theme}'")
                chosen[system, theme] = b.js(PALETTE)
    assert own["light"]["vars"]["--bg"] == "#f7f6f3" and own["dark"]["vars"]["--bg"] == "#131312"
    for (system, theme), seen in chosen.items():
        assert seen["vars"] == own[theme]["vars"], (system, theme)  # one dark palette, one light
        assert seen["scheme"] == theme
