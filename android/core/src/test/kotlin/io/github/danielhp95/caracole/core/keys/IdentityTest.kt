package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.str
import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.strings
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.fail

/** Slug keys and identity keys, and what they're made of (vectors/keys/slug.jsonl and identity.jsonl). */
class IdentityTest {
    @Test fun theKeyVersionIsPythons() {
        val record = Corpus.records("keys/identity.jsonl").first()
        assertEquals("caracole.normalize.KEY_VERSION", record.fn)
        assertEquals(record.out!!.jsonPrimitive.int, Normalize.KEY_VERSION)
        assertEquals(Normalize.KEY_VERSION, KeyTables.keyVersion)
    }

    @Test fun slugKeysArePythons() {
        val vectors = KeyVectors("keys/slug.jsonl")
        for (record in Corpus.records("keys/slug.jsonl")) {
            val s = record.args[0].str()
            when (record.fn) {
                "test_conformance_keys.slugs_of" -> {
                    val want = record.out!!.jsonObject
                    val key = want.getValue("slug_key").str()
                    vectors.expect("slug_key", listOf(s), want["slug_key"]) { Normalize.slugKey(s) }
                    vectors.expect("ug_slug_key", listOf(s), want["ug_slug_key"]) { Normalize.ugSlugKey(s) }
                    vectors.expect("compact", listOf(key), want["compact"]) { Normalize.compact(key) }
                    vectors.expect("split_variant", listOf(key), want["split_variant"]) { Normalize.splitVariant(key) }
                }
                "caracole.normalize.ug_slug_key" -> vectors.expect(record) { Normalize.ugSlugKey(s) }
                "caracole.normalize.split_variant" -> vectors.expect(record) { Normalize.splitVariant(s) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        vectors.assertNoMiss()
    }

    @Test fun identityKeysAndTheirPiecesArePythons() {
        val vectors = KeyVectors("keys/identity.jsonl")
        for (record in Corpus.records("keys/identity.jsonl").drop(1)) {
            when (record.fn) {
                "test_conformance_keys.identity_of" -> identityOf(vectors, record.args[0].str(), record.args[1].str(),
                    record.args[2].strings(), record.out!!.jsonObject)
                "caracole.normalize.canonical_variant" ->
                    vectors.expect(record) { Normalize.canonicalVariant(record.args[0].str()) }
                "caracole.normalize.holds_run" ->
                    vectors.expect(record) { Normalize.holdsRun(record.args[0].strings(), record.args[1].str()) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        vectors.assertNoMiss()
    }

    private fun identityOf(vectors: KeyVectors, s: String, other: String, runs: List<String>, want: JsonObject) {
        val one: Map<String, (String) -> Any?> = mapOf(
            "clean_title" to Normalize::cleanTitle, "title_variant" to Normalize::titleVariant,
            "without_featuring" to Normalize::withoutFeaturing, "placeholder_artist" to Normalize::placeholderArtist,
            "has_han" to Normalize::hasHan, "has_other_script" to Normalize::hasOtherScript,
            "simplified" to Normalize::simplified, "romanize" to Normalize::romanize, "name_words" to Normalize::nameWords,
            "name_key" to Normalize::lacuerdaNameKey, "title_key" to Normalize::lacuerdaTitleKey,
        )
        for ((name, f) in one) vectors.expect(name, listOf(s), want[name]) { f(s) }
        vectors.expect("identity_key", listOf(s, other), want["identity_key"]) { Normalize.identityKey(s, other) }
        vectors.expect("display_key", listOf(s, other), want["display_key"]) { Normalize.displayKey(s, other) }
        val words by lazy { Normalize.nameWords(s) }
        for ((i, pair) in want.getValue("holds_run").jsonArray.withIndex()) {
            val run = runs[i]
            assertEquals(run, pair.jsonArray[0].str())
            vectors.expect("holds_run", listOf(s, run), pair.jsonArray[1]) { Normalize.holdsRun(words, run) }
        }
        val unknown = want.keys - one.keys - setOf("identity_key", "display_key", "holds_run")
        if (unknown.isNotEmpty()) fail("identity_of answers what the test doesn't compare: $unknown")
    }
}
