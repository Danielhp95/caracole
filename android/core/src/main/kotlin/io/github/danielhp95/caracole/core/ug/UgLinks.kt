package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.http.UnreadablePage
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.PyBits
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.ug.internal.fetch.ArtistPages
import io.github.danielhp95.caracole.core.ug.internal.fetch.ListReading
import io.github.danielhp95.caracole.core.ug.internal.fetch.Pages
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.time.Duration
import java.time.Instant

/** ug/fetch.TabRead: a tab page read by the fetch's rules (Pages.readTabPage): what came of it ([said]: [READ],
 * [GONE], [CLOSED], [REDIRECTED], [WAITS] or [UNREADABLE]), the page ([READ]'s), whether UG was asked for it now
 * ([fresh]), and the error of one that won't parse. */
data class TabRead(val said: String, val page: UgTabPage? = null, val fresh: Boolean = false,
                   val error: UnreadablePage? = null) {
    companion object {
        const val READ = "read"
        const val GONE = "gone"  // UG answered 404
        const val CLOSED = "closed"  // robots.txt closes it: never asked for
        const val REDIRECTED = "redirected"  // UG sent it where robots.txt closes
        const val WAITS = "waits"  // it proved unreadable and isn't due again: not asked for
        const val UNREADABLE = "unreadable"  // it won't parse even fetched again, noted
    }
}

/** ug/link.Tab: what UG names a tab: its artist and title as UG writes them, caracole's kind ([type]), its version
 * (null where only an artist page named it) and its rating and votes (null for a tab nobody voted on). */
data class LinkTab(val artist: String, val title: String, val type: String, val version: Int?, val rating: Double?,
                   val votes: Int?)

/** ug/link.Known: what caracole knows of a link's page ([UgLinks.known]): its [state] and, but `found` and `auto`,
 * why ([why]); a tab's names ([tab]), the song its tabs are filed under ([keys]: an artist key and a song key), the
 * artist's page ([page]: a tab's, or the link's own), when caracole read it ([readAt]), UG's name of the artist
 * ([artist]), the key an artist page's tabs are filed under ([artistKey]) and the tabs caracole holds of it. */
data class LinkKnown(val link: UgLink, val state: String, val why: String = "", val tab: LinkTab? = null,
                     val keys: Pair<String, String>? = null, val page: String? = null, val readAt: String? = null,
                     val artist: String = "", val artistKey: String? = null, val tabs: Int = 0)

/** ug/link.LinkRead: what reading a link's page came to ([UgLinks.readPage], [UgLinks.readLists]): a tab's page
 * ([tab]), the artist page learned or given ([page]), its lists ([listing]) and the tabs caracole holds of it
 * ([tabs]), what stopped its read with the tab known ([stopped]: a spent budget, a block, an error) and when caracole
 * asks again for a tab page that won't parse ([until]). */
class LinkRead(val link: UgLink, val url: String) {
    var tab: TabRead? = null
    var page: String? = null
    internal var listing: ArtistPages.Listing? = null
    var tabs: Int = 0
    var stopped: Exception? = null
    var until: String? = null

    /** Whether UG answered 404 for the artist page read. */
    val pageGone: Boolean get() = listing?.gone == true
}

/**
 * ug/link.py on the phone: a UG link pasted into the library page's search box: what caracole knows of its page
 * ([known], with no request and no lock: the database and the HTTP cache alone), and its page read now (`read`,
 * `caracole ug --link`'s, an interactive lookup's: [readPage] and [readLists]), and what that came to in the words
 * the command ends with ([said], [knownLine]).
 *
 * - [known]'s `state`: `found` (a tab's song is known: its `ug_index` row, its `ug_artist_tabs` row, or its page in
 *   the cache; an artist's page read), `auto` (not yet, and a read may go now), `cooling` (UG's cooldown), `spent`
 *   (the hour's lookups), `failed` (this link's read failed within the hour, kv [FAILED_KEY], or its tab page won't
 *   parse, kv `ug:unreadable:<tab id>`), `other` (a tab of a type caracole keeps nothing of, said with no request
 *   where its slug names its type, else once read; or a page robots.txt closes) and `gone` (its cached 404).
 * - read ([readPage], then [readLists]): a tab link's page by ug/fetch.py's rules for a page (Pages.readTabPage), its
 *   artist's page learned as the fetch learns it (kv `ug:artist_url:<key>`) and read as the fetch reads one
 *   (ArtistPages.readArtistPage, of no song's: the chords list, then the tabs list, every page kept for searches); an
 *   artist link's lists alone. A budget spent, a block or an error after a tab's page is no failure of the link: the
 *   tab is known, its artist's page waits.
 */
