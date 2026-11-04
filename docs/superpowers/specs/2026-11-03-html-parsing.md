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
    val attributes: Map<String, String?>   // the first of duplicates wins; a bare attribute's value is ""
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

- CRLF and a lone CR become LF before tokenizing (`<pre>\nA\r\nB\rC</pre>` reads `A\nB\nC`).
- The LF right after a `<pre>` (and `<listing>`, `<textarea>`) start tag is dropped, as the spec's tree builder does.
- NUL as the spec says for each state (U+FFFD where it replaces one).
- Bytes are decoded as UTF-8 with replacement (`bytes.decode("utf-8", "replace")`, `PyCodec.utf8Replace`), never by a
  `<meta charset>`: caracole's parsers hand selectolax text.

## Character references

- The HTML5 table is Python's `html.entities.html5`, as data: `data/caracole/html/entities.json` (in its order; the
  legacy names listed bare beside their `;` form).
- **In text**, by the tokenizer's rules: the longest name in the table, with or without its `;`
  (`&amp頭` is `&頭`, `&ampx` is `&x`, `&notit;` is `¬it;`); numeric references by the spec's table (`&#x80;` is `€`,
  `&#0;` is U+FFFD).
- **In an attribute value**, the attribute rule: a legacy reference without its `;` followed by `=` or an ASCII
  alphanumeric stays as written (`&ampx` and `&amp=y` kept), otherwise decoded (`&amp頭` is `&頭`).

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

- Set from the doctype by the spec's lists (public id prefixes, the HTML 4.01 transitional and frameset ids without a
  system id), or by a missing doctype; `HtmlDoc.quirks` says which.
- In quirks mode, `#id` and `.class` match without ASCII case (`ul#b_main` finds `<ul id=B_MAIN>`); in standards mode
  they match as written.

## Selectors

The ones caracole's parsers use (the lane greps every `css(` and `css_first(` of `src/caracole/`): a tag, `#id`,
`.class`, `[a]`, `[a=v]`, `[a^=v]`, `[a*=v]`, `[a$=v]`, the descendant combinator, `>`, `+`, and `,`. Matches are in
document order, each node once.
