# The phone's HTML parser: lexbor's semantics in Kotlin

The contract `core.html` keeps (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, §5.1; lanes html-tokenizer
and html-tree). caracole's site parsers read pages through selectolax's lexbor (`LexborHTMLParser`, selectolax 1.0.0):
the phone answers every query they make exactly as it does, for every page caracole reads. Python's corpus holds it
(`tests/test_conformance_html.py`, `vectors/html/`): selectolax driven over every fixture of `tests/fixtures/`, every
page a test helper builds, an edge set and a seeded mutation set, compared on the JVM and on the device.

The evidence: [the probes](../spikes/2026-11-03-android/html-probes/), run against selectolax and jsoup.

## The API

```kotlin
object Html { fun parse(text: String): HtmlDoc; fun parse(bytes: ByteArray): HtmlDoc }  // bytes: PyCodec.utf8Replace
class HtmlDoc(val quirks: Boolean) { fun css(sel: String): List<HtmlNode>; fun cssFirst(sel: String): HtmlNode? }
class HtmlNode {
    val tag: String                     // lowercase (an SVG element's in its own case, "clipPath"); "-text", "-comment"
                                        // as selectolax names them, "-pi" for a processing instruction (selectolax: None)
    fun attr(name: String): String?     // attributes[name]
    val attributes: Map<String, String?>   // as selectolax's dict: null where no value was written
    fun text(deep: Boolean = true): String
    fun children(includeText: Boolean = true): List<HtmlNode>   // iter(include_text=), its default the other way
    val textContent: String?            // a text node's text; null for anything else
    val next: HtmlNode?                 // the next sibling, of any kind
    val isText: Boolean
    fun css(sel: String): List<HtmlNode>; fun cssFirst(sel: String): HtmlNode?
    fun replaceWith(text: String); fun insertAfter(text: String)
}
```

Two `HtmlNode`s of one node are equal. `HtmlDoc(quirks)` alone is an empty document in that mode.

## Input

- The page's bytes are decoded as UTF-8 with replacement (`bytes.decode("utf-8", "replace")`, `PyCodec.utf8Replace`),
  never by a `<meta charset>`: caracole's parsers hand selectolax text (`Preprocess.bytes`).
- CRLF and a lone CR become LF before tokenizing (`<pre>\nA\r\nB\rC</pre>` reads `A\nB\nC`; `Preprocess.text`).
  lexbor does it state by state, to the same text; a CR a reference writes (`&#13;`) stays one.
- Nothing else changes: a byte-order mark stays a character (text in the body), a noncharacter or a control is a parse
  error alone, and a U+0000 is each state's: kept in the data state and a CDATA section for the tree builder (dropped
  in HTML content, U+FFFD in foreign content), kept raw in a processing instruction's data, U+FFFD everywhere else.
- The LF right after a `<pre>` (and `<listing>`, `<textarea>`) start tag is dropped, as the spec's tree builder does
  (one a reference writes, `<pre>&#10;x`, too).

## The tokenizer

`core.html.internal.token` (lane html-tokenizer): `Tokenizer(text)` gives the WHATWG tokenizer's tokens (HTML
§13.2.5) as lexbor 3.1.0 (2026-09-28, selectolax 1.0.0's) makes them, one at a time (`next()`):

- `Doctype(name, publicId, systemId, forceQuirks)`: the name ASCII-lowercased, null when none was written; an
  identifier null when missing; `mode`, the document's mode it sets.
- `StartTag(name, attributes, selfClosing)` and `EndTag(name)`: names ASCII-lowercased (`<ÄB>` is no tag: `Ä` is no
  ASCII letter); an end tag's attributes dropped.
- `Comment(data)`, `ProcessingInstruction(target, data)`, `Characters(data, kind)`, `EndOfFile`.
- The characters between two other tokens come cut where they change between ASCII whitespace (tab, LF, FF, CR,
  space), U+0000 and anything else (`kind`), so that each insertion mode's rule applies to a whole token.

The tree builder drives it: after a start tag it says what follows (`switchTo(Content)`: `Tokenizer.contentFor(tag)`
gives lexbor's choice, RCDATA for `title` and `textarea`, RAWTEXT for `style`, `xmp`, `iframe`, `noembed`,
`noframes`, script data for `script`, PLAINTEXT for `plaintext`; `noscript` none, as selectolax parses with scripting
off), and `foreignContent()` answers whether the adjusted current node is outside the HTML namespace, where
`<![CDATA[` opens a CDATA section (elsewhere a bogus comment, `[CDATA[x]]`). An end tag in RCDATA, RAWTEXT or script
data is a tag only when it is the last start tag's.

The text before a `<!` or a `<?` comes out of `next()` before what follows is read, as lexbor's tag open state emits it
there, so `foreignContent()` is asked with that text inserted: text at an HTML integration point may reconstruct a
formatting element, an HTML one, and `<svg><foreignObject><p><b>a</p>y<![CDATA[z]]>` reads the text `ay` and the
comment `[CDATA[z]]` (with the text still pending, the tree would answer from `foreignObject` and read `ayz`).

### Attributes

- In source order, names ASCII-lowercased, the first of duplicates kept (`<a HREF=X Href=y>` has `href` X).
- A value null where none was written: `<a href>` and `<a href=>` (whose `=` meets `>`), as selectolax answers `None`;
  `<a href="">`'s is "". (The spec's is "" for all three.)
