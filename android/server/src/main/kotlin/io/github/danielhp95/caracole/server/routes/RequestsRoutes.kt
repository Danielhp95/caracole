package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.DatabaseTooNew
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.isSqliteError
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Feed
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobNotOver
import io.github.danielhp95.caracole.server.jobs.JobNotRepeatable
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.JobsRoutes
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.jobs.SongFacts
import io.github.danielhp95.caracole.server.routes.library.Answers
import kotlinx.serialization.json.JsonObject
import java.io.IOException
import java.time.Instant
import java.time.ZoneId

/**
 * The Requests tab on the phone (jobs_routes.py's `/requests.json` and Try again, lane requests-feed):
 *
 *     GET  /requests.json   every request, as the library page's Requests tab draws it (Feed), for the page's script
 *                           alone (?open=N,M: those requests' output with what each command printed)
 *     POST /jobs/again      a request that is over (`job`), its commands queued again: Try again
 *
 * Try again queues a request over again as JobQueue.again does it (jobs_routes.again's rules: a LaCuerda search the
 * page sent by itself asked by hand now, a lookup Get the missing songs queued made with its songbooks, a pick's
 * review never joined), a song's request that waits or runs being the answer; back to the Requests tab, or to the
 * page's script its view. A request the phone ran itself and remembers nothing of to run (one of its own read back
 * from the history) is refused: there is nothing to queue again.
 *
 * Times are the phone's: [clock], and [zone], whose days Today and Earlier are and whose clock the tab's times are on.
 */