object UgLinks {
    const val PROVIDER = "ug"
    val STATES: List<String> = listOf("found", "auto", "cooling", "spent", "failed", "other", "gone")
    const val FAILED_KEY = "ug:link-failed"  // {page's address: {"at", "error"}}: the links whose read failed lately
    val FAILED_FOR: Duration = Duration.ofHours(1)
    const val ERROR_CHARS = 200
    val KEPT: Set<String> = setOf("chords", "tabs", "ukulele")  // the slug tokens of the kinds caracole keeps

    /** A type caracole keeps nothing of, in words: by the token its slug names, and by the type its page names. */
    private val TOKEN_WORDS = mapOf("guitar-pro" to "a Guitar Pro file", "power" to "a Power Tab file",
                                    "official" to "an Official tab", "bass" to "a bass tab", "drums" to "a drum tab",
                                    "video" to "a video lesson", "musescore" to "a MuseScore score")
    private val TYPE_WORDS = mapOf("pro" to "a Guitar Pro file", "power" to "a Power Tab file",
                                   "official" to "an Official tab", "bass tabs" to "a bass tab",
                                   "drum tabs" to "a drum tab", "video" to "a video lesson")
    const val KEEPS = "caracole keeps UG's chords, tabs and ukulele chords alone"
    private val KIND_WORDS = mapOf("chords" to "chords", "tabs" to "tab", "ukulele" to "ukulele chords")
    const val GONE = "UG answers 404 for it"
    const val CLOSED = "robots.txt closes it to caracole"

    private val SLUGGED by lazy { PyRegex.compile("/tab/[^/]+/([^/]+)-\\d+") }
    private const val HOUR_US = 3_600_000_000L

    // --- what caracole knows, with no request ----------------------------------------------------------------

    /** page_url: the address a link's page is read at: an artist's, as given; a tab's, as given when slugged (UG
     * serves a slugged tab only there), else the index's slugged path for its id, else the bare `/tab/{id}`. */
    fun pageUrl(db: Db, link: UgLink): String {
        if (link.kind != UgLink.TAB || link.tabId == null || PyRe.fullmatch(SLUGGED, PyUrl.urlsplit(link.url).path) != null) {
            return link.url
        }
        return UgLookup.tabUrlFor(db, link.tabId)
    }

    /** known: what caracole knows of the link's page at [now], with no request and no lock; [cacheDir] the HTTP
     * cache's folder (`cfg.cache_dir`). */
    fun known(cfg: PhoneConfig, db: Db, cacheDir: File, link: UgLink, now: Instant): LinkKnown {
        val cache = CachedAnswers(PROVIDER, cacheDir)
        val said = if (link.kind == UgLink.TAB) tabKnown(db, cache, link, now) else artistKnown(db, cache, link)
        if (said.state != "auto") return said
        val (state, why) = gate(cfg, db, link, now)
        return said.copy(state = state, why = why)
    }

    /** tab_keys: the keys a tab's song is filed under: as an artist page caracole read lists it (`ug_artist_tabs`),
     * else as the index does (its song's key without a variant label); null for a tab neither names. */
    fun tabKeys(db: Db, tabId: Long): Pair<String, String>? {
        ListedTabs.listedTab(db, tabId)?.let { return it.artistKey to it.songKey }
        return db.one("SELECT artist_key, song_key FROM ug_index WHERE tab_id = ?", tabId) {
            it.text(0)!! to Normalize.splitVariant(it.text(1)!!).first
        }
    }

    /** _read_lately: whether caracole read the artist page's lists within [UgFetch.ARTIST_PAGE_MAX_AGE] (30 days):
     * its tabs in `ug_artist_tabs` read since. */
    private fun readLately(db: Db, page: String, now: Instant): Boolean {
        val held = ListedTabs.pageArtist(db, page) ?: return false
        return !before(held.readAt, Stamps.micros(now.minus(UgFetch.ARTIST_PAGE_MAX_AGE)))
    }

