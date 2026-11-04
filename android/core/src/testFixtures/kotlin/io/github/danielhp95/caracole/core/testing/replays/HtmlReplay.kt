package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.html.internal.token.Attribute
import io.github.danielhp95.caracole.core.html.internal.token.CharKind
import io.github.danielhp95.caracole.core.html.internal.token.CompatMode
import io.github.danielhp95.caracole.core.html.internal.token.Content
import io.github.danielhp95.caracole.core.html.internal.token.Preprocess
import io.github.danielhp95.caracole.core.html.internal.token.Token
import io.github.danielhp95.caracole.core.html.internal.token.Tokenizer
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals

/**
 * core.html's tokens (vectors/html/tokens*.jsonl, tests/test_conformance_html.py): for every page caracole reads and
 * the edge set, what lexbor's tokenizer decided as selectolax's tree shows it (the document's mode, the doctype's
 * name, each element's attributes, the text, the comments and processing instructions in document order), read by
 * core.html's tokenizer through [TokensTree], a small tree builder of the replay's own (lane html-tree's is the real
 * one). lexbor's tag and attribute names are ASCII-lowercased before they are compared with the tokenizer's, as it gave
 * them: their SVG and MathML case is the tree's. A `<template>`'s contents are left out, as selectolax's walk never
 * reaches them.
 */
object HtmlReplay : AreaReplay {
    override val area = "html"

    val TOKENS = listOf("html/tokens.jsonl", "html/tokens_edges.jsonl", "html/tokens_soup.jsonl")

    override fun replay(misses: Misses) {
        for (name in TOKENS) {
            val vector = Misses(name)
            var records = 0
            for (record in Corpus.records(name)) {
                assertEquals("test_conformance_html.reads", record.fn)
                records++
                val case = record.extra["case"]?.jsonPrimitive?.content ?: "?"
                val page = page(record.args[0])
                val got = TokensTree.read(page)
                val want = record.out!!.jsonObject
                compare(vector, case, want, got)
            }
            check(records > 0) { "$name has no record" }
            vector.assertNone()
        }
    }

    /** A record's page: its text, or the fixture it names, decoded as caracole's parsers decode bytes. */
    fun page(arg: JsonElement): String =
        if (arg is JsonObject) Preprocess.bytes(Corpus.fixture(arg.getValue("fixture").jsonPrimitive.content))
        else text(arg)

    private fun compare(misses: Misses, case: String, want: JsonObject, got: TokensTree.Read) {
        val quirks = want.getValue("quirks").jsonPrimitive.boolean
        misses.check(quirks == got.quirks) { "$case: quirks ${got.quirks}, lexbor's $quirks" }
        val doctype = want.getValue("doctype").let { if (it is JsonNull) null else it.jsonPrimitive.content }
        misses.check(doctype == got.doctype) { "$case: doctype ${got.doctype}, lexbor's $doctype" }
        val attrs = normalized(want.getValue("attrs").jsonArray.map { pair ->
            val (tag, list) = pair.jsonArray
            text(tag) to list.jsonArray.map { a ->
                val (name, value) = a.jsonArray
                Attribute(text(name), if (value is JsonNull) null else text(value))
            }
        }, lower = true)
        val mine = normalized(got.attrs, lower = false)
        misses.check(attrs == mine) {
            val missing = attrs - mine.toSet()
            val extra = mine - attrs.toSet()
            "$case: attributes differ: lexbor's not read ${missing.take(3)}, read not lexbor's ${extra.take(3)}"
        }
        val text = text(want.getValue("text"))
        misses.check(text == got.text) { "$case: text ${firstDifference(text, got.text)}" }
        val comments = want.getValue("comments").jsonArray.map(::text)
        misses.check(comments == got.comments) { "$case: comments ${got.comments.map(::show)}, lexbor's ${comments.map(::show)}" }
        val pis = want.getValue("pis").jsonArray.map { it.jsonArray.map(::text) }
        misses.check(pis == got.pis) { "$case: processing instructions ${got.pis}, lexbor's $pis" }
    }

    /** Each pair once, in one order; lexbor's names ASCII-lowercased ([lower]), the tokenizer's as it gave them.
     * lexbor's tokenizer lowercases every name, and its tree alone gives an SVG or MathML one its case back
     * (`foreignObject`, `viewBox`): lowercasing its side undoes that, so a name the tokenizer left upper-case
     * still differs. */
    private fun normalized(pairs: List<Pair<String, List<Attribute>>>, lower: Boolean): List<String> {
        fun name(s: String) = if (lower) Py.asciiLower(s) else s
        return pairs.map { (tag, list) ->
            JsonArray(listOf(JsonPrimitive(name(tag)), JsonArray(list.map {
                JsonArray(listOf(JsonPrimitive(name(it.name)), it.value?.let(::JsonPrimitive) ?: JsonNull))
            }))).toString()
        }.distinct().sorted()
    }

