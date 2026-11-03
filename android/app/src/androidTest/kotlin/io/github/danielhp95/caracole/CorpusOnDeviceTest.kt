package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
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
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.security.MessageDigest

/**
 * The conformance corpus on the device: the `unicode`, `keys`, `pinyin`, `fuzz` and `canonical` vectors
 * (tests/conformance/vectors/, the androidTest assets' `conformance/`, which app/build.gradle.kts copies), every record
 * answered by :core under Android's runtime, its ICU-backed java.util.regex and its own String, as the JVM's tests
 * answer them on the computer (PyUnicodeTest, PyRegexTest, PyTest, FoldTest, IdentityTest, NameFormsTest,
 * SafeNameTest, PinyinTest, FuzzTest, CanonicalTest, PyJsonTest: their record loops, not their hand-written cases).
 * A record that differs is named with Python's answer; a vector missing fails, never skips.
 *
 *     adb shell am instrument -w -e class io.github.danielhp95.caracole.CorpusOnDeviceTest \
 *         io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
 */
@RunWith(AndroidJUnit4::class)
class CorpusOnDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Before
    fun theVectorsAreTheTestsAssets() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
    }

    // --- unicode -----------------------------------------------------------------------------------------------------

    @Test
    fun everyCodePointHasPythonsPropertiesAndCategory() {
        val predicates: Map<String, (Int) -> Boolean> = mapOf(
            "str.isalnum" to PyUnicode::isAlnum, "str.isalpha" to PyUnicode::isAlpha,
            "str.isdecimal" to PyUnicode::isDecimal, "str.isdigit" to PyUnicode::isDigit,
            "str.isnumeric" to PyUnicode::isNumeric, "str.isspace" to PyUnicode::isSpace,
            "str.isprintable" to PyUnicode::isPrintable, "re.\\w" to PyUnicode::isWord, "re.\\s" to PyUnicode::isSpace,
            "re.\\d" to PyUnicode::isDecimal, "latin_by_name" to PyUnicode::latinByName,
        )
        val misses = Misses("unicode/strings.jsonl code points")
        var checked = 0
        for (record in Corpus.records("unicode/strings.jsonl").filter { it.fn.endsWith(".code_points") }) {
            val name = record.args[0].jsonPrimitive.content
            val runs = record.out!!.jsonArray.map { it.jsonArray }
            when (name) {
                "unicodedata.category" -> eachCodePoint(misses, name, runs, "Cn", { it[2].jsonPrimitive.content }) {
                    PyUnicode.category(it)
                }
                "unicodedata.combining" -> eachCodePoint(misses, name, runs, 0, { it[2].jsonPrimitive.int }) {
                    PyUnicode.combining(it)
                }
                // cased and case_ignorable are :core's own (internal): their answers reach the mapped strings below.
                "cased", "case_ignorable" -> continue
                else -> {
                    val test = predicates[name] ?: throw AssertionError("no Kotlin predicate for $name")
                    eachCodePoint(misses, name, runs, false, { true }) { test(it) }
                }
            }
            checked++
        }
        assertEquals(predicates.size + 2, checked)
        misses.assertNone()
    }

    private fun <T> eachCodePoint(misses: Misses, name: String, runs: List<JsonArray>, default: T, value: (JsonArray) -> T,
                                  actual: (Int) -> T) {
        var cp = 0
        fun check(upTo: Int, expected: T) {
            while (cp <= upTo) {
                val got = actual(cp)
                misses.check(got == expected) { "$name(U+%04X) = %s, Python %s".format(cp, got, expected) }
                cp++
            }
        }
        for (run in runs) {
            check(run[0].jsonPrimitive.int - 1, default)
            check(run[1].jsonPrimitive.int, value(run))
        }
        check(0x10FFFF, default)
    }

    @Test
    fun everyMappedCodePointAndEveryStringAnswersAsPythonsStrDoes() {
        val misses = Misses("unicode/strings.jsonl strings")
        val records = Corpus.records("unicode/strings.jsonl")
        val names = listOf("lower", "upper", "casefold", "nfc", "nfd", "nfkc", "nfkd", "ignorecase")
        val mapped = records.filter { it.fn.endsWith(".mapped") }
        assertTrue(mapped.size > 8000)
        for (record in mapped) {
            val s = Py.string(intArrayOf(record.args[0].jsonPrimitive.int))
            val out = record.out!!.jsonArray.map { it.jsonPrimitive.content }
            names.forEachIndexed { i, name ->
                val got = stringFunction(name, s)
                misses.check(got == out[i]) { "$name(${hex(s)}) = ${hex(got)}, Python ${hex(out[i])}" }
            }
        }
        val answers = records.filter { it.fn.endsWith(".answers") }
        assertTrue(answers.size >= 3000)
        for (record in answers) {
            val s = record.args[0].jsonPrimitive.content
            for ((name, expected) in record.out as JsonObject) {
                val got: Any = when (name) {
                    "isalnum" -> PyUnicode.allAlnum(s)
                    "isalpha" -> PyUnicode.allAlpha(s)
                    "isdigit" -> PyUnicode.allDigit(s)
                    "isspace" -> PyUnicode.allSpace(s)
                    "len" -> Py.len(s)
                    else -> stringFunction(name, s)
                }
                val want: Any = when (got) {
                    is Boolean -> expected.jsonPrimitive.boolean
                    is Int -> expected.jsonPrimitive.int
                    else -> expected.jsonPrimitive.content
                }
                misses.check(got == want) { "$name(${hex(s)}) = ${show(got)}, Python ${show(want)}" }
            }
        }
        misses.assertNone()
    }

    private fun stringFunction(name: String, s: String): String = when (name) {
        "lower" -> PyUnicode.lower(s)
        "upper" -> PyUnicode.upper(s)
        "casefold" -> PyUnicode.casefold(s)
        "nfc" -> PyUnicode.nfc(s)
        "nfd" -> PyUnicode.nfd(s)
        "nfkc" -> PyUnicode.nfkc(s)
        "nfkd" -> PyUnicode.nfkd(s)
        "ignorecase" -> PyRegex.ignoreCase(s)
        else -> throw AssertionError("no Kotlin function for $name")
    }

    @Test
    fun everyRegexRecordAnswersAsPythonsReDidThroughAndroidsRegex() {
        val misses = Misses("unicode/regex.jsonl")
        val records = Corpus.records("unicode/regex.jsonl")
        assertTrue(records.size > 9000)
        val compiled = HashMap<String, Regex>()
        for (r in records) {
            val pattern = r.args[0].jsonPrimitive.content
            if (r.err != null) {
                misses.check(runCatching { PyRegex.compile(pattern) }.isFailure) { "$pattern compiles, Python refuses it (${r.err})" }
                continue
            }
            val s = r.args[1].jsonPrimitive.content
            val ignoreCase = r.kw["flags"]?.jsonPrimitive?.content == "IGNORECASE"
            val source = (if (ignoreCase) "(?i)" else "") + pattern
            val regex = try {
                compiled.getOrPut(source) { PyRegex.compile(source) }
            } catch (e: Exception) {
                misses.check(false) { "$pattern doesn't compile: $e" }
                continue
            }
            val got: Any? = when (r.fn) {
                "re.findall" -> PyRe.findall(regex, s)
                "re.split" -> PyRe.split(regex, s, r.kw["maxsplit"]?.jsonPrimitive?.int ?: 0)
                "re.sub" -> r.kw["repl"]!!.jsonPrimitive.content.let { repl ->
                    PyRe.sub(regex, s, r.kw["count"]?.jsonPrimitive?.int ?: 0) { repl }
                }
                "re.fullmatch" -> PyRe.fullmatch(regex, s)?.value
                else -> throw AssertionError("no Kotlin function for ${r.fn}")
            }
            val want: Any? = when (val out = r.out!!) {
                is JsonNull -> null
                is JsonArray -> out.map { if (it is JsonNull) null else it.jsonPrimitive.content }
                else -> out.jsonPrimitive.content
            }
            misses.check(got == want) {
                "${r.fn}(${show(pattern)}, ${show(s)}${if (ignoreCase) ", IGNORECASE" else ""}${r.kw}) = ${show(got)}, Python ${show(want)}"
            }
        }
        misses.assertNone()
    }

    @Test
    fun everyPyRecordAnswersAsPythonDid() {
        val misses = Misses("unicode/py.jsonl")
        for (r in Corpus.records("unicode/py.jsonl")) {
            val a = r.args
            val got: Any? = when (r.fn) {
                "round" -> Py.round(double(a[0]), a[1].jsonPrimitive.int)
                "sum" -> Py.fsum(a[0].jsonArray.map(::double))
                "str.split" -> Py.split(text(a[0]))
                "str.strip" -> Py.strip(text(a[0]))
                "len" -> Py.len(text(a[0]))
                "slice" -> Py.slice(text(a[0]), a[1].intOrNull(), a[2].intOrNull())
                "sorted" -> a[0].jsonArray.map(::text).sortedWith(Py.CODE_POINT_ORDER)
                "collections.Counter.most_common" -> Py.mostCommonFirst(a[0].jsonArray.map(::text))
                "bytes.lower" -> Py.asciiLower(text(a[0]))
                "operator.mod" -> Py.floorMod(a[0].jsonPrimitive.int, a[1].jsonPrimitive.int)
                else -> throw AssertionError("no Kotlin function for ${r.fn}")
            }
            val out = r.out!!
            val want: Any? = when {
                out is JsonNull -> null
                got is Double -> double(out)
                got is Int -> out.jsonPrimitive.int
                got is List<*> -> out.jsonArray.map(::text)
                else -> text(out)
            }
            misses.check(got == want) { "${r.fn}${r.args} = $got, Python $want" }
        }
        misses.assertNone()
    }

    // --- keys --------------------------------------------------------------------------------------------------------

    @Test
    fun foldIsPythonsForEveryCodePointAndString() {
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

    @Test
    fun slugAndIdentityKeysArePythons() {
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

    @Test
    fun nameFormsAndSafeNamesArePythons() {
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

    // --- pinyin ------------------------------------------------------------------------------------------------------

    @Test
    fun everyPinyinRecordReadsAsPypinyinReadsIt() {
        val lazy = Misses("pinyin/lazy.jsonl")
        val records = Corpus.records("pinyin/lazy.jsonl")
        assertTrue(records.size > 8000)
        for (record in records) {
            val errors = when (val e = record.kw.getValue("errors").jsonPrimitive.content) {
                "default" -> Pinyin.Errors.DEFAULT
                "ignore" -> Pinyin.Errors.IGNORE
                else -> throw AssertionError("errors=$e")
            }
            val s = text(record.args.single())
            val got = Pinyin.lazyPinyin(s, errors)
            val want = record.out!!.jsonArray.map(::text)
            lazy.check(got == want) { "lazy_pinyin(${JsonPrimitive(s)}, $errors): $got, pypinyin $want" }
        }
        lazy.assertNone()

        val heteronyms = Misses("pinyin/heteronyms.jsonl")
        var chars = 0
        for (record in Corpus.records("pinyin/heteronyms.jsonl")) {
            val s = text(record.args.single())
            val want = record.out!!.jsonArray.map { cp -> cp.jsonArray.map(::text) }
            val cps = Py.codePoints(s)
            chars += cps.size
            for ((i, cp) in cps.withIndex()) {
                val got = Pinyin.heteronyms(cp)
                heteronyms.check(got == want.getOrNull(i)) { "heteronyms(U+%04X): %s, pypinyin %s".format(cp, got, want.getOrNull(i)) }
            }
        }
        assertTrue("$chars characters", chars > 41_000)
        heteronyms.assertNone()
    }

    // --- fuzz --------------------------------------------------------------------------------------------------------

    @Test
    fun everyFuzzRecordIsRapidfuzzsToTheDouble() {
        val misses = Misses("fuzz/")
        fun arg(r: Record, i: Int) = text(r.args[i])
        for (r in Corpus.records("fuzz/ratio.jsonl")) {
            val got = Fuzz.ratio(arg(r, 0), arg(r, 1))
            misses.check(got == r.out!!.jsonPrimitive.double) { "ratio ${r.args}: rapidfuzz ${r.out}, Fuzz $got" }
        }
        for (r in Corpus.records("fuzz/token_sort.jsonl")) {
            val got = Fuzz.tokenSortRatio(arg(r, 0), arg(r, 1))
            misses.check(got == r.out!!.jsonPrimitive.double) { "token_sort ${r.args}: rapidfuzz ${r.out}, Fuzz $got" }
        }
        for (r in Corpus.records("fuzz/partial_alignment.jsonl")) {
            val o = r.out!!.jsonObject
            val want = Fuzz.Alignment(o["score"]!!.jsonPrimitive.double, o["src_start"]!!.jsonPrimitive.int,
                o["src_end"]!!.jsonPrimitive.int, o["dest_start"]!!.jsonPrimitive.int, o["dest_end"]!!.jsonPrimitive.int)
            val got = Fuzz.partialRatioAlignment(arg(r, 0), arg(r, 1))
            misses.check(got == want) { "partial_alignment ${r.args}: rapidfuzz $want, Fuzz $got" }
        }
        val extracts = Corpus.records("fuzz/extract.jsonl")
        assertTrue(extracts.size > 800)
        for (r in extracts) {
            val want = r.out!!.jsonArray.map { row ->
                val (choice, score, index) = row.jsonArray
                Fuzz.Extracted(choice.jsonPrimitive.content, score.jsonPrimitive.double, index.jsonPrimitive.int)
            }
            val limit = r.kw["limit"].takeUnless { it == null || it is JsonNull }?.jsonPrimitive?.int
            val got = Fuzz.extract(arg(r, 0), r.args[1].jsonArray.map(::text), r.kw["score_cutoff"]!!.jsonPrimitive.double, limit)
            misses.check(got == want) { "extract ${r.args} ${r.kw}: rapidfuzz $want, Fuzz $got" }
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 18_000)
        misses.assertNone()
    }

    // --- canonical ---------------------------------------------------------------------------------------------------

    @Test
    fun canonicalJsonAndItsHashesArePythons() {
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

    @Test
    fun jsonDumpsAndFloatTextArePythons() {
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

    // --- how answers are compared ------------------------------------------------------------------------------------

    /** The answers of one vector that differ from Python's, gathered so that a failure names the first ones. */
    private class Misses(private val name: String) {
        private val found = ArrayList<String>()
        var checked = 0
            private set

        fun check(ok: Boolean, said: () -> String) {
            checked++
            if (!ok && found.size < 1000) found += said()
        }

        /** [got]'s answer as JSON against [want], Python's (`{"err": …}` when Python raised: then [got] must throw). */
        fun expect(fn: String, args: Any?, want: JsonElement?, got: () -> Any?) {
            val raised = (want as? JsonObject)?.get("err")
            val answer = try {
                json(got())
            } catch (e: Exception) {
                check(raised != null) { "$fn($args) threw $e, Python answered $want" }
                return
            }
            if (raised != null) check(false) { "$fn($args) answered $answer, Python raised $raised" }
            else check(answer == (want ?: JsonNull)) { "$fn(${args.toString().take(120)}) = $answer, Python's $want" }
        }

        fun expect(record: Record, got: () -> Any?) = expect(record.fn, record.args.toString().take(120),
            record.err?.let { JsonObject(mapOf("err" to JsonPrimitive(it))) } ?: record.out, got)

        fun assertNone() {
            if (checked == 0) fail("$name: no record checked")
            if (found.isNotEmpty()) {
                fail("$name: ${found.size} of $checked answers differ from Python's on this device; the first:\n" +
                    found.take(25).joinToString("\n"))
            }
        }

        private fun json(value: Any?): JsonElement = when (value) {
            null -> JsonNull
            is JsonElement -> value
            is String -> JsonPrimitive(value)
            is Boolean -> JsonPrimitive(value)
            is Int -> JsonPrimitive(value)
            is Pair<*, *> -> JsonArray(listOf(json(value.first), json(value.second)))
            is List<*> -> JsonArray(value.map { json(it) })
            else -> throw AssertionError("no JSON for $value")
        }
    }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun JsonElement.intOrNull(): Int? = if (this is JsonNull) null else jsonPrimitive.int

    private fun double(e: JsonElement): Double {
        val p = e as JsonPrimitive
        if (p.isString) return when (p.content) {
            "inf" -> Double.POSITIVE_INFINITY
            "-inf" -> Double.NEGATIVE_INFINITY
            "nan" -> Double.NaN
            else -> throw AssertionError("not a float: $p")
        }
        return p.content.toDouble()
    }

    private fun hex(s: String): String = Py.codePoints(s).joinToString(" ", "[", "]") { "%04X".format(it) }
    private fun show(x: Any?): String = when (x) {
        is String -> hex(x)
        is List<*> -> x.joinToString(", ", "[", "]") { show(it) }
        else -> x.toString()
    }

    private fun hexBytes(bytes: ByteArray): String {
        val digits = "0123456789abcdef"
        return bytes.joinToString("") { b -> "${digits[b.toInt() shr 4 and 15]}${digits[b.toInt() and 15]}" }
    }
}
