package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * The lines of search.py that [Known] keeps a copy of (`library_by_artist` with no artist key, `gtptabs_songs`,
 * `no_ones`), against the search vectors Python wrote of search.py's own: names.jsonl has no name only gtptabs.com
 * knows, so only these records would see the copy drift from search.py.
 */
class KnownTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun records(vector: String, fn: String, keep: (Record) -> Boolean = { true }): List<Record> =
        Corpus.records(vector).filter { it.fn == fn && keep(it) }.also {
            assertTrue(it.isNotEmpty(), "$vector has no record of $fn")
        }

    private fun fixtureOf(record: Record): String? =
        (record.extra["fixture"] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content

    /** Each group of [records] over its fixture replayed into a fresh database; what [check] says is wrong. */
    private fun replay(records: List<Record>, check: (Db, Record) -> String?): List<String> {
        val wrong = mutableListOf<String>()
        for ((fixture, group) in records.groupBy { fixtureOf(it)!! }) {
            val dir = tmp.newFolder(fixture)
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
                database.read { db -> group.mapNotNullTo(wrong) { r -> check(db, r)?.let { "$fixture ${r.args}: $it" } } }
            }
        }
        return wrong
    }

    private fun failIf(wrong: List<String>, of: Int, fn: String) {
        if (wrong.isNotEmpty()) fail("${wrong.size} of $of $fn records differ:\n" + wrong.take(20).joinToString("\n"))
    }

    @Test fun anArtistsSongsOnGtptabsAreThoseSearchPyCounts() {
        val all = records("search/sites.jsonl", "caracole.search.gtptabs_songs")
        assertTrue(all.any { it.out!!.jsonPrimitive.long > 0 }, "no record counts a song on gtptabs.com")
        val wrong = replay(all) { db, r ->
            val actual = Known.gtptabsSongs(db, r.args[0].jsonPrimitive.content)
            val expected = r.out!!.jsonPrimitive.long
            if (actual == expected) null else "Python $expected, Kotlin $actual"
        }
        failIf(wrong, all.size, "gtptabs_songs")
    }

    @Test fun yourSongsByAnArtistAreThoseSearchPyLists() {
        val all = records("search/library.jsonl", "caracole.search.library_by_artist") { it.kw["artist_key"] is JsonNull }
        val wrong = replay(all) { db, r ->
            val actual = Known.libraryByArtist(Songs.list(db), r.args[0].jsonPrimitive.content).map { it.key }
            val expected = r.out!!.jsonArray.map { it.jsonPrimitive.content }
            if (actual == expected) null else "Python $expected, Kotlin $actual"
        }
        failIf(wrong, all.size, "library_by_artist")
    }

    @Test fun noOnesNameIsUgsCatchAllAlone() {
        val all = records("search/index.jsonl", "caracole.search.no_ones")
        val wrong = all.mapNotNull { r ->
            val actual = Known.noOnes(r.args[0].jsonPrimitive.content)
            if (actual == r.out!!.jsonPrimitive.boolean) null else "${r.args}: Python ${r.out}, Kotlin $actual"
        }
        failIf(wrong, all.size, "no_ones")
    }
}
