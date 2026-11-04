package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.PyBits
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.SearchPage
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.Spanish
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyCodec
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import java.math.BigInteger

/**
 * lacuerda.py's pages read on the phone, as the computer reads them (selectolax's lexbor through core.html, Python's
 * regexes through PyRegex, its str and int on code points): an artist's page (its songs, their order of popularity,
 * the artist's name, LaCuerda's "no such artist"), a version's sheet in UG markup, an answer of its own search (every
 * page cut short refused), the lcd codes, which song of a page is a title, whether a song is Spanish, and the search's
 * words and address. Each takes the page's text, `resp.text` (UTF-8 with replacement: [PyCodec.utf8Replace] for the
 * bytes). A page that won't parse is a [LaCuerdaParseError], never a miss; a link urlsplit refuses is its ValueError
 * ([io.github.danielhp95.caracole.core.py.PyUrl.Invalid]), as on the computer.
 * tests/conformance/vectors/sites/lacuerda_pages.jsonl holds it to Python's answers (LaCuerdaPagesTest).
 */
object LaCuerdaPages {
    const val BASE_URL = LaCuerdaUrls.BASE_URL
    const val PROVIDER = "lacuerda"

    /** lacuerda.ACORDES: the lcd letter of a "Letra y Acordes" version. */
    const val ACORDES = "R"

    /** lacuerda.SEARCH_LETTERS: LaCuerda's search reads no shorter word. */
    const val SEARCH_LETTERS = 4

    // --- slugs and URLs ---------------------------------------------------------------------------------------

    fun artistSlug(name: String): String = LaCuerdaUrls.artistSlug(name)
    fun artistSlugCandidates(name: String): List<String> = LaCuerdaUrls.artistSlugCandidates(name)
    fun artistUrl(slug: String): String = LaCuerdaUrls.artistUrl(slug)
    fun versionUrl(artist: String, song: String, n: Int): String = LaCuerdaUrls.versionUrl(artist, song, n)
    fun songUrl(artist: String, song: String): String = LaCuerdaUrls.songUrl(artist, song)

    // --- the artist page --------------------------------------------------------------------------------------

    private val SOFT_404 by lazy { PyRegex.compile("""(?i)\s*aqu[ií] llega:""") }
    private const val SOFT_404_MAX_BYTES = 1024

    /** is_missing_artist_page: whether an artist page that came back with HTTP 200 is LaCuerda's short "aqui llega:…"
     * body for "no such artist" (under 1024 bytes of UTF-8). Any other page without the list is no miss. */
    fun isMissingArtistPage(html: String): Boolean =
        PyBits.utf8Length(html) < SOFT_404_MAX_BYTES && PyRe.match(SOFT_404, html) != null

    /**
     * parse_lcd: an lcd code ("RHRTTTDTB-314865972") as its types, one letter a version (upper-cased as str.upper
     * does), and its ranking, each character a base-36 digit; a ranking that isn't one rank per version falls back
     * to version order.
     */
    fun parseLcd(lcd: String): Pair<String, List<Int>> {
        val stripped = Py.strip(lcd)
        val dash = stripped.indexOf('-')
        val letters = PyUnicode.upper(if (dash < 0) stripped else stripped.substring(0, dash))
        val digits = if (dash < 0) "" else stripped.substring(dash + 1)
        val inOrder = (1..Py.len(letters)).toList()
        val codes = Py.codePoints(digits)
        if (codes.size != inOrder.size) return letters to inOrder
        val ranking = codes.map { PyBits.base36(it) ?: return letters to inOrder }
        if (ranking.sorted() != inOrder) return letters to inOrder
        return letters to ranking
    }

    /** best_acordes_version: the best-ranked "Letra y Acordes" version of a song, or null if it has none. */
    fun bestAcordesVersion(song: LaCuerdaSong): Int? {
        val types = Py.codePoints(song.types)
        return song.ranking.firstOrNull { it >= 1 && it <= types.size && types[it - 1] == ACORDES[0].code }
    }