    private fun firstDifference(want: String, got: String): String {
        val i = want.indices.firstOrNull { it >= got.length || want[it] != got[it] } ?: got.length
        return "differs at $i: read ${show(got.drop(i).take(40))}, lexbor's ${show(want.drop(i).take(40))} " +
            "(after ${show(want.take(i).takeLast(30))})"
    }
}

/**
 * The tree builder's part the tokenizer's vectors need (WHATWG HTML §13.2.6), just enough of it: where each node
 * goes in document order (the head before what follows it, a comment after `</body>` in the html element, one after
 * `</html>` in the document, the text a table can't hold fostered before it), which start tags it drops or merges
 * (a second `<head>`, `<html>` and `<body>` adding their attributes), the text it drops (whitespace before the head,
 * a NUL in HTML content, the newline after `<pre>`), what it switches the tokenizer to, foreign content and its
 * integration points, the active formatting elements reconstructed (a clone is the same pair, but it is the current
 * node: text at an integration point makes one, an HTML element, before `<![CDATA[` is read), a `<template>`'s
 * contents (never walked, as selectolax's walk never reaches them) and the document's mode. It keeps no exact
 * nesting: no implied end tags, no table modes, and of the adoption agency only that it closes the formatting element
 * and takes it off the list, none of which moves text in document order or changes an attribute.
 */
class TokensTree private constructor(page: String) {
    /** What [read] found: the summary each record of tokens*.jsonl holds. */
    data class Read(val quirks: Boolean, val doctype: String?, val attrs: List<Pair<String, List<Attribute>>>,
                    val text: String, val comments: List<String>, val pis: List<List<String>>)

    companion object {
        fun read(page: String): Read = TokensTree(page).summary()

        private val HEAD_TAGS = setOf("base", "basefont", "bgsound", "link", "meta", "noframes", "script", "style",
                                      "template", "title")
        private val VOID = setOf("area", "br", "embed", "img", "keygen", "wbr", "input", "param", "source", "track",
                                 "hr", "base", "basefont", "bgsound", "link", "meta", "col", "frame", "image")
        private val TABLE_PARTS = setOf("caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr")
        private val TABLE_CONTEXT = setOf("table", "tbody", "tfoot", "thead", "tr")
        private val BREAKOUT = setOf(
            "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em", "embed", "h1", "h2",
            "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu", "meta", "nobr", "ol", "p", "pre",
            "ruby", "s", "small", "span", "strong", "strike", "sub", "sup", "table", "tt", "u", "ul", "var",
        )
        private val MATH_TEXT = setOf("mi", "mo", "mn", "ms", "mtext")
        private val HEADINGS = setOf("h1", "h2", "h3", "h4", "h5", "h6")
        private val BLOCKS = setOf(
            "address", "article", "aside", "blockquote", "button", "center", "details", "dialog", "dir", "div", "dl",
            "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "listing", "main", "menu", "nav", "ol",
            "pre", "search", "section", "summary", "ul", "applet", "marquee", "object", "dd", "dt",
        )
        private val FORMATTING = setOf("a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike",
                                       "strong", "tt", "u")
        /** The start tags in body inserts without reconstructing the active formatting elements first. */
        private val NO_RECONSTRUCTION = BLOCKS - setOf("button", "applet", "marquee", "object") + HEADINGS +
            setOf("p", "rb", "rtc", "rp", "rt", "li", "table")
        private val SCOPE = setOf("applet", "caption", "html", "table", "td", "th", "marquee", "object", "template")
        private val SPECIAL = setOf(
            "address", "applet", "area", "article", "aside", "base", "basefont", "bgsound", "blockquote", "body", "br",
            "button", "caption", "center", "col", "colgroup", "dd", "details", "dir", "div", "dl", "dt", "embed",
            "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4", "h5",
            "h6", "head", "header", "hgroup", "hr", "html", "iframe", "img", "input", "keygen", "li", "link", "listing",
            "main", "marquee", "menu", "meta", "nav", "noembed", "noframes", "noscript", "object", "ol", "p", "param",
            "plaintext", "pre", "script", "search", "section", "select", "source", "style", "summary", "table",
            "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "title", "tr", "track", "ul", "wbr", "xmp",
        )
    }

    private enum class Ns { HTML, SVG, MATH }
    private enum class Mode { INITIAL, BEFORE_HTML, BEFORE_HEAD, IN_HEAD, IN_HEAD_NOSCRIPT, AFTER_HEAD, IN_BODY, TEXT,
                              AFTER_BODY, AFTER_AFTER_BODY }

    private class Node(val name: String, val ns: Ns, val kind: Kind) {
        enum class Kind { DOCUMENT, ELEMENT, TEXT, COMMENT, PI }
        var parent: Node? = null
        val children = ArrayList<Node>()
        val attrs = ArrayList<Attribute>()
        val data = StringBuilder()
        var target = ""
    }

