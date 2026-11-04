"""The HTML corpus, for the phone: tests/conformance/vectors/html/, what selectolax's lexbor (``LexborHTMLParser``,
caracole's HTML parser) reads of every page caracole reads, which ``core.html`` must read alike
(docs/superpowers/specs/2026-11-03-html-parsing.md).

lexbor shows no token stream, so the tokenizer's half is what its tree holds that the tokenizer alone decides:

- ``tokens.jsonl``: a record a page: every HTML page of tests/fixtures/ caracole's site parsers read (named by
  reference), and every page the tests' fake sites build (tests/helpers/*_site.py, ug_pages.py), as text;
- ``tokens_edges.jsonl``: the edge set, small documents where tokenizers part ways (character references in text
  and in attributes, CR and CRLF, NUL in each state, script data and its escapes, RCDATA, RAWTEXT, PLAINTEXT,
  comments and bogus comments, processing instructions, CDATA (after text at each integration point), templates,
  formatting elements reconstructed, a doctype of each quirks list, the input cut short in each state);
- ``tokens_soup.jsonl``: seeded tag soup, 600 pages of those pieces cut anywhere (:data:`SOUP`).

Each record's ``args[0]`` is the page (a ``{"fixture": …}`` reference or its text: the bytes decoded as UTF-8 with
replacement, as the parsers hand selectolax text), and its ``out`` (:func:`reads`):

- ``quirks``: whether the document is in quirks mode (``#id`` and ``.class`` then match without case), as a probe
  element's id says: limited quirks is not quirks;
- ``doctype``: the doctype's name as lexbor keeps it (``""`` for a doctype with none), or null without a doctype;
- ``attrs``: each element with an attribute, once (an element the tree builder made again, as the adoption agency and
  the active formatting elements do, is the same pair), as ``[tag, [[name, value], …]]``, its attributes in source
  order, the first of duplicates kept, a value null where none was written (``<a href>``, ``<a href=>``); sorted;
- ``text``: every text node's data in document order, joined;
- ``comments``: every comment's data in document order (from its serialization: selectolax's ``comment_content``
  strips it);
- ``pis``: every processing instruction (lexbor reads ``<?target data?>`` as one, but ``<?xml …?>`` as a bogus
  comment) as ``[target, data]``, in document order.

A ``<template>``'s contents are in none of them: selectolax's tree never reaches them (its ``first_child`` is None,
``css`` finds nothing there), only its serialization shows them.

Kotlin's ``core.testing.replays.HtmlReplay`` reads them with core.html's tokenizer through a small tree builder of its
own (the real one is lane html-tree's): lexbor's tag and attribute names ASCII-lowercased (its tree gives the SVG and
MathML ones their case), the tokenizer's compared as it gives them.
"""

from __future__ import annotations

import random
from typing import Any

from helpers import azlyrics_site, gametabs_site, gtptabs_site, harptabs_site, lacuerda_site, ug_pages
from helpers.corpus import FIXTURES, VECTORS, check, fixture_bytes, fixture_ref, jsonl
from selectolax.lexbor import LexborHTMLParser

MADE_BY = "tests/test_conformance_html.py"
SITES = ("ug", "lacuerda", "gtptabs", "harptabs", "gametabs", "azlyrics", "megalobiz", "musescore")
PROBE = "CARACOLEQUIRKSPROBE"


def write(name: str, records) -> None:
    check(VECTORS / "html" / f"{name}.jsonl", jsonl(records, corpus=f"html/{name}", made_by=MADE_BY))


# --- what lexbor read ---------------------------------------------------------------------------------------


def _walk(node):
    child = node.first_child
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.next


def quirks(text: str) -> bool:
    """Whether lexbor put ``text``'s document in quirks mode: an element added with an upper-case id is found by its
    lower-case one only then."""
    tree = LexborHTMLParser(text)
    probe = tree.create_node("i")
    probe.attrs["id"] = PROBE
    tree.root.insert_child(probe)
    return tree.css_first("#" + PROBE.lower()) is not None


def reads(text: str) -> dict[str, Any]:
    """What lexbor's tokenizer decided of ``text``, as its tree shows it."""
    tree = LexborHTMLParser(text)
    doctype = None
    attrs: dict[str, list] = {}
    texts: list[str] = []
    comments: list[str] = []
    pis: list[list[str]] = []
    for node in _walk(tree.root.parent):
        if node.is_element_node:
            pairs = list(node.attributes.items())
            if pairs:
                key = [node.tag, [list(pair) for pair in pairs]]
                attrs.setdefault(repr(key), key)
        elif node.is_text_node:
            texts.append(node.text_content)
        elif node.is_comment_node:
            html = node.html
            assert html.startswith("<!--") and html.endswith("-->"), html
            comments.append(html[4:-3])
        elif node.tag == "-doctype":
            html = node.html
            assert html.startswith("<!DOCTYPE ") and html.endswith(">"), html
            doctype = html[len("<!DOCTYPE "):-1]
        elif node.tag is None and node.html.startswith("<?"):  # a processing instruction
            target, _, data = node.html[2:-2].partition(" ")
            pis.append([target, data])
        else:
            raise AssertionError(f"a node of no known kind: {node.tag!r} {node.html!r}")
    return {"quirks": quirks(text), "doctype": doctype, "attrs": [attrs[k] for k in sorted(attrs)],
            "text": "".join(texts), "comments": comments, "pis": pis}