    /**
     * parse_artist_page: the songs an artist page lists (`ul#b_main > li[lcd]`, each with a link), in page order. A
     * [LaCuerdaParseError] for a page with no `ul#b_main`, or one whose items are all unreadable: never "no songs".
     */
    fun parseArtistPage(html: String, url: String? = null): List<LaCuerdaSong> {
        val tree = Html.parse(html)
        if (tree.cssFirst("ul#b_main") == null) throw LaCuerdaParseError("no song list (ul#b_main)", url = url)
        val songs = ArrayList<LaCuerdaSong>()
        for (item in tree.css("ul#b_main > li[lcd]")) {
            val link = item.cssFirst("a[href]")
            val slug = if (link != null) slugFromHref(link.attr("href") ?: "") else ""
            if (slug.isEmpty()) continue
            val lcd = item.attr("lcd") ?: ""
            val (types, ranking) = parseLcd(lcd)
            songs += LaCuerdaSong(slug, linkTitle(link!!), types, ranking, lcd)
        }
        if (songs.isEmpty() && tree.cssFirst("ul#b_main > li") != null) {
            throw LaCuerdaParseError("no song in the list has an lcd code and a link", url = url)
        }
        return songs
    }

    /** [parseArtistPage] of the page's bytes, as `resp.text` reads them. */
    fun parseArtist(html: ByteArray, url: String? = null): List<LaCuerdaSong> =
        parseArtistPage(PyCodec.utf8Replace(html), url)

    /** _slug_from_href: the link's last path segment ("de_musica_ligera", linked relatively). */
    private fun slugFromHref(href: String): String =
        PyBits.path(Py.strip(href)).split("/").lastOrNull { it.isNotEmpty() } ?: ""

    /** _link_title: the link's text without its trailing `<em>acordes</em>` label, its spaces collapsed. */
    private fun linkTitle(link: HtmlNode): String {
        val nodes = link.children(includeText = true).toMutableList()
        while (nodes.isNotEmpty() && nodes.last().tag == "-text" && Py.strip(nodes.last().textContent ?: "").isEmpty()) {
            nodes.removeAt(nodes.lastIndex)
        }
        if (nodes.isNotEmpty() && nodes.last().tag == "em") nodes.removeAt(nodes.lastIndex)
        return PyBits.collapsed(nodes.joinToString("") { it.text(deep = true) })
    }

    private val POP_ORDER by lazy { PyRegex.compile("""var\s+popOrder\s*=\s*\[([^\]]*)\]""") }

    /**
     * parse_popularity: each song's place in the artist page's order of popularity (`var popOrder = [5,9,…]`, the
     * items of `ul#b_main` in page order, most popular first), by slug, 0 the most popular, in that order. A number
     * past the list is skipped; a page without the order, or with one that isn't int()'s numbers, gives none.
     */
    fun parsePopularity(html: String): Map<String, Int> {
        val found = PyRe.search(POP_ORDER, html) ?: return emptyMap()
        val order = ArrayList<BigInteger>()
        for (n in found.groups[1]!!.value.split(",")) {
            if (Py.strip(n).isEmpty()) continue
            order += PyInt.parse(n) ?: return emptyMap()
        }
        val slugs = Html.parse(html).css("ul#b_main > li").map { item ->
            item.cssFirst("a[href]")?.let { slugFromHref(it.attr("href") ?: "") } ?: ""
        }
        val places = LinkedHashMap<String, Int>()
        for ((place, n) in order.withIndex()) {
            if (n.signum() < 0 || n >= BigInteger.valueOf(slugs.size.toLong())) continue
            val slug = slugs[n.toInt()]
            if (slug.isNotEmpty() && slug !in places) places[slug] = place
        }
        return places
    }

    /** parse_artist_name: the artist's name as their page heads it (`div.bTit > h1`), or null without one. */
    fun parseArtistName(html: String): String? {
        val heading = Html.parse(html).cssFirst("div.bTit > h1")
        val name = if (heading != null) PyBits.collapsed(heading.text(deep = true)) else ""
        return name.ifEmpty { null }
    }

