package io.github.danielhp95.caracole.core.html.internal.select

import io.github.danielhp95.caracole.core.html.internal.tree.Element
import io.github.danielhp95.caracole.core.html.internal.tree.Node
import io.github.danielhp95.caracole.core.html.internal.tree.Ns

/**
 * CSS selectors as lexbor 3.1.0 matches them for selectolax's `css()` (lexbor/selectors/selectors.c,
 * docs/superpowers/specs/2026-11-03-html-parsing.md, "Selectors"): the ones caracole's parsers write, a type or `*`,
 * `#id`, `.class`, `[a]` and `[a=v]`, `~=`, `|=`, `^=`, `$=`, `*=` (with an `i` or `s` flag), joined by the
 * descendant combinator, `>`, `+` and `~`, in a list. Anything else (a pseudo-class, a namespace, an escape) is an
 * [IllegalArgumentException], as selectolax raises for a selector it can't parse.
 *
 * - A type or an attribute name matches without ASCII case, in any namespace (`title` finds an SVG `<title>`).
 * - `#id` and `.class` match without ASCII case in quirks mode alone.
 * - An attribute value matches without ASCII case for the HTML attributes whose values the HTML standard lists as
 *   case-insensitive (`type`, `lang`, `rel`…), on an HTML element; with `i` always, with `s` never.
 * - [select] walks the root and its descendants in document order and gives each element once for each selector of
 *   the list it matches (`p, #a` gives a `<p id=a>` twice), as lexbor's `lxb_selectors_find` calls back. A combinator
 *   reads the whole tree, outside the root too (`div.css("body p")`).
 */
internal class Selectors private constructor(private val list: List<Complex>) {
    private enum class Combinator { DESCENDANT, CHILD, ADJACENT, SIBLING }

    private enum class Match { EXISTS, EQUAL, INCLUDE, DASH, PREFIX, SUFFIX, SUBSTRING }

    private sealed class Simple {
        class Type(val name: String) : Simple()
        object Any : Simple()
        class Id(val name: String) : Simple()
        class Class(val name: String) : Simple()
        class Attribute(val name: String, val match: Match, val value: String, val insensitive: Boolean?) : Simple()
    }

    /** Compounds left to right, [combinators][i] between compound i and i + 1. */
    private class Complex(val compounds: List<List<Simple>>, val combinators: List<Combinator>)

    companion object {
        fun parse(selector: String): Selectors = Parser(selector).list()

        private val INSENSITIVE = setOf(
            "accept", "accept-charset", "align", "alink", "axis", "bgcolor", "charset", "checked", "clear",
            "codetype", "color", "compact", "declare", "defer", "dir", "direction", "disabled", "enctype", "face",
            "frame", "hreflang", "http-equiv", "lang", "language", "link", "media", "method", "multiple", "nohref",
            "noresize", "noshade", "nowrap", "readonly", "rel", "rev", "rules", "scope", "scrolling", "selected",
            "shape", "target", "text", "type", "valign", "valuetype", "vlink",
        )

        private fun lower(c: Char) = if (c in 'A'..'Z') c + 32 else c

        private fun lower(s: String) = buildString(s.length) { for (c in s) append(lower(c)) }

        private fun isAsciiSpace(c: Char) = c == ' ' || c == '\t' || c == '\n' || c == '\u000C' || c == '\r'

        private fun equal(a: String, aFrom: Int, b: String, insensitive: Boolean): Boolean {
            if (aFrom + b.length > a.length) return false
            for (i in b.indices) {
                val x = a[aFrom + i]
                val y = b[i]
                if (if (insensitive) lower(x) != lower(y) else x != y) return false
            }
            return true
        }

        /** lexbor's `lxb_selectors_match_class`: [name] among [value]'s whitespace-separated words. */
        private fun hasWord(value: String, name: String, insensitive: Boolean): Boolean {
            if (name.isEmpty() || value.length < name.length) return false
            var start = 0
            for (i in 0..value.length) {
                if (i == value.length || isAsciiSpace(value[i])) {
                    if (i - start == name.length && equal(value, start, name, insensitive)) return true
                    start = i + 1
                }
            }
            return false
        }
    }

