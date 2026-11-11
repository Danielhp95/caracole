"""LaCuerda for the phone: what lacuerda.py's parsers, lacuerda_index.py's store writers, lacuerda_search.py,
lacuerda_fetch.py for a lookup's song and ``caracole lacuerda --artist`` and ``--search`` answer, written for the Kotlin
port's core.lacuerda (``LaCuerdaPages``, ``LaCuerda``'s writers, ``LaCuerdaSearch``, ``LaCuerdaSheets``) and
core.lookup.sites' ``LaCuerdaCommands`` to agree with (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, lanes
lacuerda-pages and lacuerda-sheets).

A body is ``{"fixture": …}``, a file of tests/fixtures/, or ``{"text": …}``: the page as Python's parsers are handed
it, ``resp.text`` (its bytes read as UTF-8, a byte that isn't replaced). A song is ``plain(LCSong)``, ``{slug, title,
types, ranking, lcd}``; an artist ``{slug, name, songs}``; an answer of the search ``plain(SearchAnswer)``, ``{songs:
[{artist_slug, artist, song}], artists, stated}``. A parser that raises is ``err``: ``"LaCuerdaParseError: <its
words>"``, or urllib's ``"ValueError: <its words>"`` (a link urlsplit refuses).

**Vectors**:

- sites/lacuerda_pages.jsonl:
  - ``caracole.lacuerda.<parser>`` records, ``args`` the body and ``kw.url``: ``parse_artist_page`` (``out`` its
    songs), ``parse_popularity`` (``out`` ``[[slug, place], …]`` in the dict's order), ``parse_artist_name``,
    ``is_missing_artist_page``, ``parse_version_page`` (the sheet's text) and ``parse_search`` (the answer), over
    tests/fixtures/lacuerda, the pages helpers/lacuerda_site.py makes, and an edge set (every cut-short refusal);
  - batches, ``args`` ``[inputs]`` and ``out`` the answer to each in turn: ``parse_lcd`` (``[types, ranking]``),
    ``best_acordes_version`` (each input ``[types, ranking]``), ``search_words``, ``search_url`` (a URL, or
    ``{"err": "ValueError: …"}``), ``is_spanish`` and ``looks_spanish`` (each input ``[title, lyrics]``);
  - ``match_title`` records: ``args`` ``[songs, [titles]]``, ``kw.cutoff``, ``out`` each title's song's slug or null.
- sites/lacuerda_store.jsonl: ``caracole.lacuerda_index.ops``, a database (``fixture``, dump_fixture's) and ``ops``
  run in turn on it: ``store_songs`` (``slug``, ``name``, ``songs``, ``popular``), ``store_artist_page`` (``slug``,
  ``body``) and ``store_search`` (``answer``, or ``body``, a page parse_search reads); ``out`` after each op its
  result, ``lacuerda_index``'s rows (null where the op changed none of them) and the kv it changed. Each op's ``at``
  is the phone's alone: when its store notes the page it wrote (core.index.Reads, kv
  ``phone:read:lacuerda:<page>``), which Python doesn't, so the replay checks the notes and leaves them out of the kv
  compared.
- lookup/lacuerda_gate.jsonl:
  - ``caracole.lacuerda_search.gate``: a database of kv records and events (``fixture``), ``kw`` the ``query``,
    ``strong``, ``now`` and the ``provider``'s settings over config.py's defaults (``enabled``, ``lookup_requests``,
    ``lookup_per_hour``); ``out`` null, or the gate's ``state``, ``key``, ``asked`` (the kv record, as json.loads
    reads it), ``failure`` (``own``, ``count``, ``error``, ``until`` as ``isoformat``) and ``route``, what
    search_routes._lacuerda_search_gate makes of it for ``/api/search`` (``state``, ``query``, ``key``, ``why``);
  - ``query_key`` (a batch); ``record_failure`` and ``_forget_failure`` (``kw`` ``key``, ``now`` and ``error``;
    ``out`` kv ``lacuerda:search-failed``'s text after); ``searches_used`` (``kw.now``); ``answered`` (a library and
    an index, ``args`` ``[queries]``, ``out`` each one's answer).
- lookup/lacuerda_search.jsonl: ``caracole.lacuerda_search.search`` scenario records (tests/helpers/scenario.py),
  ``kw.query``: the one request, the answer stored in the index, kv ``lacuerda:search:<key>`` and the failures' kv in
  one savepoint, a cached answer younger than 30 days asked for no more, an older one asked again, one that won't
  parse asked once more past the cache, a page cut short or a block an error that records nothing, a spent budget.
- lookup/lacuerda_sheets.jsonl (lane lacuerda-sheets): scenario records of ``caracole.lacuerda_fetch.lacuerda_sheets``
  for a lookup's songs (``kw.only``; ``kw.rank``, the rank policy's fields that differ from ``RankPolicy()``'s), its
  stats ``{tried, errors, budget_exhausted, failures: [[song id, error's class, its words]], kept, missing, shared:
  [words]}``, over a library and its overrides.toml (the phone's ``phone_overrides`` rows, overrides.py's writers'
  entries): a sheet kept, picked, or not replacing a better one, the auto sheet retired, a sheet the library lost
  written again, a shared folder waiting; the artist's slugs tried in order, a 404 or "aqui llega:" moving on; each
  page cached 30 days, a stale copy no answer once the budget is spent; misses (``lacuerda_checked_at``) and errors;
  and ``caracole.lacuerda_fetch.read_artist_page`` (``kw.artist``, its result ``[slug, songs]`` or null).
- lookup/commands_lacuerda.jsonl (lane lacuerda-sheets): ``caracole lacuerda --artist`` and ``--search --progress``
  (``command_record``: ``kw.command``, ``artist`` or ``query`` and ``auto``) as caracole serve queues them, each a
  scenario through the record's client, the command's own run's events logged into its database; ``out.result``
  ``{"lines"}``, every line it prints, its last ("Read: ", "Not found: ", "Not read: ", "Searched: ", "Found
  already: ", "Nothing found: ", "Not searched: ") the one its runner says.

Each of those two files' records also carries ``noted``: the pages the pass stored in LaCuerda's index (``noting``),
which the phone notes for its next push to the computer (kv ``phone:read:lacuerda:<page>`` at the record's now) and
Python doesn't; the replay checks them and leaves them out of the kv it compares. songs.py's clock is the record's
time while a pass runs (``sheets_clock``), and info.json, the viewer's (milestone 5's), is written by none.
"""

from __future__ import annotations

import json
import re
import sqlite3
import types
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
from conftest import add_song, migrated_database
from helpers.corpus import VECTORS, check, dump_fixture, fixture_bytes, fixture_ref, jsonl, phone_schema, plain
from helpers.lacuerda_site import artist_page, artists_search_page, fixture, search_page
from helpers.scenario import record as scenario

from caracole import config, db, lacuerda_index, lacuerda_search
from caracole.lacuerda import (
    _ENGLISH_WORDS,
    _SPANISH_WORDS,
    BASE_URL,
    LaCuerdaParseError,
    LCArtist,
    LCSong,
    SearchAnswer,
    SearchSong,
    _language_counts,
    best_acordes_version,
    is_missing_artist_page,
    is_spanish,
    looks_spanish,
    match_title,
    parse_artist_name,
    parse_artist_page,
    parse_lcd,
    parse_popularity,
    parse_search,
    parse_version_page,
    search_url,
    search_words,
)

SITES = VECTORS / "sites"
LOOKUP = VECTORS / "lookup"
MADE_BY = "tests/test_conformance_lacuerda_lookups.py"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
NOW_STAMP = "2026-11-03T12:00:00Z"
SOFT_404 = "aqui llega:../tabs/z/zzq_no_such_artist_qqz/index.html"
SODA = f"{BASE_URL}/soda_stereo/"


def stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(**delta: float) -> str:
    return stamp(NOW - timedelta(**delta))


# --- what a record holds -------------------------------------------------------------------------------------


def body(page: str | dict[str, str]) -> dict[str, str]:
    return page if isinstance(page, dict) else {"text": page}


def text_of(given: dict[str, str]) -> str:
    return fixture_bytes(given).decode("utf-8", "replace") if "fixture" in given else given["text"]


def parsed(fn: str, parse, case: str, page: str | dict[str, str], url: str | None = None,
           out=plain) -> dict[str, Any]:
    """A parser's record: what it made of the page, or its error's words."""
    given = body(page)
    record: dict[str, Any] = {"fn": f"caracole.lacuerda.{fn}", "case": case, "args": [given], "kw": {"url": url}}
    try:
        record["out"] = out(parse(text_of(given), url=url) if url is not None else parse(text_of(given)))
    except LaCuerdaParseError as e:
        record["err"] = f"LaCuerdaParseError: {e}"
    except ValueError as e:  # urllib's, from a link it can't split
        record["err"] = f"ValueError: {e}"
    return record


def batch(fn: str, case: str, inputs: list[Any], answer) -> dict[str, Any]:
    outs = []
    for x in inputs:
        try:
            outs.append(plain(answer(x)))
        except ValueError as e:
            outs.append({"err": f"ValueError: {e}"})
    return {"fn": fn, "case": case, "args": [inputs], "out": outs}


def lc(slug: str, title: str, lcd: str) -> LCSong:
    types_, ranking = parse_lcd(lcd)
    return LCSong(slug, title, types_, ranking, lcd)


def _no_url(f):
    """A parser that takes no url, as a parsed() parse."""
    return lambda html, url=None: f(html)


def _places(d: dict[str, int]) -> list[list[Any]]:
    return [[k, v] for k, v in d.items()]


# --- the pages ---------------------------------------------------------------------------------------------------


def _items(*items: str, ul: str = "<ul id=b_main class=b_main>") -> str:
    return f"<html><body><div id=a_cont>{ul}{''.join(items)}</ul></div></body></html>"


def _sheet(pre: str, *, around: str = "<div id=t_body><PRE>{}</PRE></div>") -> str:
    return f"<html><body>{around.format(pre)}</body></html>"


def _search_whole() -> str:
    return fixture("search.html")


def artist_page_records() -> list[dict[str, Any]]:
    p = "parse_artist_page"
    estopa = artist_page("Estopa", "estopa", ("como_camaron", "Como Camarón", "RRT-213"),
                         ("la_raja_de_tu_falda", "La Raja de Tu Falda", "TR-21"), ("tu_calorro", "Tu Calorro", "T-1"))
    chinese = artist_page("宋冬野", "song_dongye", ("banma_banma", "斑马斑马", "RT-12"), ("anhe_qiao", "安和桥", "R-1"))
    return [
        parsed(p, parse_artist_page, "Soda Stereo's page, as captured", fixture_ref("lacuerda/artist.html"), SODA),
        parsed(p, parse_artist_page, "its page, with no url", fixture_ref("lacuerda/artist.html")),
        parsed(p, parse_artist_page, "an artist page made over for Estopa", estopa, f"{BASE_URL}/estopa/"),
        parsed(p, parse_artist_page, "an artist in Chinese characters", chinese),
        parsed(p, parse_artist_page, "entities decoded; items without an lcd or a link skipped", _items(
            "<li lcd='R-1'><a href=\"cancion_y_co\">Canci&oacute;n &amp; Co <em>acordes</em></a></li>",
            "<li><a href=\"sin_lcd\">Sin lcd <em>acordes</em></a></li>",
            "<li lcd='T-1'>sin enlace</li>",
            "<li lcd='RT-21'><a href=\"/otra_banda/otra\">Otra <em>acordes</em></a></li>")),
        parsed(p, parse_artist_page, "titles: the label dropped only when it ends the link", _items(
            "<li lcd='R-1'><a href='uno'>Uno <b>y</b> dos <em>acordes</em>  \n </a></li>",
            "<li lcd='R-1'><a href='dos'><em>acordes</em> Dos</a></li>",
            "<li lcd='R-1'><a href='tres'>Tres <em>a</em><em>b</em></a></li>",
            "<li lcd='R-1'><a href='cuatro'>Cuatro<!-- c --><em>acordes</em></a></li>",
            "<li lcd='R-1'><a href='cinco'>  Cinco   Seis\n<em></em></a></li>",
            "<li lcd='R-1'><a href='seis'><em>solo la etiqueta</em></a></li>",
            "<li lcd='R-1'><a href='siete'><span>Siete <em>acordes</em></span></a></li>")),
        parsed(p, parse_artist_page, "links: the last segment of the path is the slug", _items(
            "<li lcd='R-1'><a href=' ../a/b/ '>B</a></li>",
            "<li lcd='R-1'><a href='https://acordes.lacuerda.net/soda/x?y=1#z'>X</a></li>",
            "<li lcd='R-1'><a href='?solo=consulta'>Nada</a></li>",
            "<li lcd='R-1'><a href='#'>Nada</a></li>",
            "<li lcd='R-1'><a href>Sin valor</a></li>",
            "<li lcd='R-1'><a href=''>Vacío</a></li>",
            "<li lcd='R-1'><a href='javascript:'>Javascript</a></li>",
            "<li lcd='R-1'><a name='x'>Sin href</a><a href='segundo'>Segundo</a></li>",
            "<li lcd='R-1'><a href='mañana%20sí'>Mañana</a></li>")),
        parsed(p, parse_artist_page, "a link urlsplit refuses", _items("<li lcd='R-1'><a href='//[x/y'>X</a></li>")),
        parsed(p, parse_artist_page, "lcd codes kept as written, read as parse_lcd reads them", _items(
            "<li lcd='RT-1'><a href='x'>X <em>acordes</em></a></li>",
            "<li lcd=' rht-312 '><a href='y'>Y</a></li>",
            "<li lcd=''><a href='z'>Z</a></li>",
            "<li lcd><a href='w'>W</a></li>",
            "<li LCD='RR-٢١'><a href='v'>V</a></li>")),
        parsed(p, parse_artist_page, "only the list's own items", _items(
            "<li lcd='R-1'><a href='a'>A</a><ul><li lcd='R-1'><a href='dentro'>Dentro</a></li></ul></li>")
            + "<ul class=b_main><li lcd='R-1'><a href='otra_lista'>Otra</a></li></ul>"),
        parsed(p, parse_artist_page, "an empty list", "<ul id=b_main class=b_main></ul>"),
        parsed(p, parse_artist_page, "a list of items none can be read", _items(
            "<li data-lcd='R-1'><a href='x'>X <em>acordes</em></a></li>")),
        parsed(p, parse_artist_page, "no song list: the song page", fixture_ref("lacuerda/song.html"), SODA),
        parsed(p, parse_artist_page, "no song list: a 404 page", fixture_ref("lacuerda/not_found.html")),
        parsed(p, parse_artist_page, "LaCuerda's no such artist", SOFT_404),
        parsed(p, parse_artist_page, "the list's id in another case", "<ul id=B_MAIN><li lcd='R-1'><a href=x>X</a></li></ul>"),
        parsed(p, parse_artist_page, "in quirks mode, the list's id in another case",
               "<html><body><ul id=B_MAIN><li lcd='R-1'><a href=x>X</a></li></ul></body></html>"),
        parsed(p, parse_artist_page, "in standards mode, the list's id in another case",
               "<!doctype html><html><body><ul id=B_MAIN><li lcd='R-1'><a href=x>X</a></li></ul></body></html>"),
    ]