    // --- the search -------------------------------------------------------------------------------------------

    private val SEARCH_WORD by lazy { PyRegex.compile("[a-z0-9]+") }

    /** search_words: the words LaCuerda's search reads of a query, accents folded (ñ as n), every symbol a break, four
     * letters or more each, each once, in the query's order. */
    fun searchWords(query: String): List<String> =
        LinkedHashSet(PyRe.findall(SEARCH_WORD, Normalize.fold(PyUnicode.nfc(query))).filter { Py.len(it) >= SEARCH_LETTERS })
            .toList()

    /** search_url: the first page of LaCuerda's search for [query]'s words, its songs (`canc=1`) or, with [songsOnly]
     * false, a general search (`canc=0`); IllegalArgumentException, Python's ValueError, for a query it reads no word
     * of. */
    fun searchUrl(query: String, songsOnly: Boolean = true): String {
        val words = searchWords(query)
        require(words.isNotEmpty()) {
            "LaCuerda's search reads no word of ${PyStr.repr(query)}: none has $SEARCH_LETTERS letters"
        }
        return "$BASE_URL/busca.php?exp=${words.joinToString("+")}&canc=${if (songsOnly) 1 else 0}&ord=0&ini=0"
    }

    /**
     * parse_search: a page of LaCuerda's search, its songs or the artists it lists in their place, and how many
     * results it counts ("0 resultados" an answer with none). A [LaCuerdaParseError] for a page that doesn't count its
     * results, whose table or list isn't closed, whose script's arrays are missing or disagree, with a row whose link
     * is no artist's page, or with fewer rows than it counts on its only page of them: a page cut short is never "no
     * results".
     */
    fun parseSearch(html: String, url: String? = null): LaCuerdaSearchAnswer = SearchPage.parse(html, url)

    /** [parseSearch] of the page's bytes, as `resp.text` reads them. */
    fun parseSearch(html: ByteArray, url: String? = null): LaCuerdaSearchAnswer =
        parseSearch(PyCodec.utf8Replace(html), url)

    // --- matching a title -------------------------------------------------------------------------------------

    /**
     * match_title: the song of [songs] that is [title], or null: the slug key of the cleaned title against each
     * song's title and its slug, the best rapidfuzz ratio if it reaches [cutoff]; on a tie, a song with an acordes
     * version, then the first.
     */
    fun matchTitle(songs: List<LaCuerdaSong>, title: String, cutoff: Double = 90.0): LaCuerdaSong? {
        val query = Normalize.slugKey(Normalize.cleanTitle(title))
        if (query.isEmpty()) return null
        var best: LaCuerdaSong? = null
        var bestScore = -1.0
        var bestAcordes = false
        for (song in songs) {
            val score = maxOf(Fuzz.ratio(query, Normalize.slugKey(song.title)),
                              Fuzz.ratio(query, Normalize.ugSlugKey(song.slug.replace("_", "-"))))
            val acordes = bestAcordesVersion(song) != null
            if (score > bestScore || (score == bestScore && acordes && !bestAcordes)) {
                best = song
                bestScore = score
                bestAcordes = acordes
            }
        }
        return if (bestScore >= cutoff) best else null
    }

    // --- the version page -------------------------------------------------------------------------------------

    /**
     * parse_version_page: the sheet of a version page (`div#t_body > pre`) in UG markup: `<A>Bm</A>` as `[ch]Bm[/ch]`
     * (its padding moved outside), `<br>` a line break, every other tag dropped and its text kept, entities decoded,
     * non-breaking spaces as spaces, the lines and their spaces exactly. A [LaCuerdaParseError] with no sheet, or an
     * empty one.
     */
    fun parseVersionPage(html: String, url: String? = null): String {
        val pre = Html.parse(html).cssFirst("div#t_body > pre")
            ?: throw LaCuerdaParseError("no sheet (div#t_body > pre)", url = url)
        val sheet = ugMarkup(pre).replace(' ', ' ')
        if (Py.strip(sheet).isEmpty()) throw LaCuerdaParseError("empty sheet", url = url)
        return sheet
    }

