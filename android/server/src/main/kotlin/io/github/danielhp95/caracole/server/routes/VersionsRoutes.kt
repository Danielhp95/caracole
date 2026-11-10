package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.pages.Choices
import io.github.danielhp95.caracole.server.pages.VersionsAsked
import io.github.danielhp95.caracole.server.pages.VersionsPage
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import java.time.Instant

/**
 * A sheet's versions chosen on the phone (web/versions_routes.py), each a job of the phone's `versions` runner
 * (VersionsRunner) under the song's key, as caracole serve queues it, so the song's card shows it and its jobs join
 * (web/jobs.py's `_pick`: a version made the one or kept, or the pin taken out, is a pick of the song's as a lookup's
 * `--tab` is):
 *
 *     GET  /versions?sheet=&tab=&do=   the version (`sheet`: the library path of the viewer it was asked from; `tab`:
 *                           its UG tab; `do`: choose, keep or clear) with the one form that does it, then, with
 *                           `&job=`, how it goes and a link to what it made (VersionsPage)
 *     POST /versions/choose  Make this the one: `caracole versions --choose --progress` (`caracole get --tab` with the
 *                           tab's own page, recorded under `[pin]`), and back to the versions page
 *     POST /versions/keep    Keep it: `caracole versions --keep --progress` (one tab page, at the lookup pace)
 *     POST /versions/clear   Back to caracole's pick: `caracole versions --clear --progress`, for a song with a
 *                           `[pin]` that chooses its sheet
 *
 * A sheet viewer runs in a sandbox, with no way to post a form, so its switcher links `GET /versions?…`, a top-level
 * navigation that carries the launch's cookie: a page of the server's own with no script, whose form posts with the
 * form token ([csrf]). A post names its song by the viewer it came from (`sheet`), or by its id (`song`), as the
 * library page's card posts it; one by `sheet` goes to the versions page that shows how it goes, one by `song` to its
 * line in the Requests tab (or its job to the page's script). Fetch them, `POST /versions/keep-more`, is LookupRoutes'.
 * Every refusal is versions_routes.py's, in its words; the phone writes no overrides itself: the runner does.
 * vectors/web/versions_routes.jsonl holds each page and post to caracole serve's (ChoicesReplay). [jobOf] is the
 * queue's job by its id (a test's stand-in), [clock] the time a job's view is read at.
 */
class VersionsRoutes(val parts: PhoneParts, private val csrf: String,
                     private val jobOf: (Int) -> Job? = parts.queue::job,
                     private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/versions", "a sheet's version (sheet, tab, do), and how its request goes (job)",
              get = GetAnswer { page(it.target) }),
    ) + VersionsPage.DOINGS.map { doing ->
        Route("POST", "/versions/$doing", "a sheet's version: ${WHAT.getValue(doing)} (sheet or song, tab)",
              page = "the version's page", post = PostAnswer { _, form -> post(doing, form) })
    }

    private fun name(): LibraryName = LibraryName.phone(parts.config().libraryName)

    /** versions_page: the page of `GET /versions?…`. */
    private fun page(target: String): Response {
        val params = Choices.query(target)
        val doing = params["do"].orEmpty()
        if (doing !in VersionsPage.DOINGS) {
            throw Refused(400, "Not a version", "Make this the one, Keep it or Back to caracole's pick? The address " +
                                                "names none.")
        }
        val asked = params["job"]
        if (asked != null && !Choices.digits(asked, 11)) throw Choices.NOT_AN_ADDRESS
        val rank = parts.config().rank
        return parts.database.read { db ->
            val what = VersionsPage.asked(db, { LookupForms.overrides(db) }, rank, params["sheet"].orEmpty(),
                                          params["tab"].orEmpty(), doing)
            val job = Choices.job(asked, jobOf)?.takeIf {
                it.key == what.song.key && VersionsPage.runs(it, VersionsPage.steps(doing, what))
            }  // another request's: not this page's to show
            VersionsPage.page(db, doing, what, job, csrf, name())
        }
    }

    /** versions_post: the command queued, and the page that shows how it goes (a post by song: as the library page's
     * requests go). */
    private fun post(doing: String, form: Map<String, String>): Response {
        val bySong = Py.strip(form["song"].orEmpty()).isNotEmpty()
        val rank = parts.config().rank
        val tab = form["tab"].orEmpty()
        val asked: VersionsAsked = parts.database.read { db ->
            if (bySong) {
                VersionsPage.aTab(tab, doing)
                val id = LookupForms.songId(form.getValue("song"))
                val overrides = LookupForms.overrides(db)
                VersionsPage.askedSong(db, overrides, rank, LookupForms.song(db, id), tab, doing)
            } else {
                VersionsPage.asked(db, { LookupForms.overrides(db) }, rank, form["sheet"].orEmpty(), tab, doing)
            }
        }
        VersionsPage.cant(doing, asked)?.let { throw Refused(409, "Nothing to do", it) }
        LookupForms.notIgnored(asked.song, parts.database.read { db -> LookupForms.overrides(db) })
        val song = asked.song
        val spec = LookupForms.spec(VersionsPage.title(doing, song), song.key, VersionsPage.steps(doing, asked),
                                    display = song.display, fetching = true)
        val job = parts.queue.submitOrRefuse(spec).first
        val view = LookupForms.view(parts.database, parts.queue, parts.cards, job, clock())
        if (bySong) return Answers.queued(view)
        return Answers.queued(view, "/versions?" + VersionsPage.query(doing, asked, job.id))
    }

    private companion object {
        val WHAT = mapOf("choose" to "made the one", "keep" to "kept beside the sheet",
                         "clear" to "back to caracole's pick")
    }
}
