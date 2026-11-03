package io.github.danielhp95.caracole.core.sync.internal.units

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.OverridesStore
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.UnitError
import io.github.danielhp95.caracole.core.sync.internal.units.Python.member
import io.github.danielhp95.caracole.core.sync.internal.units.Python.text
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Each kind of unit's value and document (peer_sync._unit, removed_value, songbook_value, artist_url_value), and a
 * value read back from a document alone (value_of_document), over the phone's database: its songs and tombstones,
 * and phone_overrides and phone_songbooks in place of overrides.toml and songbooks.toml.
 */
internal object Documents {
    /** A unit's value and, with [document], its document; null for a unit this side hasn't got. */
    fun unit(db: Db, unitId: String, document: Boolean): Pair<JsonElement, JsonObject?>? {
        val kind = unitId.substringBefore('/')
        val rest = unitId.substringAfter('/', "")
        return when (kind) {
            "song" -> {
                val song = Songs.byKey(db, rest) ?: return null
                val value = SongUnits.value(db, song)
                value to (if (document) SongUnits.document(db, song, value) else null)
            }
            "removed" -> {
                val stone = Cells.row(db, "SELECT artist, title, source_ids, removed_at FROM removed WHERE key = ?", rest)
                    ?: return null
                val value = removedValue(Cells.text(stone["artist"])!!, Cells.text(stone["title"])!!)
                value to (if (!document) null else JsonObject(LinkedHashMap(value).apply {
                    put("source_ids", Canonical.parse(Cells.text(stone["source_ids"])!!))
                    put("removed_at", stone.getValue("removed_at"))
                }))
            }
            "songbook" -> {
                val book = SongbookStore.byKey(db, rest) ?: return null
                val value = songbookValue(book.name, book.songs)
                value to value
            }
            "alias" -> {
                val slugs = OverridesStore.alias(db, rest) ?: return null
                slugs to JsonObject(mapOf("slugs" to slugs))
            }
            "artist_url" -> {
                val value = OverridesStore.artistUrl(db, rest) ?: return null
                value to value
            }
            "block" -> {
                // rest.isdigit() and int(rest) in the blocks: ASCII digits alone here, as every tab id is written.
                if (rest.isEmpty() || !rest.all { it in '0'..'9' }) return null
                val tab = rest.toLongOrNull() ?: return null
                if (tab !in OverridesStore.blocks(db)) return null
                JsonPrimitive(true) to JsonObject(mapOf("tab" to JsonPrimitive(tab)))
            }
            else -> null
        }
    }

    fun removedValue(artist: String, title: String): JsonObject =
        JsonObject(linkedMapOf("artist" to JsonPrimitive(artist), "title" to JsonPrimitive(title)))

    fun songbookValue(name: String, songs: JsonElement): JsonObject =
        JsonObject(linkedMapOf("name" to JsonPrimitive(name), "songs" to songs))

    fun artistUrlValue(name: String, page: JsonElement): JsonObject =
        JsonObject(linkedMapOf("name" to JsonPrimitive(name), "page" to page))

    /** value_of_document over any JSON value: null for none (JSON's null too); a UnitError for a value that isn't a
     * document of its unit's kind, or a kind this caracole doesn't know. */
    fun valueOf(unitId: String, doc: JsonElement?): JsonElement? {
        if (doc == null || doc is JsonNull) return null
        val kind = unitId.substringBefore('/')
        try {
            if (doc !is JsonObject) throw Python.Unread("TypeError", "not an object")
            when (kind) {
                "song" -> return SongUnits.valueOf(doc)
                "removed" -> return removedValue(text(member(doc, "artist")), text(member(doc, "title")))
                "songbook" -> {
                    val songs = member(doc, "songs")
                    if (songs !is JsonArray || !songs.all { it is JsonArray && it.size == 2 }) {
                        throw Python.Unread("TypeError", "songs that aren't pairs")
                    }
                    return songbookValue(text(member(doc, "name")), songs)
                }
                "alias" -> {
                    val slugs = member(doc, "slugs")
                    if (slugs !is JsonArray) throw Python.Unread("TypeError", "slugs that aren't a list")
                    return slugs
                }
                "artist_url" -> {
                    val name = text(member(doc, "name"))
                    return artistUrlValue(name, JsonPrimitive(text(member(doc, "page"))))
                }
                "block" -> {
                    if (!Python.isInt(member(doc, "tab"))) throw Python.Unread("TypeError", "a tab that isn't a number")
                    return JsonPrimitive(true)
                }
            }
        } catch (e: Python.Unread) {
            throw UnitError("its document can't be read (${e.kind}: ${e.message})")
        }
        throw UnitError("this caracole doesn't know units of kind ${Python.repr(kind)}")
    }
}
