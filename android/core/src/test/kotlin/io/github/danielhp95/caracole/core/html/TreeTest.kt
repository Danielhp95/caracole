package io.github.danielhp95.caracole.core.html

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * core.html's tree, nodes and selectors as selectolax's lexbor answers them (docs/superpowers/specs/
 * 2026-11-03-html-parsing.md): each case what selectolax 1.0.0 answered for the same page. HtmlVectorsTest replays the
 * corpus whole.
 */
class TreeTest {
    private fun ids(found: List<HtmlNode>) = found.map { it.attr("id") }

    @Test fun textIsEveryDescendantTextScriptsIncludedBreaksAndCommentsLeftOut() {
        val pre = Html.parse("<pre><script>var x='<b>';</script>T<br>U<!--c-->V</pre>").cssFirst("pre")!!
        assertEquals("var x='<b>';TUV", pre.text())
        assertEquals("TUV", pre.text(deep = false))
        val a = Html.parse("<a id=z>x<!--c-->y<?pi d?><b>q<i>r</i></b><br>s</a>").cssFirst("a")!!
        assertEquals("xyqrs", a.text())
        assertEquals("xys", a.text(deep = false))
    }

    @Test fun childrenAreTextsCommentsAndElementsInOrder() {
        val a = Html.parse("<a>x<!--c-->y<?pi d?><b>q</b><br>s</a>").cssFirst("a")!!
        assertEquals(listOf("-text", "-comment", "-text", "-pi", "b", "br", "-text"), a.children().map { it.tag })
        assertEquals(listOf("-comment", "-pi", "b", "br"), a.children(includeText = false).map { it.tag })
        val texts = a.children().map { it.textContent }
        assertEquals(listOf("x", null, "y", null, null, null, "s"), texts)
        assertEquals(listOf("", "", "q", ""), a.children(includeText = false).map { it.text() })
        assertTrue(a.children()[0].isText)
        assertEquals("-comment", a.children()[0].next!!.tag)
    }

    @Test fun aPresTextAndItsWhitespaceAreKept() {
        val pre = Html.parse("<pre><A>Bm</A>  x <b>y</b></pre>").cssFirst("pre")!!
        assertEquals(
            listOf("a" to null, "-text" to "  x ", "b" to null),
            pre.children().map { it.tag to it.textContent },
        )
        assertEquals("A\nB\nC", Html.parse("<div id=t_body><pre>\nA\r\nB\rC</pre></div>").cssFirst("pre")!!.text())
    }

    @Test fun anAttributeWrittenWithNoValueIsNull() {
        val a = Html.parse("<a href b= c=>x</a>").cssFirst("a")!!
        assertEquals(mapOf("href" to null, "b" to "c="), a.attributes)
        assertNull(a.attr("href"))
        assertEquals("&ampx &amp=y &頭", Html.parse("<a title='&ampx &amp=y &amp頭'>x</a>").cssFirst("a")!!.attr("title"))
    }

    @Test fun replaceWithAndInsertAfterAddTextNodesOfTheirOwn() {
        val pre = Html.parse("<pre>a<br>b<p>c</p>d<div>e</div></pre>").cssFirst("pre")!!
        for (br in pre.css("br")) br.replaceWith("\n")
        assertEquals(listOf("a", "\n", "b"), pre.children().take(3).map { it.textContent })
        for (node in pre.css("p, div")) node.insertAfter("\n")
        assertEquals("a\nbc\nde\n", pre.text())
        val div = Html.parse("<div><p>x</p></div>").cssFirst("div")!!
        val p = div.cssFirst("p")!!
        p.insertAfter("Q")
        p.insertAfter("R")
        assertEquals("xRQ", div.text())
    }

    @Test fun aTemplatesContentsAreNoneOfItsChildren() {
        val doc = Html.parse(
            "<template><p>a</p><td>b</td></template><p>x</p><div><template id=q><b>bb</b></template></div>",
        )
        val template = doc.cssFirst("template")!!
        assertEquals(emptyList(), template.children())
        assertEquals("", template.text())
        assertEquals(emptyList(), doc.css("template p"))
        assertEquals(listOf("x"), doc.css("p").map { it.text() })
        assertEquals(emptyList(), doc.css("b"))
        assertEquals("", doc.cssFirst("div")!!.text())
    }

    @Test fun aListOfSelectorsFindsANodeOnceForEachSelectorItMatches() {
        val doc = Html.parse("<div id=1></div><p id=2></p><div id=3><p id=4></p></div><span id=5></span>")
        assertEquals(listOf("1", "2", "3", "4"), ids(doc.css("p, div")))
        assertEquals(listOf("2", "2", "4", "4"), ids(doc.css("p, p")))
        assertEquals(listOf("2", "2", "4"), ids(doc.css("#2, p")))
        assertEquals(listOf("1", "3", "4"), ids(doc.css("div p, div")))
        assertEquals("1", doc.cssFirst("span, p, div")!!.attr("id"))
    }

    @Test fun aNodesSearchIncludesItselfAndItsCombinatorsReadTheWholeTree() {
        val doc = Html.parse("<div id=a class=x><div id=b><span id=c></span></div><p id=d></p></div><p id=e>")
        val a = doc.cssFirst("#a")!!
        assertEquals(listOf("a", "b"), ids(a.css("div")))
        assertEquals(listOf("b"), ids(a.css("div > div")))
        assertEquals(listOf("a", "b"), ids(a.css("body div")))
        assertEquals(listOf("d"), ids(a.css("div + p")))
        assertEquals(listOf("c"), ids(doc.cssFirst("#b")!!.css("body div span")))
        assertEquals("p", Html.parse("<p id=3><span></span></p>").cssFirst("p")!!.cssFirst("p")!!.tag)
    }

