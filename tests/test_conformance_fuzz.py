"""The fuzz corpus: rapidfuzz 3.14.5's scores (its compiled core, rapidfuzz-cpp 3.3.4, ``processor=None``), which
android/core's ``core.fuzz.Fuzz`` gives exactly (FuzzTest.kt compares every double with ``==``).

- vectors/fuzz/ratio.jsonl: ``rapidfuzz.fuzz.ratio(a, b)``;
- vectors/fuzz/token_sort.jsonl: ``rapidfuzz.fuzz.token_sort_ratio(a, b)``;
- vectors/fuzz/partial_alignment.jsonl: ``rapidfuzz.fuzz.partial_ratio_alignment(a, b)``, its ``out`` an object of
  ``score``, ``src_start``, ``src_end``, ``dest_start`` and ``dest_end``;
- vectors/fuzz/extract.jsonl: ``rapidfuzz.process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=c,
  limit=n)``, its ``kw`` the cutoff and the limit, its ``out`` a ``[choice, score, index]`` a result;
- vectors/fuzz/osa.jsonl: ``rapidfuzz.distance.OSA.distance(a, b)``, and with a ``score_cutoff`` in its ``kw`` (a
  distance past it is the cutoff plus one), which match.py's ``_typo_artists`` asks through process.extract;
- vectors/fuzz/osa_extract.jsonl: ``rapidfuzz.process.extract(query, choices, scorer=OSA.distance, score_cutoff=d,
  limit=None)``, a ``[choice, distance, index]`` a result, the nearest first, then by index;
- vectors/fuzz/token_set.jsonl: ``rapidfuzz.fuzz.token_set_ratio(a, b)``, which music.py's ``Names.artist_score``
  (the inbox's names) uses.

The last three are lane matcher's (core.fuzz's ``osaDistance``, ``extractDistance`` and ``tokenSetRatio``, which
MatchReplay checks).

Each record's ``case`` says where its strings come from: ``short/<alphabet>`` and ``long/<alphabet>``, 3,000 seeded
random pairs each (helpers/rapidfuzz_cpp.py ``random_pairs``: Latin, accented, CJK, supplementary characters, spaces
of every kind, NBSP in strings CPython stores in one byte a character and in wider ones); ``search``, calls caracole's
search tests made (search.py and lacuerda_index.py, recorded once and sampled); ``edge``, empty strings, block
boundaries and the like; for extract, ``ties``, choices repeated and spelled close, at cutoffs 80 and 90, and
``many``, more choices passing the cutoff than a limit of 20 or 3 keeps, a tie straddling the cut. OSA's add
``swapped``, pairs a few adjacent letters swapped apart (the transposition OSA counts as one edit, never across
another edit), and ``typo``, the misspelt artist names of tests/test_match.py against neighbours an edit or two away;
token_set's ``words``, sentences of a few words drawn from one small vocabulary, shared, repeated and reordered, their
spaces of every kind, and ``names``, artists as music.py writes them.
"""

import random

from rapidfuzz import fuzz, process
from rapidfuzz.distance import OSA

from helpers.corpus import VECTORS, check, jsonl
from helpers.rapidfuzz_cpp import ALPHABETS, changed, random_pairs

MADE_BY = "tests/test_conformance_fuzz.py"
SEED = 20261103