    /** _tab_known: a tab link's page as caracole knows it. Its song is known (`found`) by an artist page caracole read
     * that lists it, by the index, or by its page in the cache, but a cached page that names an artist page caracole
     * hasn't read within 30 days is `auto`: the read takes the page from the cache and reads that artist's lists, so
     * that every song of theirs is found by a search. */
    private fun tabKnown(db: Db, cache: CachedAnswers, link: UgLink, now: Instant): LinkKnown {
        if (link.type != null && link.type !in KEPT) {
            return LinkKnown(link, "other", "it is ${TOKEN_WORDS[link.type] ?: "a ${link.type} tab"}: $KEEPS")
        }
        val url = pageUrl(db, link)
        if (Pages.closed(url)) return LinkKnown(link, "other", CLOSED)
        val answer = cache.cached(url, accept = setOf(200, 404))
        if (answer != null && answer.status == 404) return LinkKnown(link, "gone", GONE)
        var page: UgTabPage? = null
        if (answer != null) {
            page = try {
                UgPage.parseTabPage(answer.content, url)
            } catch (e: PageParseError) {  // a copy cut short: read again, past the cache
                null
            }
        }
        if (page != null && page.tab.kind == null) {
            return LinkKnown(link, "other", "it is ${typeWords(page.tab.type)}: $KEEPS")
        }
        val tabId = link.tabId!!
        val listed = ListedTabs.listedTab(db, tabId)
        val keys = tabKeys(db, tabId)
        val tab = when {
            page != null -> tabOf(page)
            listed != null -> LinkTab(listed.artist, listed.title, listed.type, null, rating(listed.rating, listed.votes),
                                      listed.votes.takeIf { it != 0 })
            else -> null
        }
        val artist = tab?.artist ?: ""
        var base = (if (page != null) Pages.artistPageBase(page.artistUrl) else null) ?: listed?.page
        if (base == null && artist.isNotEmpty()) {
            base = Normalize.nameForms(artist).firstNotNullOfOrNull { key ->
                UgLookup.learnedArtistUrl(db, key)?.takeIf { it.isNotEmpty() }
            }
        }
        val readAt = base?.let { readAt(db, cache, it) }
        val linked = if (page != null) Pages.artistPageBase(page.artistUrl) else null
        val unread = linked != null && !readLately(db, linked, now)  // its artist's lists to read yet
        val state = if ((keys != null || page != null) && !unread) "found" else "auto"
        return LinkKnown(link, state, tab = tab, keys = keys, page = base, readAt = readAt, artist = artist)
    }

    private fun artistKnown(db: Db, cache: CachedAnswers, link: UgLink): LinkKnown {
        val held = ListedTabs.pageArtist(db, link.url)
        val readAt = readAt(db, cache, link.url)
        if (held != null) {
            return LinkKnown(link, "found", page = link.url, readAt = readAt, artist = held.artist,
                             artistKey = held.artistKey, tabs = held.tabs)
        }
        if (readAt != null) {  // read, and none of its tabs is of a kind caracole keeps
            return LinkKnown(link, "found", page = link.url, readAt = readAt, artist = cachedName(cache, link.url))
        }
        if (cache.cached(UgArtist.pageUrl(link.url), accept = setOf(404)) != null) {
            return LinkKnown(link, "gone", GONE, page = link.url)
        }
        return LinkKnown(link, "auto", page = link.url)
    }

    /** _cached_name: UG's name of the artist, from the first list of the page the cache holds; "" for none. */
    private fun cachedName(cache: CachedAnswers, page: String): String {
        for (kind in listOf("chords", "tabs", null)) {
            val url = UgArtist.pageUrl(page, kind = kind)
            val answer = cache.cached(url, accept = setOf(200)) ?: continue
            try {
                return UgArtist.parse(answer.content, url).name
            } catch (e: PageParseError) {
                continue
            }
        }
        return ""
    }

    /** _read_at: when caracole read the artist page: its tabs' latest read, else the cache's copy of one of its lists;
     * null for a page it never read. */
    private fun readAt(db: Db, cache: CachedAnswers, page: String): String? {
        ListedTabs.pageArtist(db, page)?.let { return it.readAt }
        for (kind in listOf("chords", "tabs", null)) {
            val answer = cache.cached(UgArtist.pageUrl(page, kind = kind), accept = setOf(200)) ?: continue
            return answer.fetchedAt ?: ""
        }
        return null
    }

