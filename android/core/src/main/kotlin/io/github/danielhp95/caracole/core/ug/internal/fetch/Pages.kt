package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.http.UnreadablePage
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgLookup
import io.github.danielhp95.caracole.core.ug.UgArtist
import io.github.danielhp95.caracole.core.ug.UgPage
import io.github.danielhp95.caracole.core.ug.UgTabPage
import io.github.danielhp95.caracole.core.ug.UgVersion
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/**
 * ug/fetch.py's `_SongRun`: one song's fetch, the tab pages already read for it ([pages], null for one gone, unread or
 * closed), how many pages of each UG type were fetched from UG ([fetched]; cache hits are free), the tabs whose pages
 * couldn't be read ([unreadable]) or that UG moved where robots.txt closes ([closed]) this run, and the tabs kept
 * beside the sheet once its slot is settled ([keptVersions]).
 */
internal class SongRun(val ctx: FetchContext, var song: SongRow) {
    val pages = HashMap<Long, UgTabPage?>()
    val fetched = HashMap<String, Int>()
    val unreadable = LinkedHashSet<Long>()
    val closed = LinkedHashSet<Long>()
    var keptVersions: List<String> = emptyList()

    val db: Db get() = ctx.db

    /** The UG artist key the song is filed under: its match, else its own artist's key. */
    val artistKey: String get() = song.matchArtistKey?.takeIf { it.isNotEmpty() } ?: Normalize.slugKey(song.artist)

    /** The run's time as caracole stores one (`_iso`). */
    val stamp: String get() = Stamps.of(ctx.now)

    fun count(kind: String) {
        fetched[kind] = (fetched[kind] ?: 0) + 1
    }
}

/** ug/fetch.py's pages and versions: reading a tab page once a run, recording the versions it lists, and what a page
 * that can't be read, is gone or is closed to caracole leaves. */
internal object Pages {
    private val PAGE_ACCEPT = setOf(200, 404)
    private val TAB_HOST = PyUrl.urlsplit(UgPage.TAB_BASE_URL).netloc
    private val ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")

    /** `_slot`. */
    fun slot(kind: String): String = if (kind in Versions.SHEET_KINDS) "sheet" else "guitar"

    /** `_GROUP_OF`: each kind's group (chords; tabs; ukulele). */
    fun groupOf(kind: String?): List<String>? = when (kind) {
        "chords" -> UgFetch.CHORDS_KINDS
        "tabs" -> UgFetch.TAB_KINDS
        "ukulele" -> UgFetch.UKULELE_KINDS
        else -> null
    }

    /** `_parse_iso`: a time caracole stored, or null where strptime raises. */
    fun parseIso(value: String): Instant? = try {
        LocalDateTime.parse(value, ISO).toInstant(ZoneOffset.UTC)
    } catch (e: DateTimeParseException) {
        null
    }

    /**
     * `_read_page`: a UG page from the HTTP cache or UG (null when UG answers 404) and the answer it was read from.
     * UG's 404 page has no js-store, so the status is checked before parsing. A cached copy that no longer parses is
     * fetched once more; when that doesn't parse either, the page is [UnreadablePage]. With [maxAge], a cached copy
     * older than that is no answer for [now] (PoliteClient serves one only once the budget is spent): BudgetExhausted.
     */
    fun <P> readPage(client: Client, url: String, parse: (ByteArray, String) -> P, maxAge: Duration? = null,
                     now: Instant? = null): Pair<P?, Response> {
        fun parsed(resp: Response): P? = if (resp.status == 404) null else parse(resp.content, url)
        val resp = client.get(url, accept = PAGE_ACCEPT, maxAge = maxAge)
        if (maxAge != null && now != null && HttpRules.stale(resp, now, maxAge)) throw BudgetExhausted(UgFetch.PROVIDER)
        try {
            return parsed(resp) to resp
        } catch (e: PageParseError) {
            if (!resp.fromCache) throw e
        }
        val again = client.get(url, accept = PAGE_ACCEPT, cache = false)
        try {
            return parsed(again) to again
        } catch (e: PageParseError) {
            throw UnreadablePage(e.provider, e.url, e.status, e.msg).also { it.initCause(e) }
        }
    }

