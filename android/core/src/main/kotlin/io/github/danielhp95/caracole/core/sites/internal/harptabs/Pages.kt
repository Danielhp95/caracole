package io.github.danielhp95.caracole.core.sites.internal.harptabs

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlDoc
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.http.HarpTabsParseError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.sites.HarpArtistPage
import io.github.danielhp95.caracole.core.sites.HarpListedTab
import io.github.danielhp95.caracole.core.sites.HarpTabs
import io.github.danielhp95.caracole.core.ug.internal.rank.PyValues
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal
import java.math.BigInteger

/**
 * harptabs.py on the phone: its pages' rows of the index, the keys a song's title meets them with, and a tab page and
 * an artist page read, as selectolax reads them (core.html, lexbor's semantics). What the site looks like is
 * harptabs.py's docstring. A page without the expected markup is [HarpTabsParseError]: a provider error, never a miss.
 *
 * Numbers are Python's: a chip's count is `float()`'s ([PyFloat]) times its suffix, then `int()`; an artist's count of
 * tabs `int()`'s ([PyInt]), a count that isn't one Python's ValueError ([IllegalArgumentException], its words). Both
 * are kept whole ([BigInteger], Python's int), whatever their size: a count past SQLite's integers (no page writes
 * one) is refused only where Python writes it, by [sqliteInteger], so a page that is passed over (another artist's
 * tab) reads as Python's does.
 */
object HarpTabsPages {
    const val PROVIDER = "harptabs"

    /** The tabs an artist page renders, the most viewed first; the rest are its API's, which robots.txt closes. */
    const val PAGE_TABS = 30

    private val PAGE by lazy { PyRegex.compile("""https://(?:www\.)?harptabs\.com/((tab|artist)/(\d{1,9})/([a-z0-9-]{1,200}))""") }
    private val COUNT by lazy { PyRegex.compile("""(\d+(?:\.\d+)?)\s*([kKmM]?)""") }
    private val TAB_PATH by lazy { PyRegex.compile("""/(tab/(\d{1,9})/[a-z0-9-]{1,200})""") }
    private val TABS_SAID by lazy { PyRegex.compile("""([\d,]+)\s+tabs?""") }
    private val APOSTROPHE by lazy { PyRegex.compile("""['’ʼ]""") }

    /** page_url: the address of a page, from its path as the index keeps it (`tab/25/piano-man`). */
    fun pageUrl(path: String): String = HarpTabs.pageUrl(path)

    /** joined: a slug's key with each contraction's end joined to the word before it ("can-t" is "cant"). */
    fun joined(key: String): String = HarpTabs.joined(key)

    /** title_key: the key a song's title meets the tabs' titles with, its version suffixes gone first. */
    fun titleKey(title: String): String = HarpTabs.titleKey(title)

    /** song_title: the song a tab's title names, less what it says in brackets ("Piano Man (C Harmonica)"). */
    fun songTitle(title: String): String = HarpTabs.songTitle(title)

    /** song_key: the title part of the identity key of the song a tab's title names, Chinese in pinyin. */
    fun songKey(title: String): String = HarpTabs.songKey(title)

    /** harptabs.IndexRow: one page of the sitemap, as harptabs_index keeps it. */
    data class IndexRow(val path: String, val kind: String, val pageId: Long, val key: String)

    /** parse_page_url: the index row of a tab's or an artist's page; null for any other URL, or a slug without a
     * key. A tab's key joins each contraction's end to its word ([HarpTabs.joined]). */
    fun parsePageUrl(url: String): IndexRow? {
        val m = PyRe.fullmatch(PAGE, url) ?: return null
        val (path, kind, id, slug) = m.destructured
        val key = if (kind == HarpTabs.TAB) HarpTabs.joined(Normalize.ugSlugKey(slug)) else Normalize.ugSlugKey(slug)
        return if (key.isEmpty()) null else IndexRow(path, kind, int(id).longValueExact(), key)
    }

