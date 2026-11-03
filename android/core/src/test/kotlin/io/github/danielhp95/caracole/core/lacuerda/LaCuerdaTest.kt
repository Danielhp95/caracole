package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.sites.Replay
import io.github.danielhp95.caracole.core.sites.Replay.Companion.int
import io.github.danielhp95.caracole.core.sites.Replay.Companion.string
import io.github.danielhp95.caracole.core.sites.Replay.Companion.text
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.AfterClass
import org.junit.ClassRule
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
 * query as vectors/search/index.jsonl records Python's `find_index` of it, so it is checked apart from Search.
 */
class LaCuerdaTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun everyRecordIsAFunctionOfLaCuerda() {
        val known = setOf(FIND, SEARCH, LEADS, ARTIST, SONGS, ARTIST_NAMED, LEFT_OUT, LETTERS_READ)
        assertEquals(emptySet(), replay.records.map { it.fn }.toSet() - known)
    }

    @Test fun theIndexFindsArtistsAndSongs() = replay.check(FIND) { db, r ->
        LaCuerda.find(db, text(r, 0), int(r, "artists", 3), int(r, "songs", 5)).toJson()
    }

    @Test fun aSearchOfTheIndexIsItsArtistsThenItsSongs() = replay.check(SEARCH) { db, r ->
        val (artists, songs) = LaCuerda.searchLacuerda(db, text(r, 0), int(r, "songs", 5), int(r, "artists", 3))
        JsonArray(listOf(JsonArray(artists.map { it.toJson() }), JsonArray(songs.map { it.toJson() })))
    }

    @Test fun laCuerdaLeadsAsPythonSays() = replay.check(LEADS) { db, r ->
        val q = text(r, 0)
        val ug = ugFound.getValue(r.extra.getValue("fixture").jsonPrimitive.content to q)
        JsonPrimitive(LaCuerda.lacuerdaLeads(ug, LaCuerda.searchLacuerda(db, q).first))
    }

    @Test fun anArtistIsTheirSlugsRow() = replay.check(ARTIST) { db, r ->
        LaCuerda.lacuerdaArtist(db, text(r, 0))?.toJson() ?: JsonNull
    }

    @Test fun anArtistsSongsAreLaCuerdasMostPopularFirst() = replay.check(SONGS) { db, r ->
        JsonArray(LaCuerda.lacuerdaSongs(db, text(r, 0), string(r, "title")).map { it.toJson() })
    }

    @Test fun anArtistIsFoundByTheirName() = replay.check(ARTIST_NAMED) { db, r ->
        LaCuerda.lacuerdaArtistNamed(db, text(r, 0))?.toJson() ?: JsonNull
    }

    @Test fun whatTheIndexLeavesOutIsSaid() = replay.check(LEFT_OUT) { db, _ ->
        LaCuerda.lacuerdaLeftOut(db)?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) } ?: JsonNull
    }

    @Test fun theLettersReadWholeAreThoseWhoseEveryPageTheIndexHolds() = replay.check(LETTERS_READ) { db, _ ->
        JsonArray(LaCuerda.letters(db).map { JsonPrimitive(it) })
    }

    @Test fun theIndexStateSaysWhatItHolds() = loaded("lacuerda") { database ->
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
            assertEquals("2", database.read { it.kvGet(LaCuerda.KEYS_KEY) })
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
        const val VECTOR = "search/lacuerda.jsonl"
        const val FIND = "caracole.lacuerda_index.find"
        const val SEARCH = "caracole.search.search_lacuerda"
        const val LEADS = "caracole.search.lacuerda_leads"
        const val ARTIST = "caracole.search.lacuerda_artist"
        const val SONGS = "caracole.search.lacuerda_songs"
        const val ARTIST_NAMED = "caracole.search.lacuerda_artist_named"
        const val LEFT_OUT = "caracole.search.lacuerda_left_out"
        const val LETTERS_READ = "caracole.lacuerda_index.letters_read"

        @get:ClassRule @JvmStatic val tmp = TemporaryFolder()

        private val replaying = lazy { Replay(VECTOR) { tmp.root } }
        private val replay by replaying

        /** Python's find_index of each fixture's queries (vectors/search/index.jsonl), by (fixture, query). */
        private val ugFound: Map<Pair<String, String>, IndexFound> by lazy {
            Corpus.records("search/index.jsonl")
                .filter { it.fn == "caracole.search.find_index" && it.kw.isEmpty() }
                .associate {
                    val fixture = it.extra.getValue("fixture").jsonPrimitive.content
                    (fixture to it.args[0].jsonPrimitive.content) to indexFound(it.out!!.jsonObject)
                }
        }

        private fun indexFound(o: JsonObject) = IndexFound(
            artists = o.getValue("artists").jsonArray.map { artistHit(it.jsonObject) },
            songs = o.getValue("songs").jsonArray.map { indexHit(it.jsonObject) },
            lead = (o["lead"] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content,
            best = (o["best"] as? JsonObject)?.let { indexHit(it) },
        )

        private fun artistHit(o: JsonObject) = ArtistHit(
            o.text("artist_key"), o.text("artist"), o.number("score"), o.whole("songs"), o.whole("tabs"),
            o.getValue("top").jsonArray.map { indexHit(it.jsonObject) }, o.text("page"),
            o.getValue("part").jsonPrimitive.boolean,
        )

        private fun indexHit(o: JsonObject) = IndexHit(
            o.text("artist_key"), o.text("song_key"),
            LinkedHashMap(o.getValue("counts").jsonObject.mapValues { it.value.jsonPrimitive.int }), o.number("score"),
            o.text("url"), o.getValue("labels").jsonArray.map { it.jsonPrimitive.content }, o.text("artist"), o.text("title"),
            o.text("via"), o.getValue("rating").jsonPrimitive.doubleOrNull, o.whole("votes"), o.text("page"),
        )

        private fun JsonObject.text(name: String): String = getValue(name).jsonPrimitive.content
        private fun JsonObject.number(name: String): Double = getValue(name).jsonPrimitive.double
        private fun JsonObject.whole(name: String): Int = getValue(name).jsonPrimitive.int

        @AfterClass @JvmStatic fun close() {
            if (replaying.isInitialized()) replay.close()
        }
    }
}