SEARCH_ALIGNMENTS = (
    ('banma', 'song dongye ban ma ban ma'), ('artista numero 77', 'artista numero 15778'),
    ('artista numero 77', 'artista numero 17726'), ('artista numero 77', 'artista numero 19877'),
    ('artista numero 77', 'artista numero 20277'), ('artista numero 77', 'artista numero 22770'),
    ('artista numero 77', 'artista numero 277 cancion 27720 del amor'),
    ('artista numero 77', 'artista numero 277 cancion 27731 del amor'),
    ('artista numero 77', 'artista numero 367 cancion 36778 del amor'),
    ('artista numero 77', 'artista numero 403 cancion 40377 del amor'), ('artista numero 77', 'artista numero 6477'),
    ('artista numero 77', 'artista numero 77 cancion 7711 del amor'),
    ('artista numero 77', 'artista numero 77 cancion 7725 del amor'),
    ('artista numero 77', 'artista numero 77 cancion 7731 del amor'), ('artista numero 77', 'artista numero 770'),
    ('artista numero 77', 'artista numero 776'), ('artistanumero77', 'artistanumero10377'),
    ('artistanumero77', 'artistanumero117cancion11773delamor'),
    ('artistanumero77', 'artistanumero137cancion13775delamor'),
    ('artistanumero77', 'artistanumero217cancion21773delamor'),
    ('artistanumero77', 'artistanumero271cancion27177delamor'),
    ('artistanumero77', 'artistanumero367cancion36777delamor'),
    ('artistanumero77', 'artistanumero387cancion38778delamor'),
    ('artistanumero77', 'artistanumero42cancion4277delamor'),
    ('artistanumero77', 'artistanumero471cancion47177delamor'),
    ('artistanumero77', 'artistanumero477cancion47719delamor'), ('artistanumero77', 'artistanumero6778'),
    ('artistanumero77', 'artistanumero7736'), ('artistanumero77', 'artistanumero83cancion8377delamor'),
    ('band', 'number 284 the band a song'), ('band', 'number52thebandasong'), ('banma', '宋冬野 斑马斑马'),
    ('cancion 4242 del amor', 'artista numero 11 cancion 1160 del amor'),
    ('cancion 4242 del amor', 'artista numero 14 cancion 1461 del amor'),
    ('cancion 4242 del amor', 'artista numero 16 cancion 1612 del amor'),
    ('cancion 4242 del amor', 'artista numero 17 cancion 1793 del amor'),
    ('cancion 4242 del amor', 'artista numero 2 cancion 244 del amor'),
    ('cancion 4242 del amor', 'artista numero 7 cancion 781 del amor'),
    ('cancion 4242 del amor', 'artista numero 8 cancion 881 del amor'),
    ('cancion4242delamor', 'artistanumero12cancion1285delamor'),
    ('cancion4242delamor', 'artistanumero1cancion112delamor'),
    ('cancion4242delamor', 'artistanumero1cancion179delamor'),
    ('cancion4242delamor', 'artistanumero2cancion215delamor'),
    ('cancion4242delamor', 'artistanumero3cancion368delamor'),
    ('cancion4242delamor', 'artistanumero5cancion530delamor'),
    ('cancion4242delamor', 'artistanumero8cancion822delamor'),
    ('cancion4242delamor', 'artistanumero8cancion848delamor'),
    ('cancion4242delamor', 'artistanumero9cancion913delamor'), ('horseband', 'number115thebandasong'),
    ('horseband', 'number270thebandasong'), ('horseband', 'number67thebandasong'), ('jones', 'georgejonessong54'),
    ('love', 'clublove676song'), ('love', 'dance band 654 love sweet'), ('love', 'dreampaper25lovequeen'),
    ('love', 'kingghost329lovequeen'), ('love', 'love city 681 king'), ('love', 'loveboys279club'),
    ('love', 'loverain716queenwildbabysweet'), ('love', 'lovesun520sweettears'), ('love', 'road band 506 love'),
    ('love', 'sun love 234 queen sugar'), ('love', 'sweet paper 893 love'), ('love', 'white home 281 love'),
    ('main theme', 'christopher larkin hollow knight main menu'),
    ('musica', ' epic the musical not sorry for loving you'), ('nelson', 'ricky nelson song 63'),
    ('nelson', 'rickynelsonsong19'), ('nothing', '宋冬野 斑马斑马'), ('prince', 'princesong5'), ('soda', 'radiohead lucky'),
    ('the', 'number 154 the band a song'), ('the', 'number 278 the band a song'),
    ('伍佰', 'wu bai china blue last dance'), ('伍佰', 'wubaichinabluenothingtosay'),
    ('宋冬野 斑马', 'song dongye ban ma ban ma'), ('宋冬野', 'song dong ye ban ma ban ma'),
    ('宋冬野', 'song dongye ban ma ban ma'), ('宋冬野', 'songdongye'), ('宋冬野', 'songdongyebanmabanma'),
    ('宋冬野斑马', 'songdongyebanmabanma'), ('斑馬', 'song dong ye ban ma ban ma'), ('斑馬', 'songdongyebanmabanma'),
    ('斑马 斑马', 'anju panta banma phulyo'), ('斑马 斑马', 'band maid thrill'), ('斑马', 'bandmaidthrill'),
    ('斑马', 'frenzal rhomb suburban male'), ('斑马', 'frenzalrhombsuburbanmale'), ('斑马', 'misc ban ma'),
    ('斑马', 'misc 斑马'), ('斑马', 'miscbanma'), ('斑马', 'plain jane nothing'), ('斑马', 'plainjanenothing'),
    ('斑马', 'radioheadcreep'), ('斑马', 'song dongye ban ma ban ma'), ('斑马', 'songdongyebanmabanma'),
    ('斑马斑马', 'bandmaidthrill'), ('斑马斑马', 'radioheadcreep'), ('斑马斑马', 'songdongyebanmabanma'), ('斑马斑马', '宋冬野 斑马 斑马'),
    ('斑马斑马', '宋冬野斑马斑马'),
)
SEARCH_RATIOS = (
    ('19 dias y 500 noches', '19 dias y 500 noches'), ('artista numero 77', 'cancion 30771 del amor'),
    ('artistanumero77', 'artistanumero308cancion30877delamor'),
    ('artistanumero77', 'artistanumero428cancion42877delamor'), ('artistanumero77', 'cancion27752delamor'),
    ('artistanumero77', 'cancion27794delamor'), ('cancion 4242 del amor', 'cancion 1266 del amor'),
    ('cancion 4242 del amor', 'cancion 468 del amor'), ('cancion 4242 del amor', 'cancion 493 del amor'),
    ('cancion 4242 del amor', 'cancion 497 del amor'), ('cancion 4242 del amor', 'cancion 70 del amor'),
    ('cancion4242delamor', 'artistanumero11cancion1177delamor'),
    ('cancion4242delamor', 'artistanumero18cancion1889delamor'),
    ('cancion4242delamor', 'artistanumero3cancion304delamor'),
    ('cancion4242delamor', 'artistanumero7cancion747delamor'),
    ('cancion4242delamor', 'artistanumero8cancion859delamor'),
    ('cancion4242delamor', 'artistanumero9cancion915delamor'), ('cancion4242delamor', 'cancion1256delamor'),
    ('cancion4242delamor', 'cancion139delamor'), ('cancion4242delamor', 'cancion354delamor'),
    ('love', 'blue sugar 351'), ('love', 'fire love'), ('love', 'glassriver92'), ('love', 'goldlove367'),
    ('love', 'heart velvet 116'), ('love', 'kingkiss372'), ('love', 'love girl 935'), ('love', 'lovegold114'),
    ('love', 'night silver 216'), ('love', 'whiteriver901lovesweet'), ('nelson', 'hawknelsonsong26'),
    ('nelson', 'song 62'), ('song dongye', '宋冬野'), ('songdongye', '斑马斑马'), ('the', 'number 4 the band'),
    ('viennabillyjoel', 'newyorkstateofmind'), ('yuzokoshirofillmore', 'yuzokoshirofillmore'),
    ('伍佰', 'wubaichinabluelastdance'), ('宋冬野', 'banmabanma'), ('宋冬野斑马', 'songdongyebanmabanma'), ('斑馬', '宋冬野'),
    ('斑马 斑马', 'ban ma ban ma'), ('斑马 斑马', 'banma phulyo'), ('斑马', 'frenzal rhomb'), ('斑马', 'plainjane'),
    ('斑马斑马', 'anjupanta'), ('斑马斑马', 'bandmaid'), ('斑马斑马', 'frenzalrhomb'), ('斑马斑马', 'song dong ye'),
    ('斑马斑马', 'thrill'),
)
SEARCH_TOKEN_SORTS = (
    ('artista numero 77', 'artista numero 227 cancion 22771 del amor'),
    ('artista numero 77', 'artista numero 302 cancion 30277 del amor'),
    ('artista numero 77', 'artista numero 37 cancion 3770 del amor'),
    ('artista numero 77', 'artista numero 397 cancion 39771 del amor'),
    ('artista numero 77', 'artista numero 95 cancion 9577 del amor'), ('ban ma', '宋冬野 斑马 斑马'),
    ('band', 'number 3 the band a song'), ('banma', '宋冬野 斑马 斑马'),
    ('cancion 4242 del amor', 'artista numero 1 cancion 165 del amor'),
    ('cancion 4242 del amor', 'artista numero 2 cancion 280 del amor'),
    ('cancion 4242 del amor', 'artista numero 4 cancion 448 del amor'),
    ('cancion 4242 del amor', 'artista numero 4 cancion 449 del amor'),
    ('cancion 4242 del amor', 'artista numero 4 cancion 497 del amor'),
    ('cancion 4242 del amor', 'artista numero 6 cancion 606 del amor'),
    ('cancion 4242 del amor', 'artista numero 8 cancion 813 del amor'),
    ('cancion 4242 del amor', 'artista numero 8 cancion 866 del amor'), ('horse band', 'number 166 the band a song'),
    ('love', 'band love 911 paper city'), ('love', 'boys love 753 stone radio gold night'),
    ('love', 'club love 447 tears'), ('love', 'heart baby 203 stone love'), ('love', 'king sugar 795 love'),
    ('love', 'kiss love 541 king'), ('love', 'love iron 590 sun'), ('love', 'money white 466 love dance'),
    ('love', 'silver love 629 love money'), ('nothing', '宋冬野 斑马斑马'), ('oasis', 'oasis wonderwall'),
    ('skynyrd lynyrd', 'sam grow skynyrd'), ('the', 'number 198 the band a song'),
    ('the', 'number 68 the band a song'), ('宋冬野', 'song dong ye ban ma ban ma'), ('宋冬野', 'songdongye ban ma ban ma'),
    ('斑馬', 'radiohead creep'), ('斑马 斑马', 'frenzal rhomb suburban male'), ('斑马', 'band maid thrill'),
    ('斑马', 'misc ban ma'), ('斑马', 'plain jane nothing'), ('斑马斑马', 'plain jane nothing'), ('斑马斑马', '宋冬野 斑马 斑马'),
)
SEARCH_EXTRACTS = (
    ('adelle', ['adele']),
    ('beatels', ['beatle', 'beatles']),
    ('beatels', ['belly', 'birdo', 'black', 'beatle', 'beatles']),
    ('beyonse', ['bense', 'bonse', 'burst']),
    ('bily', ['billy']),
    ('blurr', ['beatles']),
    ('bohemian', ['beatles', 'bohemian']),
    ('bohemian', ['beatles']),
    ('bunbury', ['barrio']),
    ('califronia', ['califonia', 'california']),
    ('califronia', ['coldplay', 'califonia', 'california']),
    ('califronia', ['coldplay']),
    ('camaon', ['como', 'camaron']),
    ('camaron', ['creep', 'creeping']),
    ('como', ['como', 'creep']),
    ('como', ['como']),
    ('eminen', ['eminem', 'eminence']),
    ('eminen', ['eminem']),
    ('epic', ['epic']),
    ('estopa', ['estopa']),
    ('heavn', ['heavy', 'hotel', 'heaven']),
    ('hollow', ['hell', 'highway']),
    ('hotl', ['heavy', 'hotel', 'heaven']),
    ('knight', ['karma']),
    ('ligera', ['ligera', 'losing']),
    ('lynrd', ['las', 'law', 'let', 'last', 'lord', 'love', 'lynyrd']),
    ('lynrd', ['lynyrd']),
    ('lynyrd', ['last', 'lord', 'love', 'lynyrd']),
    ('lynyrd', ['lynyrd']),
    ('mann', ['man']),
    ('metalica', ['metalica', 'metallica']),
    ('metalica', ['metallica']),
    ('metalika', ['malika', 'mashups', 'matters', 'metallica']),
    ('metalika', ['malika', 'metallica']),
    ('metalika', ['mashups', 'metallica']),
    ('musica', ['musica']),
    ('oasys', ['oasis']),
    ('paralamas', ['paralamas']),
    ('paralamas', ['persiana', 'paralamas']),
    ('piano', ['piano']),
    ('piano', ['pilots', 'police']),
    ('piano', ['pilots']),
    ('rapsody', ['rhapsody']),
    ('resting', ['radiohead']),
    ('resting', ['religion', 'radiohead']),
    ('ritchie', ['radiohead']),
    ('ritchie', ['religion', 'radiohead']),
    ('sabina', ['soda', 'stone', 'stereo']),
    ('scientst', ['scientists']),
    ('scientst', ['stairway', 'scientist', 'shattered', 'scientists']),
    ('skynrd', ['sabina', 'skynyrd']),
    ('skynrd', ['song', 'steps', 'sweet', 'sabina', 'simple', 'skynyrd']),
    ('stairwy', ['stairway', 'shattered']),
    ('wonderwal', ['wonderwall']),
    ('yesterdy', ['yesterday']),
    ('zzzzqqq', ['zeppelin']),
)

