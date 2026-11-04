"""viewer/pinyin.py and viewer/hanzi.py for the phone, and OpenCC as hanzi.py converts with it: the dictionaries and
configs :viewer's viewer.chinese reads, and what Python answers.

hanzi.py converts with OpenCC's ``t2s``, ``tw2s`` and ``s2tw``, ``include_tofu_risk_dictionaries=False``
(``hanzi._converter``). The phone runs OpenCC's algorithm (src/: Config.cpp, ConfigBasedConverter.hpp,
SingleStageConverter.cpp, MaxMatchSegmentation.cpp, ConversionChain.cpp, Conversion.cpp, PrefixMatch.cpp,
UTF8Util.hpp) over the very dictionaries the package ships, as text:

1. A config's ``normalization`` (``CJK_Compatibility_Ideographs``) converts the whole text first, then its main
   stage: its ``segmentation`` (``mmseg``, none in ``t2s``) and its ``conversion_chain``.
2. A dictionary is an ``ocd2`` file, or a ``group`` of them by its ``match_policy`` (``short_circuit``, the default,
   or ``union``). One marked ``may_output_tofu`` is left out (``TSCharactersExt``), and a group left with none is
   none; a segmentation's dictionaries keep theirs (Config.cpp reads them so), and hold none.
3. A dictionary's match at a place in a text is its longest key that begins there, with that key's first value: an
   ``ocd2`` file's own (its trie's longest common prefix); a ``short_circuit`` group's, the first of its
   dictionaries that has any (a shorter match of an earlier one wins over a later one's longer); a ``union``
   group's, the longest of any of its dictionaries, the first of them on a tie (PrefixMatch's merged trie keeps the
   first key added).
4. mmseg cuts the text: where its dictionary matches, the key is a segment of its own; the characters between such
   keys are one segment together (an ideographic description sequence, IDS, among them whole).
5. Each segment goes through the chain, each conversion in turn over the whole of what the one before wrote: from
   the start of the text, where its dictionary matches, the key's value is written and the key passed; else a whole
   IDS that begins there is written as it is (an operator U+2FF0–2FFF and as many operands as it takes, each a
   character or an IDS, 16 deep and 64 code points at most), else one character.
6. In a config with a segmentation, a segment holding U+0000 ends there (OpenCC hands each segment on as a C
   string): 头发\\0头发 is 头发 in ``tw2s``; with none (``t2s``, the normalization) the text is whole.

The data, ``tests/conformance/data/caracole/hanzi/`` (caracole/hanzi/ on the phone's classpath, a resource of
``:core``):

- ``<Name>.txt``: each dictionary the three configs use (``dictionaries()``, ``TSCharactersExt`` left out), as the
  package's own ``clib/bin/opencc_dict -f ocd2 -t text`` writes it from ``clib/share/opencc/<Name>.ocd2``: UTF-8,
  ``<key>\\t<value> <value> …`` a line, the first value the one OpenCC writes.
- ``opencc.json``: ``{"opencc": opencc.__version__, "package": its distribution's version, "configs": {"t2s": …,
  "tw2s": …, "s2tw": …}}``, each config the package's ``clib/share/opencc/<config>.json`` as it is, an indent of
  one (``viewer_corpus.data_json``). A dictionary's ``file`` is ``<Name>.ocd2``, read from ``<Name>.txt``.

``tests/conformance/data/caracole/viewer/pinyin.json`` (``ViewerData.table("pinyin")``): viewer/pinyin.py's
``_KANA`` (its pattern), ``_ZHU_WORDS`` (sorted) and ``_LONGEST``.

The vectors (``helpers.corpus.jsonl``), in ``vectors/viewer/``:

- ``opencc.jsonl``: ``convert(config, text)``, OpenCC's answer, for each config, over every key of every
  dictionary it uses, ``KEYS_A_TEXT`` a text joined by ``SEPARATORS`` by turns (none of whose characters any key or
  value holds); and ``converted(text)``, each config's answer (``{"t2s": …, "tw2s": …, "s2tw": …}``), over ``MIXES``
  seeded mixes (keys, their values, their prefixes, characters of either script, compatibility ideographs, IDS whole
  and cut short, Latin, digits, kana, Hangul, emoji, punctuation, spaces, U+0000) and ``EDGES``.
- ``hanzi.jsonl``: ``page_converted(text)``, ``hanzi._converted`` in each config (a text as long as it was, its
  Chinese alone converted), over ``EDGES`` and the first ``PAGE_MIXES`` mixes; and ``sheet_hanzi(texts, names)``:
  ``{"scripts": hanzi.scripts(texts), "traditional": hanzi.written_in_traditional(texts), "names":
  hanzi.names(names)}``, each table of ``scripts`` and ``names`` (``simplified``, ``traditional``, in that order) as
  ``[[text, converted], …]`` in its order, for every sheet of ``viewer_corpus.sheets()`` whose page is Chinese
  (``texts`` its ``page._written_texts``, ``names`` its title, artist and page title as ``page.build_viewer`` gives
  ``names_table``), a few that aren't, ``SHEETS`` seeded sheets in Simplified, Traditional or both, each string
  literal of ``LITERALS_FROM`` that holds a Chinese character alone and all of them together, and ``EDGE_SHEETS``.
- ``pinyin_page.jsonl``: ``page_pinyin(lines)``: ``{"is_chinese": pinyin.is_chinese(lines), "readings":
  pinyin.readings(lines)}``, for every sheet of the corpus but the Latin ones past the first ``LATIN_SHEETS``
  (``lines`` its ``page._drawn_lines``), the seeded sheets (with 著 in words of each kind: a word Simplified writes
  with 著, pypinyin's phrase or ``_ZHU_WORDS``, and 着's), the literals alone and together, and ``EDGE_SHEETS``.

Each vector's test also reads it back from the data alone, as the phone does (``_OpenCC``): a dump, a config or an
algorithm the phone would read otherwise fails here first. OpenCC and pypinyin are imported where they are used.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_chinese.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import functools
import importlib.metadata
import json
import random
import subprocess
import tempfile
from pathlib import Path

import pytest

from caracole.normalize import has_han
from caracole.viewer import hanzi, page, pinyin
from caracole.viewer.sheet import parse_sheet
from helpers import viewer_corpus
from helpers.corpus import DATA, check, jsonl

MADE_BY = "tests/test_conformance_viewer_chinese.py"
HELPER = "test_conformance_viewer_chinese."
HANZI_DATA = DATA / "hanzi"
TESTS = Path(__file__).resolve().parent
CONFIGS = ("t2s", "tw2s", "s2tw")
LITERALS_FROM = ("test_viewer_hanzi.py", "test_viewer_pinyin.py")

SEED = 20261105
KEYS_A_TEXT = 200
MIXES = 800
PAGE_MIXES = 300
SHEETS = 120
LATIN_SHEETS = 12
SEPARATORS = (" ", "\n", "，", "。", "a", "1", " / ", "\t")

# IDS operators (U+2FF0–2FFF) and how many operands each takes, as UTF8Util.hpp's IdeographicDescriptionOperatorArity.
IDS_ARITY = {**{cp: 2 for cp in range(0x2FF0, 0x2FFE)}, 0x2FF2: 3, 0x2FF3: 3, 0x2FFE: 1, 0x2FFF: 1}


def _nested(depth: int) -> str:
    """An IDS ``depth`` operators deep: ⿰ ⿰ … 木, then the ones they leave open."""
    return "⿰" * depth + "木" * (depth + 1)


def _long(code_points: int) -> str:
    """An IDS of ``code_points`` code points (an odd number): ⿰⿰…, flat on the left."""
    operators = (code_points - 1) // 2
    return "⿰" * operators + "木" * (operators + 1)


# Texts at the edges: U+0000 in each place, IDS whole, cut short, too deep, too long and of each arity, a phrase on
# either side of one, compatibility ideographs, supplementary characters, and the words hanzi.py's docstring names.
EDGES = (
    "", " ", "\x00", "\x00\x00", "a\x00b", "头发\x00头发", "\x00头发", "头发\x00", "發\x00發", "乾淨\x00乾淨", "后来\x00来",
    "⿰", "⿰氵", "⿰氵發", "⿰氵發後", "後⿰氵發", "⿲木木木", "⿲木木", "⿳⿰木木口口", "⿾發", "⿿發", "⿰ab", "⿰ \x00",
    "⿰⿰⿰", "⿱⿰木木發後來", "头发⿰氵头发头发", "⿰头发", "⿰\U00020000發", "⿰木", "⿻木木頭髮",
    _nested(14), _nested(15), _nested(16), _nested(17), _long(61), _long(63), _long(65), _long(67) + "頭髮",
    "\uf900", "\uf900\uf901豈", "\ufa18", "\u2f00", "\U0002f800", "\U00020000", "\U0002a6d6\U00020000頭髮",
    "发现", "头发", "后来", "皇后", "干净", "干活", "干涉", "睡著", "著名", "乾淨", "乾坤", "爲", "裏", "為", "裡", "著",
    "是只會", "鄰里", "鄰裡", "我的头发 后来", "Hello 头发，ok 2! [x]", "斑馬斑馬 你不要睡著啦", "斑马斑马 你不要睡着啦",
    "夢を見た", "가나다", "😀頭髮😀", "\r\n头发\r\n", "　头发　", "〇", "\ue815", "ｈｅｌｌｏ 頭髮",
)
# Sheets at the edges: none, empty lines, no Chinese, kana, ties, a NUL, compatibility ideographs, 〇 (RE_HANS's, no
# _HAN's), 著 alone and in words in either script.
EDGE_SHEETS = (
    (), ("",), ("la la", ""), ("Hello",), ("夢を見た", "空"), ("约翰・列侬",), ("頭髮", "头发"), ("頭髮", "头发", "发"),
    ("头发\x00头发",), ("\uf900\uf901",), ("〇〇七",), ("著",), ("睡著",), ("著名的歌", "我们睡着了"),
    ("可我浪費著我寒冷的年華", "顯著 著名 著急 執著", "他們睡著了"), ("著著著著著",), ("顯著著名",), ("著作者著",),
    ("ｈｅｌｌｏ 頭髮",), ("长城", "成长"), ("長城", "成長"), ("\U00020000頭髮",), ("⿰氵發 頭髮",), ("一 不",),
    ("行行行", "銀行行長"), ("。，、",), ("abc", "頭髮", "abc"),
)


# --- OpenCC: where the package keeps it ------------------------------------------------------------------------------


def _clib() -> Path:
    import opencc

    return Path(opencc.__file__).parent / "clib"


@functools.cache
def config(name: str) -> dict:
    """A config as the package ships it."""
    return json.loads((_clib() / "share" / "opencc" / f"{name}.json").read_text(encoding="utf-8"))


def _files(spec: dict | None, *, tofu: bool) -> list[str]:
    """The ocd2 files a dictionary's spec reads (``tofu``: those marked ``may_output_tofu`` too), as Config.cpp's
    ParseDict reads them."""
    if spec is None or (spec.get("may_output_tofu") and not tofu):
        return []
    if spec["type"] == "group":
        return [f for child in spec["dicts"] for f in _files(child, tofu=tofu)]
    assert spec["type"] == "ocd2", spec
    return [spec["file"]]


def config_files(name: str) -> list[str]:
    """The ocd2 files ``name`` reads, in the order it reads them, each once."""
    c = config(name)
    files = [f for stage in c.get("normalization", []) for f in _files(stage["dict"], tofu=False)]
    if "segmentation" in c:
        files += _files(c["segmentation"]["dict"], tofu=True)
    files += [f for stage in c["conversion_chain"] for f in _files(stage["dict"], tofu=False)]
    return list(dict.fromkeys(files))


def dictionaries() -> list[str]:
    """Every dictionary the three configs read, by name, in the order they first read them."""
    return list(dict.fromkeys(f.removesuffix(".ocd2") for c in CONFIGS for f in config_files(c)))


@functools.cache
def dumped(name: str) -> bytes:
    """``<name>.ocd2`` as the package's own opencc_dict writes it in text."""
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / f"{name}.txt"
        subprocess.run([str(_clib() / "bin" / "opencc_dict"), "-i", str(_clib() / "share" / "opencc" / f"{name}.ocd2"),
                        "-o", str(out), "-f", "ocd2", "-t", "text"], check=True, capture_output=True)
        return out.read_bytes()