def popularity_records() -> list[dict[str, Any]]:
    p = "parse_popularity"
    page = "<ul id=b_main><li lcd='R-1'><a href='a'>A</a></li><li lcd='R-1'><a href='b'>B</a></li></ul>"
    three = page.replace("</ul>", "<li><a href='c'>C</a></li><li>sin enlace</li><li><a href='a'>A otra vez</a></li></ul>")
    records = [parsed(p, _no_url(parse_popularity), "Soda Stereo's page", fixture_ref("lacuerda/artist.html"),
                      out=_places),
               parsed(p, _no_url(parse_popularity), "no order", page, out=_places)]
    for case, order in [("an order", "[1,7,0]"), ("spaces and empty places", "[ 1 , ,0, ]"),
                        ("one that isn't a number", "[x]"), ("a negative place", "[-1,0]"),
                        ("Unicode digits and underscores", "[١,0_0]"), ("a place written twice", "[1,1,0]"),
                        ("an empty order", "[]"), ("the items without a slug", "[3,4,2,0,1]"),
                        ("a fraction", "[1.0]"), ("a sign", "[+1,0]"), ("a huge place", "[99999999999999999999,0]")]:
        html = (three if "slug" in case else page) + f"<script>var popOrder = {order};</script>"
        records.append(parsed(p, _no_url(parse_popularity), case, html, out=_places))
    records.append(parsed(p, _no_url(parse_popularity), "spaces around the name and the equals",
                          page + "<script>var\tpopOrder=[1, 0]</script>", out=_places))
    records.append(parsed(p, _no_url(parse_popularity), "the first order of two",
                          page + "<script>var popOrder = [0]; var popOrder = [1,0];</script>", out=_places))
    return records


def name_records() -> list[dict[str, Any]]:
    p = "parse_artist_name"
    return [
        parsed(p, _no_url(parse_artist_name), "Soda Stereo's heading", fixture_ref("lacuerda/artist.html")),
        parsed(p, _no_url(parse_artist_name), "no artist block", "<html><body><h1>no artist block</h1></body></html>"),
        parsed(p, _no_url(parse_artist_name), "spaces collapsed, markup's text kept",
               "<div class='bTit x'><h1>  Los  <b>Fabulosos</b>\n Cadillacs </h1></div>"),
        parsed(p, _no_url(parse_artist_name), "an empty heading", "<div class=bTit><h1> \n</h1></div>"),
        parsed(p, _no_url(parse_artist_name), "a heading not the block's child", "<div class=bTit><p><h1>X</h1></p></div>"),
        parsed(p, _no_url(parse_artist_name), "the first of two", "<div class=bTit><h1>Uno</h1><h1>Dos</h1></div>"),
        parsed(p, _no_url(parse_artist_name), "entities", "<div class=bTit><h1>Man&aacute; &amp; Co</h1></div>"),
    ]


def missing_records() -> list[dict[str, Any]]:
    p = "is_missing_artist_page"
    pages = [("LaCuerda's 54 bytes", SOFT_404), ("with a line end", SOFT_404 + "\n"),
             ("after spaces, in capitals, with an accent", " \n\tAQUÍ LLEGA:x"), ("an i with an accent", "aquí llega:"),
             ("no colon", "aqui llega"), ("an empty page", ""), ("a small error page", "<html><body>No encontrado</body></html>"),
             ("a full page after it", SOFT_404 + "\n" + fixture("song.html")),
             ("just under 1024 bytes", "aqui llega:" + "x" * 1012), ("1024 bytes", "aqui llega:" + "x" * 1013),
             ("1023 bytes of two-byte letters", "aqui llega:" + "ñ" * 506), ("1025 of them", "aqui llega:" + "ñ" * 507),
             ("the artist page", fixture_ref("lacuerda/artist.html")), ("an empty list", "<ul id=b_main class=b_main></ul>"),
             ("a dotless capital I", "AQUİ LLEGA:"), ("a Kelvin sign is no k", "aqui llega:")]
    return [parsed(p, _no_url(is_missing_artist_page), case, page) for case, page in pages]


def version_records() -> list[dict[str, Any]]:
    p = "parse_version_page"
    url = f"{BASE_URL}/soda_stereo/de_musica_ligera-3.shtml"
    small = [
        ("a small sheet, exactly", "Intro:\n\n<div></div><A>Am</A>   <A>Do</A>\nla luz del bar\n"),
        ("solfège chords as written", "<A>Do</A> <A>Rem</A> <A>Sol7</A> <A>La#m</A>\n"),
        ("entities and non-breaking spaces", "Canci&oacute;n &amp; co&nbsp;<A>Fa&#35;m</A> &lt;x2&gt;\n"),
        ("other tags dropped, their text kept", "<b>CORO:</b>\n<em>e|--0--2--|</em>\n<span class=x><A>Em</A></span> fin"
                                               "<br>otra<!-- nota --> linea\n"),
        ("a chord's padding moved out of it", "<A> Am </A>|<A></A>|<A>  </A>|\n"),
        ("Unicode spaces and a non-breaking one in a chord", "<A> G </A>|<A> </A>|\n"),
        ("a chord's own markup read as text", "<A><b>C</b>7</A> <A>D<br>m</A>\n"),
        ("scripts and styles inside it dropped", "x<script>var a=1;</script>y<style>p{}</style>z\n"),
        ("a line break in markup and as written", "uno<br/>dos<BR>tres\r\ncuatro\n"),
        ("a chord inside a chord", "<A>A<A>B</A></A>\n"),
        ("a table inside it", "<table><tr><td>x</td></tr></table>y\n"),
        ("a sheet of spaces and a line", "  \n<div></div>\n"),
        ("a sheet of a non-breaking space", "&nbsp;\n"),
        ("an empty sheet", ""),
        ("the first sheet of two", "uno</PRE><PRE>dos"),
    ]
    records = [parsed(p, parse_version_page, "the version page, as captured", fixture_ref("lacuerda/version.html"), url)]
    records += [parsed(p, parse_version_page, case, _sheet(pre)) for case, pre in small]
    records += [
        parsed(p, parse_version_page, "the song page has previews, no sheet", fixture_ref("lacuerda/song.html"), url),
        parsed(p, parse_version_page, "an artist page has none", fixture_ref("lacuerda/artist.html"), url),
        parsed(p, parse_version_page, "a pre not the block's child", _sheet("x", around="<div id=t_body><p><pre>{}</pre></p></div>")),
        parsed(p, parse_version_page, "a pre after another child", _sheet("x", around="<div id=t_body><b>y</b><pre>{}</pre></div>")),
        parsed(p, parse_version_page, "a pre in a block of another id", _sheet("x", around="<div id=t_bodyx><pre>{}</pre></div>")),
    ]
    return records


def _cut(at: str) -> str:
    whole = _search_whole()
    return whole[:whole.index(at)]


def parse_search_records() -> list[dict[str, Any]]:
    p = "parse_search"
    whole = _search_whole()
    url = f"{BASE_URL}/busca.php?exp=corazon+tiza&canc=1&ord=0&ini=0"
    none = whole.replace(". 3 resultados.", ". 0 resultados.")
    start, end = none.index("<table id=s_main"), none.index("</script>", none.index("var NMAX")) + len("</script>")
    one_row = ("uno", "Uno", [("primera", "Primera", "R-1"), ("segunda", "Segunda", "RR-21")])
    cases: list[tuple[str, str | dict[str, str]]] = [
        ("a whole answer of songs, as captured", fixture_ref("lacuerda/search.html")),
        ("an answer its server cut short, as captured", fixture_ref("lacuerda/search_cut.html")),
        ("no results", none[:start] + none[end:]),
        ("no results, with the table all the same", none),
        ("the slugs from the end of the arrays", search_page(one_row, ("dos", "Dos", [("tercera", "Tercera", "T-1")]))),
        ("an answer of artists", artists_search_page([("bragas_de_la_gaviota", "Las Bragas de la Gaviota", 1),
                                                      ("gaviota", "Gaviota", 12)])),
        ("an answer of artists with a link to no artist's page and items skipped", artists_search_page(
            [("gaviota", "Gaviota", 12)]).replace("</ul>", "<li><a href='/a/b/'>Dos tramos</a></li><li>nada</li></ul>")
            .replace(". 1 resultados.", ". 3 resultados.").replace("<span>1</span>", "<span>3</span>")
            .replace("<li class='sel'>1</li>", "<li class='sel'>1</li><li onclick=\"sChg('ini',50)\">2</li>")),
        ("an answer of artists, none with a link", artists_search_page([]).replace("</ul>", "<li>nada</li></ul>")
            .replace(". 0 resultados.", ". 1 resultados.")),
        ("more results than its page holds", search_page(one_row, stated=120, pages=3)),
        ("fewer rows than it counts, on its only page", search_page(("uno", "Uno", [("primera", "Primera", "R-1")]),
                                                                    stated=3)),
        ("a count in thousands, and a link to another page", search_page(one_row, stated=1234, pages=2)
            .replace(". 1234 resultados.", ". 1.234 resultados.")),
        ("a count with a comma", search_page(one_row, stated=2).replace(". 2 resultados.", ". 2,0 resultados.")),
        ("one result", search_page(("uno", "Uno", [("primera", "Primera", "R-1")])).replace("1 resultados", "1 resultado")),
        ("a count in capitals", whole.replace("3 resultados.", "3 RESULTADOS.")),
        ("a count in Arabic-Indic digits", whole.replace(". 3 resultados.", ". ٣ resultados.")),
        ("a word after the count", whole.replace("3 resultados.", "3 resultadosx.")),
        ("cut inside the table", _cut("<tr><td>\n<a href=\"/marea_baja/")),
        ("cut between the table and its script", _cut("var hds")),
        ("cut before the count", _cut("<div class=s_res>")),
        ("cut before the script's last array", _cut("var NMAX")),
        ("a slug short", whole.replace("var fns=['tiza',", "var fns=[")),
        ("an artist short", whole.replace("var hds=['nina_de_la_lluvia',", "var hds=[")),
        ("NMAX past the arrays", whole.replace("var NMAX=2;", "var NMAX=5;")),
        ("a slug more than the table's songs", whole.replace("var hds=['nina", "var hds=['extra','nina")
            .replace("var fns=['tiza',", "var fns=['extra','tiza',").replace("var NMAX=2;", "var NMAX=3;")),
        ("NMAX in Arabic-Indic digits", whole.replace("var NMAX=2;", "var NMAX=٢;")),
        ("a slug that is no slug", whole.replace("'corazon_de_tiza_en_vivo'", "'../../etc'")),
        ("a slug with an escaped quote", whole.replace("'corazon_de_tiza_en_vivo'", "'it\\'s'")),
        ("slugs in double quotes", whole.replace("var fns=['tiza','corazon_de_tiza_en_vivo','corazon_de_tiza'];",
                                                 "var fns=[\"tiza\", \"corazon_de_tiza_en_vivo\",\"corazon_de_tiza\"];")),
        ("a number past the arrays", whole.replace("<li id='r002'", "<li id='r009'")),
        ("a song with no number", whole.replace("<li id='r002'", "<li")),
        ("a number in Arabic-Indic digits", whole.replace("<li id='r002'", "<li id='r٠٠٢'")),
        ("a row whose link is no artist's page", whole.replace('<a href="/marea_baja/">', '<a href="/ARCH/x.php?a=1">')),
        ("a row with no link", whole.replace('<a href="/marea_baja/">Marea Baja</A>', 'Marea Baja')),
        ("an artist's name from the link, its spaces collapsed", whole.replace(">Los Imaginarios</A>",
                                                                              "> Los&nbsp;<b>Imaginarios</b> </A>")),
        ("an artist with no name", whole.replace(">Los Imaginarios</A>", "> </A>")),
        ("a row with no songs skipped", whole.replace("<tr><td>\n<a href=\"/marea_baja/", "<tr><td>nada</td></tr>"
                                                                                           "<tr><td>\n<a href=\"/marea_baja/")),
        ("neither songs nor artists for the results it counts", whole.replace("<table id=s_main", "<table id=other")),
        ("the table closed in capitals, its id quoted", whole.replace("<table id=s_main", "<TABLE class=x id=\"s_main\"")
            .replace("</table>", "</TABLE >")),
        ("an empty script, no songs", search_page(("uno", "Uno", [])).replace(". 0 resultados.", ". 1 resultados.")),
        ("a maintenance page", "<html><body>Mantenimiento</body></html>"),
        ("titles with entities and markup", whole.replace(">Tiza</a>", ">Ti&ntilde;a <b>de</b> tiza</a>")),
        ("an lcd in lower case", whole.replace("lcd='TB-12'", "lcd='tb-21'")),
        ("a count past a 64-bit integer, on its only page", search_page(one_row, stated=PAST_A_LONG)),
        ("a count past a 64-bit integer, and a link to another page", search_page(one_row, stated=PAST_A_LONG, pages=2)),
    ]
    return [parsed(p, parse_search, case, page, url if n == 0 else None) for n, (case, page) in enumerate(cases)]


#: A count no 64-bit integer holds: Python's int reads it whole, and so must the phone's.
PAST_A_LONG = 2 ** 64 + 1


LCDS = ["RHRTTTDTB-314865972", "RTRTRTRTRTR-a1b23456789", "RTRTRTRTRTR-A1B23456789", "RTRTRTRTRTR-1011123456789",
        "RT-1", "RRR-113", "RR-01", "RR-1?", "RT", "", " rht-312 ", "BR-21", "TBTRTRRT-46783512", "T-1", "TT-21",
        "RT-٢١", "RT-２１", "R-𝟏", "RT-1²", "ßR-12", "ǅ-1", "RT--12", "RT-1-2", "-", "RT-12 ", "R T-123", "RTR-1 2",
        "RT-_1", "RT-+1", " RT-21 ", "RT-١٢", "ﬀ-12", "İ-1", "RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR-"
        + "123456789abcdefghijklmnopqrstuvwxyz1", "RRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR-123456789abcdefghijklmnopqrstuvwxyz"]


