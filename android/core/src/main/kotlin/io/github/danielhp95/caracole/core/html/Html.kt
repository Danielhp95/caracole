package io.github.danielhp95.caracole.core.html

import io.github.danielhp95.caracole.core.html.internal.select.Selectors
import io.github.danielhp95.caracole.core.html.internal.token.Preprocess
import io.github.danielhp95.caracole.core.html.internal.tree.Comment
import io.github.danielhp95.caracole.core.html.internal.tree.Document
import io.github.danielhp95.caracole.core.html.internal.tree.DoctypeNode
import io.github.danielhp95.caracole.core.html.internal.tree.Element
import io.github.danielhp95.caracole.core.html.internal.tree.Node
import io.github.danielhp95.caracole.core.html.internal.tree.ProcessingInstruction
import io.github.danielhp95.caracole.core.html.internal.tree.Text
import io.github.danielhp95.caracole.core.html.internal.tree.TreeBuilder

/**
 * The phone's HTML parser, with selectolax's lexbor semantics (docs/superpowers/specs/2026-11-03-html-parsing.md):
 * the WHATWG tokenizer and tree builder as lexbor 3.1.0 has them, lexbor's text and selectors, so that a page reads
 * on the phone as `LexborHTMLParser` reads it on the computer.
 */
object Html {
    fun parse(text: String): HtmlDoc = HtmlDoc(TreeBuilder.parse(text))

    /** The bytes decoded as UTF-8 with replacement first (PyCodec.utf8Replace), as caracole's parsers hand
     * selectolax text. */
    fun parse(bytes: ByteArray): HtmlDoc = HtmlDoc(TreeBuilder.parse(Preprocess.bytes(bytes), preprocessed = true))
}

/** A page parsed: [quirks] mode from its doctype, its selectors as lexbor answers them. */
class HtmlDoc internal constructor(internal val document: Document) {
    /** An empty document in the mode named. */
    constructor(quirks: Boolean) : this(Document().also { it.quirks = quirks })

    val quirks: Boolean get() = document.quirks

    /** The `<html>` element, where selectolax's `css()` starts. */
    private val root: Node? get() = generateSequence(document.firstChild) { it.next }.firstOrNull { it is Element }

    /** Every element [sel] matches, in document order, once for each selector of the list it matches. */
    fun css(sel: String): List<HtmlNode> {
        val selectors = Selectors.parse(sel)
        val root = root ?: return emptyList()
        return selectors.select(root, quirks).map { HtmlNode(it, document) }
    }

    fun cssFirst(sel: String): HtmlNode? = css(sel).firstOrNull()
}

/** A node of the tree: an element, or a text ("-text"), a comment ("-comment") or a processing instruction ("-pi")
 * as selectolax shows them. Two of the same node are equal. */
class HtmlNode internal constructor(internal val node: Node, private val document: Document) {
    /** An element's name (lowercase, an SVG element's in its own case: `clipPath`), or "-text", "-comment", "-pi",
     * "-doctype". */
    val tag: String
        get() = when (node) {
            is Element -> node.name
            is Text -> "-text"
            is Comment -> "-comment"
            is ProcessingInstruction -> "-pi"
            is DoctypeNode -> "-doctype"
            else -> "-document"
        }

    fun attr(name: String): String? = attributes[name]

    /** The element's attributes by name, in order, as selectolax's `attributes` dict holds them: a value null where
     * none was written (`<a href>`); the tokenizer kept the first of duplicates (`<a href=1 href=2>` has href 1), and
     * of two the tree builder kept under one shown name (a foreign attribute's, adjusted), the dict's last. */
    val attributes: Map<String, String?>
        get() {
            val element = node as? Element ?: return emptyMap()
            val map = LinkedHashMap<String, String?>()
            for (a in element.attributes) map[a.name] = a.value
            return map
        }

    /** lexbor's: every descendant text's data with no separator (a `<script>`'s and a `<style>`'s in, nothing for
     * `<br>`, comments out); with [deep] false, the node's own text children alone. A text node's is its data. */
    fun text(deep: Boolean = true): String {
        if (node is Text) return node.text
        val out = StringBuilder()
        if (!deep) {
            var child = node.firstChild
            while (child != null) {
                if (child is Text) out.append(child.text)
                child = child.next
            }
            return out.toString()
        }
        var at: Node? = node.firstChild
        while (at != null) {
            if (at is Text) out.append(at.text)
            at = following(at)
        }
        return out.toString()
    }

    private fun following(at: Node): Node? {
        at.firstChild?.let { return it }
        var up: Node = at
        while (up !== node) {
            up.next?.let { return it }
            up = up.parent ?: return null
        }
        return null
    }

    /** The node's children, its text nodes too unless [includeText] is false (its comments always, as selectolax's
     * `iter`). */
    fun children(includeText: Boolean = true): List<HtmlNode> {
        val list = ArrayList<HtmlNode>()
        var child = node.firstChild
        while (child != null) {
            if (includeText || child !is Text) list += HtmlNode(child, document)
            child = child.next
        }
        return list
    }

    /** A text node's text; null for anything else. */
    val textContent: String? get() = (node as? Text)?.text

    val next: HtmlNode? get() = node.next?.let { HtmlNode(it, document) }

    val isText: Boolean get() = node is Text

    /** Every element [sel] matches among this node and its descendants, in document order (a combinator reads the
     * whole tree: `body p` from a `<div>` inside the body). */
    fun css(sel: String): List<HtmlNode> =
        Selectors.parse(sel).select(node, document.quirks).map { HtmlNode(it, document) }

    fun cssFirst(sel: String): HtmlNode? = css(sel).firstOrNull()

    /** This node replaced by a text node of [text] (no merging with the texts beside it, as lexbor inserts it). */
    fun replaceWith(text: String) {
        if (node.parent == null) return
        node.insertBefore(Text(text))
        node.remove()
    }

    /** A text node of [text] right after this node. */
    fun insertAfter(text: String) {
        if (node.parent == null) return
        node.insertAfter(Text(text))
    }

    override fun equals(other: Any?) = other is HtmlNode && other.node === node

    override fun hashCode() = System.identityHashCode(node)

    override fun toString() = "HtmlNode($tag)"
}
