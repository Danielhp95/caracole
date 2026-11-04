package io.github.danielhp95.caracole.core.library.internal.overrides

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.GameTabsPick
import io.github.danielhp95.caracole.core.library.HarpTabsPick
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.TabUrlRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonElement

/**
 * overrides.py's readings of an address a user pasted, youtube_urls.video_id_from_url and ug/sitemap.classify_tab_url,
 * line for line: each pattern Python's own, compiled by PyRegex (a `\d` is any decimal digit, as Python reads one, and
 * int() reads it), each strip Python's whitespace, urlsplit Python 3.14's (PyUrl), a host lowercased as str.lower.
 * [OverridesError] where overrides.py raises one, with its words; [IllegalArgumentException] where Python's int()
 * raises ValueError (a digit str.isdigit takes that int() doesn't, "²").
 */
internal object Addresses {
    // UG's hosts as an address bar shows them, in any case: www and tabs, the bare domain, and a language edition's.
    private val UG_HOST by lazy { PyRegex.compile("(?:(?:www|tabs|[a-z]{2})\\.)?ultimate-guitar\\.com") }
    private val SCHEME by lazy { PyRegex.compile("(?i)[a-z][a-z0-9+.-]*://") }
    private val TAB_PATH by lazy { PyRegex.compile("/tab/(?:[^/]+/)?(?:[^/]*-)?(\\d+)") }
    const val TAB_HOST = "https://tabs.ultimate-guitar.com"
    private val ARTIST_PATH by lazy { PyRegex.compile("/artist/(?:[^/?#]+_)?\\d+") }
    const val ARTIST_HOST = "https://www.ultimate-guitar.com"
    const val ARTIST_PAGE_SHAPE = "$ARTIST_HOST/artist/…"
    const val TAB_PAGE_SHAPE = "$TAB_HOST/tab/…"
    private val LACUERDA_HOST by lazy { PyRegex.compile("(?:(?:acordes|www)\\.)?lacuerda\\.net") }
    private val LACUERDA_PATH by lazy {
        PyRegex.compile("/([a-z0-9_]+)/([a-z0-9_]+?)(?:(?:-([1-9][0-9]*))?(\\.shtml))?")
    }
    const val LACUERDA_BASE = "https://acordes.lacuerda.net"
    const val LACUERDA_PAGE_SHAPE = "$LACUERDA_BASE/<artist>/<song>"
    private val HARPTABS_HOST by lazy { PyRegex.compile("(?:www\\.)?harptabs\\.com") }
    private val HARPTABS_PATH by lazy { PyRegex.compile("/tab/([1-9][0-9]{0,8})/([a-z0-9-]{1,200})") }
    const val HARPTABS_BASE = "https://www.harptabs.com"
    const val HARPTABS_PAGE_SHAPE = "$HARPTABS_BASE/tab/<id>/<slug>"
    private val AZLYRICS_HOST by lazy { PyRegex.compile("(?:www\\.)?azlyrics\\.com") }
    private val AZLYRICS_PATH by lazy { PyRegex.compile("/lyrics/[a-z0-9-]+/[a-z0-9-]+\\.html") }
    const val AZLYRICS_BASE = "https://www.azlyrics.com"
    private val GAMETABS_HOST by lazy { PyRegex.compile("(?:www\\.)?gametabs\\.net") }
    private val GAMETABS_PATH by lazy { PyRegex.compile("/tabs/([a-z0-9_-]{1,200})/([a-z0-9_-]{1,200})") }
    const val GAMETABS_BASE = "https://gametabs.net"
    const val GAMETABS_PAGE_SHAPE = "$GAMETABS_BASE/tabs/<game>/<tab>"

    // youtube_urls.py
    private val VIDEO_ID by lazy { PyRegex.compile("[A-Za-z0-9_-]{11}") }
    private val YOUTUBE_HOSTS by lazy { PyRegex.compile("(?:(?:www|m|music)\\.)?youtube\\.com") }
    private const val SHORT_HOST = "youtu.be"
    private val PATH_ID by lazy { PyRegex.compile("/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})") }

    // ug/sitemap.py
    private val KEEP_TYPES = setOf("chords", "tabs", "ukulele")
    private val TYPE_TOKENS = listOf("guitar-pro", "chords", "tabs", "bass", "ukulele", "power", "official", "video",
                                     "musescore", "drums")
    const val BARE = "bare"
    const val UNRECOGNIZED = "unrecognized"
    private val TAB_URL by lazy { PyRegex.compile("https?://tabs\\.ultimate-guitar\\.com/tab/([^/]*)/([^/]*)-(\\d+)") }
    private val BARE_TAB_URL by lazy { PyRegex.compile("https?://tabs\\.ultimate-guitar\\.com/tab/\\d+") }

