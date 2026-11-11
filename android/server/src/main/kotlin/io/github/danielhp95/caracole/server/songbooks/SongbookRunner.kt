package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.lookups.LookupJobs
import io.github.danielhp95.caracole.server.routes.ExportRoutes
import io.github.danielhp95.caracole.viewer.version.Versions
import java.io.File
import java.math.BigInteger
import java.nio.file.Files
import java.nio.file.LinkOption

/**
 * `caracole songbook make|add|remove|move|set|rename|delete|render` on the phone (commands/songbook.py), each command
 * line as the Songbooks tab's forms queue it (SongbookRoutes: `songbook ACTION [OPTIONS] -- NAME …`):
 *
 * - the change through :core's Songbooks, in one write (phone_songbooks), refused in songbook.py's words (a
 *   SongbookError exits 1, a usage error 2, as typer exits), each song of `make` and `add` found as the command finds
 *   one ([findLibrarySong]: its "Artist - Title", else a search of the library one song answers well), each of
 *   `remove`, `move` and `set` the songbook's own entry first ([entryFor]); its lines commands/songbook.py's;
 * - then the songbook made again ([render]: the songbooks' pages, [PhoneParts.songbooks], `render_songbooks(only=…)`,
 *   which also takes away the files of a songbook renamed or deleted), and, once the phone makes them, the songs it
 *   names missing and the files it wrote, as `_render` says them. While the songbooks' pages are none
 *   ([SongbookPages.NONE]), nothing is made and nothing more is said, as the lookup's songbooks stage does.
 *
 * Its lines are the command's (vectors/songbook/routes_runner.jsonl holds them, and the songbooks after, to
 * commands/songbook.py's for the same library): an error its `error:` line, then the lines after it of a message of
 * several (a song the library hasn't got, with what it may have meant), as the log writes one; a songbook whose page
 * couldn't be made a `warning:` line, as render_songbooks logs it, and its exit 1 none (typer.Exit's, so the Requests
 * tab says "Making the songbook failed." as caracole serve's does).
 *
 * A song's sheet is the one the songbooks' pages play it from (SongbookEntries.sheetOf): where its pages are the
 * computer's, the [mirror]'s .cho of it. The phone forgets the search's answers after each job (Phone.afterJob), this
 * one's too. The library's pages are the phone's own, made per request, so nothing writes them here (caracole serve's
 * `write_pages`). [readOverrides] stands in for the phone's overrides, a test's.
 */
class SongbookRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = { Overrides.read(it) },
                     private val mirror: () -> Mirror? = { ExportRoutes.mirrorOf(parts.cards) }) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        try {
            command(args, context)
        } catch (e: CommandExit) {
            // a message of several lines: its error line, then the others, as the log writes it, and no line more
            val lines = e.message.orEmpty().lines()
            if (lines.size < 2) throw e
            context.say("error: ${lines[0]}")
            lines.drop(1).forEach(context::say)
            throw CommandExit(e.code, "")
        }
    }

    private suspend fun command(args: List<String>, context: JobContext) {
        val action = args.getOrNull(1) ?: throw CommandExit(2, "Missing command.")
        val line = LookupJobs.line(args.drop(1), VALUED)
        val o = line.options
        val known = if (action == "set") SET_OPTIONS else if (action == "render") setOf("--force") else emptySet()
        for (name in o.keys) if (name !in known) throw CommandExit(2, "No such option: $name")
        val w = line.words
        when (action) {
            "make" -> make(word(w, 0, "NAME"), songs(w), context)
            "add" -> add(word(w, 0, "NAME"), songs(w), context)
            "remove" -> remove(word(w, 0, "NAME"), songs(w), context)
            "move" -> move(word(w, 0, "NAME"), word(w, 1, SONG), position(word(w, 2, "POSITION")), context)
            "set" -> set(word(w, 0, "NAME"), word(w, 1, SONG), o, context)
            "rename" -> rename(word(w, 0, "NAME"), word(w, 1, "NEW"), context)
            "delete" -> delete(word(w, 0, "NAME"), context)
            "render" -> renderCommand(w.firstOrNull(), context)
            else -> throw CommandExit(2, "No such command '$action'.")
        }
    }

    // --- the commands ------------------------------------------------------------------------------------------------

    /** `songbook make NAME SONG...`: a songbook of these songs, in this order. */
    private suspend fun make(name: String, texts: List<String>, context: JobContext) {
        val (made, found) = change { db ->
            val found = librarySongs(db, texts)
            Songbooks.make(db, name, found.map { it.song.display }) to found
        }
        context.say("Made the songbook \"${made.name}\": ${plural(made.songs.size, "song")}.")
        val seen = HashSet<Long>()
        for (f in found) {  // a song named twice is in it once
            if (f.song.id in seen) context.say("${f.song.display} is in it already")
            seen += f.song.id
        }
        sayFound(texts, found, context)
        render(made.name, context)
    }

    /** `songbook add NAME SONG...`: songs at its end. */
    private suspend fun add(name: String, texts: List<String>, context: JobContext) {
        val (book, found, added) = change { db ->
            val book = book(db, name)
            val found = librarySongs(db, texts)
            Triple(book, found, Songbooks.add(db, book.name, found.map { it.song.display }))
        }
        for (f in found) {
            if (added.any { Songbooks.sameEntry(f.song.display, it) }) context.say("Added ${f.song.display}")
            else context.say("${f.song.display} is in it already")
        }
        sayFound(texts, found, context)
        render(book.name, context)
    }

    /** `songbook remove NAME SONG...`: songs out of it; a song no longer in the library goes by its name. */
    private suspend fun remove(name: String, texts: List<String>, context: JobContext) {
        val (book, removed) = change { db ->
            val book = book(db, name)
            book to Songbooks.remove(db, book.name, texts.map { entryFor(db, book, it) })
        }
        for (entry in removed) context.say("Removed $entry")
        if (removed.isEmpty()) {
            throw CommandExit(1, "None of these is in the songbook \"${book.name}\": caracole songbook show lists its songs.")
        }
        render(book.name, context)
    }

    /** `songbook move NAME SONG POSITION`: a song to a place, 1 the first. */
    private suspend fun move(name: String, song: String, position: Int, context: JobContext) {
        val (book, shown, to) = change { db ->
            val book = book(db, name)
            val entry = entryFor(db, book, song)
            val to = Songbooks.move(db, book.name, entry, position)
            // songbook_entries' song of that entry: its "Artist - Title" alone
            Triple(book, Songbooks.findEntrySong(db, entry)?.display ?: entry, to)
        }
        context.say("Moved $shown to $to")
        render(book.name, context)
    }

    /** `songbook set NAME SONG [--key K] [--mode M] [--capo N] [--instrument I] | --clear`: where it plays a song. A
     * key or a mode with no capo keeps the capo it plays at now (SongbookEntries.withCapo); another instrument at the
     * pitch it plays at now (SongbookEntries.onInstrument). */
    private suspend fun set(name: String, song: String, o: Map<String, String?>, context: JobContext) {
        val key = o["--key"]
        val mode = o["--mode"]
        val capo = o["--capo"]?.let(::capo)
        val instrument = o["--instrument"]
        val clear = "--clear" in o
        val given = key != null || mode != null || capo != null || instrument != null
        if (clear == given) {
            throw CommandExit(2, "Give --key, --mode, --capo or --instrument to set, or --clear to take the setting off.")
        }
        val (shown, new, where, bookName) = change { db ->
            val overrides = readOverrides(db)
            val book = book(db, name)
            val entry = entryFor(db, book, song)
            val old = book.songs.firstOrNull { it.text == entry }?.setting ?: Setting()
            var new: Setting? = null
            if (!clear) {
                // a part not given (or given empty, which Python's truth reads as none) keeps the song's setting's
                var setting = checkSetting(key?.ifEmpty { null }?.let { PyUnicode.upper(Py.slice(it, 0, 1)) + Py.slice(it, 1, null) }
                                               ?: old.key,
                                           mode?.ifEmpty { null }?.let(PyText::lower) ?: old.mode, capo ?: old.capo,
                                           instrument?.ifEmpty { null }?.let(PyText::lower) ?: old.instrument)
                if (instrument != null) {  // at the pitch it plays at now, as the Songbooks tab's menus keep it
                    setting = SongbookEntries.onInstrument(played(db, overrides, book, entry, old.takeUnless { it == Setting() }),
                                                           setting, keyGiven = key != null, capoGiven = capo != null)
                }
                new = SongbookEntries.withCapo(played(db, overrides, book, entry, null), setting, overrides)
            }
            Songbooks.set(db, book.name, entry, new, ::problem)
            val played = played(db, overrides, book, entry, new)
            Quad(played.song?.display ?: entry, new, SongbookEntries.playsIn(played), book.name)
        }
        context.say("$shown: " + (new?.takeUnless { it == Setting() }?.let(::settingLine) ?: "the sheet's own setting"))
        where?.let { context.say("In the songbook: $it") }
        render(bookName, context)
    }

    /** `songbook rename NAME NEW`: another name, and its files to its new folder. */
    private suspend fun rename(name: String, new: String, context: JobContext) {
        val (book, renamed) = change { db ->
            val book = book(db, name)
            book to Songbooks.rename(db, book.name, new)
        }
        context.say("Renamed the songbook \"${book.name}\" to \"${renamed.name}\".")
        render(renamed.name, context)
    }

    /** `songbook delete NAME`: the songbook, and the files caracole made of it. */
    private suspend fun delete(name: String, context: JobContext) {
        val book = change { db -> book(db, name).also { Songbooks.delete(db, it.name) } }
        context.say("Deleted the songbook \"${book.name}\".")
        render(book.name, context)
    }

    /** `songbook render [NAME]`: its files (every songbook's), when they need it; exits 1 when one couldn't be made
     * (its warning says which), with no error line, as typer.Exit(1). `--force` is the computer's (every file made
     * again): the phone's songbooks' pages make what they need. */
    private suspend fun renderCommand(name: String?, context: JobContext) {
        val only = name?.let { parts.database.read { db -> book(db, it).name } }
        val stats = render(only, context, quiet = true)
        context.say("${stats.rendered} rendered, ${stats.skipped} up to date, ${stats.failed.size} failed")
        if (stats.failed.isNotEmpty()) throw CommandExit(1, "")
    }

    // --- what they share ---------------------------------------------------------------------------------------------

    /** commands/songbook._render: the songbook's files made again ([only]: that one, else every one; the files of
     * songbooks gone go too). While the phone makes no songbook pages, none. A songbook that couldn't be made is
     * said as render_songbooks logs it (a `warning:` line), quiet or not. Not [quiet]: the songs it names missing,
     * and the files it wrote; then a songbook that couldn't be made exits 1, its change made, with no error line
     * (typer.Exit(1)). */
    private suspend fun render(only: String?, context: JobContext, quiet: Boolean = false): SongbookStats {
        val songbooks = parts.songbooks
        if (songbooks === SongbookPages.NONE) return SongbookStats()
        val stats = parts.database.write { db -> songbooks.render(db, only?.let(::setOf)) }
        stats.error?.let { throw CommandExit(2, it) }
        stats.fontError?.let { context.say("warning: $it") }
        for (name in stats.failed) context.say("warning: songbook $name: its page couldn't be made")
        if (!quiet && only != null) {
            val said = parts.database.read { db ->
                val book = Songbooks.find(Songbooks.all(db), only) ?: return@read emptyList()
                // a read: the keys as the change's write left them
                val missing = SongbookEntries.entries(db, parts.store.libraryDir, readOverrides(db), book,
                                                      rekey = false, mirror = mirror())
                    .filter { it.missing == SongbookEntries.MISSING_SHEET }
                    .map { "${it.song?.display ?: it.text} has no sheet yet: it is named missing until it has one" }
                val where = File(File(parts.store.libraryDir, Songbooks.FOLDER), SafeName.safeName(book.name))
                val files = FILES.filter { Files.isRegularFile(File(where, it).toPath(), LinkOption.NOFOLLOW_LINKS) }
                missing + if (files.isNotEmpty()) "Wrote ${where.path}: ${files.joinToString(", ")}"
                          else "Nothing written in ${where.path}"
            }
            said.forEach(context::say)
            if (stats.failed.isNotEmpty()) context.say("Some of its files couldn't be made: the warning above says why.")
        }
        if (stats.failed.isNotEmpty() && !quiet) throw CommandExit(1, "")
        return stats
    }

    /** [block] in one write, the library re-keyed first (find_song's ensure_current_keys); a SongbookError ends the
     * command with its words, exit 1. */
    private suspend fun <T> change(block: (Db) -> T): T = try {
        parts.database.write { db ->
            parts.store.ensureCurrentKeys(db)
            block(db)
        }
    } catch (e: SongbookError) {
        throw CommandExit(1, e.message.orEmpty())
    }

    /** commands/songbook._book: the songbook of that name, in any case; one there isn't ends the command. */
    private fun book(db: Db, name: String): Songbook {
        val books = Songbooks.all(db)
        return Songbooks.find(books, name) ?: throw CommandExit(1, "No songbook named \"${Py.split(name).joinToString(" ")}\"" +
            if (books.isNotEmpty()) ": there are ${books.joinToString(", ") { "\"${it.name}\"" }}." else ".")
    }

    /** commands/songbook._entry_for: the songbook's own entry [text] stands for, by its "Artist - Title"; only when it
     * names none, the songbook's entry of the library's song a search finds (or that song's name); else [text]. */
    private fun entryFor(db: Db, book: Songbook, text: String): String {
        book.texts.firstOrNull { Songbooks.sameEntry(it, text) }?.let { return it }
        val found = findLibrarySong(db, text) ?: return text
        return book.texts.firstOrNull { Songbooks.sameEntry(it, found.song.display) } ?: found.song.display
    }

    /** songbook.Found: a song of the library a text names, [exact] when by its "Artist - Title". */
    private data class Found(val song: SongRow, val exact: Boolean = true)

    /** songbook.find_library_song: by its "Artist - Title" (Songbooks.findEntrySong), then by a search of the library
     * one song answers well by its title, or by its artist and title, and no other comes close. */
    private fun findLibrarySong(db: Db, text: String): Found? {
        Songbooks.findEntrySong(db, text)?.let { return Found(it) }
        val hits = Search.searchLibrary(db, text, limit = 2)
        val first = hits.firstOrNull() ?: return null
        if (first.score >= SearchLimits.STRONG && first.via != "artist" &&
            (hits.size == 1 || hits[1].score <= first.score - SEARCH_MARGIN)) return Found(first.song, exact = false)
        return null
    }

    /** songbook.library_songs: the songs [texts] name, in order; songbook.NotInLibrary for any the library lacks,
     * naming every one with what it may have meant. */
    private fun librarySongs(db: Db, texts: List<String>): List<Found> {
        val found = ArrayList<Found>()
        val lines = ArrayList<String>()
        for (text in texts) {
            val one = findLibrarySong(db, text)
            if (one != null) {
                found += one
                continue
            }
            val near = Search.searchLibrary(db, text, limit = 3).map { "\"${it.song.display}\"" }
            val meant = if (near.isEmpty()) "." else
                ": did you mean ${if (near.size == 1) near[0] else near.dropLast(1).joinToString(", ") + " or " + near.last()}?"
            lines += "No song \"$text\" in the library$meant"
        }
        if (lines.isNotEmpty()) {
            lines += "A songbook holds songs of your library: find one with caracole search, or add it with caracole " +
                "add ARTIST TITLE first."
            throw SongbookError(lines.joinToString("\n"))
        }
        return found
    }

    private fun sayFound(texts: List<String>, found: List<Found>, context: JobContext) {
        for ((text, f) in texts.zip(found)) if (!f.exact) context.say("Took ${f.song.display} for \"$text\"")
    }

    /** commands/songbook._played: the songbook's song [entry] as its files play it with [setting]; inside [change]'s
     * write, which re-keyed the library first. */
    private fun played(db: Db, overrides: Overrides, book: Songbook, entry: String, setting: Setting?): Entry =
        SongbookEntries.entries(db, parts.store.libraryDir, overrides,
                                Songbook(book.name, listOf(SongbookSong(entry, setting))), rekey = false,
                                mirror = mirror()).single()

    /** songbook.check_setting's problem: version.setting_problem of a setting's parts. */
    private fun problem(setting: Setting): String? =
        Versions.settingProblem(setting.key, setting.mode, setting.capo, setting.instrument)

    /** songbook.check_setting: the setting these parts make; SongbookError for a part that can't be one. */
    private fun checkSetting(key: String?, mode: String?, capo: Int?, instrument: String?): Setting {
        val setting = Setting(key, mode, capo, instrument)
        problem(setting)?.let { throw SongbookError("a setting: $it") }
        return setting
    }

    private data class Quad<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)

    companion object {
        private const val SONG = "\"ARTIST - TITLE\""

        /** The options that take a value: `set`'s. */
        private val VALUED = setOf("--key", "--mode", "--capo", "--instrument")
        private val SET_OPTIONS = VALUED + "--clear"

        /** songbook.SEARCH_MARGIN: a search finds a song when no other one scores within this of it. */
        private const val SEARCH_MARGIN = 5

        /** commands/songbook._files' order: the songbook's files a folder may hold. */
        private val FILES = listOf("songbook.pdf", "songbook (Traditional).pdf", "songbook.html", "songbook.cho")

        /** A command's word [i], typer's usage error when it is missing. */
        private fun word(words: List<String>, i: Int, name: String): String =
            words.getOrNull(i) ?: throw CommandExit(2, "Missing argument '$name'.")

        /** The songs after the name, one at least. */
        private fun songs(words: List<String>): List<String> =
            words.drop(1).ifEmpty { throw CommandExit(2, "Missing argument '$SONG...'.") }

        /** POSITION as typer reads it: an int, from 1. */
        private fun position(text: String): Int {
            val n = PyInt.parse(text) ?: throw CommandExit(2, "Invalid value for 'POSITION': '$text' is not a valid integer.")
            if (n < BigInteger.ONE) throw CommandExit(2, "Invalid value for 'POSITION': $n is not in the range x>=1.")
            return if (n.bitLength() < 32) n.toInt() else Int.MAX_VALUE
        }

        /** --capo as typer reads it: an int from 0 to 11. */
        private fun capo(text: String): Int {
            val n = PyInt.parse(text) ?: throw CommandExit(2, "Invalid value for '--capo': '$text' is not a valid integer.")
            if (n < BigInteger.ZERO || n > BigInteger.valueOf(11)) {
                throw CommandExit(2, "Invalid value for '--capo': $n is not in the range 0<=x<=11.")
            }
            return n.toInt()
        }

        /** commands/songbook._setting_line: the setting as songbooks.toml holds it, in words. */
        internal fun settingLine(setting: Setting): String {
            val capo = when (setting.capo) {
                null -> ""
                0 -> "no capo"
                else -> "capo ${setting.capo}"
            }
            val on = Versions.instrumentOf(setting.instrument)?.let { "on the ${Versions.instrumentWords(it)}" }.orEmpty()
            val parts = listOf(setting.key?.let { "key $it" }.orEmpty(), setting.mode.orEmpty(), capo, on)
            return parts.filter { it.isNotEmpty() }.joinToString(", ").ifEmpty { "the sheet's own setting" }
        }

        /** logs.plural. */
        private fun plural(n: Int, word: String): String = "$n ${if (n == 1) word else word + "s"}"
    }
}
