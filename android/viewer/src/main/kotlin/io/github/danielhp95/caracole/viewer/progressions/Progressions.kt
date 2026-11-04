package io.github.danielhp95.caracole.viewer.progressions

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonArray

/** progressions.Wanted: a progression asked for, its own key, every key a song may play it as, its catalogue name and
 * how it is said. */
data class Wanted(val key: String, val keys: Set<String>, val name: String?, val label: String)

/** progressions.Playing: a song that plays a progression, the sections that do, and the key its sheet was read in. */
data class Playing(val song: SongRow, val sections: List<String>, val key: String)

/** progressions.py: each song's progressions, kv `render:progressions:<song id>` (lane version-progressions). */
object Progressions {
    fun record(db: Db, songId: Long, cho: String, key: String?, keySource: String? = null): Unit =
        TODO("lane version-progressions")
    fun forget(db: Db, songId: Long): Unit = TODO("lane version-progressions")
    fun library(db: Db): Map<Long, JsonArray> = TODO("lane version-progressions")
    fun read(text: String): Wanted? = TODO("lane version-progressions")
    fun songsWith(db: Db, w: Wanted): List<Playing> = TODO("lane version-progressions")
}