    /** `_get_page`: [readPage], and whether the page was fetched now. */
    fun <P> getPage(client: Client, url: String, parse: (ByteArray, String) -> P, maxAge: Duration? = null,
                    now: Instant? = null): Pair<P?, Boolean> {
        val (page, resp) = readPage(client, url, parse, maxAge, now)
        return page to !resp.fromCache
    }

    fun tabPage(html: ByteArray, url: String): UgTabPage = UgPage.parseTabPage(html, url)

    private fun upsert(run: SongRun, v: UgVersion): Long {
        val kind = v.kind!!
        return Versions.upsert(run.db, UgFetch.PROVIDER, v.tabId.toString(), run.song.id, slot(kind), kind, v.rating,
                               v.votes, v.version, v.label, v.url, v.raw, run.stamp)
    }

    /** `_closed`: whether robots.txt closes [url]: caracole never asks for it, and a tab there is no candidate. */
    fun closed(url: String): Boolean = Robots.disallows(url) != null

    /** `_on_tab_host`: whether a link points under `/tab/` on the tabs host (one urllib can't parse points nowhere). */
    fun onTabHost(url: String): Boolean {
        val parts = try {
            PyUrl.urlsplit(url)
        } catch (e: PyUrl.Invalid) {
            return false
        }
        val segments = parts.path.split("/")
        return parts.scheme in setOf("http", "https") && parts.netloc == TAB_HOST && segments.size > 2 &&
            segments[1] == "tab"
    }

    /** `_tab_page_url`: on the tabs host, and open in robots.txt. */
    fun tabPageUrl(url: String): Boolean = onTabHost(url) && !closed(url)

    /** `_wanted`: a kind caracole uses (never Official), public and not blocked. */
    fun wanted(run: SongRun, v: UgVersion): Boolean =
        v.kind != null && v.access == "public" && v.tabId !in run.ctx.overrides.block

    /** `_usable`: a version caracole wants, at a tab page it may read. */
    fun usable(run: SongRun, v: UgVersion): Boolean = wanted(run, v) && tabPageUrl(v.url)

    /** `_slugged_url`: whether a tab page URL is the slugged `/tab/{artist}/{song}-{type}-{id}` of [tabId]. */
    fun sluggedUrl(url: String, tabId: Long): Boolean {
        val segments = PyUrl.urlsplit(url).path.split("/")
        return segments.size == 4 && segments[3].endsWith("-$tabId")
    }

    /** `_links_a_tab_page`: a version links to a tab page caracole may read, or its own slugged page. */
    private fun linksATabPage(v: UgVersion): Boolean = tabPageUrl(v.url) || (onTabHost(v.url) && sluggedUrl(v.url, v.tabId))

    /** `_check_links`: [PageParseError] when a page lists versions caracole wants and not one links to a tab page. */
    fun checkLinks(run: SongRun, versions: List<UgVersion>, url: String) {
        val wanted = versions.filter { wanted(run, it) }
        if (wanted.isNotEmpty() && wanted.none { linksATabPage(it) }) {
            throw PageParseError(UgFetch.PROVIDER, url, null, "no version on the page links to a tab page")
        }
    }

    /** `_known`: whether the song has the version on record under its current match (a stale one isn't). */
    private fun known(run: SongRun, tabId: Long): Boolean = run.db.one(
        "SELECT 1 FROM versions WHERE provider = ? AND tab_id = ? AND song_id = ? AND gone != ?",
        UgFetch.PROVIDER, tabId.toString(), run.song.id, Versions.STALE,
    ) { true } != null