    /** title_keys: the keys a song's title meets the sitemap's tabs with: title_key's, and for a title with an
     * apostrophe that ends no contraction ("O'Brien"), that of the slug that writes it as a hyphen ("o-brien"), each
     * joined, the first of equals kept, none empty. */
    fun titleKeys(title: String): List<String> =
        listOf(HarpTabs.titleKey(title), HarpTabs.titleKey(PyRe.sub(APOSTROPHE, title) { " " }))
            .map(HarpTabs::joined).distinct().filter { it.isNotEmpty() }

    // --- a tab page ---------------------------------------------------------------------------------------------------

    /** harptabs.HarpTab: a tab page's title and artist as the site writes them ([artist] null for a tab of no known
     * artist, "by Unknown"), the tab ([body], the `<pre>`'s text) and its chips (null, or 0 for the views, when the
     * page shows none). */
    data class HarpTab(val title: String, val artist: String?, val body: String, val key: String? = null,
                       val harp: String? = null, val difficulty: String? = null,
                       val views: BigInteger = BigInteger.ZERO, val rating: Double? = null) {
        /** What a kept tab's version records of it, in harptabs.py's order. */
        fun raw(): JsonObject = JsonObject(linkedMapOf(
            "title" to JsonPrimitive(title), "artist" to str(artist), "key" to str(key), "harp" to str(harp),
            "difficulty" to str(difficulty), "views" to JsonPrimitive(views),
            "rating" to (rating?.let(PyJson::float) ?: JsonNull),
        ))
    }

    /** parse_tab_page: a tab page's title, artist, tab and chips; [HarpTabsParseError] for a page without a tab, a
     * title, or an artist named. A page that names the site's catch-all ("Unknown", "?":
     * [Normalize.placeholderArtist]) is of no artist. */
    fun parseTabPage(html: ByteArray, url: String? = null): HarpTab = tabPage(Html.parse(html), url)

    fun parseTabPage(html: String, url: String? = null): HarpTab = tabPage(Html.parse(html), url)

    private fun tabPage(tree: HtmlDoc, url: String?): HarpTab {
        val pre = tree.cssFirst("""[role="region"][aria-label="Harmonica tab notation"] pre""") ?: tree.cssFirst("pre")
        val body = pre?.let(::preText)
        if (body == null || Py.strip(body).isEmpty()) throw HarpTabsParseError("no tab (<pre>) on the page", url)
        val work = composition(tree)
        val composer = work["composer"]
        var artist = if (composer is JsonObject) Py.strip(strOr(composer["name"])) else ""
        artist = artist.ifEmpty { text(tree.cssFirst("""header a[href^="/artist/"]""")) }.ifEmpty { byLine(tree) }
        val title = Py.strip(strOr(work["name"])).ifEmpty { text(tree.cssFirst("header h1")) }
        if (artist.isEmpty() || title.isEmpty()) throw HarpTabsParseError("no title or artist on the page", url)
        val key = chip(tree, "key")
        return HarpTab(
            title = title, artist = if (Normalize.placeholderArtist(artist)) null else artist,
            body = PyText.strip(body, "\n") + "\n",
            key = key?.let { Py.strip(it.removePrefix("Key")).ifEmpty { null } },
            harp = chip(tree, "harp"), difficulty = chip(tree, "difficulty"),
            views = views(counted(tree, "lucide-eye")), rating = rating(counted(tree, "lucide-star")),
        )
    }

    /** `" ".join(node.text(deep=True).split())`, "" for no node. */
    private fun text(node: HtmlNode?): String = if (node == null) "" else Py.split(node.text(deep = true)).joinToString(" ")

    /** _composition: the page's JSON-LD `MusicComposition`, or an empty object; a script that isn't JSON passed
     * over. */
    private fun composition(tree: HtmlDoc): JsonObject {
        for (node in tree.css("""script[type="application/ld+json"]""")) {
            val data = try {
                PyJson.loads(node.text(deep = true))
            } catch (_: IllegalArgumentException) {  // json.loads' ValueError, and its RecursionError
                continue
            }
            if (data is JsonObject && isText(data["@type"], "MusicComposition")) return data
        }
        return JsonObject(emptyMap())
    }

