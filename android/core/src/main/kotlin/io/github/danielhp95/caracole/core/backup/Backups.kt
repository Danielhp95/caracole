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
 * the bytes of the library's files it keeps). */
data class Backup(val file: File, val at: Instant, val label: String?, val size: Long)

/** What a restore did to the library's files: how many it wrote (a kept file from its blob, the lyrics of a row) and
 * removed (a file kept since the backup, lyrics a row no longer has), and the kept files whose bytes it couldn't put
 * back ([missing], by path: none was kept, and the library's file no longer holds them). */
data class Restored(val written: Int, val removed: Int, val missing: List<String>)

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
 * Every method that reads or writes the database is called inside Database.write (or, for [restore], takes it).
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

    /** A backup of [db]'s library tables and of [lib]'s kept files, labelled [label], made [now]: its file, or null,
     * and none made, without free space of twice what it needs. IllegalArgumentException for a label not in
     * [LABELS]. */
    fun make(db: Db, lib: LibraryStore, stateDir: File, now: Instant, label: String): File? =
        makeAt(db, lib, stateDir, Stamps.of(now), label)

    /** [make] at [stamp] (a stored time); [lib] null: the tables alone (Take.backupBeforeSync given no library). */
    internal fun makeAt(db: Db, lib: LibraryStore?, stateDir: File, stamp: String, label: String): File? {
        require(label in LABELS) { "no backup is labelled $label: a backup is ${LABELS.joinToString(", ")}" }
        val folder = File(stateDir, FOLDER)
        folder.mkdirs()
        folder.listFiles()?.filter { it.isFile && it.name.endsWith(PART) }?.forEach { it.delete() }
        val target = File(folder, "$label-${Stamps.stampOf(stamp).replace(":", "")}$SUFFIX")
        val part = File(folder, "${target.name}.${hex(6)}$PART")
        val blobs = File(folder, BLOBS)
        val kept = if (lib == null) emptyList() else keptRows(db)
        try {
            BackupTables.fresh(part)
            val fresh = kept.groupBy { it.second }.filterKeys { !File(blobs, it).isFile }
            val bytes = fresh.values.sumOf { rows -> rows.firstNotNullOfOrNull { size(lib!!, it.first) } ?: 0L }
            if (freeSpace(folder) < 2 * (part.length() + BackupTables.payload(db) + bytes)) return null
            BackupTables.copyInto(db, part)
            check(part)
            for ((sha, rows) in fresh) keepBlob(lib!!, blobs, sha, rows.map { it.first })
            Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } finally {
            part.delete()
        }
        rotate(folder, label, target)
        sweep(folder)
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
        val kept = BackupTables.shasOf(file).sumOf { sha -> File(blobs, sha).takeIf { it.isFile }?.length() ?: 0L }
        return Backup(file, at, label, file.length() + kept)
    }

    /** The name an exported [backup] is offered under: `caracole-<label>-<UTC time>.zip`. */
    fun exportName(backup: Backup): String = "caracole-${backup.file.name.removeSuffix(SUFFIX)}.zip"

    /**
     * The backup [file] written to [out] as one zip: the copy under its own name, then each kept file it names that
     * its folder holds, as `blobs/<sha256>`, by SHA-256. [out] is left open for its caller to close.
     */
    fun exportTo(file: File, out: OutputStream) {
        require(of(file) != null) { "no backup at $file" }
        val blobs = File(file.parentFile, BLOBS)
        val zip = ZipOutputStream(out)
        zip.putNextEntry(ZipEntry(file.name))
        file.inputStream().use { it.copyTo(zip) }
        zip.closeEntry()
        for (sha in BackupTables.shasOf(file).sorted()) {
            val blob = File(blobs, sha)
            if (!blob.isFile) continue
            zip.putNextEntry(ZipEntry("$BLOBS/$sha"))
            blob.inputStream().use { it.copyTo(zip) }
            zip.closeEntry()
        }
        zip.finish()
        zip.flush()
    }

    /**
     * [file]'s library back into [database], in one write: this side's own records read ([keep]), the library's
     * tables put back as the backup has them (BackupTables.restore: a file that is no backup of this caracole's is
     * refused and nothing changes) and those records written over them ([putBack]), in one savepoint; then the
     * library's files made the rows': each kept file whose bytes its file doesn't hold written from its blob, each
     * kept file of the rows before that the backup doesn't name deleted while it holds its row's bytes, and each
     * song's lyrics files written as its row has them. A failure there leaves the tables restored and the files as
     * far as it got: restoring again finishes it.
     */
    fun restore(database: Database, lib: LibraryStore, file: File,
                keep: (Db) -> JsonObject = OwnRecords::document,
                putBack: (Db, JsonObject) -> Unit = OwnRecords::putBack): Restored = database.writeBlocking { db ->
        val before = keptRows(db)
        BackupTables.restore(db, file) { copy ->
            val own = keep(db)
            copy()
            putBack(db, own)
        }
        putFiles(db, lib, File(file.parentFile, BLOBS), before)
    }

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

    /** The bytes of [sha] kept as `blobs/<sha>` from the first of [paths] whose file holds them, read once and checked
     * as they are copied; none kept when no file holds them any more. */
    private fun keepBlob(lib: LibraryStore, blobs: File, sha: String, paths: List<String>) {
        for (rel in paths) {
            val source = try {
                place(lib, rel)
            } catch (_: IOException) {
                continue
            }
            if (LibraryFiles.entry(source)?.isRegularFile != true) continue
            blobs.mkdirs()
            val tmp = File(blobs, ".$sha.${hex(4)}$PART").toPath()
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                FileChannel.open(source, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS).use { from ->
                    FileChannel.open(tmp, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { to ->
                        val buffer = ByteBuffer.allocate(1 shl 16)
                        while (from.read(buffer) >= 0) {
                            buffer.flip()
                            digest.update(buffer.duplicate())
                            while (buffer.hasRemaining()) to.write(buffer)
                            buffer.clear()
                        }
                        to.force(true)
                    }
                }
                if (JsonText.hex(digest.digest()) == sha) {
                    Files.move(tmp, File(blobs, sha).toPath(), StandardCopyOption.ATOMIC_MOVE)
                    return
                }
            } catch (_: IOException) {
                // This file couldn't be read: another of the same bytes may be.
            } finally {
                Files.deleteIfExists(tmp)
            }
        }
    }

    /** The library's files made the restored rows' (see [restore]). */
    private fun putFiles(db: Db, lib: LibraryStore, blobs: File, before: List<Pair<String, String>>): Restored {
        var written = 0
        var removed = 0
        val missing = ArrayList<String>()
        val after = keptRows(db)
        for ((rel, sha) in after) {
            val path = place(lib, rel)
            if (Place.holds(path, sha, null)) continue
            val bytes = File(blobs, sha).takeIf { it.isFile }?.readBytes()
            if (bytes == null || JsonText.hex(MessageDigest.getInstance("SHA-256").digest(bytes)) != sha) {
                missing += rel
                continue
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
        return Restored(written, removed, missing)
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

    /** The copies of [label] beyond its newest [KEEP] deleted, never [made]. */
    private fun rotate(folder: File, label: String, made: File) {
        val copies = folder.listFiles()?.filter { it.isFile && named(it.name)?.first == label }
            ?.sortedBy { it.name } ?: return
        copies.filter { it != made }.take(maxOf(0, copies.size - KEEP)).forEach { it.delete() }
    }

    /** Each kept file's bytes no backup names any more deleted, with what a copy left half made. */
    private fun sweep(folder: File) {
        val blobs = File(folder, BLOBS)
        val held = blobs.listFiles() ?: return
        val named = folder.listFiles()?.filter { it.isFile && named(it.name) != null }
            ?.flatMap { BackupTables.shasOf(it) }?.toSet() ?: emptySet()
        for (blob in held) if (blob.isFile && (blob.name.endsWith(PART) || blob.name !in named)) blob.delete()
    }

    private fun hex(n: Int): String = JsonText.hex(ByteArray(n).also { random.nextBytes(it) })
}