# Where an edge lies: nothing, one character, two of one length, the 64 bits of one block of the bit-parallel LCS.
_BLOCK = "abcdefgh" * 8
EDGES = (
    ("", ""), ("", "a"), ("a", ""), ("", " "), (" ", ""), ("a", "a"), ("a", "b"), ("ab", "ba"), ("abc", "abc"),
    ("abc", "cba"), ("aaaa", "aa"), ("aa", "aaaa"), ("ab", "abab"), ("中", "中国"), ("中国", "国中"),
    ("\U0001f600", "a\U0001f600b"), ("\U0001f600\U0001f600", "\U0001f600"),
    (_BLOCK, _BLOCK), (_BLOCK, _BLOCK + "a"), (_BLOCK + "a", _BLOCK), (_BLOCK[:63], _BLOCK),
    (_BLOCK[1:], "x" + _BLOCK + "y"), (_BLOCK + _BLOCK[:1], "zz" + _BLOCK + _BLOCK + "zz"),
    (_BLOCK * 2, "q" + _BLOCK * 2 + "q"), (_BLOCK * 2 + "abc", _BLOCK[::-1] * 3),
    ("hgfedcba" * 9, _BLOCK * 2), ("x" * 65, "y" * 70 + "x"), ("a" * 130, "a" * 129 + "b" * 3),
)
# Words a space of each kind splits, or does not.
SPACED = (
    ("b\xa0a", "a b"), ("b\xa0aĀ", "a bĀ"), ("b\x85a", "a b"), ("b\x85a\U0001f600", "a\U0001f600 b"),
    ("  a  b ", "b a"), ("　a　b", "b a"), ("a​b", "b a"), ("a b c", "c b a"),
    ("a\x1cb\x1fc", "c b a"), ("a\tb\nc\rd\x0be\x0cf", "f e d c b a"), ("b a c d", "d c a b"),
    ("b a", "b a"), ("zeta alpha", "alpha zeta"), ("Zeta alpha", "alpha Zeta"), ("é e", "e é"),
    ("\U0001f600 a", "a \U0001f600"), ("￿ b", "b \U00010000"), ("", "   "), (" \xa0 ", "\xa0"),
)


