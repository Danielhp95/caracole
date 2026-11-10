package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.Looked
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.mirror.pageFor
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.viewer.pages.SheetPage
import io.github.danielhp95.caracole.viewer.render.Written
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.InvalidPathException
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes

/** Whether the mirror may serve a page of a unit as the computer made it: the phone's own state decides. A song
 * the phone removed (a tombstone of its key, no song) is REMOVED; a unit whose digest on the phone now differs from
 * the one the computer listed with the page is CHANGED (Units.digestOf: the unit's digest as peer_sync gives it,
 * none for a unit the phone hasn't got); anything else is served. */
class PhoneGate(val database: Database) : UnitGate {
    override fun check(unit: String, digest: String?): Gate = database.read { db ->
        if (unit.startsWith(SONG) && Songs.isRemoved(db, unit.removePrefix(SONG))) {
            Gate.REMOVED
        } else {
            val now = Units.digestOf(db, unit)
            if (now != null && now != digest) Gate.CHANGED else Gate.SERVE
        }
    }

    private companion object {
        const val SONG = "song/"
    }
}

/**
 * The pages the phone writes into its library, as [LibraryFiles] reads them (lane phone-render's [WrittenPages]): a
 * song's file's record (kv `render:files:<id>`: its bytes' SHA-256 and size, and the song unit's digest it was made
 * at), whether the unit is still at that digest, a songbook's files' records (kv `songbook:<folder>`), and the policy
 * a page is served with (viewer_csp of its very bytes: their own policy, with the viewer's sandbox).
 */
interface PhonePages {
    fun written(db: Db, songId: Long, name: String): Written?
    fun current(db: Db, songId: Long, name: String): Boolean
    fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>>
    fun csp(page: ByteArray): String

    companion object {
        /** WrittenPages' records, and SheetPage.viewerCsp (book.songbook_csp is viewer_csp too). */
        val WRITTEN: PhonePages = object : PhonePages {
            override fun written(db: Db, songId: Long, name: String): Written? = WrittenPages.written(db, songId, name)
            override fun current(db: Db, songId: Long, name: String): Boolean = WrittenPages.current(db, songId, name)
            override fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>> =
                WrittenPages.songbook(db, folder)
            override fun csp(page: ByteArray): String = SheetPage.viewerCsp(page)
        }

        /** No page of the phone's. A Phase A guard, waiting on: phone-render, whose WrittenPages records the pages it
         * writes; [LibraryFiles] reads [WRITTEN] once it merges. */
        val NONE: PhonePages = object : PhonePages {
            override fun written(db: Db, songId: Long, name: String): Written? = null
            override fun current(db: Db, songId: Long, name: String): Boolean = false
            override fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>> = emptyMap()
            override fun csp(page: ByteArray): String = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
        }
    }
}

/**
 * A library file at a path no route answers (App asks only then), as web/files.py serves one: the parts of the
 * path checked (no empty part, `.`, `..`, hidden name or NUL), then
 *
 * 1. a page caracole writes (app.py's `written_page`: a sheet's viewer, `sheet.html` and `sheet (auto).html`, a kept
 *    version's, `version-<tab>.html`, a harmonica tab's, `harmonica-N.html`, a songbook's, `songbook.html` in
 *    `_songbooks/<folder>/`): the phone's own ([pages]' records, the song's in the songs whose folder it is in, the
 *    songbook's by its folder) while it is the bytes recorded (files.read_written_page: a regular file reached through
 *    no link, of a recorded size and SHA-256, read once and served as read) and its song's unit is still at the
 *    digest it was made at, with its own policy and the viewer's sandbox (web/app.py's `_written_page`); else the
 *    mirror's, as below. One changed on disk, or of a unit moved since, is never served: the mirror's then, or a
 *    message page saying so;
 * 2. else the phone's own folder, [libraryDir]: a file its `files` table records at that path, or one the phone wrote
 *    there while it is current as a page is (a sheet's .cho), of a kind files.py serves ([FileTypes]: never a page),
 *    a regular file under [libraryDir] reached through no link, at most 64 MiB; a download named for its song
 *    (download_names.py);
 * 3. else the [mirror]'s file at that path, with the headers caracole serve listed for it exactly (a page's policy,
 *    sandbox and all), its unit checked by [gate]: a song the phone changed since answers the message page and
 *    links to the phone's sheet.txt when it keeps one; a song it removed says so.
 *
 * Null for none: the App answers 404.
 */
