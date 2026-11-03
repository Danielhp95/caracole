package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.PyText
import io.github.danielhp95.caracole.server.http.PyUrl
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.page.SongCards
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * jobs_routes.py on the phone: the requests, as the library page's script follows them.
 *
 *     GET  /jobs.json      the requests, a view each (JobViews), for the page's script alone (the token header:
 *                          App's script-only check); ?jobs=N,M: only those, each over with its song's card
 *     GET  /api/jobs/N     one request as data (Job.asJson), or 404
 *     POST /jobs/cancel    a request that hasn't started (`job`), taken out of the queue: never one that runs, nor
 *                          one that is over
 *
 * A job over that the page asks about by its id gets its song's card as the page draws it now ([cards]): an add's
 * song, by its key, and a removal's while the song is there still (once removed, the page draws its line gone).
 */
class JobsRoutes(val queue: JobQueue, val cards: SongCards, val database: Database) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/jobs.json", "the requests, for the page's script", scriptOnly = true,
              get = GetAnswer { request -> jobsJson(PyUrl.query(request.target)["jobs"]) }),
        Route("GET", "/api/jobs/", "one request as data", under = true, get = GetAnswer { request ->
            apiJob(PyUrl.unquote(PyUrl.urlsplit(request.target).path).removePrefix("/api/jobs/"))
        }),
        Route("POST", "/jobs/cancel", "a request taken out of the queue",
              post = PostAnswer { _, form -> cancel(form) }),
    )

    /** The requests for the page's script: every one, or those [asked] names, each over with its song's card. */
    private fun jobsJson(asked: String?): Response {
        val ids = jobIds(asked)
        val jobs = queue.snapshot()
        val only = if (ids == null) jobs else jobs.filter { it.id in ids }
        val songs = if (ids == null) emptyMap() else songsOf(only.filter { it.id in ids && !it.active })
        val shown = only.map { job ->
            val song = songs[job.id]
            val card = song?.let { cardOf(it) }
            JobViews.view(job, queue, card = card)
        }
        return json(200, JsonObject(linkedMapOf(
            "active" to JsonPrimitive(jobs.count { it.active }),
            "jobs" to JsonArray(shown),
        )))
    }

    /** The song of each job over, as the library has it now: an add's by its key, a removal's by its id. */
    private fun songsOf(over: List<Job>): Map<Int, SongRow> {
        val asked = over.filter { it.spec.kind == "add" || it.spec.kind == "remove" }
        if (asked.isEmpty()) return emptyMap()
        return database.read { db ->
            asked.mapNotNull { job ->
                val song = when (job.spec.kind) {
                    "add" -> job.songId?.let { Songs.byId(db, it) } ?: Songs.byKey(db, job.spec.key)
                    else -> job.songId?.let { Songs.byId(db, it) }
                }
                song?.let { job.id to it }
            }.toMap()
        }
    }

    private fun cardOf(song: SongRow): JsonObject? = database.read { db -> cards.cards(db, listOf(song))[song.id] }

    private fun apiJob(number: String): Response {
        val job = if (digits(number)) idOf(number)?.let(queue::job) else null
        return if (job == null) json(404, JsonObject(mapOf("error" to JsonPrimitive("no such request"))))
        else json(200, job.asJson())
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