def pairs():
    """Every pair the files score, each with its case, in one seeded order."""
    rng = random.Random(SEED)
    out = [(f"short/{name}", a, b) for name, a, b in random_pairs(rng, 3000)]
    out += [(f"long/{name}", a, b) for name, a, b in random_pairs(rng, 3000, long=True)]
    return out


def edges():
    return [("edge", a, b) for a, b in EDGES] + [("edge", b, a) for a, b in EDGES if a != b]


def calls(fn, name, extra):
    return [{"fn": name, "args": [a, b], "out": fn(a, b), "case": case} for case, a, b in pairs() + extra]


def aligned(a, b):
    r = fuzz.partial_ratio_alignment(a, b)
    return {"score": r.score, "src_start": r.src_start, "src_end": r.src_end, "dest_start": r.dest_start,
            "dest_end": r.dest_end}


def extract_cases():
    """``(case, query, choices)``: search's own words, then queries with choices spelled close, repeated."""
    out = [("search", q, list(choices)) for q, choices in SEARCH_EXTRACTS]
    rng = random.Random(SEED + 1)
    names = sorted(ALPHABETS)
    for _ in range(200):
        alphabet = ALPHABETS[rng.choice(names)].replace(" ", "") or "ab"
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(3, 11)))
        choices = []
        for _ in range(rng.randint(0, 14)):
            word = list(query)
            for _ in range(rng.randint(0, 3)):
                at = rng.randrange(len(word) + 1)
                if rng.random() < 0.4:
                    word.insert(at, rng.choice(alphabet))
                elif word:
                    word[min(at, len(word) - 1)] = rng.choice(alphabet)
            choices.append("".join(word))
        choices += [rng.choice(choices) for _ in range(rng.randint(0, 4))] if choices else []  # ties
        rng.shuffle(choices)
        out.append(("ties", query, choices))
    return out


