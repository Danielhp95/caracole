"""The song's timed lyrics matched to its sheet's lines, so the page can light the line being sung.

``sung_lines(drawn, timed)`` takes the sheet's lines as the page draws them (page.py ``_drawn_lines``: the lines the
data's ``pinyin`` indexes, a line of chords alone "" among them) and the lyrics' timed lines (lyrics.py
``synced_lines``: ``(seconds, text)`` in time order), and gives each timed line the sheet line it is sung on, by its
index, or None: the page's data ``sung``, ``[[ms, n or null], …]`` (page.py ``build_viewer``).

- **Top to bottom.** The sheet reads top to bottom as the song is sung, so the match is monotone: a timed line is
  sung on a sheet line below the one before it, never above. Of all such matches, the one that pairs the most lines
  (a longest common subsequence), and among those, each timed line paired as early as it can be: a sheet that writes
  a chorus once lights it the first time it is sung, and the times it comes back light nothing.
- **Words written otherwise.** Two lines meet when their keys (``line_key``: their words as normalize.py's
  ``name_words`` cuts them, accents and case folded, punctuation and apostrophes dropped) are rapidfuzz's ``ratio``
  ``LINE_MATCH`` or more alike, so "driftin'" is "drifting"; a line with no words (an instrumental break, a line of
  chords alone) meets none.
- **Chinese in either script.** Each key is written in Simplified characters first (normalize.py ``simplified``):
  lyrics in Traditional characters meet a sheet in Simplified ones, and the other way round.
- **Enough or nothing.** A match of fewer than ``MIN_LINES`` lines, or of fewer than ``MIN_SHARE`` of the sheet's
  lines with words, is no match: the lyrics are of another version, or barely the sheet's, and the page lights
  nothing (None, and the data has no ``sung``).
- **A time the song can be at.** A timed line from 0 s to under ``MAX_SECONDS`` (a day) alone is read, so its time
  in milliseconds, ``round(seconds * 1000)`` (Python's, half to even), is a finite whole number; any other is left
  out.

rapidfuzz is imported by ``sung_lines`` alone, when there are enough timed lines to match: a page with no timed
lyrics, and importing ``caracole.cli``, never load it.
"""

from __future__ import annotations

from collections.abc import Sequence

from caracole.normalize import name_words, simplified

LINE_MATCH = 80  # rapidfuzz ratio of two lines' keys for the one to be sung on the other
MIN_SHARE = 0.5  # of the sheet's lines with words, the share a match must light
MIN_LINES = 4  # and the lines it must light at least
MAX_SECONDS = 86400  # a timed line at a day or more is no song's


def line_key(text: str) -> str:
    """A line's words as the match compares them: in Simplified characters, as ``name_words`` cuts them, one space
    between; "" for a line with none."""
    return " ".join(name_words(simplified(text)))


def sung_lines(drawn: Sequence[str], timed: Sequence[Sequence]) -> list[list[int | None]] | None:
    """For each timed line ``(seconds, text)`` of ``timed`` from 0 to under ``MAX_SECONDS``, in the order given,
    ``[round(seconds * 1000), n]``: ``n`` the index in ``drawn`` of the sheet line it is sung on, or None (the
    module's docstring says how they are matched). None for the whole when fewer than ``MIN_LINES``, or fewer than
    ``MIN_SHARE`` of ``drawn``'s lines with words, are matched."""
    sung = [(round(s * 1000), line_key(t)) for s, t in timed if 0 <= s < MAX_SECONDS]
    if len(sung) < MIN_LINES:
        return None
    from rapidfuzz import fuzz

    keys = [line_key(t) for t in drawn]
    n, m = len(keys), len(sung)
    fits = [[bool(a) and bool(b) and fuzz.ratio(a, b) >= LINE_MATCH for _, b in sung] for a in keys]
    # best[i][j]: the most pairs matchable from sheet line i and timed line j on (0 past either's end)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, below = best[i], best[i + 1]
        for j in range(m - 1, -1, -1):
            row[j] = max(below[j], row[j + 1], 1 + below[j + 1] if fits[i][j] else 0)
    on: list[int | None] = [None] * m
    i = j = 0
    while i < n and j < m:
        if fits[i][j] and best[i][j] == 1 + best[i + 1][j + 1]:
            on[j] = i
            i += 1
            j += 1
        elif best[i][j + 1] >= best[i + 1][j]:
            j += 1  # a timed line this sheet line isn't sung on
        else:
            i += 1
    matched = best[0][0]
    if matched < MIN_LINES or matched < MIN_SHARE * sum(1 for key in keys if key):
        return None
    return [[ms, line] for (ms, _), line in zip(sung, on)]
