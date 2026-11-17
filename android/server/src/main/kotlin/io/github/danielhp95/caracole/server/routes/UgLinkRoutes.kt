package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.ug.UgLink
import io.github.danielhp95.caracole.core.ug.UgLinks
import io.github.danielhp95.caracole.core.ug.UgUrls
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.server.routes.search.Rows
import io.github.danielhp95.caracole.server.routes.search.SongForms
import io.github.danielhp95.caracole.server.routes.search.hitJson
import io.github.danielhp95.caracole.server.routes.search.jsonResponse
import io.github.danielhp95.caracole.server.routes.search.obj
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.File
import java.time.Instant

/**
 * A UG link pasted into the library page's search box, on the phone as on caracole serve (web/ug_link_routes.py; the
 * plan, docs/superpowers/plans/2026-11-17-ug-link.md):
 *
 *     GET  /api/ug/link?url=  what caracole knows of the link (UgLinks.known: the database and the phone's HTTP cache,
 *                             no request): its kind, page, state (found, auto, cooling, spent, failed, other, gone)
 *                             and why, the tab's names, its artist's page, the names the panel fills in, the
 *                             library's song of it, and the hits a search's rows draw
 *     POST /ug/link           (`url`) when its state is `auto`: `caracole ug --link --progress` queued, a job of no
 *                             song's under `ug-link:` and the page's address, at the lookup pace; asked again while
 *                             it waits or runs, that job. 202 {job, url}; refused 400 (no UG link), 409 (found, other,
 *                             gone), 429 (cooling, spent, failed)
 *
 * vectors/web/ug_link.jsonl holds both to caracole serve's answers (UgLinkReplay).
 */