    /** Every element of [root] and its descendants this matches, in document order, once for each selector of the
     * list it matches. */
    fun select(root: Node, quirks: Boolean): List<Element> {
        val found = ArrayList<Element>()
        var node: Node? = root
        while (node != null) {
            if (node is Element) {
                for (complex in list) if (matches(node, complex, complex.compounds.size - 1, quirks)) found += node
            }
            node = following(node, root)
        }
        return found
    }

    private fun matches(element: Element, complex: Complex, at: Int, quirks: Boolean): Boolean {
        if (!complex.compounds[at].all { matches(element, it, quirks) }) return false
        if (at == 0) return true
        return when (complex.combinators[at - 1]) {
            Combinator.DESCENDANT -> {
                var up = element.parent as? Element
                while (up != null) {
                    if (matches(up, complex, at - 1, quirks)) return true
                    up = up.parent as? Element
                }
                false
            }
            Combinator.CHILD -> (element.parent as? Element)?.let { matches(it, complex, at - 1, quirks) } ?: false
            Combinator.ADJACENT -> previousElement(element)?.let { matches(it, complex, at - 1, quirks) } ?: false
            Combinator.SIBLING -> {
                var before = previousElement(element)
                while (before != null) {
                    if (matches(before, complex, at - 1, quirks)) return true
                    before = previousElement(before)
                }
                false
            }
        }
    }

    /** The node after [node] in document order within [root], or null past its last descendant. */
    private fun following(node: Node, root: Node): Node? {
        node.firstChild?.let { return it }
        var at: Node = node
        while (at !== root) {
            at.next?.let { return it }
            at = at.parent ?: return null
        }
        return null
    }

    private fun previousElement(node: Node): Element? {
        var before = node.prev
        while (before != null && before !is Element) before = before.prev
        return before as Element?
    }

    private fun matches(element: Element, simple: Simple, quirks: Boolean): Boolean = when (simple) {
        Simple.Any -> true
        is Simple.Type -> element.local == simple.name
        is Simple.Id -> {
            val id = element.attr("id")?.value
            id != null && id.length == simple.name.length && equal(id, 0, simple.name, quirks)
        }
        is Simple.Class -> {
            val classes = element.attr("class")?.value
            classes != null && hasWord(classes, simple.name, quirks)
        }
        is Simple.Attribute -> matchAttribute(element, simple)
    }

    private fun matchAttribute(element: Element, selector: Simple.Attribute): Boolean {
        val attr = element.attr(selector.name) ?: return false
        if (selector.match == Match.EXISTS) return true
        val target = attr.value ?: ""
        val wanted = selector.value
        val insensitive = selector.insensitive ?: (element.ns == Ns.HTML && selector.name in INSENSITIVE)
        return when (selector.match) {
            Match.EXISTS -> true
            Match.EQUAL -> target.length == wanted.length && equal(target, 0, wanted, insensitive)
            Match.INCLUDE -> hasWord(target, wanted, insensitive)
            Match.DASH -> when {
                target.length == wanted.length -> equal(target, 0, wanted, insensitive)
                target.length > wanted.length -> equal(target, 0, wanted, insensitive) && target[wanted.length] == '-'
                else -> false
            }
            Match.PREFIX -> wanted.isNotEmpty() && equal(target, 0, wanted, insensitive)
            Match.SUFFIX -> wanted.isNotEmpty() && target.length >= wanted.length &&
                equal(target, target.length - wanted.length, wanted, insensitive)
            Match.SUBSTRING -> wanted.isNotEmpty() &&
                (0..target.length - wanted.length).any { equal(target, it, wanted, insensitive) }
        }
    }

    /** The selector grammar caracole's selectors are written in, a recursive descent over [s]. */
    private class Parser(private val s: String) {
        private var p = 0

        private fun fail(): Nothing = throw IllegalArgumentException("can't parse the CSS selector \"$s\" at $p")

