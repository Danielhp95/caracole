package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.RemovedRow
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.NoSuchFileException
import java.nio.file.Path

/**
 * removal.py on the phone, which has no wanted.txt, no Music/ and no audio from YouTube: a song taken out for good,
 * its record deleted with its versions, kept files' rows and per-song kv, its tombstone left
 * ([Upsert.markRemoved]), then the files caracole wrote in its folder ([plan]'s `delete`: the phone's written pages
 * among them, by their records), and the folder, and its artist's, once empty. Files caracole didn't write stay.
 * vectors/library/remove.jsonl holds Python's answers.
 */
internal object Removal {
    private const val INFO = "info.json"
    private val LYRICS = listOf("lyrics.txt", "lyrics.lrc")

    /** songs.SHEET_OUTPUTS and TRADITIONAL_PDFS: what render.py makes of each kept sheet. */
    private val SHEET_OUTPUTS = linkedMapOf(
        "sheet.txt" to listOf("sheet.cho", "sheet.pdf", "sheet.html"),
        "sheet (auto).txt" to listOf("sheet (auto).cho", "sheet (auto).pdf", "sheet (auto).html"),
    )
    private val TRADITIONAL_PDFS = mapOf("sheet.txt" to "sheet (Traditional).pdf",
                                         "sheet (auto).txt" to "sheet (auto, Traditional).pdf")
    private const val FILES_KEY = "render:files:"
    private const val EXPORT_KV = "render:export:"

    /** Why an entry of the song's folder stays, by what it is. */
    private val WHY = mapOf("file" to "caracole didn't write it", "link" to LibraryFiles.LINK, "folder" to "a folder")

    /** What removing [song] would take and leave (removal.RemovalPlan, the phone's part of it). */
    data class Plan(val song: SongRow, val folder: List<String>, val delete: List<String>,
                    val keep: List<Pair<String, String>>, val folderProblem: String?, val elsewhere: List<String>)

    /** What a removal did: the files deleted, those left, whether the song's folder went. */
    data class Result(val tombstone: RemovedRow, val deleted: List<String>, val kept: List<Pair<String, String>>,
                      val folderGone: Boolean, val errors: List<String>)

    /** removal.plan_removal: this reads, and changes nothing. */
    fun plan(db: Db, libraryDir: File, song: SongRow): Plan {
        val folder = SafeName.songFolder(song.artist, song.title).toList()
        val (keptHere, elsewhere) = keptFiles(db, song, folder)
        var ours = caracoles(db, song, keptHere)
        val why = WHY.toMutableMap()
        // Two songs whose names make one folder: its info.json, lyrics and PDFs may be the other's.
        val other = songsInFolder(db, folder).firstOrNull { it.first != song.id }
        if (other != null) {
            ours = keptHere
            why["file"] = "the folder is ${Normalize.displayKey(other.second, other.third)}'s too"
        }
        val delete = mutableListOf<String>()
        val keep = mutableListOf<Pair<String, String>>()
        var problem: String? = null
        try {
            for ((name, kind) in LibraryFiles.entries(LibraryFiles.folder(libraryDir.toPath(), folder))) {
                if (kind == "file" && isCaracoles(name, ours)) delete += name
                else keep += name to (why[kind] ?: "not a regular file")
            }
        } catch (_: LibraryFiles.NoFolder) {
        } catch (e: LibraryFiles.NotFollowed) {
            problem = e.message
        }
        val order = Canonical.KEY_ORDER
        return Plan(song, folder, delete.sortedWith(order), keep.sortedWith { a, b ->
            order.compare(a.first, b.first).let { if (it != 0) it else order.compare(a.second, b.second) }
        }, problem, elsewhere)
    }

    /** removal.remove_song: the record out, its tombstone left, at [stamp] (a stored time), in one savepoint; then
     * the plan's files. */
    fun remove(db: Db, libraryDir: File, plan: Plan, stamp: String): Result {
        val song = plan.song
        val stone = db.savepoint("remove_song") {
            val stone = Upsert.markRemoved(db, song, stamp)
            SongKv.deleteSongKv(db, song.id)
            for (key in wantedKeys(song)) db.kvDelete(SongKv.FIRST_SEEN + key)
            db.execute("DELETE FROM songs WHERE id = ?", song.id) // its versions and files go with it
            stone
        }
        val deleted = mutableListOf<String>()
        val kept = plan.keep.toMutableList()
        val errors = mutableListOf<String>()
        var gone = false
        if (plan.folderProblem == null) {
            gone = deleteFiles(libraryDir.toPath(), plan, deleted, kept, errors)
        }
        return Result(stone, deleted, kept, gone, errors)
    }

    /** The files of [song] caracole wrote in its folder, which go with it when its folder changes (a take's move);
     * IllegalStateException naming why for a folder caracole won't enter. */
    fun caracolesFiles(db: Db, libraryDir: File, song: SongRow): List<String> {
        val plan = plan(db, libraryDir, song)
        plan.folderProblem?.let { throw IllegalStateException(it) }
        return plan.delete
    }

