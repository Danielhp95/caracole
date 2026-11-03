package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * harptabs.com's and gametabs.net's keys made current, and how far each index has got, as harptabs_fetch.py,
 * harptabs_index.py and gametabs_index.py make and count them: what IndexTransfer calls after a merge, and the search
 * routes read for where a search looked. Every key is made again from what the table holds, with no request, once per
 * change to how it is made (its kv record), in one savepoint; each returns how many rows changed.
 */
object SiteKeys {
    /** harptabs_fetch.KEYS_KEY: how the sitemap's rows in harptabs_index are keyed ([HARPTABS_ROWS]). */
    const val HARPTABS_ROW_KEYS = "harptabs:index:keys"

    /** harptabs_fetch.ROW_KEYS: a tab's key joins a contraction's end to its word (harptabs.joined). */
    const val HARPTABS_ROWS = "1"

    /** harptabs_index.KEYS_KEY: the KEY_VERSION the artist pages' songs' keys were made with. */
    const val HARPTABS_SONG_KEYS = "harptabs:artists:keys"

    /** gametabs_index.KEYS_KEY: the KEY_VERSION the game pages' tabs' title keys were made with. */
    const val GAMETABS_TITLE_KEYS = "gametabs:games:keys"

    /**
     * harptabs_fetch.ensure_current_keys, then harptabs_index.ensure_current_keys, as index_transfer runs them: the
     * sitemap's rows keyed again from their paths after a change to how harptabs.py keys them ([HARPTABS_ROWS]), and
     * the artist pages' tabs' song keys again from their titles after a change to caracole's keys
     * ([Normalize.KEY_VERSION]). The rows changed, of both.
     */
    fun harptabsEnsureCurrentKeys(db: Db): Int = harptabsRowKeys(db) + harptabsSongKeys(db)

    /** harptabs_fetch.ensure_current_keys alone: the sitemap's rows keyed again from their paths (parse_page_url). */
    fun harptabsRowKeys(db: Db): Int {
        if (db.kvGet(HARPTABS_ROW_KEYS) == HARPTABS_ROWS) return 0
        return db.savepoint("harptabs_index_keys") {
            var changed = 0
            for ((path, key) in db.query("SELECT path, key FROM harptabs_index") { it.text(0)!! to it.text(1)!! }) {
                val now = HarpTabs.pageKey(HarpTabs.pageUrl(path))
                if (now != null && now != key) {
                    db.execute("UPDATE harptabs_index SET key = ? WHERE path = ?", now, path)
                    changed++
                }
            }
            db.kvSet(HARPTABS_ROW_KEYS, HARPTABS_ROWS)
            changed
        }
    }

    /** harptabs_index.ensure_current_keys alone: every tab's song key again from its title (harptabs.song_key). */
    fun harptabsSongKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(HARPTABS_SONG_KEYS) == version) return 0
        return db.savepoint("harptabs_artist_keys") {
            var changed = 0
            val rows = db.query("SELECT artist, tab_id, title, song_key FROM harptabs_artist_tabs") {
                listOf(it.text(0)!!, it.long(1)!!, it.text(2)!!, it.text(3)!!)
            }
            for ((artist, tabId, title, old) in rows) {
                val new = HarpTabs.songKey(title as String)
                if (new != old) {
                    db.execute("UPDATE harptabs_artist_tabs SET song_key = ? WHERE artist = ? AND tab_id = ?",
                               new, artist, tabId)
                    changed++
                }
            }
            db.kvSet(HARPTABS_SONG_KEYS, version)
            changed
        }
    }

    /** gametabs_index.ensure_current_keys: every game page's tab's title key again from its title after a change to
     * caracole's keys (gametabs.title_key). */
    fun gametabsEnsureCurrentKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(GAMETABS_TITLE_KEYS) == version) return 0
        return db.savepoint("gametabs_game_keys") {
            var changed = 0
            val rows = db.query("SELECT page, path, title, title_key FROM gametabs_game_tabs") {
                listOf(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!)
            }
            for ((page, path, title, old) in rows) {
                val new = GameTabs.titleKey(title)
                if (new != old) {
                    db.execute("UPDATE gametabs_game_tabs SET title_key = ? WHERE page = ? AND path = ?", new, page, path)
                    changed++
                }
            }
            db.kvSet(GAMETABS_TITLE_KEYS, version)
            changed
        }
    }

    /**
     * harptabs_index.index_state, as helpers.corpus.plain writes its IndexState: the artists the sitemap lists
     * (`artists`), those whose page caracole has read (`read`), and the tabs those pages listed (`tabs`). An artist the
     * sitemap no longer lists counts in neither. Every page is read once `read >= artists` (and `artists > 0`).
     */
    fun harptabsIndexState(db: Db): JsonObject {
        val (artists, read) = db.one(
            "SELECT COUNT(*), COUNT(a.path) FROM harptabs_index i LEFT JOIN harptabs_artists a ON a.path = i.path " +
                "WHERE i.kind = ?", HarpTabs.ARTIST,
        ) { it.long(0)!! to it.long(1)!! }!!
        val tabs = db.one("SELECT COUNT(*) FROM harptabs_artist_tabs t WHERE EXISTS " +
                              "(SELECT 1 FROM harptabs_index i WHERE i.path = t.artist)") { it.long(0)!! }!!
        return state("artists" to artists, "read" to read, "tabs" to tabs)
    }

    /**
     * gametabs_index.index_state, as helpers.corpus.plain writes its IndexState: the game pages the sitemaps list
     * (`pages`), those caracole has read (`read`), and the tabs those pages listed (`tabs`). A page the sitemaps no
     * longer list counts in neither.
     */
    fun gametabsIndexState(db: Db): JsonObject {
        val (pages, read) = db.one(
            "SELECT COUNT(*), COUNT(g.path) FROM gametabs_index i LEFT JOIN gametabs_games g ON g.path = i.path " +
                "WHERE i.kind = ?", GameTabs.GAME,
        ) { it.long(0)!! to it.long(1)!! }!!
        val tabs = db.one("SELECT COUNT(*) FROM gametabs_game_tabs t WHERE EXISTS " +
                              "(SELECT 1 FROM gametabs_index i WHERE i.path = t.page)") { it.long(0)!! }!!
        return state("pages" to pages, "read" to read, "tabs" to tabs)
    }

    private fun state(vararg fields: Pair<String, Long>): JsonObject =
        JsonObject(linkedMapOf(*fields).mapValues { JsonPrimitive(it.value.toInt()) })
}
