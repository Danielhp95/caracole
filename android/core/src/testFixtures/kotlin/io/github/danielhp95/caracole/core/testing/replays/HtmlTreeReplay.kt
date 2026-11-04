package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlDoc
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.html.internal.token.Attribute
import io.github.danielhp95.caracole.core.html.internal.tree.Comment
import io.github.danielhp95.caracole.core.html.internal.tree.DoctypeNode
import io.github.danielhp95.caracole.core.html.internal.tree.Element
import io.github.danielhp95.caracole.core.html.internal.tree.ProcessingInstruction
import io.github.danielhp95.caracole.core.html.internal.tree.Text
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyCodec
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import java.security.MessageDigest
import java.util.IdentityHashMap
import io.github.danielhp95.caracole.core.html.internal.tree.Node as DomNode

/**
 * core.html's trees (vectors/html/tree*.jsonl and mutations.jsonl, tests/test_conformance_html.py's tree half), as
 * [HtmlReplay] runs them: each page built by core.html and read through [HtmlDoc] and [HtmlNode] as caracole's site
 * parsers read it, against what lexbor built and selectolax answered: the tree's shape, every element's text, the
 * parsers' selectors from the document and from a node, harptabs.py's `<pre>` read with `replace_with` and
 * `insert_after`, selectors alone in quirks and standards mode, and the seeded mutations' shapes by digest.
 */
object HtmlTreeReplay {
    val TREES = listOf("html/tree.jsonl", "html/tree_edges.jsonl")

    fun replay() {
        var selectors: List<String> = emptyList()
        var scoped: List<Pair<String, String>> = emptyList()
        for (name in TREES) {
            val vector = Misses(name)
            var pages = 0
            for (record in Corpus.records(name)) {
                when (record.fn) {
                    "test_conformance_html.SELECTORS" -> selectors = record.out!!.jsonArray.map(::text)
                    "test_conformance_html.SCOPED" -> scoped = record.out!!.jsonArray.map {
                        val (scope, sel) = it.jsonArray
                        text(scope) to text(sel)
                    }
                    "test_conformance_html.tree" -> {
                        pages++
                        val case = record.extra["case"]?.jsonPrimitive?.content ?: "?"
                        val page = HtmlReplay.page(record.args[0])
                        compareTree(vector, case, page, record.out!!.jsonObject, selectors, scoped)
                    }
                    else -> throw AssertionError("an unknown record: ${record.fn}")
                }
            }
            check(pages > 0 && selectors.isNotEmpty()) { "$name has no page" }
            vector.assertNone()
        }
        selectorsAlone()
        mutations()
    }

    /** What tokens*.jsonl records of a page (test_conformance_html.py's `reads`), read from core.html's tree: the
     * names as the tokenizer gave them, ASCII-lowercased (the tree gives SVG's and MathML's their case). */
    fun tokensRead(page: String): TokensTree.Read {
        val doc = Html.parse(page)
        var doctype: String? = null
        val attrs = ArrayList<Pair<String, List<Attribute>>>()
        val text = StringBuilder()
        val comments = ArrayList<String>()
        val pis = ArrayList<List<String>>()
        for (node in Shape(doc).nodes) {
            when (node) {
                is Element -> if (node.attributes.isNotEmpty()) {
                    val written = HtmlNode(node, doc.document).attributes.map { (k, v) -> Attribute(Py.asciiLower(k), v) }
                    attrs += Py.asciiLower(node.name) to written
                }
                is Text -> text.append(node.text)
                is Comment -> comments += node.data
                is ProcessingInstruction -> pis += listOf(node.target, node.data)
                is DoctypeNode -> doctype = node.name ?: ""
            }
        }
        return TokensTree.Read(doc.quirks, doctype, attrs, text.toString(), comments, pis)
    }

    /** A tree's every node in document order with its depth and its place, as test_conformance_html.py's `shape`. */
    internal class Shape(doc: HtmlDoc) {
        val rows = ArrayList<JsonArray>()
        val index = IdentityHashMap<DomNode, Int>()
        val nodes = ArrayList<DomNode>()

        init {
            val stack = ArrayDeque<Pair<DomNode, Int>>()
            var child = doc.document.lastChild
            while (child != null) {
                stack.addLast(child to 0)
                child = child.prev
            }
            while (stack.isNotEmpty()) {
                val (node, depth) = stack.removeLast()
                index[node] = nodes.size
                nodes += node
                rows += row(node, depth)
                var c = node.lastChild
                while (c != null) {
                    stack.addLast(c to depth + 1)
                    c = c.prev
                }
            }
        }

