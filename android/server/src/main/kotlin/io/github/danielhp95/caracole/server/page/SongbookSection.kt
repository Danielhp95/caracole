package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFile
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.server.songbooks.Entry
import io.github.danielhp95.caracole.server.songbooks.SongbookEntries
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.BasicFileAttributes
import java.time.Instant
import java.time.ZoneOffset

/**
 * songbook_section.songbooks_data on the phone (lane songbook-entries): the Songbooks tab's data from phone_songbooks
 * (Songbooks.all), which `/jobs.json` gives again once a job is over, member for member as Python's for the same
 * library; held by vectors/songbook/tab.jsonl (SongbookTabReplay).
 *
 * The phone makes a songbook's page alone ([PHONE_FILES], `[("songbook.html", "Phone page")]`, songbooks_data's
 * `files`), never chordpro's PDF or .cho: its tab names that one file and links it while it is in the songbook's
 * folder, `_songbooks/<folder>/` of the phone's library. A song's line opens its sheet as its line on the library page
 * does (library_page.sheet_href: its folder's first viewer or PDF, else its text), and its Guitar Pro mark is the
 * file caracole keeps for it (inbox.guitar_files, still in its folder) with caracole serve's page of one it shows.
 */
object SongbookSection {
    /** The songbook's files the phone makes, each (name, label), in the order its tab links them. */
    val PHONE_FILES: List<Pair<String, String>> = listOf("songbook.html" to "Phone page")

    /** songbook.FOLDER. */
    private const val FOLDER = "_songbooks"

    /**
     * The tab's data for the phone's library, as `/jobs.json` gives it once a job is over (JobsRoutes): null, the
     * page's own data standing (the mirror's), until the phone serves the songbook pages it writes and reads the
     * sheets the mirror serves. A Phase A guard, waiting on: written-pages (LibraryFiles serving a songbook's page by
     * its record) and phone-render (the songs' .cho the entries read, render:files): before them every songbook's
     * files would read as none and every song the computer rendered as having no sheet. Phase B makes it
     * `data(db, store.libraryDir, Overrides.read(db), rekey = false)`: a read, which takes the songs' keys as the
     * writes left them (SongbookEntries.entries' `rekey`).
     */
    @Suppress("UNUSED_PARAMETER")
    fun data(db: Db, store: LibraryStore): JsonObject? = null

    /** songbooks_data(conn, cfg, overrides, files=[files]): the songbooks as the Songbooks tab draws them; a
     * songbooks' table that can't be read is said (`error`), and costs the rest of the page nothing. */
    fun data(db: Db, libraryDir: File, overrides: Overrides, files: List<Pair<String, String>> = PHONE_FILES,
             guitarFiles: (Db) -> List<GuitarFile> = ::keptGuitarFiles, rekey: Boolean = true): JsonObject {
        val shared = linkedMapOf<String, JsonElement>(
            "keys" to JsonArray(Theory.spelling(null).map(::JsonPrimitive)),
            "modes" to JsonArray(Theory.MODES.map { JsonArray(listOf(JsonPrimitive(it), JsonPrimitive(Versions.MODE_NAMES.getValue(it)))) }),
            "capoMax" to JsonPrimitive(Versions.CAPO_MAX),
            "instruments" to JsonArray(Instruments.INSTRUMENTS.values.map {
                JsonArray(listOf(JsonPrimitive(it.id), JsonPrimitive(it.name), JsonPrimitive(it.capo)))
            }),
            "fileLabels" to JsonArray(files.map { JsonPrimitive(it.second) }),
        )
        val books = try {
            Songbooks.all(db)
        } catch (e: SongbookError) {
            return unread(e.message, shared)
        } catch (e: IllegalStateException) {  // a row no writer of the phone's made: its songs aren't a list
            return unread(e.message, shared)
        }
        val guitar = if (books.isEmpty()) Guitar(emptyMap(), emptyMap()) else Guitar.read(db, guitarFiles)
        val out = linkedMapOf<String, JsonElement>(
            "books" to JsonArray(books.map { book(db, libraryDir, overrides, it, guitar, files, rekey) }),
            "error" to JsonNull,
        )
        out.putAll(shared)
        return JsonObject(out)
    }

