package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonObject

/** The library page's data: songs, fold, icons, catalogue, generated, songbooks, sites. */
interface PageData {
    fun data(db: Db, now: String): JsonObject
}

/** A song's card, as the page's data carries it, by the phone's song id. */
interface SongCards {
    fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject>
}