    /** Python's `int(text)` for a text str.isdigit or a `\d+` took; ValueError's words for one it can't read. A
     * value past a Long (Python's int has no end) is refused as no tab page, `notTab`. */
    private fun int(text: String, notTab: () -> Nothing): Long {
        val value = PyInt.parse(text)
            ?: throw IllegalArgumentException("invalid literal for int() with base 10: ${Py.slice(PyStr.repr(text), 0, 200)}")
        if (value.bitLength() > 63) notTab()
        return value.toLong()
    }

    /** The text an address reader takes, `https://` put before one written without a scheme (overrides._SCHEME,
     * any case). */
    private fun withScheme(text: String): String = if (PyRe.match(SCHEME, text) == null) "https://$text" else text

    private fun split(text: String): PyUrl.Split? = try {
        PyUrl.urlsplit(text)
    } catch (e: PyUrl.Invalid) {
        null  // a link urllib can't parse ("Invalid IPv6 URL"): no page
    }

    private fun http(parts: PyUrl.Split?): Boolean = parts != null && (parts.scheme == "http" || parts.scheme == "https")

    fun overrideKey(display: String): String {
        val at = display.indexOf(" - ")
        val artist = if (at < 0) "" else PyText.strip(display.substring(0, at))
        val title = if (at < 0) "" else PyText.strip(display.substring(at + 3))
        if (at < 0 || artist.isEmpty() || title.isEmpty()) {
            throw OverridesError("expected \"Artist - Title\", got ${PyStr.repr(display)}")
        }
        return Normalize.identityKey(artist, title)
    }

    /** overrides._ug_path: the path of an address on one of UG's hosts, without its query, fragment and trailing
     * slash; null for anything else. */
    fun ugPath(url: String): String? {
        val parts = split(withScheme(PyText.strip(url)))
        if (!http(parts) || PyRe.fullmatch(UG_HOST, PyText.lower(parts!!.netloc)) == null) return null
        return parts.path.trimEnd('/')
    }

    fun tabIdFromUrl(url: String): Long {
        val notTab: () -> Nothing = { throw OverridesError("not an Ultimate Guitar tab URL: ${PyStr.repr(url)}") }
        if (PyText.allDigits(PyText.strip(url))) return int(url, notTab)
        val path = ugPath(url)
        val m = path?.let { PyRe.fullmatch(TAB_PATH, it) } ?: notTab()
        return int(m.groupValues[1], notTab)
    }

    fun pinUrl(value: String): String {
        val text = PyText.strip(value)
        if (PyText.allDigits(text)) {
            return "$TAB_HOST/tab/${int(text) { throw OverridesError("not an Ultimate Guitar tab URL: ${PyStr.repr(value)}") }}"
        }
        return TAB_HOST + (ugPath(text) ?: "")
    }

    fun artistPageAddress(url: String): String? {
        val path = ugPath(url) ?: return null
        return if (PyRe.fullmatch(ARTIST_PATH, path) != null) ARTIST_HOST + path else null
    }

    /** overrides._artist_url_value: the artist's page, or one of their tab pages written as a pin's is; null for
     * anything else, a bare number included. A value that isn't text is none. */
    fun artistUrlValue(url: JsonElement): String? {
        val text = PyValues.text(url) ?: return null
        val page = artistPageAddress(text)
        if (page != null || PyText.allDigits(PyText.strip(text))) return page
        try {
            tabIdFromUrl(text)
        } catch (e: OverridesError) {
            return null
        }
        return pinUrl(text)
    }

    fun pastedTabId(url: String): Long? {
        if (!url.startsWith("$TAB_HOST/tab/")) return null
        return try {
            tabIdFromUrl(url)
        } catch (e: OverridesError) {
            null
        }
    }

    /** The parts of an address a pick parser reads: [url] stripped (a value that isn't text is ""), `https://` put
     * before it when it has no scheme, split; null where urlsplit refuses it. */
    private fun pickParts(url: JsonElement): PyUrl.Split? {
        var text = PyValues.text(url)?.let(PyText::strip) ?: ""
        if (text.isNotEmpty() && PyRe.match(SCHEME, text) == null) text = "https://$text"
        return split(text)
    }

    fun lacuerdaPickFromUrl(url: JsonElement): LaCuerdaPick {
        val parts = pickParts(url)
        var found: MatchResult? = null
        if (http(parts) && PyRe.fullmatch(LACUERDA_HOST, PyText.lower(parts!!.netloc)) != null) {
            val path = if (parts.path.endsWith(".shtml")) parts.path else parts.path.trimEnd('/')
            found = PyRe.fullmatch(LACUERDA_PATH, path)
        }
        val n = found?.groups?.get(3)?.value
        // A version past an Int is refused as no page (Python's int has no end): no song has a billion versions.
        if (found == null || found.groupValues[1] == "tabs" || (!n.isNullOrEmpty() && n.toIntOrNull() == null)) {
            throw OverridesError("expected a LaCuerda song's page ($LACUERDA_PAGE_SHAPE) or one of its versions' " +
                                     "(…/<song>-2.shtml), got ${PyValues.repr(url)}")
        }
        val shtml = found.groups[4]?.value
        val version = if (!n.isNullOrEmpty()) n.toInt() else if (!shtml.isNullOrEmpty()) 1 else null
        return LaCuerdaPick(found.groupValues[1], found.groupValues[2], version)
    }

