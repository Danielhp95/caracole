"""A line-for-line Python transcription of rapidfuzz-cpp 3.3.4, the C++ core of rapidfuzz 3.14.5, for the four scorers
caracole's search uses, on code points, ``processor=None``: what the Kotlin port (android/core,
``core.fuzz.Fuzz``) copies.

- ``alignment(s1, s2)``: ``fuzz.partial_ratio_alignment``, fuzz_impl.hpp's ``partial_ratio_alignment`` and its
  ``partial_ratio_impl`` for a needle no longer than the haystack: the full windows searched in bisection order with
  the score cutoff (a strict ``<``, pruning a window no cell of which can beat it), then the prefixes ``s2[:i]``
  (``i < len1``) whose last character is in ``s1``, then the suffixes from ``len2 - len1``; the first strictly better
  wins, 100 returns at once; two strings of one length are tried both ways. It returns ``[score, src_start,
  src_end, dest_start, dest_end]``.
- ``ratio(s1, s2)``: ``fuzz.ratio``, ``(1.0 - indel / (len1 + len2)) * 100``, and 100 for two empty strings.
- ``token_sort_ratio(s1, s2)``: ``fuzz.token_sort_ratio``, ``ratio`` of each string's words sorted by code point and
  joined by one space. A word ends at common_impl.hpp's ``is_space``, whose set depends on how CPython stores the
  string: for one of one byte a character (every code point at most U+00FF) it is ASCII's alone (``\\t``–``\\r``,
  ``\\x1c``–``\\x1f``, the space), so NBSP and U+0085 split only a string that holds a character above U+00FF.
- ``extract(query, choices, score_cutoff, limit)``: ``process.extract`` with ``scorer=fuzz.ratio``: each choice whose
  normalized similarity reaches ``score_cutoff / 100`` (and whose score then reaches ``score_cutoff``), by score,
  highest first, then by index; ``limit`` of them, all with ``None``.

caracole's search scores names with these (search.py ``_Query.readings``, lacuerda_index.py); rapidfuzz's
pure-Python fallback (``fuzz_py``) picks other alignment windows in about a quarter of the cases, so it is never what
is ported. ``alignment`` was first checked against the installed rapidfuzz on 4000 random pairs (seeded, an alphabet
of nine letters and a space, needles of 1 to 90, haystacks up to 50 longer): score, ``dest_start`` and ``dest_end``
agreed on 4000 of 4000. tests/test_rapidfuzz_cpp.py keeps every function here checked against rapidfuzz, on seeded
random pairs of Latin, accented, CJK and supplementary characters and spaces of every kind.

The LCS behind the Indel distance is ``lcs``, a dynamic programme, as the definition; ``indel`` uses ``lcs_bits``,
Hyyrö's bit-parallel LCS (rapidfuzz's own ``lcs_unroll``/``lcs_blockwise``, here on one Python integer of any width),
which the test holds equal to it.

``random_pairs(rng, n, long=)`` makes the seeded pairs both tests share (and tests/test_conformance_fuzz.py writes
for Kotlin): ``n`` pairs over ``ALPHABETS``, short (0 to 12 characters each) or long (a needle of 20 to 80 and a
haystack up to 40 longer, or shorter, or of its length, often holding the needle a little changed), and
``changed(rng, s, alphabet, edits)`` ``s`` after that many random insertions, deletions and substitutions.
"""

import math

INF = float("inf")

# common_impl.hpp's is_space: every character type wider than one byte, and the one-byte set (ASCII's alone).
SPACES = frozenset([0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0, 0x1680,
                    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000])
SPACES_ONE_BYTE = frozenset([0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F, 0x20])


def lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def lcs_bits(a, b):
    """``lcs(a, b)``, bit-parallel: bit i of ``s`` is 0 once a[i] is part of the LCS so far."""
    if not a or not b:
        return 0
    pm = {}
    for i, c in enumerate(a):
        pm[c] = pm.get(c, 0) | (1 << i)
    mask = (1 << len(a)) - 1
    s = mask
    for c in b:
        u = s & pm.get(c, 0)
        s = ((s + u) | (s - u)) & mask
    return len(a) - s.bit_count()


