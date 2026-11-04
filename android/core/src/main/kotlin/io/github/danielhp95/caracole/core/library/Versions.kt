package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonObject

/** versions.VersionRow: a row of `versions`. */
data class VersionRow(val id: Long, val provider: String, val tabId: String, val songId: Long, val slot: String,
                      val kind: String, val rating: Double, val votes: Int, val version: Int, val label: String?,
                      val coverage: Double?, val url: String, val raw: JsonObject, val fetchedAt: String,
                      val pickRank: Int?, val gone: Boolean, val stale: Boolean = false)

/** versions.py and songs.py's writers a site's pass calls. */
object Versions {
    fun upsert(db: Db, provider: String, tabId: String, songId: Long, slot: String, kind: String, rating: Double,
               votes: Int, version: Int, label: String?, url: String, raw: JsonObject, now: String): Long =
        TODO("lane library-writes")
    fun songVersions(db: Db, songId: Long, slot: String? = null, kinds: List<String>? = null,
                     includeGone: Boolean = false): List<VersionRow> = TODO("lane library-writes")
    fun get(db: Db, id: Long): VersionRow? = TODO("lane library-writes")
    fun setRaw(db: Db, id: Long, raw: JsonObject): Unit = TODO("lane library-writes")
    fun setCoverage(db: Db, id: Long, coverage: Double?): Unit = TODO("lane library-writes")
    fun markGone(db: Db, id: Long): Unit = TODO("lane library-writes")
    fun markStale(db: Db, songId: Long, provider: String): Unit = TODO("lane library-writes")
    fun setPicks(db: Db, songId: Long, picks: Map<String, Long?>): Unit = TODO("lane library-writes")
    fun updateSong(db: Db, songId: Long, columns: Map<String, Any?>): Unit = TODO("lane library-writes")
    fun refreshStatus(db: Db, songId: Long): Unit = TODO("lane library-writes")
}
