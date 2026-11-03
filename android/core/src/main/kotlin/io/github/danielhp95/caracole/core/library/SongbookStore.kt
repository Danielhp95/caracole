package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonArray

/** A songbook as the phone keeps it: its name key, its name, and its songs, `[[entry text, parts], …]`
 * (peer_sync.songbook_value's "songs"). */
data class StoredSongbook(val key: String, val name: String, val songs: JsonArray)

/**
 * songbooks.toml on the phone: table phone_songbooks (phone.sql), a row a songbook, `(key, name, songs, position)`:
 * its [nameKey], its name as written, the canonical text of its songs, and its place among the others. The writer is
 * called inside Database.write.
 */
object SongbookStore {
    /** songbook.name_key: NFC, whitespace (Python's) collapsed, casefold. */
    fun nameKey(name: String): String = PyUnicode.casefold(Py.split(PyUnicode.nfc(name)).joinToString(" "))

    /** Every songbook, in its place. */
    fun all(db: Db): List<StoredSongbook> =
        db.query("SELECT key, name, songs FROM phone_songbooks ORDER BY position, key") { book(it.text(0)!!, it.text(1)!!, it.text(2)!!) }

    /** songbook.put_songbook: make the songbook [name] hold [songs], found by its name in any case ([nameKey]) and
     * written under [name], in its place when it is there, else after the others; null takes it out. */
    fun put(db: Db, name: String, songs: JsonArray?) {
        val key = nameKey(name)
        if (songs == null) {
            db.execute("DELETE FROM phone_songbooks WHERE key = ?", key)
            return
        }
        db.execute(
            "INSERT INTO phone_songbooks (key, name, songs, position) " +
                "VALUES (?, ?, ?, (SELECT COALESCE(MAX(position) + 1, 0) FROM phone_songbooks)) " +
                "ON CONFLICT(key) DO UPDATE SET name = excluded.name, songs = excluded.songs",
            key, name, Canonical.write(songs),
        )
    }

    /** The songbook of name key [key], or null. */
    internal fun byKey(db: Db, key: String): StoredSongbook? =
        db.one("SELECT key, name, songs FROM phone_songbooks WHERE key = ?", key) { book(it.text(0)!!, it.text(1)!!, it.text(2)!!) }

    private fun book(key: String, name: String, songs: String): StoredSongbook =
        StoredSongbook(key, name, Canonical.parse(songs) as? JsonArray
            ?: throw IllegalStateException("the songbook $name's songs aren't a list"))
}