        private fun skipWhitespace(): Boolean {
            val from = p
            while (p < s.length && isAsciiSpace(s[p])) p++
            return p > from
        }

        private fun isNameChar(c: Char) =
            c in 'a'..'z' || c in 'A'..'Z' || c in '0'..'9' || c == '-' || c == '_' || c.code >= 0x80

        private fun name(): String {
            val from = p
            while (p < s.length && isNameChar(s[p])) p++
            if (p == from) fail()
            return s.substring(from, p)
        }

        private fun identifier(): String {
            val start = p
            val name = name()
            val first = name[0]
            val second = name.getOrNull(1)
            if (first in '0'..'9' || (first == '-' && (second == null || second in '0'..'9'))) {
                p = start
                fail()
            }
            return name
        }

        fun list(): Selectors {
            val list = ArrayList<Complex>()
            while (true) {
                skipWhitespace()
                list += complex()
                skipWhitespace()
                if (p == s.length) return Selectors(list)
                if (s[p] != ',') fail()
                p++
            }
        }

        private fun complex(): Complex {
            val compounds = ArrayList<List<Simple>>()
            val combinators = ArrayList<Combinator>()
            compounds += compound()
            while (true) {
                val spaced = skipWhitespace()
                if (p == s.length || s[p] == ',') return Complex(compounds, combinators)
                combinators += when (s[p]) {
                    '>' -> Combinator.CHILD.also { p++ }
                    '+' -> Combinator.ADJACENT.also { p++ }
                    '~' -> Combinator.SIBLING.also { p++ }
                    else -> if (spaced) Combinator.DESCENDANT else fail()
                }
                skipWhitespace()
                compounds += compound()
            }
        }

        private fun compound(): List<Simple> {
            val simples = ArrayList<Simple>()
            if (p < s.length && s[p] == '*') {
                p++
                simples += Simple.Any
            } else if (p < s.length && isNameChar(s[p])) {
                simples += Simple.Type(lower(identifier()))
            }
            while (p < s.length) {
                when (s[p]) {
                    '#' -> {
                        p++
                        simples += Simple.Id(name())
                    }
                    '.' -> {
                        p++
                        simples += Simple.Class(identifier())
                    }
                    '[' -> {
                        p++
                        simples += attribute()
                    }
                    else -> break
                }
            }
            if (simples.isEmpty()) fail()
            return simples
        }

        private fun attribute(): Simple.Attribute {
            skipWhitespace()
            val name = lower(identifier())
            skipWhitespace()
            if (p < s.length && s[p] == ']') {
                p++
                return Simple.Attribute(name, Match.EXISTS, "", null)
            }
            val match = when {
                s.startsWith("=", p) -> Match.EQUAL.also { p += 1 }
                s.startsWith("~=", p) -> Match.INCLUDE.also { p += 2 }
                s.startsWith("|=", p) -> Match.DASH.also { p += 2 }
                s.startsWith("^=", p) -> Match.PREFIX.also { p += 2 }
                s.startsWith("$=", p) -> Match.SUFFIX.also { p += 2 }
                s.startsWith("*=", p) -> Match.SUBSTRING.also { p += 2 }
                else -> fail()
            }
            skipWhitespace()
            val value = if (p < s.length && (s[p] == '"' || s[p] == '\'')) quoted() else identifier()
            skipWhitespace()
            var insensitive: Boolean? = null
            if (p < s.length && (s[p] == 'i' || s[p] == 'I' || s[p] == 's' || s[p] == 'S')) {
                insensitive = lower(s[p]) == 'i'
                p++
                skipWhitespace()
            }
            if (p >= s.length || s[p] != ']') fail()
            p++
            return Simple.Attribute(name, match, value, insensitive)
        }

        private fun quoted(): String {
            val quote = s[p++]
            val out = StringBuilder()
            while (true) {
                if (p >= s.length) fail()
                val c = s[p++]
                if (c == quote) return out.toString()
                if (c == '\\' || c == '\n') fail()
                out.append(c)
            }
        }
    }
}
