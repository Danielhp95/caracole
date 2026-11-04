package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Db

/** A page the phone wrote, as kv `render:files:<song id>` records it: its bytes' SHA-256, their size, and the song
 * unit's digest it was made at. */
data class Written(val sha256: String, val size: Long, val unitDigest: String)

/** The records of the pages the phone writes (lane phone-render), which the phone serves while they are current
 * (lane written-pages). */
object WrittenPages {
    fun written(db: Db, songId: Long, name: String): Written? = TODO("lane phone-render")
    fun note(db: Db, songId: Long, name: String, bytes: ByteArray, unitDigest: String): Unit =
        TODO("lane phone-render")
    /** Whether the song's unit is still at the digest its page [name] was made at. */
    fun current(db: Db, songId: Long, name: String): Boolean = TODO("lane phone-render")
    /** A songbook's written files, kv `songbook:<folder>`: each name's SHA-256 and size. */
    fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>> = TODO("lane phone-render")
    fun noteSongbook(db: Db, folder: String, inputs: String, files: Map<String, ByteArray>): Unit =
        TODO("lane phone-render")
}
