package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.viewer.pages.BookSong
import io.github.danielhp95.caracole.viewer.pages.SongbookPage
import io.github.danielhp95.caracole.viewer.render.OwnVersions
import io.github.danielhp95.caracole.viewer.render.RenderNames
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path

/**
 * songbook.render_songbooks on the phone (lane songbook-entries): each songbook's songbook.html (SongbookPage, its
 * songs as `_render_book` makes them of its entries), written into `_songbooks/<folder>/` of the phone's library only
 * when what it is made from changed or it is no longer as written, and recorded in kv `songbook:<folder>` as Python's
 * `_record` keeps it, `{"inputs": {file: digest}, "files": {file: {"sha256", "size"}}}`, each file's entry naming as
 * WrittenPages.noteSongbook does the digest of the songbook's unit it was made at (`unit`), by which LibraryFiles
 * serves the page (WrittenPages.songbookCurrent); then the files of the songbooks gone taken away (`_remove_gone`).
 * The phone makes the page alone: no chordpro, so no songbook.pdf nor songbook.cho, and the page links neither.
 *
 * As render_songbooks does, it plays each song in its own version as it plays now (OwnVersions.upgraded first), and
 * a song whose pages are the computer's plays from the [mirror]'s .cho of it (SongbookEntries.sheetOf). The page's
 * inputs are Python's (its name, its songs, the files beside it, `assets`), `assets` the phone's [build] now
 * (PhoneRender.build: the viewer's assets and data, the APK's code, the app's version), never Python's build_version,
 * so a new build makes every songbook page again the next time it is rendered ([renderOwn], after the render job).
 *
 * Every write is the caller's, inside Database.write. The songbook runner calls [render]; the lookup's songbooks stage
 * through [seam]; the render job and a sync's take [renderOwn].
 */
