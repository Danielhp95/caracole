package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * song_names.py against vectors/search/names.jsonl: `clean`, `clean_channel`, and `read_names` with no database and
 * no songs, or over a fixture (vectors/search/fixtures/<name>.jsonl) replayed into a fresh database with its songs
 * (`songs.list_songs`), as Python read them (tests/test_conformance_search.py).
 */
class SongNamesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records = Corpus.records(VECTOR)

    private fun of(fn: String): List<Record> = records.filter { it.fn == fn }.also {
        assertTrue(it.isNotEmpty(), "$VECTOR has no record of $fn")
    }

    private fun named(out: Pair<String, String>?) = out?.let { listOf(it.first, it.second) }

    private fun expected(record: Record): List<String>? = when (val out = record.out) {
        null, is JsonNull -> null
        is JsonArray -> out.map { it.jsonPrimitive.content }
        else -> error("not a name: $out")
    }

    private fun fail(wrong: List<String>, of: Int, fn: String) {
        if (wrong.isNotEmpty()) fail("${wrong.size} of $of $fn records differ:\n" + wrong.take(20).joinToString("\n"))
    }

    @Test fun everyRecordIsOneOfSongNamesFunctions() {
        assertEquals(emptySet(), records.map { it.fn }.toSet() - setOf(CLEAN, CLEAN_CHANNEL, READ_NAMES))
        assertTrue(records.none { it.err != null }, "Python raised on a record")
    }

    @Test fun aTextLosesWhatAVideosTitleAddsToASongsName() {
        val wrong = of(CLEAN).mapNotNull { r ->
            val actual = SongNames.clean(r.args[0].jsonPrimitive.content)
            if (actual == r.out!!.jsonPrimitive.content) null else "${r.args}: Python ${r.out}, Kotlin \"$actual\""
        }
        fail(wrong, of(CLEAN).size, CLEAN)
    }

    @Test fun aChannelsNameLosesItsLabelWords() {
        val wrong = of(CLEAN_CHANNEL).mapNotNull { r ->
            val actual = SongNames.cleanChannel(r.args[0].jsonPrimitive.content)
            if (actual == r.out!!.jsonPrimitive.content) null else "${r.args}: Python ${r.out}, Kotlin \"$actual\""
        }
        fail(wrong, of(CLEAN_CHANNEL).size, CLEAN_CHANNEL)
    }

    @Test fun aTextNamesTheArtistAndTitlePythonReads() {
        val all = of(READ_NAMES)
        val wrong = mutableListOf<String>()
        fun check(r: Record, read: (String, String?) -> Pair<String, String>?) {
            val channel = (r.kw["channel"] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content
            val actual = try {
                named(read(r.args[0].jsonPrimitive.content, channel))
            } catch (e: Exception) {
                listOf("${e::class.simpleName}: ${e.message}")
            }
            if (actual != expected(r)) wrong.add("${r.extra["fixture"]} ${r.args} ${r.kw}: Python ${expected(r)}, Kotlin $actual")
        }
        for ((fixture, group) in all.groupBy { (it.extra["fixture"] as? JsonPrimitive)?.takeUnless { f -> f is JsonNull }?.content }) {
            if (fixture == null) {
                for (r in group) check(r) { text, channel -> SongNames.readNames(null, text, emptyList(), channel) }
                continue
            }
            val dir = tmp.newFolder(fixture)
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
                database.read { db ->
                    val songs = Songs.list(db)
                    for (r in group) check(r) { text, channel -> SongNames.readNames(db, text, songs, channel) }
                }
            }
        }
        fail(wrong, all.size, READ_NAMES)
    }

    @Test fun noDatabaseKnowsOnlyTheChannelGiven() {
        assertEquals(null, SongNames.readNames(null, "silvana estrada que problema", emptyList()))
        assertEquals("Silvana Estrada" to "que problema",
                     SongNames.readNames(null, "Silvana Estrada - que problema", emptyList()))
        assertEquals("Radiohead" to "Creep", SongNames.readNames(null, "Creep", emptyList(), channel = "Radiohead - Topic"))
    }

    companion object {
        const val VECTOR = "search/names.jsonl"
        const val CLEAN = "caracole.song_names.clean"
        const val CLEAN_CHANNEL = "caracole.song_names.clean_channel"
        const val READ_NAMES = "caracole.song_names.read_names"
    }
}
