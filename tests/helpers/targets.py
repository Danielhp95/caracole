"""What a thumb and an eye need of a page's controls, measured in Chromium (helpers/browser.py).

``small_targets(exempt)`` lists every control shown that is less than 44 px either way: a link, a
button, a field, a menu or a fold's summary (a box or a radio counts as its label, the Select mode's
box as its frame). A link in a line of text is left out, as WCAG 2.5.8 leaves it out, and so is
whatever the CSS selector ``exempt`` matches.

``weak_edges(exempt)`` lists every field, menu and Select box shown whose edge is less than 3:1
against the colour around it or its own fill (WCAG 1.4.11); a box filled with its edge's colour is
measured against what is around it alone.

Each is a JavaScript expression whose value is that list, for ``Browser.js``, or for ``noting``: a
script a test adds to the page (``with_script``), which writes the value into an attribute of the
body for ``noted`` to read back from ``dump_dom``. ``UNFOLD`` opens every fold, every row's "⋯" and
the library page's View (Key, Sort, Cards and Rows on a phone) first, so that what they hold is
measured too.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

# What a test names each control by: its tag and classes, and its parent's first class.
_NAME = r"""
const name = (node) => {
  const classes = (n) => (typeof n.className === "string" ? n.className.trim().split(/\s+/).filter(Boolean) : []);
  const own = classes(node);
  const up = node.parentElement ? classes(node.parentElement) : [];
  return node.tagName.toLowerCase() + (own.length ? "." + own.join(".") : "") + (up.length ? " in ." + up[0] : "");
};
const said = (node) => String(node.getAttribute("aria-label") || node.textContent || node.value || "").trim()
  .replace(/\s+/g, " ").slice(0, 32);
"""

_SMALL = r"""
((exempt) => {
  __NAME__
  // A link among words of its own, in a line of text: WCAG 2.5.8 exempts it.
  const inText = (node) => node.tagName === "A" && getComputedStyle(node).display === "inline" &&
    node.parentElement.textContent.trim() !== node.textContent.trim();
  const short = [];
  for (const node of document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, summary')) {
    if (!node.checkVisibility() || (exempt && node.matches(exempt)) || inText(node)) continue;
    const target = node.matches(".pick input") ? node.parentElement
      : node.matches('input[type="checkbox"], input[type="radio"]') ? node.closest("label") || node : node;
    const box = target.getBoundingClientRect();
    if (box.width < 43.5 || box.height < 43.5) {
      short.push({ what: name(node), said: said(node), width: Math.round(box.width), height: Math.round(box.height) });
    }
  }
  return short;
})
"""

_WEAK = r"""
((exempt) => {
  __NAME__
  const rgb = (text) => {
    const m = /^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/.exec(text);
    return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])] : null;
  };
  const luminance = (c) => {
    const f = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const around = (node) => {
    for (let n = node.parentElement; n; n = n.parentElement) {
      const c = rgb(getComputedStyle(n).backgroundColor);
      if (c && c[3] === 1) return c;
    }
    return [255, 255, 255, 1];
  };
  const weak = [];
  const fields = 'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), select, textarea, .pick';
  for (const node of document.querySelectorAll(fields)) {
    if (!node.checkVisibility() || (exempt && node.matches(exempt))) continue;
    const style = getComputedStyle(node);
    const edge = parseFloat(style.borderTopWidth) > 0 ? rgb(style.borderTopColor) : null;
    const fill = rgb(style.backgroundColor);
    // A ring shows against what is around it and its own fill; a box filled with its edge's colour (a picked
    // one) is one solid shape, against what is around it alone.
    const solid = edge && fill && edge.slice(0, 3).join() === fill.slice(0, 3).join();
    const against = [around(node)].concat(fill && fill[3] === 1 && !solid ? [fill] : []);
    const worst = edge ? Math.min(...against.map((c) => ratio(edge, c))) : 0;
    if (!(worst >= 3)) {
      weak.push({ what: name(node), said: said(node), edge: style.borderTopColor, fill: style.backgroundColor,
                  ratio: Math.round(worst * 100) / 100 });
    }
  }
  return weak;
})
"""

UNFOLD = """
for (const fold of document.querySelectorAll("details")) fold.open = true;
for (const panel of document.querySelectorAll(".row-panel")) panel.hidden = false;
for (const panel of document.querySelectorAll(".view-panel")) panel.classList.add("open");
"""


def small_targets(exempt: str = "") -> str:
    """An expression: the controls shown that are less than 44 px either way (``exempt`` left out)."""
    return _SMALL.replace("__NAME__", _NAME) + f"({json.dumps(exempt)})"


def weak_edges(exempt: str = "") -> str:
    """An expression: the fields, menus and Select boxes shown whose edge is under 3:1."""
    return _WEAK.replace("__NAME__", _NAME) + f"({json.dumps(exempt)})"


def noting(attribute: str, expression: str) -> str:
    """A statement that writes the expression's value, as JSON, into an attribute of the body."""
    return f"document.body.setAttribute({json.dumps(attribute)}, JSON.stringify({expression}));\n"


def noted(dom: str, attribute: str) -> Any:
    """What ``noting`` wrote into ``attribute``, read back from a DOM dump."""
    found = re.search(rf'{re.escape(attribute)}="([^"]*)"', dom)
    assert found, f"the page noted no {attribute}: {dom[-1500:]}"
    return json.loads(html.unescape(found.group(1)))
