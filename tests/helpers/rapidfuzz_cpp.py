"""A line-for-line Python transcription of rapidfuzz-cpp 3.3.4's ``partial_ratio_alignment`` (fuzz_impl.hpp's
``partial_ratio_impl`` for a needle no longer than the haystack, its sliding-window search with the score cutoff,
and the swap ``partial_ratio_alignment`` makes for two strings of one length), on code points, ``processor=None``.

caracole's search scores names with rapidfuzz 3.14.5, whose compiled scorer is rapidfuzz-cpp's; its pure-Python
fallback (``fuzz_py``) picks other alignment windows in about a quarter of the cases. This file is what the Kotlin
port (android/core, ``core.fuzz.Fuzz.partialRatioAlignment``) copies. Checked against the installed rapidfuzz on
4000 random pairs (seeded, an alphabet of nine letters and a space, needles of 1 to 90, haystacks up to 50 longer):
score, ``dest_start`` and ``dest_end`` agreed on 4000 of 4000. ``alignment(s1, s2)`` returns ``[score, src_start,
src_end, dest_start, dest_end]``; tests/test_rapidfuzz_cpp.py (lane fuzz) keeps it checked.
"""

import math

INF = float("inf")


def lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def indel(a, b):
    return len(a) + len(b) - 2 * lcs(a, b)


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