    fun harptabsPickFromUrl(url: JsonElement): HarpTabsPick {
        val parts = pickParts(url)
        var found: MatchResult? = null
        if (http(parts) && PyRe.fullmatch(HARPTABS_HOST, PyText.lower(parts!!.netloc)) != null) {
            found = PyRe.fullmatch(HARPTABS_PATH, parts.path.trimEnd('/'))
        }
        found ?: throw OverridesError("expected a harptabs.com tab's page ($HARPTABS_PAGE_SHAPE), got ${PyValues.repr(url)}")
        return HarpTabsPick(found.groupValues[1].toLong(), found.groupValues[2])
    }

    fun gametabsPickFromUrl(url: JsonElement): GameTabsPick {
        val parts = pickParts(url)
        var found: MatchResult? = null
        if (http(parts) && PyRe.fullmatch(GAMETABS_HOST, PyText.lower(parts!!.netloc)) != null) {
            found = PyRe.fullmatch(GAMETABS_PATH, parts.path.trimEnd('/'))
        }
        found ?: throw OverridesError("expected a gametabs.net tab's page ($GAMETABS_PAGE_SHAPE), got ${PyValues.repr(url)}")
        return GameTabsPick(found.groupValues[1], found.groupValues[2])
    }

    fun azlyricsPageFromUrl(url: JsonElement): String {
        val parts = pickParts(url)
        if (!http(parts) || PyRe.fullmatch(AZLYRICS_HOST, PyText.lower(parts!!.netloc)) == null ||
            PyRe.fullmatch(AZLYRICS_PATH, parts.path) == null) {
            throw OverridesError("expected an AZLyrics lyrics page (azlyrics.com/lyrics/artist/song.html), got " +
                                     PyValues.repr(url))
        }
        return AZLYRICS_BASE + parts.path
    }

    /** youtube_urls.video_id_from_url: a value that isn't text is none. */
    fun videoIdFromUrl(url: JsonElement): String? {
        val parts = split(withScheme(PyText.strip(PyValues.text(url) ?: return null)))
        if (!http(parts)) return null
        val host = PyText.lower(parts!!.netloc)
        val found = when {
            host == SHORT_HOST -> parts.path.trim('/')
            PyRe.fullmatch(YOUTUBE_HOSTS, host) != null -> {
                val m = PyRe.fullmatch(PATH_ID, parts.path.trimEnd('/'))
                when {
                    m != null -> m.groupValues[1]
                    parts.path.trimEnd('/') == "/watch" -> PyUrl.parseQs(parts.query)["v"]?.firstOrNull() ?: ""
                    else -> return null
                }
            }
            else -> return null
        }
        return if (PyRe.fullmatch(VIDEO_ID, found) != null) found else null
    }

    fun watchUrl(videoId: String): String = "https://www.youtube.com/watch?v=$videoId"

    /** ug/sitemap._peel_type: `de-musica-ligera-chords` as (`de-musica-ligera`, `chords`). */
    private fun peelType(rest: String): Pair<String, String>? {
        for (token in TYPE_TOKENS) {
            if (rest == token) return "" to token
            if (rest.endsWith(token) && rest[rest.length - token.length - 1] == '-') {
                return rest.substring(0, rest.length - token.length - 1) to token
            }
        }
        return null
    }

    /** ug/sitemap.classify_tab_url: the index row, or why there is none ([BARE], [UNRECOGNIZED], or a type the index
     * doesn't keep). */
    fun classifyTabUrl(url: String): Any {
        val m = PyRe.fullmatch(TAB_URL, url) ?: return if (PyRe.fullmatch(BARE_TAB_URL, url) != null) BARE else UNRECOGNIZED
        val (artistSlug, rest, tabId) = m.destructured
        val (songSlug, kind) = peelType(rest) ?: return UNRECOGNIZED
        if (kind !in KEEP_TYPES) return kind
        val artistKey = Normalize.ugSlugKey(artistSlug)
        val songKey = Normalize.ugSlugKey(songSlug)
        if (artistKey.isEmpty() || songKey.isEmpty()) return UNRECOGNIZED
        val id = PyInt.parse(tabId) ?: return UNRECOGNIZED
        if (id.bitLength() > 63) return UNRECOGNIZED
        return TabUrlRow(id.toLong(), artistKey, songKey, kind, url.substringAfter("/tab/"))
    }
}
