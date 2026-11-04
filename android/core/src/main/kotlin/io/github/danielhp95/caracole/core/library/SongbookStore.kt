package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.songbooks.Songbooks
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
 * others. The writers are called inside Database.write: [put], a sync's take (songbook.put_songbook), and the rows'
 * own, which core.songbooks.Songbooks's writers call once they have checked what songbook.py checks.
 *
 * A songbook is found by its name's key computed now (songbook.find_songbook's `name_key(b.name) == key`), never by
 * the key stored beside it alone, so the units ([byKey], and Units.libraryState's `songbook/<name key>`) stay
 * Python's should PyUnicode's tables ever move; each writer then writes the key afresh.
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
     * written under its name as kept (Songbooks.checkName's), in its place when it is there, else after the others;
     * null takes it out. The same name and songs again write nothing; else no other songbook may have its name or
     * its folder (Songbooks.checkFree), so a take leaves a unit that would make two songbooks of one folder, as the
     * computer's does. Its refusals are SongbookErrors in songbook.py's words, and nothing is written.
     *
     * Each song is `[entry text, parts]`, and its parts are kept as songbook_value gives them back: only the key,
     * the mode, the capo and the instrument that say something (a null part is none), so what is stored is what a
     * songbook unit's value holds. The name is checked first, as put_songbook checks it; then an entry that isn't
     * a text and an object of those parts is refused (IllegalArgumentException). A take checks each song's setting
     * itself before it puts the songbook (Take.takeSongbook, as peer_sync._apply calls check_setting first), so a
     * unit with a bad name and a bad setting is left for its setting there, as on the computer.
     */
    fun put(db: Db, name: String, songs: JsonArray?) {
        val clean = Songbooks.checkName(name)
        val text = songs?.let { Canonical.write(JsonArray(it.map(::entry))) }
        val key = nameKey(clean)
        val books = all(db)
        val at = books.indexOfFirst { nameKey(it.name) == key }
        val held = books.getOrNull(at)
        if (text == null) {
            if (held != null) drop(db, held)
            return
        }
        if (held != null && held.name == clean && Canonical.write(held.songs) == text) return
        Songbooks.checkFreeOf(books.map { it.name }, clean, at)
        if (held == null) {
            db.execute(
                "INSERT INTO phone_songbooks (key, name, songs, position) " +
                    "VALUES (?, ?, ?, (SELECT COALESCE(MAX(position) + 1, 0) FROM phone_songbooks))",
                key, clean, text,
            )
        } else {
            db.execute("UPDATE phone_songbooks SET key = ?, name = ?, songs = ? WHERE key = ?", key, clean, text, held.key)
        }
    }

    /** The songbook [held] holding [songs] (each `[entry text, parts]` as stored) in its place, under its name. */
    internal fun replace(db: Db, held: StoredSongbook, songs: JsonArray) {
        db.execute("UPDATE phone_songbooks SET key = ?, name = ?, songs = ? WHERE key = ?", nameKey(held.name),
                   held.name, Canonical.write(JsonArray(songs.map(::entry))), held.key)
    }

    /** The songbook [held] under [name], in its place, its songs as they are. */
    internal fun rename(db: Db, held: StoredSongbook, name: String) {
        db.execute("UPDATE phone_songbooks SET key = ?, name = ? WHERE key = ?", nameKey(name), name, held.key)
    }

    /** The songbook [held] taken out. */
    internal fun drop(db: Db, held: StoredSongbook) {
        db.execute("DELETE FROM phone_songbooks WHERE key = ?", held.key)
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
