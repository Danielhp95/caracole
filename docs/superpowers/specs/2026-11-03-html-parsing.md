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
    val tag: String                     // lowercase; "-text", "-comment" as selectolax names them
    fun attr(name: String): String?
    val attributes: Map<String, String?>   // the first of duplicates wins; null where no value was written
    fun text(deep: Boolean = true): String
    fun children(includeText: Boolean = true): List<HtmlNode>
    val textContent: String?            // a text node's text; null for an element
    val next: HtmlNode?
    val isText: Boolean
    fun css(sel: String): List<HtmlNode>; fun cssFirst(sel: String): HtmlNode?
    fun replaceWith(text: String); fun insertAfter(text: String)
}
```

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
  `<style>`'s data included (`var x='<b>';TUV`), nothing for `<br>`, comments left out.
- `text(deep = false)`: the node's own text children alone.
- `children(includeText = true)` lists text nodes as `-text` with their `textContent` (`[('a', None), ('-text',
  '  x '), ('b', None)]`); whitespace-only text nodes kept where the tree builder keeps them.

## The tree

- The insertion modes caracole's pages reach: initial, before html, before head, in head, after head, in body (the
  adoption agency, implied end tags, the scopes), text, in table and its family (in table text, in caption, in column
  group, in table body, in row, in cell, in select in table), after body, after after body.
- Foreign content (svg, math) as the spec builds it: self-closing tags acknowledged, the breakout tags honoured.
- A `<template>`'s contents as ordinary children, as selectolax shows them.

## Quirks mode

- Set from the doctype in the initial insertion mode (The tokenizer, "Quirks mode": `Token.Doctype.mode`), or by a
  missing doctype; `HtmlDoc.quirks` says which.
- In quirks mode, `#id` and `.class` match without ASCII case (`ul#b_main` finds `<ul id=B_MAIN>`); in standards mode
  they match as written.

## Selectors

The ones caracole's parsers use (the lane greps every `css(` and `css_first(` of `src/caracole/`): a tag, `#id`,
`.class`, `[a]`, `[a=v]`, `[a^=v]`, `[a*=v]`, `[a$=v]`, the descendant combinator, `>`, `+`, and `,`. Matches are in
document order, each node once.
