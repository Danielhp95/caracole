package io.github.danielhp95.caracole.core.backup

import io.github.danielhp95.caracole.core.backup.internal.BackupTables
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.JsonText
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.library.internal.writes.Place
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.MessageDigest
import java.security.SecureRandom
import java.time.Instant
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** backup.Backup: a copy in the folder, its file, when it was made (by its name), its label and size (the copy's and
 * the bytes of the library's files it keeps), and how many of the kept files it names it holds no bytes of
 * ([missing]: a copy of the tables alone, as M1–3's take made before a sync, or one of a file that no longer held its
 * row's bytes as it was made). A restore of one that misses any is refused unless the library's files still hold
 * them, and it can't be exported. */
data class Backup(val file: File, val at: Instant, val label: String?, val size: Long, val missing: Int = 0)

/** What a restore did to the library's files: how many it wrote (a kept file from its blob, the lyrics of a row) and
 * removed (a file kept since the backup, lyrics a row no longer has). */
data class Restored(val written: Int, val removed: Int)

/** A restore refused before it changed anything: the backup holds no bytes of the kept files at [paths] its rows
 * name, and the library's files there no longer hold them either, so the restore would leave rows naming bytes no
 * file holds. */
class NotRestorable(val paths: List<String>) : IllegalStateException(
    "the backup doesn't hold ${Backups.count(paths.size)}, and the library no longer does: ${Backups.some(paths)}")

/** A restore whose tables came back (in one savepoint) but not all of whose files did: a file that couldn't be
 * written or deleted ([cause]). Restoring the same backup again finishes it. */
class PartlyRestored(cause: IOException) : IOException(
    "its tables came back but not all its files (${cause.message ?: cause.javaClass.simpleName}): restore it again",
    cause)

/**
 * The phone's backups: the library's tables, as a whole openable database (BackupTables: caracole's schema and the
 * phone's, the index tables empty), and the library's kept files by their SHA-256 in `stateDir/backups/blobs/`, each
 * kept once however many backups hold it and gone with the last of them, so that a restore leaves no row naming bytes
 * that differ. Each is `stateDir/backups/<label>-<UTC time>.sqlite`, its label one of [LABELS] (made by hand, the
 * daily one, the one before a sync takes anything), the newest [KEEP] of each label kept. None is made without free
 * space of twice what it needs, and a copy takes no old one's place before SQLite's quick check of it says "ok".
 *
 * A restore puts the tables and the kept files back but keeps this side's own records as they are now ([OwnRecords]:
 * its cooldowns, its pace, the records that gate a request, its sync records, the computer's settings), so no cooldown
 * met since is forgotten and the restored library is the phone's own change, given to the computer at the next sync.
 * One that can't put back every kept file's bytes is refused whole ([NotRestorable]). Every method that reads or writes
 * the database is called inside Database.write (or, for [restore], takes it).
 *
 * A backup being exported ([exportTo]) is never rotated out, nor are the blobs it names swept, until its export ends.
 */
object Backups {
    const val BY_HAND = "by-hand"
    const val DAILY = "daily"
    const val BEFORE_SYNC = "before-sync"

    /** The labels a backup may have. */
    val LABELS: List<String> = listOf(BY_HAND, DAILY, BEFORE_SYNC)

    /** How many backups of each label are kept. */
    const val KEEP = 3

    /** `stateDir/backups/`, and its folder of kept files. */
    const val FOLDER = "backups"
    const val BLOBS = "blobs"

    private const val SUFFIX = ".sqlite"
    private const val PART = ".part"

    /** The bytes free where a copy goes (a test gives less). */
    @Volatile
    var freeSpace: (File) -> Long = { it.usableSpace }

    /** The check a copy passes before it takes its place (a test makes it fail). */
    @Volatile
    internal var check: (File) -> Unit = BackupTables::quickCheck

    private val random = SecureRandom()

    /** What [rotate] and [sweep] check under, and the backups being exported meanwhile (their absolute paths). */
    private val lock = Any()
    private val exporting = HashSet<String>()

    /** A backup of [db]'s library tables and of [lib]'s kept files, labelled [label], made [now]: its file, or null,
     * and none made, without free space of twice what it needs. IllegalArgumentException for a label not in
     * [LABELS]. */
    fun make(db: Db, lib: LibraryStore, stateDir: File, now: Instant, label: String): File? =
        makeAt(db, lib, stateDir, Stamps.of(now), label)

    /** [make] at [stamp] (a stored time): Take.backupBeforeSync's too. A blob that can't be written (no room, a write
     * that failed) is an IOException, and no backup is made: a file that can't be read, or no longer holds its row's
     * bytes, is one the backup doesn't hold ([Backup.missing]). */
    internal fun makeAt(db: Db, lib: LibraryStore, stateDir: File, stamp: String, label: String): File? {
        require(label in LABELS) { "no backup is labelled $label: a backup is ${LABELS.joinToString(", ")}" }
        val folder = File(stateDir, FOLDER)
        folder.mkdirs()
        folder.listFiles()?.filter { it.isFile && it.name.endsWith(PART) }?.forEach { it.delete() }
        val target = File(folder, "$label-${Stamps.stampOf(stamp).replace(":", "")}$SUFFIX")
        val part = File(folder, "${target.name}.${hex(6)}$PART")
        val blobs = File(folder, BLOBS)
        val kept = keptRows(db)
        try {
            BackupTables.fresh(part)
            val fresh = kept.groupBy { it.second }.filterKeys { !File(blobs, it).isFile }
            val bytes = fresh.values.sumOf { rows -> rows.firstNotNullOfOrNull { size(lib, it.first) } ?: 0L }
            if (freeSpace(folder) < 2 * (part.length() + BackupTables.payload(db) + bytes)) return null
            BackupTables.copyInto(db, part)
            check(part)
            for ((sha, rows) in fresh) keepBlob(lib, blobs, sha, rows.map { it.first })
            Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } catch (e: Throwable) {
            // The blobs this copy kept are named by no backup now.
            part.delete()
            runCatching { synchronized(lock) { sweep(folder) } }
            throw e
        } finally {
            part.delete()
        }
        synchronized(lock) {
            rotate(folder, label, target)
            sweep(folder)
        }
        return target
    }

    /** The backups in [stateDir], newest first. */
    fun list(stateDir: File): List<Backup> =
        (File(stateDir, FOLDER).listFiles()?.mapNotNull { of(it) } ?: emptyList())
            .sortedWith(compareByDescending<Backup> { it.at }.thenByDescending { it.file.name })

    /** The backup [file] is, by its name (a label of [LABELS], then its UTC time); null for a file that is none. */
    fun of(file: File): Backup? {
        if (!file.isFile) return null
        val (label, at) = named(file.name) ?: return null
        val blobs = File(file.parentFile, BLOBS)
        val shas = BackupTables.shasOf(file)
        val held = shas.mapNotNull { sha -> File(blobs, sha).takeIf { it.isFile }?.length() }
        return Backup(file, at, label, file.length() + held.sum(), shas.size - held.size)
    }

    /** The name an exported [backup] is offered under: `caracole-<label>-<UTC time>.zip`. */
    fun exportName(backup: Backup): String = "caracole-${backup.file.name.removeSuffix(SUFFIX)}.zip"

    /**
     * The backup [file] written to [out] as one zip: the copy under its own name, then each kept file it names, as
     * `blobs/<sha256>`, by SHA-256; an IOException naming them, and nothing written, for a backup that doesn't hold
     * every one ([Backup.missing]). Meanwhile the backup is never rotated out nor its blobs swept (a backup made
     * beside it, the daily one or a sync's). [out] is left open for its caller to close.
     */
    fun exportTo(file: File, out: OutputStream) {
        val key = file.toPath().toAbsolutePath().normalize().toString()
        synchronized(lock) {
            require(of(file) != null) { "no backup at $file" }
            exporting += key
        }
        try {
            val blobs = File(file.parentFile, BLOBS)
            val kept = BackupTables.keptOf(file)
            val lacking = kept.filter { !File(blobs, it.second).isFile }.map { it.first }
            if (lacking.isNotEmpty()) throw IOException("the backup doesn't hold ${count(lacking.size)}: ${some(lacking)}")
            val zip = ZipOutputStream(out)
            zip.putNextEntry(ZipEntry(file.name))
            file.inputStream().use { it.copyTo(zip) }
            zip.closeEntry()
            for (sha in kept.mapTo(sortedSetOf()) { it.second }) {
                zip.putNextEntry(ZipEntry("$BLOBS/$sha"))
                File(blobs, sha).inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
            zip.finish()
            zip.flush()
        } finally {
            synchronized(lock) { exporting -= key }
        }
    }

    /**
     * [file]'s library back into [database], in one write: this side's own records read ([keep]), the library's
     * tables put back as the backup has them (BackupTables.restore: a file that is no backup of this caracole's is
     * refused and nothing changes) and those records written over them ([putBack]), in one savepoint; then the
     * library's files made the rows': each kept file whose bytes its file doesn't hold written from its blob, each
     * kept file of the rows before that the backup doesn't name deleted while it holds its row's bytes, and each
     * song's lyrics files written as its row has them.
     *
     * Refused whole, before anything changes, when it couldn't put back every kept file's bytes ([NotRestorable]: one
     * the backup holds no blob of, checked by its SHA-256, whose file no longer holds them either) or a path of the
     * rows, the backup's or the library's now, is no place in the library (an IOException: a link on it, say). A write
     * that fails after the tables came back is a [PartlyRestored]: restoring again finishes it.
     */
    fun restore(database: Database, lib: LibraryStore, file: File,
                keep: (Db) -> JsonObject = OwnRecords::document,
                putBack: (Db, JsonObject) -> Unit = OwnRecords::putBack): Restored = database.writeBlocking { db ->
        val before = keptRows(db)
        val blobs = File(file.parentFile, BLOBS)
        BackupTables.restore(db, file) { copy ->
            refuseUnlessWhole(lib, blobs, BackupTables.keptInCopy(db), before)
            val own = keep(db)
            copy()
            putBack(db, own)
        }
        try {
            putFiles(db, lib, blobs, before)
        } catch (e: IOException) {
            throw PartlyRestored(e)
        }
    }

    /** "1 of its files", "3 of its files". */
    internal fun count(n: Int): String = if (n == 1) "1 of its files" else "$n of its files"

    /** The first few of [paths], for a line. */
    internal fun some(paths: List<String>): String =
        paths.take(3).joinToString(", ") + if (paths.size > 3) ", …" else ""

    // --- the kept files ---------------------------------------------------------------------------------------------

    /** Each kept file's path and SHA-256, in path order. */
    private fun keptRows(db: Db): List<Pair<String, String>> =
        db.query("SELECT path, sha256 FROM files ORDER BY path") { it.text(0)!! to it.text(1)!! }

    /** The library's file at [rel] (a `files.path`), no component a link, ".." or empty: IOException otherwise. */
    private fun place(lib: LibraryStore, rel: String): Path {
        val parts = rel.split('/')
        if (parts.any { it.isEmpty() || it == "." || it == ".." || '\u0000' in it || '\\' in it }) {
            throw IOException("$rel is no place in the library")
        }
        var at = lib.libraryDir.toPath()
        for ((i, part) in parts.withIndex()) {
            at = at.resolve(part)
            val attrs = LibraryFiles.entry(at) ?: return parts.drop(i + 1).fold(at) { p, rest -> p.resolve(rest) }
            if (attrs.isSymbolicLink || (i < parts.size - 1 && !attrs.isDirectory)) {
                throw IOException("${parts.take(i + 1).joinToString("/")} is " +
                                  (if (attrs.isSymbolicLink) LibraryFiles.LINK else "not a folder"))
            }
        }
        return at
    }

    /** The size of the regular file at [rel], or null. */
    private fun size(lib: LibraryStore, rel: String): Long? = try {
        LibraryFiles.entry(place(lib, rel))?.takeIf { it.isRegularFile }?.size()
    } catch (_: IOException) {
        null
    }

    /**
     * The bytes of [sha] kept as `blobs/<sha>` from the first of [paths] whose file holds them, read once and checked
     * as they are copied: true; false, and none kept, when no file holds them any more (gone, a link, unreadable, other
     * bytes). A blob that can't be written is an IOException.
     */
    private fun keepBlob(lib: LibraryStore, blobs: File, sha: String, paths: List<String>): Boolean {
        for (rel in paths) {
            val source = try {
                place(lib, rel)
            } catch (_: IOException) {
                continue
            }
            if (LibraryFiles.entry(source)?.isRegularFile != true) continue
            val from = try {
                FileChannel.open(source, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)
            } catch (_: IOException) {
                continue // This file can't be read: another of the same bytes may be.
            }
            blobs.mkdirs()
            val tmp = File(blobs, ".$sha.${hex(4)}$PART").toPath()
            try {
                val held = from.use { copied(it, tmp, sha) }
                if (held) {
                    Files.move(tmp, File(blobs, sha).toPath(), StandardCopyOption.ATOMIC_MOVE)
                    return true
                }
            } finally {
                Files.deleteIfExists(tmp)
            }
        }
        return false
    }

    /** [from] copied into the new file [to], synced: whether what it read was the bytes of [sha]. A read that fails
     * is false (the file is one the backup doesn't hold); a write that fails, an IOException. */
    private fun copied(from: FileChannel, to: Path, sha: String): Boolean {
        val digest = MessageDigest.getInstance("SHA-256")
        FileChannel.open(to, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { out ->
            val buffer = ByteBuffer.allocate(1 shl 16)
            while (true) {
                val n = try {
                    from.read(buffer)
                } catch (_: IOException) {
                    return false
                }
                if (n < 0) break
                buffer.flip()
                digest.update(buffer.duplicate())
                while (buffer.hasRemaining()) out.write(buffer)
                buffer.clear()
            }
            out.force(true)
        }
        return JsonText.hex(digest.digest()) == sha
    }

    /** [NotRestorable] unless each of the backup's kept files [rows] is held by its file now or by its blob (checked
     * by its SHA-256); an IOException for a path of [rows] or [before] that is no place in the library. */
    private fun refuseUnlessWhole(lib: LibraryStore, blobs: File, rows: List<Pair<String, String>>,
                                  before: List<Pair<String, String>>) {
        for ((rel, _) in before) place(lib, rel)
        val lacking = rows.filter { (rel, sha) ->
            !Place.holds(place(lib, rel), sha, null) && !Place.holds(File(blobs, sha).toPath(), sha, null)
        }.map { it.first }
        if (lacking.isNotEmpty()) throw NotRestorable(lacking)
    }

    /** The library's files made the restored rows' (see [restore]). */
    private fun putFiles(db: Db, lib: LibraryStore, blobs: File, before: List<Pair<String, String>>): Restored {
        var written = 0
        var removed = 0
        val after = keptRows(db)
        for ((rel, sha) in after) {
            val path = place(lib, rel)
            if (Place.holds(path, sha, null)) continue
            val bytes = File(blobs, sha).readBytes()
            if (JsonText.hex(MessageDigest.getInstance("SHA-256").digest(bytes)) != sha) {
                throw IOException("the backup's copy of $rel is no longer its bytes")
            }
            Place.writeAtomic(path, bytes)
            written++
        }
        val named = after.map { it.first }.toSet()
        for ((rel, sha) in before) {
            if (rel in named) continue
            val path = place(lib, rel)
            if (Place.holds(path, sha, null)) {
                Files.delete(path)
                removed++
            }
        }
        // Each song's lyrics as its row has them now, a name holding anything but a regular file left alone.
        for (song in Songs.list(db)) {
            val (folder, _) = Place.folder(lib, song)
            for ((name, data) in LyricsFiles.of(song.lyricsJson)) {
                val path = try {
                    place(lib, "$folder/$name")
                } catch (_: IOException) {
                    continue
                }
                val attrs = LibraryFiles.entry(path)
                if (attrs != null && !attrs.isRegularFile) continue
                val there = if (attrs == null) null else LibraryFiles.regularBytes(path)
                if (data == null) {
                    if (attrs != null) {
                        Files.delete(path)
                        removed++
                    }
                } else if (there == null || !there.contentEquals(data)) {
                    Place.writeAtomic(path, data)
                    written++
                }
            }
        }
        return Restored(written, removed)
    }

    // --- the folder -------------------------------------------------------------------------------------------------

    /** A backup's label and time by its name, `<label>-<yyyy-mm-ddTHHMMSSZ>.sqlite`; null for any other name. */
    private fun named(name: String): Pair<String, Instant>? {
        if (!name.endsWith(SUFFIX)) return null
        val label = LABELS.firstOrNull { name.startsWith("$it-") } ?: return null
        val stamp = name.substring(label.length + 1, name.length - SUFFIX.length)
        if (stamp.length != 18 || stamp[10] != 'T' || stamp[17] != 'Z') return null
        val iso = "${stamp.substring(0, 13)}:${stamp.substring(13, 15)}:${stamp.substring(15, 17)}Z"
        return try {
            label to Instant.parse(iso)
        } catch (_: Exception) {
            null
        }
    }

    /** The copies of [label] beyond its newest [KEEP] deleted, never [made] nor one being exported (under [lock]). */
    private fun rotate(folder: File, label: String, made: File) {
        val copies = folder.listFiles()?.filter { it.isFile && named(it.name)?.first == label }
            ?.sortedBy { it.name } ?: return
        copies.filter { it != made }.take(maxOf(0, copies.size - KEEP))
            .filter { it.toPath().toAbsolutePath().normalize().toString() !in exporting }
            .forEach { it.delete() }
    }

    /** Each kept file's bytes no backup names any more deleted, with what a copy left half made (under [lock]). */
    private fun sweep(folder: File) {
        val blobs = File(folder, BLOBS)
        val held = blobs.listFiles() ?: return
        val named = folder.listFiles()?.filter { it.isFile && named(it.name) != null }
            ?.flatMap { BackupTables.shasOf(it) }?.toSet() ?: emptySet()
        for (blob in held) if (blob.isFile && (blob.name.endsWith(PART) || blob.name !in named)) blob.delete()
    }

    private fun hex(n: Int): String = JsonText.hex(ByteArray(n).also { random.nextBytes(it) })
}
