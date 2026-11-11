package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.server.songbooks.SongbookEntries
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Instant

/**
 * The Songbooks tab's forms and the Select bar's songbook on the phone (web/songbook_routes.py, web/songbooks.py), each
 * queued as its `caracole songbook` command, which the phone's songbook runner runs (SongbookRunner):
 *
 *     POST /songbook/make     name, songs (song ids, in order)   songbook make -- NAME SONG...
 *     POST /songbook/add      name, songs                        songbook add -- NAME SONG...
 *     POST /songbook/move     name, song, position               songbook move -- NAME SONG POSITION
 *     POST /songbook/remove   name, song                         songbook remove -- NAME SONG
 *     POST /songbook/set      name, song, key, mode, capo,       songbook set --key K --mode M --capo N
 *                             instrument (or clear)              --instrument I -- NAME SONG (or --clear)
 *     POST /songbook/rename   name, new                          songbook rename -- NAME NEW
 *     POST /songbook/delete   name                               songbook delete -- NAME
 *     POST /songbook/get      name (and song, one song's id)     get --no-songbooks, for each song without a
 *                                                                sheet (or that one); then songbook render -- NAME
 *     POST /songbook/add-song name, and song (an id), or the     get, for a song the library hasn't got; then
 *                             artist, title, ug, tab and         songbook add -- NAME SONG, both or neither
 *                             lacuerda of a search's result
 *
 * A form is checked here against the songbooks (phone_songbooks) and the library, both only read, so one that can't be
 * done is refused at once in caracole serve's words (a name a songbook can't have, a songbook there isn't, a song the
 * library hasn't got: a song the phone mirrors but hasn't got, a card of a negative id, is one); then it is queued
 * under web/songbooks.py's key (`songbook\u001f` and its command's words; a setting's, its songbook and song before its
 * setting; Get the missing songs' render, the last lookup it follows), so the same change sent twice is queued once.
 * The route writes nothing. A song is the library's "Artist - Title" (`songs`, by the ids of the page's data) or the
 * songbook's own entry (`song`), so a song gone from the library can be moved or taken out too.
 *
 * Get the missing songs queues one lookup a song the library has without a sheet yet, in the songbook's order
 * (SongbookEntries.songsToGet: a song whose pages are the computer's has the [mirror]'s sheet, as the Songbooks tab
 * shows it, so none is asked of a site for it), as many as leave room for the songbook's render after them, then the
 * render; Add a song adds a song of the library at once, and looks a song new to it up first
 * ([LookupForms.lookupRequest], whose `caracole get` adds it: the phone writes no wanted.txt), its lookup and the add
 * queued together (JobQueue.submitAll). To the page's script each answers the songbook job's view (App.queued), with
 * the lookups' views (`jobs`) and how many songs wait for another tap (`left`); to a form, its line in the Requests
 * tab. vectors/songbook/routes.jsonl holds every form to caracole serve's answers, the views too
 * (SongbookRoutesReplay).
 */