@functools.cache
def entries(name: str) -> tuple[tuple[str, str], ...]:
    """A dictionary's keys and first values, in its dump's order."""
    lines = dumped(name).decode("utf-8").split("\n")
    assert lines[-1] == "", name
    return tuple((key, values.split(" ")[0]) for key, values in (line.split("\t") for line in lines[:-1]))


def opencc_json() -> str:
    import opencc

    return viewer_corpus.data_json({"opencc": opencc.__version__, "package": importlib.metadata.version("opencc"),
                                    "configs": {name: config(name) for name in CONFIGS}})


def pinyin_json() -> str:
    return viewer_corpus.data_json({"_KANA": pinyin._KANA.pattern, "_ZHU_WORDS": sorted(pinyin._ZHU_WORDS),
                                    "_LONGEST": pinyin._LONGEST})


def convert(config_name: str, text: str) -> str:
    """OpenCC's answer, as hanzi.py asks it."""
    return hanzi._converter(config_name)(text)


def converted(text: str) -> dict[str, str]:
    return {name: convert(name, text) for name in CONFIGS}


def page_converted(text: str) -> dict[str, str]:
    return {name: hanzi._converted(name, text) for name in CONFIGS}


def _items(shown: dict[str, dict[str, str]]) -> dict[str, list[list[str]]]:
    """``scripts``' and ``names``' answer, each table's items in their order (a page writes them so; a record's
    objects are written with their keys sorted)."""
    assert list(shown) == ["simplified", "traditional"]
    return {script: [[before, after] for before, after in table.items()] for script, table in shown.items()}


