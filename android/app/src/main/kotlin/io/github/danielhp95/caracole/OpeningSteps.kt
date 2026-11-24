package io.github.danielhp95.caracole

import java.io.File
import java.io.IOException
import java.io.RandomAccessFile

/**
 * The steps the app goes through as it opens, which its opening screen shows under the logo (MainActivity's
 * `opening`, the owner's ask of 2026-11-23: "say beneath the logo what it is that is happening so that the user does
 * not feel like it's stuck"): the library's database opened (and first upgraded, after an update that brings a newer
 * schema), caracole's own server started, then the library page drawn.
 */
object OpeningSteps {
    enum class Step(val number: Int) { OPEN(1), START(2), DRAW(3) }

    /** The most of a WAL the opening reads: SQLite's own `journal_size_limit` for the phone (Database's 16 MiB). A WAL
     * past it is one a big write left mid-way (an index merge the app's end cut short); the opening can't say then. */
    const val MOST_WAL = 16L shl 20

    /**
     * Whether opening [database] will first upgrade it: the user_version SQLite will read ([userVersion]) is above 0
     * and under [schema], as core.db.Database migrates. Read with no SQLite and nothing written; a missing, new or
     * unreadable file, or one whose version can't be told, opens as ever.
     */
    fun updating(database: File, schema: Int): Boolean = userVersion(database)?.let { it in 1 until schema } ?: false

    /**
     * The user_version a connection to [database] would read, with no SQLite: the newest page 1 its WAL holds
     * committed ([walVersion]), else its own header's (bytes 60–63, big-endian). The phone's database is in WAL mode,
     * and a migration's `PRAGMA user_version` stays in the WAL until a checkpoint, which a process Android ends never
     * makes: the file's header alone would say an update is due that SQLite won't run. Null for a file that isn't a
     * database, or a WAL past [MOST_WAL].
     */
    fun userVersion(database: File): Int? = try {
        if (!database.isFile || database.length() < 100) null
        else {
            val head = ByteArray(64)
            RandomAccessFile(database, "r").use { it.readFully(head) }
            if (String(head, 0, 16, Charsets.US_ASCII) != "SQLite format 3\u0000") null
            else when (val wal = walVersion(File(database.path + "-wal"))) {
                Wal.None -> int(head, 60, bigEndian = true)
                Wal.Unknown -> null
                is Wal.Known -> wal.version
            }
        }
    } catch (e: IOException) {
        null
    }

    private sealed interface Wal {
        /** No WAL, or none of its frames commits a page 1: the file's header is what SQLite reads. */
        data object None : Wal
        data object Unknown : Wal
        data class Known(val version: Int) : Wal
    }

    /**
     * The user_version of the last page 1 [wal] commits, as SQLite's recovery reads a WAL (sqlite.org/fileformat2.html,
     * "The Write-Ahead Log"): its header's checksum right; then frame after frame, each read alone, while each has the
     * header's salts (an older generation's frames, after a restart, have others) and its running checksum right (a
     * frame cut short or torn has not), the first that hasn't ending the read; a frame's page held until a commit frame
     * (its database size not 0) ends its transaction.
     */
    private fun walVersion(wal: File): Wal {
        if (!wal.isFile || wal.length() < WAL_HEADER) return Wal.None
        if (wal.length() > MOST_WAL) return Wal.Unknown
        return RandomAccessFile(wal, "r").use { file ->
            val header = ByteArray(WAL_HEADER)
            file.readFully(header)
            val bigEndian = when (int(header, 0, bigEndian = true)) {
                MAGIC_BIG -> true
                MAGIC_LITTLE -> false
                else -> return Wal.None
            }
            val pageSize = int(header, 8, bigEndian = true)
            if (pageSize < 512 || pageSize > 65536 || pageSize and (pageSize - 1) != 0) return Wal.None
            val salts = int(header, 16, true) to int(header, 20, true)
            var sum = checksum(header, 0, 24, 0 to 0, bigEndian)
            if (sum != int(header, 24, true) to int(header, 28, true)) return Wal.None
            val frame = ByteArray(FRAME_HEADER)
            val page = ByteArray(pageSize)
            var pending: Int? = null
            var committed: Int? = null
            var at = WAL_HEADER.toLong()
            val length = file.length()
            while (at + FRAME_HEADER + pageSize <= length) {
                file.readFully(frame)
                if (int(frame, 8, true) to int(frame, 12, true) != salts) break
                file.readFully(page)
                sum = checksum(frame, 0, 8, sum, bigEndian)
                sum = checksum(page, 0, pageSize, sum, bigEndian)
                if (sum != int(frame, 16, true) to int(frame, 20, true)) break
                if (int(frame, 0, true) == 1) pending = int(page, 60, bigEndian = true)
                if (int(frame, 4, true) != 0) {  // a commit: its transaction's page 1, if it wrote one, is SQLite's
                    if (pending != null) committed = pending
                    pending = null
                }
                at += FRAME_HEADER + pageSize
            }
            committed?.let(Wal::Known) ?: Wal.None
        }
    }

    /** SQLite's WAL checksum of [bytes] from [from] to [to] (a multiple of 8) after [seed]: 32-bit words in the WAL's
     * order, summed in pairs, each sum wrapping. */
    private fun checksum(bytes: ByteArray, from: Int, to: Int, seed: Pair<Int, Int>, bigEndian: Boolean): Pair<Int, Int> {
        var (s0, s1) = seed
        var i = from
        while (i < to) {
            s0 += int(bytes, i, bigEndian) + s1
            s1 += int(bytes, i + 4, bigEndian) + s0
            i += 8
        }
        return s0 to s1
    }

    private fun int(bytes: ByteArray, at: Int, bigEndian: Boolean): Int = (0 until 4).fold(0) { n, i ->
        (n shl 8) or (bytes[at + if (bigEndian) i else 3 - i].toInt() and 0xff)
    }

    private const val WAL_HEADER = 32
    private const val FRAME_HEADER = 24
    private const val MAGIC_BIG = 0x377f0683
    private const val MAGIC_LITTLE = 0x377f0682
}
