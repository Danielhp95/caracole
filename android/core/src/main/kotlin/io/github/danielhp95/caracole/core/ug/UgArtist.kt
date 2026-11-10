package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.internal.pages.PyValues
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** ug/artist.py's UGArtistPage: one page of an artist's tab list. [tabs] are this page's, of every type, links to
 * UG's paid app left out; [page] its number and [pages] the highest page number UG links to; [filters] each of
 * caracole's kinds UG offers a filtered list of (chords, tabs). */
data class UgArtistPage(val artistId: Long, val name: String, val tabs: List<UgVersion>, val page: Int, val pages: Int,
                        val filters: Set<String>)

/**
 * ug/artist.py: UG's artist pages, every tab of an artist, bare-id tabs too, 100 a page, filterable by type
 * (`?filter=chords|tabs|…&page=N`): caracole reads the chords and tabs lists alone. The data is where a tab page
 * keeps it (UgPage.readPageData): `data.artist`, `data.other_tabs`, `data.pagination` and `data.filters.types`,
 * their links relative (`/artist/soda_stereo_2946?filter=chords`) or absolute.
 *
 * Python's ValueError (urllib's, of a filter link it can't split, or [pageUrl]'s refusals) is an
 * [IllegalArgumentException] with its words.
 */
object UgArtist {
    const val WWW = "https://www.ultimate-guitar.com"

    /** KIND_FILTERS: caracole's kind → the artist page's `filter` value. */
    val KIND_FILTERS: Map<String, String> = linkedMapOf("chords" to "chords", "tabs" to "tabs")
    private val FILTER_KINDS = KIND_FILTERS.entries.associate { (kind, value) -> value to kind }

    private fun mapping(value: JsonElement?): JsonObject = value as? JsonObject ?: JsonObject(emptyMap())

    /** The objects of a JSON list, such as `pagination.pages` or `filters.types`. */
    private fun entries(value: JsonElement?): List<JsonObject> = (value as? JsonArray)?.filterIsInstance<JsonObject>().orEmpty()

    private fun links(entries: List<JsonObject>): List<String> =
        entries.mapNotNull { e -> (e["url"] as? JsonPrimitive)?.takeIf { it.isString && it.content.isNotEmpty() }?.content }

    private fun split(url: String): PyUrl.Split = try {
        PyUrl.urlsplit(url)
    } catch (e: PyUrl.Invalid) {
        throw IllegalArgumentException(e.message, e)
    }

    /** The kinds the filter links' `filter` parameter names, relative links or absolute (parse_qs's first value). */
    private fun filters(entries: List<JsonObject>): Set<String> {
        val found = LinkedHashSet<String>()
        for (link in links(entries)) {
            val value = PyUrl.parseQs(split(link).query)["filter"]?.first() ?: ""
            FILTER_KINDS[value]?.let { found += it }
        }
        return found
    }

    /** `json_int(a) or json_int(b) or …`: the first that is neither none nor 0. */
    private fun firstOf(vararg values: JsonElement?): Int? =
        values.firstNotNullOfOrNull { v -> UgPage.asInt(PyValues.jsonInt(v))?.takeIf { it != 0 } }

    /** ug/artist.py's `parse_artist_page`. [url] is the page's address, for the errors' words. */
    fun parse(html: ByteArray, url: String? = null): UgArtistPage {
        val data = UgPage.readPageData(html, url)
        val artist = mapping(data["artist"])
        val artistId = UgPage.asLong(PyValues.jsonInt(artist["id"]))
            ?: throw PageParseError("ug", url, null, "no usable data.artist")
        val tabs = UgPage.readVersions(data, "other_tabs", url)
        val pagination = mapping(data["pagination"])
        val pageEntries = entries(pagination["pages"])
        val filterEntries = entries(mapping(data["filters"])["types"])
        val page = firstOf(pagination["current"], data["current_page"]) ?: 1
        val listed = pageEntries.mapNotNull { e -> firstOf(e["page"]) }
        val name = artist["name"].takeIf { PyValues.truthy(it) }?.let { PyValues.text(it) } ?: ""
        return UgArtistPage(artistId = artistId, name = name, tabs = tabs, page = page,
                            pages = (listed + page).max(), filters = filters(filterEntries))
    }

    /**
     * ug/artist.py's `artist_page_url`: one page of an artist's tab list, filtered to one [kind] or not:
     * `pageUrl(".../artist/soda_stereo_2946", "chords", 2)` is `.../artist/soda_stereo_2946?filter=chords&page=2`;
     * page 1 has no page parameter; a query on [base], a fragment and trailing slashes are dropped.
     */
    fun pageUrl(base: String, kind: String? = null, page: Int = 1): String {
        require(kind == null || kind in KIND_FILTERS) { "no artist-page filter for kind ${PyStr.repr(kind!!)}" }
        require(page >= 1) { "page must be 1 or more, not $page" }
        val query = ArrayList<Pair<String, String>>()
        if (!kind.isNullOrEmpty()) query += "filter" to KIND_FILTERS.getValue(kind)
        if (page > 1) query += "page" to page.toString()
        val parts = split(base)
        return PyUrl.urlunsplit(PyUrl.Split(parts.scheme, parts.netloc, parts.path.trimEnd('/'), PyUrl.urlencode(query), ""))
    }
}
