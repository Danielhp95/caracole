package io.github.danielhp95.caracole.core.html.internal.tree

import io.github.danielhp95.caracole.core.html.internal.token.Attribute
import io.github.danielhp95.caracole.core.html.internal.token.CompatMode
import io.github.danielhp95.caracole.core.html.internal.token.Content
import io.github.danielhp95.caracole.core.html.internal.token.Token
import io.github.danielhp95.caracole.core.html.internal.token.Tokenizer

/**
 * The HTML tree builder (WHATWG HTML §13.2.6) as lexbor 3.1.0 builds trees for selectolax 1.0.0: a port of
 * lexbor/html/tree.c and tree/ (Apache-2.0), insertion mode by insertion mode, so that every page caracole reads
 * gives selectolax's tree (docs/superpowers/specs/2026-11-03-html-parsing.md, "The tree").
 *
 * Where lexbor reads the spec its own way, this does too: `<select>` is an ordinary element and a scope (the
 * customizable select's parsing: no "in select" modes); a token the "in table" mode hands to "in body" is never
 * processed again there (`<table><image>` drops the image); the implied end tags pop by tag name in any namespace;
 * `sup` is no breakout tag of foreign content; a processing instruction is a node, placed as a comment is.
 *
 * Each mode returns true once the token is used, false to process it again in the mode it leaves set, as lexbor's do.
 * Scripting is off, as selectolax parses: `<noscript>`'s contents are markup.
 */
