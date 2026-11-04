package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyHtml
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.ug.internal.pages.PyValues
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * ug/page.py's UGVersion: one version a tab page, a versions list or an artist page lists. [access] is UG's
 * `tab_access_type` (only `public` is usable), [url] its `tab_url`, [description] its `version_description`; a null
 * rating or vote count is 0. [raw] is UG's object, unchanged, left out of equality as Python's `compare=False` leaves
 * it.
 */
data class UgVersion(val tabId: Long, val songId: Long?, val songName: String, val artistName: String,
                     val type: String, val part: String, val version: Int, val rating: Double, val votes: Int,
                     val access: String, val url: String, val description: String?, val isAcoustic: Boolean,
                     val raw: JsonObject) {
    /** chords, tabs or ukulele; null for every type caracole doesn't use. */
    val kind: String? get() = UgPage.kindOf(type)

    /** The part ("intro", "solo"…), else "acoustic" for an acoustic recording, else null. */
    val label: String?
        get() {
            val part = PyUnicode.lower(Py.strip(part))
            if (part.isNotEmpty()) return part
            return if (isAcoustic) "acoustic" else null
        }

    private fun fields() = listOf(tabId, songId, songName, artistName, type, part, version, rating, votes, access, url,
                                  description, isAcoustic)

    override fun equals(other: Any?): Boolean = other is UgVersion && fields() == other.fields()
    override fun hashCode(): Int = fields().hashCode()
    override fun toString(): String = "UgVersion(tabId=$tabId, type=$type, songName=$songName, version=$version)"
}

/** ug/page.py's UGTabPage: a tab page read. [content] is `wiki_tab.content` in UG markup, or null on the page of a
 * type caracole doesn't use; [meta] `tab_view.meta` ({} when empty); [raw] `store.page.data`, out of equality;
 * [artistUrl] the artist page UG links the tab to. */
data class UgTabPage(val tab: UgVersion, val versions: List<UgVersion>, val content: String?, val meta: JsonObject,
                     val raw: JsonObject, val artistUrl: String? = null) {
    override fun equals(other: Any?): Boolean = other is UgTabPage && tab == other.tab && versions == other.versions &&
        content == other.content && meta == other.meta && artistUrl == other.artistUrl

    override fun hashCode(): Int = listOf(tab, versions, content, meta, artistUrl).hashCode()
    override fun toString(): String = "UgTabPage(tab=$tab, versions=${versions.size}, artistUrl=$artistUrl)"
}

/**
 * ug/page.py: UG's tab pages, read from the JSON UG embeds in them (`div.js-store[data-content]`, under
 * `store.page.data`): `data.tab` the page's own tab, `data.tab_view.versions` the song's other versions of its type
 * (UG's Official among them), `wiki_tab.content` the sheet in UG markup (none on a Guitar Pro or Power Tab file's
 * page), `tab_view.meta` what UG says of the tab (`[]` for none).
 *
 * The attribute is read as selectolax reads it (core.html), then by PyJson.loads, as json.loads reads it; half of a
 * surrogate pair the JSON escapes alone is U+FFFD in every string of the data, keys too. A page that can't be read
 * is a [PageParseError], a provider's error and never a miss.
 *
 * A number past what the phone keeps, which UG never writes, is read as no number where Python keeps the value: an
 * id past a Long makes the tab unusable, a version or a vote count past an Int is 0 (Python keeps it, and its sqlite3
 * stores one up to 2^63), and an artist page's number past an Int falls through to the next one UgArtist reads.
 * Python's json reads 50,000 containers deep, the phone PyJson.MAX_DEPTH (512): a page nested between is a
 * PageParseError on the phone alone.
 */
object UgPage {
    const val TAB_BASE_URL = "https://tabs.ultimate-guitar.com/tab/"

    /** _KINDS: caracole's kind by UG's type, lowered: its chords, its text tabs and its Ukulele Chords. */
    private val KINDS_BY_TYPE = mapOf("chords" to "chords", "tabs" to "tabs", "ukulele chords" to "ukulele")

    /** KINDS: caracole's kinds of UG's tabs. */
    val KINDS: List<String> = KINDS_BY_TYPE.values.toList()

    private val MARKUP = Regex("\\[/?(?:ch|tab)\\]")
    private val ENTITY = PyRegex.compile("(?i)&(#\\d+|#x[0-9a-f]+|[a-z]+);")

    /** caracole's kind for a UG tab type: Chords → chords, Tabs → tabs, Ukulele Chords → ukulele, by the type
     * stripped and lowered as Python's str does; null for every other type (Official, Pro, Power…). */
    fun kindOf(type: String?): String? = type?.let { KINDS_BY_TYPE[PyUnicode.lower(Py.strip(it))] }

    /** A tab page's URL: its sitemap [path] (`artist/song-type-id`, slashes before it dropped) when given, the only
     * URL UG serves a slugged tab at; else the bare `/tab/{id}`. */
    fun pageUrl(tabId: Long, path: String? = null): String =
        if (!path.isNullOrEmpty()) TAB_BASE_URL + path.trimStart('/') else "$TAB_BASE_URL$tabId"

    /** The sheet as plain text: UG's `[ch]`, `[/ch]`, `[tab]` and `[/tab]` tags removed. */
    fun stripMarkup(s: String): String = MARKUP.replace(s, "")

