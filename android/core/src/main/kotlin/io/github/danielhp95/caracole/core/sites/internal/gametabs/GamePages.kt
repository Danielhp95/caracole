package io.github.danielhp95.caracole.core.sites.internal.gametabs

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlDoc
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sites.GameListedTab
import io.github.danielhp95.caracole.core.sites.GamePage
import io.github.danielhp95.caracole.core.sites.GameTabsPages
import java.math.BigInteger

/** gametabs.parse_game_page, its helpers' names kept. */
internal object GamePages {
    private val COUNT by lazy { PyRegex.compile("""(\d+(?:\.\d+)?)\s*([kKmM]?)""") }
    private val SAID by lazy { PyRegex.compile("""Tabs:\s*([\d,]+)""") }
    private val RATING by lazy { PyRegex.compile("""(\d+(?:\.\d+)?) average fun rating""") }

    fun parse(html: ByteArray, url: String?): GamePage = read(Html.parse(html), url)

    private fun read(tree: HtmlDoc, url: String?): GamePage {
        val wrapper = tree.cssFirst("#game-page-wrapper")
        val name = if (wrapper != null) PageText.text(wrapper.cssFirst("h1")) else ""
        if (wrapper == null || name.isEmpty()) {
            throw GameTabsParseError("no game's name (#game-page-wrapper h1) on the page", url = url)
        }
        val vocabulary = vocabulary(tree)
        val listed = wrapper.css("#game-page-games-list .results-list > a").mapNotNull { card(it, name, vocabulary) }
        val said = wrapper.css("p").firstNotNullOfOrNull { SAID.matchEntire(PageText.text(it)) }
        val tabs = if (said != null) int(said.groupValues[1].replace(",", "")) else BigInteger.valueOf(listed.size.toLong())
        if (tabs.signum() != 0 && listed.isEmpty()) {
            throw GameTabsParseError("the page says $tabs tabs and lists none caracole can read", url = url)
        }
        val pages = wrapper.css(".page-selector-wrapper a").map { PageText.text(it) }
            .filter { PyUnicode.allDigit(it) }.map { pageNumber(it, url) }
        val byPath = LinkedHashMap<String, GameListedTab>()
        for (t in listed) byPath[t.path] = t  // dict((t.path, t) for t in listed): its first place, its last card
        return GamePage(name, tabs.max(BigInteger.valueOf(listed.size.toLong())), byPath.values.toList(),
                        pages.maxOrNull() ?: BigInteger.ONE)
    }

    /** `int(text)`, a ValueError where Python raises one ("Tabs: ," is int('')): an IllegalArgumentException. */
    private fun int(text: String): BigInteger = PyInt.parse(text)
        ?: throw IllegalArgumentException("invalid literal for int() with base 10: ${PyStr.repr(text)}")

    /** `_page_number`: a page selector's number; GameTabsParseError for digits int() refuses ("²", "①"). */
    private fun pageNumber(text: String, url: String?): BigInteger = PyInt.parse(text)
        ?: throw GameTabsParseError("a page number caracole can't read: ${PyStr.repr(text)}", url = url)

    /** `_vocabulary`: the site's instruments as the page's shuffle dialog names them; INSTRUMENTS when it doesn't. */
    private fun vocabulary(tree: HtmlDoc): Set<String> {
        val dialog = tree.cssFirst("[data-prepopulated-instruments]")
        val named = if (dialog != null) PageText.names(PageText.loads(dialog.attributes["data-prepopulated-instruments"]))
        else emptyList()
        return named.ifEmpty { GameTabsPages.INSTRUMENTS }.toSet()
    }

    /** `_card`: a card's tab, or null for one that links to no tab page. */
    private fun card(card: HtmlNode, game: String, instruments: Set<String>): GameListedTab? {
        val found = PageText.TAB_HREF.matchEntire(PageText.attr(card, "href"))
        val left = card.cssFirst(".split-row-left")
        if (found == null || left == null) return null
        val spans = left.children(includeText = false).filter { it.tag == "span" }
        var title = Values.collapse(PageText.attr(card, "title"))
            .ifEmpty { if (spans.isNotEmpty()) PageText.text(spans[0]) else "" }
        title = Py.strip(title.removeSuffix(" - $game"))
        if (title.isEmpty()) return null
        var platform: String? = null
        var tabber: String? = null
        var composers: List<String> = emptyList()
        val said = ArrayList<List<String>>()
        for (span in spans.drop(1)) {
            val text = PageText.text(span)
            val at = text.indexOf(':')
            val label = if (at < 0) text else text.substring(0, at)
            val value = if (at < 0) "" else text.substring(at + 1)
            when {
                "italic" in PageText.attr(span, "style") -> platform = text.ifEmpty { null }
                at >= 0 && (label == "Composer" || label == "Composers") -> composers = PageText.split(value)
                at >= 0 && label == "Tabber" -> tabber = Py.strip(value).trimStart('@').ifEmpty { null }
                text.isNotEmpty() -> said.add(PageText.split(text))
            }
        }
        // next(s for s in said if s and set(s) <= instruments), then the first other, by identity: Python's one empty
        // tuple is every empty one, so with no instruments named an empty part is never the styles.
        val named = said.indexOfFirst { it.isNotEmpty() && instruments.containsAll(it) }
        val styles = said.indices.firstOrNull { if (named < 0) said[it].isNotEmpty() else it != named }
        val right = card.cssFirst(".split-row-right")
        val views = right?.css("span").orEmpty().map { PageText.text(it) }.firstOrNull { it.startsWith("Views") }
            ?.let { views(it.removePrefix("Views")) } ?: BigInteger.ZERO
        val rated = right?.cssFirst("[title$=\"average fun rating\"]")
        val rating = rated?.let { RATING.matchEntire(PageText.attr(it, "title")) }
        return GameListedTab(
            found.groupValues[1], title, composers = composers,
            instruments = if (named >= 0) said[named] else emptyList(),
            styles = styles?.let { said[it] } ?: emptyList(), platform = platform, tabber = tabber, views = views,
            rating = rating?.let { PyFloat.parse(it.groupValues[1]) },
        )
    }

    /** `_views`: "11.2k" 11,200; "1.1M" 1,100,000; "692" 692; 0 for none, or a count past a float. */
    private fun views(text: String): BigInteger {
        val m = COUNT.matchEntire(Py.strip(text.replace(",", ""))) ?: return BigInteger.ZERO
        val times = when (m.groupValues[2]) { "k", "K" -> 1_000.0; "m", "M" -> 1_000_000.0; else -> 1.0 }
        val n = (PyFloat.parse(m.groupValues[1]) ?: return BigInteger.ZERO) * times
        return if (n.isFinite()) Values.rounded(n) else BigInteger.ZERO
    }
}