def many_cases():
    """``(case, query, choices)`` with more choices passing the cutoff than the limit keeps: 25 to 60 close spellings
    of the query, a few repeated, as search's ``_close_words`` meets a whole letter of an index's words."""
    rng = random.Random(SEED + 2)
    names = sorted(ALPHABETS)
    out = []
    for _ in range(40):
        alphabet = ALPHABETS[rng.choice(names)].replace(" ", "") or "ab"
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(8, 14)))
        choices = [changed(rng, query, alphabet, rng.choice((0, 1, 1, 1, 2, 2, 3, 5)))
                   for _ in range(rng.randint(25, 60))]
        choices += [rng.choice(choices) for _ in range(rng.randint(2, 8))]  # ties, some across the cut
        rng.shuffle(choices)
        out.append(("many", query, choices))
    return out


def passing(record):
    """What ``record``'s extract keeps with no limit."""
    query, choices = record["args"]
    return process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=record["kw"]["score_cutoff"], limit=None)


def extracts():
    records = []
    runs = ((80, 20), (90, 20), (80, 1), (90, None))
    for case, query, choices in extract_cases() + many_cases():
        for cutoff, limit in runs + (((80, 3), (90, 3)) if case == "many" else ()):
            got = process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=cutoff, limit=limit)
            records.append({"fn": "rapidfuzz.process.extract", "args": [query, choices],
                            "kw": {"limit": limit, "score_cutoff": cutoff, "scorer": "rapidfuzz.fuzz.ratio"},
                            "out": [[choice, score, index] for choice, score, index in got], "case": case})
    return records