class SongbookRoutes(val parts: PhoneParts, private val clock: () -> Instant = Instant::now,
                     private val mirror: () -> Mirror? = { ExportRoutes.mirrorOf(parts.cards) }) : RouteModule {
    override val routes: List<Route> = CHANGES.map { (action, doc) ->
        Route("POST", "/songbook/$action", doc, post = PostAnswer { _, form -> change(action, form) })
    } + listOf(
        Route("POST", GET_MISSING, "a songbook's songs without a sheet looked up now, then the songbook (name, song)",
              post = PostAnswer { _, form -> getMissing(form) }),
        Route("POST", ADD_SONG, "a song put in a songbook from the tab's search, looked up first when new (name, " +
                                "song or its names)",
              post = PostAnswer { _, form -> addSong(form) }),
    )

    // --- the forms ---------------------------------------------------------------------------------------------------

    /** songbook_routes.change: a songbook made or changed, its command queued. */
    private fun change(action: String, form: Map<String, String>): Response {
        val spec = readable { songbookJob(action, form) }
        return queued(parts.queue.submitOrRefuse(spec).first)
    }

    /** songbooks.songbook_job: the job a songbook form asks for; Refused when it can't be done, before anything is
     * queued. */
    private fun songbookJob(action: String, form: Map<String, String>): JobSpec {
        val (asked, books) = named(form)
        if (action == "make") {
            try {
                Songbooks.checkFree(books, asked)
            } catch (e: SongbookError) {
                throw Refused(409, "Taken", e.message.orEmpty())
            }
            val songs = songs(form)
            return job("Make the songbook \"$asked\" (${plural(songs.size, "song")})", "Making the songbook", "make",
                       asked, *songs.toTypedArray())
        }
        val book = book(books, asked)
        val name = book.name
        when (action) {
            "add" -> {
                val songs = songs(form)
                return job("Add ${plural(songs.size, "song")} to \"$name\"", "Adding to the songbook", "add", name,
                           *songs.toTypedArray())
            }
            "move", "remove", "set" -> {
                val song = Py.split(form["song"].orEmpty()).joinToString(" ")
                if (song.isEmpty()) throw Refused(400, "Not a song", "Which song? The form names none.")
                val entry = book.texts.firstOrNull { Songbooks.sameEntry(it, song) }
                    ?: throw Refused(404, "Not in the songbook",
                                     "\"$song\" isn't in the songbook \"$name\": reload the library to see what it holds.")
                if (action == "remove") return job("Take $entry out of \"$name\"", "Taking the song out", "remove", name, entry)
                if (action == "set") return settingJob(name, entry, form)
                val position = PyInt.parse(form["position"].orEmpty()) ?: BigInteger.ZERO
                if (position < BigInteger.ONE || position > BigInteger.valueOf(MAX_POSITION.toLong())) {
                    throw Refused(400, "Not a position", "A position is a whole number from 1, the first song.")
                }
                return job("Move $entry to $position in \"$name\"", "Moving the song", "move", name, entry,
                           position.toString())
            }
            "rename" -> {
                val new = try {
                    Songbooks.checkName(form["new"].orEmpty())
                } catch (e: SongbookError) {
                    throw Refused(400, "Not a name", e.message.orEmpty())
                }
                try {
                    Songbooks.checkFree(books, new, but = book)
                } catch (e: SongbookError) {
                    throw Refused(409, "Taken", e.message.orEmpty())
                }
                return job("Rename \"$name\" to \"$new\"", "Renaming the songbook", "rename", name, new)
            }
            else -> return job("Delete the songbook \"$name\"", "Deleting the songbook", "delete", name)
        }
    }

    /** songbook_routes.get_missing: the songbook's songs without a sheet (with `song`, a set list's Get it: that one),
     * each looked up now, `caracole get --no-songbooks`, in the songbook's order, as many as leave room for the
     * songbook after them; then `caracole songbook render -- NAME` after the last of them. */
    private fun getMissing(form: Map<String, String>): Response {
        val (name, songs) = readable {
            parts.database.read { db ->
                val overrides = LookupForms.overrides(db)
                missingSongs(db, form, overrides)
            }
        }
        val lookups = ArrayList<Job>()
        for (song in songs.take(maxOf(0, parts.queue.room() - 1))) {  // room for the songbook after them
            val spec = LookupForms.spec("Fetch ${song.display}", song.key,
                                        JobCommands.lookupSteps(song.artist, song.title, songbooks = false),
                                        display = song.display, fetching = true)
            try {
                lookups += parts.queue.submit(spec).first
            } catch (_: QueueFull) {
                break
            }
        }
        if (lookups.isEmpty()) throw Refused(503, "The queue is full", JobQueue.QUEUE_FULL)
        // A queue full now refuses the songbook alone: the lookups run all the same.
        val made = parts.queue.submitOrRefuse(renderJob(name, lookups.maxOf { it.id })).first
        return queued(made, "jobs" to JsonArray(lookups.map(::view)),
                      "left" to JsonPrimitive(songs.size - lookups.size))
    }

    /** songbooks.missing_songs: the songbook a Get the missing songs form names, and the songs of it a lookup could
     * get a sheet for now, in its order (SongbookEntries.songsToGet; with `song`, that one alone); Refused when there
     * is no such songbook, or none of its songs to get. A read: the songs' keys as the writes left them, as the tab's
     * data reads them (SongbookSection). */
    private fun missingSongs(db: Db, form: Map<String, String>, overrides: Overrides): Pair<String, List<SongRow>> {
        val (asked, books) = named(form, db)
        val book = book(books, asked)
        var songs = SongbookEntries.songsToGet(
            SongbookEntries.entries(db, parts.store.libraryDir, overrides, book, rekey = false, mirror = mirror()),
            overrides)
        val one = Py.strip(form["song"].orEmpty())
        if (one.isNotEmpty()) {  // a set list's Get it: that song alone
            val id = if (asciiDigits(one)) BigInteger(one) else null
            songs = songs.filter { id != null && BigInteger.valueOf(it.id) == id }
            if (songs.isEmpty()) {
                throw Refused(409, "Nothing to get", "That song of \"${book.name}\" has a sheet already, isn't in the " +
                                                     "library, or is ignored in overrides.toml: reload the library.")
            }
        }
        if (songs.isEmpty()) {
            throw Refused(409, "Nothing to get", "Every song of \"${book.name}\" that the library has has a sheet " +
                                                 "already, or is ignored in overrides.toml: reload the library.")
        }
        return book.name to songs
    }

    /** songbook_routes.add_song: a song put in a songbook from the Songbooks tab's search: one of the library (`song`,
     * its id, or the one a result of the indexes is: its UG pick or its names) with `caracole songbook add` alone; one
     * the library hasn't got looked up now as Get it does, then added once it is in the library. Nothing is queued
     * unless both fit; a lookup that joins one queued needs no room. */
    private fun addSong(form: Map<String, String>): Response {
        val name = readable {
            parts.database.read { db ->
                val (asked, books) = named(form, db)
                book(books, asked).name
            }
        }
        val (_, ug) = LookupForms.pick(form)
        val song = readable { parts.database.read { db -> LookupForms.librarySong(db, form, ug) } }
        val specs = ArrayList<JobSpec>()
        var full = JobQueue.QUEUE_FULL
        val display = if (song != null) {
            song.display
        } else {
            if (Py.strip(form["artist"].orEmpty()).isEmpty() || Py.strip(form["title"].orEmpty()).isEmpty()) {
                throw Refused(400, "Not a song", "Which song? The form names none.")
            }
            val lookup = readable { LookupForms.lookupRequest(parts.database, form) }
            specs += lookup.spec
            full = lookup.full
            lookup.spec.display
        }
        specs += addJob(name, display)
        val queued = try {
            parts.queue.submitAll(specs)
        } catch (_: QueueFull) {
            throw Refused(503, "The queue is full", full)
        }
        return queued(queued.last().first, "jobs" to JsonArray(queued.dropLast(1).map { view(it.first) }))
    }

    // --- what the forms share ----------------------------------------------------------------------------------------

    /** songbooks._named: the name a form gives, as a songbook keeps it, and the songbooks; Refused for a name a
     * songbook can't have. */
    private fun named(form: Map<String, String>, db: Db? = null): Pair<String, List<Songbook>> {
        val name = try {
            Songbooks.checkName(form["name"].orEmpty())
        } catch (e: SongbookError) {
            throw Refused(400, "Not a name", e.message.orEmpty())
        }
        return name to (db?.let(Songbooks::all) ?: parts.database.read(Songbooks::all))
    }

    /** songbooks._book: the songbook of that name, in any case; Refused when there is none. */
    private fun book(books: List<Songbook>, name: String): Songbook =
        Songbooks.find(books, name) ?: throw Refused(404, "No such songbook", "No songbook named \"$name\"" +
            if (books.isNotEmpty()) ": there are ${books.joinToString(", ") { "\"${it.name}\"" }}." else ": reload the library.")

    /** songbooks._songs: the songs of the form's `songs` (ids, comma-separated, in order), each as the library names
     * it ("Artist - Title"), once each; Refused for a list that can't be read, or a song the library hasn't got. */
    private fun songs(form: Map<String, String>): List<String> {
        val text = Py.strip(form["songs"].orEmpty())
        if (text.isEmpty()) throw Refused(400, "No songs", "Pick a song or more for the songbook first.")
        val ids = LinkedHashSet<BigInteger>()
        for (part in text.split(",")) {
            ids += PyInt.parse(part)
                ?: throw Refused(400, "Not songs", "Which songs? The form's list can't be read: reload the library.")
        }
        return parts.database.read { db ->
            ids.map { id ->
                val song = id.takeIf { it.bitLength() < 64 }?.let { Songs.byId(db, it.toLong()) }
                    ?: throw Refused(404, "No such song", "A song you picked isn't in the library any more: reload " +
                                                          "the library and pick again.")
                song.display
            }
        }
    }

    /** songbooks._setting_job: `caracole songbook set`, the song's key, mode, capo and instrument in the songbook (each
     * left out where the form says nothing), or `clear` for its own version; Refused for a setting that can't be one
     * (songbook.check_setting: Versions.settingProblem's words). */
    private fun settingJob(name: String, entry: String, form: Map<String, String>): JobSpec {
        val options: List<String>
        val parts: List<String>
        val said: String
        if (form["clear"].orEmpty() in CLEARS) {
            options = listOf("--clear")
            parts = listOf("clear")
            said = ""
        } else {
            val (key, mode, capo, instrument) = listOf("key", "mode", "capo", "instrument").map { Py.strip(form[it].orEmpty()) }
            if (key.isEmpty() && mode.isEmpty() && capo.isEmpty() && instrument.isEmpty()) {
                throw Refused(400, "Not a setting", "Give it a key, a mode, a capo or an instrument, or play it in its " +
                                                    "own version.")
            }
            val k = key.ifEmpty { null }?.let { PyUnicode.upper(Py.slice(it, 0, 1)) + Py.slice(it, 1, null) }
            val m = PyText.lower(mode).ifEmpty { null }
            val c: Any? = capo.ifEmpty { null }?.let { if (asciiDigits(it)) BigInteger(it) else it }
            val i = PyText.lower(instrument).ifEmpty { null }
            Versions.settingProblem(k, m, c, i)?.let { throw Refused(400, "Not a setting", "The setting: $it") }
            val setting = Setting(k, m, (c as BigInteger?)?.toInt(), i)
            options = listOfNotNull(setting.key?.let { "--key" to it }, setting.mode?.let { "--mode" to it },
                                    setting.capo?.let { "--capo" to it.toString() },
                                    setting.instrument?.let { "--instrument" to it })
                .flatMap { (flag, value) -> listOf(flag, value) }
            val where = listOfNotNull(setting.key, setting.mode).filter { it.isNotEmpty() }.joinToString(" ")
            val capoSaid = when (setting.capo) {
                null -> ""
                0 -> "no capo"
                else -> "capo ${setting.capo}"
            }
            val both = listOf(where, capoSaid).filter { it.isNotEmpty() }.joinToString(", ")
            var words = if (where.isNotEmpty()) "in $both" else if (both.isNotEmpty()) "with $both" else ""
            setting.instrument?.let { id ->
                val on = "on the ${Versions.instrumentWords(Versions.instrumentOf(id)!!)}"
                words = if (words.isNotEmpty()) "$words $on" else on
            }
            said = words
            parts = listOf(setting.key.orEmpty(), setting.mode.orEmpty(), setting.capo?.toString().orEmpty(),
                           setting.instrument.orEmpty())
        }
        val command = listOf("songbook", "set") + options + listOf("--", name, entry)
        val title = if (parts == listOf("clear")) "Play $entry in its own version in \"$name\""
                    else "Play $entry $said, in \"$name\""
        return spec(title, KEY + (listOf("songbook", "set", "--", name, entry) + parts).joinToString(SEP),
                    Command("Changing where it plays", command))
    }

    /** songbooks._job: the job of one `caracole songbook` command; its label is its line while it runs ("Moving the
     * song…"). */
    private fun job(title: String, label: String, action: String, vararg args: String): JobSpec {
        val command = listOf("songbook", action, "--") + args
        return spec(title, KEY + command.joinToString(SEP), Command(label, command))
    }

    /** songbooks.add_job: `caracole songbook add -- NAME SONG`, a song put at the end of the songbook. */
    private fun addJob(name: String, song: String): JobSpec =
        job("Add $song to \"$name\"", "Adding to the songbook", "add", name, song)

    /** songbooks.render_job: `caracole songbook render -- NAME`, queued after the lookups of its missing songs, the
     * last of which is job [after]: its key names that one, so the same tap twice is queued once, and a tap after a
     * newer lookup makes the songbook again after it. */
    private fun renderJob(name: String, after: Int): JobSpec {
        val command = listOf("songbook", "render", "--", name)
        return spec("Make \"$name\" again, with the songs it got", KEY + command.joinToString(SEP) + SEP + after,
                    Command("Making the songbook", command))
    }

    private fun spec(title: String, key: String, command: Command): JobSpec = LookupForms.spec(title, key, listOf(command))

    /** App.queued: the songbook job's view to the page's script (with [more], the lookups' and what is left), else its
     * line in the Requests tab. */
    private fun queued(job: Job, vararg more: Pair<String, JsonElement>): Response {
        val answer = Answers.queued(view(job))
        if (more.isNotEmpty()) answer.data = JsonObject(answer.data.orEmpty() + more)
        return answer
    }

    private fun view(job: Job): JsonObject = LookupForms.view(parts.database, parts.queue, parts.cards, job, clock())

    /** [block], a database that can't be read refused as caracole serve refuses it (app.unreadable, 503). */
    private fun <T> readable(block: () -> T): T = try {
        block()
    } catch (e: Refused) {
        throw e
    } catch (e: Exception) {
        if (!RequestsRoutes.unreadable(e)) throw e
        throw Refused(503, "The database can't be read", "The database can't be read: ${e.message}")
    }

    companion object {
        /** web/songbooks.py's ROUTES' actions, each a `caracole songbook` command. */
        private val CHANGES = listOf(
            "make" to "a songbook made of songs (name, songs)",
            "add" to "songs put at a songbook's end (name, songs)",
            "move" to "a song of a songbook moved (name, song, position)",
            "remove" to "a song taken out of a songbook (name, song)",
            "set" to "where a songbook plays a song: key, mode, capo, instrument, or clear (name, song)",
            "rename" to "a songbook renamed (name, new)",
            "delete" to "a songbook deleted (name)",
        )

        /** songbooks.GET_MISSING: its songs without a sheet, looked up now. */
        const val GET_MISSING = "/songbook/get"

        /** songbooks.ADD_SONG: a song from the tab's search, looked up first when the library hasn't got it. */
        const val ADD_SONG = "/songbook/add-song"

        /** songbooks.MAX_POSITION. */
        const val MAX_POSITION = 100_000

        /** songbooks.KEY: a songbook job's key, then its command's words, [SEP] between them (JobCommands.SONGBOOK). */
        const val KEY = JobCommands.SONGBOOK
        const val SEP = "\u001f"

        /** A form's `clear` that takes the setting off, as songbooks.py reads it. */
        private val CLEARS = setOf("1", "on", "yes")

        /** `s.isascii() and s.isdigit()`: ASCII digits alone, at least one. */
        private fun asciiDigits(s: String): Boolean = s.isNotEmpty() && s.all { it in '0'..'9' }

        /** logs.plural: "1 song", "2 songs". */
        private fun plural(n: Int, word: String): String = "$n ${if (n == 1) word else word + "s"}"
    }
}
