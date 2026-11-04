package io.github.danielhp95.caracole.core.library.internal.overrides

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonElement

/** One entry of `phone_overrides` (phone.sql), as the writers read and write it: its value the canonical text of the
 * value overrides.song_entries yields, read back as JSON with its literals kept. */
internal object Rows {
    class Entry(val written: String, val value: JsonElement)

    fun get(db: Db, table: String, key: String): Entry? =
        db.one("SELECT written, value FROM phone_overrides WHERE tbl = ? AND key = ?", table, key) {
            Entry(it.text(0)!!, Canonical.parse(it.text(1)!!))
        }

    /** The entry written under [written] with [value], in place of any the key had (its place, its rowid, kept). */
    fun put(db: Db, table: String, key: String, written: String, value: JsonElement) {
        db.execute(
            "INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?) " +
                "ON CONFLICT(tbl, key) DO UPDATE SET written = excluded.written, value = excluded.value",
            table, key, written, Canonical.write(value),
        )
    }

    /** The entry's value made [value], under the name it is written under. */
    fun setValue(db: Db, table: String, key: String, value: JsonElement) {
        db.execute("UPDATE phone_overrides SET value = ? WHERE tbl = ? AND key = ?", Canonical.write(value), table, key)
    }

    fun delete(db: Db, table: String, key: String) {
        db.execute("DELETE FROM phone_overrides WHERE tbl = ? AND key = ?", table, key)
    }
}
