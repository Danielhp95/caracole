package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonArray

data class StoredSongbook(val key: String, val name: String, val songs: JsonArray)

/** songbooks.toml on the phone: table phone_songbooks (lane sync-units). */
object SongbookStore {
    /** songbook.name_key: NFC, whitespace collapsed, casefold. */
    fun nameKey(name: String): String = TODO("lane sync-units")
    fun all(db: Db): List<StoredSongbook> = TODO("lane sync-units")
    fun put(db: Db, name: String, songs: JsonArray?): Unit = TODO("lane sync-units")
}