    private val document = Node("#document", Ns.HTML, Node.Kind.DOCUMENT)
    private val stack = ArrayList<Node>()
    private var mode = Mode.INITIAL
    private var original = Mode.INITIAL
    private var quirks = false
    private var doctype: String? = null
    private var head: Node? = null
    private var form: Node? = null
    private var skipNewline = false
    private val pendingTableText = ArrayList<Token.Characters>()
    /** The list of active formatting elements (§13.2.4.3), a null its marker. */
    private val active = ArrayList<Node?>()
    private val tokenizer = Tokenizer(page)

    init {
        tokenizer.foreignContent = { stack.lastOrNull()?.let { it.ns != Ns.HTML } ?: false }
        while (true) {
            var token = tokenizer.next()
            if (skipNewline) {
                skipNewline = false
                if (token is Token.Characters && token.data.startsWith("\n")) {
                    if (token.data.length == 1) continue
                    token = Token.Characters(token.data.substring(1), token.kind)
                }
            }
            if (token !is Token.Characters) flushTableText()
            dispatch(token)
            if (token === Token.EndOfFile) break
        }
    }

    // --- the dispatcher and foreign content ---------------------------------------------------------------------

    private fun current(): Node? = stack.lastOrNull()

    private fun isMathTextPoint(node: Node) = node.ns == Ns.MATH && node.name in MATH_TEXT

    private fun isHtmlPoint(node: Node): Boolean = when (node.ns) {
        Ns.SVG -> node.name in setOf("foreignobject", "desc", "title")
        Ns.MATH -> node.name == "annotation-xml" && node.attrs.any {
            it.name == "encoding" && Py.asciiLower(it.value.orEmpty()) in setOf("text/html", "application/xhtml+xml")
        }
        Ns.HTML -> false
    }

    private fun dispatch(token: Token) {
        val node = current()
        val html = node == null || node.ns == Ns.HTML || token === Token.EndOfFile ||
            (isMathTextPoint(node) && (token is Token.Characters ||
                (token is Token.StartTag && token.name != "mglyph" && token.name != "malignmark"))) ||
            (node.ns == Ns.MATH && node.name == "annotation-xml" && token is Token.StartTag && token.name == "svg") ||
            (isHtmlPoint(node) && (token is Token.StartTag || token is Token.Characters))
        if (html) process(token) else foreign(token)
    }

    private fun foreign(token: Token) {
        when (token) {
            is Token.Characters -> insertText(token.data.replace('\u0000', '�'), foster = false)
            is Token.Comment -> insertComment(token.data, current()!!)
            is Token.ProcessingInstruction -> insertPi(token, current()!!)
            is Token.Doctype, Token.EndOfFile -> {}
            is Token.StartTag -> {
                val breakout = token.name in BREAKOUT ||
                    (token.name == "font" && token.attributes.any { it.name in setOf("color", "face", "size") })
                if (breakout) breakOut(token) else {
                    insertElement(token.name, current()!!.ns, token.attributes)
                    if (token.selfClosing) stack.removeAt(stack.lastIndex)
                }
            }
            is Token.EndTag -> {
                if (token.name == "br" || token.name == "p") { breakOut(token); return }
                var i = stack.lastIndex
                while (i > 0) {
                    val node = stack[i]
                    if (node.name == token.name) { while (stack.size > i) stack.removeAt(stack.lastIndex); return }
                    i--
                    if (stack[i].ns == Ns.HTML) { process(token); return }
                }
            }
        }
    }

    private fun breakOut(token: Token) {
        while (true) {
            val node = current() ?: break
            if (node.ns == Ns.HTML || isMathTextPoint(node) || isHtmlPoint(node)) break
            stack.removeAt(stack.lastIndex)
        }
        process(token)
    }

    // --- the insertion modes -----------------------------------------------------------------------------------

    private fun process(token: Token) {
        when (mode) {
            Mode.INITIAL -> initial(token)
            Mode.BEFORE_HTML -> beforeHtml(token)
            Mode.BEFORE_HEAD -> beforeHead(token)
            Mode.IN_HEAD -> inHead(token)
            Mode.IN_HEAD_NOSCRIPT -> inHeadNoscript(token)
            Mode.AFTER_HEAD -> afterHead(token)
            Mode.IN_BODY -> inBody(token)
            Mode.TEXT -> textMode(token)
            Mode.AFTER_BODY -> afterBody(token)
            Mode.AFTER_AFTER_BODY -> afterAfterBody(token)
        }
    }

    private fun isWhitespace(token: Token) = token is Token.Characters && token.kind == CharKind.WHITESPACE

    private fun initial(token: Token) {
        when {
            isWhitespace(token) -> {}
            token is Token.Comment -> insertComment(token.data, document)
            token is Token.ProcessingInstruction -> insertPi(token, document)
            token is Token.Doctype -> {
                doctype = token.name ?: ""
                quirks = token.mode == CompatMode.QUIRKS
                mode = Mode.BEFORE_HTML
            }
            else -> { quirks = true; mode = Mode.BEFORE_HTML; process(token) }
        }
    }

