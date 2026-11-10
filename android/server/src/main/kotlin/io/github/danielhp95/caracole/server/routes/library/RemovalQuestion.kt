package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What removing a song from the phone takes and leaves, as removal.brief and removal.describe say it on the computer:
 * the files the phone keeps for it and its entry go; nothing stays, since every file in its folder on the phone is
 * one a sync or an add wrote. The removal leaves a tombstone, so the song stays removed until it is asked for again.
 */
internal object RemovalQuestion {
    const val AFTER = "It stays gone from the phone until you ask again (the request form, or Fetch on a search's " +
        "line). The next share removes it from the computer's book too, unless you keep theirs."

    /** The question's data, `{removal: {song, key, display, brief, goes, stays, notes}}`, as remove_routes gives it. */
    fun data(db: Db, song: SongRow): JsonObject {
        val files = db.query("SELECT name FROM files WHERE song_id = ? ORDER BY name", song.id) { it.text(0)!! }
        val versions = db.one("SELECT COUNT(*) FROM versions WHERE song_id = ?", song.id) { it.long(0) } ?: 0L
        val goes = buildList {
            if (files.isNotEmpty()) add("${plural(files.size, "file")} the phone keeps for it: ${files.joinToString(", ")}")
            add("its entry on the phone: match, lyrics" +
                if (versions > 0) " and ${plural(versions.toInt(), "version")} seen" else "")
        }
        val brief = buildList {
            if (files.isNotEmpty()) add("the phone's ${plural(files.size, "file")} for it")
            add("its entry")
        }.let { "Deletes " + if (it.size > 1) it.dropLast(1).joinToString(", ") + " and " + it.last() + "." else it[0] + "." }
        return JsonObject(mapOf("removal" to JsonObject(linkedMapOf(
            "song" to JsonPrimitive(song.id), "key" to JsonPrimitive(song.key), "display" to JsonPrimitive(song.display),
            "brief" to JsonPrimitive(brief), "goes" to JsonArray(goes.map(::JsonPrimitive)),
            "stays" to JsonArray(emptyList()), "notes" to JsonArray(listOf(JsonPrimitive(AFTER))),
        ))))
    }

    private fun plural(n: Int, word: String) = "$n ${if (n == 1) word else word + "s"}"
}
