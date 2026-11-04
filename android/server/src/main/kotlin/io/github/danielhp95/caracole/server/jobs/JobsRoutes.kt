package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * jobs_routes.py on the phone: the requests, as the library page's script follows them.
 *
 *     GET  /jobs.json      the requests, a view each (JobViews), for the page's script alone (the token header:
 *                          App's script-only check); ?jobs=N,M: only those, each over with its song's card
 *     GET  /api/jobs/N     one request as data (Job.asJson; a site's index read with its line, which says what the
 *                          site answered), or 404
 *     POST /jobs/cancel    a request that hasn't started (`job`), taken out of the queue: never one that runs, nor
 *                          one that is over
 *
 * Each job names its song as the library has it now, with what its line needs to know of it (SongFacts.songOf,
 * jobs_routes.song_of): an add's, a lookup's and a removal's by its key, a removal done by the song it removed, Make
 * this my version's by its id and as none of the song's requests. A job that is over doesn't change, so its answer is
 * worked out once and kept while the queue remembers the job (jobs_routes' `_ended`: SongFacts.ended, the queue's,
 * which the Requests tab's feed reads too). A songbook's change that is
 * done links its songbook's page while the phone has written one ([songbookPage]: kv `songbook:<folder>`'s
 * songbook.html, songbooks.songbook_page). A job over that the page asks about by its id gets the Songbooks tab's
 * data as it is now ([songbooks], when one is given; never for a site's index read) and its song's card as the page
 * draws it now ([cards]), with `fetchable` (false for a song a review must come first for), while the song is there.
 */
class JobsRoutes(val queue: JobQueue, val cards: SongCards, val database: Database,
                 val clock: () -> Instant = { Instant.now() }, val songbooks: ((Db) -> JsonObject?)? = null) :
    RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/jobs.json", "the requests, for the page's script", scriptOnly = true,
              get = GetAnswer { request -> jobsJson(PyUrl.query(request.target)["jobs"]) }),
        Route("GET", "/api/jobs/", "one request as data", under = true, get = GetAnswer { request ->
            apiJob(PyUrl.unquote(PyUrl.urlsplit(request.target).path).removePrefix("/api/jobs/"))
        }),
        Route("POST", "/jobs/cancel", "a request taken out of the queue",
              post = PostAnswer { _, form -> cancel(form) }),
    )

    /** What each job over came to (its song's id and facts), worked out once: the queue's, which the Requests tab's
     * feed shares (SongFacts.ended). */
    private val ended = SongFacts.ended(queue)

    /** The requests for the page's script: every one, or those [asked] names, each over with its song's card. */
    private fun jobsJson(asked: String?): Response {
        val ids = jobIds(asked)
        val jobs = queue.snapshot()
        val only = if (ids == null) jobs else jobs.filter { it.id in ids }
        val shown = database.read { db ->
            ended.forget(jobs)
            var section: JsonObject? = null  // read once, for every job that asks
            only.map { job ->
                val (songId, facts) = songOf(db, job)
                val over = ids != null && job.id in ids && !job.active
                val read = JobCommands.INDEX_READS.any(job.key::startsWith)
                if (over && !read) section = section ?: songbooks?.invoke(db)
                val song = if (over && songId != null) Songs.byId(db, songId) else null
                val card = song?.let { cardOf(db, it) }
                val ahead = if (job.state == Job.QUEUED) jobs.count { it.active && it.id < job.id } else 0
                JobViews.view(job, ahead, songId, card = card, songbooks = if (over && !read) section else null,
                              facts = facts, songbookPage = songbookPage(db, job))
            }
        }
        return json(200, JsonObject(linkedMapOf(
            "active" to JsonPrimitive(jobs.count { it.active }),
            "jobs" to JsonArray(shown),
        )))
    }

    /** The job's song and what the library knows of it now (SongFacts.songOf), kept once the job is over. */
    private fun songOf(db: Db, job: Job): Pair<Long?, SongFacts?> = ended.songOf(db, job, cards, clock())

    /** The song's card as the page draws it now, with `fetchable` as the page's own cards have it. */
    private fun cardOf(db: Db, song: SongRow): JsonObject? = cards.cards(db, listOf(song))[song.id]?.let { card ->
        JsonObject(LinkedHashMap(card).apply { put("fetchable", JsonPrimitive(!song.review)) })
    }

    private fun apiJob(number: String): Response {
        val job = (if (digits(number)) idOf(number)?.let(queue::job) else null)
            ?: return json(404, JsonObject(mapOf("error" to JsonPrimitive("no such request"))))
        if (JobCommands.INDEX_READS.any(job.key::startsWith)) {  // no song's: its line says what the site answered
            return json(200, JsonObject(LinkedHashMap(job.asJson()).apply { put("line", JobViews.line(job).asJson()) }))
        }
        return json(200, job.asJson())
    }

    /** A songbook's change that is done: its songbook's page, relative to the library page, while the phone has
     * written one (songbooks.songbook_page: kv `songbook:<folder>`'s songbook.html, as songbook.written_page reads it);
     * null for any other job, a deletion, or a songbook with no page. */
    private fun songbookPage(db: Db, job: Job): String? {
        if (job.state != Job.DONE || job.steps.isEmpty()) return null
        val book = Status.songbookOf(job.key) ?: return null
        val after = book.after ?: return null
        val folder = SafeName.safeName(after)
        val record = db.kvGet("songbook:$folder")?.let {
            try {
                Json.parseToJsonElement(it)
            } catch (e: IllegalArgumentException) {
                null
            }
        } as? JsonObject ?: return null
        val entry = (record["files"] as? JsonObject)?.get("songbook.html") as? JsonObject ?: return null
        val sha = entry["sha256"] as? JsonPrimitive
        val size = entry["size"] as? JsonPrimitive
        if (sha == null || !sha.isString || size == null || size.isString || size.content.toLongOrNull() == null) return null
        return "_songbooks/${PyUrl.quote(folder, safe = "")}/songbook.html"
    }

    /** A request that hasn't started, taken out of the queue (jobs_routes.cancel); back to its tab. */
    private fun cancel(form: Map<String, String>): Response {
        val text = PyText.strip(form["job"] ?: "")
        if (!digits(text) || text.length > 12) {
            throw Refused(400, "Not a request", "Which request? The form names none.")
        }
        val job = try {
            idOf(text)?.let(queue::cancel)
        } catch (e: JobStarted) {
            if (e.state == Job.RUNNING) {
                throw Refused(409, "Running already", "That request has started, and caracole never stops a command " +
                                                      "halfway: it runs to its end.")
            }
            throw Refused(409, "Over already", "That request is over: there's nothing left to cancel.")
        } ?: throw Refused(404, "No such request", "That request isn't queued any more.")
        return Response(303, Body.Empty, mutableListOf("Location" to "/${JobViews.REQUESTS}"),
                        JsonObject(mapOf("cancelled" to JsonPrimitive(job.id))))
    }

    private fun json(status: Int, data: JsonElement) = Response(
        status, Body.Bytes(PyJson.dumps(data, compact = true).toByteArray()),
        mutableListOf("Content-Type" to "application/json; charset=utf-8"),
    )

    companion object {
        const val MAX_ASKED = 50  // jobs one /jobs.json answer is asked about

        /** The jobs `?jobs=N,M` asks about (plain digits only, [MAX_ASKED] at most); null when it asks about none in
         * particular (jobs_routes._job_ids). */
        fun jobIds(value: String?): Set<Int>? {
            if (value == null) return null
            val ids = LinkedHashSet<java.math.BigInteger>()
            for (part in value.split(',')) {
                val number = PyText.strip(part)
                if (digits(number) && ids.size < MAX_ASKED) ids.add(number.toBigInteger())
            }
            return ids.mapNotNull { it.takeIf { id -> id <= MAX_ID }?.toInt() }.toSet()  // a larger one is no job's
        }

        private val MAX_ID = Int.MAX_VALUE.toBigInteger()

        /** str.isascii() and str.isdigit(): plain digits, at least one. */
        private fun digits(text: String): Boolean = text.isNotEmpty() && text.all { it in '0'..'9' }

        /** The job id [text] names; null for a number no job has. */
        private fun idOf(text: String): Int? = text.toBigInteger().takeIf { it <= MAX_ID }?.toInt()
    }
}
