package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** A songbook as the phone keeps it: its name key, its name, and its songs, `[[entry text, parts], …]`
 * (peer_sync.songbook_value's "songs"). */
data class StoredSongbook(val key: String, val name: String, val songs: JsonArray)

/**
 * songbooks.toml on the phone: table phone_songbooks (phone.sql), a row a songbook, `(key, name, songs, position)`:
 * its [nameKey] when it was written, its name as written, the canonical text of its songs, and its place among the
 * others. The writer is called inside Database.write.
 *
 * A songbook is found by its name's key computed now (songbook.find_songbook's `name_key(b.name) == key`), never by
 * the key stored beside it alone, so the units ([byKey], and Units.libraryState's `songbook/<name key>`) stay
 * Python's should PyUnicode's tables ever move; [put] then writes the key afresh.
 */
object SongbookStore {
    /** The parts a song's setting in a songbook has (songbook.check_setting's), in song_value's order. */
    private val SETTING_PARTS = listOf("key", "mode", "capo", "instrument")

    /** songbook.name_key: NFC, whitespace (Python's) collapsed, casefold. */
    fun nameKey(name: String): String = PyUnicode.casefold(Py.split(PyUnicode.nfc(name)).joinToString(" "))

    /** Every songbook, in its place. */
    fun all(db: Db): List<StoredSongbook> =
        db.query("SELECT key, name, songs FROM phone_songbooks ORDER BY position, key") { book(it.text(0)!!, it.text(1)!!, it.text(2)!!) }

    /**
     * songbook.put_songbook: make the songbook [name] hold [songs], found by its name in any case ([nameKey]) and
     * written under [name], in its place when it is there, else after the others; null takes it out.
     *
     * Each song is `[entry text, parts]`, and its parts are kept as songbook_value gives them back: only the key,
     * the mode, the capo and the instrument that say something (a null part is none), so what is stored is what a
     * songbook unit's value holds. An entry that isn't a text and an object of those parts is refused
     * (IllegalArgumentException, as check_setting refuses an unknown part), and nothing is written.
     */
    fun put(db: Db, name: String, songs: JsonArray?) {
        val key = nameKey(name)
        val held = all(db).firstOrNull { nameKey(it.name) == key }
        if (songs == null) {
            if (held != null) db.execute("DELETE FROM phone_songbooks WHERE key = ?", held.key)
            return
        }
        val text = Canonical.write(JsonArray(songs.map(::entry)))
        if (held == null) {
            db.execute(
                "INSERT INTO phone_songbooks (key, name, songs, position) " +
                    "VALUES (?, ?, ?, (SELECT COALESCE(MAX(position) + 1, 0) FROM phone_songbooks))",
                key, name, text,
            )
        } else {
            db.execute("UPDATE phone_songbooks SET key = ?, name = ?, songs = ? WHERE key = ?", key, name, text, held.key)
        }
    }

    /** The songbook whose name's key is [key] now, or null. */
    internal fun byKey(db: Db, key: String): StoredSongbook? = all(db).firstOrNull { nameKey(it.name) == key }

    /** One song as a songbook unit holds it: its entry's text, and its setting's parts that say something. */
    private fun entry(song: JsonElement): JsonArray {
        val pair = song as? JsonArray
        val entry = pair?.getOrNull(0)
        val parts = pair?.getOrNull(1)
        require(pair != null && pair.size == 2 && entry is JsonPrimitive && entry.isString && parts is JsonObject) {
            "a songbook's song is [entry text, parts]: $song"
        }
        val unknown = parts.keys.filter { it !in SETTING_PARTS }
        require(unknown.isEmpty()) { "a song's setting has no part ${unknown.joinToString(", ")}: $song" }
        val kept = LinkedHashMap<String, JsonElement>()
        for (part in SETTING_PARTS) parts[part]?.takeUnless { it is JsonNull }?.let { kept[part] = it }
        return JsonArray(listOf(entry, JsonObject(kept)))
    }

    private fun book(key: String, name: String, songs: String): StoredSongbook =
        StoredSongbook(key, name, Canonical.parse(songs) as? JsonArray
            ?: throw IllegalStateException("the songbook $name's songs aren't a list"))
}