    private fun unread(why: String?, shared: Map<String, JsonElement>): JsonObject {
        val out = linkedMapOf<String, JsonElement>(
            "books" to JsonArray(emptyList()),
            "error" to JsonPrimitive("songbooks.toml can't be read: $why. Fix it, and the songbooks are back; " +
                                         "until then each keeps its files."),
        )
        out.putAll(shared)
        return JsonObject(out)
    }

    /** songbook_section._book. */
    private fun book(db: Db, libraryDir: File, overrides: Overrides, book: Songbook, guitar: Guitar,
                     files: List<Pair<String, String>>, rekey: Boolean): JsonObject {
        val entries = SongbookEntries.entries(db, libraryDir, overrides, book, rekey)
        val getting = SongbookEntries.songsToGet(entries, overrides).mapTo(HashSet()) { it.id }
        val folder = SafeName.safeName(book.name)
        val made = made(File(File(libraryDir, FOLDER), folder), files)
        val base = "$FOLDER/${PyUrl.quote(folder, safe = "")}"
        val songs = entries.withIndex().map { (i, e) ->
            val (plays, at) = plays(e)
            val song = e.song
            JsonObject(linkedMapOf(
                "n" to JsonPrimitive(i + 1), "entry" to JsonPrimitive(e.text),
                "key" to JsonPrimitive(song?.key ?: Songbooks.entryKeys(e.text).firstOrNull() ?: ""),
                "title" to JsonPrimitive(e.title), "artist" to JsonPrimitive(e.artist),
                "id" to (song?.id?.let(::JsonPrimitive) ?: JsonNull), "missing" to text(e.missing),
                "get" to JsonPrimitive(song != null && song.id in getting), "plays" to text(plays),
                "own" to JsonPrimitive(e.setting == null || e.setting == Setting()), "at" to (at ?: JsonNull),
                "href" to (if (song != null && e.cho != null) text(sheetHref(libraryDir, song)) else JsonNull),
                "guitar" to (song?.let { guitar.mark(libraryDir, it) } ?: JsonNull),
            ))
        }
        val newest = made.values.maxOrNull()
        return JsonObject(linkedMapOf(
            "name" to JsonPrimitive(book.name), "songs" to JsonPrimitive(entries.size),
            "missing" to JsonPrimitive(entries.count { it.missing != null }),
            "changed" to (newest?.let { JsonPrimitive(it.atOffset(ZoneOffset.UTC).toLocalDate().toString()) } ?: JsonNull),
            "files" to JsonArray(files.filter { it.first in made }.map { (name, label) ->
                JsonObject(linkedMapOf("name" to JsonPrimitive(name), "label" to JsonPrimitive(label),
                                       "href" to JsonPrimitive("$base/${PyUrl.quote(name)}")))
            }),
            "set" to JsonArray(songs),
        ))
    }

    /** songbook_section._made: the songbook's files of [files] there are, regular files alone (no link followed),
     * each with when it was written. */
    private fun made(folder: File, files: List<Pair<String, String>>): Map<String, Instant> {
        val found = LinkedHashMap<String, Instant>()
        for ((name, _) in files) {
            val attrs = attrs(File(folder, name)) ?: continue
            if (attrs.isRegularFile) found[name] = attrs.lastModifiedTime().toInstant()
        }
        return found
    }

    /** songbook_section._plays: where the songbook plays the song in words, and for the setting's menus the key of
     * the shapes played (a pitch class and a mode, null for a sheet with no key), the capo, the tonic it sounds in
     * and the instrument it is played on; null for a song without a sheet. */
    private fun plays(entry: Entry): Pair<String?, JsonObject?> {
        val (label, played) = SongbookEntries.wherePlayed(entry)
        if (played == null) return label to null
        val (key, capo) = played
        return label to JsonObject(linkedMapOf(
            "tonic" to (key?.tonic?.let(::JsonPrimitive) ?: JsonNull), "mode" to text(key?.mode),
            "capo" to JsonPrimitive(capo),
            "sounds" to (key?.let { JsonPrimitive(Math.floorMod(it.tonic + capo, 12)) } ?: JsonNull),
            "inst" to JsonPrimitive(Versions.playedOn(entry.version).id),
        ))
    }