def record(case: str, page: str | dict[str, str]) -> dict[str, Any]:
    text = fixture_bytes(page).decode("utf-8", "replace") if isinstance(page, dict) else page
    return {"fn": "test_conformance_html.reads", "case": case, "args": [page], "out": reads(text)}


# --- the pages caracole reads -------------------------------------------------------------------------------


def fixture_pages() -> list[str]:
    """Every HTML page of the sites' fixtures, by its path under tests/fixtures/."""
    return sorted(p.relative_to(FIXTURES).as_posix() for site in SITES for p in (FIXTURES / site).rglob("*.html"))


def helper_pages() -> list[tuple[str, str]]:
    """The pages the fake sites build, each with a name and text that their escapes meet (&, <, quotes, Chinese)."""
    tab = ug_pages.version_dict(85053, version=2, rating=4.54, votes=7, song="De Música Ligera", artist="Soda Stereo")
    others = [ug_pages.version_dict(85042, rating=4.83, votes=277, song="De Música Ligera", artist="Soda Stereo"),
              ug_pages.version_dict(2528571, type="Official", song="De Música Ligera", artist="Soda Stereo")]
    content = "[Verse 1]\r\n[tab][ch]Bm[/ch]    [ch]G[/ch]\r\nla <la> & \"la\" 'la'[/tab]"
    dongye = ug_pages.song_dongye_chords(t4180894=(4.8, 120))
    return [
        ("ug make_tab_page_html", ug_pages.make_tab_page_html(
            tab, others, content=content, artist_url="https://www.ultimate-guitar.com/artist/soda_stereo_2946")),
        ("ug make_tab_page_html, a Guitar Pro page", ug_pages.make_tab_page_html(
            ug_pages.version_dict(9, type="Pro"), [])),
        ("ug make_artist_page_html", ug_pages.make_artist_page_html(
            2946, "Soda Stereo", [tab, *others, {"id": 1806686, "song_name": "X", "marketing_type": "TabPro"}],
            page=1, pages=2)),
        ("ug song_dongye_page_html", ug_pages.song_dongye_page_html(dongye)),
        ("ug song_dongye_sheet", ug_pages.make_tab_page_html(
            dongye[0], dongye[1:], content=ug_pages.song_dongye_sheet(ug_pages.DONG_XIAOJIE_LINES))),
        ("ug store_page_html", ug_pages.store_page_html({"a": "<&>\"'ú宋"}, title="A & B <C>")),
        ("gametabs tab_page", gametabs_site.tab_page("Final Fantasy VII", "Aerith's Theme & <Prelude>",
                                                     composers=("Nobuo Uematsu",), instruments=("Guitar", "Bass"))),
        ("gametabs game_page", gametabs_site.game_page("Hollow Knight", [
            ("dirtmouth", "Dirtmouth"), ("city", "City of Tears & Rain", "Christopher Larkin", "Piano", "11.2k"),
            ("none", "No Composer", "")])),
        ("harptabs tab_page", harptabs_site.tab_page("la bamba", "ritchie valens", key="G",
                                                     body="-4 5 -5\nPara bailar <la> bamba & más\n")),
        ("harptabs artist_page", harptabs_site.artist_page("bob & <dylan>", [
            (29910, "knockin-on-heavens-door", "knockin' on heaven's door"), (1, "a-b", "a & b", "57k")])),
        ("lacuerda listing_page", lacuerda_site.listing_page(
            [("soda_stereo", "Soda Stereo", 120), ("enanitos", "Enanitos Verdes & Co", 3)], pages=3, page=1)),
        ("lacuerda search_page", lacuerda_site.search_page(
            ("soda_stereo", "Soda Stereo", [("de_musica_ligera", "De Música Ligera", "1"), ("prófugos", "Prófugos",
                                                                                          "2")]),
            ("sui_generis", "Sui Generis", [("rasguna", "Rasguña las piedras", "3")]), stated=4, pages=2)),
        ("lacuerda artists_search_page", lacuerda_site.artists_search_page(
            [("la_gaviota", "La Gaviota", 7), ("gaviotas", "Las Gaviotas", 1)])),
        ("lacuerda artist_page", lacuerda_site.artist_page(
            "Charly García", "charly_garcia", ("demoliendo", "Demoliendo hoteles", "1"), ("rezo", "Rezo por vos", "2"))),
        ("gtptabs artist_page", gtptabs_site.artist_page(
            "Café Tacvba", "tabs/7/cafe_tacvba.html",
            gtptabs_site.entry(11, "tabs/7/11/eres.html", "Eres", stars=5, instruments=("drums", "vocals")),
            gtptabs_site.entry(12, "tabs/7/12/las_flores.html", "Las Flores", fmt="gp4"))),
        ("azlyrics artist_page", azlyrics_site.artist_page()),
        ("azlyrics lyrics_page", azlyrics_site.lyrics_page()),
    ]


