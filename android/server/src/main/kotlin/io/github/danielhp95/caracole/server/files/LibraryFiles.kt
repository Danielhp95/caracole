package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.Looked
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.mirror.pageFor
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.PyText
import io.github.danielhp95.caracole.server.http.PyUrl
import io.github.danielhp95.caracole.server.http.Response
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.InvalidPathException
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes

/** Whether the mirror may serve a page of a unit as the computer made it: the phone's own state decides. A song
 * the phone removed (a tombstone of its key, no song) is REMOVED; a unit whose digest on the phone now differs from
 * the one the computer listed with the page is CHANGED (until lane sync-units, the phone knows no digest, so
 * nothing is); anything else is served. */
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
 * A library file at a path no route answers (App asks only then), as web/files.py serves one: the parts of the
 * path checked (no empty part, `.`, `..`, hidden name or NUL), then
 *
 * 1. the phone's own folder, [libraryDir]: only a file its `files` table records at that path, of a kind files.py
 *    serves ([FileTypes]: never a page), a regular file under [libraryDir] reached through no link, at most 64 MiB;
 *    a download named for its song (download_names.py);
 * 2. else the [mirror]'s file at that path, with the headers caracole serve listed for it exactly (a page's policy,
 *    sandbox and all), its unit checked by [gate]: a song the phone changed since answers the message page and
 *    links to the phone's sheet.txt when it keeps one; a song it removed says so.
 *
 * Null for none: the App answers 404.
 */
class LibraryFiles(val libraryDir: File, val mirror: Mirror?, val gate: UnitGate, val database: Database) {
    /** The library the message pages name: the App's, which sets it. */
    internal var name: LibraryName = LibraryName(AppConfig.PHONE, MessagePage.PHONE_BADGE)

    fun serve(path: String): Response? {
        if (!path.startsWith("/")) return null
        val relative = path.substring(1)
        val parts = relative.split('/')
        if (parts.any { it.isEmpty() || it == "." || it == ".." || it.startsWith(".") || '\u0000' in it }) return null
        return own(relative, parts) ?: mirrored(relative)
    }

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

    /** The file at [parts] under [libraryDir]: each folder on the way a folder and no link, the file a regular file
     * and no link, within the library once resolved, at most [FileTypes.MAX_BYTES]; null otherwise (a name the file
     * system can't hold among them). */
    private fun regularFile(parts: List<String>): File? {
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
            return if (file.toRealPath(LinkOption.NOFOLLOW_LINKS).startsWith(root)) file.toFile() else null
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
                Gate.REMOVED -> MessagePage.page(410, "Removed on the phone", "This song was removed on the phone.", name = name)
                else -> MessagePage.page(409, "Changed on the phone",
                                         "This song changed on the phone since the computer made its page.",
                                         sheetOf(looked.entry.unit)?.let { it to "The phone's sheet" }, name)
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
    }
}