    /** HTML entities decoded, and once more when the result still holds one (`&amp;amp;`), as html.unescape. */
    fun decodeTwice(s: String): String {
        val text = PyHtml.unescape(s)
        return if (PyRe.search(ENTITY, text) != null) PyHtml.unescape(text) else text
    }

    /** ug/page.py's `json_int`: a whole number from UG's JSON (a number, a digit string, a bool), else null. */
    fun jsonInt(value: JsonElement?): BigInteger? = PyValues.jsonInt(value)

    private val LONG_MIN = BigInteger.valueOf(Long.MIN_VALUE)
    private val LONG_MAX = BigInteger.valueOf(Long.MAX_VALUE)

    internal fun asLong(n: BigInteger?): Long? = n?.takeIf { it >= LONG_MIN && it <= LONG_MAX }?.toLong()
    internal fun asInt(n: BigInteger?): Int? =
        n?.takeIf { it >= BigInteger.valueOf(Int.MIN_VALUE.toLong()) && it <= BigInteger.valueOf(Int.MAX_VALUE.toLong()) }
            ?.toInt()

    /**
     * ug/page.py's `parse_version`: a [UgVersion] of one of UG's tab objects, or null when it isn't a usable tab: a
     * usable one has a `type` (true as Python's truth goes) and a whole-number `id`. Artist pages mix in links to
     * UG's paid app as entries without a type.
     */
    fun parseVersion(d: JsonElement?): UgVersion? {
        if (d !is JsonObject || !PyValues.truthy(d["type"])) return null
        val tabId = asLong(PyValues.jsonInt(d["id"])) ?: return null
        val acoustic = (d["recording"] as? JsonObject)?.get("is_acoustic")
        val rating = PyValues.number(d["rating"])
        return UgVersion(
            tabId = tabId,
            songId = asLong(PyValues.jsonInt(d["song_id"])),
            songName = PyValues.text(d["song_name"]),
            artistName = PyValues.text(d["artist_name"]),
            type = PyValues.text(d["type"]),
            part = PyValues.text(d["part"]),
            version = asInt(PyValues.jsonInt(d["version"])) ?: 0,
            rating = if (rating == null || rating == 0.0) 0.0 else rating,
            votes = asInt(PyValues.jsonInt(d["votes"])) ?: 0,
            access = PyValues.text(d["tab_access_type"]),
            url = PyValues.text(d["tab_url"]).ifEmpty { pageUrl(tabId) },
            description = PyValues.text(d["version_description"]).ifEmpty { null },
            isAcoustic = PyValues.number(acoustic).let { it != null && it != 0.0 },
            raw = d,
        )
    }

    /** ug/page.py's `read_page_data`: the `store.page.data` object of any UG page, or [PageParseError]. [html] is
     * decoded as UTF-8 with replacement, as Python's parsers decode it. */
    fun readPageData(html: ByteArray, url: String? = null): JsonObject {
        val node = Html.parse(html).cssFirst("div.js-store")
        val payload = node?.attributes?.get("data-content")
        if (payload.isNullOrEmpty()) throw PageParseError("ug", url, null, "no div.js-store data on the page")
        var store = try {
            PyJson.loads(payload)
        } catch (e: IllegalArgumentException) {  // PyJson's DecodeError and RecursionError, Python's ValueError
            throw PageParseError("ug", url, null, "js-store is not valid JSON: ${e.message}").apply { initCause(e) }
        }
        if (PyValues.escapesASurrogate(payload)) store = PyValues.whole(store)
        var data: JsonElement? = store
        for (key in listOf("store", "page", "data")) data = (data as? JsonObject)?.get(key)
        return data as? JsonObject ?: throw PageParseError("ug", url, null, "js-store has no store.page.data")
    }

    /** ug/page.py's `read_versions`: the usable tabs of the list `data[key]`; a missing key, or a value that isn't
     * a list, a [PageParseError]; null no tabs. */
    fun readVersions(data: JsonObject, key: String, url: String? = null): List<UgVersion> {
        if (key !in data) throw PageParseError("ug", url, null, "no $key on the page")
        val items = data[key]
        if (items == null || items == JsonNull) return emptyList()
        if (items !is JsonArray) throw PageParseError("ug", url, null, "$key is not a list")
        return items.mapNotNull { parseVersion(it) }
    }

    /** ug/page.py's `parse_tab_page`. [url] is only for the errors' words. */
    fun parseTabPage(html: ByteArray, url: String? = null): UgTabPage {
        val data = readPageData(html, url)
        val tab = parseVersion(data["tab"]) ?: throw PageParseError("ug", url, null, "no usable data.tab")
        val view = data["tab_view"] as? JsonObject ?: throw PageParseError("ug", url, null, "no data.tab_view")
        val versions = readVersions(view, "versions", url)
        val given = (view["wiki_tab"] as? JsonObject)?.get("content")
        val content = if (given is JsonPrimitive && given.isString) {
            // UG keeps the sheet's text HTML-escaped inside its JSON, on top of the attribute's own escaping.
            decodeTwice(given.content)
        } else {
            if (tab.kind != null) throw PageParseError("ug", url, null, "${tab.type} page without wiki_tab.content")
            null
        }
        return UgTabPage(
            tab = tab,
            versions = versions,
            content = content,
            meta = view["meta"] as? JsonObject ?: JsonObject(emptyMap()),
            raw = data,
            artistUrl = PyValues.text(tab.raw["artist_url"]).ifEmpty { null },
        )
    }
}
