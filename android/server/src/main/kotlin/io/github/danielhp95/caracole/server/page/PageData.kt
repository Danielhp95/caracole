package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject

/** The library page's data: songs, fold, icons, catalogue, generated, songbooks, sites. */
interface PageData {
    fun data(db: Db, now: String): JsonObject
}

/** A song's card, as the page's data carries it, by the phone's song id. */
interface SongCards {
    fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject>

    /** library_page.result_cards: what /api/search's rows show of each song as its line does (`links`, `source`,
     * `key`, `instruments`), by song id; by default its card's files, source, key and instruments. */
    fun results(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = cards(db, songs).mapValues { (_, card) ->
        JsonObject(linkedMapOf(
            "links" to (card["files"] ?: JsonArray(emptyList())), "source" to (card["source"] ?: JsonNull),
            "key" to (card["key"] ?: JsonNull), "instruments" to (card["instruments"] ?: JsonArray(emptyList())),
        ))
    }
}
