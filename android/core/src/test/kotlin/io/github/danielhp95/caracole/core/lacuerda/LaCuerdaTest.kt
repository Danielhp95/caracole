package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

/**
 * lacuerda_index.py's read side and search.py's LaCuerda glue against vectors/search/lacuerda.jsonl: `find`,
 * `search_lacuerda`, `lacuerda_leads`, `lacuerda_artist`, `lacuerda_songs`, `lacuerda_artist_named`,
 * `lacuerda_left_out` and `letters_read`, each record Python's answer to the same call over the same fixture
 * (tests/test_conformance_search.py), compared whole. `lacuerda_leads` takes the Ultimate Guitar index's answer to the
 * query as vectors/search/index.jsonl records Python's `find_index` of it, so it is checked apart from Search. The
 * records are SearchReplay.lacuerda's, which the device runs too.
 */
class LaCuerdaTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun everyRecordIsAFunctionOfLaCuerda() {
        assertEquals(SearchReplay.LACUERDA_FNS, Corpus.records(VECTOR).map { it.fn }.toSet())
    }

    /** The index finds artists and songs, a search of it is its artists then its songs, LaCuerda leads as Python
     * says, an artist is their slug's row, their songs LaCuerda's most popular first, an artist found by their name,
     * what the index leaves out said, and the letters read whole those whose every page the index holds. */
    @Test fun everyAnswerIsLacuerdaIndexPys() = Misses(VECTOR).also { SearchReplay.lacuerda(it) }.assertNone()

    @Test fun theIndexStateSaysWhatItHolds() = loaded("lacuerda") { database ->
        // lacuerda_index.index_state's answers over the same fixture, asked of Python (no corpus record holds them yet).
        assertEquals(state(43, 31, false, "a", "b"), database.read { LaCuerda.lettersRead(it) })
        database.writeBlocking { it.kvSet(LaCuerda.COMPLETE_KEY, "2026-10-21T03:30:00Z") }
        assertEquals(state(43, 31, true, "a", "b"), database.read { LaCuerda.lettersRead(it) })
        database.writeBlocking { it.kvSet(LaCuerda.COMPLETE_KEY, "not a time") } // unreadable: never read whole
        assertEquals(state(43, 31, false, "a", "b"), database.read { LaCuerda.lettersRead(it) })
    }

    @Test fun anEmptyIndexHasReadNoLetter() = loaded("empty") { database ->
        assertEquals(state(0, 0, false), database.read { LaCuerda.lettersRead(it) })
        assertEquals("empty", database.read { LaCuerda.lacuerdaLeftOut(it) }?.first)
    }

    @Test fun lettersAreNamedAsLaCuerdasMenuNamesThem() {
        // lacuerda_index.letters_text's answers, asked of Python.
        val cases = listOf(
            listOf<String>() to "", listOf("a") to "A", listOf("a", "b") to "A, B", listOf("a", "b", "c") to "A–C",
            listOf("_num", "a", "b", "c", "e") to "#, A–C, E", listOf("n", "nn", "o") to "N–O",
            listOf("m", "n", "nn") to "M–Ñ", listOf("_num", "a") to "#, A", listOf("z", "a", "b", "c") to "A–C, Z",
            listOf("x", "x") to "X", listOf("b", "a") to "A, B",
        )
        for ((letters, text) in cases) assertEquals(text, LaCuerda.lettersText(letters), "$letters")
    }

    @Test fun anArtistsSlugsAreTriedBestGuessFirst() {
        // lacuerda.artist_slug_candidates' answers, asked of Python.
        val cases = listOf(
            "Joaquín Sabina" to listOf("joaquin_sabina"),
            "Fito y Fitipaldis" to listOf("fito_y_fitipaldis", "fito__fitipaldis"),
            "Fito & Fitipaldis" to listOf("fito__fitipaldis", "fito_y_fitipaldis"),
            "Los Enanitos Verdes" to listOf("enanitos_verdes", "los_enanitos_verdes"),
            "Mägo de Oz" to listOf("mago_de_oz"), "Ñu" to listOf("niu"), "宋冬野" to listOf(),
            "2 Minutos" to listOf("2_minutos"), "The Beatles" to listOf("beatles", "the_beatles"), "Y" to listOf("y"),
            "Simon y Garfunkel y" to listOf("simon_y_garfunkel_y", "simon__garfunkel"), "AC/DC" to listOf("acdc"),
            "  Soda   Stereo " to listOf("soda_stereo"),
            "Joan Manuel Serrat & Y" to listOf("joan_manuel_serrat__y", "joan_manuel_serrat", "joan_manuel_serrat_y_y"),
            "" to listOf(),
        )
        for ((name, slugs) in cases) assertEquals(slugs, LaCuerda.artistSlugCandidates(name), name)
    }

    @Test fun anUnreadLetterIsWhereANameWouldBe() = loaded("lacuerda") { database ->
        // lacuerda_index.unread_letter's answers over the same fixture, asked of Python.
        database.read { db ->
            assertEquals("e", LaCuerda.unreadLetter(db, "Estopa"))
            assertEquals(null, LaCuerda.unreadLetter(db, "Andrés Calamaro")) // under A, read whole
            assertEquals("t", LaCuerda.unreadLetter(db, "The Beatles")) // beatles under B, read; the_beatles under T
            assertEquals("_num", LaCuerda.unreadLetter(db, "2 Minutos"))
            assertEquals(null, LaCuerda.unreadLetter(db, "宋冬野")) // no slug
        }
        database.writeBlocking { it.kvSet(LaCuerda.COMPLETE_KEY, "2026-10-21T03:30:00Z") }
        assertEquals(null, database.read { LaCuerda.unreadLetter(it, "Estopa") }) // the whole index read
    }

    @Test fun anArtistsSlugsAreTheListingsOfTheirName() = loaded("lacuerda") { database ->
        // lacuerda_index.artist_slugs' answers over the same fixture, asked of Python.
        database.read { db ->
            assertEquals(listOf("estopa"), LaCuerda.artistSlugs(db, "Estopa"))
            assertEquals(listOf(), LaCuerda.artistSlugs(db, "Nobody At All"))
            assertEquals(listOf(), LaCuerda.artistSlugs(db, ""))
        }
    }

    @Test fun keysAreMadeAgainFromTheNamesAsPythonMadeThem() {
        for (fixture in listOf("lacuerda", "titles", "by_word", "names")) loaded(fixture) { database ->
            val rows = { database.read { db ->
                db.query("SELECT path, artist_key, title_key FROM lacuerda_index ORDER BY path") {
                    listOf(it.text(0), it.text(1), it.text(2))
                }
            } }
            val python = rows()
            database.writeBlocking { db ->
                db.execute("UPDATE lacuerda_index SET artist_key = 'stale-' || artist_key, title_key = title_key || '-stale'")
                db.kvDelete(LaCuerda.KEYS_KEY)
            }
            assertNotEquals(python, rows())
            assertEquals(python.size, database.writeBlocking { LaCuerda.ensureCurrentKeys(it) }, fixture)
            assertEquals(python, rows(), fixture)
            assertEquals(Normalize.KEY_VERSION.toString(), database.read { it.kvGet(LaCuerda.KEYS_KEY) })
            assertEquals(0, database.writeBlocking { LaCuerda.ensureCurrentKeys(it) }, "once only")
        }
    }

    private fun loaded(fixture: String, block: (Database) -> Unit) {
        val dir = folder.newFolder(fixture)
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
            block(database)
        }
    }

    private fun state(artists: Int, songs: Int, complete: Boolean, vararg letters: String) = JsonObject(linkedMapOf(
        "artists" to JsonPrimitive(artists), "songs" to JsonPrimitive(songs), "complete" to JsonPrimitive(complete),
        "letters" to JsonArray(letters.map { JsonPrimitive(it) }),
    ))

    companion object {
        const val VECTOR = SearchReplay.LACUERDA
    }
}
