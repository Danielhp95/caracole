package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.str
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.fail

/** library.safe_name and song_folder (vectors/keys/safe_name.jsonl). */
class SafeNameTest {
    @Test fun safeNamesAndSongFoldersArePythons() {
        val vectors = KeyVectors("keys/safe_name.jsonl")
        for (record in Corpus.records("keys/safe_name.jsonl")) {
            val s = record.args[0].str()
            when (record.fn) {
                "test_conformance_keys.safe_of" -> {
                    val other = record.args[1].str()
                    val want = record.out!!.jsonObject
                    assertEquals(setOf("safe_name", "song_folder"), want.keys)
                    vectors.expect("safe_name", listOf(s), want["safe_name"]) { SafeName.safeName(s) }
                    vectors.expect("song_folder", listOf(s, other), want["song_folder"]) { SafeName.songFolder(s, other) }
                }
                "caracole.library.safe_name" -> vectors.expect(record) { SafeName.safeName(s) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        vectors.assertNoMiss()
    }

    @Test fun theLimitIsLibraryPys() {
        assertEquals(120, KeyTables.maxNameBytes)
    }
}
