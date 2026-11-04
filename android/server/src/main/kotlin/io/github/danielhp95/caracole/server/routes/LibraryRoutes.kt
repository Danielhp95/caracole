package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.NamedSong
import io.github.danielhp95.caracole.server.routes.library.RemovalQuestion
import io.github.danielhp95.caracole.server.routes.library.SongForm
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A song added to the phone's library, and one removed, from the library page's forms (library_routes.py's
 * `/request`, remove_routes.py's `/remove`, on the phone):
 *
 *     POST /request   a song for the library, its `artist` and `title` (or one text, `q`, read as song_names.py
 *                     reads it), with its album and length: added (LibraryStore.add) as an `add` job under its
 *                     identity key; with `fetch` (Fetch now), looked up now instead, `caracole get --progress`, which
 *                     adds it (LookupForms.fetchNow: with the LaCuerda song or version it picked); with `youtube`,
 *                     refused (not on the phone yet)
 *     POST /remove    what removing a song takes ({removal: {song, key, display, brief, goes, stays, notes}}, its
 *                     data; the message page to a browser without the script); with `confirm` and the song's `key`,
 *                     the removal queued under `remove:<key>` (LibraryStore.remove: a tombstone, so the song stays
 *                     removed until asked for again), then back to the library at its card
 *
 * Get it on a search's line (`/lookup`) is LookupRoutes'. A song the library has already is never written to: its
 * record stays as it is, as `caracole add` leaves a song whose wanted.txt line is there already; its job is still an
 * add's, the song named as the library names it. A new song's names are those wanted.txt's line would hold
 * (wanted._clean). Every write runs in its job, inside Database.write; the job names the song it added once added
 * (JobContext.song), so /jobs.json gives a job over its song's card ([cards]: JobsRoutes draws it; an answer here is
 * the job just queued, which has none, as app.job_view gives none). Of the site picks a form may carry, a request
 * reads the LaCuerda song or version alone (library_routes.lacuerda_field), which Fetch now's lookup asks for and an
 * add keeps no further; the others it never reads. A full queue is refused, 503, nothing written.
 */