    private fun beforeHtml(token: Token) {
        when {
            token is Token.Doctype || isWhitespace(token) -> {}
            token is Token.Comment -> insertComment(token.data, document)
            token is Token.ProcessingInstruction -> insertPi(token, document)
            token is Token.StartTag && token.name == "html" -> {
                insertElement("html", Ns.HTML, token.attributes)
                mode = Mode.BEFORE_HEAD
            }
            token is Token.EndTag && token.name !in setOf("head", "body", "html", "br") -> {}
            else -> { insertElement("html", Ns.HTML, emptyList()); mode = Mode.BEFORE_HEAD; process(token) }
        }
    }

    private fun beforeHead(token: Token) {
        when {
            token is Token.Doctype || isWhitespace(token) -> {}
            token is Token.Comment -> insertComment(token.data, current()!!)
            token is Token.ProcessingInstruction -> insertPi(token, current()!!)
            token is Token.StartTag && token.name == "html" -> inBody(token)
            token is Token.StartTag && token.name == "head" -> {
                head = insertElement("head", Ns.HTML, token.attributes)
                mode = Mode.IN_HEAD
            }
            token is Token.EndTag && token.name !in setOf("head", "body", "html", "br") -> {}
            else -> { head = insertElement("head", Ns.HTML, emptyList()); mode = Mode.IN_HEAD; process(token) }
        }
    }

    private fun inHead(token: Token) {
        when {
            isWhitespace(token) -> insertText((token as Token.Characters).data, foster = false)
            token is Token.Comment -> insertComment(token.data, current()!!)
            token is Token.ProcessingInstruction -> insertPi(token, current()!!)
            token is Token.Doctype -> {}
            token is Token.StartTag && token.name == "html" -> inBody(token)
            token is Token.StartTag && token.name in setOf("base", "basefont", "bgsound", "link", "meta") ->
                insertVoid(token.name, token.attributes)
            token is Token.StartTag && token.name == "noscript" -> {
                insertElement("noscript", Ns.HTML, token.attributes)
                mode = Mode.IN_HEAD_NOSCRIPT
            }
            token is Token.StartTag && token.name in HEAD_TAGS -> headElement(token)
            token is Token.StartTag && token.name == "head" -> {}
            token is Token.EndTag && token.name == "head" -> { popUntil("head"); mode = Mode.AFTER_HEAD }
            token is Token.EndTag && token.name == "template" -> endTemplate()
            token is Token.EndTag && token.name !in setOf("body", "html", "br") -> {}
            else -> { popUntil("head"); mode = Mode.AFTER_HEAD; process(token) }
        }
    }

    /** title, style, script, noframes and template, by the in head rules: their text in them; a template's contents
     * by the in body rules (its own mode's, near enough: they are never walked). */
    private fun headElement(token: Token.StartTag) {
        insertElement(token.name, Ns.HTML, token.attributes)
        if (token.name == "template") {
            active += null
            mode = Mode.IN_BODY
            return
        }
        val content = Tokenizer.contentFor(token.name)
        if (content != null) {
            tokenizer.switchTo(content)
            original = mode
            mode = Mode.TEXT
        }
    }

    private fun inHeadNoscript(token: Token) {
        when {
            token is Token.Doctype -> {}
            token is Token.StartTag && token.name == "html" -> inBody(token)
            token is Token.EndTag && token.name == "noscript" -> { popUntil("noscript"); mode = Mode.IN_HEAD }
            isWhitespace(token) || token is Token.Comment || token is Token.ProcessingInstruction ||
                (token is Token.StartTag && token.name in setOf("basefont", "bgsound", "link", "meta", "noframes", "style")) ->
                inHead(token)
            token is Token.StartTag && token.name in setOf("head", "noscript") -> {}
            token is Token.EndTag && token.name != "br" -> {}
            else -> { popUntil("noscript"); mode = Mode.IN_HEAD; process(token) }
        }
    }

    private fun afterHead(token: Token) {
        when {
            isWhitespace(token) -> insertText((token as Token.Characters).data, foster = false)
            token is Token.Comment -> insertComment(token.data, current()!!)
            token is Token.ProcessingInstruction -> insertPi(token, current()!!)
            token is Token.Doctype -> {}
            token is Token.StartTag && token.name == "html" -> inBody(token)
            token is Token.StartTag && token.name == "body" -> {
                insertElement("body", Ns.HTML, token.attributes)
                mode = Mode.IN_BODY
            }
            token is Token.StartTag && token.name in HEAD_TAGS -> {
                val head = head!!
                stack += head
                inHead(token)
                stack.remove(head)
            }
            token is Token.EndTag && token.name == "template" -> inHead(token)
            token is Token.StartTag && token.name == "head" -> {}
            token is Token.EndTag && token.name !in setOf("body", "html", "br") -> {}
            else -> { insertElement("body", Ns.HTML, emptyList()); mode = Mode.IN_BODY; process(token) }
        }
    }

