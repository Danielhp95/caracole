package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.SongFacts
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupAsk
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * The library page's lookups on the phone, each a lookup command queued as caracole serve queues it (search_routes.py's
 * `/lookup`, `/lacuerda/artist`, `/lacuerda/search` and `/harptabs/artist`; library_routes.py's `/fetch`;
 * versions_routes.py's Fetch them), run by the phone's own runners (`get`, `lacuerda`, `harptabs`, `versions`: the
 * lookup lane's), at the lookup pace and within a lookup's budgets, through the sites the app's transport reaches:
 *
 *     POST /lookup              Get it on a search's line: the song as the library has it (`song`, its id; or the one
 *                               its UG pick or its names are) or a new one, which its `caracole get` adds; its picks
 *                               (`ug`, `tab`, `lacuerda`, `harptabs`, `gametabs`) on the command line. To the page's
 *                               script, 202 {job, url: /api/jobs/N, view}; to a form, the request's line in the
 *                               Requests tab (status.details_href: the phone has no /lookup page)
 *     POST /fetch               Fetch now on a song's card (`song`): unless it is ignored or needs review first
 *     POST /lacuerda/artist     an artist's Songs: a LaCuerda artist's page read (`slug`, or a `name` under a letter
 *                               not read yet), a job of no song's under `lacuerda-artist:`
 *     POST /lacuerda/search     LaCuerda's own search (`q`; `by_hand`: the button, Enter, else `--auto`), as its gate
 *                               allows (LaCuerdaSearch.gate at the phone's clock), under `lacuerda-search:` and the
 *                               query's key, so never twice for a query while one waits or runs
 *     POST /harptabs/artist     a harptabs.com artist's page read (`path`), under `harptabs-artist:`
 *     POST /versions/keep-more  Fetch them on a song's card (`song`): its UG versions not kept yet, as many as a
 *                               lookup may
 *
 * The forms are read as caracole serve reads them, its refusals in its words ([LookupForms]); a full queue is refused,
 * 503, nothing queued (a song new to the library added nowhere). `/request`'s Fetch now is LibraryRoutes', queued the
 * same way. A site's index read answers {job, url} to the page's script and the request's line to a form; Fetch now and
 * Fetch them answer as the library's forms do (App.queued: the job's view, or its line). Once a job is over the phone
 * forgets the search's answers (Phone.afterJob), so the next search finds what it added. vectors/web/lookup_routes.jsonl
 * holds each route to caracole serve's answers (LookupRoutesReplay).
 */
class LookupRoutes(val parts: PhoneParts, private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/lookup", "a song looked up now (Get it)", page = "the page",
              post = PostAnswer { request, form -> lookup(request, form) }),
        Route("POST", "/fetch", "a song fetched now (song)",
              post = PostAnswer { _, form -> queued(LookupForms.fetch(parts.database, form)) }),
        Route("POST", "/lacuerda/artist", "a LaCuerda artist's page read (slug, or name)", page = "the page",
              post = PostAnswer { request, form -> read(request, LookupForms.lacuerdaRead(parts.database, form)) }),
        Route("POST", "/lacuerda/search", "LaCuerda's own search (q, by_hand)", page = "the page",
              post = PostAnswer { request, form ->
                  read(request, LookupForms.lacuerdaSearch(parts.database, parts.config(), form, parts.searchesLacuerda,
                                                           clock()))
              }),
        Route("POST", "/harptabs/artist", "a harptabs.com artist's page read (path)", page = "the page",
              post = PostAnswer { request, form -> read(request, LookupForms.harptabsRead(parts.database, form)) }),
        Route("POST", "/versions/keep-more", "a song's UG versions kept, as many as a lookup may (song)",
              post = PostAnswer { _, form -> queued(LookupForms.keepMore(parts.database, parts.config(), form)) }),
    )

    /** search_routes.lookup: the lookup queued; to the page's script its job, address and view, else its line. */
    private fun lookup(request: Request, form: Map<String, String>): Response {
        val job = submit(LookupForms.lookupRequest(parts.database, form))
        if (!wantsJson(request)) return line(job)
        return Answers.json(JsonObject(linkedMapOf(
            "job" to JsonPrimitive(job.id), "url" to JsonPrimitive("/api/jobs/${job.id}"), "view" to view(job),
        )), 202)
    }

    /** A site's index read queued: to the page's script its job and address, else its line. */
    private fun read(request: Request, ask: LookupAsk): Response {
        val job = submit(ask)
        if (!wantsJson(request)) return line(job)
        return Answers.json(JsonObject(linkedMapOf(
            "job" to JsonPrimitive(job.id), "url" to JsonPrimitive("/api/jobs/${job.id}"),
        )), 202)
    }

    /** App.queued: the job's view to the page's script, else its line. */
    private fun queued(ask: LookupAsk): Response = Answers.queued(view(submit(ask)))

    private fun submit(ask: LookupAsk): Job = parts.queue.submitOrRefuse(ask.spec, ask.full).first

    /** The request's line in the Requests tab (status.details_href). */
    private fun line(job: Job): Response =
        Response(303, Body.Empty, mutableListOf("Location" to "/${Status.detailsHref(job.id)}"))

    /** WebApp.job_view: a job just queued, as /jobs.json gives it, its song as the library has it now. */
    private fun view(job: Job): JsonObject {
        val ahead = if (job.state == Job.QUEUED) parts.queue.ahead(job) else 0
        val (songId, facts) = parts.database.read { db -> SongFacts.songOf(db, job, parts.cards, clock()) }
        return JobViews.view(job, ahead, songId, facts = facts)
    }

    private fun wantsJson(request: Request): Boolean =
        "application/json" in PyText.lower(request.headers["accept"].orEmpty())
}