- `<a b= c>`: `b`'s value is `c` (whitespace before a value is skipped); `<a "x"=1 =w>` has attributes `"x"` and `=w`.

### Comments and processing instructions

- Comments as the spec reads them: `<!-->` and `<!--->` empty, `--!>` ends one, `<!--a--!->` holds `a--!->`, a nested
  `<!--` kept (`<!--<!--x-->` holds `<!--x`), one the input ends in emitted.
- Bogus comments: `<!x>`, `</ x>` (its data ` x`), `<![CDATA[…` outside foreign content. selectolax's `comment_content`
  strips the data; the tokenizer's, and the vectors', is as written (a comment node's serialization).
- lexbor reads `<?target data?>` as a processing instruction (its §13.2.5.72–76): the target ASCII alphanumerics, `-`
  and `_`, starting with a letter or `_`; the data after the whitespace that follows it, to `?>` or `>` (`<?x y? z?>`
  holds `y? z`, `<?x?>` none). A target `xml` or `xml-stylesheet` in any case, a target cut by any other character, or
  `<?` followed by neither a letter nor `_`, makes a bogus comment that starts with `?` (`<?xml version='1.0'?>` is
  the comment `?xml version='1.0'?`). A processing instruction the input ends in is dropped whole, `<?` too. The tree
  builder places one as it places a comment.
- At the end of the input, lexbor drops what of `<![CDATA[` was written (`<![CD` is an empty comment); `<!DOCT` is
  the comment `DOCT`, as the spec has it; and `<!` alone is a comment of the text since the token before it, again
  (`<p>a<!` has the text `a` and the comment `a`), its buffer never emptied there.

### Character references

- The HTML5 table is Python's `html.entities.html5`, as data: `data/caracole/html/entities.json` (in its order; the
  legacy names listed bare beside their `;` form), read as lexbor reads its own: the longest name the input starts
  with, case-sensitive.
- **In text** (and RCDATA): the longest name in the table, with or without its `;` (`&amp頭` is `&頭`, `&ampx` is `&x`,
  `&notit;` is `¬it;`, `&notin` is `¬in`); a name the table lacks as written (`&hellip` without its `;`).
- **In an attribute value**, the attribute rule: a reference without its `;` followed by `=` or an ASCII alphanumeric
  stays as written (`&ampx`, `&amp=y`, `&para4`, `?a=1&copy=2`), otherwise decoded (`&amp頭` is `&頭`).
- Numeric references by the spec's rules: U+FFFD for 0, a surrogate or past U+10FFFF (the digits stop counting there),
  the spec's table for 0x80–0x9F (`&#x80;` is `€`, `&#x81;` stays U+0081), a noncharacter or a control kept;
  `&#x41` without its `;` decoded; `&#`, `&#x` and `&#;` as written.

### Quirks mode

From the doctype by the spec's lists (lexbor's, `CompatMode.of`), or by a missing doctype:

- quirks: force-quirks, a name other than `html`, a public identifier equal to one of three or starting with one of
  55, the IBM system identifier, or a public identifier starting with HTML 4.01 Frameset's or Transitional's and no
  system identifier; limited quirks: those two with a system identifier, or XHTML 1.0 Frameset's or Transitional's;
  ASCII case-insensitive throughout.