def batch_records() -> list[dict[str, Any]]:
    bests = [["RHRTTTDTB", [3, 1, 4, 8, 6, 5, 9, 7, 2]], ["BR", [2, 1]], ["TBTRTRRT", [4, 6, 7, 8, 3, 5, 1, 2]],
             ["T", [1]], ["TT", [2, 1]], ["", []], ["TR", [5, 2, 1]], ["R", [0, 1]], ["r", [1]], ["SSR", [1, 2, 3]],
             ["RT", [-1, 1]], ["ÑR", [2, 1]]]
    queries = ["Corazón Espinado", "la flaca", "Fito & Fitipaldis: ¿Por la boca vive el pez?", "19 días y 500 noches",
               "Ñandú ñandú", "sol y luz", "宋冬野", "", "corazon_de_tiza", "ROCK-AND-ROLL", "1234 abc", "ǅemal",
               "straße", "İstanbul", "naïve café", "Œuvre", "x" * 4, "ﬁnal"]
    titles = [["De Música Ligera", None], ["La Flaca", None], ["19 Días y 500 Noches", None], ["Te Para Tres", None],
              ["Let It Be", None], ["Wonderwall", None], ["Hotel California", None], ["Persiana Americana", None],
              ["", None], ["Señorita", None], ["¿Dónde Estás?", None], ["¡Ay!", None], ["Corazón Espinado", None],
              ["Pingüino", None], ["La Bamba", None], ["Déjà Vu", None], ["Für Elise", None], ["Ça Ira", None],
              ["Café in the Rain", None], ["斑马，斑马", None], ["SEÑORITA", None], ["Señorita".replace("ñ", "ñ"), None],
              ["CORAZÓN ESPINADO", None], ["PINGÜINO", None], ["GÜERO", None], ["STRASSE ß", None], ["Ÿ", None],
              ["Señorita", "I walk the long road when the city is asleep and the lights are on"],
              ["Persiana Americana", "Cruzo la plaza con el café frío y cuento las luces del tren"],
              ["Señorita", "  \n"], ["It's my life", "don't you know that I'm the one you'll never see"],
              ["Un día", "la la la la la la la"], ["", "我走过安静的长街 风吹着旧城的屋檐 你说远方没有尽头 te quiero"],
              ["x", "de de de the the"], ["x", "de de the"], ["x", "de x x x x x x"], ["x", "de x x x x x"],
              ["x", "el’s l`s d´e"], ["x", "ʼde ʼde"], ["x", "Ölé et Ça"], ["x", "un ２ x"], ["x", "_de_ de1 1de"]]
    texts = [t for t, _ in titles] + [lyr for _, lyr in titles if lyr]
    return [
        batch("caracole.lacuerda.parse_lcd", "lcd codes", LCDS, parse_lcd),
        batch("caracole.lacuerda.best_acordes_version", "types and rankings", bests,
              lambda x: best_acordes_version(LCSong("s", "t", x[0], tuple(x[1])))),
        batch("caracole.lacuerda.search_words", "queries", queries, search_words),
        batch("caracole.lacuerda.search_url", "queries, songs only", queries, search_url),
        batch("caracole.lacuerda.search_url", "queries, a general search", queries,
              lambda q: search_url(q, songs_only=False)),
        batch("caracole.lacuerda._language_counts", "each function word alone, then the texts",
              sorted(_SPANISH_WORDS | _ENGLISH_WORDS) + ["", "x", "Ünder dé"] + texts, _language_counts),
        batch("caracole.lacuerda.is_spanish", "texts", texts, is_spanish),
        batch("caracole.lacuerda.looks_spanish", "titles, and lyrics when there are", titles,
              lambda x: looks_spanish(x[0], x[1])),
    ]


def match_records() -> list[dict[str, Any]]:
    soda = parse_artist_page(fixture("artist.html"))
    titles = ["De Música Ligera", "De Música Ligera - Remasterizado 2007", "Cuando Pase El Temblor - MTV Unplugged",
              "de musica ligera", "ÁNGEL ELÉCTRICO", "Algún Día (Someday)", "Picnic en el 4º B", "Persiana Americanna",
              "Hotel California", "Persiana", "斑马斑马", "!!!", "", "1990", "Té para 3", "Telarañas"]
    ties = [LCSong("la_flaca_tab", "La Flaca", "T", (1,)), LCSong("la_flaca", "La Flaca", "TR", (2, 1)),
            LCSong("la_flaca_2", "La flaca", "R", (1,))]
    firsts = [LCSong("la_flaca", "La Flaca", "R", (1,)), LCSong("la_flaca_2", "La flaca", "R", (1,))]
    chinese = [lc("banma_banma", "斑马斑马", "R-1"), lc("anhe_qiao", "安和桥", "RT-21"), lc("x", "", "R-1")]

    def rec(case: str, songs: list[LCSong], asked: list[str], cutoff: float | None = None) -> dict[str, Any]:
        kw = {} if cutoff is None else {"cutoff": cutoff}
        out = [(m.slug if (m := match_title(songs, t, **kw)) is not None else None) for t in asked]
        return {"fn": "caracole.lacuerda.match_title", "case": case, "args": [plain(songs), asked],
                "kw": {"cutoff": 90 if cutoff is None else cutoff}, "out": out}

    return [
        rec("Soda Stereo's page", soda, titles),
        rec("Soda Stereo's page, a lower cutoff", soda, titles, cutoff=60),
        rec("Soda Stereo's page, a cutoff of a fraction", soda, ["Persiana Americanna", "Persiana"], cutoff=94.73684),
        rec("a tie: the song with acordes, then the first on the page", ties, ["La Flaca", "la flaca!"]),
        rec("a full tie: the first", firsts, ["La Flaca"]),
        rec("nothing to match", [], ["De Música Ligera"]),
        rec("Chinese titles, and a song with none", chinese, ["斑马斑马", "斑马", "Banma Banma", "安和桥", ""]),
    ]


def test_lacuerda_pages_jsonl():
    records = [*artist_page_records(), *popularity_records(), *name_records(), *missing_records(),
               *version_records(), *parse_search_records(), *batch_records(), *match_records()]
    check(SITES / "lacuerda_pages.jsonl", jsonl(records, corpus="sites/lacuerda_pages", made_by=MADE_BY))


def test_the_pages_cover_each_outcome():
    searched = parse_search_records()
    errors = [r["err"] for r in searched if "err" in r]
    for words in ("no count", "isn't closed", "no song slugs", "disagree", "no artist's page", "numbered past",
                  "no song slug: ", "rows of the", "neither songs", "songs in the table for"):
        assert any(words in e for e in errors), words
    assert any("out" in r and r["out"]["artists"] for r in searched)
    assert any("out" in r and r["out"]["stated"] == 0 for r in searched)
    assert any("out" in r and r["out"]["stated"] == PAST_A_LONG for r in searched)
    assert any(f"of the {PAST_A_LONG} results it counts" in r.get("err", "") for r in searched)
    pages = artist_page_records()
    assert any(r.get("err", "").startswith("ValueError: ") for r in pages)
    assert sum("err" in r for r in version_records()) >= 6
    assert {r["out"] for r in missing_records()} == {True, False}


# --- the store writers ------------------------------------------------------------------------------------------


def fresh(directory: Path, name: str) -> sqlite3.Connection:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.sqlite"
    path.write_bytes(migrated_database())
    return db.connect(path)


def _rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [r["row"] for r in dump_fixture(conn) if r.get("table") == "lacuerda_index"]


