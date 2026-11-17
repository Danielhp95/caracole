package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize

/**
 * ug/directory.py's half the phone holds: UG's artist directory (`ug_directory`, schema 16), every artist UG's letter
 * listings name, by UG's id, with their page's address, their tabs and when caracole last saw them there and read
 * their page. The phone reads no listing and runs no directory pass, the computer's bulk work: it takes the directory
 * from a sync's or a file's index merge (core.index's Merge) and searches it (core.search's `directoryArtists`). So
 * this is how a row is filed ([artistKeyOf], [formsText]) and filed again after a change to caracole's keys
 * ([ensureCurrentKeys]), with no request. Every call runs inside Database.write.
 */
object UgDirectory {
    /** directory.LETTERS_KEY: each listing's rounds, `{letter: {pages, artists, started, next, done}}`. */
    const val LETTERS_KEY = "ug:directory:letters"

    /** directory.KEYS_KEY: the Normalize.KEY_VERSION the keys were made with. */
    const val KEYS_KEY = "ug:directory:keys"

    /** page_address: an artist page's address from UG's id and its slug: `/artist/{slug}_{id}`, or `/artist/{id}`. */
    fun pageAddress(artistId: Long, slug: String): String =
        "${UgUrls.ARTIST_HOST}/artist/${if (slug.isNotEmpty()) slug + "_" else ""}$artistId"

    /** forms_text: a row's forms, for the prefilter's `LIKE`: its name's (Normalize.nameForms) and its slug's key,
     * each hyphenated and written together, once each, in that order. */
    fun formsText(name: String, slug: String): String {
        val every = (Normalize.nameForms(name) +
            (if (slug.isNotEmpty()) listOf(Normalize.slugKey(slug.replace("_", " "))) else emptyList()))
            .filter { it.isNotEmpty() }
        val forms = LinkedHashSet<String>()
        forms.addAll(every)
        for (f in every) forms.add(f.replace("-", ""))
        return forms.joinToString(" ")
    }

    /** artist_key_of: the key an artist is filed under, as ArtistTabs files a page's tabs: the index's key where
     * their slug is one of its keys (`simon_garfunkel` is `simon-garfunkel`), else their name's slug key ("Song Dongye
     * (宋冬野)" is `song-dongye-宋冬野`), else their slug's, else their id. */
    fun artistKeyOf(db: Db, artistId: Long, name: String, slug: String): String {
        val slugged = if (slug.isNotEmpty()) Normalize.slugKey(slug.replace("_", " ")) else ""
        if (slugged.isNotEmpty() &&
            db.one("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", slugged) { true } != null
        ) {
            return slugged
        }
        return Normalize.slugKey(name).ifEmpty { slugged }.ifEmpty { artistId.toString() }
    }

    /** ensure_current_keys: every row's key and forms made again from its name after a change to caracole's keys,
     * once (kv [KEYS_KEY]), a row at a time by its id; how many rows changed. */
    fun ensureCurrentKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(KEYS_KEY) == version) return 0
        return db.savepoint("ug_directory_keys") {
            val rows = db.query(
                "SELECT artist_id, name, slug, artist_key, forms FROM ug_directory ORDER BY artist_id",
            ) {
                Row(it.long(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.text(4)!!)
            }
            var changed = 0
            for (row in rows) {
                val key = artistKeyOf(db, row.id, row.name, row.slug)
                val forms = formsText(row.name, row.slug)
                if (key != row.key || forms != row.forms) {
                    db.execute("UPDATE ug_directory SET artist_key = ?, forms = ? WHERE artist_id = ?",
                               key, forms, row.id)
                    changed++
                }
            }
            db.kvSet(KEYS_KEY, version)
            changed
        }
    }

    private class Row(val id: Long, val name: String, val slug: String, val key: String, val forms: String)
}
