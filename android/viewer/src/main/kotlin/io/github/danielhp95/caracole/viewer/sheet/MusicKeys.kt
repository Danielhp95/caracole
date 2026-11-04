package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonObject
import java.io.File

/** keys.SongKey: a song's key and where it came from (one of keys.SOURCES). */
data class SongKey(val key: String, val source: String)

/** keys.py: a song's musical key over the phone's files and versions (lane sheet-keys). */
object MusicKeys {
    fun sheetKey(raw: JsonObject, markup: String?, capo: Int? = null): SongKey? = TODO("lane sheet-keys")
    fun songKey(db: Db, libraryDir: File, songId: Long): SongKey? = TODO("lane sheet-keys")
}