# --- the edge set -------------------------------------------------------------------------------------------

# The doctype lists of the tree builder's initial mode (WHATWG HTML, 13.2.6.4.1), lexbor's.
PUBLIC_IS = ["-//W3O//DTD W3 HTML Strict 3.0//EN//", "-/W3C/DTD HTML 4.0 Transitional/EN", "HTML"]
SYSTEM_IS = ["http://www.ibm.com/data/dtd/v11/ibmxhtml1-transitional.dtd"]
PUBLIC_STARTS = [
    "+//Silmaril//dtd html Pro v0r11 19970101//", "-//AS//DTD HTML 3.0 asWedit + extensions//",
    "-//AdvaSoft Ltd//DTD HTML 3.0 asWedit + extensions//", "-//IETF//DTD HTML 2.0 Level 1//",
    "-//IETF//DTD HTML 2.0 Level 2//", "-//IETF//DTD HTML 2.0 Strict Level 1//", "-//IETF//DTD HTML 2.0 Strict Level 2//",
    "-//IETF//DTD HTML 2.0 Strict//", "-//IETF//DTD HTML 2.0//", "-//IETF//DTD HTML 2.1E//", "-//IETF//DTD HTML 3.0//",
    "-//IETF//DTD HTML 3.2 Final//", "-//IETF//DTD HTML 3.2//", "-//IETF//DTD HTML 3//", "-//IETF//DTD HTML Level 0//",
    "-//IETF//DTD HTML Level 1//", "-//IETF//DTD HTML Level 2//", "-//IETF//DTD HTML Level 3//",
    "-//IETF//DTD HTML Strict Level 0//", "-//IETF//DTD HTML Strict Level 1//", "-//IETF//DTD HTML Strict Level 2//",
    "-//IETF//DTD HTML Strict Level 3//", "-//IETF//DTD HTML Strict//", "-//IETF//DTD HTML//",
    "-//Metrius//DTD Metrius Presentational//", "-//Microsoft//DTD Internet Explorer 2.0 HTML Strict//",
    "-//Microsoft//DTD Internet Explorer 2.0 HTML//", "-//Microsoft//DTD Internet Explorer 2.0 Tables//",
    "-//Microsoft//DTD Internet Explorer 3.0 HTML Strict//", "-//Microsoft//DTD Internet Explorer 3.0 HTML//",
    "-//Microsoft//DTD Internet Explorer 3.0 Tables//", "-//Netscape Comm. Corp.//DTD HTML//",
    "-//Netscape Comm. Corp.//DTD Strict HTML//", "-//O'Reilly and Associates//DTD HTML 2.0//",
    "-//O'Reilly and Associates//DTD HTML Extended 1.0//", "-//O'Reilly and Associates//DTD HTML Extended Relaxed 1.0//",
    "-//SQ//DTD HTML 2.0 HoTMetaL + extensions//",
    "-//SoftQuad Software//DTD HoTMetaL PRO 6.0::19990601::extensions to HTML 4.0//",
    "-//SoftQuad//DTD HoTMetaL PRO 4.0::19971010::extensions to HTML 4.0//", "-//Spyglass//DTD HTML 2.0 Extended//",
    "-//Sun Microsystems Corp.//DTD HotJava HTML//", "-//Sun Microsystems Corp.//DTD HotJava Strict HTML//",
    "-//W3C//DTD HTML 3 1995-03-24//", "-//W3C//DTD HTML 3.2 Draft//", "-//W3C//DTD HTML 3.2 Final//",
    "-//W3C//DTD HTML 3.2//", "-//W3C//DTD HTML 3.2S Draft//", "-//W3C//DTD HTML 4.0 Frameset//",
    "-//W3C//DTD HTML 4.0 Transitional//", "-//W3C//DTD HTML Experimental 19960712//",
    "-//W3C//DTD HTML Experimental 970421//", "-//W3C//DTD W3 HTML//", "-//W3O//DTD W3 HTML 3.0//",
    "-//WebTechs//DTD Mozilla HTML 2.0//", "-//WebTechs//DTD Mozilla HTML//",
]
NO_SYSTEM_STARTS = ["-//W3C//DTD HTML 4.01 Frameset//", "-//W3C//DTD HTML 4.01 Transitional//"]
LIMITED_STARTS = ["-//W3C//DTD XHTML 1.0 Frameset//", "-//W3C//DTD XHTML 1.0 Transitional//"]
BODY = "<p id=A class=B>x</p>"


