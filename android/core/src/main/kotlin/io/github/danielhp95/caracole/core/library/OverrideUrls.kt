package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.library.internal.overrides.Addresses
import kotlinx.serialization.json.JsonPrimitive

/**
 * overrides.py's, youtube_urls.py's and ug/sitemap.py's readings of an address a user pasted, as `get.find_song` and
 * overrides.py read them: written as an address bar shows it (without `https://` or `www.`, with capitals in the
 * host, with a query, a fragment or a trailing slash), on the site's own hosts alone. Each refusal is [OverridesError]
 * with Python's words; a digit str.isdigit takes that int() can't read ("²") is Python's ValueError,
 * [IllegalArgumentException]. Held to Python by vectors/library/override_urls.jsonl.
 */
object OverrideUrls {
    /** overrides.ARTIST_PAGE_SHAPE and TAB_PAGE_SHAPE: how messages write an artist page's address and a tab page's. */
    const val ARTIST_PAGE_SHAPE = Addresses.ARTIST_PAGE_SHAPE
    const val TAB_PAGE_SHAPE = Addresses.TAB_PAGE_SHAPE

    /** ug/sitemap.BARE and UNRECOGNIZED: why a tab page's address has no index row, besides a type it doesn't keep. */
    const val BARE = Addresses.BARE
    const val UNRECOGNIZED = Addresses.UNRECOGNIZED

    /** overrides.override_key: the song identity of an "Artist - Title" key. */
    fun overrideKey(display: String): String = Addresses.overrideKey(display)

    /** overrides.tab_id_from_url: the tab id of a UG tab page's address (`/tab/85053`, `/tab/a/b-chords-85053`), or
     * of a bare id. An id past a Long is refused as no tab page (Python's int has no end). */
    fun tabIdFromUrl(s: String): Long = Addresses.tabIdFromUrl(s)

    /** overrides.pin_url: a pinned page's address, on the tabs host, over https and without its query, fragment and
     * trailing slash; for a bare tab id, the bare `/tab/{id}` page. [s] passed [tabIdFromUrl]. */
    fun pinUrl(s: String): String = Addresses.pinUrl(s)

    /** overrides.artist_page_address: a UG artist page's address (`/artist/<name>_<id>`, `/artist/<id>`) on the www
     * host, or null. */
    fun artistPageAddress(url: String): String? = Addresses.artistPageAddress(url)

    /** overrides._artist_url_value: an `[artist_url]` value, the artist's page or one of their tab pages written as
     * a pin's is; null for anything else, a bare number included. */
    fun artistUrlValue(url: String): String? = Addresses.artistUrlValue(JsonPrimitive(url))

    /** overrides.pasted_tab_id: the tab id when an `[artist_url]` value is a tab page; null for the artist's page. */
    fun pastedTabId(url: String): Long? = Addresses.pastedTabId(url)

    /** ug/sitemap.classify_tab_url's reason a tab page's address has no index row ([BARE], [UNRECOGNIZED] or the type
     * the index doesn't keep, "bass"), or null for an address that has one ([parseTabUrl]). */
    fun classifyTabUrl(url: String): String? = Addresses.classifyTabUrl(url) as? String

    /** ug/sitemap.parse_tab_url: the index row of a tab page's address, or null ([classifyTabUrl] says why). */
    fun parseTabUrl(url: String): TabUrlRow? = Addresses.classifyTabUrl(url) as? TabUrlRow

    /** overrides.lacuerda_pick_from_url: the LaCuerda song or version a page's address names. */
    fun lacuerdaPickFromUrl(s: String): LaCuerdaPick = Addresses.lacuerdaPickFromUrl(JsonPrimitive(s))
    fun harptabsPickFromUrl(s: String): HarpTabsPick = Addresses.harptabsPickFromUrl(JsonPrimitive(s))
    fun gametabsPickFromUrl(s: String): GameTabsPick = Addresses.gametabsPickFromUrl(JsonPrimitive(s))

    /** overrides.azlyrics_page_from_url: the lyrics page an address names, as caracole asks for it. */
    fun azlyricsPageFromUrl(s: String): String = Addresses.azlyricsPageFromUrl(JsonPrimitive(s))

    /** youtube_urls.video_id_from_url: the id of a YouTube video's address (`watch?v=`, `youtu.be/`, `/shorts/`,
     * `/embed/`, `/live/`, on www, m or music), or null. */
    fun videoIdFromUrl(s: String): String? = Addresses.videoIdFromUrl(JsonPrimitive(s))

    /** youtube_urls.watch_url: the video's plain address. */
    fun watchUrl(videoId: String): String = Addresses.watchUrl(videoId)
}