    /** `round(float(rating), 2) if votes else None`. */
    private fun rating(rating: Double, votes: Int): Double? = if (votes != 0) Py.round(rating, 2) else null

    private fun tabOf(page: UgTabPage): LinkTab {
        val v = page.tab
        return LinkTab(v.artistName, v.songName, v.kind!!, v.version, rating(v.rating, v.votes), v.votes.takeIf { it != 0 })
    }

    /** _type_words: a page's type caracole keeps nothing of, in words. */
    private fun typeWords(ugType: String): String {
        val stripped = PyText.strip(ugType)
        return TYPE_WORDS[PyUnicode.lower(stripped)] ?: "a ${stripped.ifEmpty { "nameless" }} tab"
    }

    /** gate: whether a link caracole doesn't know may be read now, with no request: its state and, but `auto`, why.
     * Not while UG cools down after a block (`cooling`) or the hour's lookups are spent (`spent`), nor once its read
     * failed within the hour, or its tab page won't parse even fetched again until it is due (`failed`). */
    fun gate(cfg: PhoneConfig, db: Db, link: UgLink, now: Instant): Pair<String, String> {
        if (Health.isCooling(db, PROVIDER, now)) {
            return "cooling" to "UG turned us back; no asks until ${shown(Health.state(db, PROVIDER).cooldownUntil)}"
        }
        val p = cfg.provider(PROVIDER)
        if (p.lookupRequests < 1 || Pace.lookupRequestsUsed(db, PROVIDER, now) >= p.lookupPerHour) {
            return "spent" to "no more asks of UG this hour (${p.lookupPerHour} spent)"
        }
        failed(db, link.url, now)?.let { return "failed" to it }
        val until = link.tabId?.let { unreadableUntil(db, it) }
        if (until != null && !before(until, Stamps.micros(now))) {
            return "failed" to "UG's copy of it can't be read; caracole asks for it again after ${Py.slice(until, 0, 10)}"
        }
        return "auto" to ""
    }

    /** ug/fetch.unreadable_until: when caracole asks for the tab's page again, which proved unreadable (kv
     * `ug:unreadable:<tab id>`); null when it didn't. */
    fun unreadableUntil(db: Db, tabId: Long): String? =
        ((db.kvGetJson(Pages.unreadableKey(tabId)) as? JsonObject)?.get("until") as? JsonPrimitive)
            ?.takeIf { it.isString }?.content?.takeIf { it.isNotEmpty() }

    // --- how caracole names what a link stands for ----------------------------------------------------------

    /** ug/link.ARTIST_SONGS: an artist's songs a link's answer gives, most tabbed first, as /api/artist gives them at a
     * time. */
    const val ARTIST_SONGS = 50

    /** ug/link.Named: what a link stands for, named as caracole names it ([named]): the songs ([hits]: a tab's song,
     * or an artist page's songs once read, as a search gives them), the library's song of a tab ([song]), and the
     * artist and the title the panel fills in, the line a read ends with says, and a search names the song by. */
    data class Named(val artist: String, val title: String, val hits: List<IndexHit> = emptyList(),
                     val song: SongRow? = null)

    /** named: [was]'s songs and names: a tab's song by the keys it is filed under (Search.indexSong, its names a
     * search's); an artist page's songs once read (Search.artistSongs). The names are the library's song's, the one
     * that holds the tab as a version of its own, else of those names; else the hit's; else UG's as a search names a
     * song only an artist page lists (Search.listedNames). An artist link's title is "".
     *
     * With [rekey], the library's songs are re-keyed first where they are looked up by those names, as find_song does
     * (songs.ensure_current_keys: kv `songs:key_version`), as the command's writes do; a read-only answer (the route's)
     * looks them up as they are. */
    fun named(db: Db, was: LinkKnown, rekey: Boolean = false): Named {
        val link = was.link
        if (link.kind == UgLink.ARTIST) {
            val hits = if (was.state == "found" && !was.artistKey.isNullOrEmpty()) {
                Search.artistSongs(db, was.artistKey, limit = ARTIST_SONGS).first
            } else {
                emptyList()
            }
            return Named(if (was.artist.isNotEmpty()) Search.listedNames(db, was.artist, "").first else "", "", hits)
        }
        val known = was.state != "other" && was.state != "gone"
        val hit = if (was.keys != null && known) Search.indexSong(db, was.keys.first, was.keys.second, 100.0) else null
        var (artist, title) = when {
            hit != null -> hit.artist to hit.title
            was.tab != null -> Search.listedNames(db, was.tab.artist, was.tab.title)
            else -> "" to ""
        }
        var song = if (known) songOf(db, link) else null
        if (song == null && artist.isNotEmpty() && title.isNotEmpty() && known) {
            if (rekey) Rekey.ensure(db, Stamps.now())
            song = Songs.byKey(db, Normalize.identityKey(artist, title))
        }
        if (song != null) {  // the library's own song of it: its names
            artist = song.artist
            title = song.title
        }
        return Named(artist, title, listOfNotNull(hit), song)
    }

