package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.pages.Choices
import io.github.danielhp95.caracole.server.pages.HarmonicaPage
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.core.py.PyUrl
import java.time.Instant

/**
 * A harmonica tab's readings chosen on the phone (web/harmonica_routes.py):
 *
 *     GET  /harmonica?page=&job=   the readings of the tab whose page `page` is (its library path, a
 *                           `harmonica-N.html` the phone wrote), each with a form that pins it; then, with `&job=`,
 *                           how it goes (HarmonicaPage)
 *     POST /harmonica/pin    Read it so: `caracole harmonica --tab=… --as=… [--symbol=…]` queued (`as`: a notation's
 *                           name, "legend", or a table as JSON), and back to the page
 *     POST /harmonica/clear  Back to caracole's guess: `caracole harmonica --tab=… --clear` queued
 *
 * A harmonica tab's page runs in a sandbox, so its Read as line links `GET /harmonica?page=…` (harptab.js, served), a
 * top-level navigation that carries the launch's cookie: a page of the server's own with no script, whose forms post
 * with the form token ([csrf]). Each post is one command, the phone's `harmonica` runner (HarmonicaRunner), queued
 * under a key of its own (jobs.READING, the song's key, the tab and the reading, then jobs.MINE), so it joins no
 * request of the song's, and the same reading asked twice is one job. Every refusal is harmonica_routes.py's, in its
 * words: a page that is no harmonica tab's page the phone wrote for a song of the library (404), a reading that is
 * none (400), the tab read so already or no pin to take out (409), and an ignored song.
 * vectors/web/harmonica_routes.jsonl holds each page and post to caracole serve's (ChoicesReplay). [jobOf] is the
 * queue's job by its id (a test's stand-in), [clock] the time a job's view is read at.
 */
class HarmonicaRoutes(val parts: PhoneParts, private val csrf: String,
                      private val jobOf: (Int) -> Job? = parts.queue::job,
                      private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/harmonica", "$WHAT: the tab's readings (page), and how its request goes (job)",
              get = GetAnswer { page(it.target) }),
        Route("POST", "/harmonica/pin", "$WHAT: a reading pinned (page, as)", page = PAGE,
              post = PostAnswer { _, form -> post("pin", form) }),
        Route("POST", "/harmonica/clear", "$WHAT: back to caracole's guess (page)", page = PAGE,
              post = PostAnswer { _, form -> post("clear", form) }),
    )

    private fun name(): LibraryName = LibraryName.phone(parts.config().libraryName)

    /** harmonica_page: the page of `GET /harmonica?…`. */
    private fun page(target: String): Response {
        val params = Choices.query(target)
        val asked = params["job"]
        if (asked != null && !Choices.digits(asked, 11)) throw Choices.NOT_AN_ADDRESS
        val what = parts.database.read { db ->
            HarmonicaPage.asked(db, { LookupForms.overrides(db) }, parts.store.libraryDir, params["page"].orEmpty())
        }
        val job = Choices.job(asked, jobOf)?.takeIf { HarmonicaPage.ofPage(it, what) }  // another request's
        return HarmonicaPage.page(what, job, csrf, name())
    }

    /** harmonica_post: the command queued, and back to the page, which says how it goes. */
    private fun post(doing: String, form: Map<String, String>): Response {
        val asked = parts.database.read { db ->
            HarmonicaPage.asked(db, { LookupForms.overrides(db) }, parts.store.libraryDir, form["page"].orEmpty())
        }
        val spec = if (doing == "pin") HarmonicaPage.reading(form["as"].orEmpty()) else null
        if (doing == "pin" && spec == asked.pin) {
            throw Refused(409, "Nothing to do", "Read that way already, as you set it.")
        }
        if (doing == "clear" && asked.pin == null) {
            throw Refused(409, "Nothing to do", "We guess its reading already: no [harmonica] entry pins it.")
        }
        LookupForms.notIgnored(asked.song, parts.database.read { db -> LookupForms.overrides(db) })
        val song = asked.song
        val (title, label, options) = HarmonicaPage.command(asked, spec)
        val commands = listOf(Command(label, listOf(HarmonicaPage.COMMAND, "--tab=${asked.tab.name}") + options +
                                             listOf("--", song.artist, song.title)))
        val key = HarmonicaPage.key(asked, spec)
        val job = parts.queue.submitOrRefuse(JobSpec(
            title = title, key = key, kind = JobCommands.kindOf(key, commands.map { it.args }, emptyList()),
            stages = emptyList(), display = song.display, songId = song.id, commands = commands,
        )).first
        val view = LookupForms.view(parts.database, parts.queue, parts.cards, job, clock())
        return Answers.queued(view, "/harmonica?" + PyUrl.urlencode(listOf("page" to asked.page, "job" to job.id.toString())))
    }

    private companion object {
        const val WHAT = "How a harmonica tab is read"
        const val PAGE = "the tab's page of readings"
    }
}