def sheet_hanzi(texts: list[str], names: list[str]) -> dict:
    return {"scripts": _items(hanzi.scripts(texts)), "traditional": hanzi.written_in_traditional(texts),
            "names": _items(hanzi.names(names))}


def page_pinyin(lines: list[str]) -> dict:
    return {"is_chinese": pinyin.is_chinese(lines), "readings": pinyin.readings(lines)}


# --- the data --------------------------------------------------------------------------------------------------------


def test_the_dictionaries_are_openccs_own_dumped_in_text():
    names = dictionaries()
    assert "TSCharactersExt" not in names
    assert {"STPhrases", "TSCharacters", "CJK_Compatibility_Ideographs"} <= set(names)
    for name in names:
        check(HANZI_DATA / f"{name}.txt", dumped(name))
    written = sorted(p.name for p in HANZI_DATA.iterdir() if p.name != "opencc.json")
    assert written == sorted(f"{name}.txt" for name in names), "a stale file in data/caracole/hanzi"


def test_opencc_json_is_the_version_and_the_three_configs():
    check(HANZI_DATA / "opencc.json", opencc_json())


def test_pinyin_json_is_pinyin_pys_constants():
    check(viewer_corpus.VIEWER_DATA / "pinyin.json", pinyin_json())


def test_what_the_phone_takes_for_granted_of_opencc():
    """The phone's reader rests on these: an OpenCC or a config that breaks one says so here."""
    for name in CONFIGS:
        c = config(name)
        assert set(c) <= {"name", "normalization", "segmentation", "conversion_chain"}, name
        if "segmentation" in c:
            assert c["segmentation"]["type"] == "mmseg" and set(c["segmentation"]) == {"type", "dict"}
            assert "may_output_tofu" not in json.dumps(c["segmentation"]), name
        for stage in [*c.get("normalization", []), *c["conversion_chain"]]:
            assert set(stage) == {"dict"}, name

        def walk(spec: dict) -> None:
            assert spec["type"] in ("ocd2", "group"), spec
            if spec["type"] == "group":
                assert spec.get("match_policy", "short_circuit") in ("short_circuit", "union"), spec
                for child in spec["dicts"]:
                    walk(child)
            else:
                assert spec["file"].endswith(".ocd2") and "/" not in spec["file"], spec

        for stage in [*c.get("normalization", []), *c["conversion_chain"]]:
            walk(stage["dict"])
        if "segmentation" in c:
            walk(c["segmentation"]["dict"])
    for name in dictionaries():
        keys = [key for key, _ in entries(name)]
        assert len(keys) == len(set(keys)) and all(keys), name
        for key, value in entries(name):
            assert value and "\x00" not in key and not set(key) & set("".join(SEPARATORS)), (name, key)
            assert not set(value) & set("".join(SEPARATORS)), (name, value)
            # hanzi.py's rule rests on it too: a phrase is as long as what it becomes.
            assert len(value) == len(key), (name, key, value)


