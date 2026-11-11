package io.github.danielhp95.caracole.core.backup

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.internal.SongKv
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The kv records a restore keeps as they are now, never as the backup has them: this side's own, which no backup of
 * the library takes back (AGENTS.md's "Two caracoles, each its own politeness": each side's cooldowns, pace and the
 * records that gate a request are its own, and so are its identity and its settings), so that a restore never
 * forgets a cooldown met since:
 *
 * - its politeness: each provider's health (`provider:`), its pace (`http:last_request:`), and the global records
 *   that gate a request (LaCuerda's searches and their failures, gtptabs.com's unusable tabs, UG's artist pages
 *   learned and its pages that won't read, YouTube's searches);
 * - its identity and what it agreed with the computer (`sync:`: its id, each base and kept answer, the peer and index
 *   records), so the restored library is the phone's own change, given to the computer at the next sync;
 * - the computer's settings (`phone:settings`), the phone's own schema record, and its indexes' progress and the
 *   pages it read for them (`phone:read:`, `phone:pushed:`, each site's sitemaps, `:index:`, `:keys` records): the
 *   index tables are no backup's, so their records stay theirs;
 * - and each song's records that gate a request ([SONGS]: a site's 30-day check, UG's artist page checked), kept by
 *   the song's identity key, since a song's id may differ in the backup: a song the backup has takes the records the
 *   phone has now for that song (none, if it has none now), and one only the backup has keeps its own.
 *
 * Everything else in kv is the library's (each song's pages, versions and lyrics records, wanted.txt's first
 * sightings, the songbooks' pages, the key version of its songs), and comes back from the backup with its tables.
 */
object OwnRecords {
    /** Records kept by their whole key. */
    val KEYS: Set<String> = setOf(
        "phone:settings", "phone:schema", "lacuerda:search-failed",
        "ug:sitemaps", "gtptabs:sitemaps", "musescore:sitemaps", "harptabs:sitemaps", "gametabs:sitemaps",
    )

    /** Records kept by the start of their key. */
    val PREFIXES: List<String> = listOf(
        "provider:", "http:last_request:", "sync:", "phone:read:", "phone:pushed:",
        "lacuerda:search:", "gtptabs:unusable:", "ug:artist_url:", "ug:pasted_tab:", "ug:unreadable:",
        "youtube-search:",
        "ug:index:", "ug:artist_tabs:", "lacuerda:index:", "harptabs:index:", "harptabs:artists:", "gametabs:index:",
        "gametabs:games:", "gtptabs:index:", "musescore:index:",
    )

    /** A song's records that gate a request (of songs._PER_SONG_KV), `<prefix><song id>` or `<prefix><id>:<more>`. */
    val SONGS: List<String> = listOf(
        "megalobiz:checked:", "azlyrics:checked:", "gtptabs:checked:", "harptabs:checked:", "gametabs:checked:",
        "ug:artist_page_checked:",
    )

    /** Whether [key] is one of this side's own global records. */
    fun isOwn(key: String): Boolean = key in KEYS || PREFIXES.any { key.startsWith(it) }

    /** Whether [key] is a song's record that gates a request. */
    fun isSongsOwn(key: String): Boolean = songRecord(key) != null

    /**
     * This side's own records now: `{"kv": {key: value}, "songs": {identity key: [[prefix, after the id, value]]}}`,
     * every song of the library listed, its records or none.
     */
    fun document(db: Db): JsonObject {
        val keys = db.query("SELECT id, key FROM songs") { it.long(0)!! to it.text(1)!! }.toMap()
        val kv = sortedMapOf<String, JsonPrimitive>(Canonical.KEY_ORDER)
        val songs = sortedMapOf<String, MutableList<JsonArray>>(Canonical.KEY_ORDER)
        for (key in keys.values) songs[key] = mutableListOf()
        for ((key, value) in db.query("SELECT key, value FROM kv") { it.text(0)!! to it.text(1).orEmpty() }) {
            if (isOwn(key)) {
                kv[key] = JsonPrimitive(value)
                continue
            }
            val (prefix, id, rest) = songRecord(key) ?: continue
            val song = keys[id] ?: continue
            songs.getValue(song) += JsonArray(listOf(JsonPrimitive(prefix), JsonPrimitive(rest), JsonPrimitive(value)))
        }
        return JsonObject(mapOf(
            "kv" to JsonObject(kv),
            "songs" to JsonObject(songs.mapValues { (_, records) ->
                JsonArray(records.sortedWith(compareBy(Canonical.KEY_ORDER) { r -> r.joinToString("\u0000") { it.jsonPrimitive.content } }))
            }),
        ))
    }

    /**
     * [document]'s records made the database's again, over what a restore put back: every own global record the
     * backup brought gone and the document's written; each song the document names that the library has (by its
     * identity key) given the document's records of it under its id here, its others gone.
     */
    fun putBack(db: Db, document: JsonObject) {
        for (key in db.query("SELECT key FROM kv") { it.text(0)!! }) if (isOwn(key)) db.kvDelete(key)
        for ((key, value) in document.getValue("kv").jsonObject) db.kvSet(key, value.jsonPrimitive.content)
        val ids = db.query("SELECT key, id FROM songs") { it.text(0)!! to it.long(1)!! }.toMap()
        for ((song, records) in document.getValue("songs").jsonObject) {
            val id = ids[song] ?: continue
            for (prefix in SONGS) SongKv.deletePrefixed(db, prefix, id)
            for (record in records.jsonArray) {
                val (prefix, rest, value) = record.jsonArray.map { it.jsonPrimitive.content }
                require(prefix in SONGS) { "not a song's own record: $prefix" }
                db.kvSet("$prefix$id$rest", value)
            }
        }
    }

    /** [key]'s prefix of [SONGS], its song's id and what follows the id ("" or ":…"); null for no such record. */
    private fun songRecord(key: String): Triple<String, Long, String>? {
        for (prefix in SONGS) {
            if (!key.startsWith(prefix)) continue
            val rest = key.substring(prefix.length)
            val digits = rest.takeWhile { it in '0'..'9' }
            val tail = rest.substring(digits.length)
            if (digits.isEmpty() || (tail.isNotEmpty() && !tail.startsWith(":"))) return null
            return Triple(prefix, digits.toLongOrNull() ?: return null, tail)
        }
        return null
    }
}
