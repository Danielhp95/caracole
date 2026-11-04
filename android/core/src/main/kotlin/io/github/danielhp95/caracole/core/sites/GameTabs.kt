package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sites.internal.gametabs.GamePages
import io.github.danielhp95.caracole.core.sites.internal.gametabs.Lookups
import io.github.danielhp95.caracole.core.sites.internal.gametabs.TabPages
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Duration
import java.time.Instant

/** gametabs_fetch.GameTabsStats: [sitemaps] the sitemap reads stored (none on the phone, whose lookups read no
 * sitemap), the tabs [kept], the songs [missing] one; the songs tried, the errors and the failures [PassStats]'. */
class GameTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats()

/**
 * gametabs.GameTab: a tab page read: the site's id of it (null where its page doesn't say), the track's title, the
 * game's name and slug, the tab's own slug, the tab ([body], the `<pre>`'s text), and what the page says of it. Its
 * numbers are Python's ints, unbounded ([views], [ratings], [tabId]).
 */
data class GameTab(
    val tabId: BigInteger?, val title: String, val game: String, val gameSlug: String, val slug: String,
    val body: String, val composers: List<String> = emptyList(), val instruments: List<String> = emptyList(),
    val styles: List<String> = emptyList(), val tuning: String? = null, val tabber: String? = null,
    val views: BigInteger = BigInteger.ZERO, val rating: Double? = null, val ratings: BigInteger = BigInteger.ZERO,
    val created: String? = null,
) {
    /** GameTab.raw: what a kept tab's version records of it, its twelve members in Python's order. */
    fun raw(): JsonObject = JsonObject(linkedMapOf(
        "id" to (tabId?.let { JsonPrimitive(it) } ?: JsonNull), "title" to JsonPrimitive(title),
        "game" to JsonPrimitive(game), "composers" to names(composers), "instruments" to names(instruments),
        "styles" to names(styles), "tuning" to text(tuning), "tabber" to text(tabber), "views" to JsonPrimitive(views),
        "rating" to (rating?.let { PyJson.float(it) } ?: JsonNull), "ratings" to JsonPrimitive(ratings),
        "created" to text(created),
    ))

    private fun names(list: List<String>) = JsonArray(list.map { JsonPrimitive(it) })
    private fun text(s: String?) = s?.let { JsonPrimitive(it) } ?: JsonNull
}

/** gametabs.ListedTab: a tab a game page lists: its page's path, the track's title as its card writes it (less the
 * game's name), and what the card says of it (empty, null or 0 where it says nothing). */
data class GameListedTab(
    val path: String, val title: String, val composers: List<String> = emptyList(),
    val instruments: List<String> = emptyList(), val styles: List<String> = emptyList(), val platform: String? = null,
    val tabber: String? = null, val views: BigInteger = BigInteger.ZERO, val rating: Double? = null,
)

/** gametabs.GamePage: a game page: the game's name as the page heads it, the tabs it says the game has, those it lists
 * ([GameTabsPages.PAGE_TABS] at most) and how many pages its selector offers (1 with none). */
data class GamePage(val name: String, val tabs: BigInteger, val listed: List<GameListedTab> = emptyList(),
                    val pages: BigInteger = BigInteger.ONE)

/**
 * gametabs.py's pages on the phone: a tab page and a game page read as gametabs.py reads them, through core.html (a
 * page without the expected markup a GameTabsParseError: a provider error, never a miss), and its addresses and
 * keys. A lookup reads tab pages alone; [parseGamePage] is the game pages' reading, which the computer's index keeps
 * (gametabs_index.py), ported whole. vectors/sites/gametabs.jsonl holds Python's answers
 * (tests/test_conformance_gametabs.py).
 */
object GameTabsPages {
    const val PROVIDER = "gametabs"
    const val BASE_URL = "https://gametabs.net"

    /** The tabs a game page lists; the rest on its next pages. */
    const val PAGE_TABS = 50

    /** The site's instruments, as its shuffle dialog named them on 28 October 2026: what a card's instruments are told
     * from its styles by, for a page that doesn't name them. */
    val INSTRUMENTS: List<String> = listOf("Guitar", "Bass", "Mandolin", "Banjo", "Ukulele")

    /** The address of a page, from its path as the index keeps it (`tabs/actraiser/fillmore`). */
    fun pageUrl(path: String): String = "$BASE_URL/$path"

    /** The key a song's title meets the tabs' titles with: its version suffixes go first (clean_title). */
    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))

    /** parse_tab_page: a tab page's tab and what its `data-tab` says of it (its microdata and heading where it says
     * nothing); GameTabsParseError for a page without a tab, a title or a game. [html] is the answer's bytes, read
     * as UTF-8 with replacement. */
    fun parseTabPage(html: ByteArray, url: String? = null): GameTab = TabPages.parse(html, url)

    /** parse_game_page: a game page's name, the tabs it says the game has and those it lists; GameTabsParseError for
     * a page without its heading, one that says the game has tabs and lists none caracole can read, or a page number
     * int() refuses. */
    fun parseGamePage(html: ByteArray, url: String? = null): GamePage = GamePages.parse(html, url)
}

/**
 * gametabs_fetch.py for a lookup's song: its candidates by title (a game one of its artists names, or a composer one
 * of them is, by the game pages the index read), at most [CANDIDATES], the most viewed first; the most viewed page
 * that agrees kept as the song's next `gametab-N.txt` under a version of provider `gametabs` and kind `gametab`; a
 * tab you picked (`[gametabs]`) read alone and kept whatever its page names. A miss, asked about again after
 * [RECHECK_AFTER], is kv `gametabs:checked:<id>` (and `:pick`, the pick asked for); an error is never one. The
 * sitemaps and the game pages are the computer's to read: a lookup reads neither (refresh_index=False), and
 * info.json is the viewer's, the phone's pages' (M5). vectors/lookup/gametabs.jsonl replays its scenarios.
 */
object GameTabsFetch {
    const val CANDIDATES = 4
    val RECHECK_AFTER: Duration = Duration.ofDays(30)
    const val CHECKED_PREFIX = "gametabs:checked:"
    const val PICKED = ":pick"
    const val KIND = "gametab"

    /** gametabs_index.KEYS_KEY: the KEY_VERSION the game pages' title keys were made with. */
    const val KEYS_KEY = "gametabs:games:keys"

    /** gametabs_tabs(conn, client, library_dir, now, overrides=, only=, refresh_index=False): see the object's
     * docstring. ProviderBlocked propagates; a spent budget ends the pass (`budgetExhausted`); any other provider
     * error leaves the song in `failures`. */
    fun gametabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): GameTabsStats = Lookups.gametabsTabs(db, client, lib, now, overrides, only)

    /** game_forms: the keys a game's name is compared by (name_forms), and those of the name less what says it is
     * its music ("Hollow Knight OST", "Celeste (Original Soundtrack)"). */
    fun gameForms(name: String): List<String> = Lookups.gameForms(name)

    /** song_forms: the keys the song's artists are compared by, hyphens aside. */
    fun songForms(song: SongRow): Set<String> = Lookups.songForms(song)

    /** fits: whether a tab page is the song's: its track's title is the song's, and its game or one of its composers
     * is one of the song's artists. */
    fun fits(song: SongRow, tab: GameTab): Boolean = Lookups.fits(song, tab)

    /** gametabs_index.ensure_current_keys: every game page's tab's title key made again from its title after a
     * change to caracole's keys, once; how many rows changed. */
    fun ensureCurrentKeys(db: Db): Int = Lookups.ensureCurrentKeys(db)
}