    /** _song_of: the library's song that holds the tab as a version of its own (`versions`, live), if any. */
    private fun songOf(db: Db, link: UgLink): SongRow? {
        val id = db.one("SELECT song_id FROM versions WHERE provider = 'ug' AND tab_id = ? AND gone = ? " +
                            "ORDER BY song_id LIMIT 1", link.tabId.toString(), Versions.LIVE) { it.long(0) }
            ?: return null
        return Songs.byId(db, id)
    }

    /** _a_tab: a tab read, as its line says it: its title by its artist, as caracole names them ([named]), and its
     * kind ("斑马斑马 by 宋冬野, chords"), with no bracket: status.py reads the line up to its first. */
    private fun aTab(db: Db, link: UgLink, page: UgTabPage): String {
        val known = LinkKnown(link, "found", tab = tabOf(page), keys = tabKeys(db, link.tabId!!))
        val names = named(db, known, rekey = true)
        val v = page.tab
        return "${names.title.ifEmpty { v.songName }} by ${names.artist.ifEmpty { v.artistName }}, " +
            (KIND_WORDS[v.kind ?: ""] ?: v.kind.toString())
    }

    /** known_line: what the command says of a link it reads nothing of ([known]: `found`, `other`, `gone`), in the
     * words a read ends with ([said]). */
    fun knownLine(db: Db, was: LinkKnown): String {
        val link = was.link
        if (was.state == "gone") return "Not found: UG answers 404 for ${link.url}."
        if (was.state == "other") return "Not read: ${link.url}: ${was.why}."
        val tabs = was.page?.let { ListedTabs.pageArtist(db, it)?.tabs } ?: 0
        val names = named(db, was, rekey = true)
        if (link.kind == UgLink.ARTIST) {
            return "Read: UG's page of ${names.artist.ifEmpty { "the artist" }} lists ${plural(tabs, "tab")}."
        }
        val song = if (names.title.isNotEmpty() && names.artist.isNotEmpty()) "${names.title} by ${names.artist}"
                   else "tab ${link.tabId}"
        val t = was.tab ?: return "Read: $song, in UG's index; nothing asked."
        val their = when {
            was.readAt != null -> "their page lists ${plural(tabs, "tab")}"
            was.page != null -> "their page isn't read yet"
            else -> "it links to no artist page"
        }
        return "Read: $song, ${KIND_WORDS[t.type] ?: t.type}; $their."
    }

    // --- a read that failed -----------------------------------------------------------------------------------

    /** _failures: the links whose read failed within [FAILED_FOR], by address, each its `at` and `error` as str()
     * reads them; an entry whose `at` is missing or unreadable is older than any. */
    private fun failures(db: Db, now: Instant): LinkedHashMap<String, Pair<String, String>> {
        val out = LinkedHashMap<String, Pair<String, String>>()
        val said = db.kvGet(FAILED_KEY)?.let { PyJson.loads(it) } as? JsonObject ?: return out
        val since = Stamps.micros(now) - FAILED_FOR.toHours() * HOUR_US
        for ((url, v) in said) {
            if (v !is JsonObject || before(v["at"], since)) continue
            out[url] = str(v["at"]) to (v["error"]?.takeUnless(::falsy)?.let(::str) ?: "")
        }
        return out
    }

    /** failed: why the page doesn't read the link by itself now: its read failed within the hour; null when it
     * didn't. */
    fun failed(db: Db, url: String, now: Instant): String? {
        val (_, error) = failures(db, now)[url] ?: return null
        return "reading it failed within the hour ($error)"
    }