    private fun inBody(token: Token) {
        when (token) {
            is Token.Characters -> when {
                token.kind == CharKind.NULL -> {}
                inTableContext() -> pendingTableText += token
                else -> { reconstruct(foster = false); insertText(token.data, foster = false) }
            }
            is Token.Comment -> insertComment(token.data, current()!!)
            is Token.ProcessingInstruction -> insertPi(token, current()!!)
            is Token.Doctype, Token.EndOfFile -> {}
            is Token.StartTag -> inBodyStart(token)
            is Token.EndTag -> inBodyEnd(token)
        }
    }

    private fun inBodyStart(token: Token.StartTag) {
        val name = token.name
        when {
            name == "html" -> if (!inTemplate()) merge(stack[0], token.attributes)
            name == "body" -> if (!inTemplate() && stack.size >= 2 && stack[1].name == "body") merge(stack[1], token.attributes)
            name in setOf("base", "basefont", "bgsound", "link", "meta") -> insertVoid(name, token.attributes)
            name in HEAD_TAGS -> headElement(token)
            name == "head" || name == "frameset" || name == "frame" -> {}
            name in TABLE_PARTS && !inTableScope("table") -> {} // in body, or in a template opened in the table
            name == "form" -> {
                val inTemplate = inTemplate()
                if (inTableContext()) {
                    if (!inTemplate && form == null) { form = insertElement("form", Ns.HTML, token.attributes); pop() }
                } else if (form == null || inTemplate) {
                    val node = insertElement("form", Ns.HTML, token.attributes)
                    if (!inTemplate) form = node
                }
            }
            name == "pre" || name == "listing" -> { insertElement(name, Ns.HTML, token.attributes); skipNewline = true }
            name == "textarea" -> {
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
                skipNewline = true
                tokenizer.switchTo(Content.RCDATA)
                original = mode
                mode = Mode.TEXT
            }
            name in setOf("iframe", "noembed") -> {
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
                tokenizer.switchTo(Content.RAWTEXT)
                original = mode
                mode = Mode.TEXT
            }
            name == "xmp" -> {
                reconstruct(fosters(name, token))
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
                tokenizer.switchTo(Content.RAWTEXT)
                original = mode
                mode = Mode.TEXT
            }
            name == "plaintext" -> {
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
                tokenizer.switchTo(Content.PLAINTEXT)
            }
            name == "math" || name == "svg" -> {
                reconstruct(fosters(name, token))
                insertElement(name, if (name == "math") Ns.MATH else Ns.SVG, token.attributes,
                              foster = fosters(name, token))
                if (token.selfClosing) pop()
            }
            name in setOf("param", "source", "track", "hr") -> insertVoid(name, token.attributes, fosters(name, token))
            name == "col" -> {
                toTableContext(name)
                insertVoid(name, token.attributes)
            }
            name == "input" && inTableContext() && isHidden(token) -> insertVoid(name, token.attributes)
            name in VOID -> {
                reconstruct(fosters(name, token))
                insertVoid(if (name == "image") "img" else name, token.attributes, fosters(name, token))
            }
            name == "a" -> {
                formattingEntry("a")?.let { open -> // the one still listed closed, then out of the list and the stack
                    adoption("a")
                    stack.remove(open)
                    active.remove(open)
                }
                formatting(token)
            }
            name == "nobr" -> {
                if (inScope("nobr")) adoption("nobr")
                formatting(token)
            }
            name in FORMATTING -> formatting(token)
            name in setOf("applet", "marquee", "object") -> {
                reconstruct(fosters(name, token))
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
                active += null
            }
            name in NO_RECONSTRUCTION -> insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
            name in setOf("td", "th", "caption") -> {
                toTableContext(name)
                insertElement(name, Ns.HTML, token.attributes)
                active += null
            }
            name in TABLE_PARTS -> { toTableContext(name); insertElement(name, Ns.HTML, token.attributes) }
            else -> { // button, select, option, span and any other: the active formatting elements first
                reconstruct(fosters(name, token))
                insertElement(name, Ns.HTML, token.attributes, foster = fosters(name, token))
            }
        }
    }

    /** A formatting element's start tag: the list reconstructed, the element inserted and listed (Noah's Ark: three
     * alike since the last marker are enough). */
    private fun formatting(token: Token.StartTag) {
        reconstruct(fosters(token.name, token))
        val node = insertElement(token.name, Ns.HTML, token.attributes, foster = fosters(token.name, token))
        var alike = 0
        var earliest = -1
        for (i in active.indices.reversed()) {
            val entry = active[i] ?: break
            if (entry.name == node.name && entry.attrs.toSet() == node.attrs.toSet()) { alike++; earliest = i }
        }
        if (alike >= 3) active.removeAt(earliest)
        active += node
    }

