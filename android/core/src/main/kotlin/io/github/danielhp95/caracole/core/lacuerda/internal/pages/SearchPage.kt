package io.github.danielhp95.caracole.core.lacuerda.internal.pages

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlDoc
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearchAnswer
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearchSong
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSong
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import java.math.BigInteger

/**
 * lacuerda.parse_search: an answer of LaCuerda's search, read from its tree and, where a page cut short shows, from
 * its raw text with lacuerda.py's own regexes (IGNORECASE and DOTALL, as Python reads them): the table's and the
 * list's closing tags, the script's `var hds=[…]; var fns=[…]; var NMAX=…;`. Every refusal is lacuerda.py's, in its
 * order and words.
 */
internal object SearchPage {
    private val STATED by lazy { PyRegex.compile("""(?i)(\d[\d.,]*)\s+resultados?\b""") }
    private val SONG_TABLE by lazy { PyRegex.compile("""(?is)<table\b[^>]*\bid=['"]?s_main\b.*?</table\s*>""") }
    private val ARTIST_LIST by lazy { PyRegex.compile("""(?is)<ul\b[^>]*\bid=['"]?i_main\b.*?</ul\s*>""") }
    private val NMAX by lazy { PyRegex.compile("""\bvar\s+NMAX\s*=\s*(-?\d+)\s*;""") }
    private val QUOTED by lazy { PyRegex.compile("""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"""") }
    private val ROW_ID by lazy { PyRegex.compile("""r(\d+)""") }
    private val POINTS by lazy { PyRegex.compile("[.,]") }
    private val ARRAYS: Map<String, Regex> by lazy {
        listOf("hds", "fns").associateWith { PyRegex.compile("""\bvar\s+$it\s*=\s*\[([^\]]*)\]\s*;""") }
    }

    fun parse(html: String, url: String?): LaCuerdaSearchAnswer {
        val tree = Html.parse(html)
        val said = tree.cssFirst("div.s_res")
        val counted = said?.let { PyRe.search(STATED, it.text(deep = true)) }
            ?: throw LaCuerdaParseError("no count of results (div.s_res)", url = url)
        val stated = int(PyRe.sub(POINTS, counted.groups[1]!!.value) { "" })
        if (stated.signum() == 0) return LaCuerdaSearchAnswer()
        val found: LaCuerdaSearchAnswer
        val rows: Int
        val main = tree.cssFirst("ul#i_main")
        if (tree.cssFirst("table#s_main") != null) {
            if (PyRe.search(SONG_TABLE, html) == null) {
                throw LaCuerdaParseError("the results table isn't closed: the page was cut short", url = url)
            }
            found = LaCuerdaSearchAnswer(songs = songs(tree, html, url), stated = stated.longValueExact())
            rows = found.songs.size
        } else if (main != null) {
            if (PyRe.search(ARTIST_LIST, html) == null) {
                throw LaCuerdaParseError("the list of artists isn't closed: the page was cut short", url = url)
            }
            found = LaCuerdaSearchAnswer(artists = LaCuerdaPages.listedArtists(main, url), stated = stated.longValueExact())
            rows = found.artists.size
        } else {
            throw LaCuerdaParseError("neither songs (table#s_main) nor artists (ul#i_main) for the $stated results " +
                                         "it counts", url = url)
        }
        if (BigInteger.valueOf(rows.toLong()) < stated && !otherPages(tree) || rows == 0) {
            throw LaCuerdaParseError("$rows rows of the $stated results it counts, on its only page of them", url = url)
        }
        return found
    }

    /** _search_songs: table#s_main's songs, each one's slug from the script's arrays (`fns[NMAX-N]` for song `rN`). */
    private fun songs(tree: HtmlDoc, html: String, url: String?): List<LaCuerdaSearchSong> {
        val hds = strings(html, "hds")
        val fns = strings(html, "fns")
        val nmax = PyRe.search(NMAX, html)
        if (hds == null || fns == null || nmax == null) {
            throw LaCuerdaParseError("no song slugs in the page's script (var hds, fns, NMAX)", url = url)
        }
        val last = int(nmax.groups[1]!!.value)
        if (hds.size != fns.size || last != BigInteger.valueOf(fns.size - 1L)) {
            throw LaCuerdaParseError("the script's arrays disagree: ${hds.size} artists, ${fns.size} songs, " +
                                         "NMAX=$last", url = url)
        }
        val songs = ArrayList<LaCuerdaSearchSong>()
        for (row in tree.css("table#s_main tr")) {
            val items = row.css("ul.b_main > li")
            if (items.isEmpty()) continue
            val link = row.cssFirst("td a[href]")
            val slug = if (link != null) LaCuerdaPages.artistSlugFromHref(link.attr("href") ?: "") else ""
            if (slug.isEmpty()) throw LaCuerdaParseError("a row of results whose link is no artist's page", url = url)
            val name = PyBits.collapsed(link!!.text(deep = true).replace(' ', ' ')).ifEmpty { slug }
            for (item in items) {
                val number = PyRe.fullmatch(ROW_ID, item.attr("id") ?: "")
                val n = if (number != null) int(number.groups[1]!!.value) else BigInteger.ONE.negate()
                if (n.signum() < 0 || n > last) {
                    throw LaCuerdaParseError("a song numbered past the script's ${fns.size} slugs", url = url)
                }
                val song = fns[last.subtract(n).toInt()]
                if (!LaCuerdaPages.isSlug(song)) throw LaCuerdaParseError("no song slug: ${PyStr.repr(song)}", url = url)
                val lcd = item.attr("lcd") ?: ""
                val (types, ranking) = LaCuerdaPages.parseLcd(lcd)
                val title = PyBits.collapsed(item.text(deep = true).replace(' ', ' '))
                songs += LaCuerdaSearchSong(slug, name, LaCuerdaSong(song, title, types, ranking, lcd))
            }
        }
        if (songs.size != fns.size) {
            throw LaCuerdaParseError("${songs.size} songs in the table for the script's ${fns.size} slugs", url = url)
        }
        return songs
    }

    /** _strings: the quoted strings of the script's array `var NAME=[…];`, as written (escapes kept); null without one. */
    private fun strings(html: String, name: String): List<String>? {
        val found = PyRe.search(ARRAYS.getValue(name), html) ?: return null
        return PyRe.finditer(QUOTED, found.groups[1]!!.value).map { m ->
            (m.groups[1] ?: m.groups[2])!!.value
        }.toList()
    }

    /** _other_pages: whether the answer's `div.multipag` links another page of results than this one. */
    private fun otherPages(tree: HtmlDoc): Boolean {
        val multipag = tree.cssFirst("div.multipag") ?: return false
        return multipag.css("li").any { li ->
            Py.split(li.attr("class") ?: "").none { it == "sel" || it == "last" }
        }
    }

    /** int() of `\d`'s digits, of any script. */
    private fun int(digits: String): BigInteger = PyInt.parse(digits)
        ?: throw IllegalArgumentException("invalid literal for int() with base 10: ${PyStr.repr(digits)}")
}