def _groups(spec: dict, *, tofu: bool):
    """Each group a dictionary's spec holds, as the config reads it: its policy and the members left in it."""
    if spec.get("may_output_tofu") and not tofu or spec["type"] != "group":
        return
    members = [child for child in spec["dicts"] if _files(child, tofu=tofu)]
    if members:
        yield spec.get("match_policy", "short_circuit"), members
    for child in members:
        yield from _groups(child, tofu=tofu)


def test_the_vectors_tell_the_group_policies_apart_wherever_this_data_can():
    """What the vectors can't show of the two policies, this data never needs: an OpenCC whose dictionaries need it
    fails here by name, and its vectors then need texts that tell the policies apart (OpenCC.kt follows
    PrefixMatch.cpp for both).

    - ``short_circuit``: every member after the first holds one-character keys alone, so the first member that
      matches is also the longest match, the first of them on a tie: what ``union`` would answer.
    - ``union``: a key two members hold has one first value in both, so its tie-break changes nothing; its longest
      match is told apart, as some later member's key goes on from an earlier member's.
    """
    longer = False
    for name in CONFIGS:
        c = config(name)
        specs = [(stage["dict"], False) for stage in [*c.get("normalization", []), *c["conversion_chain"]]]
        if "segmentation" in c:
            specs.append((c["segmentation"]["dict"], True))
        for spec, tofu in specs:
            for policy, members in _groups(spec, tofu=tofu):
                files = [_files(member, tofu=tofu) for member in members]
                held = [{key: value for file in fs for key, value in entries(file.removesuffix(".ocd2"))}
                        for fs in files]
                if policy == "short_circuit":
                    for fs, keys in zip(files[1:], held[1:]):
                        assert max(map(len, keys)) == 1, (name, fs, "a later member's key of two characters")
                    continue
                assert all(member["type"] == "ocd2" for member in members), (name, "a union of groups")
                first: dict[str, str] = {}
                for fs, keys in zip(files, held):
                    for key, value in keys.items():
                        assert first.setdefault(key, value) == value, (name, fs, key, "a tie a union breaks")
                for n, keys in enumerate(held[1:], start=1):
                    earlier = set().union(*held[:n])
                    longer |= any(key[:end] in earlier for key in keys for end in range(1, len(key)))
    assert longer, "no union's longest match the vectors show"


