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

/** The canonical: canonical JSON, its digests and stored hashes, json.dumps and Python's float text (vectors/canonical/), every record answered by :core as Python answered it: the JVM's
 * tests' record loops, run on the device by CorpusOnDeviceTest. */
object CanonicalReplay : AreaReplay {
    override val area = "canonical"

    override fun replay(misses: Misses) {
        canonicalJsonAndItsHashesArePythons()
        jsonDumpsAndFloatTextArePythons()
    }

    private fun canonicalJsonAndItsHashesArePythons() {
        val misses = Misses("canonical/")
        for (r in Corpus.records("canonical/dumps.jsonl")) {
            val got = Canonical.write(r.args[0])
            misses.check(got == text(r.out!!)) { "dumps of ${r.args[0].toString().take(80)}: $got, Python ${r.out}" }
        }
        for (r in Corpus.records("canonical/digest.jsonl")) {
            val got = Canonical.digest(r.args[0])
            misses.check(got == text(r.out!!)) { "digest of ${r.args[0].toString().take(80)}: $got, Python ${r.out}" }
        }
        for (r in Corpus.records("canonical/stored_hash.jsonl")) {
            val stored = r.args[0].takeUnless { it is JsonNull }?.jsonPrimitive?.content
            stored(misses, r, stored, rawSurrogates = false)
        }
        for (r in Corpus.records("canonical/stored_hash_utf16.jsonl")) {
            val units = r.extra.getValue("utf16").jsonArray.map { it.jsonPrimitive.int.toChar() }
            stored(misses, r, String(units.toCharArray()), rawSurrogates = true)
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 300)
        misses.assertNone()
    }

    /**
     * A stored text's hash, whether it reads, and its canonical form, as Python's canonical.stored_hash has them. A
     * text with [rawSurrogates] (never SQLite's) may read as the pair its UTF-16 units make where Python reads two lone
     * surrogates (Canonical.parse): its hash tells them apart, and only a canonical form Python has is compared.
     */
    private fun stored(misses: Misses, r: Record, text: String?, rawSurrogates: Boolean) {
        val shown = text?.let { hex(it.take(40)) }
        val want = r.out.takeUnless { it == null || it is JsonNull }?.jsonPrimitive?.content
        misses.expect("stored_hash", shown, r.out ?: JsonNull) { Canonical.hashStoredJson(text) }
        if (text == null) return
        val reads = r.extra.getValue("reads").jsonPrimitive.boolean
        val canonical = r.extra["canonical"].takeUnless { it == null || it is JsonNull }?.jsonPrimitive?.content
        val value = runCatching { Canonical.parse(text) }
        misses.check(value.isSuccess == reads) { "parse($shown) reads: ${value.isSuccess}, Python $reads (hash $want)" }
        val written = value.getOrNull()?.let { v -> runCatching { Canonical.write(v) } }
        if (reads && written != null && (canonical != null || !rawSurrogates)) {
            misses.check(written.getOrNull() == canonical && (canonical != null || written.exceptionOrNull() is CanonicalError)) {
                "write(parse($shown)) = ${written.getOrNull() ?: written.exceptionOrNull()}, Python ${canonical ?: "not canonicalizable"}"
            }
        }
    }

    private fun jsonDumpsAndFloatTextArePythons() {
        val misses = Misses("canonical/pydumps.jsonl, float_text.jsonl")
        for (r in Corpus.records("canonical/pydumps.jsonl")) {
            val sortKeys = r.kw["sort_keys"]?.jsonPrimitive?.boolean == true
            val compact = r.kw["separators"] == JsonArray(listOf(JsonPrimitive(","), JsonPrimitive(":")))
            val value = text(r.extra.getValue("value"))
            val got = PyJson.dumps(Canonical.parse(value), sortKeys = sortKeys, compact = compact)
            misses.check(got == text(r.out!!)) { "json.dumps(${value.take(80)}, ${r.kw}) = $got, Python ${r.out}" }
        }
        val floats = Corpus.records("canonical/float_text.jsonl")
        assertTrue(floats.size > 4000)
        for (r in floats) {
            val x = text(r.args[0]).toDouble()
            val got = PyJson.floatText(x)
            misses.check(got == text(r.out!!)) { "json.dumps(${r.args[0]}) = $got, Python ${r.out}" }
            misses.check(got.toDouble().toRawBits() == x.toRawBits()) { "$got doesn't read back as ${r.args[0]}" }
        }
        misses.assertNone()
    }
}