class RequestsRoutes(val parts: PhoneParts, val clock: () -> Instant = { Instant.now() },
                     val zone: () -> ZoneId = { ZoneId.systemDefault() }) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/requests.json", "the Requests tab's requests, for the page's script (open)", scriptOnly = true,
              get = GetAnswer { request -> requestsJson(PyUrl.query(request.target)["open"]) }),
        Route("POST", "/jobs/again", "a request over queued again (job)",
              post = PostAnswer { _, form -> again(form) }),
    )

    private val queue: JobQueue get() = parts.queue

    /** What each job over came to, worked out once: the queue's, which /jobs.json's views share (SongFacts.ended). */
    private val ended = SongFacts.ended(queue)

    /**
     * Every request, as the Requests tab draws it (jobs_routes.requests_json): the one that runs and those queued,
     * then the finished ones, each with its outcome and its next step; what each command printed only for the requests
     * the tab has opened ([open]: `?open=N,M`). Each job's line is the one /jobs.json gives it (JobViews.line: its
     * song's facts, a songbook's page), the running one's chips and each finished one's outcome are Outcomes', and a
     * song a finished request waits for a pick of is [picksWaiting]'s. The database unreadable, the lines say only how
     * the jobs went; a bug is the request's error, as caracole serve's.
     */
    private fun requestsJson(open: String?): Response {
        val opened = JobsRoutes.jobIds(open) ?: emptySet()
        val jobs = queue.snapshot()
        val now = clock()
        var songs: Map<Int, Pair<Long?, SongFacts?>> = emptyMap()
        var books: Map<Int, String?> = emptyMap()
        try {
            parts.database.read { db ->
                ended.forget(jobs)
                songs = jobs.associate { it.id to ended.songOf(db, it, parts.cards, now) }
                books = jobs.associate { it.id to JobsRoutes.songbookPage(db, it) }
            }
        } catch (e: Exception) {  // the lines say only how the jobs went, then (what was read before it, as Python's)
            if (!unreadable(e)) throw e
        }
        val facts = songs.mapValues { it.value.second }
        val lines = jobs.associate { job ->
            job.id to JobViews.line(job, ahead(jobs, job), facts[job.id], songbookPage = books[job.id])
        }
        val outcomes = jobs.filter { !it.active }.associate { job ->
            job.id to Outcomes.outcome(job, lines.getValue(job.id), facts[job.id], songs[job.id]?.first)
        }
        val steps = jobs.filter { it.state == Job.RUNNING }.associate { job -> job.id to Outcomes.steps(job, facts[job.id]) }
        return Answers.json(Feed.feed(jobs, lines, outcomes, steps, picksWaiting(jobs), opened, now, zone()))
    }

    /**
     * review_routes.picks_waiting on the phone: the songs of finished requests that wait for a pick now, by the
     * request's key, as review_routes._offer offers them: a song in review with candidates to pick from (not one
     * ignored); a song the offline index didn't match, whose pick is what `caracole search` finds (`search`). Read on
     * its own, as caracole serve reads it: none when the database can't be read, the Requests tab showing the requests
     * all the same.
     */
    private fun picksWaiting(jobs: List<Job>): Map<String, Feed.Pick> {
        val keys = jobs.filter { !it.active }.map { it.key }.toSortedSet()
        if (keys.isEmpty()) return emptyMap()
        return try {
            parts.database.read { db ->
                val picks = LinkedHashMap<String, Feed.Pick>()
                for (key in keys) {
                    val song = Songs.byKey(db, key) ?: continue
                    offer(db, song)?.let { picks[key] = it }
                }
                picks
            }
        } catch (e: Exception) {
            if (!unreadable(e)) throw e
            emptyMap()
        }
    }

    private fun offer(db: Db, song: SongRow): Feed.Pick? {
        if (song.status == "ignored" || "ignore" in OverridesStore.songEntries(db, song.key)) return null
        if (song.review) return if (SongFacts.hasCandidates(song)) Feed.Pick(song.id) else null
        if (song.matchDecision != "not_found") return null
        return Feed.Pick(song.id, search = true)
    }

    /** A request that is over, its commands queued again as a new request (Try again); back to the Requests tab. */
    private fun again(form: Map<String, String>): Response {
        val id = formJob(form)
        val job = id?.let(queue::job) ?: throw gone()
        if (job.active) throw notOver()
        val queued = try {
            queue.again(job.id)
        } catch (e: NoSuchElementException) {
            throw gone()
        } catch (e: JobNotOver) {
            throw notOver()
        } catch (e: JobNotRepeatable) {
            throw Refused(409, "Nothing to run again", NOT_REPEATABLE)
        } catch (e: QueueFull) {
            throw Refused(503, "The queue is full", JobQueue.QUEUE_FULL)
        }
        return Answers.queued(view(queue.job(queued.id) ?: queued), "/${JobViews.REQUESTS}")
    }

    /** A job just queued, as /jobs.json gives it to the library page's script (WebApp.job_view, the queue's copy of
     * it now: one the worker has started already runs): its song as the library has it now; the job alone when the
     * database can't be read. */
    private fun view(job: Job): JsonObject = try {
        parts.database.read { db ->
            val (songId, facts) = ended.songOf(db, job, parts.cards, clock())
            JobViews.view(job, if (job.state == Job.QUEUED) queue.ahead(job) else 0, songId, facts = facts,
                          songbookPage = JobsRoutes.songbookPage(db, job))
        }
    } catch (e: Exception) {
        if (!unreadable(e)) throw e
        JobViews.view(job, queue)  // the job is queued all the same
    }

    /** The request a form names (`job`): plain digits, twelve at most; Refused (400) when it names none; null for a
     * number no request can have. */
    private fun formJob(form: Map<String, String>): Int? {
        val text = PyText.strip(form["job"] ?: "")
        if (text.isEmpty() || text.any { it !in '0'..'9' } || text.length > 12) {
            throw Refused(400, "Not a request", "Which entry? The form names none.")
        }
        return text.toLong().takeIf { it <= Int.MAX_VALUE }?.toInt()
    }

    private fun gone() = Refused(404, "No such request", "We no longer remember that request. Ask again from the " +
                                                         "logbook.")

    private fun notOver() = Refused(409, "Not over yet", "Still queued or running.")

    /** How many jobs wait or run before a queued one (jobs_routes._ahead). */
    private fun ahead(jobs: List<Job>, job: Job): Int = jobs.count { it.active && it.id < job.id }

    companion object {
        /** Python's `(sqlite3.Error, OSError)`, which caracole serve's routes catch reading the library: the bundled
         * SQLite's own error (isSqliteError), a database too new, or a file that can't be read. Anything else is a
         * bug, the request's error. */
        internal fun unreadable(e: Throwable): Boolean = e.isSqliteError() || e is IOException || e is DatabaseTooNew

        /** Why a request of the phone's own read back from the history can't be tried again (the phone's words:
         * caracole serve's requests are all commands, which it always can). */
        const val NOT_REPEATABLE = "The phone ran that itself: nothing left to run again. Ask again from the logbook."
    }
}