class SongbookPagesImpl(val database: Database, val store: LibraryStore, val mirror: Mirror?,
                        val build: () -> String) : SongbookPages {
    /** render_songbooks(only=…): every songbook ([only]: those of these names, in any case) made into its page, each
     * song in its own version as it plays now (own_versions_upgraded), then the files of the songbooks gone taken
     * away. A songbook whose page can't be made or written fails, and the others go on. */
    override fun render(db: Db, only: Set<String>?): SongbookStats {
        val overrides = OwnVersions.upgraded(db, store.libraryDir, Overrides.read(db))
        val onlyKeys = only?.mapTo(HashSet(), Songbooks::nameKey)
        val books = try {
            Songbooks.all(db)
        } catch (e: SongbookError) {
            return SongbookStats(error = e.message)
        } catch (e: IllegalStateException) {  // a row no writer of the phone's made
            return SongbookStats(error = e.message)
        }
        var rendered = 0
        var skipped = 0
        val failed = ArrayList<String>()
        for (book in books) {
            if (onlyKeys != null && Songbooks.nameKey(book.name) !in onlyKeys) continue
            when (renderBook(db, overrides, book)) {
                Done.FAILED -> failed += book.name
                Done.WRITTEN -> rendered++
                Done.UP_TO_DATE -> skipped++
            }
        }
        val removed = removeGone(db, books.mapTo(HashSet()) { SafeName.safeName(it.name) })
        return SongbookStats(rendered = rendered, skipped = skipped, failed = failed, removed = removed)
    }

    /** What the lookup's songbooks stage calls (Assembly gives it as PhoneParts.songbooks): this. */
    val seam: SongbookPages get() = this

    /** The songbooks the phone has made a page of (kv `songbook:<folder>` records a file of theirs) made again where
     * what they are made from changed (a new build, a song a take or the render job moved, the mirror's sheets of
     * them), then the files of the songbooks gone taken away: what the render job and a sync's take end with, so the
     * phone's page of a songbook is never left as an older build or older sheets made it. A songbook the phone made
     * none of keeps the computer's (the mirror's), as LibraryFiles serves it. What it can't do is said in the stats,
     * never thrown: it must cost the job it ends nothing (a bug too, "a bug in caracole: …", a StackOverflowError
     * among them). */
    fun renderOwn(db: Db): SongbookStats = try {
        val made = WrittenPages.songbookFolders(db).filterTo(HashSet()) { WrittenPages.songbook(db, it).isNotEmpty() }
        render(db, Songbooks.all(db).map { it.name }.filterTo(HashSet()) { SafeName.safeName(it) in made })
    } catch (e: SongbookError) {
        SongbookStats(error = e.message)
    } catch (e: IllegalStateException) {  // a row no writer of the phone's made
        SongbookStats(error = e.message)
    } catch (e: Exception) {
        SongbookStats(error = "${RenderNames.BUG}: $e")
    } catch (e: StackOverflowError) {
        SongbookStats(error = "${RenderNames.BUG}: $e")
    }

    private enum class Done { WRITTEN, UP_TO_DATE, FAILED }

    /** songbook._render_book with no PDF and no .cho: the songbook's page, recorded whatever stopped it. */
    private fun renderBook(db: Db, overrides: Overrides, book: Songbook): Done {
        val entries = SongbookEntries.entries(db, store.libraryDir, overrides, book, mirror = mirror)
        val name = SafeName.safeName(book.name)
        val folder = try {
            bookFolder(name)
        } catch (e: SongbookError) {
            return Done.FAILED
        }
        val record = record(db, name)
        try {
            return page(db, book, entries, folder, record)
        } finally {  // what was written stays recorded, whatever stopped the rest
            db.kvSetJson("$RECORD_KEY$name", record.json())
        }
    }

    /** songbook._make_files' songbook.html: written unless it was made from these inputs and is still as written;
     * either way recorded at the songbook unit's digest now, which it is the page of. */
    private fun page(db: Db, book: Songbook, entries: List<Entry>, folder: Path, record: Record): Done {
        val songs = bookSongs(entries)
        val inputs = JsonObject(linkedMapOf(
            "name" to JsonPrimitive(book.name),
            "songs" to JsonArray(songs.map { s ->
                JsonArray(listOf(JsonPrimitive(s.title), JsonPrimitive(s.artist), text(s.cho), text(s.key),
                                 text(s.keySource), JsonPrimitive(s.transpose), text(s.missing), JsonPrimitive(s.id),
                                 text(s.start)))
            }),
            "files" to JsonArray(emptyList()),  // no PDF, no .cho beside it: the phone makes neither
            "assets" to JsonPrimitive(build()),
        ))
        val digest = Canonical.sha256Hex(PyJson.dumps(inputs, sortKeys = true).toByteArray())
        val path = folder.resolve(HTML_NAME)
        val unit = WrittenPages.songbookUnit(db, SafeName.safeName(book.name))?.let { WrittenPages.songbookDigest(db, it) }
        val was = WrittenPages.entryOf(record.files[HTML_NAME])
        if (record.inputs[HTML_NAME] == JsonPrimitive(digest) && was != null && Kept.holds(path, was.first, was.second)) {
            record.files[HTML_NAME] = entry(was.first, was.second, unit)
            return Done.UP_TO_DATE
        }
        val data = try {
            SongbookPage.build(book.name, songs).toByteArray()
        } catch (e: Exception) {  // a sheet the viewer can't read must never cost the songbook its record
            return Done.FAILED
        } catch (e: StackOverflowError) {
            return Done.FAILED
        }
        val sha = Canonical.sha256Hex(data)
        var written = false
        if (!Kept.holds(path, sha, data.size.toLong())) {  // one more sync, else none
            try {
                Kept.writeAtomic(path, data)
            } catch (e: IOException) {  // a folder in its place, a full disk
                return Done.FAILED
            }
            written = true
        }
        record.files[HTML_NAME] = entry(sha, data.size.toLong(), unit)
        record.inputs[HTML_NAME] = JsonPrimitive(digest)
        return if (written) Done.WRITTEN else Done.UP_TO_DATE
    }

    /** songbook._remove_gone: the files of the songbooks no longer in phone_songbooks taken away, each only while it
     * is still as caracole wrote it, then their folder when nothing else is in it; how many songbooks went. Nothing is
     * removed through a symbolic link, in place of `_songbooks` or of a folder. */
    private fun removeGone(db: Db, folders: Set<String>): Int {
        val keys = db.query("SELECT key FROM kv WHERE key LIKE ? ESCAPE '\\'", likePrefix(RECORD_KEY)) { it.text(0)!! }
        val books = File(store.libraryDir, FOLDER).toPath()
        val at = SongbookEntries.attrs(books)
        if (at != null && (at.isSymbolicLink || !at.isDirectory)) return 0  // the records stay, for a folder back
        var gone = 0
        for (key in keys) {
            val folder = key.substring(RECORD_KEY.length)
            if (folder in folders) continue
            val where = books.resolve(folder)
            val dir = if (folder.isNotEmpty() && !folder.startsWith(".") && '/' !in folder) SongbookEntries.attrs(where) else null
            if (dir != null && dir.isDirectory) {
                try {
                    for ((name, entry) in record(db, folder).files) {
                        if (name in OUTPUTS && holds(where.resolve(name), entry)) Files.deleteIfExists(where.resolve(name))
                    }
                } catch (e: IOException) {  // no permission, say: the record stays, and the next render tries again
                    continue
                }
                try {
                    Files.delete(where)  // only when empty: a file of yours stays, and so does its folder
                } catch (e: IOException) {
                    // not empty, or gone
                }
            }
            db.kvDelete(key)
            gone++
        }
        return gone
    }

    /** songbook._book_folder: `_songbooks/<folder>/` of the library, made if need be; SongbookError when either is a
     * symbolic link (caracole doesn't follow one there), not a folder, or can't be made. */
    private fun bookFolder(folder: String): Path {
        var path = store.libraryDir.toPath()
        for (part in listOf(FOLDER, folder)) {
            path = path.resolve(part)
            val found = SongbookEntries.attrs(path)
            if (found?.isSymbolicLink == true) {
                throw SongbookError("$path is a symbolic link, which caracole doesn't follow: put a folder there")
            }
            if (found == null) {
                try {
                    Files.createDirectories(path)
                } catch (e: IOException) {
                    throw SongbookError("can't make the folder $path: ${e.message}")
                }
            }
            val made = SongbookEntries.attrs(path)
            if (made == null || made.isSymbolicLink || !made.isDirectory) throw SongbookError("$path isn't a folder")
        }
        return path
    }

    /** songbook._record: kv `songbook:<folder>`, its `inputs` and `files` objects (each made empty when it isn't
     * one), the rest of it kept as it is. */
    private fun record(db: Db, folder: String): Record {
        val stored = db.kvGet("$RECORD_KEY$folder")?.let {
            try {
                PyJson.loads(it)
            } catch (e: Exception) {
                null
            }
        } as? JsonObject
        val whole = LinkedHashMap<String, JsonElement>(stored.orEmpty())
        val inputs = LinkedHashMap((whole["inputs"] as? JsonObject).orEmpty())
        val files = LinkedHashMap((whole["files"] as? JsonObject).orEmpty())
        return Record(whole, inputs, files)
    }

    private class Record(val whole: LinkedHashMap<String, JsonElement>, val inputs: LinkedHashMap<String, JsonElement>,
                         val files: LinkedHashMap<String, JsonElement>) {
        fun json(): JsonObject {
            whole["inputs"] = JsonObject(inputs)
            whole["files"] = JsonObject(files)
            return JsonObject(whole)
        }
    }

    companion object {
        /** songbook.HTML_NAME, and the files a songbook's folder may hold of caracole's (songbook.OUTPUTS). */
        const val HTML_NAME = "songbook.html"
        val OUTPUTS = setOf("songbook.cho", "songbook.pdf", "songbook (Traditional).pdf", HTML_NAME)

        /** songbook.RECORD_KEY and songbook.FOLDER. */
        const val RECORD_KEY = "songbook:"
        const val FOLDER = "_songbooks"

        /** The songbook's songs as `_render_book` makes them of its [entries] (viewer.book.BookSong). */
        fun bookSongs(entries: List<Entry>): List<BookSong> = entries.map { e ->
            BookSong(e.title, e.artist, cho = e.cho, key = e.key, keySource = e.keySource, transpose = e.transpose,
                     missing = e.missing, id = songId(e), start = start(e))
        }

        /** songbook._song_id: a short id for the song on the phone page, the same wherever the songbook puts it. */
        fun songId(entry: Entry): String = Canonical.sha256Hex((entry.song?.key ?: entry.text).toByteArray()).take(10)

        /** songbook._start: where the phone page starts the song, its version as the viewer's address writes it
         * (render.export_query), null for one that only moves it; a setting naming the guitar names it there too. */
        fun start(entry: Entry): String? {
            val version = entry.version
            val onGuitar = entry.setting?.instrument != null && version.inst == null
            if (version == Version(t = version.t) && !onGuitar) return null
            return exportQuery(version) + if (onGuitar) "&inst=guitar" else ""
        }

        /** render.export_query: the version as an address that always says its `t`. */
        fun exportQuery(v: Version): String =
            (listOf("t=${v.t}") + Versions.query(v).split("&").filter { it.isNotEmpty() && !it.startsWith("t=") })
                .joinToString("&")

        /** A file's entry in the record: render.written_entry's, with the songbook unit's digest it was made at, as
         * WrittenPages.noteSongbook writes one (none where no songbook has the folder). */
        private fun entry(sha: String, size: Long, unit: String?): JsonObject {
            val entry = linkedMapOf<String, JsonElement>("sha256" to JsonPrimitive(sha), "size" to JsonPrimitive(size))
            unit?.let { entry["unit"] = JsonPrimitive(it) }
            return JsonObject(entry)
        }

        private fun holds(path: Path, entry: JsonElement?): Boolean {
            val (sha, size) = WrittenPages.entryOf(entry) ?: return false
            return Kept.holds(path, sha, size)
        }

        private fun likePrefix(prefix: String): String =
            prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

        private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
    }
}