    /**
     * The phone's own written pages and .cho of [song] (kv `render:files:<id>`'s entries that name the unit digest each
     * was made at, WrittenPages'), those still as written in the song's folder now (library.holds: its bytes, through
     * no link): a take that moves or respells the song's folder deletes these rather than moving them, since the take
     * changed the song (its names are part of its unit), so they were made of the song as it was; its record goes
     * with them, and the phone's next render makes them again where the song is now. A computer's record (no unit:
     * render.py's) names none, and neither does a folder caracole won't enter, nor one two songs share.
     */
    fun phonesWritten(db: Db, libraryDir: File, song: SongRow): List<String> {
        val record = kvJson(db, "$FILES_KEY${song.id}") as? JsonObject ?: return emptyList()
        val parts = SafeName.songFolder(song.artist, song.title).toList()
        if (songsInFolder(db, parts).any { it.first != song.id }) return emptyList()
        val folder = try {
            LibraryFiles.folder(libraryDir.toPath(), parts)
        } catch (_: LibraryFiles.NoFolder) {
            return emptyList()
        } catch (_: LibraryFiles.NotFollowed) {
            return emptyList()
        }
        return record.mapNotNull { (name, entry) ->
            val (sha, size) = written(entry) ?: return@mapNotNull null
            if ('/' in name || name.startsWith(".") || '\u0000' in name) return@mapNotNull null
            name.takeIf { Kept.holds(folder.resolve(it), sha, size) }
        }.sortedWith(Canonical.KEY_ORDER)
    }

    /** removal._wanted_keys: the song's key, and its wanted.txt source ids. */
    private fun wantedKeys(song: SongRow): List<String> {
        val ids = SongKv.sourceIds(song.sourceIds)[SongKv.WANTED].orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
        return (listOf(song.key) + ids).distinct()
    }

    private fun deleteFiles(root: Path, plan: Plan, deleted: MutableList<String>, kept: MutableList<Pair<String, String>>,
                            errors: MutableList<String>): Boolean {
        val folder = try {
            LibraryFiles.folder(root, plan.folder)
        } catch (_: LibraryFiles.NoFolder) {
            return true
        } catch (e: LibraryFiles.NotFollowed) {
            errors += "${e.message}: nothing in it was deleted"
            return false
        }
        for (name in plan.delete) {
            val file = folder.resolve(name)
            val attrs = LibraryFiles.entry(file) ?: continue // gone already
            if (!attrs.isRegularFile) {
                kept += name to "no longer a regular file"
                continue
            }
            try {
                Files.delete(file)
            } catch (_: NoSuchFileException) {
                continue
            } catch (e: IOException) {
                errors += "can't delete ${plan.folder.joinToString("/")}/$name: ${e.message}"
                continue
            }
            deleted += name
        }
        // The folders, emptied, go too: the song's, then its artist's, unless they hold something.
        var gone = false
        var at: Path = folder
        for (depth in plan.folder.size downTo 1) {
            try {
                Files.delete(at)
            } catch (_: IOException) {
                break
            }
            if (depth == plan.folder.size) gone = true
            at = at.parent
        }
        return gone
    }

    /** removal._kept_files: the song's kept files in its folder, by name, and those the database places elsewhere. */
    private fun keptFiles(db: Db, song: SongRow, folder: List<String>): Pair<Set<String>, List<String>> {
        val here = LinkedHashSet<String>()
        val elsewhere = mutableListOf<String>()
        val prefix = folder.joinToString("/")
        for (path in db.query("SELECT path FROM files WHERE song_id = ? ORDER BY path", song.id) { it.text(0)!! }) {
            val parts = path.split('/').filter { it.isNotEmpty() && it != "." }
            if (parts.size > 1 && parts.dropLast(1).joinToString("/") == prefix) here += parts.last()
            else elsewhere += path
        }
        return here to elsewhere
    }