# --- the vectors ------------------------------------------------------------------------------------------------------


def _key_batches(name: str) -> list[tuple[str, list[str]]]:
    """Every key of every dictionary config ``name`` reads, ``KEYS_A_TEXT`` a batch, each with its separator."""
    batches = []
    for file in config_files(name):
        keys = [key for key, _ in entries(file.removesuffix(".ocd2"))]
        for at in range(0, len(keys), KEYS_A_TEXT):
            batches.append((SEPARATORS[len(batches) % len(SEPARATORS)], keys[at:at + KEYS_A_TEXT]))
    return batches


def key_records() -> list[dict]:
    records = []
    for name in CONFIGS:
        for separator, keys in _key_batches(name):
            text = separator.join(keys)
            records.append({"fn": HELPER + "convert", "args": [name, text], "kw": {}, "out": convert(name, text)})
    return records


@functools.cache
def _mixes() -> tuple[str, ...]:
    rng = random.Random(SEED)
    phrases = [key for name in dictionaries() for key, _ in entries(name) if len(key) > 1]
    values = [value for name in dictionaries() for _, value in entries(name) if len(value) > 1]
    chars = [c for name in dictionaries() for key, value in entries(name) if len(key) == 1 for c in (key, value)]
    compatibility = [key for key, _ in entries("CJK_Compatibility_Ideographs")]
    operators = sorted(IDS_ARITY)
    others = [" ", "  ", "，", "。", "、", "·", "-", "(", ")", "（", "）", "《", "》", "'", "!", "?", "\n", "\t", "　",
              "/", "&", "ー", "…", "\r\n", "\x00", "[Am]", "x2"]
    latin = ["Song", "dongye", "a", "ABC", "ü", "é", "ß", "Ａ", "x", "la la"]
    digits = ["0", "2011", "２０１１", "①"]

    def ids(depth: int = 0) -> str:
        operator = rng.choice(operators)
        operands = [ids(depth + 1) if depth < 3 and rng.random() < 0.2 else rng.choice(chars + latin[:3])
                    for _ in range(IDS_ARITY[operator])]
        if rng.random() < 0.15:  # cut short
            operands = operands[:rng.randrange(len(operands))]
        return chr(operator) + "".join(operands)

    def piece() -> str:
        kind = rng.choices(("phrase", "value", "prefix", "char", "compat", "ids", "other", "latin", "digit", "kana",
                            "hangul", "emoji", "supplementary"),
                           weights=(8, 4, 3, 6, 1, 1, 3, 1, 1, 1, 1, 1, 1))[0]
        if kind == "phrase":
            return rng.choice(phrases)
        if kind == "value":
            return rng.choice(values)
        if kind == "prefix":
            p = rng.choice(phrases)
            return p[:rng.randrange(1, len(p))]
        if kind == "char":
            return "".join(rng.choice(chars) for _ in range(rng.randint(1, 4)))
        if kind == "compat":
            return rng.choice(compatibility)
        if kind == "ids":
            return ids()
        if kind == "other":
            return rng.choice(others)
        if kind == "latin":
            return rng.choice(latin)
        if kind == "digit":
            return rng.choice(digits)
        if kind == "kana":
            return "".join(chr(rng.randint(0x3041, 0x3096)) for _ in range(rng.randint(1, 3)))
        if kind == "hangul":
            return chr(rng.randint(0xAC00, 0xD7A3))
        if kind == "emoji":
            return rng.choice(["🎸", "😀", "\U0001F004"])
        return chr(rng.choice((rng.randint(0x20000, 0x2A6DF), rng.randint(0x2F800, 0x2FA1D))))

    return tuple("".join(piece() for _ in range(rng.randint(1, 10))) for _ in range(MIXES))