def write(name, records):
    check(VECTORS / "fuzz" / f"{name}.jsonl", jsonl(records, corpus=f"fuzz/{name}", made_by=MADE_BY))


def test_ratio_jsonl():
    extra = [("search", a, b) for a, b in SEARCH_RATIOS] + edges()
    write("ratio", calls(fuzz.ratio, "rapidfuzz.fuzz.ratio", extra))


def test_token_sort_jsonl():
    extra = [("search", a, b) for a, b in SEARCH_TOKEN_SORTS] + edges() + [("edge", a, b) for a, b in SPACED]
    write("token_sort", calls(fuzz.token_sort_ratio, "rapidfuzz.fuzz.token_sort_ratio", extra))


def test_partial_alignment_jsonl():
    extra = [("search", a, b) for a, b in SEARCH_ALIGNMENTS] + edges()
    write("partial_alignment", calls(aligned, "rapidfuzz.fuzz.partial_ratio_alignment", extra))


def test_extract_jsonl():
    write("extract", extracts())


def test_the_corpus_holds_what_the_kotlin_port_must_meet():
    cases = pairs()
    assert len([c for c in cases if c[0].startswith("short/")]) == 3000
    assert len([c for c in cases if c[0].startswith("long/")]) == 3000
    assert {c[0].split("/")[1] for c in cases} == set(ALPHABETS)
    assert ("banma", "song dongye ban ma ban ma") in SEARCH_ALIGNMENTS
    assert aligned("banma", "song dongye ban ma ban ma")["dest_start"] == 19
    # Ties and both cutoffs reach the results.
    records = extracts()
    assert any(len({r[1] for r in rec["out"]}) < len(rec["out"]) for rec in records)
    assert {rec["kw"]["score_cutoff"] for rec in records if rec["out"]} == {80, 90}
    # A limit above 1 cuts the results short (search's CLOSE_WORDS of 20, and 3), a tie straddling the cut too.
    for limit in (3, 20):
        cut = [rec for rec in records if rec["kw"]["limit"] == limit and len(rec["out"]) == limit
               and len(passing(rec)) > limit]
        assert len(cut) >= 20, limit
        assert any(passing(rec)[limit][1] == rec["out"][-1][1] for rec in cut), limit
    # Both kinds of string storage meet NBSP: the one-byte (no space) and the wider (a space).
    assert fuzz.token_sort_ratio("b\xa0a", "a b") != fuzz.token_sort_ratio("b\xa0aĀ", "a bĀ")


