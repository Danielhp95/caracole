package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.str
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame
import kotlin.test.fail

/** A name's forms (vectors/keys/name_forms.jsonl). */
class NameFormsTest {
    @Test fun nameFormsListingFormsAndOriginalPartsArePythons() {
        val vectors = KeyVectors("keys/name_forms.jsonl")
        for (record in Corpus.records("keys/name_forms.jsonl")) {
            if (record.fn != "test_conformance_keys.forms_of") fail("an unknown record: ${record.fn}")
            val s = record.args[0].str()
            val want = record.out!!.jsonObject
            assertEquals(setOf("name_forms", "listing_forms", "original_part"), want.keys)
            vectors.expect("name_forms", listOf(s), want["name_forms"]) { Normalize.nameForms(s) }
            vectors.expect("listing_forms", listOf(s), want["listing_forms"]) { Normalize.listingForms(s) }
            vectors.expect("original_part", listOf(s), want["original_part"]) { Normalize.originalPart(s) }
        }
        vectors.assertNoMiss()
    }

    @Test fun aNamesFormsAreKeptOnceMade() {
        val name = "Song Dongye (宋冬野)"
        assertSame(Normalize.nameForms(name), Normalize.nameForms(name))
    }
}
