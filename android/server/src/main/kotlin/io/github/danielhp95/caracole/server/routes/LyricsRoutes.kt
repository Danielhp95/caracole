package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.sites.LyricsPickCommands
import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * A song's lyrics looked up under a name typed, on the phone as on caracole serve (web/lyrics_routes.py):
 *
 *     POST /lyrics/search   (`song`, `identity`, `artist`, `title`): `caracole lyrics --song --as` queued, a lookup of
 *                           no song's under `lyrics-search:` and the song's key; the name the command reads (lyrics_search
 *                           typed_name) is the one queued and answered (`as`); 202 {job, url, as} to the page's script,
 *                           the search on its way the answer, `said` naming it when another name was typed
 *     GET  /api/lyrics/search?song=ID   what the card's panel shows, with no request and no write: `[lyrics]`' `as`
 *                           and `picked`, `picked_why`, `picked_note`, the audio's length, the kept search (its rows,
 *                           words and last line; past its week the name and the day alone), the song's lyrics state
 *                           and `lyrics_note`; with `card=1` the song's card as the page draws it now
 *     POST /lyrics/pick     (`song`, `identity`, `record`): a row of the kept search taken as the song's lyrics:
 *                           `caracole lyrics --song --record --progress` queued under `lyrics:` and the song's key
 *
 * Refused as caracole serve refuses: no such song (404), another song's identity, ignored (409), a name of no artist
 * or title (400), a record no row of a search within its week (409 "Search again"), a site off (409), another record
 * while a pick is on its way (409); a clear of a song with no record picked (409). `POST /lyrics/clear` queues
 * `caracole lyrics --song --clear` under `lyrics-clear:`. vectors/web/lyrics_routes.jsonl holds the four to caracole
 * serve's answers (WebReplay.lyricsRoutes).
 */