# --- OSA and token_set_ratio (lane matcher) ---------------------------------------------------------------------

OSA_PAIRS = 800  # short seeded pairs scored (and a fifth as many long ones), of the 3000 each above
# match.py's typo route: names an edit or two from a neighbour (tests/test_match.py's), and the cases between.
TYPOS = (
    ("coldplya", "coldplay"), ("oaiss", "oasis"), ("metalicca", "metallica"), ("tolo", "tool"), ("tolo", "colo"),
    ("tolo", "polo"), ("u3", "u2"), ("muse", "fuse"), ("ca", "abc"), ("abc", "ca"), ("abcd", "badc"),
    ("abcdef", "badcfe"), ("ab", "ba"), ("abc", "acb"), ("abcdefgh", "abdcefhg"), ("redhotchilipeppers",
    "redhotchillipeppers"), ("enanitosverde", "enanitosverdes"), ("songdongye", "sungdongye"), ("宋冬野", "冬宋野"),
)
TYPO_QUERIES = ("coldplya", "oaiss", "metalicca", "tolo", "beatels", "lynrd", "skynrd", "metalika", "radiohaed",
                "abba", "a")
TYPO_CHOICES = ("coldplay", "oasis", "metallica", "tool", "colo", "lolo", "molo", "polo", "solo", "beatles",
                "beatle", "lynyrd", "skynyrd", "metalica", "radiohead", "abba", "baba", "abab", "a", "", "toll", "tolo")


def swapped(rng, s, swaps):
    chars = list(s)
    for _ in range(swaps):
        if len(chars) < 2:
            break
        at = rng.randrange(len(chars) - 1)
        chars[at], chars[at + 1] = chars[at + 1], chars[at]
    return "".join(chars)


def osa_pairs():
    """``(case, a, b)``: seeded pairs short and long (OSA's bit-parallel block from 64 characters), letters swapped,
    the typo route's names, the edges."""
    rng = random.Random(SEED + 3)
    out = [(f"short/{name}", a, b) for name, a, b in random_pairs(rng, OSA_PAIRS)]
    out += [(f"long/{name}", a, b) for name, a, b in random_pairs(rng, OSA_PAIRS // 5, long=True)]
    names = sorted(ALPHABETS)
    for _ in range(300):
        alphabet = ALPHABETS[rng.choice(names)]
        a = "".join(rng.choice(alphabet) for _ in range(rng.randint(2, 70)))
        b = swapped(rng, a, rng.randint(1, 4))
        if rng.random() < 0.4:
            b = changed(rng, b, alphabet, rng.randint(1, 2))
        out.append(("swapped", a, b))
    out += [("typo", a, b) for a, b in TYPOS] + [("typo", b, a) for a, b in TYPOS]
    return out + edges()


def osa_records():
    records = []
    for case, a, b in osa_pairs():
        records.append({"fn": "rapidfuzz.distance.OSA.distance", "args": [a, b], "out": OSA.distance(a, b),
                        "case": case})
        if case in ("typo", "edge") or (case == "swapped" and len(a) < 20) or (case.startswith("short/")
                                                                              and len(records) % 4 == 1):
            for cutoff in (1, 2):
                records.append({"fn": "rapidfuzz.distance.OSA.distance", "args": [a, b],
                                "kw": {"score_cutoff": cutoff}, "out": OSA.distance(a, b, score_cutoff=cutoff),
                                "case": case})
    return records


def osa_extract_cases():
    """``(case, query, choices)``: the typo route's names, then queries among choices an edit or few away."""
    out = [("typo", q, list(TYPO_CHOICES)) for q in TYPO_QUERIES]
    rng = random.Random(SEED + 4)
    names = sorted(ALPHABETS)
    for _ in range(120):
        alphabet = ALPHABETS[rng.choice(names)].replace(" ", "") or "ab"
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(3, 12)))
        choices = []
        for _ in range(rng.randint(0, 16)):
            pick = rng.random()
            if pick < 0.3:
                choices.append(swapped(rng, query, rng.randint(1, 2)))
            elif pick < 0.8:
                choices.append(changed(rng, query, alphabet, rng.randint(0, 3)))
            else:
                choices.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12))))
        choices += [rng.choice(choices) for _ in range(rng.randint(0, 3))] if choices else []  # ties
        rng.shuffle(choices)
        out.append(("near", query, choices))
    return out


