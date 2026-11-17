package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex

/** ug_urls.UgLink: a UG link pasted into the search box: its [kind] (`"tab"` or `"artist"`), the page's address as
 * caracole asks for it ([url]: a tab's on the tabs host, an artist's on www), a tab's id, and the type its slug names
 * ([type], one of [UgUrls.TYPE_TOKENS]; null for a bare `/tab/{id}`, a slug that names none, and an artist). */
data class UgLink(val kind: String, val url: String, val tabId: Long? = null, val type: String? = null) {
    companion object {
        const val TAB = "tab"
        const val ARTIST = "artist"
    }
}

/**
 * ug_urls.py on the phone: a UG link pasted into a search box, read as an address bar shows it, through the one reading
 * of UG's addresses overrides.py has too (`ug_path`):
 *
 * - **a tab page**: `/tab/{id}` or `/tab/{artist}/{song}-{type}-{id}` on one of UG's hosts (www, tabs, the bare
 *   domain, a language edition's), its query, fragment and trailing slash dropped, asked for on the tabs host; a
 *   slugged one names its type ([TYPE_TOKENS], as UG's sitemaps write them);
 * - **an artist page**: `/artist/{name}_{id}` or `/artist/{id}`, asked for on the www host, its `?filter=` and
 *   `?page=` dropped;
 * - anything else (UG's home, `/explore`, a search, a forum page, a tab's download or print page, a link with words
 *   around it) is no UG link.
 *
 * The text's spaces around it ([SPACES], neither str.strip's nor JavaScript's `\s`, as library.js's `ugLink` names
 * them) aside, it is one address with no space in it. A tab id past a Long is no link the phone reads (Python's int
 * has no end). vectors/web/ug_link.jsonl holds it to Python's (helpers/ug_links.py's shapes).
 */
object UgUrls {
    /** ug_urls.TYPE_TOKENS: "guitar-pro" first, peeled whole before a single word could match its last part. */
    val TYPE_TOKENS: List<String> = listOf("guitar-pro", "chords", "tabs", "bass", "ukulele", "power", "official", "video",
                                           "musescore", "drums")

    const val TAB_HOST = "https://tabs.ultimate-guitar.com"
    const val ARTIST_HOST = "https://www.ultimate-guitar.com"

    /** ug_urls.SPACES, a character class's body: controls, spaces and the like around a link, never in one. */
    const val SPACES = "\\x00-\\x20\\x7f-\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff"

    private val EDGES by lazy { PyRegex.compile("^[$SPACES]+|[$SPACES]+$") }
    private val SPACED by lazy { PyRegex.compile("[$SPACES]") }
    private val TAB_PATH by lazy { PyRegex.compile("/tab/(?:[^/]+/)?(?:[^/]*-)?(\\d+)") }
    private val SLUGGED by lazy { PyRegex.compile("/tab/[^/]+/([^/]+)-\\d+") }
    private val ARTIST_PATH by lazy { PyRegex.compile("/artist/(?:[^/?#]+_)?\\d+") }

    /** read_link: the UG page [text] is a link to, or null. */
    fun readLink(text: String): UgLink? {
        val link = PyRe.sub(EDGES, text) { "" }
        if (link.isEmpty() || PyRe.search(SPACED, link) != null) return null
        val path = OverrideUrls.ugPath(link) ?: return null
        PyRe.fullmatch(TAB_PATH, path)?.let { tab ->
            val id = PyInt.parse(tab.groupValues[1])?.takeIf { it.bitLength() <= 63 } ?: return null
            return UgLink(UgLink.TAB, TAB_HOST + path, id.toLong(), slugType(path))
        }
        if (PyRe.fullmatch(ARTIST_PATH, path) != null) return UgLink(UgLink.ARTIST, ARTIST_HOST + path)
        return null
    }

    /** _slug_type: the type a slugged tab page's address names (`/tab/radiohead/creep-chords-4169` is "chords"); null
     * for a bare `/tab/{id}` or a slug that names none. */
    private fun slugType(path: String): String? {
        val rest = PyRe.fullmatch(SLUGGED, path)?.groupValues?.get(1) ?: return null
        return TYPE_TOKENS.firstOrNull { rest == it || rest.endsWith("-$it") }
    }
}