    /** `_record`: usable versions recorded; a cached page only adds the versions the song doesn't have yet. */
    fun record(run: SongRun, versions: List<UgVersion>, fresh: Boolean) {
        for (v in versions) {
            if (usable(run, v) && (fresh || !known(run, v.tabId))) upsert(run, v)
        }
    }

    /** `_record_page`: the page's own tab (at [url], should its own link go elsewhere) and the versions it lists of
     * the same kind group. */
    private fun recordPage(run: SongRun, page: UgTabPage, url: String, fresh: Boolean) {
        val group = groupOf(page.tab.kind) ?: return
        val inGroup = (listOf(page.tab) + page.versions).filter { it.kind in group }
        val tab = inGroup.first()
        checkLinks(run, inGroup, url)
        val own = if (tabPageUrl(tab.url)) tab else tab.copy(url = url)
        record(run, listOf(own) + inGroup.drop(1), fresh)
    }

    /** `_version_row`: the song's UG version of [tabId], gone or not. */
    fun versionRow(run: SongRun, tabId: Long): VersionRow? =
        Versions.songVersions(run.db, run.song.id, includeGone = true)
            .firstOrNull { it.provider == UgFetch.PROVIDER && it.tabId == tabId.toString() }

    /** `_mark_gone`: UG answered 404, the version is gone; an id the index alone knows gets a row to say so. */
    private fun markGone(run: SongRun, tabId: Long, url: String, kind: String?) {
        val row = versionRow(run, tabId)
        val id = when {
            row != null -> row.id
            groupOf(kind) != null -> Versions.upsert(run.db, UgFetch.PROVIDER, tabId.toString(), run.song.id,
                                                     slot(kind!!), kind, 0.0, 0, 0, null, url, JsonObject(emptyMap()),
                                                     run.stamp)
            else -> return
        }
        Versions.markGone(run.db, id)
    }

    /** `_artist_page_base`: the UG artist page a link of UG's points to (a relative link is UG's own), else null. */
    fun artistPageBase(url: String?): String? {
        if (url.isNullOrEmpty()) return null
        return try {
            OverrideUrls.artistPageAddress(PyUrl.urljoin(UgArtist.WWW + "/", Py.strip(url)))
        } catch (e: PyUrl.Invalid) {
            null
        }
    }

    /** `_a_pair`: whether the artist UG names features another ("Ma Di (feat. 宋冬野)"). */
    private fun aPair(name: String): Boolean = Normalize.withoutFeaturing(name) != Py.strip(name)

    /** `_same_artist`: whether the artist UG names [name] is the one filed under [key]: they share a form, hyphens
     * aside. A pair is neither of its artists. */
    private fun sameArtist(key: String, name: String): Boolean {
        if (aPair(name)) return false
        val mine = Normalize.nameForms(key).map(Normalize::compact).toSet()
        return Normalize.nameForms(name).any { Normalize.compact(it) in mine }
    }

    /** `_learn_artist_url`: the artist page a tab page links to remembered under its artist's keys and [also]
     * (a pair's under the pair's own name alone); the page. */
    fun learnArtistUrl(db: Db, page: UgTabPage, also: List<String> = emptyList()): String? {
        val url = artistPageBase(page.artistUrl) ?: return null
        val name = page.tab.artistName
        val own = if (aPair(name)) listOf(Normalize.slugKey(name)) else Normalize.nameForms(name)
        for (key in LinkedHashSet(own + also)) {
            if (key.isNotEmpty()) UgLookup.rememberArtistUrl(db, key, url)
        }
        return url
    }

    fun unreadableKey(tabId: Long): String = "ug:unreadable:$tabId"