def doctype_edges() -> list[tuple[str, str]]:
    out = []
    for i, public in enumerate(PUBLIC_IS):
        out += [(f"doctype public is {i}", f'<!DOCTYPE html PUBLIC "{public}">{BODY}'),
                (f"doctype public is {i}, other case", f'<!DOCTYPE html PUBLIC "{public.lower()}">{BODY}'),
                (f"doctype public is {i} and more", f'<!DOCTYPE html PUBLIC "{public}x">{BODY}')]
    for i, system in enumerate(SYSTEM_IS):
        out += [(f"doctype system is {i}", f'<!DOCTYPE html SYSTEM "{system}">{BODY}'),
                (f"doctype system is {i}, other case", f"<!DOCTYPE html PUBLIC '' '{system.upper()}'>{BODY}")]
    for i, public in enumerate(PUBLIC_STARTS):
        cased = public.upper() if i % 2 else public.lower()
        out += [(f"doctype public starts {i}", f'<!DOCTYPE html PUBLIC "{public}EN" "http://x/y.dtd">{BODY}'),
                (f"doctype public starts {i}, other case", f"<!doctype HTML public '{cased}'>{BODY}"),
                (f"doctype public starts {i}, cut", f'<!DOCTYPE html PUBLIC "{public[:-1]}">{BODY}')]
    for i, public in enumerate(NO_SYSTEM_STARTS + LIMITED_STARTS):
        out += [(f"doctype 4.01 or xhtml {i}, no system", f'<!DOCTYPE html PUBLIC "{public}EN">{BODY}'),
                (f"doctype 4.01 or xhtml {i}, a system", f'<!DOCTYPE html PUBLIC "{public}EN" "http://x/y.dtd">{BODY}'),
                (f"doctype 4.01 or xhtml {i}, an empty system", f'<!DOCTYPE html PUBLIC "{public}EN" "">{BODY}')]
    plain = [
        "<!DOCTYPE html>", "<!doctype html>", "<!DOCTYPE HTML>", "<!DoCtYpE hTmL>", "<!DOCTYPE html5>",
        "<!DOCTYPE>", "<!DOCTYPE >", "<!DOCTYPEhtml>", "<!DOCTYPE  html  >", "<!DOCTYPE html x>",
        "<!DOCTYPE html PUBLIC>", "<!DOCTYPE html SYSTEM>", "<!DOCTYPE html PUBLIC \"\">", "<!DOCTYPE html PUBLIC ''>",
        "<!DOCTYPE html SYSTEM \"\">", "<!DOCTYPE html SYSTEM 'about:legacy-compat'>",
        "<!DOCTYPE html SYSTEM \"about:legacy-compat\" x>", "<!DOCTYPE html PUBLIC\"-//W3C//DTD HTML 4.01//EN\">",
        "<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.01//EN\"\"http://www.w3.org/TR/html4/strict.dtd\">",
        "<!DOCTYPE html PUBLIC \"a>b\">", "<!DOCTYPE html SYSTEM 'a>b'>", "<!DOCTYPE html PUBLIC x>",
        "<!DOCTYPE html PUBLICx>", "<!DOCTYPE html SYSTEMx>", "<!DOCTYPE html PUBLIC 'x' 'y' z>",
        "<!DOCTYPE html PUBLIC 'x'y>", "<!DOCTYPE h\x00tml>", "<!DOCTYPE html PUBLIC 'a\x00b'>", "<!DOCTYPE \x00>",
        "<!DOCTYPE html\r\nPUBLIC\r\n\"-//W3C//DTD HTML 4.01 Transitional//EN\"\r\n\"http://www.w3.org/TR/html4/loose.dtd\">",
        "<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Strict//EN\" "
        "\"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd\">",
        "<!DOCTYPE svg>", "<!--c--><!DOCTYPE html>", " \n<!DOCTYPE html>", "x<!DOCTYPE html>", "<p><!DOCTYPE html>",
        "<!DOCTYPE html><!DOCTYPE html PUBLIC \"HTML\">", "<?xml version='1.0'?><!DOCTYPE html>",
    ]
    out += [(f"doctype {i}", text + BODY) for i, text in enumerate(plain)]
    cut = ["<!DOCTYPE", "<!DOCTYPE ", "<!DOCTYPE ht", "<!DOCTYPE html ", "<!DOCTYPE html P", "<!DOCTYPE html PUBLIC ",
           "<!DOCTYPE html PUBLIC 'x", "<!DOCTYPE html PUBLIC 'x' ", "<!DOCTYPE html PUBLIC 'x' 'y",
           "<!DOCTYPE html SYSTEM", "<!DOCTYPE html SYSTEM 'y' ", "<!DOCTYPE html x", "<!DOCT", "<!DOC"]
    out += [(f"doctype cut {i}", text) for i, text in enumerate(cut)]
    return out