class UgLinkRoutes(val parts: PhoneParts, private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/api/ug/link", "a UG link pasted into the search box: what caracole knows of it (url)",
              get = GetAnswer { request -> link(request) }),
        Route("POST", "/ug/link", "a UG link pasted into the search box read now (url)",
              post = PostAnswer { request, form -> read(request, form) }),
    )

    private val cacheDir: File get() = File(parts.stateDir, "cache")
    private val forms = SongForms()

    /** pasted_link: the UG page a pasted text links to (UgUrls.readLink, a text of [LINK_LIMIT] code points at most);
     * refused (400) for anything else. */
    private fun pastedLink(text: String): UgLink {
        val link = if (text.codePointCount(0, text.length) <= LINK_LIMIT) UgUrls.readLink(text) else null
        return link ?: throw Refused(400, "Not a UG link", "Not an Ultimate Guitar tab's page or artist's page.")
    }

    /** api_ug_link (GET /api/ug/link). */
    private fun link(request: Request): Response {
        val link = pastedLink(PyUrl.query(request.target)["url"].orEmpty())
        val now = clock()
        val answer = parts.database.read { db ->
            val overrides = Overrides.read(db)
            linkAnswer(db, overrides, link, now)
        }
        return jsonResponse(200, answer)
    }

    /** read_ug_link (POST /ug/link): refused as the module's docstring says, else the read queued. */
    private fun read(request: Request, form: Map<String, String>): Response {
        val link = pastedLink(PyText.strip(form["url"].orEmpty()))
        val now = clock()
        val was = parts.database.read { db -> UgLinks.known(parts.config(), db, cacheDir, link, now) }
        when (was.state) {
            "found" -> throw Refused(409, "Read already", "Read already: caracole knows this page.")
            "other", "gone" -> throw Refused(409, "Nothing to read", "Nothing to read: ${was.why}.")
            "auto" -> {}
            else -> throw Refused(429, "Not now", "Not now: ${was.why}.")
        }
        val what = if (link.kind == UgLink.TAB) "tab ${link.tabId}" else "an artist's page"
        val display = if (link.kind == UgLink.TAB) "A tab on Ultimate Guitar" else "An artist on Ultimate Guitar"
        val spec = LookupForms.spec("Read $what on Ultimate Guitar", JobCommands.UG_LINK + link.url,
                                    JobCommands.ugLinkSteps(link.url), display = display)
        val job = parts.queue.submitOrRefuse(spec, JobQueue.QUEUE_FULL).first
        if ("application/json" !in PyText.lower(request.headers["accept"].orEmpty())) {
            return Response(303, Body.Empty, mutableListOf("Location" to "/${Status.detailsHref(job.id)}"))
        }
        return Answers.json(JsonObject(linkedMapOf(
            "job" to JsonPrimitive(job.id), "url" to JsonPrimitive("/api/jobs/${job.id}"),
        )), 202)
    }

    /** link_answer: `GET /api/ug/link`'s answer for [link]. */
    private fun linkAnswer(db: Db, overrides: Overrides, link: UgLink, now: Instant): JsonObject {
        val config = parts.config()
        val was = UgLinks.known(config, db, cacheDir, link, now)
        val found = was.state == "found"
        val songs = Songs.list(db)
        var hits: List<IndexHit> = emptyList()
        if (found && link.kind == UgLink.TAB && was.keys != null) {
            hits = listOfNotNull(Search.indexSong(db, was.keys!!.first, was.keys!!.second, 100.0))
        } else if (found && link.kind == UgLink.ARTIST && !was.artistKey.isNullOrEmpty()) {
            hits = Search.artistSongs(db, was.artistKey!!, limit = ARTIST_SONGS).first
        }
        var guess: Pair<String, String> = when {
            link.kind == UgLink.ARTIST ->
                (if (was.artist.isNotEmpty()) Search.listedNames(db, was.artist, "").first else "") to ""
            hits.isNotEmpty() -> hits[0].artist to hits[0].title
            was.tab != null -> Search.listedNames(db, was.tab!!.artist, was.tab!!.title)
            else -> "" to ""
        }
        var song = if (link.kind == UgLink.TAB) songOf(db, link) else null
        if (song == null && link.kind == UgLink.TAB && guess.first.isNotEmpty() && guess.second.isNotEmpty()) {
            song = Songs.byKey(db, Normalize.identityKey(guess.first, guess.second))
        }
        if (song != null) guess = song.artist to song.title  // the library's own song of it: its names
        val rows = if (hits.isEmpty()) emptyList() else {
            val enabled = config.providers.filterValues { it.enabled }.keys
            Rows(db, songs, parts.cards, forms, enabled).rows(emptyList(), hits.map { hitJson(db, it) }).second
        }
        val out = linkedMapOf<String, Any?>("kind" to link.kind, "url" to link.url, "tab_id" to link.tabId,
                                            "type" to link.type, "state" to was.state)
        if (was.why.isNotEmpty()) out["why"] = was.why
        out["tab"] = was.tab?.let { t ->
            obj("artist" to t.artist, "title" to t.title, "type" to t.type, "version" to t.version, "rating" to t.rating,
                "votes" to t.votes)
        }
        out["artist_page"] = was.page?.let {
            obj("url" to it, "read" to (was.readAt != null), "read_at" to was.readAt?.takeIf { at -> at.isNotEmpty() })
        }
        out["guess"] = obj("artist" to guess.first, "title" to guess.second)
        out["song"] = song?.let { songJson(db, overrides, it, link) }
        out["hits"] = rows
        return obj(*out.toList().toTypedArray())
    }

    /** _song_of: the library's song that holds the tab as a version of its own (`versions`, live), if any. */
    private fun songOf(db: Db, link: UgLink): SongRow? {
        val id = db.one("SELECT song_id FROM versions WHERE provider = 'ug' AND tab_id = ? AND gone = ? " +
                            "ORDER BY song_id LIMIT 1", link.tabId.toString(), Versions.LIVE) { it.long(0) }
            ?: return null
        return Songs.byId(db, id)
    }

    /** _song_json: the library's song of a link, as the panel names it: whether it has a sheet and the link to it, and
     * whether this tab is that sheet or its pick (`this_tab`: `[pin]`). */
    private fun songJson(db: Db, overrides: Overrides, song: SongRow, link: UgLink): JsonObject {
        val sheet = db.one(
            "SELECT v.provider, v.tab_id FROM files f LEFT JOIN versions v ON v.id = f.version_id " +
                "WHERE f.song_id = ? AND f.name = ?", song.id, HUMAN_SHEET,
        ) { it.text(0) to it.text(1) }
        val thisTab = (sheet != null && sheet.first == "ug" && sheet.second == link.tabId.toString()) ||
            (link.tabId != null && link.tabId in overrides.pin[song.key].orEmpty())
        return obj("id" to song.id, "identity" to song.key, "display" to song.display, "has_sheet" to (sheet != null),
                   "sheet" to (if (sheet != null) sheetHref(db, song) else null), "this_tab" to thisTab)
    }

    /** library_page.sheet_href on the phone: the song's card's primary file, as its line opens it. */
    private fun sheetHref(db: Db, song: SongRow): String? {
        val files = parts.cards.cards(db, listOf(song))[song.id]?.get("files") as? JsonArray ?: return null
        return files.filterIsInstance<JsonObject>().firstOrNull { (it["primary"] as? JsonPrimitive)?.booleanOrNull == true }
            ?.let { (it["href"] as? JsonPrimitive)?.content }
    }

    companion object {
        /** ug_link_routes.LINK_LIMIT: characters of a pasted address. */
        const val LINK_LIMIT = 600

        /** ug_link_routes.ARTIST_SONGS: an artist's songs a link's answer gives, most tabbed first. */
        const val ARTIST_SONGS = 50

        /** songs.HUMAN_SHEET. */
        private const val HUMAN_SHEET = "sheet.txt"
    }
}