    /** json.loads' NaN and infinities, as PyJson.loads writes them: truthy, as Python's floats are. */
    private val NOT_FINITE = setOf("NaN", "Infinity", "-Infinity")

    private fun isText(e: JsonElement?, s: String) = e is JsonPrimitive && e.isString && e.content == s

    /** `str(value or "")` of a value json.loads made: Python's truth, then its str(). */
    private fun strOr(e: JsonElement?): String = if (e == null || !truthy(e)) "" else PyValues.str(e)

    private fun truthy(e: JsonElement): Boolean = when (e) {
        is JsonNull -> false
        is JsonArray -> e.isNotEmpty()
        is JsonObject -> e.isNotEmpty()
        is JsonPrimitive -> when {
            e.isString -> e.content.isNotEmpty()
            e.content == "true" -> true
            e.content == "false" -> false
            e.content in NOT_FINITE -> true
            else -> BigDecimal(e.content).signum() != 0  // a number: nonzero
        }
    }

    /** _chip: the text of the chip that links to `/search?<query>=`: "Key C", "Diatonic". */
    private fun chip(tree: HtmlDoc, query: String): String? =
        text(tree.cssFirst("""a[href^="/search?$query="]""")).ifEmpty { null }

    /** _counted: the text of the chip whose icon is [icon] (`lucide-eye`: the views; `lucide-star`: the rating). */
    private fun counted(tree: HtmlDoc, icon: String): String? = iconChip(tree.css("li > span"), icon)

    private fun iconChip(nodes: List<HtmlNode>, icon: String): String? {
        for (node in nodes) {
            val svg = node.cssFirst("svg") ?: continue
            if (icon in Py.split(svg.attributes["class"] ?: "")) return text(node).ifEmpty { null }
        }
        return null
    }

    /** _views: "1.1M" is 1,100,000, "57k" 57,000, "974" 974; 0 for none, or one that isn't a count. `int()` of the
     * float, every digit of it ("9"×30 + "M": a float near 10^36, past a Long); an infinity 0. */
    fun views(text: String?): BigInteger {
        val m = PyRe.fullmatch(COUNT, Py.strip((text ?: "").replace(",", ""))) ?: return BigInteger.ZERO
        val n = PyFloat.parse(m.groupValues[1])!! * when (Py.asciiLower(m.groupValues[2])) {
            "k" -> 1_000
            "m" -> 1_000_000
            else -> 1
        }
        return if (n.isFinite()) BigDecimal(n).toBigInteger() else BigInteger.ZERO
    }

    /** sqlite3's binding of Python's int: within SQLite's 64 bits, else its OverflowError (an
     * [ArithmeticException], in its words), raised where Python's statement would be, so that nothing it writes is
     * written. */
    fun sqliteInteger(n: BigInteger): Long =
        if (n.bitLength() < Long.SIZE_BITS) n.toLong()
        else throw ArithmeticException("Python int too large to convert to SQLite INTEGER")

    /** _rating: the chip's rating, 0 to 5; null for none, or one that isn't. */
    fun rating(text: String?): Double? {
        val value = PyFloat.parse(Py.strip(text ?: "")) ?: return null
        return if (value.isFinite() && value >= 0 && value <= 5) value else null
    }

    /** _by_line: the artist the header's line under the title names ("by Unknown · posted by …"): its first child
     * element of a link or a span, its text; "" with no such line. */
    private fun byLine(tree: HtmlDoc): String {
        val line = tree.cssFirst("header h1 + p")
        if (line == null || !text(line).startsWith("by ")) return ""
        return line.children(includeText = false).firstOrNull { it.tag == "a" || it.tag == "span" }?.let(::text) ?: ""
    }