    /** library_page's viewers and PDFs a line opens first, in its order, then its texts (`_primary` over
     * `_in_line_order`). */
    private val VIEWERS = listOf("sheet.html", "sheet.pdf", "sheet (auto).html", "sheet (auto).pdf")
    private val TEXTS = listOf("sheet.txt", "sheet (auto).txt")

    /** library_page.sheet_href: the link to the song's sheet, its line's primary file, relative to the library page
     * and percent-encoded, or null without one (`_file_names`: the folder's files, a name with a leading dot aside). */
    internal fun sheetHref(libraryDir: File, song: SongRow): String? {
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        val folder = File(File(libraryDir, artist), title)
        val names = try {
            folder.listFiles()?.filter { it.isFile && !it.name.startsWith(".") }?.mapTo(HashSet()) { it.name }
        } catch (e: SecurityException) {
            null
        } ?: emptySet()
        val primary = VIEWERS.firstOrNull { it in names } ?: TEXTS.firstOrNull { it in names } ?: return null
        return "${PyUrl.quote(artist, safe = "")}/${PyUrl.quote(title, safe = "")}/${PyUrl.quote(primary, safe = "")}"
    }

    /** songbook_section._Guitar: what caracole keeps of Guitar Pro for the songs, read once for every songbook: the
     * files by song, in their order, and caracole serve's Guitar Pro page of each it shows, by song and name
     * (library_page.guitar_pages: `guitar?file=<its path>`). */
    private class Guitar(val files: Map<Long, List<GuitarFile>>, val pages: Map<Long, Map<String, String>>) {
        /** The song's mark: a file it keeps that is still in the library (a regular file, no link followed), one the
         * Guitar Pro page shows first; else null. */
        fun mark(libraryDir: File, song: SongRow): JsonElement? {
            val kept = files[song.id].orEmpty().filter { attrs(File(libraryDir, it.path))?.isRegularFile == true }
            if (kept.isEmpty()) return null
            val shown = pages[song.id].orEmpty()
            val f = kept.firstOrNull { it.name in shown } ?: kept[0]
            val download = DownloadNames.downloadName(song.artist, Normalize.cleanTitle(song.title), f.name)
            return JsonObject(linkedMapOf("kind" to JsonPrimitive("file"), "href" to JsonPrimitive(PyUrl.quote(f.path)),
                                          "download" to JsonPrimitive(download), "page" to text(shown[f.name])))
        }

        companion object {
            fun read(db: Db, guitarFiles: (Db) -> List<GuitarFile>): Guitar {
                val all = guitarFiles(db)
                val pages = LinkedHashMap<Long, LinkedHashMap<String, String>>()
                for (f in all) {
                    if (f.inBrowser) pages.getOrPut(f.songId) { LinkedHashMap() }[f.name] = "guitar?" + PyUrl.urlencode(listOf("file" to f.path))
                }
                return Guitar(all.groupBy { it.songId }, pages)
            }
        }
    }

    /** inbox.guitar_files, :core's GuitarFiles.of. A Phase A guard, waiting on: guitar-alphatab, whose port it is:
     * until it lands no file is a mark, so the tab is drawn whatever. */
    private fun keptGuitarFiles(db: Db): List<GuitarFile> = try {
        GuitarFiles.of(db)
    } catch (e: NotImplementedError) {
        emptyList()
    }

    /** What [file] is itself (no link followed), or null for nothing there or a file that can't be looked at. */
    private fun attrs(file: File): BasicFileAttributes? = try {
        Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
    } catch (e: IOException) {
        null
    }

    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
}