    /** record_failure: the link's read failed (kv [FAILED_KEY]): the page doesn't send it by itself again within the
     * hour, and the failures older than that go. */
    fun recordFailure(db: Db, url: String, now: Instant, error: String) {
        val kept = failures(db, now)
        kept[url] = Stamps.of(now) to Py.slice(Py.split(error).joinToString(" "), 0, ERROR_CHARS)
        write(db, kept)
    }

    /** forget_failure: the link was read: its failure goes, and those older than the hour. */
    fun forgetFailure(db: Db, url: String, now: Instant) {
        val said = db.kvGet(FAILED_KEY)?.let { PyJson.loads(it) }
        val kept = failures(db, now)
        val gone = kept.remove(url) != null
        if (gone || (said is JsonObject && said.size != kept.size)) write(db, kept)
    }

    private fun write(db: Db, failures: Map<String, Pair<String, String>>) {
        db.kvSetJson(FAILED_KEY, JsonObject(failures.mapValuesTo(LinkedHashMap()) { (_, v) ->
            JsonObject(linkedMapOf("at" to JsonPrimitive(v.first), "error" to JsonPrimitive(v.second)))
        }))
    }

    // --- the page read now -------------------------------------------------------------------------------------

    /**
     * read's page: a tab link's page read now through [client] at [now], by the fetch's rules, and the artist page it
     * links to learned (its [LinkRead.page]); an artist link's page named. [stage] is told how each of its stages
     * (`tab`, `artist`) starts and ends. A block, a spent budget or an error propagates. ug/link.py's `read` is this,
     * then [readLists] when [LinkRead.page] names a page: the phone asks the two through the envelope apart, so that a
     * block, a spent budget or an error of a tab's artist page is the read's [LinkRead.stopped] (UgLinkCommands).
     */
    fun readPage(db: Db, client: Client, now: Instant, link: UgLink,
                 stage: (name: String, state: String, detail: String) -> Unit): LinkRead {
        val done = LinkRead(link, pageUrl(db, link))
        if (link.kind != UgLink.TAB) {
            done.page = link.url
            return done
        }
        val tabId = link.tabId!!
        stage("tab", "running", "asking Ultimate Guitar")
        val tab = Pages.readTabPage(db, client, now, tabId, done.url)
        done.tab = tab
        if (tab.said == TabRead.WAITS || tab.said == TabRead.UNREADABLE) done.until = unreadableUntil(db, tabId)
        val page = tab.page
        if (page == null || page.tab.kind == null) return done
        stage("tab", "done", aTab(db, link, page))
        done.page = Pages.learnArtistUrl(db, page)
        return done
    }

    /**
     * read's lists: the lists of the artist page [done] names read now through [client] at [now] (ArtistPages
     * .readArtistPage, of no song's: the chords list, then the tabs list, each whole, every page kept for searches),
     * the tabs you `[block]`ed never counted; UG's 404 for it forgets what caracole kept of it. A block, a spent budget
     * or an error propagates, what was read before it kept.
     */
    fun readLists(db: Db, client: Client, now: Instant, block: Set<Long>, done: LinkRead,
                  stage: (name: String, state: String, detail: String) -> Unit) {
        val base = done.page!!
        stage("artist", "running", "asking Ultimate Guitar")
        val reading = ListReading(db, client, now, UgFetch.ARTIST_PAGE_MAX_AGE, ARTIST_PAGES_PER_KIND, block)
        val listing = ArtistPages.readArtistPage(reading, base, ArtistRoute.ARTIST_PAGE_KINDS, forms = null)
        done.listing = listing
        if (listing.gone) {
            pageGone(db, base)
        } else {
            done.tabs = ListedTabs.pageArtist(db, base)?.tabs ?: 0
        }
    }

    /** FetchContext's artist_pages_per_kind, the default a link's read reads at. */
    private const val ARTIST_PAGES_PER_KIND = 3

    /** _page_gone: UG answered 404 for the artist page: its tabs go, and every artist it was learned for learns it
     * again. */
    private fun pageGone(db: Db, page: String) {
        val kv = UgLookup.ARTIST_URL_KV
        val keys = db.query("SELECT key FROM kv WHERE substr(key, 1, ?) = ? AND value = ? ORDER BY key", kv.length, kv,
                            page) { it.text(0)!! }
        for (key in keys) UgLookup.forgetArtistUrl(db, key.substring(kv.length))
        ArtistTabs.forget(db, page)
    }