class LyricsRoutes(val parts: PhoneParts, private val clock: () -> Instant = Instant::now,
                   private val fileLength: (String) -> Double? = { null }) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/lyrics/search", "a song's lyrics looked up under a name typed (song, identity, artist, title)",
              post = PostAnswer { request, form -> search(request, form) }),
        Route("GET", "/api/lyrics/search", "what the card's lyrics panel shows of a song's search (song, identity, card)",
              get = GetAnswer { request -> apiSearch(request) }),
        Route("POST", "/lyrics/pick", "a row of a song's kept lyrics search taken as its lyrics (song, identity, record)",
              post = PostAnswer { request, form -> pick(request, form) }),
        Route("POST", "/lyrics/clear", "the lyrics record picked for a song taken back (song, identity)",
              post = PostAnswer { _, form -> clear(form) }),
    )

    /** lyrics_routes._song: the song a form names by its id, the one its `identity` names, not ignored. */
    private fun song(db: Db, form: Map<String, String>): SongRow {
        val overrides = LookupForms.overrides(db)
        val song = LookupForms.song(db, LookupForms.songId(form["song"].orEmpty()))
        LookupForms.sameSong(song, form)
        LookupForms.notIgnored(song, overrides)
        return song
    }

    /** lyrics_routes._typed: the name the command will ask under for the fields typed. */
    private fun typed(db: Db, artist: String, title: String): Pair<String, String> {
        val a = artist.codePointCount(0, artist.length)
        val t = title.codePointCount(0, title.length)
        if (a !in 1..NAME_MOST || t !in 1..NAME_MOST) throw Refused(400, "Which name?", WHICH_NAME)
        if (" - " in artist) throw Refused(400, "Which name?", "An artist's name can't hold “ - ”.")
        val text = "$artist - $title"
        return LyricsSearchCommands.typedName(db, text, Songs.list(db))
            ?: throw Refused(400, "Which name?", "Which name? “$text” names no artist and title once cleaned.")
    }

    private fun asJson(name: Pair<String, String>?): JsonElement = name?.let {
        JsonObject(linkedMapOf("artist" to JsonPrimitive(it.first), "title" to JsonPrimitive(it.second)))
    } ?: JsonNull

    /** The value a job's command gives an option ([prefix], `--as=`), else "". */
    private fun option(job: Job, vararg prefixes: String): String = job.steps.asSequence().flatMap { it.args }
        .firstOrNull { arg -> prefixes.any { arg.startsWith(it) } }?.substringAfter('=') ?: ""

    private fun wantsJson(request: Request) = "application/json" in PyText.lower(request.headers["accept"].orEmpty())

    /** lyrics_routes.search (POST /lyrics/search). */
    private fun search(request: Request, form: Map<String, String>): Response {
        val (song, name) = parts.database.read { db ->
            val s = song(db, form)
            s to typed(db, Py.strip(form["artist"].orEmpty()), Py.strip(form["title"].orEmpty()))
        }
        val named = "${name.first} - ${name.second}"
        val spec = LookupForms.spec("Lyrics under “$named”", JobCommands.LYRICS_SEARCH + song.key,
                                    JobCommands.lyricsSearchSteps(song.display, named), display = song.display)
        val (job, new) = parts.queue.submitOrRefuse(spec, JobQueue.QUEUE_FULL)
        val answer = linkedMapOf<String, JsonElement>("job" to JsonPrimitive(job.id),
                                                      "url" to JsonPrimitive("/api/jobs/${job.id}"), "as" to asJson(name))
        val asked = option(job, "--as=")
        if (!new && asked != named) {
            answer["as"] = asJson(parts.database.read { db -> LyricsSearchCommands.typedName(db, asked, Songs.list(db)) })
            answer["said"] = JsonPrimitive("A search under “$asked” is on its way: ask under “$named” once it is over.")
        }
        if (!wantsJson(request)) return Response(303, Body.Empty, mutableListOf("Location" to "/${Status.detailsHref(job.id)}"))
        return Answers.json(JsonObject(answer), 202)
    }

    /** lyrics_routes.api_search (GET /api/lyrics/search). */
    private fun apiSearch(request: Request): Response {
        val query = PyUrl.query(request.target)
        val now = clock()
        val answer = parts.database.read { db ->
            val overrides = LookupForms.overrides(db)
            val song = LookupForms.song(db, LookupForms.songId(query["song"].orEmpty(), where = "address"))
            LookupForms.sameSong(song, mapOf("identity" to query["identity"].orEmpty()))
            val kept = LyricsSearchCommands.lastSearch(db, song.id, now)
            val length = LyricsSearchCommands.audioLength(db, song, fileLength)
            val card = if (query["card"] == "1") card(db, song, overrides) else null
            answer(song, overrides, kept, length, now, card)
        }
        return Answers.json(answer)
    }

    private fun card(db: Db, song: SongRow, overrides: Overrides): JsonObject? {
        val made = parts.cards.cards(db, listOf(song))[song.id] ?: return null
        return JsonObject(made + ("fetchable" to JsonPrimitive(!LookupForms.reviewFirst(song, overrides))))
    }

    private fun answer(song: SongRow, overrides: Overrides, kept: LyricsSearchCommands.Search?, length: Double?,
                       now: Instant, card: JsonObject?): JsonObject {
        val entry = overrides.lyrics[OverrideUrls.overrideKey(song.display)]
        val record = entry?.record
        val why = pickedWithoutLyrics(song, overrides)
        val again = entry?.asked?.takeIf { record == null && song.lyricsStatus == "pending" }
        val out = linkedMapOf<String, JsonElement>(
            "song" to JsonPrimitive(song.id), "identity" to JsonPrimitive(song.key),
            "lyrics" to JsonPrimitive(song.lyricsStatus),
            "lyrics_note" to (again?.let {
                JsonPrimitive("Its lyrics are asked for again under “${it.first} - ${it.second}”, tonight or at a lookup.")
            } ?: JsonNull),
            "as" to asJson(entry?.asked), "picked" to (record?.let { JsonPrimitive(it.text) } ?: JsonNull),
            "picked_why" to (why?.let(::JsonPrimitive) ?: JsonNull),
            "picked_note" to (pickedNote(why, record?.text, record?.let { "${it.site} ${it.id}" }, kept)?.let(::JsonPrimitive)
                ?: JsonNull),
            "length" to (length?.let(io.github.danielhp95.caracole.core.json.PyJson::float) ?: JsonNull),
            "search" to (kept?.let { searchJson(it, now) } ?: JsonNull),
        )
        if (card != null) out["card"] = card
        return JsonObject(out)
    }

    /** transcript.picked_without_lyrics: why a song whose record was picked and has no lyrics is never heard. */
    private fun pickedWithoutLyrics(song: SongRow, overrides: Overrides): String? {
        val record = overrides.lyrics[OverrideUrls.overrideKey(song.display)]?.record ?: return null
        if (song.lyricsStatus !in setOf("pending", "missing")) return null
        val said = "${record.site} ${record.id}"
        val words = if (song.lyricsStatus == "missing") "picked_none" else "picked_unread"
        return AudioRunner.Words.text(words).replace("{record}", said)
    }

    /** lyrics_routes._picked_note. */
    private fun pickedNote(why: String?, record: String?, named: String?, kept: LyricsSearchCommands.Search?): String? {
        if (why != null && why.isNotEmpty()) return io.github.danielhp95.caracole.core.py.PyUnicode.upper(Py.slice(why, 0, 1)) + Py.slice(why, 1, null) + "."
        if (record == null || (kept != null && kept.rows.any { it.record == record })) return null
        return "Its lyrics are the record you picked ($named)."
    }

    /** lyrics_routes._search_json. */
    private fun searchJson(kept: LyricsSearchCommands.Search, now: Instant): JsonObject {
        val asked = JsonPrimitive(LyricsSearchCommands.askedLine(kept, now))
        if (!LyricsSearchCommands.pickable(kept, now)) {
            return JsonObject(linkedMapOf("at" to JsonPrimitive(kept.at), "as" to asJson(kept.asked), "length" to JsonNull,
                                          "rows" to JsonArrayOf(), "said" to JsonObject(emptyMap()), "asked" to asked,
                                          "state" to JsonObject(emptyMap()), "instrumental" to JsonPrimitive(0),
                                          "pickable" to JsonPrimitive(false), "notes" to JsonArrayOf(), "line" to JsonNull))
        }
        val json = kept.json()
        return JsonObject(linkedMapOf(
            "at" to JsonPrimitive(kept.at), "as" to asJson(kept.asked), "length" to json.getValue("length"),
            "rows" to kotlinx.serialization.json.JsonArray(kept.rows.map { row ->
                JsonObject(row.json() + linkedMapOf("far" to JsonPrimitive(LyricsSearchCommands.far(row, kept.length)),
                                                    "facts" to JsonPrimitive(LyricsSearchCommands.rowFacts(row, kept.length))))
            }),
            "said" to json.getValue("said"), "asked" to asked, "state" to json.getValue("state"),
            "instrumental" to json.getValue("instrumental"), "pickable" to JsonPrimitive(true),
            "notes" to kotlinx.serialization.json.JsonArray(LyricsSearchCommands.notes(kept).map { n ->
                JsonObject(linkedMapOf("site" to JsonPrimitive(n.site), "state" to JsonPrimitive(n.state),
                                       "line" to JsonPrimitive(n.line)))
            }),
            "line" to JsonPrimitive(LyricsSearchCommands.lastLine(kept)),
        ))
    }

    @Suppress("FunctionName")
    private fun JsonArrayOf() = kotlinx.serialization.json.JsonArray(emptyList())

    /** lyrics_routes.pick (POST /lyrics/pick). */
    private fun pick(request: Request, form: Map<String, String>): Response {
        val record = Py.strip(form["record"].orEmpty())
        val now = clock()
        val (song, row) = parts.database.read { db ->
            val s = song(db, form)
            s to LyricsSearchCommands.keptSearch(db, s.id, now)?.let { LyricsSearchCommands.rowOf(it, record) }
        }
        if (row == null) throw Refused(409, "Search again", SEARCH_AGAIN)
        if (!parts.config().provider(row.site).enabled) {
            throw Refused(409, "Turned off", "${LookupWords.name(row.site)} is off (caracole.toml): nothing picked.")
        }
        val spec = LookupForms.spec("Lyrics for ${song.display}", JobCommands.LYRICS_PICK + song.key,
                                    JobCommands.lyricsPickSteps(song.display, record), display = song.display)
            .copy(join = false)
        val (job, new) = parts.queue.submitOrRefuse(spec, JobQueue.QUEUE_FULL)
        val onItsWay = option(job, "--record=", "--pick=")
        if (!new && onItsWay != record) {
            throw Refused(409, "On its way", "A pick of this song is on its way: $onItsWay. Pick another once it is over.")
        }
        return Answers.queued(LookupForms.view(parts.database, parts.queue, parts.cards, job, now))
    }

    /** lyrics_routes.clear (POST /lyrics/clear). */
    private fun clear(form: Map<String, String>): Response {
        val now = clock()
        val song = parts.database.read { db ->
            song(db, form).also { s ->
                if (Lyrics.pickedRecord(s, LookupForms.overrides(db).lyrics) == null) {
                    throw Refused(409, "Nothing to clear", "${s.display} ${LyricsPickCommands.NOTHING_TO_CLEAR}")
                }
            }
        }
        val spec = LookupForms.spec("Clear the lyrics record: ${song.display}", JobCommands.LYRICS_CLEAR + song.key,
                                    JobCommands.lyricsClearSteps(song.display), display = song.display).copy(join = false)
        val (job, _) = parts.queue.submitOrRefuse(spec, JobQueue.QUEUE_FULL)
        return Answers.queued(LookupForms.view(parts.database, parts.queue, parts.cards, job, now))
    }

    companion object {
        /** lyrics_routes.NAME_MOST. */
        const val NAME_MOST = 200
        const val WHICH_NAME = "Which name? An artist and a title, 1 to $NAME_MOST characters each."
        const val SEARCH_AGAIN = "Search again: that record isn't among its last search's, or the search is over a week old."

    }
}