    /** `_waits`: whether the tab's page proved unreadable and isn't due to be asked for again yet. */
    fun waits(run: SongRun, tabId: Long): Boolean {
        val record = run.db.kvGetJson(unreadableKey(tabId)) as? JsonObject ?: return false
        val until = (record["until"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return false
        val at = parseIso(until) ?: return false
        return run.ctx.now < at
    }

    /** `_note_unreadable`: when to ask for the tab's page again, which won't parse even fetched again: after a week,
     * then after twice as long each time it still won't, 90 days at most. */
    fun noteUnreadable(run: SongRun, tabId: Long, error: UnreadablePage) {
        val record = run.db.kvGetJson(unreadableKey(tabId)) as? JsonObject
        val before = (record?.get("strikes") as? JsonPrimitive)?.let { it.longOrNull ?: it.doubleOrNull?.toLong() } ?: 0L
        val strikes = before + 1
        val until = run.ctx.now.plus(retryAfter(strikes))
        run.db.kvSetJson(unreadableKey(tabId), JsonObject(linkedMapOf(
            "until" to JsonPrimitive(Stamps.of(until)), "strikes" to JsonPrimitive(strikes),
            "error" to JsonPrimitive(error.message ?: ""),
        )))
    }

    /** `min(UNREADABLE_RETRY * 2 ** (strikes - 1), UNREADABLE_RETRY_MAX)`, a negative power as Python's float one. */
    private fun retryAfter(strikes: Long): Duration {
        val most = UgFetch.UNREADABLE_RETRY_MAX
        if (strikes - 1 >= 8) return most
        val micros = Math.round(UgFetch.UNREADABLE_RETRY.toNanos() / 1000.0 * Math.pow(2.0, (strikes - 1).toDouble()))
        val after = Duration.ofNanos(micros * 1000)
        return if (after < most) after else most
    }

    /** `_unreadable`: no page for the tab this run; with [error], when to ask for it again noted. Never taken for
     * gone: the song goes on with its other versions, and stays dirty to read this one once it is due. */
    private fun unreadable(run: SongRun, tabId: Long, kind: String?, error: UnreadablePage? = null) {
        if (error != null) {
            run.count(kind ?: "?")  // the request that fetched it again
            noteUnreadable(run, tabId, error)
        }
        run.pages[tabId] = null
        run.unreadable += tabId
    }

    /**
     * `_page`: a tab page of this song, read once per run; null when UG says it's gone, or it can't be read. [kind]
     * (the index's type) lets a deleted tab never rated be remembered as gone. Every page teaches caracole its
     * artist's UG page, filed under the song's artist only when the tab is by that artist. A page that won't parse
     * even fetched again waits until it is due; one robots.txt closes is null without a request, neither gone nor
     * unreadable, and so is one UG redirects to where robots.txt closes, not asked for again this run.
     */
    fun page(run: SongRun, tabId: Long, url: String, kind: String? = null): UgTabPage? {
        if (tabId in run.pages) return run.pages[tabId]
        if (closed(url)) return null
        if (waits(run, tabId)) {
            unreadable(run, tabId, kind)
            return null
        }
        val (page, fresh) = try {
            getPage(run.ctx.client, url, ::tabPage)
        } catch (e: UnreadablePage) {
            unreadable(run, tabId, kind, e)
            return null
        } catch (e: RobotsClosed) {
            run.count(kind ?: "?")  // the request UG answered with the redirect
            run.pages[tabId] = null
            run.closed += tabId
            return null
        }
        run.db.kvDelete(unreadableKey(tabId))
        run.pages[tabId] = page
        if (fresh) run.count(page?.let { it.tab.kind } ?: kind ?: "?")
        if (page == null) {
            markGone(run, tabId, url, kind)
            return null
        }
        recordPage(run, page, url, fresh)
        val mine = run.artistKey
        val also = if (mine.isNotEmpty() && sameArtist(mine, page.tab.artistName)) listOf(mine) else emptyList()
        learnArtistUrl(run.db, page, also)
        return page
    }

    /** The JSON a kept file holds: json.dumps(body, ensure_ascii=False, indent=2) and a newline. */
    fun keptJson(body: JsonObject): ByteArray = (PyJson.dumps(body, indent = 2) + "\n").toByteArray(Charsets.UTF_8)
}