    private fun isHidden(token: Token.StartTag) =
        token.attributes.any { it.name == "type" && Py.asciiLower(it.value.orEmpty()) == "hidden" }

    /** Whether a start tag goes before the table it meets (§13.2.6.4.9, "anything else"). */
    private fun fosters(name: String, token: Token.StartTag): Boolean {
        if (!inTableContext()) return false
        if (name in TABLE_PARTS || name in setOf("table", "style", "script", "template", "form")) return false
        if (name == "input" && isHidden(token)) return false
        return true
    }

    private fun inBodyEnd(token: Token.EndTag) {
        val name = token.name
        when {
            name == "template" -> endTemplate()
            name == "body" -> if (inScope("body")) mode = Mode.AFTER_BODY
            name == "html" -> if (inScope("body")) { mode = Mode.AFTER_BODY; process(token) }
            name == "form" -> if (inTemplate()) {
                if (inScope("form")) popUntilHtml(setOf("form"))
            } else {
                val node = form
                form = null
                if (node != null && inScope("form")) stack.remove(node)
            }
            name == "p" -> if (inScope("p", setOf("button"))) popUntilHtml(setOf("p")) // else an empty p: no attribute
            name == "li" -> if (inScope("li", setOf("ol", "ul"))) popUntilHtml(setOf("li"))
            name in HEADINGS -> if (HEADINGS.any { inScope(it) }) popUntilHtml(HEADINGS)
            name in setOf("applet", "marquee", "object") -> if (inScope(name)) { popUntilHtml(setOf(name)); clearToMarker() }
            name in BLOCKS -> if (inScope(name)) popUntilHtml(setOf(name))
            name == "br" -> { reconstruct(foster = false); insertVoid("br", emptyList()) }
            name in FORMATTING -> adoption(name)
            name in setOf("td", "th", "caption") -> if (inTableScope(name)) {
                popUntilHtml(setOf(name))
                clearToMarker()
            }
            name in setOf("table", "tbody", "tfoot", "thead", "tr") -> if (inTableScope(name)) {
                closeThrough(stack.last { it.ns == Ns.HTML && it.name == name })
            }
            else -> anyOtherEndTag(name)
        }
    }

    /** The adoption agency (§13.2.6.4.7), as far as the stack and the list go: the formatting element closed and
     * taken off the list; of what was open in it, each special element (a furthest block, which stays open) and the
     * listed elements before the last of them, which it clones (the same element here: a clone is the same pair).
     * The tree's moves keep text in document order, so this builder leaves the nodes where they are. */
    private fun adoption(name: String) {
        val node = current()
        if (node != null && node.ns == Ns.HTML && node.name == name && node !in active) { pop(); return }
        val element = formattingEntry(name) ?: return anyOtherEndTag(name)
        if (element !in stack) { active.remove(element); return }
        if (!inScopeNode(element)) return
        active.remove(element)
        val at = stack.indexOf(element)
        val inside = stack.subList(at + 1, stack.size).toList()
        while (stack.size > at) pop()
        val last = inside.indexOfLast(::isSpecial)
        for (i in 0..last) if (isSpecial(inside[i]) || inside[i] in active) stack += inside[i]
    }

    /** The last formatting element named [name] since the last marker. */
    private fun formattingEntry(name: String): Node? {
        for (i in active.indices.reversed()) {
            val entry = active[i] ?: return null
            if (entry.name == name) return entry
        }
        return null
    }

    /** Reconstructing the active formatting elements (§13.2.4.3): a clone of each one closed since the last marker
     * or the last still open, in order, the first fostered when [foster] and the current node is a table's. */
    private fun reconstruct(foster: Boolean) {
        if (active.isEmpty()) return
        val last = active.last()
        if (last == null || last in stack) return
        var i = active.lastIndex
        while (i > 0) {
            val before = active[i - 1]
            if (before == null || before in stack) break
            i--
        }
        for (j in i..active.lastIndex) {
            val entry = active[j]!!
            active[j] = insertElement(entry.name, Ns.HTML, entry.attrs, foster = foster && inTableContext())
        }
    }

    private fun clearToMarker() {
        while (active.isNotEmpty()) if (active.removeAt(active.lastIndex) == null) return
    }

    private fun inTemplate() = stack.any { it.ns == Ns.HTML && it.name == "template" }

    /** `</template>` (§13.2.6.4.4): the template and all it holds closed, the list cleared to its marker, and the mode
     * the stack says. */
    private fun endTemplate() {
        val template = stack.lastOrNull { it.ns == Ns.HTML && it.name == "template" } ?: return
        popThrough(template)
        clearToMarker()
        resetMode()
    }