def osa_extracts():
    records = []
    for case, query, choices in osa_extract_cases():
        for cutoff in (1, 2):
            got = process.extract(query, choices, scorer=OSA.distance, score_cutoff=cutoff, limit=None)
            records.append({"fn": "rapidfuzz.process.extract", "args": [query, choices],
                            "kw": {"limit": None, "score_cutoff": cutoff, "scorer": "rapidfuzz.distance.OSA.distance"},
                            "out": [[choice, distance, index] for choice, distance, index in got], "case": case})
    return records


TOKEN_SET_PAIRS = 1200  # seeded short pairs scored, of the 3000 above
NAMES = (
    ("the beatles", "beatles the"), ("beatles", "the beatles"), ("simon garfunkel", "simon and garfunkel"),
    ("soda stereo", "soda"), ("song dongye", "song dong ye"), ("crosby stills nash young", "crosby stills nash"),
    ("bob marley the wailers", "bob marley and the wailers"), ("a b c", "a b"), ("fuzzy wuzzy was a bear",
    "wuzzy fuzzy was a bear"), ("fuzzy was a bear", "fuzzy fuzzy was a bear"), ("x y", "z w"), ("a a a", "a"),
    ("中国 人", "人 中国"), ("songdongye", "song dongye"),
)


def token_set_pairs():
    """``(case, a, b)``: sentences of shared words, seeded short pairs, artists' names, the spaces and edges."""
    rng = random.Random(SEED + 5)
    out = []
    names = sorted(ALPHABETS)
    for _ in range(1000):
        name = rng.choice(names)
        alphabet = ALPHABETS[name]
        letters = "".join(c for c in alphabet if not c.isspace()) or "ab"
        spaces = "".join(c for c in alphabet if c.isspace()) or " "
        vocabulary = ["".join(rng.choice(letters) for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(2, 6))]

        def sentence():
            words = [rng.choice(vocabulary) for _ in range(rng.randint(0, 5))]
            text = ""
            for w in words:
                text += "".join(rng.choice(spaces) for _ in range(rng.randint(1, 2))) + w
            return text if rng.random() < 0.5 else text.lstrip()

        out.append((f"words/{name}", sentence(), sentence()))
    out += [(f"short/{name}", a, b) for name, a, b in random_pairs(rng, TOKEN_SET_PAIRS)]
    out += [("names", a, b) for a, b in NAMES] + [("names", b, a) for a, b in NAMES]
    out += [("edge", a, b) for a, b in SPACED]
    return out + edges()


def test_osa_jsonl():
    write("osa", osa_records())


def test_osa_extract_jsonl():
    write("osa_extract", osa_extracts())


def test_token_set_jsonl():
    write("token_set", [{"fn": "rapidfuzz.fuzz.token_set_ratio", "args": [a, b], "out": fuzz.token_set_ratio(a, b),
                          "case": case} for case, a, b in token_set_pairs()])


def test_the_matchers_vectors_reach_every_rule_of_osa_and_token_set():
    records = osa_records()
    # A transposition is one edit; a swap and an edit beside it, OSA's restriction, more than Damerau's.
    assert OSA.distance("ab", "ba") == 1 and OSA.distance("ca", "abc") == 3
    assert any(r["case"] == "swapped" and r["out"] == 1 for r in records)
    assert any(len(r["args"][0]) >= 64 and len(r["args"][1]) >= 64 for r in records)  # the block variant
    cut = [r for r in records if "kw" in r]
    assert any(r["out"] == r["kw"]["score_cutoff"] + 1 for r in cut)  # past the cutoff: the cutoff plus one
    extracts = osa_extracts()
    assert any(len({row[1] for row in r["out"]}) < len(r["out"]) for r in extracts)  # ties by index
    assert any(r["out"] for r in extracts if r["kw"]["score_cutoff"] == 2)
    pairs = token_set_pairs()
    scores = {fuzz.token_set_ratio(a, b) for _, a, b in pairs}
    assert {0.0, 100.0} <= scores and len(scores) > 100
    # One sentence's words within the other's is 100; an empty one is 0.
    assert fuzz.token_set_ratio("a b c", "a b") == 100 and fuzz.token_set_ratio("", "a") == 0