        private fun row(node: DomNode, depth: Int): JsonArray {
            val d = JsonPrimitive(depth)
            return when (node) {
                is Element -> JsonArray(listOf(d, JsonPrimitive(node.name), JsonArray(attributes(node))))
                is Text -> JsonArray(listOf(d, JsonPrimitive("#"), JsonPrimitive(node.text)))
                is Comment -> JsonArray(listOf(d, JsonPrimitive("!"), JsonPrimitive(node.data)))
                is ProcessingInstruction ->
                    JsonArray(listOf(d, JsonPrimitive("?"), JsonPrimitive(node.target), JsonPrimitive(node.data)))
                is DoctypeNode -> JsonArray(listOf(d, JsonPrimitive("-doctype"), JsonPrimitive(node.name ?: "")))
                else -> throw AssertionError("a node of no known kind: $node")
            }
        }

        /** As selectolax's `attributes` dict lists them: one a name, the last of a name at the first's place. */
        private fun attributes(element: Element): List<JsonArray> {
            val map = LinkedHashMap<String, String?>()
            for (a in element.attributes) map[a.name] = a.value
            return map.map { (name, value) ->
                JsonArray(listOf(JsonPrimitive(name), value?.let(::JsonPrimitive) ?: JsonNull))
            }
        }

        fun of(found: List<HtmlNode>): List<Int> = found.map { index.getValue(it.node) }
    }

    private fun compareTree(misses: Misses, case: String, page: String, want: JsonObject, selectors: List<String>,
                            scoped: List<Pair<String, String>>) {
        val doc = Html.parse(page)
        val shape = Shape(doc)
        val quirks = want.getValue("quirks").jsonPrimitive.boolean
        misses.check(quirks == doc.quirks) { "$case: quirks ${doc.quirks}, lexbor's $quirks" }
        val rows = want.getValue("shape").jsonArray
        misses.check(rows == JsonArray(shape.rows)) { "$case: shape ${firstDifference(rows, shape.rows)}" }
        val texts = texts(doc, shape)
        misses.check(texts == text(want.getValue("texts"))) { "$case: the elements' text differs" }
        val queries = want.getValue("queries").jsonObject
        for (sel in selectors) {
            val wanted = queries[sel]?.jsonArray?.map { it.jsonPrimitive.int } ?: emptyList()
            val got = shape.of(doc.css(sel))
            misses.check(wanted == got) { "$case: css(\"$sel\") found $got, lexbor $wanted" }
        }
        val scopes = want.getValue("scoped").jsonObject
        for ((scope, sel) in scoped) {
            val wanted = scopes["$scope\t$sel"]?.jsonArray?.map(::scopeRow) ?: emptyList()
            val got = doc.css(scope).map { shape.index.getValue(it.node) to shape.of(it.css(sel)) }
            misses.check(wanted == got) { "$case: css(\"$scope\").css(\"$sel\") found $got, lexbor $wanted" }
        }
        val pre = want.getValue("pre").jsonArray
        val pres = doc.css("pre")
        misses.check(pre.size == pres.size) { "$case: ${pres.size} pre, lexbor ${pre.size}" }
        for ((k, row) in pre.withIndex()) {
            val (at, read) = row.jsonArray
            if (k >= pres.size) break
            val place = shape.index.getValue(pres[k].node)
            misses.check(place == at.jsonPrimitive.int) { "$case: pre $k at another place" }
            val got = preText(Html.parse(page).css("pre")[k])
            misses.check(got == text(read)) {
                "$case: pre $k reads ${show(got.take(60))}, lexbor ${show(text(read).take(60))}"
            }
        }
    }

    private fun scopeRow(row: JsonElement): Pair<Int, List<Int>> {
        val (at, found) = row.jsonArray
        return at.jsonPrimitive.int to found.jsonArray.map { it.jsonPrimitive.int }
    }

    /** test_conformance_html.py's `_texts`: every element's deep and shallow text, NUL-joined, hashed. */
    private fun texts(doc: HtmlDoc, shape: Shape): String {
        val parts = ArrayList<String>()
        for (node in shape.nodes) {
            if (node !is Element) continue
            val wrapped = HtmlNode(node, doc.document)
            parts += wrapped.text(deep = true)
            parts += wrapped.text(deep = false)
        }
        val sha = MessageDigest.getInstance("SHA-256").digest(parts.joinToString("\u0000").toByteArray(Charsets.UTF_8))
        return hexBytes(sha)
    }