    /** removal._caracoles: the names of the files caracole wrote in the song's folder; on the phone, also every page
     * and .cho its records name (kv `render:files:<id>`, WrittenPages'), the phone's written pages. */
    private fun caracoles(db: Db, song: SongRow, keptHere: Set<String>): Set<String> {
        val ours = LinkedHashSet(keptHere)
        ours += INFO
        for ((sheet, outputs) in SHEET_OUTPUTS) {
            if (sheet in keptHere) {
                ours += outputs
                ours += TRADITIONAL_PDFS.getValue(sheet)
            }
        }
        (kvJson(db, "$FILES_KEY${song.id}") as? JsonObject)?.forEach { (name, entry) ->
            val tab = tabOf(name)
            if ((tab != null && name == "version-$tab.html") || isHarmonicaPage(name)) ours += name
            // The phone's written pages and .cho (WrittenPages' records, each naming the unit it was made at): it
            // makes no PDF, so no render record names its sheet's; a record of render.py's names no unit, and keeps
            // removal.py's answer.
            else if (isWritten(entry)) ours += name
        }
        for (key in listOf("render:${song.id}", "render:${song.id}:auto")) {
            val pdf = text((kvJson(db, key) as? JsonObject)?.get("pdf"))
            if (pdf != null) {
                val stem = pdf.removeSuffix(".pdf")
                ours += listOf(pdf, "$stem.cho", "$stem.html")
            }
            val twin = text((kvJson(db, "$key:trad") as? JsonObject)?.get("pdf"))
            if (twin != null && twin in TRADITIONAL_PDFS.values) ours += twin
        }
        (kvJson(db, "$EXPORT_KV${song.id}") as? JsonObject)?.values?.forEach { entry ->
            val pdf = text((entry as? JsonObject)?.get("pdf"))
            if (pdf != null && isExport(pdf)) ours += pdf
        }
        if (song.lyricsStatus == "found") ours += LYRICS
        return ours
    }

    private fun kvJson(db: Db, key: String) = SongKv.json(db.kvGet(key))

    /** Whether [entry] is the phone's own record of a file it wrote ([written]). */
    private fun isWritten(entry: JsonElement): Boolean = written(entry) != null

    /** The phone's own record of a file it wrote, WrittenPages': render.written_entry's reading of it, `{"sha256":
     * <a string>, "size": <an int>}` (a JSON integer, never a boolean or a float), with the `unit` digest it was made
     * at (a string), whatever else it holds; null for anything else, a record render.py wrote among them, which
     * names no unit: those keep removal._caracoles' reading (a version's or a tab's page alone). */
    private fun written(entry: JsonElement): Pair<String, Long>? {
        val record = entry as? JsonObject ?: return null
        val sha = record["sha256"] as? JsonPrimitive
        val size = record["size"] as? JsonPrimitive
        val unit = record["unit"] as? JsonPrimitive
        if (sha == null || !sha.isString || size == null || size.isString || unit == null || !unit.isString) return null
        val digits = size.content.removePrefix("-")
        if (digits.isEmpty() || !digits.all { it in '0'..'9' }) return null
        return size.content.toLongOrNull()?.let { sha.content to it }
    }

    private fun text(e: kotlinx.serialization.json.JsonElement?): String? =
        (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** songs.is_export: a sheet's PDF in another version, not the auto sheet's own nor a Traditional one. */
    private fun isExport(name: String) = name.startsWith("sheet (") && name.endsWith(").pdf") &&
        name !in SHEET_OUTPUTS.getValue("sheet (auto).txt") && name !in TRADITIONAL_PDFS.values

    /** sheet_versions.tab_of: `version-<[0-9]+>.(txt|json|html)`'s tab id. */
    private fun tabOf(name: String): String? {
        if (!name.startsWith("version-")) return null
        val rest = name.removePrefix("version-")
        val dot = rest.indexOf('.')
        if (dot <= 0) return null
        val tab = rest.substring(0, dot)
        if (!tab.all { it in '0'..'9' } || rest.substring(dot + 1) !in setOf("txt", "json", "html")) return null
        return tab
    }

    /** inbox.HARMONICA_PAGE, `harmonica-(\d+)\.html` with Python's \d. */
    private fun isHarmonicaPage(name: String): Boolean {
        if (!name.startsWith("harmonica-") || !name.endsWith(".html")) return false
        val digits = name.substring("harmonica-".length, name.length - ".html".length)
        return digits.isNotEmpty() && digits.codePoints().allMatch { PyUnicode.isDecimal(it) }
    }

    /** removal._is_caracoles: one of [ours], or what a write caracole didn't finish left beside one
     * (`.<name>.<8 hex>.tmp`). */
    private fun isCaracoles(name: String, ours: Set<String>): Boolean {
        if (name in ours) return true
        if (!name.startsWith(".") || !name.endsWith(".tmp") || name.length < 1 + 1 + 1 + 8 + 4) return false
        val hex = name.substring(name.length - 12, name.length - 4)
        if (name[name.length - 13] != '.' || !hex.all { it in '0'..'9' || it in 'a'..'f' }) return false
        val inner = name.substring(1, name.length - 13)
        return inner.isNotEmpty() && '\n' !in inner && inner in ours
    }

    /** library.songs_in_folder: the songs whose folder is [folder], newest first: (id, artist, title). */
    private fun songsInFolder(db: Db, folder: List<String>): List<Triple<Long, String, String>> {
        if (folder.size != 2) return emptyList()
        return db.query("SELECT id, artist, title FROM songs ORDER BY added_at DESC, id DESC") {
            Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }.filter { SafeName.songFolder(it.second, it.third).toList() == folder }
    }
}