class LibraryFiles(val libraryDir: File, val mirror: Mirror?, val gate: UnitGate, val database: Database,
                   pages: PhonePages = PhonePages.NONE) {
    /** The library the message pages name, read for each: the App's, which sets it. */
    internal var name: () -> LibraryName = { LibraryName.phone(null) }

    /** The records of the pages the phone wrote (a test sets its own). */
    internal var pages: PhonePages = pages

    fun serve(path: String): Response? {
        if (!path.startsWith("/")) return null
        val relative = path.substring(1)
        val parts = relative.split('/')
        if (parts.any { it.isEmpty() || it == "." || it == ".." || it.startsWith(".") || '\u0000' in it }) return null
        if (isPage(parts.last())) return page(relative, parts)
        return own(relative, parts) ?: writtenFile(parts) ?: mirrored(relative)
    }

    /** What the phone wrote at a path, as its records and the file say. */
    private sealed interface Found {
        /** Its bytes, as recorded, at the digest of the unit it was made at. */
        class Current(val bytes: ByteArray) : Found

        /** As recorded, of a unit moved since ([unit]: its song's). */
        class Moved(val unit: String?) : Found

        /** Recorded, but not as the file is now (changed on disk, gone, a link in its place). */
        data object Changed : Found

        /** No record of it. */
        data object None : Found
    }

    /** A record of the phone's, with whether its unit is still where it was made, and the unit (a song's). */
    private class Record(val written: Written, val current: Boolean, val unit: String?)

    /** The page at [relative]: the phone's while it is current, else the mirror's, else why neither. */
    private fun page(relative: String, parts: List<String>): Response? = when (val found = found(parts)) {
        is Found.Current -> Response(200, Body.Bytes(found.bytes), mutableListOf(
            "Content-Type" to HTML, "Content-Security-Policy" to "${pages.csp(found.bytes)}; ${App.FRAMES}"))
        is Found.Moved -> mirrored(relative) ?: MessagePage.page(
            409, "Changed on the phone", "This song changed on the phone since its page was made.",
            sheetOf(found.unit)?.let { it to "The phone's sheet" }, name())
        Found.Changed -> mirrored(relative) ?: MessagePage.page(404, "Not sent", REFUSED, name = name())
        Found.None -> mirrored(relative)
    }

    /** A file the phone wrote that isn't a page (a sheet's .cho), while it is current as a page is; null otherwise. */
    private fun writtenFile(parts: List<String>): Response? {
        val suffix = PyText.asciiLower(FileTypes.suffix(parts.last()))
        val type = FileTypes.TYPES[suffix]?.takeIf { suffix !in FileTypes.DOWNLOADS } ?: return null
        val found = found(parts) as? Found.Current ?: return null
        return Response(200, Body.Bytes(found.bytes), mutableListOf("Content-Type" to type))
    }

    /** What the phone wrote at [parts]: its records (a songbook's by its folder, a song's by the songs whose folder
     * it is in), then the file, read once, against them. */
    private fun found(parts: List<String>): Found {
        val records = database.read { db -> records(db, parts) }
        if (records.isEmpty()) return Found.None
        val bytes = recordedBytes(parts, records.mapTo(HashSet()) { it.written.size }) ?: return Found.Changed
        val sha = Canonical.sha256Hex(bytes)
        val same = records.filter { it.written.sha256 == sha && it.written.size == bytes.size.toLong() }
        return when {
            same.any { it.current } -> Found.Current(bytes)
            same.isNotEmpty() -> Found.Moved(same.first().unit)
            else -> Found.Changed
        }
    }

    private fun records(db: Db, parts: List<String>): List<Record> {
        val name = parts.last()
        if (parts.size == 3 && parts[0] == SONGBOOKS) {
            val (sha, size) = pages.songbook(db, parts[1])[name] ?: return emptyList()
            return listOf(Record(Written(sha, size, ""), current = true, unit = null))
        }
        if (parts.size != 3) return emptyList()
        return songsInFolder(db, parts[0], parts[1]).mapNotNull { (id, key) ->
            pages.written(db, id, name)?.let { Record(it, pages.current(db, id, name), SONG + key) }
        }
    }

    /** library.songs_in_folder: the songs whose folder is [artist]/[title], newest first: (id, key). */
    private fun songsInFolder(db: Db, artist: String, title: String): List<Pair<Long, String>> =
        db.query("SELECT id, key, artist, title FROM songs ORDER BY added_at DESC, id DESC") {
            Triple(it.long(0)!! to it.text(1)!!, it.text(2)!!, it.text(3)!!)
        }.filter { SafeName.songFolder(it.second, it.third) == (artist to title) }.map { it.first }

    /** The bytes of the regular file at [parts], read once through no link, when its size is one of [sizes]; null
     * otherwise (no such file, a link, a folder, another size, a disk error). */
    private fun recordedBytes(parts: List<String>, sizes: Set<Long>): ByteArray? {
        val (path, size) = regular(parts) ?: return null
        if (size !in sizes) return null
        return try {
            Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readNBytes((FileTypes.MAX_BYTES + 1).toInt()) }
                .takeIf { it.size.toLong() in sizes }
        } catch (e: NoSuchFileException) {
            null
        } catch (e: IOException) {
            null
        }
    }

    /** Whether [name] is a page caracole writes (app.py's written_page; index.html aside, which the phone never
     * writes: its library page is its own). */
    private fun isPage(name: String): Boolean =
        name in SHEET_PAGES || name == SONGBOOK_PAGE ||
            SheetVersions.tabOf(name)?.let { SheetVersions.versionNames(it).third == name } == true ||
            PyRe.fullmatch(HARMONICA_PAGE, name) != null

    private class Kept(val artist: String, val title: String)

    private fun own(relative: String, parts: List<String>): Response? {
        val suffix = PyText.asciiLower(FileTypes.suffix(parts.last()))
        val type = FileTypes.TYPES[suffix] ?: return null
        val kept = database.read { db ->
            db.one("SELECT s.artist, s.title FROM files f JOIN songs s ON s.id = f.song_id WHERE f.path = ?", relative) {
                Kept(it.text(0)!!, it.text(1)!!)
            }
        } ?: return null
        val file = regularFile(parts) ?: return null
        val headers = mutableListOf("Content-Type" to type)
        if (suffix in FileTypes.DOWNLOADS) {
            val named = DownloadNames.downloadName(kept.artist, Normalize.cleanTitle(kept.title), parts.last())
            headers.add("Content-Disposition" to DownloadNames.contentDisposition(named))
        }
        return Response(200, Body.FromFile(file, file.length()), headers)
    }

    /** The file at [parts] under [libraryDir] ([regular]'s), or null. */
    private fun regularFile(parts: List<String>): File? = regular(parts)?.first?.toFile()

    /** The file at [parts] under [libraryDir] and its size: each folder on the way a folder and no link, the file a
     * regular file and no link, within the library once resolved, at most [FileTypes.MAX_BYTES]; null otherwise (a
     * name the file system can't hold among them). */
    private fun regular(parts: List<String>): Pair<Path, Long>? {
        try {
            val root = libraryDir.toPath().toRealPath()
            var at: Path = root
            for (part in parts.dropLast(1)) {
                at = at.resolve(part)
                if (!Files.isDirectory(at, LinkOption.NOFOLLOW_LINKS)) return null
            }
            val file = at.resolve(parts.last())
            val info = Files.readAttributes(file, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
            if (!info.isRegularFile || info.size() > FileTypes.MAX_BYTES) return null
            return if (file.toRealPath(LinkOption.NOFOLLOW_LINKS).startsWith(root)) file to info.size() else null
        } catch (e: IOException) {
            return null
        } catch (e: InvalidPathException) {
            return null
        }
    }

    private fun mirrored(relative: String): Response? {
        val mirror = mirror ?: return null
        return when (val looked = mirror.pageFor(relative, gate)) {
            is Looked.Page -> Response(200, Body.FromFile(looked.file, looked.file.length()),
                                       (listOf("Content-Type" to looked.entry.type) + looked.entry.headers.toList()).toMutableList())
            is Looked.Gated -> when (looked.gate) {
                Gate.REMOVED -> MessagePage.page(410, "Removed on the phone", "This song was removed on the phone.", name = name())
                else -> MessagePage.page(409, "Changed on the phone",
                                         "This song changed on the phone since the computer made its page.",
                                         sheetOf(looked.entry.unit)?.let { it to "The phone's sheet" }, name())
            }
            Looked.Missing -> null
        }
    }

    /** The address of the sheet.txt the phone keeps for the song of [unit], or null: one its `files` records that
     * [serve] answers (on disk, a regular file under the library), never a link that would 404. */
    private fun sheetOf(unit: String?): String? {
        val key = unit?.takeIf { it.startsWith("song/") }?.removePrefix("song/") ?: return null
        val path = database.read { db ->
            db.one("SELECT f.path FROM files f JOIN songs s ON s.id = f.song_id WHERE s.key = ? AND f.name = ?",
                   key, SHEET) { it.text(0) }
        } ?: return null
        val parts = path.split('/')
        if (parts.any { it.isEmpty() || it == "." || it == ".." || it.startsWith(".") || '\u0000' in it }) return null
        if (regularFile(parts) == null) return null
        return "/" + parts.joinToString("/") { PyUrl.quote(it, safe = "") }
    }

    private companion object {
        const val SHEET = "sheet.txt"
        const val SONG = "song/"
        const val HTML = "text/html; charset=utf-8"

        /** render.py's HUMAN_OUTPUTS[2] and AUTO_OUTPUTS[2]: a sheet's viewer. */
        val SHEET_PAGES = setOf("sheet.html", "sheet (auto).html")

        /** songbook.FOLDER and HTML_NAME. */
        const val SONGBOOKS = "_songbooks"
        const val SONGBOOK_PAGE = "songbook.html"

        /** inbox.HARMONICA_PAGE. */
        val HARMONICA_PAGE by lazy { PyRegex.compile("""harmonica-(\d+)\.html""") }

        /** What a page of the phone's says when it isn't sent (app.py's refusals, the phone's words). */
        const val REFUSED = "This page isn't the one the phone made here (it changed since), so it isn't sent."
    }
}
