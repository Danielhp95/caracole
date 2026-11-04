package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonObject

/** sheet_versions.SheetVersion. */
data class SheetVersion(val versionId: Long, val tabId: String, val number: Int?, val rating: Double?, val votes: Int?,
                        val label: String?, val note: String?, val coverage: Double?, val complete: Boolean?,
                        val rank: Int, val kept: Boolean, val chosen: Boolean, val gone: Boolean, val page: String?,
                        val url: String)

/** sheet_versions.py: a song's UG chords versions in rank order. */
object SheetVersions {
    fun versionNames(tabId: String): Triple<String, String, String> = TODO("lane rank-coverage")
    fun sheetKind(db: Db, songId: Long): String = TODO("lane rank-coverage")
    fun keptByYou(db: Db, songId: Long): List<String> = TODO("lane rank-coverage")
    fun noteKeptByYou(db: Db, songId: Long, tabId: String): Unit = TODO("lane rank-coverage")
    fun unkeepable(db: Db, songId: Long): List<String> = TODO("lane rank-coverage")
    fun noteUnkeepable(db: Db, songId: Long, tabId: String): Unit = TODO("lane rank-coverage")
    fun mayKeep(db: Db, songId: Long, versions: List<SheetVersion>, block: Collection<Long>): List<SheetVersion> =
        TODO("lane rank-coverage")
    fun sheetPins(db: Db, songId: Long, pins: List<Long>): List<Long> = TODO("lane rank-coverage")
    fun inLibrary(db: Db, songId: Long, policy: RankPolicy): List<SheetVersion> = TODO("lane rank-coverage")
    fun inLibraryOf(db: Db, songIds: Collection<Long>, policy: RankPolicy): Map<Long, List<SheetVersion>> =
        TODO("lane rank-coverage")
    fun asData(versions: List<SheetVersion>, total: Int): JsonObject = TODO("lane rank-coverage")
}