def reference_edges() -> list[tuple[str, str]]:
    texts = [
        "&amp頭 &ampx &notit; &#x80; &#0; a&nbsp;b", "&amp;&AMP;&AMP&amp", "&amp=x &amp;=x &ampy", "&lt&gt&quot&copy&reg",
        "&notin; &notin &noti; &not &not; &notx", "&NotEqualTilde; &acE; &nGt;", "&hellip &hellip; &Hellip; &hellipx",
        "&;", "& ", "&#", "&#;", "&#x", "&#x;", "&#X41;", "&#x41", "&#65", "&#65x", "&#0065;", "&#x00041;",
        "&#xD800;&#xDFFF;&#xDBFF;", "&#x10FFFF;&#x110000;&#x7FFFFFFF;&#99999999999999999999;",
        "&#xFDD0;&#xFDEF;&#xFFFE;&#xFFFF;&#x1FFFE;&#x10FFFE;", "&#x1;&#x8;&#x9;&#xA;&#xB;&#xC;&#xD;&#xE;&#x1F;&#x20;",
        "&#x7F;" + "".join(f"&#x{n:X};" for n in range(0x80, 0xA0)) + "&#xA0;", "&#13;&#10;&#x0D;",
        "&aacute&Aacute;&aacutex&aacute;x", "&frac12&frac12;&frac34x", "&zwj;&zwnj;&lrm;", "&ThickSpace;&bne;",
        "&a", "&am", "&amp", "&amp;", "&#x41", "&#6", "&noti", "&notin", "x&", "&&amp;&", "&am&amp;", "&#38;amp;",
        "&ampamp;", "&Eacute;&eacute;&ETH;&eth;&Ouml;&ouml", "&fjlig;&ncy;&NewLine;&Tab;", "&lt;b&gt;bold&lt;/b&gt;",
        "&Abreve;&abreve;&Abreve", "&nbsp&nbsp;&nbspx&nbsp=", "&copy2026 &reg;x &para9", "a&b=c&d;e",
    ]
    out = [(f"text reference {i}", f"<p>{text}</p>") for i, text in enumerate(texts)]
    out += [(f"text reference at the end {i}", "<p>" + text) for i, text in enumerate(texts)]
    values = [
        "&ampx &amp=y &amp頭", "&amp &amp; &amp! &amp. &amp-", "&notit; &noti; &not; &notx", "&lt;&gt;&quot;&apos;",
        "&#x80;&#0;&#65;&#x41&#65x", "&nbsp=1 &nbspx &nbsp; &nbsp", "a=1&b=2&copy=3&copy;=4&reg5", "&hellip &hellip;",
        "x&", "&", "&#", "&#x", "&;", "&NotEqualTilde;", "&aacute;x&aacutex&aacute", "?q=&lang=en&amp=",
    ]
    for i, value in enumerate(values):
        out += [(f"attribute reference {i}, double quoted", f'<a title="{value}">x</a>'),
                (f"attribute reference {i}, single quoted", f"<a title='{value}'>x</a>"),
                (f"attribute reference {i}, unquoted", "<a title=" + value.replace(" ", "_") + ">x</a>")]
    return out


