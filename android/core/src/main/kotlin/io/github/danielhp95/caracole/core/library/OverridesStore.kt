package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** overrides.toml's entries on the phone: table phone_overrides (lane sync-units). */
object OverridesStore {
    /** overrides.song_entries. */
    fun songEntries(db: Db, key: String): JsonObject = TODO("lane sync-units")
    fun putSongEntries(db: Db, key: String, written: String, entries: JsonObject?): Unit = TODO("lane sync-units")
    fun alias(db: Db, artistKey: String): JsonArray? = TODO("lane sync-units")
    fun putAlias(db: Db, artistKey: String, written: String, slugs: JsonArray?): Unit = TODO("lane sync-units")
    fun artistUrl(db: Db, artistKey: String): JsonObject? = TODO("lane sync-units")
    fun putArtistUrl(db: Db, artistKey: String, value: JsonObject?): Unit = TODO("lane sync-units")
    fun blocks(db: Db): List<Long> = TODO("lane sync-units")
    fun putBlock(db: Db, tab: Long, on: Boolean): Unit = TODO("lane sync-units")
}
