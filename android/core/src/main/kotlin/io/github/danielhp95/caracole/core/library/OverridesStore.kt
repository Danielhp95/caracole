package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.sync.internal.units.Python
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * overrides.toml's entries on the phone: table phone_overrides (phone.sql), a row an entry, `(tbl, key, written,
 * value)`. A song's tables ([SONG_TABLES], and `ignore`) are keyed by its identity key, `alias` and `artist_url` by
 * the artist's key (slug_key), `block` by the tab id; `written` is the name overrides.toml writes the entry under
 * ("Artist - Title", the artist's name, the tab id); `value` is the canonical text (Canonical.write) of the value as
 * overrides.song_entries yields it, read back as JSON with its literals kept. The writers are called inside
 * Database.write.
 */
object OverridesStore {
    /** overrides.SONG_TABLES: the tables of entries about one song, in song_entries' order. */
    val SONG_TABLES: List<String> = listOf(
        "match", "pin", "transpose", "reject", "youtube", "lacuerda", "harptabs", "gametabs", "azlyrics", "version",
        "harmonica",
    )
    private const val IGNORE = "ignore"
    private val SONG_TABLES_IN = (SONG_TABLES + IGNORE).joinToString(", ") { "'$it'" }

    /** overrides.song_entries: every entry about the song of identity [key], by table, in [SONG_TABLES]' order then
     * `ignore` (true), only the tables that have one. */
    fun songEntries(db: Db, key: String): JsonObject {
        // By the primary key, (tbl, key), each of the song's tables in one IN: no scan of every entry.
        val found = db.query("SELECT tbl, value FROM phone_overrides WHERE tbl IN ($SONG_TABLES_IN) AND key = ?", key) {
            it.text(0)!! to it.text(1)!!
        }.toMap()
        val out = LinkedHashMap<String, JsonElement>()
        for (table in SONG_TABLES) found[table]?.let { out[table] = Canonical.parse(it) }
        if (IGNORE in found) out[IGNORE] = JsonPrimitive(true)
        return JsonObject(out)
    }

    /**
     * overrides.put_song_entries: make the song's entries what [entries] says (song_entries' shape), written under
     * [written]: each table it names gets that entry, each it leaves out (or gives null) loses the song's, and
     * `ignore` is set by its truth. A table already as given is left alone, keeping how it was written. Null takes
     * every entry out. A table that isn't a song's is refused (IllegalArgumentException), and nothing is written.
     */
    fun putSongEntries(db: Db, key: String, written: String, entries: JsonObject?) {
        val wanted = entries ?: JsonObject(emptyMap())
        val unknown = (wanted.keys - SONG_TABLES.toSet() - IGNORE).sortedWith(Canonical.KEY_ORDER)
        if (unknown.isNotEmpty()) {
            throw IllegalArgumentException("${Python.repr(written)}: unknown table(s) ${unknown.joinToString(", ")}")
        }
        db.savepoint("song_entries") {
            for (table in SONG_TABLES) {
                val value = wanted[table]?.takeUnless { it is JsonNull }
                if (value == null) delete(db, table, key) else put(db, table, key, written, Canonical.write(value))
            }
            if (wanted[IGNORE]?.let(Python::truthy) == true) put(db, IGNORE, key, written, "true") else delete(db, IGNORE, key)
        }
    }

    /** The artist's `[alias]`: the UG artists' slugs, or null for none. */
    fun alias(db: Db, artistKey: String): JsonArray? = value(db, "alias", artistKey)?.let { it as? JsonArray }

    /** Make the artist's `[alias]` [slugs], written under [written]; null takes it out. */
    fun putAlias(db: Db, artistKey: String, written: String, slugs: JsonArray?) {
        if (slugs == null) delete(db, "alias", artistKey) else put(db, "alias", artistKey, written, Canonical.write(slugs))
    }

    /** The artist's `[artist_url]` as its unit's value, `{name, page}` (the name it is written under), or null. */
    fun artistUrl(db: Db, artistKey: String): JsonObject? =
        db.one("SELECT written, value FROM phone_overrides WHERE tbl = 'artist_url' AND key = ?", artistKey) {
            artistUrlValue(it.text(0)!!, it.text(1)!!)
        }

    /** Make the artist's `[artist_url]` the page of [value] (`{name, page}`, both text), written under its name;
     * null takes it out. */
    fun putArtistUrl(db: Db, artistKey: String, value: JsonObject?) {
        if (value == null) {
            delete(db, "artist_url", artistKey)
            return
        }
        val name = value["name"]
        val page = value["page"]
        require(name is JsonPrimitive && name.isString && page is JsonPrimitive && page.isString) {
            "an artist's page is {name, page}, both text: $value"
        }
        db.execute(
            "INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('artist_url', ?, ?, ?) " +
                "ON CONFLICT(tbl, key) DO UPDATE SET written = excluded.written, value = excluded.value",
            artistKey, name.content, Canonical.write(page),
        )
    }

    /** The blocked tabs (`[block] tab_ids`), in order. */
    fun blocks(db: Db): List<Long> =
        db.query("SELECT key FROM phone_overrides WHERE tbl = 'block'") { it.text(0)!!.toLongOrNull() }
            .filterNotNull().distinct().sorted()

    /** Block the tab [tab], or with [on] false let it be used again. */
    fun putBlock(db: Db, tab: Long, on: Boolean) {
        if (on) {
            db.execute(
                "INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('block', ?, ?, 'true') " +
                    "ON CONFLICT(tbl, key) DO NOTHING", tab.toString(), tab.toString(),
            )
        } else {
            delete(db, "block", tab.toString())
        }
    }

    /** Every `[alias]`, by artist key: the slugs [alias] reads. */
    internal fun aliases(db: Db): List<Pair<String, JsonArray>> =
        db.query("SELECT key, value FROM phone_overrides WHERE tbl = 'alias' ORDER BY rowid") {
            (Canonical.parse(it.text(1)!!) as? JsonArray)?.let { slugs -> it.text(0)!! to slugs }
        }.filterNotNull()

    /** Every `[artist_url]`, by artist key, as its unit's value. */
    internal fun artistUrls(db: Db): List<Pair<String, JsonObject>> =
        db.query("SELECT key, written, value FROM phone_overrides WHERE tbl = 'artist_url' ORDER BY rowid") {
            it.text(0)!! to artistUrlValue(it.text(1)!!, it.text(2)!!)
        }

    private fun artistUrlValue(written: String, value: String): JsonObject =
        JsonObject(linkedMapOf("name" to JsonPrimitive(written), "page" to Canonical.parse(value)))

    private fun value(db: Db, table: String, key: String): JsonElement? =
        db.one("SELECT value FROM phone_overrides WHERE tbl = ? AND key = ?", table, key) { Canonical.parse(it.text(0)!!) }

    /** An entry written, or left as it is (and as it was written) when it already holds [value]. */
    private fun put(db: Db, table: String, key: String, written: String, value: String) {
        db.execute(
            "INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?) ON CONFLICT(tbl, key) DO UPDATE " +
                "SET written = excluded.written, value = excluded.value WHERE phone_overrides.value IS NOT excluded.value",
            table, key, written, value,
        )
    }

    private fun delete(db: Db, table: String, key: String) {
        db.execute("DELETE FROM phone_overrides WHERE tbl = ? AND key = ?", table, key)
    }
}