def markup_edges() -> list[tuple[str, str]]:
    cases = {
        "cr and crlf": "<div id=t_body><pre>\nA\r\nB\rC</pre></div>\r\n<p>\r\rx\r\n\r\n</p>",
        "cr in attributes": "<a title='a\rb\r\nc' b=\"\r\" c=x\ry\r>q</a><a\rhref=x\r\n>r</a>",
        "cr in a comment": "<!--a\rb\r\nc\n\rd-->x",
        "cr at the end": "<p>a\r",
        "a form feed": "<a\fb=c\fd>x\fy</a>",
        "nul in text": "<p>a\x00b\x00</p>",
        "nul in a tag": "<p\x00q a\x00b=c\x00d>x</p\x00q>",
        "nul in values": "<a b='\x00' c=\"\x00\" d=\x00>x</a>",
        "nul in a comment": "<!--a\x00b--><!--\x00--><!-\x00->",
        "nul in a bogus comment": "</ \x00 x>y<! \x00>",
        "nul in rcdata": "<title>a\x00b</title><textarea>\x00</textarea>",
        "nul in rawtext": "<style>a\x00b</style><xmp>\x00</xmp>",
        "nul in script": "<script>a\x00b<!--\x00<script>\x00</script>\x00-->\x00</script>",
        "nul in plaintext": "<plaintext>a\x00b",
        "nul in cdata": "<svg><![CDATA[a\x00b]]></svg>",
        "nul in svg text": "<svg><text>a\x00b</text></svg>",
        "nul in a pi": "<p><?x a\x00b?></p>",
        "nul at the start": "\x00<p>x</p>",
        "a bom": "﻿<p>x</p>",
        "attributes": "<a HREF=X Href=y href='z' title='' data-x=y b c= d=>x</a>",
        "attribute oddities": "<a \"x\"=1 'y'=2 <z=3 =w a'b=c a\"b=d>x</a><a/b/c=d/>y</a><a b='1'c=\"2\"d=3>z</a>",
        "unquoted values": "<a b=c\"d e=f'g h=i<j k=l=m n=o`p q=&amp;r>x</a>",
        "a value with a space after the equals": "<a b= c d =e f = 'g'>x</a>",
        "self-closing tags": "<br/><br /><div/>x</div><img src=a/><a href=b/>c</a><a href=b / >d</a>",
        "a slash in a tag": "<a / b>x</a><a/ /b/>y</a><p/ x>z</p>",
        "end tags with attributes": "<a></a b=c><p>q</p class=x/><div></div/>",
        "odd tag names": "<a1>x</a1><h7>y</h7><x-y z=1>q</x-y><ÄB c=d>e</äb><foo:bar a=b>c</foo:bar>",
        "upper case": "<DIV CLASS=A ID=B>x</DIV><P>y</p><SPAN Title=T>z</SPAN>",
        "less-than signs": "<p>a < b <1 <! <? <- <<a>x</a> </ x> </> <-p>",
        "end tag opens": "</>a</ b>c</1>d</\t>e</x\x00>f</-a>g</p",
        "comments": "<!--a--><!----><!---><!--><!-- a -- b --><!--a--!>b--><!--a--!->c--><!--<!--x--><!--a<!--b-->",
        "comment ends": "<!--a-><!--a--><!--a---><!--a----><!--a--->b--><!-- --!-->x<!--a<!->b-->",
        "comment less-than": "<!--<!-- x--><!--<!-x--><!--<!--->--><!--<<!--y--><!--a<!---->",
        "comments cut 1": "<!--x",
        "comments cut 2": "<!--x-",
        "comments cut 3": "<!--x--",
        "comments cut 4": "<!--x--!",
        "comments cut 5": "<!--",
        "comments cut 6": "<!---",
        "comments cut 7": "<!--<!-",
        "comments cut 8": "<!--<!--",
        "comments cut 9": "<!-",
        "comments cut 10": "<!",
        "comments cut 11": "<p>a&amp;b\x00c<!",
        "comments cut 12": "<svg><![CDATA[x]]>y<!",
        "comments cut 13": "a</>b<!",
        "comments cut 14": "<p>a</p>\n<!",
        "bogus comments": "<!x><!-x><!x-y><![x]><!DOCTYPEx><!doc>y</ x y>z",
        "bogus comments cut": "<!x",
        "comments in places": "<!--0--><html><!--1--><head><!--2--></head><!--3--><body><!--4--></body><!--5--></html><!--6-->",
        "a comment after body": "<p>x</p></body><!--c-->\n<p>y",
        "processing instructions": "<p><?x y?>a<?x?>b<?x  y z ?>c<?x y? z?>d<?a-b_c d>e<?_x y?>f</p>",
        "processing instructions at the top": "<?php echo 1; ?><?x y?><p>q",
        "processing instructions as comments": "<?xml version='1.0'?><?XML x?><?xml-stylesheet href=x?><?xmlx y?>"
                                               "<?xml-x y?><p><?x.y?>a<?1?>b<? x?>c<?-x?>d<?x\x00y?>e</p>",
        "processing instructions cut 1": "<p>a<?",
        "processing instructions cut 2": "<p>a<?x",
        "processing instructions cut 3": "<p>a<?x y",
        "processing instructions cut 4": "<p>a<?x y?",
        "processing instructions in svg": "<svg><?x y?></svg>",
        "cdata in html": "<p><![CDATA[x]]>y<![CDATA[]]><![cdata[z]]></p>",
        "cdata in svg": "<svg><![CDATA[x<y]]>a<![CDATA[]]]]><![CDATA[a]b]]c]]]></svg>",
        "cdata in math": "<math><![CDATA[1<2]]><mi><![CDATA[q]]></mi></math>",
        "cdata in foreignobject": "<svg><foreignObject><![CDATA[a]]><div><![CDATA[b]]></div></foreignObject></svg>",
        "cdata after text at an integration point": "<svg><foreignObject><p><b>a</p>y<![CDATA[z]]>",
        "cdata after text at a math text point": "<math><mi><p><b>a</p>y<![CDATA[z]]></mi></math>",
        "cdata after text in desc": "<svg><desc><i>a<p>b</i>c<![CDATA[d]]></desc></svg>",
        "cdata after text, nothing to reconstruct": "<svg><foreignObject>y<![CDATA[z]]></foreignObject></svg>",
        "cdata cut": "<svg><![CDATA[x",
        "cdata cut short": "<svg><![CDA",
        "rcdata": "<title>a&amp;b<i>c</i></title><textarea>\nx&lt;y</textarea><textarea>\n\nz</textarea>",
        "rcdata end tags": "<title>a</titlex>b</title y>c</TITLE><title>d</ title></title/></title>",
        "rcdata cut": "<title>a&amp",
        "rawtext": "<style>a&amp;<b>c</b></style><xmp>&lt;<i></xmp><iframe><b>x</b></iframe>"
                   "<noembed><i></noembed><noframes><b></noframes>",
        "rawtext end tags": "<style>a</stylex>b</ style></STYLE x=y><xmp></xmp/>",
        "rawtext cut": "<style>a</sty",
        "noscript": "<noscript><b>x</b></noscript><head><noscript><p>y</p></noscript>",
        "plaintext": "<plaintext></plaintext>x&amp;<b>",
        "script": "<script>a<!--b<script>c</script>d</script>e",
        "script escapes": "<script><!--x--></script><script><!--<script>x</script>-->y</script>z"
                          "<script><!--<script>x</scriptx>y</script>z</script>w<script><!--<sCrIpT >--></script>q",
        "script double escapes": "<script><!--<script></script x>--></script>a<script><!--<script/>--></script>b"
                                 "<script><!-- <script>-</script>--></script>c<script><!--<scriptx>--></script>d",
        "script dashes": "<script>--></script><script><!---></script><script><!-- - -- ---></script>"
                         "<script><!--<script>--></script>a</script>",
        "script less-than": "<script><a></script><script><</script><script></</script><script></scriptx</script>",
        "script end tags": "<script>a</SCRIPT>b<script>c</script d=e>f<script>g</script/>h",
        "script escaped end tags": "<script><!--a</script>b<script><!--a-</script>c<script><!--a--<</script>d"
                                   "<script><!--a</scriptx>e</SCRIPT >f",
        "script double escaped ends": "<script><!--<script>a-<</script>b--></script>c"
                                      "<script><!--<script>a--<</script>--></script>d<script><!--<script>-<x--></script>e",
        "references at a value's end": "<a b=\"x&\" c=\"&amp\" d=&amp e='&#65x' f=&lt g=\"&lt;&\">x</a>",
        "references in rcdata": "<title>&</title><textarea>&#x41;&amp&notit;</textarea><title>a</TiTlE >",
        "script cut 1": "<script>a",
        "script cut 2": "<script><!--a",
        "script cut 3": "<script><!--<script>a",
        "script cut 4": "<script></scr",
        "script in svg": "<svg><script>a<b>c</b></script></svg>",
        "title in svg": "<svg><title>a<b>c</b>&amp;</title><style>d<i>e</i></style></svg>",
        "tags cut 1": "<p>a<",
        "tags cut 2": "<p>a</",
        "tags cut 3": "<p>a<b",
        "tags cut 4": "<p>a<b ",
        "tags cut 5": "<p>a<b c",
        "tags cut 6": "<p>a<b c=",
        "tags cut 7": "<p>a<b c='d",
        "tags cut 8": "<p>a<b c=d",
        "tags cut 9": "<p>a<b c='d' ",
        "tags cut 10": "<p>a<b/",
        "tags cut 11": "<p>a</b",
        "tags cut 12": "<p>a<b c=\"d",
        "template": "<p>a<template b=c><i id=y>t</i><!--c--><?x y?></template>z",
        "template in head": "<head><template id=h><p id=x>a</template></head><body>y",
        "template after head": "<head></head><template a=1><b>x</b></template><p id=q>y",
        "template html and body": "<body b=1><template><html a=1><body b=2></template><p>y",
        "template unclosed": "<p>a<template><div id=d>x",
        "template in a table": "<table><template t=1><tr><td>x</template>y</table>",
        "templates nested": "<template><template id=i>a</template>b</template>c",
        "template in svg": "<svg><template id=t>a</template></svg>",
        "template and cdata": "<template><svg><![CDATA[x]]></template>q",
        "template and forms": "<form id=a><template><form id=b>x</form></template></form>",
        "template and formatting": "<b>a<template><i>b</template>c</b>",
        "template end tags": "<template><div></div></p></body></html></td>x</template>y",
        "reconstructed formatting": "<p><b id=1><i>a</p>b<p>c</b>d</i>e",
        "formatting in a table": "<table><b>x<tr><td>y</td></tr>z</table>w",
        "formatting and markers": "<b>a<object><i>b</object>c</b>d<marquee><s>e</marquee>f",
        "an a in an a": "<a href=1>x<p><a href=2>y</a>z",
        "a nobr in a nobr": "<nobr>x<nobr>y</nobr>z",
        "noah's ark": "<p><b c=1><b c=1><b c=1><b c=1>x</p>y",
        "pre and listing": "<pre>\n\nx</pre><listing>\ny</listing><pre>z</pre><pre>\r\nw</pre><pre>&#10;v</pre>",
        "whitespace in places": " \n\t<html> \n<head> \n</head> \n<body> \n</body> \n</html> \n",
        "text in places": "a<html>b<head>c</head>d<body>e</body>f</html>g",
        "head re-entry": "<head></head>\n<script>x</script>\n<link rel=a>\n<meta name=b>\n<body>y",
        "html and body attributes": "<html a=1><body b=2><html a=3 c=4><body b=5 d=6><p>x</p>",
        "svg attributes": "<svg viewbox='0 0 1 1' xlink:href=a XML:LANG=b><clippath><path d=x/></clippath>"
                          "<foreignObject><b>q</b></foreignObject></svg>",
        "math attributes": "<math definitionurl=x xlink:href=y><mi>x</mi></math>",
        "entities in svg": "<svg><text title='&ampx'>&amp;&lt;</text></svg>",
        "non-ascii": "<p title='宋冬野 «x»'>斑马, 斑马 — ✓ 𝄞</p>",
        "lone ampersands and angles": "<p>a & b && c &; d >e > f</p>",
        "empty": "",
        "text alone": "hello",
        "whitespace alone": " \n ",
        "a comment alone": "<!--x-->",
    }
    return list(cases.items())