    private fun ugMarkup(node: HtmlNode): String {
        val out = StringBuilder()
        for (child in node.children(includeText = true)) {
            val tag = child.tag
            when {
                tag == "-text" -> out.append(child.textContent ?: "")
                tag == "a" -> out.append(chord(child.text(deep = true)))
                tag == "br" -> out.append('\n')
                tag.startsWith("-") || tag == "script" || tag == "style" -> Unit
                else -> out.append(ugMarkup(child))
            }
        }
        return out.toString()
    }

    /** _chord: `[ch]Am[/ch]`, any padding moved outside so the column stays put. */
    private fun chord(text: String): String {
        val name = Py.strip(text)
        if (name.isEmpty()) return text
        val lead = text.substring(0, text.length - PyBits.lstrip(text).length)
        val trail = text.substring(PyBits.rstrip(text).length)
        return "$lead[ch]$name[/ch]$trail"
    }

    // --- is it Spanish? ---------------------------------------------------------------------------------------

    /** is_spanish: Spanish function words outnumber English ones and make up 15% of the words or more (each character
     * of an unspaced script a word). */
    fun isSpanish(text: String): Boolean = Spanish.isSpanish(text)

    /** _language_counts: (Spanish function words, English ones, all words) in [text], as [isSpanish] counts them. */
    fun languageCounts(text: String): Triple<Int, Int, Int> = Spanish.counts(text)

    /** looks_spanish: the lyrics decide when there are any; else the title, by its marks, then [isSpanish]. */
    fun looksSpanish(title: String, lyrics: String? = null): Boolean = Spanish.looksSpanish(title, lyrics)

    // --- shared with SearchPage -------------------------------------------------------------------------------

    private val SLUG by lazy { PyRegex.compile("[a-z0-9_]+") }

    /** _SLUG.fullmatch. */
    internal fun isSlug(s: String): Boolean = PyRe.fullmatch(SLUG, s) != null

    /** _artist_slug_from_href: the slug of an artist page's link (`/estopa/`, or its full address); "" for any other. */
    internal fun artistSlugFromHref(href: String): String {
        val segments = PyBits.path(Py.strip(href)).split("/").filter { it.isNotEmpty() }
        return if (segments.size == 1 && isSlug(segments[0])) segments[0] else ""
    }

    private val LEADING_NUMBER by lazy { PyRegex.compile("""\s*(\d+)""") }

    /** _listed_artists: the artists of a `ul#i_main` (a link to their page, their name after an `<em>` label, their
     * songs counted in a `<span>`); a [LaCuerdaParseError] for a list with items but none with such a link. */
    internal fun listedArtists(main: HtmlNode, url: String?): List<LaCuerdaArtist> {
        val artists = ArrayList<LaCuerdaArtist>()
        val items = main.css("li")
        for (item in items) {
            val link = item.cssFirst("a[href]")
            val slug = if (link != null) artistSlugFromHref(link.attr("href") ?: "") else ""
            if (slug.isEmpty()) continue
            val name = PyBits.collapsed(link!!.children(includeText = true).filter { it.tag != "em" }
                                            .joinToString("") { it.text(deep = true) }.replace(' ', ' '))
            val count = item.cssFirst("span")
            val number = if (count != null) PyRe.match(LEADING_NUMBER, count.text(deep = true)) else null
            val songs = number?.let { PyInt.parse(it.groups[1]!!.value)!!.toLong() } ?: 0L
            artists += LaCuerdaArtist(slug, name.ifEmpty { slug }, songs)
        }
        if (items.isNotEmpty() && artists.isEmpty()) {
            throw LaCuerdaParseError("no artist in the list has a link to their page", url = url)
        }
        return artists
    }
}