    /** Resetting the insertion mode appropriately (§13.2.4.1), with this builder's modes: a table's and a select's
     * are in body's. */
    private fun resetMode() {
        for (node in stack.asReversed()) {
            if (node.ns != Ns.HTML) continue
            when (node.name) {
                "template", "body" -> { mode = Mode.IN_BODY; return }
                "head" -> if (node !== stack[0]) { mode = Mode.IN_HEAD; return }
                "html" -> { mode = if (head == null) Mode.BEFORE_HEAD else Mode.AFTER_HEAD; return }
            }
        }
        mode = Mode.IN_BODY
    }

    private fun pop() { stack.removeAt(stack.lastIndex) }

    private fun popThrough(node: Node) {
        while (stack.isNotEmpty()) if (stack.removeAt(stack.lastIndex) === node) return
    }

    /** Whether an HTML element [name] is in scope (§13.2.4.2), [more] HTML elements bounding it too. */
    private fun inScope(name: String, more: Set<String> = emptySet()): Boolean {
        for (i in stack.indices.reversed()) {
            val node = stack[i]
            if (node.ns == Ns.HTML && node.name == name) return true
            if (isScopeBoundary(node) || (node.ns == Ns.HTML && node.name in more)) return false
        }
        return false
    }

    /** A table part's start tag in a table (§13.2.6.4.9, in table body, in row, in cell, in caption): an open cell
     * or caption closed, then the stack cleared back to the part's context (no implied `tbody` or `tr`: they hold
     * nothing the vectors record). */
    private fun toTableContext(name: String) {
        for (cell in listOf("td", "th", "caption")) {
            if (inTableScope(cell)) closeThrough(stack.last { it.ns == Ns.HTML && it.name == cell })
        }
        val context = when (name) {
            "td", "th" -> setOf("tr", "tbody", "tfoot", "thead", "table", "template", "html")
            "tr" -> setOf("tbody", "tfoot", "thead", "table", "template", "html")
            else -> setOf("table", "template", "html")
        }
        while (true) {
            val node = current() ?: return
            if (node.ns == Ns.HTML && node.name in context) return
            pop()
        }
    }

    /** The stack popped through [node], the list cleared to its marker for each cell and caption closed. */
    private fun closeThrough(node: Node) {
        while (stack.isNotEmpty()) {
            val popped = stack.removeAt(stack.lastIndex)
            if (popped.ns == Ns.HTML && popped.name in setOf("td", "th", "caption")) clearToMarker()
            if (popped === node) return
        }
    }

    /** Whether an HTML element [name] is in table scope. */
    private fun inTableScope(name: String): Boolean {
        for (node in stack.asReversed()) {
            if (node.ns == Ns.HTML && node.name == name) return true
            if (node.ns == Ns.HTML && node.name in setOf("html", "table", "template")) return false
        }
        return false
    }

    /** Whether [element] itself is in scope. */
    private fun inScopeNode(element: Node): Boolean {
        for (i in stack.indices.reversed()) {
            val node = stack[i]
            if (node === element) return true
            if (isScopeBoundary(node)) return false
        }
        return false
    }

    private fun isScopeBoundary(node: Node): Boolean = when (node.ns) {
        Ns.HTML -> node.name in SCOPE
        Ns.MATH -> node.name in MATH_TEXT || node.name == "annotation-xml"
        Ns.SVG -> node.name in setOf("foreignobject", "desc", "title")
    }

    private fun isSpecial(node: Node): Boolean = when (node.ns) {
        Ns.HTML -> node.name in SPECIAL
        else -> isScopeBoundary(node)
    }

    private fun popUntilHtml(names: Set<String>) {
        val i = stack.indexOfLast { it.ns == Ns.HTML && it.name in names }
        if (i >= 0) while (stack.size > i) stack.removeAt(stack.lastIndex)
    }

    /** §13.2.6.4.7's "any other end tag": the nearest HTML element of that name closed, unless a special one comes
     * first. */
    private fun anyOtherEndTag(name: String) {
        for (i in stack.indices.reversed()) {
            val node = stack[i]
            if (node.ns == Ns.HTML && node.name == name) {
                while (stack.size > i) stack.removeAt(stack.lastIndex)
                return
            }
            if (isSpecial(node)) return
        }
    }

    private fun textMode(token: Token) {
        when (token) {
            is Token.Characters -> insertText(token.data, foster = false)
            is Token.EndOfFile -> { stack.removeAt(stack.lastIndex); mode = original; process(token) }
            is Token.EndTag -> { stack.removeAt(stack.lastIndex); mode = original }
            else -> {}
        }
    }

    private fun afterBody(token: Token) {
        when {
            isWhitespace(token) -> inBody(token)
            token is Token.Comment -> insertComment(token.data, stack[0])
            token is Token.ProcessingInstruction -> insertPi(token, stack[0])
            token is Token.Doctype || token === Token.EndOfFile -> {}
            token is Token.StartTag && token.name == "html" -> inBody(token)
            token is Token.EndTag && token.name == "html" -> mode = Mode.AFTER_AFTER_BODY
            else -> { mode = Mode.IN_BODY; process(token) }
        }
    }