def edge_pages() -> list[tuple[str, str]]:
    return doctype_edges() + reference_edges() + markup_edges()


# The pieces of the tag soup: markup a tokenizer meets cut anywhere, and the tags that switch it.
SOUP = [
    "<", ">", "/", "!", "-", "--", "?", "&", "#", "x", "X", ";", "amp", "lt", "not", "notin", "nbsp", "a", "b", "p",
    "div", "script", "title", "textarea", "style", "xmp", "plaintext", "svg", "math", "pre", "=", "'", '"', " ", "\n",
    "\r", "\r\n", "\t", "\x00", "[CDATA[", "]]", "DOCTYPE", "html", "PUBLIC", "SYSTEM", "x=y", "é", "宋", "&#",
    "<!--", "-->", "<?", "?>", "</", "<script>", "</script>", "<!--<script>", "<title>", "</title>", "<svg>", "</svg>",
    "<p>", "</p>", "<a href=", "<b>", "</b>", "<br/>", "1", "9", "F", "&#x", "&amp;", "<!", "<!DOCTYPE html>",
    "<textarea>", "</textarea>", "<style>", "</style>", "<math><mi>", "<foreignObject>", "<desc>", "<i>", "<p id=Q>",
    "xml", "<html a=1>", "<body b=2>", "<head>", "</head>", "</body>", "</html>", "<!-- x -->", "<![CDATA[x]]>",
    "&notit;", "&ampx", "&#128;", "&#0;", "<noscript>", "<iframe>", "</iframe>", '<a b="&amp=">', "<a b=&ampx>",
    "<x y z=w>", "<FOO Bar=Baz>", "</FOO>", "<?x y?>", "<?xml?>", "<!--->", "--!>", "<!-->", "<template>",
    "</template>", "<template t=1>",
]