    /** _pre_text: the tab's `<pre>` as its lines show: a `<br>` breaks a line, and so does the end of a `<p>` (or a
     * `<div>`) where no line break follows it in the page. It edits the tree, as Python's does (HtmlTreeReplay holds
     * it to what selectolax read of every `<pre>` of vectors/html/tree.jsonl). */
    fun preText(pre: HtmlNode): String {
        for (node in pre.css("br")) node.replaceWith("\n")
        for (node in pre.css("p, div")) {
            val after = node.next
            if (after != null && !(after.isText && (after.textContent ?: "").startsWith("\n"))) node.insertAfter("\n")
        }
        return pre.text(deep = true)
    }

    // --- an artist page -----------------------------------------------------------------------------------------------

    /** parse_artist_page: an artist page's name, the tabs it says they have and those it lists (each tab once, where
     * it first came, as its last card says it); [HarpTabsParseError] for a page without its header (the name in its
     * `<h1>`), or one that says they have tabs and lists none caracole can read (its cards changed, say: never an
     * artist without tabs). */
    fun parseArtistPage(html: ByteArray, url: String? = null): HarpArtistPage = artistPage(Html.parse(html), url)

    fun parseArtistPage(html: String, url: String? = null): HarpArtistPage = artistPage(Html.parse(html), url)

    private fun artistPage(tree: HtmlDoc, url: String?): HarpArtistPage {
        val name = text(tree.cssFirst("main header h1"))
        if (name.isEmpty()) throw HarpTabsParseError("no artist's name (main header h1) on the page", url)
        val listed = tree.css("main div.group").mapNotNull(::card)
        val said = PyRe.search(TABS_SAID, text(tree.cssFirst("main header p")))
        val tabs = if (said != null) int(said.groupValues[1].replace(",", "")) else listed.size.toBigInteger()
        if (tabs.signum() != 0 && listed.isEmpty()) {
            throw HarpTabsParseError("the page says $tabs tabs and lists none caracole can read", url)
        }
        val once = LinkedHashMap<Long, HarpListedTab>()
        for (tab in listed) once[tab.tabId] = tab
        return HarpArtistPage(name, tabs.max(listed.size.toBigInteger()), once.values.toList())
    }

    /** _card: a card's tab, or null for one that links to no tab page. */
    private fun card(card: HtmlNode): HarpListedTab? {
        val link = card.cssFirst("""h3 a[href^="/tab/"]""")
        val found = link?.let { PyRe.fullmatch(TAB_PATH, it.attributes["href"] ?: "") }
        val title = text(link)
        if (found == null || title.isEmpty()) return null
        val said = card.cssFirst("h3 + p")?.css("span")?.map(::text) ?: emptyList()
        val key = said.firstOrNull { it.startsWith("Key ") }?.let { Py.strip(it.removePrefix("Key")) }
        val difficulty = card.cssFirst("""span[class*="text-diff-"]""")
        return HarpListedTab(int(found.groupValues[2]).longValueExact(), found.groupValues[1], title,
                             key = key?.ifEmpty { null }, difficulty = text(difficulty).ifEmpty { null },
                             views = views(iconChip(card.css("span"), "lucide-eye")),
                             rating = rating(iconChip(card.css("span"), "lucide-star")))
    }

    /** `int(s)` of what a pattern's `\d` matched (decimal digits of any script, none maybe): its ValueError an
     * [IllegalArgumentException] in Python's words, for no digit or more than Python reads. */
    private fun int(digits: String): BigInteger = PyInt.parse(digits) ?: throw IllegalArgumentException(
        if (digits.isEmpty()) {
            "invalid literal for int() with base 10: ${PyStr.repr(digits)}"
        } else {
            "Exceeds the limit (${PyInt.MAX_DIGITS} digits) for integer string conversion: value has " +
                "${Py.len(digits)} digits; use sys.set_int_max_str_digits() to increase the limit"
        },
    )

    private fun str(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull
}
