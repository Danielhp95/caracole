package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.pinyin.Pinyin
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.security.MessageDigest
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The keys: fold, slug and identity keys, name forms and safe names (vectors/keys/), every record answered by :core as Python answered it: the JVM's
 * tests' record loops, run on the device by CorpusOnDeviceTest. */
object KeysReplay : AreaReplay {
    override val area = "keys"

    override fun replay(misses: Misses) {
        foldIsPythonsForEveryCodePointAndString()
        slugAndIdentityKeysArePythons()
        nameFormsAndSafeNamesArePythons()
    }

    private fun foldIsPythonsForEveryCodePointAndString() {
        val misses = Misses("keys/fold.jsonl")
        var digests = 0
        for (record in Corpus.records("keys/fold.jsonl")) {
            when (record.fn) {
                "test_conformance_keys.fold_each" -> {
                    val each = Py.codePoints(text(record.args[0])).map { String(Character.toChars(it)) }
                    misses.expect(record) { each.map { Normalize.fold(it) } }
                }
                "test_conformance_keys.fold_digest" -> {
                    digests++
                    misses.expect(record) { foldDigest() }
                }
                "caracole.normalize.fold" -> misses.expect(record) { Normalize.fold(text(record.args[0])) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertEquals("fold.jsonl's digest records", 1, digests)
        misses.assertNone()
    }

    /** The SHA-256 of every code point's fold (the surrogates left out) joined by NUL, in UTF-8. */
    private fun foldDigest(): String {
        val sha = MessageDigest.getInstance("SHA-256")
        for (cp in 0 until 0x110000) {
            if (cp in 0xD800..0xDFFF) continue
            if (cp != 0) sha.update(0.toByte())
            sha.update(Normalize.fold(String(Character.toChars(cp))).toByteArray(Charsets.UTF_8))
        }
        return hexBytes(sha.digest())
    }

    private fun slugAndIdentityKeysArePythons() {
        val version = Corpus.records("keys/identity.jsonl").first()
        assertEquals("caracole.normalize.KEY_VERSION", version.fn)
        assertEquals(version.out!!.jsonPrimitive.int, Normalize.KEY_VERSION)

        val slugs = Misses("keys/slug.jsonl")
        for (record in Corpus.records("keys/slug.jsonl")) {
            val s = text(record.args[0])
            when (record.fn) {
                "test_conformance_keys.slugs_of" -> {
                    val want = record.out!!.jsonObject
                    val key = text(want.getValue("slug_key"))
                    slugs.expect("slug_key", s, want["slug_key"]) { Normalize.slugKey(s) }
                    slugs.expect("ug_slug_key", s, want["ug_slug_key"]) { Normalize.ugSlugKey(s) }
                    slugs.expect("compact", key, want["compact"]) { Normalize.compact(key) }
                    slugs.expect("split_variant", key, want["split_variant"]) { Normalize.splitVariant(key) }
                }
                "caracole.normalize.ug_slug_key" -> slugs.expect(record) { Normalize.ugSlugKey(s) }
                "caracole.normalize.split_variant" -> slugs.expect(record) { Normalize.splitVariant(s) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        slugs.assertNone()

        val identities = Misses("keys/identity.jsonl")
        val one: Map<String, (String) -> Any?> = mapOf(
            "clean_title" to Normalize::cleanTitle, "title_variant" to Normalize::titleVariant,
            "without_featuring" to Normalize::withoutFeaturing, "placeholder_artist" to Normalize::placeholderArtist,
            "has_han" to Normalize::hasHan, "has_other_script" to Normalize::hasOtherScript,
            "simplified" to Normalize::simplified, "romanize" to Normalize::romanize, "name_words" to Normalize::nameWords,
            "name_key" to Normalize::lacuerdaNameKey, "title_key" to Normalize::lacuerdaTitleKey,
        )
        for (record in Corpus.records("keys/identity.jsonl").drop(1)) {
            when (record.fn) {
                "test_conformance_keys.identity_of" -> {
                    val s = text(record.args[0])
                    val other = text(record.args[1])
                    val runs = record.args[2].jsonArray.map(::text)
                    val want = record.out!!.jsonObject
                    for ((name, f) in one) identities.expect(name, s, want[name]) { f(s) }
                    identities.expect("identity_key", "$s, $other", want["identity_key"]) { Normalize.identityKey(s, other) }
                    identities.expect("display_key", "$s, $other", want["display_key"]) { Normalize.displayKey(s, other) }
                    val words = Normalize.nameWords(s)
                    for ((i, pair) in want.getValue("holds_run").jsonArray.withIndex()) {
                        assertEquals(runs[i], text(pair.jsonArray[0]))
                        identities.expect("holds_run", "$s, ${runs[i]}", pair.jsonArray[1]) { Normalize.holdsRun(words, runs[i]) }
                    }
                }
                "caracole.normalize.canonical_variant" ->
                    identities.expect(record) { Normalize.canonicalVariant(text(record.args[0])) }
                "caracole.normalize.holds_run" ->
                    identities.expect(record) { Normalize.holdsRun(record.args[0].jsonArray.map(::text), text(record.args[1])) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        identities.assertNone()
    }

    private fun nameFormsAndSafeNamesArePythons() {
        val forms = Misses("keys/name_forms.jsonl")
        for (record in Corpus.records("keys/name_forms.jsonl")) {
            assertEquals("test_conformance_keys.forms_of", record.fn)
            val s = text(record.args[0])
            val want = record.out!!.jsonObject
            forms.expect("name_forms", s, want["name_forms"]) { Normalize.nameForms(s) }
            forms.expect("listing_forms", s, want["listing_forms"]) { Normalize.listingForms(s) }
            forms.expect("original_part", s, want["original_part"]) { Normalize.originalPart(s) }
        }
        forms.assertNone()

        val safe = Misses("keys/safe_name.jsonl")
        for (record in Corpus.records("keys/safe_name.jsonl")) {
            val s = text(record.args[0])
            when (record.fn) {
                "test_conformance_keys.safe_of" -> {
                    val other = text(record.args[1])
                    val want = record.out!!.jsonObject
                    safe.expect("safe_name", s, want["safe_name"]) { SafeName.safeName(s) }
                    safe.expect("song_folder", "$s, $other", want["song_folder"]) { SafeName.songFolder(s, other) }
                }
                "caracole.library.safe_name" -> safe.expect(record) { SafeName.safeName(s) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        safe.assertNone()
    }
}
