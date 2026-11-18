"""A song's card, found by its chevron: the element whose id the line's ``.line-more`` names in ``aria-controls``,
wherever the page puts it (under its line, or in the laptop's pane)::

    from helpers import cards

``KIT``: JavaScript for a page's script, which declares ``cardOf(line)`` (the card of a line, or null), ``openCardOf(line)``
(clicks the chevron unless ``aria-expanded`` is "true"; returns ``cardOf(line)``) and ``closeCard(line)``. A script that
also holds test_library_card.py's title form, ``openCard(title)``, declares each name once.

``install(page)``: for a ``Browser``, the same three as ``window.cardOf``, ``window.openCardOf`` and
``window.closeCard``, for ``page.js`` and ``page.wait`` (an evaluation can't declare a ``const`` twice).
``open_card(page, line_selector)`` opens the line's card and returns ``"#" + its id``, a selector for ``page.click``.

``card_js(line_selector)``: a self-contained JavaScript expression, the card of the line ``line_selector`` finds (null when
the line or its card is not there), for ``page.js`` and ``page.wait`` with no ``install``.

``card_of(dom, title)``: from a DOM dump, the markup of the element the chevron of the line headed ``title`` names (nested
elements counted), or "" when there is none; a test opens the card first (a script that clicks the chevron).

``IN_PLACE``: the widest window ("1024,900") whose cards open under their lines, for a test that reads several cards of
one page in one dump.
"""

from __future__ import annotations

from html.parser import HTMLParser

IN_PLACE = "1024,900"

KIT = r"""
const cardOf = (line) => {
  const more = line && line.querySelector(".line-more");
  return more ? document.getElementById(more.getAttribute("aria-controls")) : null;
};
const openCardOf = (line) => {
  const more = line.querySelector(".line-more");
  if (more.getAttribute("aria-expanded") !== "true") more.click();
  return cardOf(line);
};
const closeCard = (line) => {
  const more = line.querySelector(".line-more");
  if (more.getAttribute("aria-expanded") === "true") more.click();
};
"""

_GLOBALS = """
window.cardOf = (line) => {
  const more = line && line.querySelector(".line-more");
  return more ? document.getElementById(more.getAttribute("aria-controls")) : null;
};
window.openCardOf = (line) => {
  const more = line.querySelector(".line-more");
  if (more.getAttribute("aria-expanded") !== "true") more.click();
  return window.cardOf(line);
};
window.closeCard = (line) => {
  const more = line.querySelector(".line-more");
  if (more.getAttribute("aria-expanded") === "true") more.click();
};
"""


def install(page) -> None:
    """``cardOf``, ``openCardOf`` and ``closeCard`` on the page's ``window``."""
    page.js(_GLOBALS)


def card_js(line_selector: str) -> str:
    """The card of the line ``line_selector`` finds, as an expression (null: no line, no chevron or no card)."""
    import json

    return ("(() => { const l = document.querySelector(" + json.dumps(line_selector) + "); "
            "const m = l && l.querySelector('.line-more'); "
            "return m ? document.getElementById(m.getAttribute('aria-controls')) : null; })()")


def open_card(page, line_selector: str) -> str:
    """The card of the line ``line_selector`` finds, opened; ``"#" + its id``."""
    install(page)
    import json

    shown = json.dumps(line_selector)
    card_id = page.js(f"(() => {{ const c = window.openCardOf(document.querySelector({shown})); return c && c.id; }})()")
    if not card_id:
        raise AssertionError(f"no card for {line_selector}")
    return "#" + card_id


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Lines(HTMLParser):
    """Each line's title and the id its chevron names."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[list[str]] = []  # [title, controls]
        self._in_h3 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "article" and "line" in classes:
            self.lines.append(["", ""])
        elif self.lines and tag == "h3" and not self.lines[-1][0]:
            self._in_h3 = True
        elif self.lines and tag == "button" and "line-more" in classes and not self.lines[-1][1]:
            self.lines[-1][1] = a.get("aria-controls") or ""

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_h3 = False

    def handle_data(self, data):
        if self._in_h3:
            self.lines[-1][0] += data


class _Element(HTMLParser):
    """The markup of the element with id ``wanted``, its nested elements counted."""

    def __init__(self, text: str, wanted: str):
        super().__init__(convert_charrefs=False)
        self.text, self.wanted = text, wanted
        self.starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.starts.append(i + 1)
        self.begin = self.end = None
        self.tag = None
        self.depth = 0

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.end is not None:
            return
        if self.begin is None:
            if dict(attrs).get("id") == self.wanted:
                self.begin, self.tag, self.depth = self._offset(), tag, 1
                if tag in _VOID:
                    self.end = self.begin + len(self.get_starttag_text())
        elif tag == self.tag and tag not in _VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.begin is None or self.end is not None or tag != self.tag:
            return
        self.depth -= 1
        if self.depth == 0:
            start = self._offset()
            self.end = self.text.index(">", start) + 1


def card_of(dom: str, title: str) -> str:
    """The markup of the card the chevron of the line headed ``title`` names; "" when there is none."""
    lines = _Lines()
    lines.feed(dom)
    controls = next((c for t, c in lines.lines if t.strip() == title and c), "")
    if not controls:
        return ""
    found = _Element(dom, controls)
    found.feed(dom)
    return dom[found.begin:found.end] if found.begin is not None and found.end is not None else ""