    @Test fun idAndClassMatchWithoutCaseInQuirksModeAlone() {
        val quirks = Html.parse("<ul id=B_MAIN class=Foo><li>one<li>two</ul>")
        assertTrue(quirks.quirks)
        assertEquals(listOf("one", "two"), quirks.css("ul#b_main > li").map { it.text() })
        assertEquals(listOf("one", "two"), quirks.css("ul#B_MAIN > li").map { it.text() })
        assertEquals(2, quirks.css("ul.foo > li").size)
        val standards = Html.parse("<!doctype html><ul id=B_MAIN class=Foo><li>one<li>two</ul>")
        assertEquals(false, standards.quirks)
        assertEquals(emptyList(), standards.css("ul#b_main > li"))
        assertEquals(emptyList(), standards.css("ul.foo > li"))
        assertEquals(2, standards.css("ul#B_MAIN > li").size)
    }

    @Test fun attributeValuesMatchWithoutCaseForTheHtmlListAndTheIFlag() {
        val doc = Html.parse("<!doctype html><a href=Q type=TeXt rel=NoFollow data-x=AbC title='Hello World'>x</a>")
        assertEquals(1, doc.css("a[type=text]").size)
        assertEquals(1, doc.css("a[rel=nofollow]").size)
        assertEquals(0, doc.css("a[href=q]").size)
        assertEquals(0, doc.css("a[data-x=abc]").size)
        assertEquals(1, doc.css("a[data-x=abc i]").size)
        assertEquals(0, doc.css("a[type=text s]").size)
        assertEquals(1, doc.css("[title^=Hello]").size)
        assertEquals(1, doc.css("[title$=\"World\"]").size)
        assertEquals(1, doc.css("[title*='o W']").size)
        assertEquals(0, doc.css("a[href*='']").size)
        assertEquals(1, doc.css("DIV, A").size)
    }

    @Test fun aSelectorItCantReadIsRefused() {
        val doc = Html.parse("<p>x")
        for (sel in listOf("a[title=hello world]", "#", "a[", "a >", ",a", "li:not(x)")) {
            assertFailsWith<IllegalArgumentException>(sel) { doc.css(sel) }
        }
    }

    @Test fun svgElementsAndAttributesKeepTheirCaseAndTypesMatchInAnyNamespace() {
        val doc = Html.parse("<svg viewBox='0 0 1 1'><clipPath id='c'/><title>t</title></svg>")
        val svg = doc.cssFirst("svg")!!
        assertEquals(mapOf("viewBox" to "0 0 1 1"), svg.attributes)
        assertEquals(listOf("clipPath", "title"), svg.children().map { it.tag })
        assertEquals(1, doc.css("clippath").size)
        assertEquals(1, doc.css("[viewbox]").size)
        assertEquals(1, doc.css("svg title").size)
    }

    @Test fun theTreeIsLexborsWhereItReadsTheStandardItsOwnWay() {
        // <select> is a scope, so a button outside it is not in scope inside it.
        assertEquals(1, Html.parse("<button><select><button>").css("button button").size)
        assertEquals(1, Html.parse("<select><div>x</div></select>").css("select > div").size)
        // A token "in table" gives "in body" is never processed again: the image is dropped.
        assertEquals(0, Html.parse("<table><image src=x><td>a</table>").css("img").size)
        // sup is no breakout tag of foreign content.
        assertEquals(1, Html.parse("<svg><sup>x</sup></svg>").css("svg sup").size)
        // Text after a frameset's html adds nothing unless all of it is whitespace.
        assertEquals("", Html.parse("<frameset></frameset></html> x ").cssFirst("html")!!.text())
    }

    @Test fun theTreeBuildersRulesMoveNodesAsTheStandardSays() {
        val agency = Html.parse("<a><p>x</a>y")
        assertEquals(1, agency.css("body > a").size)
        assertEquals("xy", agency.cssFirst("p")!!.text())
        assertEquals(1, agency.css("p > a").size)
        val fostered = Html.parse("<table>a<tr>b<td>c</table>")
        assertEquals("ab", fostered.cssFirst("body")!!.text(deep = false))
        assertEquals(listOf("tbody"), fostered.cssFirst("table")!!.children().map { it.tag })
        val lists = Html.parse("<ul><li>a<li>b<ul><li>c</ul><li>d</ul>")
        assertEquals(listOf("a", "bc", "c", "d"), lists.css("li").map { it.text() })
        assertEquals(2, Html.parse("<!DOCTYPE html><p>a<table>").css("body > *").size)
        assertEquals(1, Html.parse("<p>a<table>").css("body > *").size)
    }

    @Test fun bytesAreDecodedAsUtf8WithReplacement() {
        val bytes = byteArrayOf(0x3C, 0x70, 0x3E, 0x61, 0xFF.toByte(), 0x0D, 0x0A, 0x62) // <p>a\xFF\r\nb
        assertEquals("a�\nb", Html.parse(bytes).cssFirst("p")!!.text())
    }

    /** The spec's one divergence: lexbor reads a hidden input's every `type` in a table, duplicates too; core.html's
     * tokenizer gives the first alone, so `<input type=text type=hidden>` is fostered (lexbor keeps it in the
     * table). */
    @Test fun aTableInputsDuplicateTypeIsTheFirstAlone() {
        val doc = Html.parse("<table><input type=text type=hidden></table>")
        assertEquals(listOf("input", "table"), doc.cssFirst("body")!!.children().map { it.tag })
        assertEquals(listOf("input"), Html.parse("<table><input type=hidden type=text></table>")
            .cssFirst("table")!!.children().map { it.tag })
    }
}