internal class TreeBuilder private constructor(private val tokenizer: Tokenizer) {
    companion object {
        /** [text]'s tree; [preprocessed] when its newlines are normalized already. */
        fun parse(text: String, preprocessed: Boolean = false): Document =
            TreeBuilder(Tokenizer(text, preprocessed)).run()

        private val IMPLIED = setOf("dd", "dt", "li", "optgroup", "option", "p", "rb", "rp", "rt", "rtc")
        private val THOROUGHLY = IMPLIED + setOf("caption", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr")
        private val HEADINGS = setOf("h1", "h2", "h3", "h4", "h5", "h6")
        private val TABLE_TARGETS = setOf("table", "tbody", "tfoot", "thead", "tr")
        private val BREAKOUT = setOf(
            "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em", "embed", "h1",
            "h2", "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing", "menu", "meta", "nobr", "ol", "p",
            "pre", "ruby", "s", "small", "span", "strong", "strike", "sub", "table", "tt", "u", "ul", "var", "font",
        )
        private val BLOCK_END = setOf(
            "address", "article", "aside", "blockquote", "button", "center", "details", "dialog", "dir", "div", "dl",
            "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "listing", "main", "menu", "nav", "ol",
            "pre", "search", "section", "select", "summary", "ul",
        )
        private val BLOCK_START = setOf(
            "address", "article", "aside", "blockquote", "center", "details", "dialog", "dir", "div", "dl",
            "fieldset", "figcaption", "figure", "footer", "header", "hgroup", "main", "menu", "nav", "ol", "p",
            "search", "section", "summary", "ul",
        )
        private val FORMATTING_END = setOf(
            "a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small", "strike", "strong", "tt", "u",
        )
        private val FORMATTING_START = setOf(
            "b", "big", "code", "em", "font", "i", "s", "small", "strike", "strong", "tt", "u",
        )
        private val HEAD_TAGS = setOf(
            "base", "basefont", "bgsound", "link", "meta", "noframes", "script", "style", "template", "title",
        )
        private val IGNORED_IN_BODY = setOf(
            "caption", "col", "colgroup", "frame", "head", "tbody", "td", "tfoot", "th", "thead", "tr",
        )
        private const val TEXT = "#text"
        private const val COMMENT = "#comment"
        private const val PI = "#pi"
        private const val DOCTYPE = "#doctype"
        private const val EOF = "#eof"
    }

    /** A token as lexbor's tree builder reads and changes it: [tag] a tag's name, or one of [TEXT], [COMMENT], [PI],
     * [DOCTYPE] and [EOF]; [end] for an end tag. */
    private class Tk(
        var tag: String,
        var end: Boolean = false,
        var attrs: List<Attribute> = emptyList(),
        val selfClosing: Boolean = false,
        var text: String = "",
        val target: String = "",
        val doctype: Token.Doctype? = null,
        /** The element a clone copies its attributes from (lexbor's `base_element`). */
        val base: Element? = null,
    )

    private enum class Mode {
        INITIAL, BEFORE_HTML, BEFORE_HEAD, IN_HEAD, IN_HEAD_NOSCRIPT, AFTER_HEAD, IN_BODY, TEXT, IN_TABLE,
        IN_TABLE_TEXT, IN_CAPTION, IN_COLUMN_GROUP, IN_TABLE_BODY, IN_ROW, IN_CELL, IN_TEMPLATE, AFTER_BODY,
        IN_FRAMESET, AFTER_FRAMESET, AFTER_AFTER_BODY, AFTER_AFTER_FRAMESET, SKIP_NEWLINE, SKIP_NEWLINE_TEXTAREA,
    }

    private enum class Adjust { NONE, MATH, SVG }

    private val document = Document()
    private val open = ArrayList<Element>()

    /** The list of active formatting elements; null is a marker. */
    private val formatting = ArrayList<Element?>()
    private val templateModes = ArrayList<Mode>()
    private var mode = Mode.INITIAL
    private var originalMode = Mode.INITIAL
    private var head: Element? = null
    private var form: Element? = null
    private var framesetOk = true
    private var fosterParenting = false
    private var adjust = Adjust.NONE
    private val pendingTable = ArrayList<String>()
    private var pendingNonWhitespace = false
    private var stopped = false
    private var pushedBack: Token? = null

    private fun run(): Document {
        tokenizer.foreignContent = { adjustedCurrent().let { it != null && it.ns != Ns.HTML } }
        while (!stopped) {
            val next = pushedBack ?: tokenizer.next()
            pushedBack = null
            if (next is Token.Characters && mode == Mode.AFTER_AFTER_FRAMESET && current()?.ns == Ns.HTML) {
                afterAfterFramesetText(next)
                continue
            }
            val token = tk(next)
            while (!dispatch(token)) { /* processed again */ }
            if (token.tag == EOF) break
        }
        return document
    }

    /**
     * Text after `</html>` after a frameset, the one place where lexbor's text token, the whole run of characters
     * between two other tokens, decides more than the tokenizer's pieces of it: all whitespace, it goes to "in body";
     * else none of it does, its whitespace too (`</html> x ` adds no text).
     */
    private fun afterAfterFramesetText(first: Token.Characters) {
        val run = arrayListOf(first)
        while (true) {
            val next = tokenizer.next()
            if (next is Token.Characters) run += next else {
                pushedBack = next
                break
            }
        }
        if (!run.all { onlyWhitespace(it.data) }) return
        for (piece in run) {
            val token = tk(piece)
            while (!dispatch(token)) { /* processed again */ }
        }
    }

    private fun tk(token: Token): Tk = when (token) {
        is Token.StartTag -> Tk(token.name, attrs = token.attributes, selfClosing = token.selfClosing)
        is Token.EndTag -> Tk(token.name, end = true)
        is Token.Characters -> Tk(TEXT, text = token.data)
        is Token.Comment -> Tk(COMMENT, text = token.data)
        is Token.ProcessingInstruction -> Tk(PI, target = token.target, text = token.data)
        is Token.Doctype -> Tk(DOCTYPE, doctype = token)
        Token.EndOfFile -> Tk(EOF)
    }

    // --- the dispatcher (lxb_html_tree_construction_dispatcher) ----------------------------------------------

    private fun dispatch(t: Tk): Boolean {
        val adjusted = adjustedCurrent()
        if (adjusted == null || adjusted.ns == Ns.HTML) return mode(t)
        if (mathTextIntegrationPoint(adjusted)) {
            if (!t.end && t.tag != "mglyph" && t.tag != "malignmark") return mode(t)
            if (t.tag == TEXT) return mode(t)
        }
        if (adjusted.ns == Ns.MATH && adjusted.local == "annotation-xml" && !t.end && t.tag == "svg") return mode(t)
        if (htmlIntegrationPoint(adjusted) && (!t.end || t.tag == TEXT)) return mode(t)
        if (t.tag == EOF) return mode(t)
        return foreignContent(t)
    }

    private fun mode(t: Tk): Boolean = when (mode) {
        Mode.INITIAL -> initial(t)
        Mode.BEFORE_HTML -> beforeHtml(t)
        Mode.BEFORE_HEAD -> beforeHead(t)
        Mode.IN_HEAD -> inHead(t)
        Mode.IN_HEAD_NOSCRIPT -> inHeadNoscript(t)
        Mode.AFTER_HEAD -> afterHead(t)
        Mode.IN_BODY -> inBody(t)
        Mode.TEXT -> text(t)
        Mode.IN_TABLE -> inTable(t)
        Mode.IN_TABLE_TEXT -> inTableText(t)
        Mode.IN_CAPTION -> inCaption(t)
        Mode.IN_COLUMN_GROUP -> inColumnGroup(t)
        Mode.IN_TABLE_BODY -> inTableBody(t)
        Mode.IN_ROW -> inRow(t)
        Mode.IN_CELL -> inCell(t)
        Mode.IN_TEMPLATE -> inTemplate(t)
        Mode.AFTER_BODY -> afterBody(t)
        Mode.IN_FRAMESET -> inFrameset(t)
        Mode.AFTER_FRAMESET -> afterFrameset(t)
        Mode.AFTER_AFTER_BODY -> afterAfterBody(t)
        Mode.AFTER_AFTER_FRAMESET -> afterAfterFrameset(t)
        Mode.SKIP_NEWLINE, Mode.SKIP_NEWLINE_TEXTAREA -> skipNewline(t)
    }

    // --- the stack of open elements and the list of active formatting elements -----------------------------

    private fun current(): Element? = open.lastOrNull()

    private fun adjustedCurrent(): Element? = current()

    private fun pop(): Element? = if (open.isEmpty()) null else open.removeAt(open.size - 1)

    private fun popUntilTag(tag: String, ns: Ns = Ns.HTML) {
        while (open.isNotEmpty()) {
            val node = open.removeAt(open.size - 1)
            if (node.local == tag && node.ns == ns) return
        }
    }

    /** Pops up to [node], [node] too unless [keep]. */
    private fun popUntilNode(node: Element, keep: Boolean = false) {
        while (open.isNotEmpty()) {
            val popped = open.removeAt(open.size - 1)
            if (popped === node) {
                if (keep) open.add(popped)
                return
            }
        }
    }

    private fun popUntilAny(tags: Set<String>) {
        while (open.isNotEmpty()) {
            val node = open.removeAt(open.size - 1)
            if (node.local in tags && node.ns == Ns.HTML) return
        }
    }

    private fun removeOpen(node: Element) {
        val i = open.indexOfLast { it === node }
        if (i >= 0) open.removeAt(i)
    }

    private fun findOpen(tag: String): Element? = open.firstOrNull { it.local == tag && it.ns == Ns.HTML }

    private fun findOpenReverse(tag: String): Int = open.indexOfLast { it.local == tag && it.ns == Ns.HTML }

    private fun inScope(tag: String, category: Int, ns: Ns = Ns.HTML): Element? {
        for (i in open.indices.reversed()) {
            val node = open[i]
            if (node.local == tag && node.ns == ns) return node
            if (Tags.isCategory(node, category)) return null
        }
        return null
    }

    private fun inScopeByNode(target: Element, category: Int): Element? {
        for (i in open.indices.reversed()) {
            val node = open[i]
            if (node === target) return node
            if (Tags.isCategory(node, category)) return null
        }
        return null
    }

    private fun inScopeAny(tags: Set<String>, category: Int): Element? {
        for (i in open.indices.reversed()) {
            val node = open[i]
            if (node.local in tags && node.ns == Ns.HTML) return node
            if (Tags.isCategory(node, category)) return null
        }
        return null
    }

    private fun generateImpliedEndTags(except: String? = null, set: Set<String> = IMPLIED) {
        while (open.isNotEmpty()) {
            val node = open.last()
            if (node.local !in set) return
            if (node.local == except && node.ns == Ns.HTML) return
            open.removeAt(open.size - 1)
        }
    }

    private fun closeP() {
        generateImpliedEndTags(except = "p")
        popUntilTag("p")
    }

    private fun closePInButtonScope() {
        if (inScope("p", Tags.SCOPE_BUTTON) != null) closeP()
    }

    private fun parsingTemplateContents() = findOpenReverse("template") >= 0

    private fun pushMarker() {
        formatting.add(null)
    }

    private fun formattingUpToLastMarker() {
        while (formatting.isNotEmpty()) {
            if (formatting.removeAt(formatting.size - 1) == null) return
        }
    }

    private fun removeFormatting(node: Element) {
        val i = formatting.indexOfLast { it === node }
        if (i >= 0) formatting.removeAt(i)
    }

    private fun formattingIndex(node: Element): Int = formatting.indexOfLast { it === node }

    /** lexbor's `lxb_html_tree_active_formatting_reconstruct_elements`. */
    private fun reconstructFormatting() {
        if (formatting.isEmpty()) return
        var i = formatting.size - 1
        val last = formatting[i]
        if (last == null || open.any { it === last }) return
        while (i != 0) {
            i--
            val entry = formatting[i]
            if (entry == null || open.any { it === entry }) {
                i++
                break
            }
        }
        while (i < formatting.size) {
            val entry = formatting[i]!!
            formatting[i] = insertHtmlElement(Tk(entry.local, base = entry))
            i++
        }
    }

    private fun formattingBetweenLastMarker(tag: String): Element? {
        for (i in formatting.indices.reversed()) {
            val entry = formatting[i] ?: return null
            if (entry.local == tag && entry.ns == Ns.HTML) return entry
        }
        return null
    }

    /** lexbor's `lxb_html_tree_active_formatting_push_with_check_dupl`: the Noah's Ark clause. */
    private fun pushFormatting(node: Element) {
        var i = formatting.size
        var earliest = if (i != 0) i - 1 else 0
        var count = 0
        while (i != 0) {
            i--
            val entry = formatting[i] ?: break
            if (entry.local == node.local && entry.ns == node.ns && sameElement(entry, node)) {
                count++
                earliest = i
            }
        }
        if (count >= 3 && earliest < formatting.size) formatting.removeAt(earliest)
        formatting.add(node)
    }

    /** lexbor's `lxb_dom_element_compare`. */
    private fun sameElement(a: Element, b: Element): Boolean {
        if (a.local != b.local || a.ns != b.ns || a.name != b.name) return false
        if (a.attributes.size != b.attributes.size) return false
        return a.attributes.all { x ->
            b.attributes.any { y ->
                x.local == y.local && x.ns == y.ns && x.qualified == y.qualified && x.value == y.value
            }
        }
    }

    // --- inserting nodes ----------------------------------------------------------------------------------

    /** Where a node goes: inside [node], after its last child, or right before it ([before]). */
    private class Place(val node: Node, val before: Boolean)

    /** lexbor's `lxb_html_tree_appropriate_place_inserting_node`. */
    private fun appropriatePlace(override: Node? = null): Place {
        val target: Node = override ?: checkNotNull(current()) { "no current node" }
        var adjusted: Node
        var before = false
        if (fosterParenting && target is Element && target.ns == Ns.HTML && target.local in TABLE_TARGETS) {
            val lastTemplate = findOpenReverse("template")
            val lastTable = findOpenReverse("table")
            if (lastTemplate >= 0 && (lastTable < 0 || lastTemplate > lastTable)) {
                return Place(open[lastTemplate].content!!, false)
            } else if (lastTable < 0) {
                adjusted = open[0]
            } else if (open[lastTable].parent != null) {
                adjusted = open[lastTable]
                before = true
            } else {
                adjusted = open[lastTable - 1]
            }
        } else {
            adjusted = target
        }
        if (adjusted is Element && adjusted.isHtml("template")) adjusted = adjusted.content!!
        return Place(adjusted, before)
    }

    private fun insertAt(place: Place, node: Node) {
        if (place.before) place.node.insertBefore(node) else place.node.append(node)
    }

    private fun createElement(t: Tk, ns: Ns, name: String = t.tag): Element {
        val element = Element(t.tag, ns, name)
        val base = t.base
        if (base == null) appendAttributes(element, t.attrs, ns)
        else for (a in base.attributes) element.attributes.add(Attr(a.local, a.qualified, a.value, a.ns))
        return element
    }

    private fun nsName(ns: Ns) = when (ns) {
        Ns.HTML -> "html"
        Ns.MATH -> "math"
        Ns.SVG -> "svg"
    }

    /** lexbor's `lxb_html_tree_append_attributes`: each of [attrs] an element has no attribute of yet, adjusted as
     * [adjust] says. */
    private fun appendAttributes(element: Element, attrs: List<Attribute>, ns: Ns) {
        val nsName = nsName(ns)
        for (a in attrs) {
            if (element.attributes.any { (it.local == a.name && it.ns == nsName) || it.qualified == a.name }) continue
            element.attributes.add(adjusted(a, nsName))
        }
    }

    private fun adjusted(a: Attribute, nsName: String): Attr {
        var local = a.name
        var qualified: String? = null
        var ns = nsName
        when (adjust) {
            Adjust.NONE -> return Attr(local, null, a.value, ns)
            Adjust.MATH -> if (local == "definitionurl") qualified = "definitionURL"
            Adjust.SVG -> Tags.SVG_ATTRIBUTES[local]?.let { qualified = it }
        }
        val part = Tags.FOREIGN_LOCAL[local]
        if (part != null) {
            qualified = local
            ns = local.substringBefore(':')
            local = part
        } else if (local == "xmlns") {
            ns = "xmlns"
        }
        return Attr(local, qualified, a.value, ns)
    }

    private fun insertForeignElement(t: Tk, ns: Ns, name: String = t.tag): Element {
        val place = appropriatePlace()
        val element = createElement(t, ns, name)
        insertAt(place, element)
        open.add(element)
        return element
    }

    private fun insertHtmlElement(t: Tk): Element = insertForeignElement(t, Ns.HTML)

    /** lexbor's `lxb_html_tree_insert_character_for_data`. */
    private fun insertCharacters(data: String) {
        val place = appropriatePlace()
        if (place.node is Document) return
        val adjacent = if (place.before) place.node.prev else place.node.lastChild
        if (adjacent is Text) adjacent.add(data) else insertAt(place, Text(data))
    }

    private fun insertComment(t: Tk, at: Node? = null) {
        val place = if (at == null) appropriatePlace() else Place(at, false)
        insertAt(place, Comment(t.text))
    }

    private fun insertPi(t: Tk, at: Node? = null) {
        insertAt(appropriatePlace(at), ProcessingInstruction(t.target, t.text))
    }

    private fun rawtext(t: Tk) {
        insertHtmlElement(t)
        tokenizer.switchTo(Content.RAWTEXT)
        originalMode = mode
        mode = Mode.TEXT
    }

    private fun rcdata(t: Tk) {
        insertHtmlElement(t)
        tokenizer.switchTo(Content.RCDATA)
        originalMode = mode
        mode = Mode.TEXT
    }

    private fun resetInsertionMode() {
        var i = open.size
        while (i != 0) {
            i--
            val node = open[i]
            val last = i == 0
            if (node.ns != Ns.HTML) {
                if (last) {
                    mode = Mode.IN_BODY
                    return
                }
                continue
            }
            when (node.local) {
                "td", "th" -> if (!last) {
                    mode = Mode.IN_CELL
                    return
                }
                "tr" -> { mode = Mode.IN_ROW; return }
                "tbody", "tfoot", "thead" -> { mode = Mode.IN_TABLE_BODY; return }
                "caption" -> { mode = Mode.IN_CAPTION; return }
                "colgroup" -> { mode = Mode.IN_COLUMN_GROUP; return }
                "table" -> { mode = Mode.IN_TABLE; return }
                "template" -> { mode = templateModes.lastOrNull() ?: Mode.IN_BODY; return }
                "head" -> if (!last) {
                    mode = Mode.IN_HEAD
                    return
                }
                "body" -> { mode = Mode.IN_BODY; return }
                "frameset" -> { mode = Mode.IN_FRAMESET; return }
                "html" -> { mode = if (head == null) Mode.BEFORE_HEAD else Mode.AFTER_HEAD; return }
            }
            if (last) {
                mode = Mode.IN_BODY
                return
            }
        }
    }

    private fun mathTextIntegrationPoint(node: Element) =
        node.ns == Ns.MATH && node.local in setOf("mi", "mo", "mn", "ms", "mtext")

    private fun htmlIntegrationPoint(node: Element): Boolean {
        if (node.ns == Ns.MATH && node.local == "annotation-xml") {
            val encoding = node.attributes.firstOrNull { it.local == "encoding" || it.qualified == "encoding" }?.value
                ?: return false
            return asciiEqualsIgnoringCase(encoding, "text/html") ||
                asciiEqualsIgnoringCase(encoding, "application/xhtml+xml")
        }
        return node.ns == Ns.SVG && (node.local == "foreignobject" || node.local == "desc" || node.local == "title")
    }

    // --- text ---------------------------------------------------------------------------------------------

    private fun isAsciiSpace(c: Char) = c == '\t' || c == '\n' || c == '\u000C' || c == '\r' || c == ' '

    private fun skipWhitespace(s: String): String {
        var i = 0
        while (i < s.length && isAsciiSpace(s[i])) i++
        return if (i == 0) s else s.substring(i)
    }

    /** The whitespace [t]'s text begins with, inserted; true when nothing is left of it. */
    private fun insertLeadingWhitespace(t: Tk): Boolean {
        var i = 0
        while (i < t.text.length && isAsciiSpace(t.text[i])) i++
        if (i == 0) return t.text.isEmpty()
        insertCharacters(t.text.substring(0, i))
        t.text = t.text.substring(i)
        return t.text.isEmpty()
    }

    private fun onlyWhitespace(s: String) = s.all(::isAsciiSpace)

    private fun dropNul(s: String) = if (s.indexOf('\u0000') < 0) s else s.replace("\u0000", "")

    private fun asciiEqualsIgnoringCase(a: String, b: String) =
        a.length == b.length && a.indices.all { lowerAscii(a[it]) == lowerAscii(b[it]) }

    private fun lowerAscii(c: Char) = if (c in 'A'..'Z') c + 32 else c

    // --- the insertion modes ------------------------------------------------------------------------------

    private fun initial(t: Tk): Boolean {
        when (t.tag) {
            COMMENT -> insertComment(t, document)
            PI -> insertPi(t, document)
            DOCTYPE -> {
                mode = Mode.BEFORE_HTML
                val d = t.doctype!!
                document.append(DoctypeNode(d.name, d.publicId, d.systemId))
                when (d.mode) {
                    CompatMode.QUIRKS -> document.quirks = true
                    CompatMode.LIMITED_QUIRKS -> document.limitedQuirks = true
                    CompatMode.NO_QUIRKS -> {}
                }
            }
            else -> {
                if (t.tag == TEXT) {
                    t.text = skipWhitespace(t.text)
                    if (t.text.isEmpty()) return true
                }
                document.quirks = true
                mode = Mode.BEFORE_HTML
                return false
            }
        }
        return true
    }

    private fun beforeHtml(t: Tk): Boolean {
        if (t.end) {
            return if (t.tag in setOf("head", "body", "html", "br")) beforeHtmlAnythingElse() else true
        }
        when (t.tag) {
            DOCTYPE -> {}
            COMMENT -> insertComment(t, document)
            PI -> insertPi(t, document)
            "html" -> {
                val html = createElement(t, Ns.HTML)
                open.add(html)
                document.append(html)
                mode = Mode.BEFORE_HEAD
            }
            else -> {
                if (t.tag == TEXT) {
                    t.text = skipWhitespace(t.text)
                    if (t.text.isEmpty()) return true
                }
                return beforeHtmlAnythingElse()
            }
        }
        return true
    }

    private fun beforeHtmlAnythingElse(): Boolean {
        val html = Element("html", Ns.HTML)
        open.add(html)
        document.append(html)
        mode = Mode.BEFORE_HEAD
        return false
    }

    private fun beforeHead(t: Tk): Boolean {
        if (t.end) {
            return if (t.tag in setOf("head", "body", "html", "br")) beforeHeadAnythingElse() else true
        }
        when (t.tag) {
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> return inBody(t)
            "head" -> {
                head = insertHtmlElement(t)
                mode = Mode.IN_HEAD
            }
            else -> {
                if (t.tag == TEXT) {
                    t.text = skipWhitespace(t.text)
                    if (t.text.isEmpty()) return true
                }
                return beforeHeadAnythingElse()
            }
        }
        return true
    }

    private fun beforeHeadAnythingElse(): Boolean {
        head = insertHtmlElement(Tk("head"))
        mode = Mode.IN_HEAD
        return false
    }

    private fun inHead(t: Tk): Boolean {
        if (t.end) {
            when (t.tag) {
                "head" -> {
                    pop()
                    mode = Mode.AFTER_HEAD
                }
                "body", "html", "br" -> return inHeadAnythingElse()
                "template" -> return templateEnd()
            }
            return true
        }
        when (t.tag) {
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> return inBody(t)
            "base", "basefont", "bgsound", "link", "meta" -> {
                insertHtmlElement(t)
                pop()
            }
            "title" -> rcdata(t)
            "noscript" -> {
                insertHtmlElement(t)
                mode = Mode.IN_HEAD_NOSCRIPT
            }
            "noframes", "style" -> rawtext(t)
            "script" -> {
                val place = appropriatePlace()
                val element = createElement(t, Ns.HTML)
                open.add(element)
                insertAt(place, element)
                tokenizer.switchTo(Content.SCRIPT_DATA)
                originalMode = mode
                mode = Mode.TEXT
            }
            "template" -> {
                insertHtmlElement(t)
                pushMarker()
                framesetOk = false
                mode = Mode.IN_TEMPLATE
                templateModes.add(Mode.IN_TEMPLATE)
            }
            "head" -> {}
            TEXT -> {
                if (insertLeadingWhitespace(t)) return true
                return inHeadAnythingElse()
            }
            else -> return inHeadAnythingElse()
        }
        return true
    }

    private fun templateEnd(): Boolean {
        if (findOpenReverse("template") < 0) return true
        generateImpliedEndTags(set = THOROUGHLY)
        popUntilTag("template")
        formattingUpToLastMarker()
        templateModes.removeLastOrNull()
        resetInsertionMode()
        return true
    }

    private fun inHeadAnythingElse(): Boolean {
        pop()
        mode = Mode.AFTER_HEAD
        return false
    }

    private fun inHeadNoscript(t: Tk): Boolean {
        if (t.end) {
            if (t.tag == "br") return inHeadNoscriptAnythingElse()
            if (t.tag == "noscript") {
                pop()
                mode = Mode.IN_HEAD
            }
            return true
        }
        when (t.tag) {
            DOCTYPE -> {}
            "html" -> return inBody(t)
            COMMENT, PI, "basefont", "bgsound", "link", "meta", "noframes", "style" -> return inHead(t)
            "head", "noscript" -> {}
            TEXT -> {
                if (insertLeadingWhitespace(t)) return true
                return inHeadNoscriptAnythingElse()
            }
            else -> return inHeadNoscriptAnythingElse()
        }
        return true
    }

    private fun inHeadNoscriptAnythingElse(): Boolean {
        pop()
        mode = Mode.IN_HEAD
        return false
    }

    private fun afterHead(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "template" -> inHead(t)
                "body", "html", "br" -> afterHeadAnythingElse()
                else -> true
            }
        }
        when (t.tag) {
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> return inBody(t)
            "body" -> {
                insertHtmlElement(t)
                framesetOk = false
                mode = Mode.IN_BODY
            }
            "frameset" -> {
                insertHtmlElement(t)
                mode = Mode.IN_FRAMESET
            }
            in HEAD_TAGS -> {
                val head = this.head!!
                open.add(head)
                inHead(t)
                removeOpen(head)
            }
            "head" -> {}
            TEXT -> {
                if (insertLeadingWhitespace(t)) return true
                return afterHeadAnythingElse()
            }
            else -> return afterHeadAnythingElse()
        }
        return true
    }

    private fun afterHeadAnythingElse(): Boolean {
        insertHtmlElement(Tk("body"))
        framesetOk = true
        mode = Mode.IN_BODY
        return false
    }

    private fun text(t: Tk): Boolean {
        when (t.tag) {
            TEXT -> insertCharacters(t.text)
            EOF -> {
                pop()
                mode = originalMode
                return false
            }
            else -> {
                pop()
                mode = originalMode
            }
        }
        return true
    }

    private fun skipNewline(t: Tk): Boolean {
        mode = originalMode
        if (t.tag != TEXT) return false
        if (t.text.startsWith('\n')) t.text = t.text.substring(1)
        return t.text.isEmpty()
    }

    // --- in body ------------------------------------------------------------------------------------------

    private fun inBody(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "template" -> inHead(t)
                "body" -> {
                    if (inScope("body", Tags.SCOPE) != null) mode = Mode.AFTER_BODY
                    true
                }
                "html" -> {
                    if (inScope("body", Tags.SCOPE) == null) return true
                    mode = Mode.AFTER_BODY
                    false
                }
                in BLOCK_END -> {
                    if (inScope(t.tag, Tags.SCOPE) == null) return true
                    generateImpliedEndTags()
                    popUntilTag(t.tag)
                    true
                }
                "form" -> formEnd()
                "p" -> {
                    if (inScope("p", Tags.SCOPE_BUTTON) == null) insertHtmlElement(Tk("p"))
                    closeP()
                    true
                }
                "li" -> {
                    if (inScope("li", Tags.SCOPE_LIST_ITEM) == null) return true
                    generateImpliedEndTags(except = "li")
                    popUntilTag("li")
                    true
                }
                "dd", "dt" -> {
                    if (inScope(t.tag, Tags.SCOPE) == null) return true
                    generateImpliedEndTags(except = t.tag)
                    popUntilTag(t.tag)
                    true
                }
                in HEADINGS -> {
                    if (inScopeAny(HEADINGS, Tags.SCOPE) == null) return true
                    generateImpliedEndTags()
                    popUntilAny(HEADINGS)
                    true
                }
                in FORMATTING_END -> if (adoptionAgency(t)) anyOtherEndTag(t) else true
                "applet", "marquee", "object" -> {
                    if (inScope(t.tag, Tags.SCOPE) == null) return true
                    generateImpliedEndTags()
                    popUntilTag(t.tag)
                    formattingUpToLastMarker()
                    true
                }
                "br" -> {
                    t.end = false
                    t.attrs = emptyList()
                    voidFormatting(t)
                }
                else -> anyOtherEndTag(t)
            }
        }
        when (t.tag) {
            TEXT -> {
                val data = dropNul(t.text)
                if (data.isNotEmpty()) appendBodyText(data)
            }
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> {
                if (findOpen("template") == null) appendAttributes(open[0], t.attrs, open[0].ns)
            }
            in HEAD_TAGS -> return inHead(t)
            "body" -> {
                val body = open.getOrNull(1)
                if (body == null || body.local != "body") return true
                if (findOpenReverse("template") >= 0) return true
                framesetOk = false
                appendAttributes(body, t.attrs, body.ns)
            }
            "frameset" -> {
                val body = open.getOrNull(1)
                if (body == null || body.local != "body") return true
                if (!framesetOk) return true
                body.remove()
                popUntilNode(open[0], keep = true)
                insertHtmlElement(t)
                mode = Mode.IN_FRAMESET
            }
            EOF -> {
                if (templateModes.isNotEmpty()) return inTemplate(t)
                stopped = true
            }
            in BLOCK_START -> {
                closePInButtonScope()
                insertHtmlElement(t)
            }
            in HEADINGS -> {
                closePInButtonScope()
                if (current()!!.local in HEADINGS) pop()
                insertHtmlElement(t)
            }
            "pre", "listing" -> {
                closePInButtonScope()
                insertHtmlElement(t)
                originalMode = mode
                mode = Mode.SKIP_NEWLINE
                framesetOk = false
            }
            "form" -> {
                val inTemplate = parsingTemplateContents()
                if (form != null && !inTemplate) return true
                closePInButtonScope()
                val element = insertHtmlElement(t)
                if (!inTemplate) form = element
            }
            "li" -> listItem(t, setOf("li"))
            "dd", "dt" -> listItem(t, setOf("dd", "dt"))
            "plaintext" -> {
                closePInButtonScope()
                insertHtmlElement(t)
                tokenizer.switchTo(Content.PLAINTEXT)
            }
            "button" -> {
                if (inScope("button", Tags.SCOPE) != null) {
                    generateImpliedEndTags()
                    popUntilTag("button")
                }
                reconstructFormatting()
                insertHtmlElement(t)
                framesetOk = false
            }
            "a" -> {
                val active = formattingBetweenLastMarker("a")
                if (active != null) {
                    adoptionAgency(t)
                    removeFormatting(active)
                    removeOpen(active)
                }
                reconstructFormatting()
                pushFormatting(insertHtmlElement(t))
            }
            in FORMATTING_START -> {
                reconstructFormatting()
                pushFormatting(insertHtmlElement(t))
            }
            "nobr" -> {
                reconstructFormatting()
                if (inScope("nobr", Tags.SCOPE) != null) {
                    if (adoptionAgency(t)) anyOtherEndTag(t)
                    reconstructFormatting()
                }
                pushFormatting(insertHtmlElement(t))
            }
            "applet", "marquee", "object" -> {
                reconstructFormatting()
                insertHtmlElement(t)
                pushMarker()
                framesetOk = false
            }
            "table" -> {
                if (!document.quirks) closePInButtonScope()
                insertHtmlElement(t)
                framesetOk = false
                mode = Mode.IN_TABLE
            }
            "area", "br", "embed", "img", "keygen", "wbr" -> return voidFormatting(t)
            "input" -> {
                inScope("select", Tags.SCOPE)?.let { popUntilNode(it) }
                reconstructFormatting()
                val element = insertHtmlElement(t)
                pop()
                val type = element.attributes.firstOrNull { it.local == "type" || it.qualified == "type" }
                if (type == null || type.value != "hidden") framesetOk = false
            }
            "param", "source", "track" -> {
                insertHtmlElement(t)
                pop()
            }
            "hr" -> {
                closePInButtonScope()
                if (inScope("select", Tags.SCOPE) != null) generateImpliedEndTags()
                insertHtmlElement(t)
                pop()
                framesetOk = false
            }
            "image" -> {
                t.tag = "img"
                return false
            }
            "textarea" -> {
                insertHtmlElement(t)
                tokenizer.switchTo(Content.RCDATA)
                framesetOk = false
                originalMode = mode
                mode = Mode.SKIP_NEWLINE_TEXTAREA
            }
            "xmp" -> {
                closePInButtonScope()
                reconstructFormatting()
                framesetOk = false
                rawtext(t)
            }
            "iframe" -> {
                framesetOk = false
                rawtext(t)
            }
            "noembed" -> rawtext(t)
            "select" -> {
                val select = inScope("select", Tags.SCOPE)
                if (select != null) {
                    popUntilNode(select)
                    return true
                }
                reconstructFormatting()
                insertHtmlElement(t)
                framesetOk = false
            }
            "option" -> {
                if (inScope("select", Tags.SCOPE) != null) generateImpliedEndTags(except = "optgroup")
                else if (current()!!.isHtml("option")) pop()
                reconstructFormatting()
                insertHtmlElement(t)
            }
            "optgroup" -> {
                if (inScope("select", Tags.SCOPE) != null) generateImpliedEndTags()
                else if (current()!!.isHtml("option")) pop()
                reconstructFormatting()
                insertHtmlElement(t)
            }
            "rb", "rtc" -> {
                if (inScope("ruby", Tags.SCOPE) != null) generateImpliedEndTags()
                insertHtmlElement(t)
            }
            "rp", "rt" -> {
                if (inScope("ruby", Tags.SCOPE) != null) generateImpliedEndTags(except = "rtc")
                insertHtmlElement(t)
            }
            "math" -> foreignRoot(t, Ns.MATH, Adjust.MATH)
            "svg" -> foreignRoot(t, Ns.SVG, Adjust.SVG)
            in IGNORED_IN_BODY -> {}
            else -> {
                reconstructFormatting()
                insertHtmlElement(t)
            }
        }
        return true
    }

    /** In body: text, after the active formatting elements are reconstructed (lexbor's
     * `lxb_html_tree_insertion_mode_in_body_text_append`). */
    private fun appendBodyText(data: String) {
        reconstructFormatting()
        if (framesetOk && !onlyWhitespace(data)) framesetOk = false
        insertCharacters(data)
    }

    private fun voidFormatting(t: Tk): Boolean {
        reconstructFormatting()
        insertHtmlElement(t)
        pop()
        framesetOk = false
        return true
    }

    private fun foreignRoot(t: Tk, ns: Ns, how: Adjust) {
        reconstructFormatting()
        adjust = how
        insertForeignElement(t, ns)
        adjust = Adjust.NONE
        if (t.selfClosing) pop()
    }

    private fun listItem(t: Tk, tags: Set<String>) {
        framesetOk = false
        for (i in open.indices.reversed()) {
            val node = open[i]
            if (node.ns == Ns.HTML && node.local in tags) {
                generateImpliedEndTags(except = node.local)
                popUntilTag(node.local)
                break
            }
            if (Tags.isCategory(node, Tags.SPECIAL) && !node.isHtml("address") && !node.isHtml("div") &&
                !node.isHtml("p")
            ) {
                break
            }
        }
        closePInButtonScope()
        insertHtmlElement(t)
    }

    private fun formEnd(): Boolean {
        if (!parsingTemplateContents()) {
            val node = form
            form = null
            if (node == null) return true
            if (inScopeByNode(node, Tags.SCOPE) == null) return true
            generateImpliedEndTags()
            removeOpen(node)
            return true
        }
        if (inScope("form", Tags.SCOPE) == null) return true
        generateImpliedEndTags()
        popUntilTag("form")
        return true
    }

    /** lexbor's `lxb_html_tree_insertion_mode_in_body_anything_else_closed`. */
    private fun anyOtherEndTag(t: Tk): Boolean {
        for (i in open.indices.reversed()) {
            val node = open[i]
            if (node.isHtml(t.tag)) {
                generateImpliedEndTags(except = t.tag)
                popUntilNode(node)
                return true
            }
            if (Tags.isCategory(node, Tags.SPECIAL)) return true
        }
        return true
    }

    /** lexbor's `lxb_html_tree_adoption_agency_algorithm`: true when the token is to be handled as any other end
     * tag. Its indexes into the list of active formatting elements are lexbor's, as they move. */
    private fun adoptionAgency(t: Tk): Boolean {
        val subject = t.tag
        val node0 = current()!!
        if (node0.isHtml(subject) && formattingIndex(node0) < 0) {
            pop()
            return false
        }
        var outer = 0
        while (outer < 8) {
            outer++
            var formattingAt = 0
            var formattingElement: Element? = null
            var idx = formatting.size
            while (idx != 0) {
                idx--
                val entry = formatting[idx] ?: return true
                if (entry.local == subject) {
                    formattingAt = idx
                    formattingElement = entry
                    break
                }
            }
            if (formattingElement == null) return true
            val openAt = open.indexOfLast { it === formattingElement }
            if (openAt < 0) {
                removeFormatting(formattingElement)
                return false
            }
            if (inScopeByNode(formattingElement, Tags.SCOPE) == null) return false
            var furthestAt = openAt
            var furthest: Element? = null
            while (furthestAt < open.size) {
                if (Tags.isCategory(open[furthestAt], Tags.SPECIAL)) {
                    furthest = open[furthestAt]
                    break
                }
                furthestAt++
            }
            if (furthest == null) {
                popUntilNode(formattingElement)
                removeFormatting(formattingElement)
                return false
            }
            val commonAncestor = open[openAt - 1]
            var bookmark = formattingAt
            var last: Element = furthest
            var nodeAt = furthestAt
            var inner = 0
            while (true) {
                inner++
                if (nodeAt == 0) return false
                nodeAt--
                var node = open[nodeAt]
                if (node === formattingElement) break
                var at = formattingIndex(node)
                if (inner > 3 && at >= 0) {
                    removeFormatting(node)
                    at = -1
                }
                if (at < 0) {
                    removeOpen(node)
                    continue
                }
                val clone = createElement(Tk(node.local, base = node), Ns.HTML)
                formatting[at] = clone
                open[nodeAt] = clone
                node = clone
                if (last === furthest) bookmark = at + 1
                node.append(last)
                last = node
            }
            last.remove()
            insertAt(appropriatePlace(commonAncestor), last)
            val element = createElement(Tk(formattingElement.local, base = formattingElement), Ns.HTML)
            var child = furthest.firstChild
            while (child != null) {
                val next = child.next
                element.append(child)
                child = next
            }
            furthest.append(element)
            if (formattingAt < formatting.size) formatting.removeAt(formattingAt)
            if (bookmark > formatting.size) bookmark = formatting.size
            formatting.add(bookmark, element)
            removeOpen(formattingElement)
            val furthestNow = open.indexOfFirst { it === furthest }.coerceAtLeast(0)
            open.add(furthestNow + 1, element)
        }
        return false
    }

    // --- tables -------------------------------------------------------------------------------------------

    private fun clearBackTo(tags: Set<String>) {
        while (true) {
            val node = current() ?: return
            if (node.ns == Ns.HTML && node.local in tags) return
            pop()
        }
    }

    private val tableContext = setOf("table", "template", "html")
    private val tableBodyContext = setOf("tbody", "tfoot", "thead", "template", "html")
    private val rowContext = setOf("tr", "template", "html")

    private fun inTable(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "table" -> {
                    val table = inScope("table", Tags.SCOPE_TABLE) ?: return true
                    popUntilNode(table)
                    resetInsertionMode()
                    true
                }
                "body", "caption", "col", "colgroup", "html", "tbody", "td", "tfoot", "th", "thead", "tr" -> true
                "template" -> inHead(t)
                else -> inTableAnythingElse(t)
            }
        }
        return when (t.tag) {
            TEXT -> {
                val node = current()!!
                if (node.ns == Ns.HTML && node.local in TABLE_TARGETS) {
                    pendingTable.clear()
                    pendingNonWhitespace = false
                    originalMode = mode
                    mode = Mode.IN_TABLE_TEXT
                    false
                } else {
                    inTableAnythingElse(t)
                }
            }
            COMMENT -> { insertComment(t); true }
            PI -> { insertPi(t); true }
            DOCTYPE -> true
            "caption" -> {
                clearBackTo(tableContext)
                pushMarker()
                insertHtmlElement(t)
                mode = Mode.IN_CAPTION
                true
            }
            "colgroup" -> {
                clearBackTo(tableContext)
                insertHtmlElement(t)
                mode = Mode.IN_COLUMN_GROUP
                true
            }
            "col" -> {
                clearBackTo(tableContext)
                insertHtmlElement(Tk("colgroup"))
                mode = Mode.IN_COLUMN_GROUP
                false
            }
            "tbody", "tfoot", "thead" -> {
                clearBackTo(tableContext)
                insertHtmlElement(t)
                mode = Mode.IN_TABLE_BODY
                true
            }
            "td", "th", "tr" -> {
                clearBackTo(tableContext)
                insertHtmlElement(Tk("tbody"))
                mode = Mode.IN_TABLE_BODY
                false
            }
            "table" -> {
                val table = inScope("table", Tags.SCOPE_TABLE) ?: return true
                popUntilNode(table)
                resetInsertionMode()
                false
            }
            "style", "script", "template" -> inHead(t)
            "input" -> {
                val hidden = t.attrs.any {
                    it.name == "type" && it.value != null && asciiEqualsIgnoringCase(it.value, "hidden")
                }
                if (!hidden) return inTableAnythingElse(t)
                val element = insertHtmlElement(t)
                popUntilNode(element)
                true
            }
            "form" -> {
                val inTemplate = parsingTemplateContents()
                if (form != null && !inTemplate) return true
                val element = insertHtmlElement(t)
                if (!inTemplate) form = element
                popUntilNode(element)
                true
            }
            EOF -> inBody(t)
            else -> inTableAnythingElse(t)
        }
    }

    /** In body with foster parenting; the token is used whatever in body says, as lexbor has it. */
    private fun inTableAnythingElse(t: Tk): Boolean {
        fosterParenting = true
        inBody(t)
        fosterParenting = false
        return true
    }

    private fun inTableText(t: Tk): Boolean {
        if (t.tag == TEXT) {
            val data = dropNul(t.text)
            if (data.isEmpty()) return true
            pendingTable.add(data)
            if (!onlyWhitespace(data)) pendingNonWhitespace = true
            return true
        }
        if (pendingNonWhitespace) {
            fosterParenting = true
            for (data in pendingTable) appendBodyText(data)
            fosterParenting = false
        } else {
            for (data in pendingTable) insertCharacters(data)
        }
        pendingTable.clear()
        mode = originalMode
        return false
    }

    private fun closeCaption(): Boolean {
        if (inScope("caption", Tags.SCOPE_TABLE) == null) return false
        generateImpliedEndTags()
        popUntilTag("caption")
        formattingUpToLastMarker()
        mode = Mode.IN_TABLE
        return true
    }

    private fun inCaption(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "caption" -> { closeCaption(); true }
                "table" -> !closeCaption()
                "body", "col", "colgroup", "html", "tbody", "td", "tfoot", "th", "thead", "tr" -> true
                else -> inBody(t)
            }
        }
        return when (t.tag) {
            "caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr" -> !closeCaption()
            else -> inBody(t)
        }
    }

    private fun inColumnGroup(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "colgroup" -> {
                    if (!current()!!.isHtml("colgroup")) return true
                    pop()
                    mode = Mode.IN_TABLE
                    true
                }
                "col" -> true
                "template" -> inHead(t)
                else -> inColumnGroupAnythingElse()
            }
        }
        return when (t.tag) {
            TEXT -> if (insertLeadingWhitespace(t)) true else inColumnGroupAnythingElse()
            COMMENT -> { insertComment(t); true }
            PI -> { insertPi(t); true }
            "html" -> inBody(t)
            "col" -> {
                insertHtmlElement(t)
                pop()
                true
            }
            "template" -> inHead(t)
            EOF -> inBody(t)
            else -> inColumnGroupAnythingElse()
        }
    }

    private fun inColumnGroupAnythingElse(): Boolean {
        if (!current()!!.isHtml("colgroup")) return true
        pop()
        mode = Mode.IN_TABLE
        return false
    }

    private fun inTableBody(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "tbody", "tfoot", "thead" -> {
                    if (inScope(t.tag, Tags.SCOPE_TABLE) == null) return true
                    clearBackTo(tableBodyContext)
                    pop()
                    mode = Mode.IN_TABLE
                    true
                }
                "table" -> tableBodyEnds()
                "body", "caption", "col", "colgroup", "html", "td", "th", "tr" -> true
                else -> inTable(t)
            }
        }
        return when (t.tag) {
            "tr" -> {
                clearBackTo(tableBodyContext)
                insertHtmlElement(t)
                mode = Mode.IN_ROW
                true
            }
            "th", "td" -> {
                clearBackTo(tableBodyContext)
                insertHtmlElement(Tk("tr"))
                mode = Mode.IN_ROW
                false
            }
            "caption", "col", "colgroup", "tbody", "tfoot", "thead" -> tableBodyEnds()
            else -> inTable(t)
        }
    }

    private fun tableBodyEnds(): Boolean {
        if (inScopeAny(setOf("tbody", "thead", "tfoot"), Tags.SCOPE_TABLE) == null) return true
        clearBackTo(tableBodyContext)
        pop()
        mode = Mode.IN_TABLE
        return false
    }

    private fun inRow(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "tr" -> {
                    if (inScope("tr", Tags.SCOPE_TABLE) == null) return true
                    clearBackTo(rowContext)
                    pop()
                    mode = Mode.IN_TABLE_BODY
                    true
                }
                "table" -> rowEnds()
                "tbody", "tfoot", "thead" -> {
                    if (inScope(t.tag, Tags.SCOPE_TABLE) == null) return true
                    rowEnds()
                }
                "body", "caption", "col", "colgroup", "html", "td", "th" -> true
                else -> inTable(t)
            }
        }
        return when (t.tag) {
            "th", "td" -> {
                clearBackTo(rowContext)
                insertHtmlElement(t)
                mode = Mode.IN_CELL
                pushMarker()
                true
            }
            "caption", "col", "colgroup", "tbody", "tfoot", "thead", "tr" -> rowEnds()
            else -> inTable(t)
        }
    }

    private fun rowEnds(): Boolean {
        if (inScope("tr", Tags.SCOPE_TABLE) == null) return true
        clearBackTo(rowContext)
        pop()
        mode = Mode.IN_TABLE_BODY
        return false
    }

    private fun closeCell() {
        generateImpliedEndTags()
        popUntilAny(setOf("td", "th"))
        formattingUpToLastMarker()
        mode = Mode.IN_ROW
    }

    private fun inCell(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "td", "th" -> {
                    if (inScope(t.tag, Tags.SCOPE_TABLE) == null) return true
                    generateImpliedEndTags()
                    popUntilTag(t.tag)
                    formattingUpToLastMarker()
                    mode = Mode.IN_ROW
                    true
                }
                "body", "caption", "col", "colgroup", "html" -> true
                "table", "tbody", "tfoot", "thead", "tr" -> {
                    if (inScope(t.tag, Tags.SCOPE_TABLE) == null) return true
                    closeCell()
                    false
                }
                else -> inBody(t)
            }
        }
        return when (t.tag) {
            "caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr" -> {
                if (inScopeAny(setOf("td", "th"), Tags.SCOPE_TABLE) == null) return true
                closeCell()
                false
            }
            else -> inBody(t)
        }
    }

    // --- templates, after the body, framesets ------------------------------------------------------------

    private fun switchTemplateMode(to: Mode): Boolean {
        templateModes.removeLastOrNull()
        templateModes.add(to)
        mode = to
        return false
    }

    private fun inTemplate(t: Tk): Boolean {
        if (t.end) return if (t.tag == "template") inHead(t) else true
        return when (t.tag) {
            TEXT, COMMENT, PI, DOCTYPE -> inBody(t)
            in HEAD_TAGS -> inHead(t)
            "caption", "colgroup", "tbody", "tfoot", "thead" -> switchTemplateMode(Mode.IN_TABLE)
            "col" -> switchTemplateMode(Mode.IN_COLUMN_GROUP)
            "tr" -> switchTemplateMode(Mode.IN_TABLE_BODY)
            "td", "th" -> switchTemplateMode(Mode.IN_ROW)
            EOF -> {
                if (findOpen("template") == null) {
                    stopped = true
                    return true
                }
                popUntilTag("template")
                formattingUpToLastMarker()
                templateModes.removeLastOrNull()
                resetInsertionMode()
                false
            }
            else -> switchTemplateMode(Mode.IN_BODY)
        }
    }

    private fun afterBody(t: Tk): Boolean {
        when (t.tag) {
            COMMENT -> insertComment(t, open[0])
            PI -> insertPi(t, open[0])
            DOCTYPE -> {}
            "html" -> {
                if (t.end) {
                    mode = Mode.AFTER_AFTER_BODY
                    return true
                }
                return inBody(t)
            }
            EOF -> stopped = true
            else -> {
                if (t.tag == TEXT && onlyWhitespace(t.text)) return inBody(t)
                mode = Mode.IN_BODY
                return false
            }
        }
        return true
    }

    private fun insertOnlyWhitespace(t: Tk) {
        val kept = t.text.filter(::isAsciiSpace)
        if (kept.isNotEmpty()) insertCharacters(kept)
    }

    private fun inFrameset(t: Tk): Boolean {
        if (t.end) {
            if (t.tag == "frameset") {
                if (current() === open[0]) return true
                pop()
                if (!current()!!.isHtml("frameset")) mode = Mode.AFTER_FRAMESET
            }
            return true
        }
        when (t.tag) {
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> return inBody(t)
            "frameset" -> insertHtmlElement(t)
            "frame" -> {
                insertHtmlElement(t)
                pop()
            }
            "noframes" -> return inHead(t)
            EOF -> stopped = true
            TEXT -> insertOnlyWhitespace(t)
        }
        return true
    }

    private fun afterFrameset(t: Tk): Boolean {
        when (t.tag) {
            COMMENT -> insertComment(t)
            PI -> insertPi(t)
            DOCTYPE -> {}
            "html" -> {
                if (t.end) {
                    mode = Mode.AFTER_AFTER_FRAMESET
                    return true
                }
                return inBody(t)
            }
            "noframes" -> return inHead(t)
            EOF -> stopped = true
            TEXT -> insertOnlyWhitespace(t)
        }
        return true
    }

    private fun afterAfterBody(t: Tk): Boolean {
        when (t.tag) {
            COMMENT -> insertComment(t, document)
            PI -> insertPi(t, document)
            DOCTYPE, "html" -> return inBody(t)
            EOF -> stopped = true
            else -> {
                if (t.tag == TEXT && onlyWhitespace(t.text)) return inBody(t)
                mode = Mode.IN_BODY
                return false
            }
        }
        return true
    }

    private fun afterAfterFrameset(t: Tk): Boolean {
        when (t.tag) {
            COMMENT -> insertComment(t, document)
            PI -> insertPi(t, document)
            DOCTYPE, "html" -> return inBody(t)
            EOF -> stopped = true
            "noframes" -> return inHead(t)
            TEXT -> if (onlyWhitespace(t.text)) return inBody(t)
        }
        return true
    }

    // --- foreign content ----------------------------------------------------------------------------------

    private fun foreignContent(t: Tk): Boolean {
        if (t.end) {
            return when (t.tag) {
                "script" -> foreignScriptEnd(t)
                "p", "br" -> foreignBreakout(t)
                else -> foreignEndTag(t)
            }
        }
        return when (t.tag) {
            TEXT -> {
                val data = if (t.text.indexOf('\u0000') < 0) t.text else t.text.replace('\u0000', '�')
                if (data.isEmpty()) return true
                if (framesetOk && data.any { !isAsciiSpace(it) && it != '�' }) framesetOk = false
                insertCharacters(data)
                true
            }
            COMMENT -> { insertComment(t); true }
            PI -> { insertPi(t); true }
            DOCTYPE -> true
            in BREAKOUT -> foreignBreakout(t)
            else -> foreignStartTag(t)
        }
    }

    private fun foreignScriptEnd(t: Tk): Boolean {
        val node = current()!!
        if (node.local != "script" || node.ns != Ns.SVG) return foreignEndTag(t)
        pop()
        return true
    }

    private fun foreignEndTag(t: Tk): Boolean {
        if (open.isEmpty()) return mode(t)
        var i = open.size - 1
        while (i != 0) {
            if (open[i].local == t.tag) {
                popUntilNode(open[i])
                return true
            }
            i--
            if (open[i].ns == Ns.HTML) break
        }
        return mode(t)
    }

    private fun foreignBreakout(t: Tk): Boolean {
        if (t.tag == "font" && !t.end && t.attrs.none { it.name in setOf("color", "face", "size") }) {
            return foreignStartTag(t)
        }
        while (true) {
            val node = current() ?: break
            if (mathTextIntegrationPoint(node) || htmlIntegrationPoint(node) || node.ns == Ns.HTML) break
            pop()
        }
        return mode(t)
    }

    private fun foreignStartTag(t: Tk): Boolean {
        val ns = adjustedCurrent()!!.ns
        adjust = when (ns) {
            Ns.MATH -> Adjust.MATH
            Ns.SVG -> Adjust.SVG
            Ns.HTML -> Adjust.NONE
        }
        val name = if (ns == Ns.SVG) Tags.SVG_NAMES[t.tag] ?: t.tag else t.tag
        insertForeignElement(t, ns, name)
        adjust = Adjust.NONE
        if (!t.selfClosing) return true
        val node = current()!!
        if (t.tag == "script" && node.ns == Ns.SVG) return foreignScriptEnd(t)
        pop()
        return true
    }
}