def indel(a, b):
    return len(a) + len(b) - 2 * lcs_bits(a, b)


def norm_sim(a, b, cutoff):  # cutoff in [0,1]
    ls = len(a) + len(b)
    nd = indel(a, b) / ls if ls else 0.0
    ns = 1.0 - nd
    return ns if ns >= cutoff else 0.0


def impl(s1, s2, score_cutoff):
    len1, len2 = len(s1), len(s2)
    cs = set(s1)
    res = [0.0, 0, len1, 0, len1]  # score, src_start, src_end, dest_start, dest_end
    if len2 > len1:
        maximum = len1 * 2
        ncs = min(1.0, 1.0 - score_cutoff / 100 + 0.00001)
        cutoff_dist = math.ceil(maximum * ncs)
        best = INF
        scores = [None] * (len2 - len1)
        windows = [(0, len2 - len1 - 1)]
        while windows:
            new = []
            for f, s in windows:
                for w in (f, s):
                    if scores[w] is None:
                        scores[w] = indel(s1, s2[w:w + len1])
                        if scores[w] < cutoff_dist:
                            cutoff_dist = best = scores[w]
                            res[3], res[4] = w, w + len1
                            if best == 0:
                                res[0] = 100
                                return res
                cell = s - f
                if cell == 1:
                    continue
                known = abs(scores[f] - scores[s])
                improve = (cell - known // 2) // 2 * 2
                if min(scores[f], scores[s]) - improve < cutoff_dist:
                    c = cell // 2
                    new += [(f, f + c), (f + c, s)]
            windows = new
        score = (1.0 - best / maximum) * 100 if best != INF else 0.0
        if score >= score_cutoff:
            score_cutoff = res[0] = score
    for i in range(1, len1):
        sub = s2[:i]
        if sub[-1] not in cs:
            continue
        r = norm_sim(s1, sub, score_cutoff / 100) * 100
        if r > res[0]:
            score_cutoff = res[0] = r
            res[3], res[4] = 0, i
            if res[0] == 100.0:
                return res
    for i in range(len2 - len1, len2):
        sub = s2[i:]
        if sub[0] not in cs:
            continue
        r = norm_sim(s1, sub, score_cutoff / 100) * 100
        if r > res[0]:
            score_cutoff = res[0] = r
            res[3], res[4] = i, len2
            if res[0] == 100.0:
                return res
    return res


def alignment(s1, s2):
    if len(s1) > len(s2):
        r = alignment(s2, s1)
        return [r[0], r[3], r[4], r[1], r[2]]
    if not s1 or not s2:
        return [float(len(s1) == len(s2)) * 100.0, 0, len(s1), 0, len(s1)]
    r = impl(s1, s2, 0.0)
    if r[0] != 100 and len(s1) == len(s2):
        r2 = impl(s2, s1, max(0.0, r[0]))
        if r2[0] > r[0]:
            return [r2[0], r2[3], r2[4], r2[1], r2[2]]
    return r


def ratio(s1, s2):
    return norm_sim(s1, s2, 0.0) * 100


def sorted_split(s):
    """common_impl.hpp's ``sorted_split(s).join()``: the words (no empty one) sorted by code point, one space
    between."""
    spaces = SPACES if any(ord(c) > 0xFF for c in s) else SPACES_ONE_BYTE
    words, word = [], []
    for c in s:
        if ord(c) in spaces:
            if word:
                words.append("".join(word))
            word = []
        else:
            word.append(c)
    if word:
        words.append("".join(word))
    return " ".join(sorted(words))


def token_sort_ratio(s1, s2):
    return ratio(sorted_split(s1), sorted_split(s2))


def extract(query, choices, score_cutoff, limit):
    found = []
    for index, choice in enumerate(choices):
        ns = norm_sim(query, choice, score_cutoff / 100)
        if ns >= score_cutoff / 100 and ns * 100 >= score_cutoff:
            found.append((choice, ns * 100, index))
    found.sort(key=lambda r: (-r[1], r[2]))
    return found if limit is None else found[:limit]


# --- seeded random pairs ---------------------------------------------------------------------------------------

_EVERY_SPACE = "".join(chr(c) for c in sorted(SPACES))
# Characters that look like spaces and are none of is_space's: zero width, Mongolian, BOM, word joiner.
_NOT_SPACES = "᠎​⁠﻿­"
ALPHABETS = {
    "latin": "abcdefgh ",
    "accented": "aeéèñnüuçAÉ ",
    "cjk": "中国人大小的一是ab ",
    "supplementary": "\U0001d11e\U0001f600\U00020000\U00020001\U0001f3b8ab ",
    "spaces": "ab" + _EVERY_SPACE + _NOT_SPACES,
    "latin1 spaces": "abc \t\xa0\x85\x1c\n",  # one byte a character: NBSP and U+0085 are no spaces here
    "wide spaces": "abc \t\xa0\x85\x1c\nĀ",  # U+0100 makes the string two bytes a character: now they are
    "astral spaces": "abc \xa0\x85\U0001f600",  # four bytes a character
    "mixed": "abcxyz éñ中国\U0001f600 \xa0　",
}


def _word(rng, alphabet, k):
    return "".join(rng.choice(alphabet) for _ in range(k))


def changed(rng, s, alphabet, edits):
    chars = list(s)
    for _ in range(edits):
        op = rng.randrange(3)
        at = rng.randrange(len(chars) + 1)
        if op == 0 or not chars:
            chars.insert(at, rng.choice(alphabet))
        elif op == 1:
            del chars[min(at, len(chars) - 1)]
        else:
            chars[min(at, len(chars) - 1)] = rng.choice(alphabet)
    return "".join(chars)


def random_pairs(rng, n, *, long=False):
    """``n`` pairs ``(alphabet, a, b)``: short ones of 0 to 12 characters each, or long ones whose haystack often
    holds the needle changed by a few edits."""
    names = sorted(ALPHABETS)
    out = []
    for _ in range(n):
        name = rng.choice(names)
        alphabet = ALPHABETS[name]
        if not long:
            a = _word(rng, alphabet, rng.randint(0, 12))
            b = _word(rng, alphabet, rng.randint(0, 12)) if rng.random() < 0.7 else changed(rng, a, alphabet, 2)
        else:
            a = _word(rng, alphabet, rng.randint(20, 80))
            shape = rng.random()
            if shape < 0.2:  # one length
                b = _word(rng, alphabet, len(a)) if rng.random() < 0.5 else changed(rng, a, alphabet, 3)
                b = (b + _word(rng, alphabet, len(a)))[:len(a)]
            elif shape < 0.35:  # the haystack the shorter
                b = changed(rng, a[rng.randrange(len(a) // 2):], alphabet, rng.randint(0, 6))
            elif shape < 0.7:  # the needle within the haystack, changed
                inner = changed(rng, a, alphabet, rng.randint(0, 8))
                b = _word(rng, alphabet, rng.randint(0, 20)) + inner + _word(rng, alphabet, rng.randint(0, 15))
            else:
                b = _word(rng, alphabet, len(a) + rng.randint(1, 40))
        out.append((name, a, b))
    return out


if __name__ == "__main__":
    import random

    from rapidfuzz import fuzz

    random.seed(11)
    alpha = "abcde fgh"
    diff = n = 0
    for _ in range(4000):
        k = random.randint(1, 90)
        a = "".join(random.choice(alpha) for _ in range(k))
        b = "".join(random.choice(alpha) for _ in range(k + random.randint(0, 50)))
        c = fuzz.partial_ratio_alignment(a, b)
        p = alignment(a, b)
        n += 1
        if (c.score, c.dest_start, c.dest_end) != (p[0], p[3], p[4]):
            diff += 1
    print("the transcription and the installed rapidfuzz differ on", diff, "of", n)