    private fun afterAfterBody(token: Token) {
        when {
            token is Token.Comment -> insertComment(token.data, document)
            token is Token.ProcessingInstruction -> insertPi(token, document)
            token is Token.Doctype || isWhitespace(token) || (token is Token.StartTag && token.name == "html") ->
                inBody(token)
            token === Token.EndOfFile -> {}
            else -> { mode = Mode.IN_BODY; process(token) }
        }
    }

    // --- tables -------------------------------------------------------------------------------------------------

    private fun inTableContext(): Boolean = current()?.let { it.ns == Ns.HTML && it.name in TABLE_CONTEXT } ?: false

    /** The pending table character tokens (§13.2.6.4.10): fostered before the table, whitespace and all, when any is
     * other than whitespace, else inserted where they are. */
    private fun flushTableText() {
        if (pendingTableText.isEmpty()) return
        val foster = pendingTableText.any { it.kind == CharKind.OTHER }
        if (foster) reconstruct(foster = true)
        for (token in pendingTableText) if (token.kind != CharKind.NULL) insertText(token.data, foster && inTableContext())
        pendingTableText.clear()
    }

    /** Where a fostered node goes: before the last table of the stack, in its parent. */
    private fun fosterPlace(): Pair<Node, Int> {
        val table = stack.last { it.name == "table" && it.ns == Ns.HTML }
        val template = stack.lastOrNull { it.name == "template" && it.ns == Ns.HTML }
        if (template != null && stack.indexOf(template) > stack.indexOf(table)) return template to template.children.size
        val parent = table.parent ?: stack[stack.indexOf(table) - 1]
        val index = parent.children.indexOf(table).let { if (it < 0) parent.children.size else it }
        return parent to index
    }

    // --- nodes --------------------------------------------------------------------------------------------------

    private fun place(foster: Boolean): Pair<Node, Int> {
        if (foster) return fosterPlace()
        val parent = current() ?: document
        return parent to parent.children.size
    }

    private fun attach(node: Node, parent: Node, index: Int) {
        node.parent = parent
        parent.children.add(index, node)
    }

    private fun insertElement(name: String, ns: Ns, attrs: List<Attribute>, foster: Boolean = false): Node {
        val node = Node(name, ns, Node.Kind.ELEMENT)
        node.attrs += attrs
        val (parent, index) = place(foster)
        attach(node, parent, index)
        stack += node
        return node
    }

    private fun insertVoid(name: String, attrs: List<Attribute>, foster: Boolean = false) {
        insertElement(name, Ns.HTML, attrs, foster)
        stack.removeAt(stack.lastIndex)
    }

    private fun merge(node: Node, attrs: List<Attribute>) {
        for (a in attrs) if (node.attrs.none { it.name == a.name }) node.attrs += a
    }

    private fun insertText(data: String, foster: Boolean) {
        if (data.isEmpty()) return
        val (parent, index) = place(foster)
        val before = if (index > 0) parent.children[index - 1] else null
        if (before != null && before.kind == Node.Kind.TEXT) {
            before.data.append(data)
        } else {
            val node = Node("#text", Ns.HTML, Node.Kind.TEXT)
            node.data.append(data)
            attach(node, parent, index)
        }
    }

    private fun insertComment(data: String, parent: Node) {
        val node = Node("#comment", Ns.HTML, Node.Kind.COMMENT)
        node.data.append(data)
        attach(node, parent, parent.children.size)
    }

    private fun insertPi(token: Token.ProcessingInstruction, parent: Node) {
        val node = Node("#pi", Ns.HTML, Node.Kind.PI)
        node.target = token.target
        node.data.append(token.data)
        attach(node, parent, parent.children.size)
    }

    private fun popUntil(name: String) {
        val i = stack.indexOfLast { it.name == name }
        if (i >= 0) while (stack.size > i) stack.removeAt(stack.lastIndex)
    }

    // --- the summary --------------------------------------------------------------------------------------------

    private fun summary(): Read {
        val attrs = ArrayList<Pair<String, List<Attribute>>>()
        val text = StringBuilder()
        val comments = ArrayList<String>()
        val pis = ArrayList<List<String>>()
        fun walk(node: Node) {
            for (child in node.children) {
                when (child.kind) {
                    Node.Kind.ELEMENT -> if (child.attrs.isNotEmpty()) attrs += child.name to child.attrs.toList()
                    Node.Kind.TEXT -> text.append(child.data)
                    Node.Kind.COMMENT -> comments += child.data.toString()
                    Node.Kind.PI -> pis += listOf(child.target, child.data.toString())
                    Node.Kind.DOCUMENT -> {}
                }
                if (!(child.ns == Ns.HTML && child.name == "template")) walk(child)
            }
        }
        walk(document)
        return Read(quirks, doctype, attrs, text.toString(), comments, pis)
    }
}