- As lexbor reads them, an empty identifier is a missing one: `PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" ""` is
  quirks mode (the spec's limited quirks).
- selectolax shows quirks mode alone (`#id` and `.class` without case), never limited quirks.

### The vectors

`vectors/html/tokens.jsonl` (every HTML page of the sites' fixtures, by reference, and every page the fake sites build),
`tokens_edges.jsonl` (the edge set: references in text and attributes, CR, NUL in each state, script data and its
escapes, RCDATA, RAWTEXT, PLAINTEXT, comments, processing instructions, CDATA (after text at each integration point),
templates, formatting elements reconstructed, each doctype list's entries, the input cut short in each state) and
`tokens_soup.jsonl` (seeded tag soup: 600 pages of markup cut anywhere). lexbor shows no token stream, so each record
holds what its tree shows the tokenizer decided: the document's mode (by a probe element's id), the doctype's name, each
element with an attribute once (its tag and attributes; the tree's clones are the same pair), every text node's data in
document order joined, every comment's and processing instruction's. A `<template>`'s contents are in none of them:
selectolax's tree never reaches them (its `first_child` is None, `css` finds nothing there; only its serialization shows
them). `core.testing.replays.HtmlReplay` reads them through `TokensTree`, a tree builder of the replay's own: where each
node goes in document order (the head before what follows it, a comment after `</body>` in the html element, text a
table can't hold fostered before it, or into a template opened in the table), the start tags it drops or merges, the
text it drops, what it switches the tokenizer to, foreign content, the active formatting elements reconstructed (the
current node `<![CDATA[` is read in), of the adoption agency the furthest block left open, a table part's context, and a
template's contents in body's rules, never walked. lexbor's tag and attribute names are ASCII-lowercased (its tree gives
the SVG and MathML ones their case) and the tokenizer's compared as it gives them, so a name it left upper-case differs.

### nu.validator's htmlparser (the plan's §11, Q1b)

- Not run: the half-day probe's jar (htmlparser 1.4.16, its last release, of 2020) was not allowed to run on the
  machine, and nothing went round that; its timing waits for the owner's yes.
- It can't match the vectors as it stands, nor under a layer of core.html's own, since what differs is gone from its
  tree: it follows the spec where lexbor departs from it (above), and reads
  - `<?x y?>` as a bogus comment ending at the first `>`, where lexbor reads a processing instruction;
  - an attribute written with no value as `""`, as `x=""` is, where lexbor gives null;
  - an empty system identifier as one written, so `PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" ""` is limited
    quirks, where lexbor's is quirks.
- Those three alone answer at least 3 of tokens.jsonl's 47 records otherwise, 12 of the edge set's 523 and 122 of the
  soup's 600 (each a record whose answer holds a processing instruction, a null value, or that doctype in quirks).
- So the tokenizer stays hand-written, the default.

## Text

- `text(deep = true)` is lexbor's: every descendant text node's text concatenated with no separator, a `<script>`'s or
  `<style>`'s data included (`var x='<b>';TUV`), nothing for `<br>`, comments and processing instructions left out; a
  text node's is its own text, a comment's "".
- `text(deep = false)`: the node's own text children alone (`<a>x<!--c-->y<b>q</b>s</a>` is `xys`).
- `children(includeText = true)` lists every child, text nodes as `-text` with their `textContent` (`[('a', None),
  ('-text', '  x '), ('b', None)]`); with `includeText = false` it leaves the text nodes out but keeps comments and
  processing instructions, as selectolax's `iter()` does. Whitespace-only text nodes are kept where the tree builder
  keeps them. The defaults differ: selectolax's `iter()` is `children(includeText = false)`, its
  `iter(include_text=True)` is `children()`.
- `attributes` is selectolax's dict: in order, a value null where none was written. The tokenizer kept the first of
  duplicates; of two attributes the tree builder keeps under one shown name (a foreign attribute, adjusted), the dict's
  last value at the first's place.
- `replaceWith(text)` puts a text node of `text` in the node's place, `insertAfter(text)` one right after it; neither
  merges with the text beside it (harptabs.py's `<pre>`: `a<br>b` then has the texts `a`, `\n`, `b`).

## The tree

`core.html.internal.tree` (lane html-tree): `TreeBuilder`, a port of lexbor 3.1.0's tree builder (lexbor/html/tree.c
and tree/insertion_mode/, Apache-2.0), insertion mode by insertion mode, with lexbor's tables of each tag's categories
in each namespace, of SVG's element and attribute names in their own case and of the foreign attributes
(`Tags`); `Dom.kt`, lexbor's nodes linked to their parent and siblings. `TreeBuilder`, `Tags` and `Selectors` carry
lexbor's copyright and say they were ported and changed; `core/html/internal/LICENSE-lexbor` holds the Apache License
2.0 and lexbor's NOTICE.

- Every insertion mode: initial, before html, before head, in head, in head noscript (scripting is off, as selectolax
  parses), after head, in body (the adoption agency, the active formatting elements and their Noah's Ark clause, the
  implied end tags, the scopes), text, in table, in table text, in caption, in column group, in table body, in row,
  in cell, in template, after body, in frameset, after frameset, after after body, after after frameset; foreign
  content (svg and math in their namespaces, their integration points, a self-closing tag popped, the breakout tags
  that leave it, a `<font>` with `color`, `face` or `size`).
- A `<template>`'s contents are a fragment of their own, as lexbor builds them: selectolax shows a template with no
  children, its text "", and no selector finds what it holds (`<template><p>a</p></template>`: `css("p")` finds
  nothing).
- A processing instruction is a node, placed as a comment is: in a table, the table's child, never fostered
  (`<table><?x y?><tr>`, tree_edges.jsonl's "a processing instruction in a table").
- A document with no doctype is in quirks mode; a doctype sets it as The tokenizer, "Quirks mode", says.

Where lexbor reads the standard its own way, core.html does too:

- **`<select>`** is an ordinary element (the customizable select's parsing: there is no "in select" mode) and a
  scope, so a `<p>` or a `<button>` outside it is not in scope inside it (`<button><select><button>` nests the second
  button); `<select>` in a select's scope closes it and is dropped, `<input>` closes it, `<option>`, `<optgroup>` and
  `<hr>` in one imply their end tags; anything else nests (`<select><div>x</div>` keeps the div).
- **In table**, a token "anything else" hands to in body is never processed again, whatever in body says: `<table>
  <image src=x>` drops the image (in body would make it an `<img>` and process it again).
- **Implied end tags** pop an element of any namespace by its tag name, as lexbor compares tag ids.
- **`sup`** is no breakout tag of foreign content (`<svg><sup>` is an SVG element); `sub` is.
- **Text after `</html>` after a frameset** goes to in body only when the whole text between two other tokens is
  whitespace: `</html> x ` adds nothing, its spaces neither (the tokenizer's pieces of it are read together there).
- A start tag's attributes are its first of duplicates everywhere but one place lexbor reads them all: Divergences.

## Quirks mode

- Set from the doctype in the initial insertion mode (The tokenizer, "Quirks mode": `Token.Doctype.mode`), or by a
  missing doctype; `HtmlDoc.quirks` says which (limited quirks is not quirks).
- In quirks mode, `#id` and `.class` match without ASCII case (`ul#b_main` finds `<ul id=B_MAIN>`); in standards mode
  they match as written. A `<table>` closes an open `<p>` only outside quirks mode.

## Selectors

`core.html.internal.select.Selectors`, lexbor/selectors' matching of the selectors caracole's parsers write (each
`css(` and `css_first(` of src/caracole/): a type or `*`, `#id`, `.class`, `[a]`, `[a=v]`, `[a~=v]`, `[a|=v]`,
`[a^=v]`, `[a$=v]`, `[a*=v]` (a value quoted or not, an `i` or `s` flag), the descendant combinator, `>`, `+`, `~`, and
`,`. A selector of anything else (a pseudo-class, a namespace, an escape) or one that won't parse (`a[title=hello
world]`, `#`, `a >`) is an `IllegalArgumentException`, as selectolax raises for one it can't parse.

- `css` walks the node it is asked of and its descendants in document order (a node's search finds the node itself:
  `div.css("div")` gives the div), and gives each element once for each selector of the list it matches: `p, #a`
  gives a `<p id=a>` twice, `p, p` every `<p>` twice. `HtmlDoc.css` starts at the `<html>` element.
- A combinator reads the whole tree, outside the node searched from too: `div.css("body p")` finds the div's `<p>`.
- A type or an attribute name matches without ASCII case, in any namespace (`title` finds an SVG `<title>`,
  `clippath` an SVG `<clipPath>`, `[viewbox]` its `viewBox`).
- `#id` and `.class`: as Quirks mode says; a class is any of the value's words (split at ASCII whitespace).
- An attribute's value matches without ASCII case for the attributes HTML lists as such (`type`, `lang`, `rel`,
  `dir`, `media`, `target`… lexbor's 46) on an HTML element, as written otherwise; with `i` always without case, with
  `s` never. A value-less attribute's value is "" to `=`, `~=` and the others; `^=`, `$=` and `*=` of "" find nothing.

## The tree's vectors

`tests/test_conformance_html.py`'s tree half (`HtmlReplay`'s, `HtmlTreeReplay`):

- `tree.jsonl`, a record of every page of `tokens.jsonl` (each fixture page by reference, each helper-built page):
  its `shape`, every node in document order with its depth (an element's name and attributes, a text's, a comment's
  and a processing instruction's data, the doctype's name); `texts`, the SHA-256 of every element's `text(deep=True)`
  and `text(deep=False)`; `queries`, what each selector caracole's parsers write finds from the document; `scoped`,
  what each search the parsers make from a node finds from each node its first selector finds; `pre`, what
  harptabs.py's `_pre_text` (`replace_with`, `insert_after`, `next`) reads of each `<pre>`.
- `tree_edges.jsonl`, the same of the tree's edge set: `<pre>`'s first newline, the adoption agency, nested `<a>`,
  unclosed `<p>`, `<li>`, `<dd>`, tables and foster parenting, select, svg and math with their self-closing children,
  integration points and breakout tags, templates, the head, framesets, script and style, odd tags, quirks and
  standards mode, pages cut short.
- `tree_selectors.jsonl`, selectors alone over one page in quirks and in standards mode, from the document and from
  the nodes a scope finds, and the selectors selectolax refuses.
- `mutations.jsonl`, 400 seeded tag-soup edits of the fixtures (a fixture, a cut of it in code points and up to 12
  edits, each inserting a tag that moves the tree builder or a piece of the page): each shape's canonical digest
  (`canonical.digest`, `core.json.Canonical`) and length.
- The token vectors are read through core.html's tree too (`HtmlTreeReplay.tokensRead`).

All match on the JVM and on the device: 400 of 400 mutations. A local differential run of about 140,000 more seeded
pages (tag soup of up to 300 pieces, 12,000 more fixture mutations, every token vector's page, frameset text cases),
compared node for node with selectolax, found none that differ once its one finding was fixed (text after a
frameset's `</html>`, read whole: The tree).

## Divergences

- `<input type=text type=hidden>` in a table: lexbor reads every `type` the tag was written with, its duplicates too,
  and keeps the input in the table when any says `hidden`; core.html's tokenizer keeps the first of duplicates alone,
  so the input (`type=text`, as both show it) is fostered before the table. (`TreeTest` pins it.)

## For the site parsers

What a lane porting a site's parser (ug-pages, lacuerda-pages, harptabs, gametabs, tab-files) keeps in mind:

- **A processing instruction's `tag`** is `"-pi"` in core.html and None in selectolax. Python that calls a str method
  on every child's `.tag` raises on a page that holds one: lacuerda.py's `_ug_markup` (`tag.startswith("-")`) raises
  `AttributeError` for `lacuerda.parse_version_page("<div id=t_body><pre>Am <?php echo 1?>\nla</pre></div>")`, where a
  straight port would skip the node and read a sheet. Such a parser is fixed in Python first, test first (`tag =
  child.tag or "-"`), and then ported; core.html keeps `"-pi"`.
- **`iter()`** is `children(includeText = false)`, **`iter(include_text=True)`** `children()` (The API).
- **harptabs.py's `_pre_text`** is core.sites' own (`HarpTabsPages.preText`, lane harptabs'), which the replay's
  `pre` comparison calls for `tree.jsonl`'s `pre` reads: no copy of it in the replay.