def mix_records() -> list[dict]:
    return [{"fn": HELPER + "converted", "args": [text], "kw": {}, "out": converted(text)}
            for text in [*EDGES, *_mixes()]]


def page_converted_records() -> list[dict]:
    return [{"fn": HELPER + "page_converted", "args": [text], "kw": {}, "out": page_converted(text)}
            for text in [*EDGES, *_mixes()[:PAGE_MIXES]]]


def test_opencc_vectors_are_openccs_answers_and_the_data_reads_each():
    records = key_records() + mix_records()
    check(viewer_corpus.VIEWER_VECTORS / "opencc.jsonl", jsonl(records, corpus="viewer/opencc", made_by=MADE_BY))
    # They hold what they mean to: every key of each config, and conversions of each kind.
    for name in CONFIGS:
        texts = [r["args"][1] for r in records if r["fn"] == HELPER + "convert" and r["args"][0] == name]
        batches = _key_batches(name)
        assert texts == [separator.join(keys) for separator, keys in batches]
        held = {key for _, keys in batches for key in keys}
        assert held == {key for f in config_files(name) for key, _ in entries(f.removesuffix(".ocd2"))}, name
    outs = [r["out"] for r in records if r["fn"] == HELPER + "converted"]
    assert any(o["tw2s"] != o["t2s"] for o in outs) and any(len(o["s2tw"]) != len(t) for o, t in
                                                             zip(outs, [*EDGES, *_mixes()]))
    assert converted("头发\x00头发") == {"t2s": "头发\x00头发", "tw2s": "头发", "s2tw": "頭髮頭髮"}
    assert converted("⿰氵發後") == {"t2s": "⿰氵發后", "tw2s": "⿰氵發后", "s2tw": "⿰氵發後"}
    # The data alone converts each, as the phone does.
    data = _OpenCC()
    for record in records:
        if record["fn"] == HELPER + "convert":
            name, text = record["args"]
            assert data.convert(name, text) == record["out"], (name, text)
        else:
            assert {name: data.convert(name, record["args"][0]) for name in CONFIGS} == record["out"], record["args"]


def _literals() -> list[str]:
    found: set[str] = set()
    for name in LITERALS_FROM:
        tree = ast.parse((TESTS / name).read_text("utf-8"))
        found |= {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and has_han(node.value)}
    return sorted(found)


def _names(sheet: viewer_corpus.CorpusSheet) -> list[str]:
    """Its title, its artist's name and its page's title, as ``page.build_viewer`` hands them to ``names_table``."""
    parsed = parse_sheet(sheet.cho)
    title = parsed.title or "Untitled"
    page_title = f"{title} · {parsed.artist}" if parsed.artist else title
    return [text for text in (title, parsed.artist, page_title) if text]