def _kv(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM kv").fetchall())


def _answer(given: dict[str, Any]) -> SearchAnswer:
    return SearchAnswer(
        songs=tuple(SearchSong(s["artist_slug"], s["artist"], LCSong(s["song"]["slug"], s["song"]["title"],
                                                                     s["song"]["types"], tuple(s["song"]["ranking"]),
                                                                     s["song"]["lcd"])) for s in given["songs"]),
        artists=tuple(LCArtist(a["slug"], a["name"], a["songs"]) for a in given["artists"]), stated=given["stated"])


def _songs(given: list[dict[str, Any]]) -> list[LCSong]:
    return [LCSong(s["slug"], s["title"], s["types"], tuple(s["ranking"]), s["lcd"]) for s in given]


def run_ops(conn: sqlite3.Connection, case: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``ops`` record: each op run on ``conn`` in turn, and what came of each."""
    before = dump_fixture(conn)
    outs: list[dict[str, Any]] = []
    last = _rows(conn)
    for op in ops:
        kv_before = _kv(conn)
        if op["op"] == "store_songs":
            result: Any = lacuerda_index.store_songs(conn, op["slug"], op["name"], _songs(op["songs"]), op["popular"])
        elif op["op"] == "store_artist_page":
            result = lacuerda_index.store_artist_page(conn, op["slug"], text_of(op["body"]))
        elif op["op"] == "store_search":
            answer = _answer(op["answer"]) if "answer" in op else parse_search(text_of(op["body"]))
            result = lacuerda_index.store_search(conn, answer)
        else:
            raise AssertionError(op)
        kv_after = _kv(conn)
        changed = {k: kv_after.get(k) for k in sorted(set(kv_before) | set(kv_after)) if kv_before.get(k) != kv_after.get(k)}
        rows = _rows(conn)
        outs.append({"result": result, "rows": None if rows == last else rows, "kv": changed})
        last = rows
    return {"fn": "caracole.lacuerda_index.ops", "case": case, "fixture": before, "ops": ops, "out": outs}


def _song(slug: str, title: str, lcd: str) -> dict[str, Any]:
    return plain(lc(slug, title, lcd))


def _found(artist_slug: str, artist: str, slug: str, title: str, lcd: str) -> dict[str, Any]:
    return {"artist_slug": artist_slug, "artist": artist, "song": _song(slug, title, lcd)}


def store_records(directory: Path) -> list[dict[str, Any]]:
    records = []

    conn = fresh(directory, "soda")
    lacuerda_index.store_artists(conn, "tabs/s/index0.html", [LCArtist("soda_stereo", "Soda Stereo", 89),
                                                              LCArtist("sui_generis", "Sui Generis", 40)])
    conn.execute("DELETE FROM kv WHERE key = ?", (lacuerda_index.KEYS_KEY,))  # the keys made again by the first store
    records.append(run_ops(conn, "an artist page's songs in place of those it gave before", [
        {"op": "store_artist_page", "slug": "soda_stereo", "body": fixture_ref("lacuerda/artist.html"), "at": ago(hours=3)},
        {"op": "store_artist_page", "slug": "soda_stereo", "at": ago(hours=2), "body": {"text": artist_page(
            "Soda Stereo", "soda_stereo", ("persiana_americana", "Persiana Americana", "R-1"))}},
        {"op": "store_songs", "slug": "soda_stereo", "name": None, "popular": None, "at": ago(hours=1),
         "songs": [_song("signos", "Signos", "R-1"), _song("te_para_3", "Té para 3", "TR-21")]},
        {"op": "store_songs", "slug": "sui_generis", "name": "", "popular": {"rasguna": 0, "otra": 4},
         "songs": [_song("rasguna", "Rasguña las Piedras", "RTR-312")], "at": NOW_STAMP},
        {"op": "store_songs", "slug": "los_del_rio_", "name": None, "popular": None, "at": NOW_STAMP,
         "songs": [_song("macarena", "Macarena", "R-1")]},
        {"op": "store_songs", "slug": "__", "name": None, "popular": None, "at": NOW_STAMP,
         "songs": [_song("x", "X", "R-1")]},
        {"op": "store_songs", "slug": "ñandu_ǆungla_ßtraße", "name": None, "popular": None, "at": NOW_STAMP,
         "songs": [_song("y", "Y", "R-1")]},
        {"op": "store_songs", "slug": "soda_stereo", "name": "Soda", "popular": None, "songs": [], "at": NOW_STAMP},
        {"op": "store_artist_page", "slug": "nadie", "body": {"text": SOFT_404}, "at": NOW_STAMP},
        {"op": "store_artist_page", "slug": "nadie", "body": fixture_ref("lacuerda/song.html"), "at": NOW_STAMP},
        {"op": "store_artist_page", "slug": "nadie", "at": NOW_STAMP,
         "body": {"text": "<ul id=b_main><li lcd='R-1'><a href='solo'>Solo</a></li></ul>"}},
    ]))

    conn = fresh(directory, "search")
    lacuerda_index.store_artists(conn, "tabs/s/index0.html", [LCArtist("soda_stereo", "Soda Stereo", 89)])
    lacuerda_index.store_artists(conn, "tabs/g/index0.html", [LCArtist("gaviota", "Gaviota", 12)])
    lacuerda_index.store_artist_page(conn, "soda_stereo", fixture("artist.html"))
    records.append(run_ops(conn, "a search's rows beside what the index holds", [
        {"op": "store_search", "at": ago(hours=2), "answer": plain(SearchAnswer(songs=(
            SearchSong("imaginarios", "Los Imaginarios", lc("corazon_de_tiza", "Corazón de Tiza", "RT-12")),
            SearchSong("soda_stereo", "Soda Stereo", lc("de_musica_ligera", "De Música Ligera", "TR-21")),
            SearchSong("imaginarios", "Imaginarios", lc("otra", "Otra", "T-1"))), stated=3))},
        {"op": "store_search", "at": ago(hours=1), "answer": plain(SearchAnswer(artists=(
            LCArtist("bragas_de_la_gaviota", "Las Bragas de la Gaviota", 1), LCArtist("gaviota", "Gaviota", 30),
            LCArtist("imaginarios", "Los Imaginarios", 7), LCArtist("imaginarios", "Imaginarios Dos", 3)), stated=4))},
        {"op": "store_search", "at": ago(minutes=30), "answer": plain(SearchAnswer(artists=(
            LCArtist("imaginarios", "Los Imaginarios", 2), LCArtist("bragas_de_la_gaviota", "Las Bragas", 9)),
            songs=(SearchSong("nuevo", "Nuevo", lc("cancion", "Canción", "R-1")),), stated=3))},
        {"op": "store_search", "at": ago(minutes=20), "answer": plain(SearchAnswer())},
        {"op": "store_search", "at": ago(minutes=10), "answer": {"songs": [_found("song_dongye", "宋冬野", "banma",
                                                                                  "斑马斑马", "ǅR-21")],
                                                                 "artists": [], "stated": 1}},
        {"op": "store_artist_page", "slug": "imaginarios", "at": NOW_STAMP, "body": {"text": artist_page(
            "Los Imaginarios", "imaginarios", ("corazon_de_tiza", "Corazón de Tiza", "RT-12"), ("otra", "Otra", "R-1"))}},
        {"op": "store_search", "at": NOW_STAMP, "body": fixture_ref("lacuerda/search.html")},
    ]))

    conn = fresh(directory, "rekeyed")
    lacuerda_index.store_artists(conn, "tabs/e/index0.html", [LCArtist("enanitos", "Los Enanitos Verdes", 30)])
    conn.execute("UPDATE lacuerda_index SET artist_key = 'old-key'")
    conn.execute("UPDATE kv SET value = '0' WHERE key = ?", (lacuerda_index.KEYS_KEY,))
    records.append(run_ops(conn, "the keys made again before a store, once", [
        {"op": "store_search", "at": NOW_STAMP, "answer": plain(SearchAnswer(songs=(
            SearchSong("enanitos", "Enanitos Verdes", lc("lamento_boliviano", "Lamento Boliviano", "R-1")),), stated=1))},
        {"op": "store_songs", "slug": "enanitos", "name": "Enanitos Verdes", "popular": {"tus_viejas_cartas": 0},
         "songs": [_song("tus_viejas_cartas", "Tus Viejas Cartas", "RT-21")], "at": NOW_STAMP},
    ]))
    return records


def test_lacuerda_store_jsonl(tmp_path):
    check(SITES / "lacuerda_store.jsonl", jsonl(store_records(tmp_path), corpus="sites/lacuerda_store",
                                                made_by=MADE_BY))


def test_the_stores_replace_add_and_keep_rows(tmp_path):
    soda, search, rekeyed = store_records(tmp_path)
    assert [o["result"] for o in soda["out"]][-3:] == [False, False, True]
    assert soda["out"][0]["kv"] == {lacuerda_index.KEYS_KEY: str(lacuerda_index.normalize.KEY_VERSION)}
    assert [o["result"] for o in search["out"]] == [3, 4, 3, 0, 1, True, 3]
    assert search["out"][3]["rows"] is None
    assert rekeyed["out"][0]["rows"][0]["artist_key"] == "enanitos-verdes"


# --- the gate -------------------------------------------------------------------------------------------------


def _event(conn: sqlite3.Connection, run: str, at: str, decision: str = "ok", provider: str = "lacuerda",
           n: int = 1) -> None:
    for _ in range(n):
        conn.execute("INSERT INTO events (run, at, provider, url, status, decision, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (run, at, provider, f"{BASE_URL}/x", 200 if decision == "ok" else None, decision, None))


def _set(conn: sqlite3.Connection, key: str, value: str) -> None:
    db.kv_set(conn, key, value)


SEARCH_RUN = "lookup:lacuerda-search:"


def _config(**fields: Any) -> config.Config:
    providers = dict(config.DEFAULT_PROVIDERS)
    providers["lacuerda"] = replace(providers["lacuerda"], **fields)
    return types.SimpleNamespace(provider=lambda name: providers[name])  # what gate reads of a Config


def _route(query: str, gate: lacuerda_search.Gate | None) -> dict[str, str] | None:
    """search_routes._lacuerda_search_gate's shaping of the gate, for ``/api/search``."""
    if gate is None:
        return None
    why = {"why": gate.failure.said(f"“{query}”") + "."} if gate.failure is not None else {}
    return {"state": gate.state, "query": query, "key": gate.key, **why}


def gate_record(conn: sqlite3.Connection, case: str, query: str, *, strong: bool = False, now: datetime = NOW,
                **provider: Any) -> dict[str, Any]:
    settings = {"enabled": True, "lookup_requests": 6, "lookup_per_hour": 60, **provider}
    said = lacuerda_search.gate(_config(**settings), conn, query, strong=strong, now=now)
    out = None if said is None else {
        "state": said.state, "key": said.key, "asked": said.asked,
        "failure": None if said.failure is None else {
            "own": said.failure.own, "count": said.failure.count, "error": said.failure.error,
            "until": said.failure.until.isoformat()},
        "route": _route(query, said)}
    return {"fn": "caracole.lacuerda_search.gate", "case": case, "fixture": dump_fixture(conn),
            "kw": {"query": query, "strong": strong, "now": stamp(now), "provider": settings}, "out": out}


def _failures(**at: tuple[str, Any]) -> str:
    import json

    return json.dumps({k: {"at": when, "error": error} for k, (when, error) in at.items()}, ensure_ascii=False)


def gate_records(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    queries = ["corazón de tiza", "tiza corazon", "la flaca", "sol y luz", "宋冬野", "  ", "FLACA!", "Ñandú y Ñandú",
               "estopa como camarón", "straße"]
    records.append(batch("caracole.lacuerda_search.query_key", "queries", queries, lacuerda_search.query_key))

    conn = fresh(directory, "empty")
    records.append(gate_record(conn, "a query sent by itself", "corazón de tiza"))
    records.append(gate_record(conn, "no word LaCuerda reads", "sol y luz"))
    records.append(gate_record(conn, "answered well already", "corazón de tiza", strong=True))
    records.append(gate_record(conn, "LaCuerda turned off", "corazón de tiza", enabled=False))
    records.append(gate_record(conn, "no lookup requests", "corazón de tiza", lookup_requests=0))
    records.append(gate_record(conn, "no lookup requests an hour", "corazón de tiza", lookup_per_hour=0))

    conn = fresh(directory, "asked")
    key = lacuerda_search.query_key("corazón de tiza")
    _set(conn, lacuerda_search.KV_PREFIX + key, '{"at": "%s", "songs": 2, "artists": 0, "stated": 2}' % ago(days=29))
    _set(conn, lacuerda_search.KV_PREFIX + "flaca", '{"at": "%s", "songs": 1, "artists": 0, "stated": 1}' % ago(days=31))
    _set(conn, lacuerda_search.KV_PREFIX + "boca-vive", '{"at": "2026-10-04T12:00:00+00:00", "x": [1, 2.50, null]}')
    _set(conn, lacuerda_search.KV_PREFIX + "camaron-estopa", '["at"]')
    _set(conn, lacuerda_search.KV_PREFIX + "gaviota", '{"at": "not a time"}')
    _set(conn, lacuerda_search.KV_PREFIX + "noches", '{"songs": 1}')
    _set(conn, lacuerda_search.KV_PREFIX + "nandu", '{"at": "2026-10-20", "at": "%s"}' % ago(days=1))
    records.append(gate_record(conn, "asked within 30 days, in either order of its words", "tiza corazón"))
    records.append(gate_record(conn, "asked 31 days ago", "la flaca"))
    records.append(gate_record(conn, "asked 30 days ago to the second, in another zone's notation", "boca vive"))
    records.append(gate_record(conn, "a record that isn't an object", "estopa como camarón"))
    records.append(gate_record(conn, "a record whose time can't be read", "la gaviota"))
    records.append(gate_record(conn, "a record with no time", "500 noches"))
    records.append(gate_record(conn, "a record whose time is written twice", "ñandú"))
    _set(conn, "provider:lacuerda", '{"strikes": 2, "cooldown_until": "%s"}' % stamp(NOW + timedelta(days=2)))
    records.append(gate_record(conn, "asked, though cooling down: what it answered is in the index", "tiza corazón"))

    conn = fresh(directory, "spent")
    _set(conn, "provider:lacuerda", '{"strikes": 1, "cooldown_until": "%s"}' % stamp(NOW + timedelta(hours=1)))
    records.append(gate_record(conn, "cooling down", "corazón de tiza"))
    conn.execute("DELETE FROM kv WHERE key = 'provider:lacuerda'")
    _set(conn, "provider:lacuerda", '{"strikes": 1, "cooldown_until": "%s"}' % ago(seconds=1))
    _event(conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), n=59)
    _event(conn, "lookup:2026-11-03T10:59:00Z", ago(minutes=61), n=5)
    _event(conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), decision="cached")
    _event(conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), provider="ug", n=3)
    _event(conn, "run:2026-11-03T11:30:00Z", ago(minutes=30), n=3)
    records.append(gate_record(conn, "a cooldown over, 59 of the hour's lookups spent", "corazón de tiza"))
    _event(conn, "lookup:2026-11-03T11:59:59Z", ago(hours=1), decision="blocked")
    records.append(gate_record(conn, "the hour's lookups spent, the oldest an hour ago to the second", "corazón de tiza"))
    records.append(gate_record(conn, "the hour's lookups spent, a higher limit", "corazón de tiza", lookup_per_hour=61))

    conn = fresh(directory, "failed")
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        **{key: (ago(minutes=59), "lacuerda: 500: https://acordes.lacuerda.net/busca.php?exp=corazon+tiza"),
           "flaca": (ago(minutes=61), "an hour ago and more")}))
    records.append(gate_record(conn, "its own search failed within the hour", "tiza corazón"))
    records.append(gate_record(conn, "another search's failure", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=50), "first"), b=(ago(minutes=10), "third"), c=(ago(minutes=30), "second"),
        d=(ago(minutes=90), "gone"), e=("not a time", "unread"), f=(None, "none")))
    records.append(gate_record(conn, "three searches failed in the hour", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=50), "1"), b=(ago(minutes=40), "2"), c=(ago(minutes=30), "3"), d=(ago(minutes=20), "4")))
    records.append(gate_record(conn, "four failed: the pause until the second's hour", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=50), "1"), b=(ago(minutes=40), 5), c=(ago(minutes=30), ["x", 1, None, True, 1.5, {"k": "v"}])))
    records.append(gate_record(conn, "the last error a list, read as str reads it", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=50), "1"), b=(ago(minutes=40), {"k": True}), c=(ago(minutes=30), 5)))
    records.append(gate_record(conn, "the last error a number", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(flaca=(ago(minutes=5), None), b=(ago(minutes=40), 0)))
    records.append(gate_record(conn, "its own error none", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=50), "1"), b=(ago(minutes=40), 1e100), c=("2026-11-03T11:05:00.250000+00:00", 2.5)))
    records.append(gate_record(conn, "the pause's end to the microsecond", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=("2026-11-03T13:05:00+01:00", "zone"), b=(ago(minutes=40), "b"), c=("2026-11-03T11:30:00", "naive")))
    records.append(gate_record(conn, "times in another zone and in none", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, '[1, 2]')
    records.append(gate_record(conn, "failures that aren't an object", "la flaca"))
    _set(conn, lacuerda_search.FAILED_KEY, '{"a": 1, "b": {"at": "%s"}, "c": {"at": "%s"}, "d": {"at": "%s"}}'
         % (ago(minutes=1), ago(minutes=2), ago(minutes=3)))
    records.append(gate_record(conn, "failures with no words", "la flaca"))

    conn = fresh(directory, "button")
    _event(conn, SEARCH_RUN + "flaca:2026-11-03T11:30:00Z", ago(minutes=30), n=19)
    _event(conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), n=10)
    records.append(gate_record(conn, "19 of the page's 20 an hour", "corazón de tiza"))
    _event(conn, SEARCH_RUN + "tiza:2026-11-03T11:40:00Z", ago(minutes=20), decision="error")
    records.append(gate_record(conn, "the page's 20 an hour spent", "corazón de tiza"))
    _set(conn, lacuerda_search.FAILED_KEY, _failures(flaca=(ago(minutes=5), "a page cut short")))
    records.append(gate_record(conn, "the page's 20 spent and its own failed", "la flaca"))
    records.append(gate_record(conn, "the page's 20 spent, its own failure aside", "corazón de tiza"))
    return records


def failure_records(directory: Path) -> list[dict[str, Any]]:
    records = []

    def rec(fn: str, case: str, conn: sqlite3.Connection, key: str, error: str | None = None,
            now: datetime = NOW) -> None:
        before = dump_fixture(conn)
        if fn == "record_failure":
            lacuerda_search.record_failure(conn, key, now, error)
        else:
            lacuerda_search._forget_failure(conn, key, now)
        kw: dict[str, Any] = {"key": key, "now": stamp(now)}
        if error is not None:
            kw["error"] = error
        records.append({"fn": f"caracole.lacuerda_search.{fn}", "case": case, "fixture": before, "kw": kw,
                        "out": {"kv": db.kv_get(conn, lacuerda_search.FAILED_KEY)}})

    conn = fresh(directory, "failures")
    rec("record_failure", "the first failure", conn, "corazon-tiza", "lacuerda: 500: https://x")
    rec("record_failure", "another, its words' spaces collapsed", conn, "flaca", "  dos\n\tlíneas   y más ")
    rec("record_failure", "the first again, kept at its place", conn, "corazon-tiza", "otra vez")
    rec("record_failure", "an hour on: the old ones gone", conn, "nandu", "x" * 150 + " " + "ñ" * 100,
        now=NOW + timedelta(minutes=61))
    rec("record_failure", "words past 200 characters cut, by code point", conn, "boca", "😀" * 250)
    rec("_forget_failure", "a failure forgotten", conn, "nandu", now=NOW + timedelta(minutes=61))
    rec("_forget_failure", "one not there", conn, "otra", now=NOW + timedelta(minutes=61))
    conn = fresh(directory, "odd")
    _set(conn, lacuerda_search.FAILED_KEY, _failures(
        a=(ago(minutes=5), 7), b=(ago(minutes=5), None), c=(ago(minutes=500), "gone")))
    rec("record_failure", "errors that aren't texts read as str does", conn, "d", "")
    conn = fresh(directory, "none")
    rec("_forget_failure", "none ever", conn, "x")
    return records


def searches_used_records(directory: Path) -> list[dict[str, Any]]:
    conn = fresh(directory, "used")
    _event(conn, SEARCH_RUN + "flaca:2026-11-03T11:30:00Z", ago(minutes=30), n=3)
    _event(conn, SEARCH_RUN + "x:2026-11-03T11:00:00Z", ago(hours=1))
    _event(conn, SEARCH_RUN + "x:2026-11-03T10:59:00Z", ago(minutes=61))
    _event(conn, SEARCH_RUN + "y:2026-11-03T11:30:00Z", ago(minutes=30), decision="cached")
    _event(conn, SEARCH_RUN + "y:2026-11-03T11:30:00Z", ago(minutes=30), decision="not_modified")
    _event(conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), n=4)
    _event(conn, "LOOKUP:LACUERDA-SEARCH:z", ago(minutes=30))
    fixture_ = dump_fixture(conn)
    return [{"fn": "caracole.lacuerda_search.searches_used", "case": case, "fixture": fixture_,
             "kw": {"now": stamp(now)}, "out": lacuerda_search.searches_used(conn, now)}
            for case, now in [("now", NOW), ("half an hour on", NOW + timedelta(minutes=30)),
                              ("two hours on", NOW + timedelta(hours=2))]]


