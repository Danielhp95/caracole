package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/** UgDirectory, ug/directory.py's keys on the phone: how a row of UG's artist directory is filed, and filed again
 * after a change to caracole's keys. The merge's re-keying is IndexReplay's too (vectors/index/, its rekey and
 * unseeded merges); the forms here are those the corpus's fixtures hold, Python's. */
class UgDirectoryTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun aRowsFormsAreItsNamesAndItsSlugsHyphenatedThenWrittenTogether() {
        assertEquals("song-dongye-宋冬野 song-dongye-song-dong-ye song-dongye 宋冬野 song-dong-ye songdongye宋冬野 " +
                         "songdongyesongdongye songdongye", UgDirectory.formsText("Song Dongye (宋冬野)", ""))
        assertEquals("simon-garfunkel simongarfunkel", UgDirectory.formsText("Simon & Garfunkel", "simon_garfunkel"))
        assertEquals("кино", UgDirectory.formsText("Кино", ""))
    }

    @Test fun anArtistIsFiledUnderTheIndexsKeyWhereTheirSlugIsOneElseTheirNamesElseTheirId() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                // a name and a slug of two keys (as a page renamed since its slug was made)
                assertEquals("paul-simon", UgDirectory.artistKeyOf(db, 274, "Paul Simon", "simon_garfunkel"))
                db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                               "VALUES (1, 'simon-garfunkel', 'the-boxer', 'chords', '1', 'x', '')")
                assertEquals("simon-garfunkel", UgDirectory.artistKeyOf(db, 274, "Paul Simon", "simon_garfunkel"))
                assertEquals("song-dongye-宋冬野", UgDirectory.artistKeyOf(db, 634073, "Song Dongye (宋冬野)", ""))
                assertEquals("634073", UgDirectory.artistKeyOf(db, 634073, "", ""))
                assertEquals("https://www.ultimate-guitar.com/artist/634073", UgDirectory.pageAddress(634073, ""))
                assertEquals("https://www.ultimate-guitar.com/artist/simon_garfunkel_274",
                             UgDirectory.pageAddress(274, "simon_garfunkel"))
            }
        }
    }

    @Test fun theKeysAreMadeAgainOnceAfterAChangeToCaracolesKeys() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.execute("INSERT INTO ug_directory (artist_id, name, slug, letter, artist_key, forms, seen_at) " +
                               "VALUES (13472, 'Кино', '', '0-9', 'stale', 'stale-key', '2026-11-03T10:00:00Z'), " +
                               "(90, 'Toto', 'toto', 't', 'toto', 'toto', '2026-11-03T10:00:00Z')")
                db.kvSet(UgDirectory.KEYS_KEY, "1")
                assertEquals(1, UgDirectory.ensureCurrentKeys(db))
                assertEquals(Normalize.KEY_VERSION.toString(), db.kvGet(UgDirectory.KEYS_KEY))
                assertEquals(listOf("кино" to "кино", "toto" to "toto"),
                             db.query("SELECT artist_key, forms FROM ug_directory ORDER BY artist_id DESC") {
                                 it.text(0)!! to it.text(1)!!
                             })
                // its key joins the artist vocabulary, the stale one gone with its last row
                assertEquals(listOf("toto", "кино"), db.query("SELECT artist_key FROM ug_artists ORDER BY artist_key") {
                    it.text(0)!!
                })
                db.execute("UPDATE ug_directory SET forms = 'again' WHERE artist_id = 90")
                assertEquals(0, UgDirectory.ensureCurrentKeys(db))  // once: the record says they are current
            }
        }
    }
}