    /** harptabs.py's `_pre_text`, a copy of the replay's own until lane harptabs ports it into core.sites' main
     * code: then the `pre` comparison above calls that port, and this copy goes. */
    fun preText(pre: HtmlNode): String {
        for (node in pre.css("br")) node.replaceWith("\n")
        for (node in pre.css("p, div")) {
            val after = node.next
            if (after != null && !(after.isText && (after.textContent ?: "").startsWith("\n"))) node.insertAfter("\n")
        }
        return pre.text(deep = true)
    }

    private fun selectorsAlone() {
        val misses = Misses("html/tree_selectors.jsonl")
        var pages: JsonObject? = null
        for (record in Corpus.records("html/tree_selectors.jsonl")) {
            if (record.fn == "test_conformance_html.SELECTOR_PAGES") {
                pages = record.out!!.jsonObject
                continue
            }
            assertEquals("test_conformance_html.select", record.fn)
            val case = record.extra["case"]?.jsonPrimitive?.content ?: "?"
            val (mode, scope, sel) = record.args
            val doc = Html.parse(text(checkNotNull(pages) { "no pages before $case" }.getValue(text(mode))))
            val shape = Shape(doc)
            val got = try {
                if (scope is JsonNull) shape.of(doc.css(text(sel)))
                else doc.css(text(scope)).map { listOf(shape.index.getValue(it.node), shape.of(it.css(text(sel)))) }
            } catch (e: IllegalArgumentException) {
                misses.check(record.err != null) { "$case: refused, lexbor found ${record.out}" }
                continue
            }
            if (record.err != null) {
                misses.check(false) { "$case: found $got, lexbor refused it" }
                continue
            }
            val wanted = if (scope is JsonNull) record.out!!.jsonArray.map { it.jsonPrimitive.int }
            else record.out!!.jsonArray.map { r -> scopeRow(r).let { listOf(it.first, it.second) } }
            misses.check(wanted == got) { "$case: found $got, lexbor $wanted" }
        }
        misses.assertNone()
    }

    /** A mutation's page, as test_conformance_html.py's `mutated` makes it: the fixture decoded, cut and edited in
     * code points. */
    fun mutated(spec: JsonObject): String {
        val text = PyCodec.utf8Replace(Corpus.fixture(text(spec.getValue("fixture"))))
        val (from, to) = spec.getValue("cut").jsonArray.map { it.jsonPrimitive.int }
        var page = Py.codePoints(text).copyOfRange(from, to).toMutableList()
        for (edit in spec.getValue("edits").jsonArray) {
            val (at, deleted, inserted) = edit.jsonArray
            val a = at.jsonPrimitive.int
            val d = deleted.jsonPrimitive.int
            page = (page.subList(0, a) + Py.codePoints(text(inserted)).toList() + page.subList(a + d, page.size))
                .toMutableList()
        }
        return String(page.toIntArray(), 0, page.size)
    }

    private fun mutations() {
        val misses = Misses("html/mutations.jsonl")
        var records = 0
        for (record in Corpus.records("html/mutations.jsonl")) {
            assertEquals("test_conformance_html.mutation", record.fn)
            records++
            val case = record.extra["case"]?.jsonPrimitive?.content ?: "?"
            val page = mutated(record.args[0].jsonObject)
            val want = record.out!!.jsonObject
            val doc = Html.parse(page)
            val shape = Shape(doc)
            val digest = Canonical.digest(JsonArray(shape.rows))
            val same = digest == text(want.getValue("shape")) &&
                shape.rows.size == want.getValue("nodes").jsonPrimitive.int &&
                doc.quirks == want.getValue("quirks").jsonPrimitive.boolean
            misses.check(same) { "$case: ${shape.rows.size} nodes, another shape than lexbor's ${want["nodes"]}" }
        }
        check(records > 0) { "mutations.jsonl has no record" }
        misses.assertNone()
    }

    private fun firstDifference(want: JsonArray, got: List<JsonArray>): String {
        val i = (0 until maxOf(want.size, got.size)).firstOrNull { want.getOrNull(it) != got.getOrNull(it) }
            ?: return "same"
        return "differs at node $i of ${want.size}: built ${got.getOrNull(i)}, lexbor's ${want.getOrNull(i)} " +
            "(after ${want.subList(maxOf(0, i - 3), minOf(i, want.size))})"
    }
}