class LibraryRoutes(val store: LibraryStore, val queue: JobQueue, val cards: SongCards, val database: Database) :
    RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/request", "a song for the library", post = PostAnswer { _, form -> request(form) }),
        Route("POST", "/remove", "a song removed", post = PostAnswer { _, form -> remove(form) }),
    )

    private fun request(form: Map<String, String>): Response {
        val named = SongForm.named(database, form)
        if (PyText.strip(named["youtube"].orEmpty()).isNotEmpty()) {
            throw Refused(409, "Not on the phone yet", "A sheet from a YouTube video isn't on the phone yet.")
        }
        val lacuerda = LookupForms.lacuerdaField(named)
        val song = SongForm.song(named, picks = false)
        if (named["fetch"] in FETCH) {  // `caracole get` adds the song itself
            val ask = LookupForms.fetchNow(song, lacuerda)
            return Answers.queued(view(queue.submitOrRefuse(ask.spec, ask.full).first))
        }
        val found = database.read { Songs.byKey(it, song.key) }
        val display = found?.let { "${it.artist} - ${it.title}" } ?: song.display
        return Answers.queued(view(add(song, found, "Add $display", display)))
    }

    /** The view of a job just queued, its song the one the library has of its key (jobs_routes.song_of). */
    private fun view(job: Job): JsonObject {
        val ahead = if (job.state == Job.QUEUED) queue.ahead(job) else 0
        val song = database.read { Songs.byKey(it, job.spec.key.removePrefix(REMOVING)) }
        return JobViews.view(job, ahead, song?.id ?: job.songId)
    }

    /**
     * [song] added as an `add` job under its key: [found], the song the library has of it (nothing written to it),
     * else a new one. Inside the job's write the library is looked at again, so a song another job added meanwhile is
     * never written to either.
     */
    private fun add(song: NamedSong, found: SongRow?, title: String, display: String): Job {
        val key = found?.key ?: song.key
        return queue.submitOrRefuse(JobSpec(
            title = title, key = key, kind = "add", stages = listOf(ADD to "Adding to the library"),
            display = display, songId = found?.id,
            run = { context ->
                context.stage(ADD, "running")
                val (added, new) = database.write { db ->
                    store.ensureCurrentKeys(db)
                    val have = found?.let { Songs.byId(db, it.id) } ?: Songs.byKey(db, key)
                    when {
                        have != null -> have to false
                        found != null -> throw IllegalStateException(NO_SUCH_SONG)  // removed since it was asked for
                        else -> store.add(db, song.artist, song.title, album = song.album, durationMs = song.durationMs,
                                          now = Answers.now()) to true
                    }
                }
                context.song(added.id, added.display)
                context.stage(ADD, "done", if (new) "" else "In your library as ${added.display}.")
            },
        ), FULL).first
    }

    private fun remove(form: Map<String, String>): Response {
        val id = PyText.strip(form["song"].orEmpty()).toLongOrNull()
            ?: throw Refused(400, "Not a song", "Which song? The form names none.")
        val confirmed = form["confirm"] == "1"
        val back = back(form["back"].orEmpty())
        val (song, question) = database.read { db ->
            val song = Songs.byId(db, id)
                ?: throw Refused(404, "No such song", "That song isn't in the library: removed already, maybe.")
            song to if (confirmed) null else RemovalQuestion.data(db, song)
        }
        if (question != null) {
            val brief = ((question["removal"] as JsonObject)["brief"] as JsonPrimitive).content
            return MessagePage.page(200, "Remove ${song.display}?", "$brief ${RemovalQuestion.AFTER}")
                .also { it.data = question }
        }
        if (form["key"] != song.key) {
            throw Refused(409, "Not that song", "The library changed since this page was made, so nothing was removed: " +
                                                "reload the library and try again.")
        }
        val job = queue.submitOrRefuse(removal(song)).first
        return Answers.queued(JobViews.view(job, queue), libraryAt(back, song.id))
    }

    private fun removal(song: SongRow) = JobSpec(
        title = "Remove ${song.display}", key = REMOVING + song.key, kind = "remove",
        stages = listOf(REMOVE to "Removing from caracole"), display = song.display, songId = song.id,
        run = { context ->
            context.stage(REMOVE, "running")
            val gone = database.write { db -> store.remove(db, song.key, Answers.now()) }
            context.stage(REMOVE, "done", if (gone == null) "It was gone already." else "")
        },
    )

    companion object {
        /** A removal's job key: the song's after it, so it never joins the song's add, nor an add it (jobs.REMOVING). */
        const val REMOVING = "remove:"
        const val ADD = "add"
        const val REMOVE = "remove"

        /** A full queue's words: nothing was added (app.py's QUEUE_FULL, for a request that wrote nothing yet). */
        const val FULL = "The queue is full, so nothing was added: ask for the song again once the queue empties."
        const val NO_SUCH_SONG = "That song isn't in the library."

        private val FETCH = setOf("1", "on", "yes")

        /** The library page's own address after # (URLSearchParams' characters alone). */
        private val BACK = Regex("[A-Za-z0-9%*._~+=&-]{0,512}")

        /** remove_routes._back: the library page's address after # a form sends along, without `song=`; "" else. */
        fun back(text: String): String {
            val address = text.removePrefix("#")
            if (!BACK.matches(address)) return ""
            return address.split('&').filter { it.isNotEmpty() && !it.startsWith("song=") }.joinToString("&")
        }

        /** remove_routes._library_at: the library page as [back] left it, at a song's card. */
        fun libraryAt(back: String, song: Long): String = if (back.isNotEmpty()) "/#$back&song=$song" else "/#song=$song"
    }
}
