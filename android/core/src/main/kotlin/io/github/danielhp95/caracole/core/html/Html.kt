package io.github.danielhp95.caracole.core.html

/**
 * The phone's HTML parser, with selectolax's lexbor semantics (docs/superpowers/specs/2026-11-03-html-parsing.md):
 * the WHATWG tokenizer and tree builder, lexbor's text and selectors (lanes html-tokenizer and html-tree).
 */
object Html {
    fun parse(text: String): HtmlDoc = TODO("lane html-tree")

    /** The bytes decoded as UTF-8 with replacement first (PyCodec.utf8Replace), as caracole's parsers hand
     * selectolax text. */
    fun parse(bytes: ByteArray): HtmlDoc = TODO("lane html-tree")
}

/** A page parsed: [quirks] mode from its doctype, its selectors as lexbor answers them. */
class HtmlDoc(val quirks: Boolean) {
    fun css(sel: String): List<HtmlNode> = TODO("lane html-tree")
    fun cssFirst(sel: String): HtmlNode? = TODO("lane html-tree")
}

/** A node of the tree: an element, or a text ("-text") or a comment ("-comment") as selectolax names them. */
class HtmlNode {
    val tag: String get() = TODO("lane html-tree")
    fun attr(name: String): String? = TODO("lane html-tree")

    /** The first of duplicates wins. */
    val attributes: Map<String, String?> get() = TODO("lane html-tree")

    /** lexbor's: script and style data in, nothing for `<br>`, comments out, no separator. */
    fun text(deep: Boolean = true): String = TODO("lane html-tree")
    fun children(includeText: Boolean = true): List<HtmlNode> = TODO("lane html-tree")
    val textContent: String? get() = TODO("lane html-tree")
    val next: HtmlNode? get() = TODO("lane html-tree")
    val isText: Boolean get() = TODO("lane html-tree")
    fun css(sel: String): List<HtmlNode> = TODO("lane html-tree")
    fun cssFirst(sel: String): HtmlNode? = TODO("lane html-tree")
    fun replaceWith(text: String): Unit = TODO("lane html-tree")
    fun insertAfter(text: String): Unit = TODO("lane html-tree")
}