    /** lists: what a tab's artist page read lists, in words. */
    fun lists(tabs: Int, done: LinkRead): String {
        if (done.listing != null && !done.listing!!.complete) {
            return "${plural(tabs, "tab")} of their page read so far, the rest the next time"
        }
        return "their page lists ${plural(tabs, "tab")}"
    }

    /** said: the line the read ends with, `Read: `, `Not found: ` or `Not read: `, the song and the artist named as
     * caracole names them ([named]), with no bracket in the part status.py reads; a block, a spent budget or an error
     * before anything was read is the command's to say. */
    fun said(db: Db, done: LinkRead): String {
        val link = done.link
        val tab = done.tab
        if (tab != null) {
            when (tab.said) {
                TabRead.GONE -> return "Not found: UG answers 404 for ${done.url}."
                TabRead.CLOSED, TabRead.REDIRECTED -> {
                    val where = if (tab.said == TabRead.CLOSED) "closes it" else "closes where UG sends it"
                    return "Not read: robots.txt $where to caracole (${done.url})."
                }
                TabRead.WAITS, TabRead.UNREADABLE -> {
                    val until = Py.slice(done.until ?: "?", 0, 10)
                    val error = tab.error?.let { " (${it.message})" } ?: ""
                    return "Not read: UG's copy of ${done.url} can't be read$error; caracole asks for it again after $until."
                }
            }
            val page = tab.page!!
            if (page.tab.kind == null) {
                val (artist, title) = Search.listedNames(db, page.tab.artistName, page.tab.songName)
                return "Read: $title by $artist is ${typeWords(page.tab.type)}: $KEEPS."
            }
            val named = aTab(db, link, page)
            val stopped = done.stopped
            return when {
                done.page == null -> "Read: $named; it links to no artist page."
                stopped is io.github.danielhp95.caracole.core.http.BudgetExhausted ->
                    "Read: $named; their page waits for the next lookup (its asks of UG are spent)."
                stopped is io.github.danielhp95.caracole.core.http.ProviderBlocked ->
                    "Read: $named; UG turned us back on their page (${stopped.message})."
                stopped != null -> "Read: $named; their page failed (${stopped.message})."
                done.pageGone -> "Read: $named; their page is gone (UG answers 404 for it)."
                else -> "Read: $named; ${lists(done.tabs, done)}."
            }
        }
        if (done.pageGone) return "Not found: UG answers 404 for ${link.url}."
        val listing = done.listing
        val ugName = listing?.name.orEmpty()
        val name = if (ugName.isNotEmpty()) Search.listedNames(db, ugName, "").first else "the artist"
        if (listing != null && !listing.complete) {
            return "Read: ${plural(done.tabs, "tab")} of UG's page of $name so far, the rest the next time."
        }
        return "Read: UG's page of $name lists ${plural(done.tabs, "tab")}."
    }

    // --- Python's values ---------------------------------------------------------------------------------------

    /** logs.plural: "1 tab", "2 tabs". */
    fun plural(n: Int, noun: String): String = "$n ${if (n == 1) noun else noun + "s"}"

    /** stamps.shown: "2026-11-03 12:30 UTC", "?" for none. */
    fun shown(at: Instant?): String {
        if (at == null) return "?"
        val stamp = Stamps.of(at)
        return stamp.substring(0, 10) + " " + stamp.substring(11, 16) + " UTC"
    }

    /** stamps.before: a stored time older than [cutoff] (microseconds), or missing or unreadable. */
    private fun before(value: JsonElement?, cutoff: Long): Boolean {
        val at = Stamps.parse(value) ?: return true
        return at < cutoff
    }

    private fun before(value: String, cutoff: Long): Boolean = before(JsonPrimitive(value), cutoff)

    /** str() of a JSON value as Python holds it. */
    private fun str(e: JsonElement?): String = when {
        e == null -> "None"
        e is JsonPrimitive && e.isString -> e.content
        else -> PyBits.str(e)
    }

    private fun falsy(e: JsonElement): Boolean = when (e) {
        is JsonObject -> e.isEmpty()
        is kotlinx.serialization.json.JsonArray -> e.isEmpty()
        is JsonPrimitive -> when {
            e.isString -> e.content.isEmpty()
            e.content == "null" || e.content == "false" -> true
            else -> e.content.toDoubleOrNull() == 0.0
        }
    }
}