def answered_records(directory: Path) -> list[dict[str, Any]]:
    conn = fresh(directory, "answered")
    add_song(conn, "Soda Stereo", "De Música Ligera")
    add_song(conn, "Los Imaginarios", "Corazón de Tiza")
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"))
    lacuerda_index.store_artists(conn, "tabs/e/index0.html", [LCArtist("estopa", "Estopa", 160),
                                                              LCArtist("enanitos", "Enanitos Verdes", 40)])
    lacuerda_index.store_artist_page(conn, "estopa", artist_page("Estopa", "estopa",
                                                                 ("como_camaron", "Como Camarón", "RRT-213")))
    lacuerda_index.store_search(conn, SearchAnswer(songs=(
        SearchSong("bunbury", "Enrique Bunbury", lc("lady_blue", "Lady Blue", "R-1")),), stated=1))
    queries = ["de musica ligera", "corazon de tiza", "estopa", "estopa como camaron", "como camaron",
               "enanitos verdes", "lamento boliviano", "lady blue", "bunbury", "nadie sabe", "soda stereo", "fito"]
    return [{"fn": "caracole.lacuerda_search.answered", "case": "a library and an index", "fixture": dump_fixture(conn),
             "args": [queries], "out": [lacuerda_search.answered(conn, q) for q in queries]}]


def test_lacuerda_gate_jsonl(tmp_path):
    records = [*gate_records(tmp_path / "gate"), *failure_records(tmp_path / "failures"),
               *searches_used_records(tmp_path / "used"), *answered_records(tmp_path / "answered")]
    check(LOOKUP / "lacuerda_gate.jsonl", jsonl(records, corpus="lookup/lacuerda_gate", made_by=MADE_BY))


def test_the_gate_says_each_state(tmp_path):
    records = gate_records(tmp_path)
    states = {r["out"]["state"] if r["out"] else None for r in records if r["fn"].endswith(".gate")}
    assert states == {None, *lacuerda_search.STATES}
    assert any(r["out"] and r["out"]["failure"] and not r["out"]["failure"]["own"] for r in records
               if r["fn"].endswith(".gate"))
    answered = answered_records(tmp_path / "a")[0]["out"]
    assert True in answered and False in answered


# --- the search ----------------------------------------------------------------------------------------------


def _page(page: str | dict[str, str], status: int = 200) -> dict[str, Any]:
    return {"status": status, "headers": [["content-type", "text/html; charset=UTF-8"]], "body": body(page)}


def search_scenario(directory: Path, case: str, query: str, *, answer: dict[str, Any] | None = None,
                    cached: tuple[str, dict[str, str]] | None = None, budget: int = 6, setup=None) -> dict[str, Any]:
    """A scenario of ``search``: ``answer`` what LaCuerda answers its one request, ``cached`` its cache's copy
    (``(fetched_at, body)``), each of the query's own address."""
    name = "".join(c if c.isalnum() else "_" for c in case)[:40]
    conn = fresh(directory, name)
    if setup is not None:
        setup(conn)
    url = search_url(query)
    return scenario(conn, None, fn="caracole.lacuerda_search.search", case=case,
                    call=lambda made: lacuerda_search.search(conn, made["lacuerda"], query, NOW),
                    clients={"lacuerda": {"budget": budget, "delay": [0.125, 0.375]}},
                    answers={f"GET {url}": answer} if answer is not None else {},
                    cache={"lacuerda": {f"GET {url}": {"status": 200, "fetched_at": cached[0], "body": cached[1]}}}
                    if cached is not None else None, now=NOW, kw={"query": query}, cache_dir=directory / f"{name}-cache")


def search_records(directory: Path) -> list[dict[str, Any]]:
    whole = _page(fixture_ref("lacuerda/search.html"))
    cut = _page(fixture_ref("lacuerda/search_cut.html"))

    def failures(conn: sqlite3.Connection) -> None:
        _set(conn, lacuerda_search.FAILED_KEY, _failures(
            **{"corazon-tiza": (ago(minutes=10), "cut short"), "flaca": (ago(minutes=20), "kept"),
               "gone": (ago(minutes=70), "old")}))

    def indexed(conn: sqlite3.Connection) -> None:
        lacuerda_index.store_artists(conn, "tabs/i/index0.html", [LCArtist("imaginarios", "Los Imaginarios", 40)])
        lacuerda_index.store_artist_page(conn, "imaginarios", artist_page(
            "Los Imaginarios", "imaginarios", ("corazon_de_tiza", "Corazón de Tiza", "TT-12")))
        conn.execute("UPDATE kv SET value = '0' WHERE key = ?", (lacuerda_index.KEYS_KEY,))

    gaviotas = artists_search_page([("bragas_de_la_gaviota", "Las Bragas de la Gaviota", 1), ("gaviota", "Gaviota", 12)])
    one = search_page(("uno", "Uno", [("tiza", "Tiza", "R-1")]), query="corazon tiza")
    return [
        search_scenario(directory, "a whole answer stored", "corazón de tiza", answer=whole),
        search_scenario(directory, "a failure dropped and the rest kept", "tiza corazon", setup=failures, answer=whole),
        search_scenario(directory, "beside the index's rows, its keys made again first", "corazon de tiza",
                        setup=indexed, answer=whole),
        search_scenario(directory, "an answer of artists", "la gaviota", answer=_page(gaviotas)),
        search_scenario(directory, "no results", "la flaca", answer=_page(search_page(query="flaca"))),
        search_scenario(directory, "a cached answer younger than 30 days asked for no more", "corazón de tiza",
                        cached=(ago(days=29), whole["body"])),
        search_scenario(directory, "a cached answer older than 30 days asked again", "corazón de tiza",
                        cached=(ago(days=31), {"text": "old"}), answer=_page(one)),
        search_scenario(directory, "an old cached answer with the budget spent", "corazón de tiza", budget=0,
                        cached=(ago(days=31), whole["body"])),
        search_scenario(directory, "a cached answer that won't parse asked once more", "corazón de tiza",
                        cached=(ago(days=1), cut["body"]), answer=whole),
        search_scenario(directory, "a page cut short records nothing", "corazón de tiza", setup=failures, answer=cut),
        search_scenario(directory, "a cached page and its fresh copy both cut short", "corazón de tiza",
                        cached=(ago(days=1), cut["body"]), answer=cut),
        search_scenario(directory, "a block records nothing", "corazón de tiza", setup=failures,
                        answer=_page("Forbidden", status=403)),
        search_scenario(directory, "a server's error", "corazón de tiza", answer=_page("x", 500)),
        search_scenario(directory, "a 404 is no answer", "corazón de tiza", answer=_page("x", 404)),
        search_scenario(directory, "no budget", "corazón de tiza", budget=0),
        search_scenario(directory, "a count past a 64-bit integer kept whole", "corazon tiza", answer=_page(
            search_page(("uno", "Uno", [("tiza", "Tiza", "R-1")]), query="corazon tiza", stated=PAST_A_LONG, pages=2))),
    ]


def test_lacuerda_search_jsonl(tmp_path):
    check(LOOKUP / "lacuerda_search.jsonl", jsonl(search_records(tmp_path), corpus="lookup/lacuerda_search",
                                                  made_by=MADE_BY))


def test_the_search_stores_its_answer_or_records_nothing(tmp_path):
    records = search_records(tmp_path)
    stored = records[0]["out"]
    assert stored["requests"] == [f"GET {search_url('corazón de tiza')}"]
    assert set(stored["kv"]) == {lacuerda_index.KEYS_KEY, lacuerda_search.KV_PREFIX + "corazon-tiza",
                                 lacuerda_search.FAILED_KEY}
    assert stored["rows"]["lacuerda_index"]
    raised = {r["case"]: r["raises"]["type"] for r in records if "raises" in r}
    assert raised == {"a page cut short records nothing": "LaCuerdaParseError",
                      "a cached page and its fresh copy both cut short": "LaCuerdaParseError",
                      "a block records nothing": "ProviderBlocked", "a server's error": "ProviderError",
                      "a 404 is no answer": "ProviderError", "an old cached answer with the budget spent":
                      "BudgetExhausted", "no budget": "BudgetExhausted"}
    for r in records:
        if "raises" in r:
            assert not r["after"]["kv"] and not r["after"]["rows"], r["case"]
    assert records[5]["out"]["requests"] == []
    assert len(records[8]["out"]["requests"]) == 1


# --- the sheets (lane lacuerda-sheets) ---------------------------------------------------------------------------

# Every line of these lyrics is in tests/fixtures/lacuerda/version.html's sheet (all invented, as
# tests/test_lacuerda_fetch.py's): with them that sheet is complete, with the eight lines after them half of it.
SHEET_LYRICS = """\
Cruzo la plaza con el café frío
y cuento las luces del tren de las seis
nadie me espera en el andén vacío
guardo tu nombre y no sé qué hacer
Baila la lluvia sobre los tejados
suena la radio de la vecindad
llevo en el bolso tu carta doblada
mañana el puerto se va a despertar
"""
OTHER_LINES = """\
Siete caballos corren hacia el norte
el viento canta coplas de cristal
la madrugada quema mis bolsillos
y las campanas tocan sin final
Un perro viejo duerme en la escalera
las golondrinas vuelven a su hogar
mi abuela teje redes de colores
y el río lento aprende a nadar
"""
HALF_LYRICS = SHEET_LYRICS + OTHER_LINES
ENGLISH_LYRICS = """\
I walk the long road when the city is asleep
and the lights are on in every window of the town
you never told me what the river said to you
so I keep on walking till the morning comes around
"""
SHEETS = LOOKUP / "lacuerda_sheets.jsonl"
COMMANDS = LOOKUP / "commands_lacuerda.jsonl"
ADDED = "2026-10-01T00:00:00Z"
STAMP_SHAPE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
DML_PAGE = f"{BASE_URL}/soda_stereo/de_musica_ligera"
DML_3 = f"{DML_PAGE}-3.shtml"
DML = "De Música Ligera"


def small_artist(name: str | None, *songs: tuple[str, str, str], popular: str | None = None) -> str:
    """An artist page as small as lacuerda.py reads one: its heading, ``(slug, title, lcd)`` per song, and
    ``popular`` its popOrder's list."""
    items = "".join(f"<li lcd='{lcd}'><a href=\"{slug}\">{title} <em>acordes</em></a></li>" for slug, title, lcd in songs)
    heading = f"<div class=bTit><h1>{name}</h1></div>" if name is not None else ""
    script = f"<script>var popOrder = [{popular}];</script>" if popular is not None else ""
    return f"<html><body>{heading}<ul id=b_main>{items}</ul>{script}</body></html>"


def small_version(lines: str) -> str:
    """A version page as small as lacuerda.py reads one: each lyric line under a line of chords."""
    rows = []
    for n, line in enumerate(lines.splitlines()):
        rows += [f"<A>{('Am', 'F', 'C', 'G')[n % 4]}</A>        <A>Dm</A>", line]
    return "<html><body><div id=t_body><PRE>Intro: <A>Am</A>\n\n" + "\n".join(rows) + "\n</PRE></div></body></html>"


def soft_404(slug: str) -> dict[str, Any]:
    return _page(f"aqui llega:../tabs/{slug[0]}/{slug}/index.html")


@contextmanager
def sheets_clock(stamp_: str):
    """songs.py's clock at ``stamp_``, and no info.json (the viewer's, M5's: the phone writes none)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: stamp_), \
            mock.patch("caracole.lacuerda_fetch.write_info", lambda *a, **k: None):
        yield


@contextmanager
def noting(pages: list[str]):
    """Each page a pass stores in LaCuerda's index (an artist's, ``<slug>/``; an answer of its search with rows,
    ``busca.php``), which the phone notes for its next push to the computer (core.index.Reads) and Python doesn't."""
    store_songs, store_search = lacuerda_index.store_songs, lacuerda_index.store_search

    def songs(conn, slug, *args, **kwargs):
        store_songs(conn, slug, *args, **kwargs)
        pages.append(f"{slug}/")

    def search(conn, answer):
        stored = store_search(conn, answer)
        if answer.songs or answer.artists:
            pages.append(lacuerda_index.SEARCH_PAGE)
        return stored

    with mock.patch("caracole.lacuerda_fetch.store_songs", songs), \
            mock.patch("caracole.lacuerda_index.store_search", search):
        yield


def canonical_json(value: Any) -> str:
    from caracole import canonical as c

    return c.dumps(value)


def stats_plain(s) -> dict[str, Any]:
    """A LaCuerdaStats as the records write it: the failures as ``[song id, error's class, its words]``, the songs
    that wait for a shared folder as their error's words."""
    return {"tried": s.tried, "errors": s.errors, "budget_exhausted": s.budget_exhausted,
            "failures": [[song.id, type(e).__name__, str(e)] for song, e in s.failures],
            "kept": s.kept, "missing": s.missing, "shared": [str(e) for e in s.shared]}


def stamped(made: dict[str, Any]) -> None:
    """keep_file's ``created_at``, SQLite's clock: each ``files`` row a pass wrote holds a time of that form now,
    recorded as the record's ``now``, the time the phone's Kept.keepFile is given (tests/test_conformance_ug_fetch.py's
    rule); a table whose rows are then as before is no change."""
    done = made.get("out") or made["after"]
    rows = done["rows"]
    if "files" not in rows:
        return
    before = [r["row"] for r in made["fixture"] if r.get("table") == "files"]
    old = {r["id"]: r for r in before}
    for row in rows["files"]:
        was = old.get(row["id"])
        if was is not None and was["created_at"] == row["created_at"]:
            continue
        assert STAMP_SHAPE.fullmatch(row["created_at"]), row["created_at"]
        at = datetime.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), row["created_at"]
        row["created_at"] = NOW_STAMP
    if rows["files"] == before:
        del rows["files"]


