package io.github.danielhp95.caracole

import java.io.File
import java.io.RandomAccessFile

/**
 * The steps the app goes through as it opens, which its opening screen shows under the logo (MainActivity's
 * `opening`, the owner's ask of 2026-11-23: "say beneath the logo what it is that is happening so that the user does
 * not feel like it's stuck"): the library's database opened (and first upgraded, after an update that brings a newer
 * schema), caracole's own server started, then the library page drawn.
 */
object OpeningSteps {
    enum class Step(val number: Int) { OPEN(1), START(2), DRAW(3) }

    /**
     * Whether opening [database] will first upgrade it: its SQLite header's user_version (bytes 60–63, big-endian) is
     * above 0 and under [schema], as core.db.Database migrates. Read with no SQLite and nothing written; a missing,
     * new or unreadable file opens as ever.
     */
    fun updating(database: File, schema: Int): Boolean = try {
        if (!database.isFile || database.length() < 100) false
        else RandomAccessFile(database, "r").use { file ->
            val head = ByteArray(64)
            file.readFully(head)
            val magic = String(head, 0, 16, Charsets.US_ASCII) == "SQLite format 3\u0000"
            val version = (0 until 4).fold(0) { at, i -> (at shl 8) or (head[60 + i].toInt() and 0xff) }
            magic && version in 1 until schema
        }
    } catch (e: java.io.IOException) {
        false
    }
}