@functools.cache
def _seeded_sheets() -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """``SHEETS`` sheets of seeded lines, each ``(lines, names)``: words of STPhrases (Simplified) or their values
    (Traditional), the sheet in one script, the other or both, with 著 words of each kind, Latin, chords' room and
    punctuation."""
    rng = random.Random(SEED + 1)
    simplified = [key for key, _ in entries("STPhrases")]
    traditional = [value for _, value in entries("STPhrases")]
    zhu = sorted(pinyin._ZHU_WORDS) + ["显著", "名著", "执著", "睡著", "著急", "浪費著", "看著", "著作", "顯著"]
    zhe = ["睡着", "着急", "看着", "等着", "着凉", "沉着"]
    glue = ["", "", " ", "，", "。", "！", "的", "了", "我", "你", " la ", "(x2)", "  "]
    out = []
    for n in range(SHEETS):
        script = n % 4  # 0 Simplified, 1 Traditional, 2 both, 3 mostly one with a word of the other
        lines = []
        for _ in range(rng.randint(2, 14)):
            words = []
            for _ in range(rng.randint(1, 6)):
                pick = rng.random()
                if pick < 0.12:
                    word = rng.choice(zhu + zhe)
                else:
                    i = rng.randrange(len(simplified))
                    use_t = script == 1 or (script == 2 and rng.random() < 0.5) or (script == 3 and rng.random() < 0.1)
                    word = traditional[i] if use_t else simplified[i]
                words.append(word + rng.choice(glue))
            lines.append("".join(words) if rng.random() < 0.9 else rng.choice(("", "la la la", "[Am] [G]")))
        names = (rng.choice(lines) or "Untitled", rng.choice(("宋冬野", "張學友", "张学友", "The Placeholders")))
        out.append((tuple(lines), names))
    return tuple(out)


def _corpus_sheets() -> list[tuple[str, list[str], list[str], list[str]]]:
    """Each corpus sheet's name, drawn lines, written texts and names."""
    out = []
    for sheet in viewer_corpus.sheets():
        parsed = parse_sheet(sheet.cho)
        out.append((sheet.name, page._drawn_lines(parsed), page._written_texts(parsed), _names(sheet)))
    return out


def hanzi_records() -> list[dict]:
    records = page_converted_records()
    sheets = [(texts, names) for _, lines, texts, names in _corpus_sheets() if pinyin.is_chinese(lines)]
    others = [(texts, names) for _, lines, texts, names in _corpus_sheets() if not pinyin.is_chinese(lines)][:4]
    literals = _literals()
    inputs = [*sheets, *others, *((list(lines), list(names)) for lines, names in _seeded_sheets()),
              *(([text], [text]) for text in literals), (literals, literals[:3]),
              *((list(lines), list(lines)) for lines in EDGE_SHEETS)]
    records += [{"fn": HELPER + "sheet_hanzi", "args": [texts, names], "kw": {}, "out": sheet_hanzi(texts, names)}
                for texts, names in inputs]
    return records


def test_hanzi_vectors_are_hanzi_pys_answers():
    records = hanzi_records()
    check(viewer_corpus.VIEWER_VECTORS / "hanzi.jsonl", jsonl(records, corpus="viewer/hanzi", made_by=MADE_BY))
    sheets = [r["out"] for r in records if r["fn"] == HELPER + "sheet_hanzi"]
    # Sheets of either script, conversions both ways, and names judged otherwise than their sheet.
    assert sum(s["traditional"] for s in sheets) > 20 and sum(not s["traditional"] for s in sheets) > 20
    assert any(s["scripts"]["simplified"] for s in sheets) and any(s["scripts"]["traditional"] for s in sheets)
    assert any(s["names"]["traditional"] for s in sheets if s["traditional"])
    # A conversion that came out of another length is made again a character at a time.
    assert len(convert("s2tw", "头发\x00头发")) != 5 and hanzi._converted("s2tw", "头发\x00头发") == "頭發\x00頭發"


def pinyin_records() -> list[dict]:
    corpus = _corpus_sheets()
    latin = [lines for name, lines, _, _ in corpus if not any(has_han(line) for line in lines)][:LATIN_SHEETS]
    sheets = [lines for name, lines, _, _ in corpus if any(has_han(line) for line in lines)] + latin
    literals = _literals()
    inputs = [*sheets, *(list(lines) for lines, _ in _seeded_sheets()), *([text] for text in literals), literals,
              *(list(lines) for lines in EDGE_SHEETS)]
    return [{"fn": HELPER + "page_pinyin", "args": [lines], "kw": {}, "out": page_pinyin(lines)} for lines in inputs]


def test_pinyin_page_vectors_are_pinyin_pys_answers():
    records = pinyin_records()
    check(viewer_corpus.VIEWER_VECTORS / "pinyin_page.jsonl",
          jsonl(records, corpus="viewer/pinyin_page", made_by=MADE_BY))
    outs = [r["out"] for r in records]
    # Chinese sheets, kana ones (none), Latin ones (none), and the 著 rule both ways.
    assert sum(o["readings"] is not None for o in outs) > 100
    assert any(o["readings"] is None and o["is_chinese"] is False for o in outs)
    read = [syllable for o in outs if o["readings"] for line in o["readings"] if line for syllable in line]
    assert {"zhù", "zháo", "zhe", ""} <= set(read)


