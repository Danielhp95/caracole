package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
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
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.routes.library.Answers
import kotlinx.serialization.json.JsonElement
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

    /** Every request, as the Requests tab draws it: the one that runs and those queued, then the finished ones; what
     * each command printed only for the requests the tab has opened ([open]: `?open=N,M`). */
    private fun requestsJson(open: String?): Response {
        val opened = JobsRoutes.jobIds(open) ?: emptySet()
        val jobs = queue.snapshot()
        // waiting on job-views: each job's line with what the library knows of its song (Status, SongFacts), the
        // running one's chips and each finished one's outcome (Outcomes), and the songs that wait for a pick.
        val lines = jobs.associate { job -> job.id to JobViews.line(job, ahead(jobs, job)) }
        return json(Feed.feed(jobs, lines, opened = opened, now = clock(), zone = zone()))
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
        return Answers.queued(JobViews.view(queued, queue), "/${JobViews.REQUESTS}")
    }

    /** The request a form names (`job`): plain digits, twelve at most; Refused (400) when it names none; null for a
     * number no request can have. */
    private fun formJob(form: Map<String, String>): Int? {
        val text = PyText.strip(form["job"] ?: "")
        if (text.isEmpty() || text.any { it !in '0'..'9' } || text.length > 12) {
            throw Refused(400, "Not a request", "Which request? The form names none.")
        }
        return text.toLong().takeIf { it <= Int.MAX_VALUE }?.toInt()
    }

    private fun gone() = Refused(404, "No such request", "caracole serve no longer remembers that request: ask for " +
                                                         "it again from the library.")

    private fun notOver() = Refused(409, "Not over yet", "That request is still queued or running.")

    /** How many jobs wait or run before a queued one (jobs_routes._ahead). */
    private fun ahead(jobs: List<Job>, job: Job): Int = jobs.count { it.active && it.id < job.id }

    private fun json(data: JsonElement) = Response(
        200, Body.Bytes(PyJson.dumps(data, compact = true).toByteArray()),
        mutableListOf("Content-Type" to "application/json; charset=utf-8"),
    )

    companion object {
        /** Why a request of the phone's own read back from the history can't be tried again (the phone's words:
         * caracole serve's requests are all commands, which it always can). */
        const val NOT_REPEATABLE = "The phone ran that request itself, and there's nothing of it left to run again: " +
            "ask for it again from the library."
    }
}