class SheetWorld:
    """A library for one scenario: its database (the phone's tables too), its folder and its overrides.toml, whose
    entries the phone holds as ``phone_overrides`` rows (tests/test_conformance_ug_fetch.py's ``rows_of``)."""

    def __init__(self, tmp: Path, name: str):
        self.dir = tmp / name
        self.conn = fresh(self.dir, "caracole")
        phone_schema(self.conn)
        self.library = self.dir / "library"
        self.library.mkdir()
        self.overrides_file = self.dir / "overrides.toml"
        self.displays: dict[str, str] = {}
        self.records = 0

    def song(self, artist: str = "Soda Stereo", title: str = DML, *, lyrics: str | None = SHEET_LYRICS,
             added: str = ADDED, **fields: Any) -> int:
        from caracole.lyrics import Lyrics
        from caracole.normalize import identity_key
        from caracole.songs import update_song, upsert_song

        with sheets_clock(ADDED):
            song_id, _ = upsert_song(self.conn, artists=[artist], title=title, album=None, duration_ms=213000,
                                     isrc=None, source="wanted", source_id=identity_key(artist, title), added_at=added)
            if lyrics is not None:
                found = Lyrics(plain=lyrics, synced=None, instrumental=False, duration=213.0, lrclib_id=7)
                fields |= {"lyrics_status": "found", "lyrics_json": found.to_json(), "lyrics_at": ADDED}
            if fields:
                update_song(self.conn, song_id, **fields)
        return song_id

    def get(self, song_id: int):
        from caracole.songs import get_song

        return get_song(self.conn, song_id)

    def kept(self, song_id: int, *, provider: str = "ug", tab_id: str = "101", kind: str = "chords",
             coverage: float | None = None, text: str = "Am F C\nla luz del bar\n", version: int = 1,
             files: tuple[str, ...] = ("sheet.txt",), url: str | None = None, raw: dict[str, Any] | None = None,
             pick: bool = True) -> int:
        """A version the song keeps: its files (a sheet.json of it as its provider's own record), its coverage,
        and its pick."""
        from caracole.library import keep_file
        from caracole.songs import refresh_status
        from caracole.versions import SHEET_KINDS, set_coverage, set_picks, upsert_version

        with sheets_clock(ADDED):
            vid = upsert_version(self.conn, provider=provider, tab_id=tab_id, song_id=song_id, slot="sheet", kind=kind,
                                 rating=4.5 if provider == "ug" else 0, votes=20 if provider == "ug" else 0,
                                 version=version, label=None,
                                 url=url or f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw=raw or {},
                                 now=ADDED)
            set_coverage(self.conn, vid, coverage)
            for name in files:
                data = (json.dumps({"provider": provider, "content": text}) + "\n" if name.endswith(".json")
                        else text).encode("utf-8")
                keep_file(self.conn, self.library, song=self.get(song_id), version_id=vid, name=name, data=data,
                          rank=1)
            if pick:
                set_picks(self.conn, song_id, SHEET_KINDS if kind != "auto" else ("auto",), [vid])
            refresh_status(self.conn, song_id, ignored=False)
        self.settle()
        return vid

    def settle(self) -> None:
        """The files' ``created_at`` at the world's time (SQLite's clock wrote them)."""
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))

    def overrides(self, *edits) -> None:
        """Each of ``edits`` writes overrides.toml with overrides.py's writers, ``(writer, display, value)``;
        the phone's rows of it follow."""
        from caracole.overrides import SONG_TABLES, load_overrides, song_entries
        from caracole.normalize import identity_key  # noqa: F401  (song_entries reads keys as written)

        for writer, display, value in edits:
            if value is None:
                writer(self.overrides_file, display)
            else:
                writer(self.overrides_file, display, value)
            self.displays[self.key_of(display)] = display
        o = load_overrides(self.overrides_file)
        self.conn.execute("DELETE FROM phone_overrides")
        keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
        for key in keys:
            entries = song_entries(o, key)
            for table in (*SONG_TABLES, "ignore"):
                if table in entries:
                    self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                                      (table, key, self.displays[key], canonical_json(entries[table])))

    @staticmethod
    def key_of(display: str) -> str:
        from caracole.overrides import override_key

        return override_key(display)

    def load(self):
        from caracole.overrides import load_overrides

        return load_overrides(self.overrides_file)

    def record(self, fn: str, case: str, call, kw: dict[str, Any], answers: dict[str, dict[str, Any]] | None,
               cache: dict[str, Any] | None = None, budget: int = 6, run: str | None = None,
               library: bool = True) -> dict[str, Any]:
        self.records += 1
        pages: list[str] = []
        with sheets_clock(NOW_STAMP), noting(pages):
            made = scenario(self.conn, self.library if library else None, fn=fn, case=case, call=call, kw=kw, now=NOW,
                            clients={"lacuerda": {"budget": budget, "delay": [0.125, 0.375]}}, answers=answers or {},
                            cache={"lacuerda": cache} if cache else None, run=run,
                            cache_dir=self.dir / f"cache-{self.records}")
        made["noted"] = list(dict.fromkeys(pages))
        stamped(made)
        done = made.get("out") or made["after"]
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}
        if run is not None:
            made["run"] = run
        self.settle()
        return made

    def sheets(self, case: str, song_id: int, answers: dict[str, dict[str, Any]] | None = None, *,
               cache: dict[str, Any] | None = None, budget: int = 6, rank: dict[str, Any] | None = None,
               only: list[int] | None = None) -> dict[str, Any]:
        from caracole.config import RankPolicy
        from caracole.lacuerda_fetch import lacuerda_sheets

        policy = replace(RankPolicy(), **(rank or {}))
        asked = sorted(only or [song_id])

        def call(made):
            return stats_plain(lacuerda_sheets(self.conn, made["lacuerda"], self.library, policy, NOW,
                                               overrides=self.load(), only=set(asked)))

        kw: dict[str, Any] = {"only": asked}
        if rank:
            kw["rank"] = rank
        return self.record("caracole.lacuerda_fetch.lacuerda_sheets", case, call, kw, answers, cache, budget)

    def artist_page(self, case: str, artist: str, answers: dict[str, dict[str, Any]] | None = None, *,
                    cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        from caracole.lacuerda_fetch import read_artist_page

        def call(made):
            found = read_artist_page(self.conn, made["lacuerda"], artist, NOW)
            return list(found) if found is not None else None

        return self.record("caracole.lacuerda_fetch.read_artist_page", case, call, {"artist": artist}, answers, cache,
                           budget, library=False)

    def stage(self, case: str, song_id: int, answers: dict[str, dict[str, Any]] | None = None, *,
              cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        """get.py's lacuerda stage for the song, ``_Lookup.lacuerda`` (the sheet stage's too, for a pick): its
        ``[state, detail]``, or what its work raises, its asking the record's client alone, so that the words are
        the work's own (the envelope's are lane lookup's vectors', asking.jsonl)."""
        from types import SimpleNamespace

        from caracole import get
        from caracole.config import RankPolicy

        def call(made):
            song = self.get(song_id)
            lk = get._Lookup(SimpleNamespace(library_dir=self.library, rank=RankPolicy()),
                             get.LookupRequest(song.artist, song.title), get.Progress(), runner=None, now=NOW,
                             clock=lambda: 0.0)
            lk.conn, lk.song, lk.overrides = self.conn, song, self.load()
            lk.asking = lk.after_the_sheet = lambda provider, work: work(made["lacuerda"])
            out = lk.lacuerda()
            return list(out) if isinstance(out, tuple) else ["done", out]

        return self.record("caracole.get._Lookup.lacuerda", case, call, {"song": song_id}, answers, cache, budget)

    def listing(self, *artists: tuple[str, str, int]) -> None:
        """LaCuerda's listings of every artist, as the computer's index holds them, with these artists."""
        lacuerda_index.store_artists(self.conn, "tabs/s/index0.html", [LCArtist(*a) for a in artists])


def cached(body_: Any, fetched: str, status: int = 200) -> dict[str, Any]:
    return {"status": status, "fetched_at": fetched, "body": body(body_) if isinstance(body_, str) else body_}


def sheet_records(directory: Path) -> list[dict[str, Any]]:
    from caracole.overrides import add_ignore, add_lacuerda, add_pin

    soda = _page(fixture_ref("lacuerda/artist.html"))
    dml3 = _page(fixture_ref("lacuerda/version.html"))
    records: list[dict[str, Any]] = []
    n = iter(range(1000))

    def world() -> SheetWorld:
        return SheetWorld(directory, f"w{next(n)}")

    # Asked, chosen and kept.
    w = world()
    s = w.song()
    records.append(w.sheets("a Spanish song with no sheet: its artist's page, the best acordes version kept", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=None)
    records.append(w.sheets("no lyrics: its Spanish title decides, the sheet kept of no coverage", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    records.append(w.sheets("a sheet of half the lyrics is kept where none is", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    records.append(w.sheets("completeness by the rank policy", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3},
                            rank={"coverage_threshold": 1.0, "line_match": 99}))
    w = world()
    w.listing(("soda_stereo_oficial", "Soda Stereo", 120), ("soda", "Soda Stereo", 3), ("otra", "Otra Banda", 9))
    s = w.song()
    records.append(w.sheets("the slugs LaCuerda's listings give the name first, most songs first, then those built "
                            "from it; a 404 and its 'aqui llega:' move on", s,
                            {f"GET {BASE_URL}/soda_stereo_oficial/": _page("x", 404), f"GET {BASE_URL}/soda/": soft_404("soda"),
                             f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    matador = "Me quedo con la luz de la mañana\ny el ruido de la calle que se va\n"
    s = w.song("Los Fabulosos Cadillacs", "Matador", lyrics=matador)
    fab = small_artist("Los Fabulosos Cadillacs", ("matador", "Matador", "TR-21"), ("vasos_vacios", "Vasos Vacíos", "R-1"),
                       popular="1,0")
    records.append(w.sheets("the second slug built from the name answers, its songs stored with their popularity",
                            s, {f"GET {BASE_URL}/fabulosos_cadillacs/": soft_404("fabulosos_cadillacs"),
                                f"GET {BASE_URL}/los_fabulosos_cadillacs/": _page(fab),
                                f"GET {BASE_URL}/los_fabulosos_cadillacs/matador-2.shtml": _page(small_version(matador))}))
    w = world()
    s = w.song("Estopa", "Como Camarón", lyrics=None)
    records.append(w.sheets("an artist page with no name in its heading: the slug names them", s,
                            {f"GET {BASE_URL}/estopa/": _page(small_artist(None, ("como_camaron", "Como Camarón",
                                                                                     "RT-12"))),
                             f"GET {BASE_URL}/estopa/como_camaron.shtml": _page(small_version("Como camarón\n"))}))

    # Misses, asked again after 30 days.
    w = world()
    s = w.song("Nadie Conocido", "Canción de Nadie", lyrics=None)
    records.append(w.sheets("an artist LaCuerda doesn't have is a miss", s,
                            {f"GET {BASE_URL}/nadie_conocido/": soft_404("nadie_conocido")}))
    w = world()
    s = w.song("Soda Stereo", "Canción Inexistente", lyrics=None)
    records.append(w.sheets("a title the artist's page lacks is a miss", s, {f"GET {SODA}": soda}))
    w = world()
    s = w.song("Soda Stereo", "Telarañas")
    records.append(w.sheets("a song with no acordes version is a miss", s, {f"GET {SODA}": soda}))
    w = world()
    s = w.song()
    records.append(w.sheets("a version page that is gone is a miss", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": _page(fixture_ref("lacuerda/not_found.html"), 404)}))
    w = world()
    s = w.song(lacuerda_checked_at="2026-09-01T00:00:00Z")
    records.append(w.sheets("a miss asked again after 30 days, the artist's page from a fresh copy", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3},
                            cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-09-01T00:00:00Z")}))

    # The cache.
    w = world()
    s = w.song()
    records.append(w.sheets("an artist's page cached within 30 days, the version page from the cache too", s,
                            cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-10-20T00:00:00Z"),
                                   f"GET {DML_3}": cached(fixture_ref("lacuerda/version.html"), "2026-10-20T00:00:00Z")}))
    w = world()
    s = w.song()
    records.append(w.sheets("a stale artist's page once the budget is spent is no answer", s, budget=0,
                            cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-09-01T00:00:00Z")}))
    w = world()
    s = w.song()
    records.append(w.sheets("no budget: nothing asked, the song left for later", s, budget=0))
    w = world()
    s = w.song()
    records.append(w.sheets("a cached version page that won't parse is asked for once more", s,
                            {f"GET {DML_3}": dml3},
                            cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-10-20T00:00:00Z"),
                                   f"GET {DML_3}": cached("<html><body>Mantenimiento</body></html>",
                                                          "2026-10-20T00:00:00Z")}))
    w = world()
    s = w.song()
    records.append(w.sheets("a cached artist's page that won't parse is asked for once more", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3},
                            cache={f"GET {SODA}": cached("<html><body>Mantenimiento</body></html>",
                                                         "2026-10-20T00:00:00Z")}))

    # Errors are never misses.
    w = world()
    s = w.song()
    records.append(w.sheets("an artist's page without its list is an error", s,
                            {f"GET {SODA}": _page(fixture_ref("lacuerda/song.html"))}))
    w = world()
    s = w.song()
    records.append(w.sheets("a version page without its sheet is an error", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": _page(fixture_ref("lacuerda/song.html"))}))
    w = world()
    s = w.song()
    records.append(w.sheets("a server's error leaves the song for later", s, {f"GET {SODA}": _page("x", 500)}))
    w = world()
    s = w.song()
    records.append(w.sheets("a block is raised, nothing marked", s, {f"GET {SODA}": _page("Forbidden", 403)}))

    # Which songs are tried.
    w = world()
    s = w.song("Oasis", "Wonderwall", lyrics=ENGLISH_LYRICS)
    records.append(w.sheets("an English song isn't tried", s))
    w = world()
    s = w.song(lyrics=ENGLISH_LYRICS)
    records.append(w.sheets("English lyrics outweigh a Spanish title", s))
    w = world()
    s = w.song(lacuerda_checked_at="2026-10-20T00:00:00Z")
    records.append(w.sheets("asked within 30 days: not tried", s))
    w = world()
    s = w.song()
    w.overrides((add_ignore, "Soda Stereo - De Música Ligera", None))
    records.append(w.sheets("ignored in overrides.toml: not tried", s))
    w = world()
    s = w.song(status="ignored")
    records.append(w.sheets("an ignored song isn't tried", s))
    w = world()
    s = w.song()
    w.kept(s, coverage=1.0)
    records.append(w.sheets("a complete sheet kept: not tried", s))
    w = world()
    other = w.song("Soda Stereo", "Persiana Americana", added="2026-10-02T00:00:00Z")
    s = w.song()
    records.append(w.sheets("the lookup's song alone", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    assert other

    # Keeping it, or not.
    w = world()
    s = w.song()
    w.kept(s, coverage=0.5, files=("sheet.txt", "sheet.json"))
    records.append(w.sheets("a complete sheet replaces a partial one", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    w.kept(s, coverage=0.25, files=("sheet.txt", "sheet.json"))
    records.append(w.sheets("a partial sheet that covers more replaces a partial one", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    w.kept(s, coverage=0.75, files=("sheet.txt", "sheet.json"))
    records.append(w.sheets("a partial sheet that covers less leaves the kept one, its version recorded", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    w.kept(s, coverage=None, files=("sheet.txt", "sheet.json"))
    records.append(w.sheets("a complete sheet replaces one of unknown coverage", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=None)
    w.kept(s, coverage=None, files=("sheet.txt", "sheet.json"))
    records.append(w.sheets("without lyrics a kept sheet is never replaced", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    w.kept(s, provider="auto", tab_id="auto", kind="auto", files=("sheet (auto).txt",), url="file:///audio.m4a")
    records.append(w.sheets("a complete sheet retires the auto sheet", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    w.kept(s, provider="auto", tab_id="auto", kind="auto", files=("sheet (auto).txt",), url="file:///audio.m4a")
    records.append(w.sheets("a partial sheet is kept beside the auto sheet", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    w.kept(s, provider="auto", tab_id="auto", kind="auto", files=("sheet (auto).txt",), url="file:///audio.m4a")
    _lacuerda_sheet_of(w, s)
    _lyrics(w, s, SHEET_LYRICS)
    records.append(w.sheets("the partial sheet kept, rescored complete once the lyrics are its own: the auto sheet "
                            "goes", s, cache=_cached_dml()))
    w = world()
    s = w.song(lyrics=None)
    _lacuerda_sheet_of(w, s)
    _lyrics(w, s, SHEET_LYRICS)
    records.append(w.sheets("the sheet kept while the lyrics were pending is rescored, not written again", s,
                            cache=_cached_dml()))
    w = world()
    s = w.song()
    _lacuerda_sheet_of(w, s, checked="2026-10-30T00:00:00Z")
    (w.library / "Soda Stereo" / DML / "sheet.txt").unlink()
    records.append(w.sheets("a kept LaCuerda sheet the library lost is written again, asked about lately or not", s,
                            cache=_cached_dml()))
    w = world()
    s = w.song()
    _lacuerda_sheet_of(w, s, checked="2026-10-30T00:00:00Z")
    (w.library / "Soda Stereo" / DML / "sheet.json").write_bytes(b"")
    records.append(w.sheets("a kept sheet cut short counts as lost", s, cache=_cached_dml()))

    # A song whose sheet would go where another song keeps one.
    live = ("Persiana Americana, en vivo en el estadio de River Plate para la gira de despedida del grupo en 2007, "
            "con orquesta y coros, toma")
    w = world()
    one = w.song(title=f"{live} uno", added="2026-10-03T00:00:00Z")
    w.kept(one, coverage=1.0, files=("sheet.txt", "sheet.json"))
    two = w.song(title=f"{live} dos", added="2026-10-02T00:00:00Z")
    page = small_artist("Soda Stereo", ("persiana_dos", f"{live} dos", "R-1"))
    records.append(w.sheets("a sheet that would go where another song keeps one waits", two,
                            {f"GET {SODA}": _page(page), f"GET {BASE_URL}/soda_stereo/persiana_dos.shtml": dml3}))

    # Your pick.
    w = world()
    s = w.song(lyrics=ENGLISH_LYRICS)
    w.kept(s, coverage=1.0, files=("sheet.txt", "sheet.json"))
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_3))
    records.append(w.sheets("the version you picked is kept whatever the song's language and its coverage", s,
                            {f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=ENGLISH_LYRICS)
    w.conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, songs, "
                   "versions, acordes, popular, page) VALUES (?, 'soda_stereo', 'Soda Stereo', 'soda-stereo', ?, "
                   "'musica-ligera', 0, 'RHRTTTDTB', 3, 0, 'soda_stereo/')", ("soda_stereo/de_musica_ligera", DML))
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_PAGE))
    records.append(w.sheets("a song you picked: its best acordes version as the index names it", s,
                            {f"GET {DML_3}": dml3}))
    w = world()
    s = w.song(lyrics=ENGLISH_LYRICS)
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_PAGE))
    records.append(w.sheets("a song you picked the index lacks: its artist's page first", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    w.conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, songs, "
                   "versions, acordes, popular, page) VALUES ('soda_stereo/disco_eterno_unplugged', 'soda_stereo', "
                   "'Soda Stereo', 'soda-stereo', 'Disco eterno (unplugged)', 'disco-eterno', 0, 'T', 0, NULL, "
                   "'soda_stereo/')")
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", f"{BASE_URL}/soda_stereo/disco_eterno_unplugged"))
    records.append(w.sheets("a song you picked with no acordes version, as the index says, is a miss", s))
    w = world()
    s = w.song()
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", f"{BASE_URL}/soda_stereo/de_musica_ligera-9.shtml"))
    records.append(w.sheets("a version you picked that is gone is a miss", s,
                            {f"GET {BASE_URL}/soda_stereo/de_musica_ligera-9.shtml": _page("x", 404)}))
    w = world()
    s = w.song(lacuerda_checked_at="2026-10-20T00:00:00Z")
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_3))
    records.append(w.sheets("a pick asked about this month waits", s))
    w = world()
    s = w.song()
    w.kept(s, tab_id="85053", coverage=0.5, files=("sheet.txt", "sheet.json"))
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_3),
                (add_pin, "Soda Stereo - De Música Ligera", ["https://tabs.ultimate-guitar.com/tab/85053"]))
    records.append(w.sheets("a sheet you pinned on Ultimate Guitar wins over your pick", s))
    w = world()
    s = w.song()
    w.kept(s, tab_id="85053", coverage=0.5, files=("sheet.txt", "sheet.json"))
    w.overrides((add_pin, "Soda Stereo - De Música Ligera", ["https://tabs.ultimate-guitar.com/tab/777"]))
    records.append(w.sheets("a pin of another tab leaves the sheet open to LaCuerda", s,
                            {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    _lacuerda_sheet_of(w, s)
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_PAGE))
    records.append(w.sheets("the pick's sheet kept already: never asked again", s))
    return records


def _cached_dml() -> dict[str, Any]:
    """Soda Stereo's page and De Música Ligera's version 3, as the cache holds them since 20 October."""
    return {f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-10-20T00:00:00Z"),
            f"GET {DML_3}": cached(fixture_ref("lacuerda/version.html"), "2026-10-20T00:00:00Z")}


def _lyrics(w: SheetWorld, song_id: int, plain: str) -> None:
    """The song's lyrics now ``plain``."""
    from caracole.lyrics import Lyrics
    from caracole.songs import update_song

    with sheets_clock(ADDED):
        update_song(w.conn, song_id, lyrics_status="found", lyrics_at=ADDED,
                    lyrics_json=Lyrics(plain=plain, synced=None, instrumental=False, duration=213.0,
                                       lrclib_id=7).to_json())


def _lacuerda_sheet_of(w: SheetWorld, song_id: int, checked: str = "2026-09-01T00:00:00Z") -> int:
    """The song keeping version.html's sheet as a pass keeps it (asked for, from the cache, at ``checked``)."""
    from caracole.config import RankPolicy
    from caracole.lacuerda_fetch import lacuerda_sheets
    from caracole.songs import update_song

    pages = {f"{SODA}": fixture("artist.html"), DML_3: fixture("version.html")}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages[str(request.url)], headers=[("content-type", "text/html")])

    from caracole.http import PoliteClient

    client = PoliteClient("lacuerda", replace(config.DEFAULT_PROVIDERS["lacuerda"], budget=10, delay=(0.0, 0.0)),
                          w.dir / "setup-cache", user_agent=config.DEFAULT_USER_AGENT,
                          transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0,
                          wall_clock=lambda: NOW)
    try:
        with sheets_clock(ADDED):
            stats = lacuerda_sheets(w.conn, client, w.library, RankPolicy(), NOW, overrides=w.load(), only={song_id})
            update_song(w.conn, song_id, lacuerda_checked_at=checked)
    finally:
        client.close()
    assert stats.kept == 1, stats
    w.settle()
    w.conn.execute("UPDATE versions SET fetched_at = ?", (ADDED,))
    return stats.kept


def artist_read_records(directory: Path) -> list[dict[str, Any]]:
    soda = _page(fixture_ref("lacuerda/artist.html"))
    w = SheetWorld(directory, "artist-by-slug")
    by_slug = w.artist_page("an artist's page by its slug", "soda_stereo", {f"GET {SODA}": soda})
    w = SheetWorld(directory, "artist-by-name")
    w.listing(("soda_stereo_oficial", "Soda Stereo", 120))
    by_name = w.artist_page("by their name: the listings' slug first, then the slugs built from it", "Soda Stereo",
                            {f"GET {BASE_URL}/soda_stereo_oficial/": soft_404("soda_stereo_oficial"),
                             f"GET {SODA}": soda})
    w = SheetWorld(directory, "artist-slug-first")
    w.listing(("estopa_oficial", "Estopa", 50))
    slug_first = w.artist_page("a slug written as one asked first, before the listings'", "estopa",
                               {f"GET {BASE_URL}/estopa/": _page(small_artist(
                                   "Estopa", ("como_camaron", "Como Camarón", "RT-12"),
                                   ("como_camaron", "Como Camarón (bis)", "R-1")))})
    w = SheetWorld(directory, "artist-none")
    none = w.artist_page("no page by any of their slugs", "Los Nadie",
                         {f"GET {BASE_URL}/nadie/": soft_404("nadie"), f"GET {BASE_URL}/los_nadie/": _page("x", 404)})
    w = SheetWorld(directory, "artist-cached")
    from_cache = w.artist_page("from the cache within 30 days", "Soda Stereo",
                               cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"), "2026-10-20T00:00:00Z")})
    w = SheetWorld(directory, "artist-blocked")
    blocked = w.artist_page("a block is raised", "soda_stereo", {f"GET {SODA}": _page("Forbidden", 403)})
    w = SheetWorld(directory, "artist-unreadable")
    unreadable = w.artist_page("a page that won't parse is an error", "soda_stereo",
                               {f"GET {SODA}": _page(fixture_ref("lacuerda/song.html"))})
    w = SheetWorld(directory, "artist-spent")
    spent = w.artist_page("no budget", "soda_stereo", budget=0)
    return [by_slug, by_name, slug_first, none, from_cache, blocked, unreadable, spent]


def stage_records(directory: Path) -> list[dict[str, Any]]:
    """get.py's words for what LaCuerda's pass came to, the lacuerda stage's and a pick's in the sheet stage: each
    of ``lacuerda()``'s own ends, and the work's raises its asking turns into the envelope's words."""
    from caracole.overrides import add_lacuerda, add_pin

    soda = _page(fixture_ref("lacuerda/artist.html"))
    dml3 = _page(fixture_ref("lacuerda/version.html"))
    pick = (add_lacuerda, "Soda Stereo - De Música Ligera", DML_3)
    records: list[dict[str, Any]] = []
    n = iter(range(1000))

    def world() -> SheetWorld:
        return SheetWorld(directory, f"s{next(n)}")

    w = world()
    s = w.song()
    records.append(w.stage("a sheet kept", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    w = world()
    s = w.song("Nadie Conocido", "Canción de Nadie", lyrics=None)
    records.append(w.stage("an artist LaCuerda doesn't have", s,
                           {f"GET {BASE_URL}/nadie_conocido/": soft_404("nadie_conocido")}))
    w = world()
    s = w.song(lyrics=HALF_LYRICS)
    w.kept(s, coverage=0.75, files=("sheet.txt", "sheet.json"))
    records.append(w.stage("a sheet that covers less than the one kept", s, {f"GET {SODA}": soda, f"GET {DML_3}": dml3}))
    live = ("Persiana Americana, en vivo en el estadio de River Plate para la gira de despedida del grupo en 2007, "
            "con orquesta y coros, toma")
    w = world()
    one = w.song(title=f"{live} uno", added="2026-10-03T00:00:00Z")
    w.kept(one, coverage=1.0, files=("sheet.txt", "sheet.json"))
    two = w.song(title=f"{live} dos", added="2026-10-02T00:00:00Z")
    page = small_artist("Soda Stereo", ("persiana_dos", f"{live} dos", "R-1"))
    records.append(w.stage("a sheet that would go where another song keeps one", two,
                           {f"GET {SODA}": _page(page), f"GET {BASE_URL}/soda_stereo/persiana_dos.shtml": dml3}))
    w = world()
    s = w.song("Oasis", "Wonderwall", lyrics=ENGLISH_LYRICS)
    records.append(w.stage("not a song for LaCuerda", s))
    w = world()
    s = w.song(lyrics=ENGLISH_LYRICS)
    w.kept(s, coverage=1.0, files=("sheet.txt", "sheet.json"))
    w.overrides(pick)
    records.append(w.stage("your pick kept as the sheet", s, {f"GET {DML_3}": dml3}))
    w = world()
    s = w.song()
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", f"{BASE_URL}/soda_stereo/de_musica_ligera-9.shtml"))
    records.append(w.stage("your pick gone", s, {f"GET {BASE_URL}/soda_stereo/de_musica_ligera-9.shtml": _page("x", 404)}))
    w = world()
    s = w.song()
    _lacuerda_sheet_of(w, s)
    w.overrides((add_lacuerda, "Soda Stereo - De Música Ligera", DML_PAGE))
    records.append(w.stage("your pick is the sheet already", s))
    w = world()
    s = w.song()
    w.kept(s, tab_id="85053", coverage=0.5, files=("sheet.txt", "sheet.json"))
    w.overrides(pick, (add_pin, "Soda Stereo - De Música Ligera", ["https://tabs.ultimate-guitar.com/tab/85053"]))
    records.append(w.stage("your pick waits for the tab you pinned", s))
    w = world()
    s = w.song(lacuerda_checked_at="2026-10-20T00:00:00Z")
    w.overrides(pick)
    records.append(w.stage("your pick waits: asked this month", s))
    w = world()
    s = w.song(status="ignored")
    w.overrides(pick)
    records.append(w.stage("your pick waits for the nightly run", s))
    w = world()
    s = w.song()
    records.append(w.stage("no budget", s, budget=0))
    w = world()
    s = w.song()
    records.append(w.stage("a server's error", s, {f"GET {SODA}": _page("x", 500)}))
    w = world()
    s = w.song()
    records.append(w.stage("a block", s, {f"GET {SODA}": _page("Forbidden", 403)}))
    return records


def test_lacuerda_sheets_jsonl(tmp_path):
    records = [*sheet_records(tmp_path / "sheets"), *artist_read_records(tmp_path / "artists"),
               *stage_records(tmp_path / "stages")]
    check(SHEETS, jsonl(records, corpus="lookup/lacuerda_sheets", made_by=MADE_BY))


def test_the_stage_says_each_of_its_ends(tmp_path):
    records = stage_records(tmp_path / "stages")
    said = {tuple(r["out"]["result"]) for r in records if "out" in r}
    assert said == {
        ("done", "sheet kept from LaCuerda"), ("done", "not on LaCuerda"), ("done", "kept what it had"),
        ("skipped", "not for LaCuerda: not Spanish, a full sheet already, or asked this month"),
        ("done", "your LaCuerda pick is the sheet already"),
        ("skipped", "your pinned UG tab is kept over your LaCuerda pick"),
        ("skipped", "your LaCuerda pick waits: asked this month already"),
        ("skipped", "your LaCuerda pick comes tonight"),
    }, said
    assert {r["raises"]["type"] for r in records if "raises" in r} == {"BudgetExhausted", "ProviderError",
                                                                        "ProviderBlocked"}
    shared = next(r for r in records if r["case"] == "a sheet that would go where another song keeps one")
    assert not shared["out"]["library"]  # nothing written over the other song's sheet


def test_the_sheets_cover_each_outcome(tmp_path):
    records = sheet_records(tmp_path / "sheets")
    results = [r["out"]["result"] for r in records if "out" in r]
    assert sum(r["kept"] for r in results) >= 20 and sum(r["missing"] for r in results) >= 6
    assert any(r["shared"] for r in results) and any(r["failures"] for r in results)
    assert any(r["budget_exhausted"] for r in results)
    assert {r["raises"]["type"] for r in records if "raises" in r} == {"ProviderBlocked"}
    noted = [r["noted"] for r in records]
    assert ["soda_stereo_oficial/", "soda/", "soda_stereo/"] not in noted  # a 404 and its "aqui llega:" store nothing
    assert any(n == ["soda_stereo/"] for n in noted) and any(not n for n in noted)
    written = [r["out"]["library"] for r in records if "out" in r and r["out"]["library"]]
    assert any(set(w) == {"Soda Stereo/De Música Ligera/sheet.json", "Soda Stereo/De Música Ligera/sheet.txt"}
               for w in written)


# --- the commands: lacuerda --artist and --search (lane lacuerda-sheets) ----------------------------------------


class _Kept:
    """The record's client as ``make_client`` hands it to the command, its policy the command's (the lookup's pace,
    and its budget, which the record's is), its close left to the record."""

    def __init__(self, client, policy):
        assert client.policy.budget == policy.budget and tuple(client.policy.delay) == tuple(policy.delay), policy
        client.policy = policy
        self._client = client

    def __getattr__(self, name):
        return getattr(self._client, name)

    def close(self) -> None:
        pass


class _Open:
    """The world's connection, which the command's ``closing(open_db(cfg))`` leaves open."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def command_record(w: SheetWorld, case: str, command: str, answers: dict[str, dict[str, Any]] | None = None, *,
                   cache: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    """``caracole lacuerda --artist NAME`` (``command`` "artist", ``kw.artist``) or ``--search QUERY --progress``
    (``search``, ``kw.query`` and ``kw.auto``) as caracole serve queues it, at the record's now, through the record's
    client, whose budget is the one ``make_client`` gives the command (the lookup's what this hour's lookups leave; the
    search's one request) and whose events are logged under the command's run; ``out.result`` its ``{"lines"}``, every
    line it prints, the last one its runner's. The computer's search first stores the artist pages its HTTP cache
    holds (``backfill_cached``), of a folder of its own here, as the phone stores each page as it reads it."""
    from contextlib import nullcontext

    from caracole.commands import _common
    from caracole.commands import lyrics as cmd

    cfg = types.SimpleNamespace(provider=lambda name: config.DEFAULT_PROVIDERS[name], cache_dir=w.dir / "no-cache")
    search = command == "search"
    run = f"{SEARCH_RUN}{NOW_STAMP}" if search else None
    budget = 1 if search else _common.lookup_policy(cfg, w.conn, "lacuerda", NOW).budget

    def call(made):
        lines: list[str] = []

        def make_client(cfg_, conn, provider, run_id, *, policy=None, interactive=False):
            assert provider == "lacuerda" and interactive and run_id == (run or f"lookup:{NOW_STAMP}"), run_id
            return _Kept(made["lacuerda"], policy or _common.lookup_policy(cfg_, w.conn, provider, NOW))

        with mock.patch.object(cmd, "exclusive", lambda *a, **k: nullcontext()), \
                mock.patch.object(cmd, "open_db", lambda cfg_: _Open(w.conn)), \
                mock.patch.object(cmd, "make_client", make_client), \
                mock.patch.object(cmd, "utcnow", lambda: NOW), \
                mock.patch("typer.echo", lines.append):
            if search:
                cmd._lacuerda_search(cfg, kw["query"], auto=kw["auto"], progress=True)
            else:
                cmd._lacuerda_artist(cfg, kw["artist"])
        return {"lines": lines}

    return w.record(f"caracole.commands.lyrics._lacuerda_{command}", case, call, {"command": command, **kw}, answers,
                    cache, budget, run=run, library=False)


def _cooling(w: SheetWorld) -> None:
    _set(w.conn, "provider:lacuerda", '{"strikes": 1, "cooldown_until": "%s", "last_block": "%s"}'
         % (stamp(NOW + timedelta(hours=20)), ago(hours=4)))


def _hour_spent(w: SheetWorld, used: int = 60) -> None:
    """``used`` requests every lookup of the last hour sent LaCuerda."""
    _event(w.conn, "lookup:2026-11-03T11:30:00Z", ago(minutes=30), n=used)


def command_records(directory: Path) -> list[dict[str, Any]]:
    soda = _page(fixture_ref("lacuerda/artist.html"))
    whole = _page(fixture_ref("lacuerda/search.html"))
    records: list[dict[str, Any]] = []
    n = iter(range(1000))

    def world() -> SheetWorld:
        return SheetWorld(directory, f"c{next(n)}")

    # lacuerda --artist
    w = world()
    records.append(command_record(w, "read by its slug: its name as its page heads it", "artist",
                                  {f"GET {SODA}": soda}, artist="soda_stereo"))
    w = world()
    w.listing(("soda_stereo_oficial", "Soda Stereo", 120))
    records.append(command_record(w, "read by their name: the listings' slug, then those built from it", "artist",
                                  {f"GET {BASE_URL}/soda_stereo_oficial/": _page("x", 404), f"GET {SODA}": soda},
                                  artist="Soda Stereo"))
    w = world()
    records.append(command_record(w, "a page with no name in its heading: the slug names them", "artist",
                                  {f"GET {BASE_URL}/estopa/": _page(small_artist(
                                      None, ("como_camaron", "Como Camarón", "RT-12"), ("tu_calorro", "Tu Calorro",
                                                                                        "T-1")))}, artist="estopa"))
    w = world()
    records.append(command_record(w, "one song", "artist", {f"GET {BASE_URL}/estopa/": _page(small_artist(
        "Estopa", ("como_camaron", "Como Camarón", "RT-12")))}, artist="estopa"))
    w = world()
    records.append(command_record(w, "no page by any of their slugs: not found", "artist",
                                  {f"GET {BASE_URL}/nadie/": soft_404("nadie"),
                                   f"GET {BASE_URL}/los_nadie/": _page("x", 404)}, artist="Los Nadie"))
    w = world()
    records.append(command_record(w, "from the cache: read, nothing sent, no good run recorded", "artist",
                                  cache={f"GET {SODA}": cached(fixture_ref("lacuerda/artist.html"),
                                                               "2026-10-20T00:00:00Z")}, artist="soda_stereo"))
    w = world()
    _cooling(w)
    records.append(command_record(w, "cooling down after a block: not read, nothing asked", "artist",
                                  artist="soda_stereo"))
    w = world()
    records.append(command_record(w, "a block: its cooldown begun", "artist", {f"GET {SODA}": _page("Forbidden", 403)},
                                  artist="soda_stereo"))
    w = world()
    records.append(command_record(w, "a server's error: counted, nothing changed", "artist",
                                  {f"GET {SODA}": _page("x", 500)}, artist="soda_stereo"))
    w = world()
    records.append(command_record(w, "a page that won't parse is an error", "artist",
                                  {f"GET {SODA}": _page(fixture_ref("lacuerda/song.html"))}, artist="soda_stereo"))
    w = world()
    slugs = [f"soda_{i}" for i in range(7)]
    w.listing(*[(s, "Soda", 100 - i) for i, s in enumerate(slugs)])
    records.append(command_record(w, "the lookup's requests spent on slugs LaCuerda doesn't have", "artist",
                                  {f"GET {BASE_URL}/{s}/": _page("x", 404) for s in slugs[:6]}, artist="Soda"))
    w = world()
    _hour_spent(w)
    records.append(command_record(w, "this hour's lookup requests spent", "artist", artist="soda_stereo"))
    w = world()
    _hour_spent(w, 59)
    w.listing(("soda_stereo_oficial", "Soda Stereo", 120))
    records.append(command_record(w, "what this hour leaves spent before the page", "artist",
                                  {f"GET {BASE_URL}/soda_stereo_oficial/": _page("x", 404)}, artist="Soda Stereo"))

    # lacuerda --search --progress
    tiza = "corazón de tiza"
    key = lacuerda_search.query_key(tiza)
    w = world()
    records.append(command_record(w, "no word of four letters: nothing asked", "search", query="sol y luz", auto=True))
    w = world()
    records.append(command_record(w, "songs found, in the index now", "search",
                                  {f"GET {search_url(tiza)}": whole}, query=tiza, auto=True))
    w = world()
    records.append(command_record(w, "more songs than it shows", "search", {f"GET {search_url(tiza)}": _page(search_page(
        ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]),
        ("otros", "Otros", [("tiza", "Tiza", "R-1")]), stated=40, pages=3))}, query=tiza, auto=False))
    w = world()
    records.append(command_record(w, "a count past a 64-bit integer, said whole", "search",
                                  {f"GET {search_url(tiza)}": _page(search_page(
                                      ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]),
                                      stated=PAST_A_LONG, pages=2))}, query=tiza, auto=False))
    w = world()
    gaviotas = artists_search_page([("bragas_de_la_gaviota", "Las Bragas de la Gaviota", 1), ("gaviota", "Gaviota", 12)])
    records.append(command_record(w, "artists alone", "search", {f"GET {search_url('la gaviota')}": _page(gaviotas)},
                                  query="la gaviota", auto=True))
    w = world()
    records.append(command_record(w, "nothing found", "search",
                                  {f"GET {search_url('la flaca')}": _page(search_page(query="flaca"))},
                                  query="la flaca", auto=True))
    w = world()
    _set(w.conn, lacuerda_search.KV_PREFIX + key,
         '{"at": "%s", "songs": 3, "artists": 0, "stated": 3}' % ago(days=12))
    records.append(command_record(w, "asked within 30 days: what it answered then", "search", query="tiza corazón",
                                  auto=True))
    w = world()
    _set(w.conn, lacuerda_search.KV_PREFIX + key, '{"at": "%s", "songs": 1, "artists": 0, "stated": 1}' % ago(days=1))
    records.append(command_record(w, "asked yesterday for one song", "search", query=tiza, auto=False))
    w = world()
    s = w.song("Los Imaginarios", "Corazón de Tiza", lyrics=None)
    assert s
    records.append(command_record(w, "your library answers it already: nothing asked", "search",
                                  query="los imaginarios corazón de tiza", auto=True))
    w = world()
    _cooling(w)
    records.append(command_record(w, "cooling down after a block: nothing asked", "search", query=tiza, auto=True))
    w = world()
    _hour_spent(w)
    records.append(command_record(w, "this hour's lookup requests spent", "search", query=tiza, auto=False))
    w = world()
    _set(w.conn, lacuerda_search.FAILED_KEY, _failures(**{key: (ago(minutes=10), "LaCuerda failed: cut short")}))
    records.append(command_record(w, "sent by the page: its own search failed within the hour", "search",
                                  query=tiza, auto=True))
    w = world()
    _set(w.conn, lacuerda_search.FAILED_KEY, _failures(**{key: (ago(minutes=10), "LaCuerda failed: cut short")}))
    records.append(command_record(w, "by hand, its failure within the hour: asked, the failure gone", "search",
                                  {f"GET {search_url(tiza)}": whole}, query=tiza, auto=False))
    w = world()
    _set(w.conn, lacuerda_search.FAILED_KEY, _failures(
        **{"flaca": (ago(minutes=5), "one"), "gaviota": (ago(minutes=15), "two"), "nandu": (ago(minutes=25), "three")}))
    records.append(command_record(w, "sent by the page once three searches failed within the hour", "search",
                                  query=tiza, auto=True))
    w = world()
    _event(w.conn, f"{SEARCH_RUN}2026-11-03T11:40:00Z", ago(minutes=20), n=20)
    records.append(command_record(w, "sent by the page with the hour's searches it sends by itself spent", "search",
                                  query=tiza, auto=True))
    w = world()
    _event(w.conn, f"{SEARCH_RUN}2026-11-03T11:40:00Z", ago(minutes=20), n=20)
    records.append(command_record(w, "by hand with the page's searches spent: asked", "search",
                                  {f"GET {search_url(tiza)}": whole}, query=tiza, auto=False))
    w = world()
    records.append(command_record(w, "from the cache: nothing sent, no good run recorded", "search", query=tiza,
                                  auto=True, cache={f"GET {search_url(tiza)}": cached(fixture_ref("lacuerda/search.html"),
                                                                                      ago(days=3))}))
    w = world()
    records.append(command_record(w, "a block: its cooldown begun, no failure kept", "search",
                                  {f"GET {search_url(tiza)}": _page("Forbidden", 403)}, query=tiza, auto=True))
    w = world()
    records.append(command_record(w, "a server's error: counted and kept an hour", "search",
                                  {f"GET {search_url(tiza)}": _page("x", 500)}, query=tiza, auto=True))
    w = world()
    records.append(command_record(w, "a page cut short: an error kept an hour", "search",
                                  {f"GET {search_url(tiza)}": _page(fixture_ref("lacuerda/search_cut.html"))},
                                  query=tiza, auto=False))
    return records


def test_commands_lacuerda_jsonl(tmp_path):
    check(COMMANDS, jsonl(command_records(tmp_path), corpus="lookup/commands_lacuerda", made_by=MADE_BY))


def test_the_commands_end_with_each_of_their_lines(tmp_path):
    records = command_records(tmp_path)
    ends = [r["out"]["result"]["lines"][-1] for r in records]
    assert all("raises" not in r for r in records)
    for start in ("Read: ", "Not found: ", "Not read: ", "Searched: ", "Found already: ", "Nothing found: ",
                  "Not searched: "):
        assert any(e.startswith(start) for e in ends), start
    spent = [e for e in ends if "spent" in e]
    assert any("this fetch's 6 asks" in e for e in spent) and any("this hour (60 spent)" in e for e in spent)
    searches = [r for r in records if r["kw"]["command"] == "search"]
    for r in searches[1:]:  # every one past the first, which reads no word, says it is asking first
        assert r["out"]["result"]["lines"][0].startswith('caracole-progress: {"stage":"search","state":"running"'), r
    assert all(r["out"]["requests"] for r in searches if r["out"]["result"]["lines"][-1].startswith("Nothing found"))
    ok = [r for r in records if "provider:lacuerda" in r["out"]["kv"]]
    assert len(ok) >= 8
    assert any(f"has {PAST_A_LONG} songs" in e for e in ends)  # Python's int, whole
