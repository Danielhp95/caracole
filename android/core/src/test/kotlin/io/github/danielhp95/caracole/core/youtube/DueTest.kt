package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals

/** Due.songs by hand, over due.jsonl's "every kind of song" scene (the corpus's records are YouTubeReplay's). */
class DueTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun aLastTryWhoseErrorIsEmptyIsNoFailureAsPythonsTruthSays() {
        val scene = Corpus.lines("youtube/due.jsonl")
            .first { it["case"]?.jsonPrimitive?.content == "every kind of song" }
        val o = scene.getValue("overrides").jsonObject
        val overrides = Overrides(
            ignore = o.getValue("ignore").jsonArray.map { it.jsonPrimitive.content }.toSet(),
            youtube = o.getValue("youtube").jsonObject.mapValues { (_, v) -> v.jsonPrimitive.contentOrNull },
            lacuerda = emptyMap<String, LaCuerdaPick>(),
        )
        val now = Instant.parse(scene.getValue("now").jsonPrimitive.content)
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                Fixtures.loadRecords(db, scene.getValue("fixture").jsonArray.map { it.jsonObject })
                assertEquals(listOf(1L, 5, 2, 7, 8, 9, 3, 4), Due.songs(db, overrides, now, false).map { it.id })
                // Song 4, "its last try failed", not noted: its error said as nothing, it is no failure.
                db.kvSet(Records.key(4), """{"error": "", "error_at": "2026-11-25T12:00:00Z"}""")
                assertEquals(listOf(1L, 5, 2, 4, 7, 8, 9, 3), Due.songs(db, overrides, now, false).map { it.id })
            }
        }
    }
}