# --- OpenCC, from the data alone -------------------------------------------------------------------------------------


class _OpenCC:
    """The three configs as viewer.chinese.OpenCC reads them: opencc.json's configs over the dictionaries' dumps
    (the module's docstring says how, step by step)."""

    def __init__(self):
        data = json.loads(opencc_json())
        self.leaves: dict[str, tuple[dict[str, str], int]] = {}
        self.configs = {}
        for name, c in data["configs"].items():
            norm = [d for d in (self._dict(s["dict"], tofu=False) for s in c.get("normalization", [])) if d]
            chain = [d for d in (self._dict(s["dict"], tofu=False) for s in c["conversion_chain"]) if d]
            seg = self._dict(c["segmentation"]["dict"], tofu=True) if "segmentation" in c else None
            self.configs[name] = (norm, "segmentation" in c, seg, chain)

    def _leaf(self, file: str) -> tuple[dict[str, str], int]:
        name = file.removesuffix(".ocd2")
        if name not in self.leaves:
            held = dict(entries(name))
            self.leaves[name] = (held, max(map(len, held)))
        return self.leaves[name]

    def _dict(self, spec: dict, tofu: bool):
        """A dictionary: ("leaf", entries), ("short_circuit" | "union", [children]), or None."""
        if spec.get("may_output_tofu") and not tofu:
            return None
        if spec["type"] == "group":
            children = [d for d in (self._dict(child, tofu) for child in spec["dicts"]) if d is not None]
            return (spec.get("match_policy", "short_circuit"), children) if children else None
        return ("leaf", self._leaf(spec["file"]))

    def _match(self, d, text: str, at: int) -> tuple[int, str] | None:
        """The longest key of ``d`` that begins at ``at``: its length, its value."""
        kind, held = d
        if kind == "leaf":
            keys, longest = held
            for end in range(min(len(text), at + longest), at, -1):
                if text[at:end] in keys:
                    return end - at, keys[text[at:end]]
            return None
        best = None
        for child in held:
            found = self._match(child, text, at)
            if found is not None and kind == "short_circuit":
                return found
            if found is not None and (best is None or found[0] > best[0]):
                best = found
        return best

    @staticmethod
    def _ids(text: str, at: int) -> int:
        """The length of the IDS that begins at ``at``, 0 for none whole."""
        if at >= len(text) or ord(text[at]) not in IDS_ARITY:
            return 0
        count = [0]

        def consume(i: int, depth: int) -> int | None:  # its end, or None: incomplete or invalid
            if i >= len(text) or depth == 0 or count[0] >= 64:
                return None
            count[0] += 1
            arity = IDS_ARITY.get(ord(text[i]), 0)
            i += 1
            for _ in range(arity):
                if i >= len(text):
                    return None
                i = consume(i, depth - 1)
                if i is None:
                    return None
            return i

        end = consume(at, 16)
        return 0 if end is None else end - at

    def _conversion(self, d, text: str) -> str:
        out, at = [], 0
        while at < len(text):
            found = self._match(d, text, at)
            if found is None:
                n = self._ids(text, at) or 1
                out.append(text[at:at + n])
            else:
                n, value = found
                out.append(value)
            at += n
        return "".join(out)

    def _segments(self, d, text: str) -> list[str]:
        segments, start, at = [], 0, 0
        while at < len(text):
            found = self._match(d, text, at)
            if found is None:
                at += self._ids(text, at) or 1
            else:
                if at > start:
                    segments.append(text[start:at])
                segments.append(text[at:at + found[0]])
                at += found[0]
                start = at
        if at > start:
            segments.append(text[start:at])
        return segments

    def _chain(self, dicts: list, text: str) -> str:
        for d in dicts:
            text = self._conversion(d, text)
        return text

    def convert(self, name: str, text: str) -> str:
        norm, segmented, seg, chain = self.configs[name]
        text = self._chain(norm, text)
        if not segmented:
            return self._chain(chain, text)
        segments = self._segments(seg, text) if seg is not None else [text]
        return "".join(self._chain(chain, segment.split("\x00")[0]) for segment in segments)


@pytest.mark.parametrize("name", CONFIGS)
def test_the_data_alone_converts_hanzi_pys_words_as_opencc_does(name):
    data = _OpenCC()
    for text in [*EDGES, *_literals()]:
        assert data.convert(name, text) == convert(name, text), (name, text)