def soup_pages(count: int = 600, seed: int = 20261104) -> list[tuple[str, str]]:
    """Seeded tag soup: each page 3 to 40 of the pieces above, at random."""
    rng = random.Random(seed)
    return [(f"soup {i}", "".join(rng.choice(SOUP) for _ in range(rng.randint(3, 40)))) for i in range(count)]


# --- the vectors --------------------------------------------------------------------------------------------


def test_tokens_jsonl_is_what_lexbor_reads_of_every_page():
    records = [record(f"fixture {path}", fixture_ref(path)) for path in fixture_pages()]
    records += [record(f"helper {name}", text) for name, text in helper_pages()]
    write("tokens", records)


def test_tokens_edges_jsonl_is_what_lexbor_reads_of_the_edge_set():
    write("tokens_edges", [record(name, text) for name, text in edge_pages()])


def test_tokens_soup_jsonl_is_what_lexbor_reads_of_seeded_tag_soup():
    write("tokens_soup", [record(name, text) for name, text in soup_pages()])


def test_the_edge_set_and_the_pages_are_named_once():
    names = [name for name, _ in edge_pages()] + [name for name, _ in helper_pages()]
    assert len(names) == len(set(names))
    assert len(fixture_pages()) >= 30


def test_the_probe_finds_quirks_mode_as_the_spec_says():
    assert quirks("<p>x") and not quirks("<!DOCTYPE html><p>x")
    assert quirks('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN"><p>x')
    assert not quirks('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://x"><p>x')  # limited


def test_what_the_spec_says_of_lexbor_holds():
    assert reads("<div id=t_body><pre>\nA\r\nB\rC</pre></div>")["text"] == "A\nB\nC"
    assert reads("<p>&amp頭 &ampx &notit; &#x80; &#0; a&nbsp;b</p>")["text"] == "&頭 &x ¬it; € � a\xa0b"
    assert reads("<a title='&ampx &amp=y &amp頭'>x</a>")["attrs"] == [["a", [["title", "&ampx &amp=y &頭"]]]]
    assert reads("<a href b= c=>x</a>")["attrs"] == [["a", [["href", None], ["b", "c="]]]]
    assert reads("<!-- x -->")["comments"] == [" x "]
    assert reads("<p><?x y?>")["pis"] == [["x", "y"]] and reads("<?xml v?>")["comments"] == ["?xml v?"]


def test_a_page_is_read_by_reference_as_the_parsers_decode_it():
    path = fixture_pages()[0]
    assert record("x", fixture_ref(path))["out"] == reads((FIXTURES / path).read_bytes().decode("utf-8", "replace"))

