package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyHtml
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import java.security.MessageDigest

/**
 * core.py's site records (vectors/py/sites_*.jsonl, tests/test_conformance_py.py) answered by :core as Python
 * answered them: html.unescape, json.loads and json.dumps with an indent, float() and int(), str.capitalize, and
 * urljoin, urlunsplit and urlencode. The JVM's tests (PyHtmlTest, PyJsonLoadsTest, PyNumbersTest, PyCapitalizeTest,
 * PyUrlTest) call each part; CorpusOnDeviceTest runs them all under ART. Lane py-format adds its format records.
 */
object PyReplay : AreaReplay {
    override val area = "py"

    override fun replay(misses: Misses) {
        unescape()
        json()
        numbers()
        capitalize()
        urls()
    }

    // --- html.unescape ------------------------------------------------------------------------------------------

    fun unescape() {
        val misses = Misses("py/sites_unescape.jsonl")
        var numeric = 0
        for (r in Corpus.records("py/sites_unescape.jsonl")) {
            when (r.fn) {
                "html.unescape" -> {
                    val inputs = r.args[0].jsonArray.map { it.jsonPrimitive.content }
                    if (r.err != null) {
                        for (s in inputs) misses.check(runCatching { PyHtml.unescape(s) }.exceptionOrNull() is
                            IllegalArgumentException) { "html.unescape(${s.take(40)}…) didn't raise: Python ${r.err}" }
                        continue
                    }
                    val outs = r.out!!.jsonArray
                    inputs.forEachIndexed { k, s ->
                        val want = outs[k].jsonPrimitive.content
                        val got = runCatching { PyHtml.unescape(s) }
                        misses.check(got.getOrNull() == want) {
                            "html.unescape(${show(s.take(60))}) = ${got.map { show(it) }}, Python ${show(want)}"
                        }
                    }
                }
                "html.unescape.numeric" -> {
                    numeric++
                    val form = r.args[0].jsonPrimitive.content
                    val first = r.args[1].jsonPrimitive.int
                    val last = r.args[2].jsonPrimitive.int
                    val runs = r.out!!.jsonArray.map { it.jsonArray }
                    var run = 0
                    for (n in first..last) {
                        while (run < runs.size && runs[run][1].jsonPrimitive.int < n) run++
                        val inRun = run < runs.size && runs[run][0].jsonPrimitive.int <= n
                        val want = if (inRun) runs[run][2].jsonPrimitive.content else String(Character.toChars(n))
                        val text = format(form, n)
                        val got = PyHtml.unescape(text)
                        misses.check(got == want) { "html.unescape($text) = ${show(got)}, Python ${show(want)}" }
                    }
                }
                else -> throw AssertionError("py/sites_unescape.jsonl: no replay for ${r.fn}")
            }
        }
        assertTrue("every numeric form replayed: $numeric", numeric >= 4)
        assertTrue("records checked: ${misses.checked}", misses.checked > 2_000_000)
        misses.assertNone()
    }

    /** Python's `form % n` for the forms the numeric records use: `%X`, `%x`, `%d` and `%0Nd`. */
    private fun format(form: String, n: Int): String {
        val at = form.indexOf('%')
        var k = at + 1
        var width = 0
        if (form[k] == '0') { k++; while (form[k] in '0'..'9') { width = width * 10 + (form[k] - '0'); k++ } }
        val body = when (form[k]) {
            'X' -> Integer.toHexString(n).let { h -> buildString { for (c in h) append(if (c in 'a'..'f') c - 32 else c) } }
            'x' -> Integer.toHexString(n)
            'd' -> n.toString()
            else -> throw AssertionError("no replay of the form $form")
        }
        return form.substring(0, at) + "0".repeat(maxOf(0, width - body.length)) + body + form.substring(k + 1)
    }

    // --- json.loads and json.dumps ------------------------------------------------------------------------------

    fun json() {
        val misses = Misses("py/sites_json.jsonl")
        var fixtures = 0
        for (r in Corpus.records("py/sites_json.jsonl")) {
            when (r.fn) {
                "json.loads" -> loaded(misses, r, r.args[0].jsonPrimitive.content) { PyJson.loads(it) }
                "json.loads(bytes)" -> {
                    val arg = r.args[0].jsonObject
                    val bytes = arg["fixture"]?.let { fixtures++; Corpus.fixture(it.jsonPrimitive.content) }
                        ?: unhex(arg.getValue("hex").jsonPrimitive.content)
                    loaded(misses, r, bytes) { PyJson.loads(it) }
                }
                "json.loads.numbers" -> {
                    val outs = r.out!!.jsonArray
                    r.args[0].jsonArray.forEachIndexed { k, literal ->
                        val text = literal.jsonPrimitive.content
                        val want = outs[k].jsonPrimitive.content
                        val got = runCatching { PyJson.dumps(PyJson.loads(text)) }
                        misses.check(got.getOrNull() == want) { "json.dumps(json.loads($text)) = $got, Python $want" }
                    }
                }
                else -> throw AssertionError("py/sites_json.jsonl: no replay for ${r.fn}")
            }
        }
        assertTrue("the fixtures' JSON files read: $fixtures", fixtures >= 10)
        assertTrue("records checked: ${misses.checked}", misses.checked > 3000)
        misses.assertNone()
    }

    private fun <T> loaded(misses: Misses, r: Record, input: T, loads: (T) -> JsonElement) {
        val shown = when (input) {
            is String -> show(input.take(80))
            is ByteArray -> hexBytes(input.copyOf(minOf(input.size, 40)))
            else -> input.toString()
        }
        val value = try {
            loads(input)
        } catch (e: Exception) {
            val raised = r.err
            misses.check(raised != null && raised == python(e, raised)) { "json.loads($shown) raised ${e}, Python ${r.err ?: r.out}" }
            return
        }
        if (r.err != null) {
            misses.check(false) { "json.loads($shown) = ${PyJson.dumps(value).take(80)}, Python raised ${r.err}" }
            return
        }
        for ((key, want) in r.out!!.jsonObject) {
            val name = key.substringBefore('_')
            val text = when (name) {
                "indent" -> PyJson.dumps(value, indent = 2)
                "dumps" -> PyJson.dumps(value)
                "ascii" -> PyJson.dumps(value, indent = 1, ensureAscii = true, sortKeys = true)
                else -> throw AssertionError("no replay of the output $key")
            }
            val ok = when {
                key.endsWith("_sha256") -> sha256(text) == want.jsonPrimitive.content
                key.endsWith("_utf16") -> text.map { it.code } == want.jsonArray.map { it.jsonPrimitive.int }
                else -> text == want.jsonPrimitive.content
            }
            misses.check(ok) { "json.loads($shown) written as $key: ${show(text.take(120))}, Python's ${want.toString().take(120)}" }
        }
    }

    /** What Python would have said of [e], in the record's words: `<type>: <message>`, or the type alone where the
     * record gives no message (a UTF-16 or UTF-32 decoding error). */
    private fun python(e: Exception, raised: String): String? {
        val type = when {
            e is PyJson.DecodeError -> "JSONDecodeError"
            e is IllegalArgumentException && e.message.orEmpty().startsWith("Exceeds the limit") -> "ValueError"
            e is IllegalArgumentException -> "UnicodeDecodeError"
            else -> return null
        }
        return if (raised == type) type else "$type: ${e.message}"
    }

    private fun unhex(s: String): ByteArray = ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    /** The SHA-256 of [s]'s UTF-8, each lone surrogate as its three bytes (Python's "surrogatepass"). */
    private fun sha256(s: String): String {
        val out = java.io.ByteArrayOutputStream(s.length)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            i += Character.charCount(cp)
            when {
                cp < 0x80 -> out.write(cp)
                cp < 0x800 -> { out.write(0xC0 or (cp shr 6)); out.write(0x80 or (cp and 0x3F)) }
                cp < 0x10000 -> {
                    out.write(0xE0 or (cp shr 12)); out.write(0x80 or ((cp shr 6) and 0x3F)); out.write(0x80 or (cp and 0x3F))
                }
                else -> {
                    out.write(0xF0 or (cp shr 18)); out.write(0x80 or ((cp shr 12) and 0x3F))
                    out.write(0x80 or ((cp shr 6) and 0x3F)); out.write(0x80 or (cp and 0x3F))
                }
            }
        }
        return hexBytes(MessageDigest.getInstance("SHA-256").digest(out.toByteArray()))
    }

    // --- float() and int() --------------------------------------------------------------------------------------

    fun numbers() {
        val misses = Misses("py/sites_numbers.jsonl")
        for (r in Corpus.records("py/sites_numbers.jsonl")) {
            val outs = r.out!!.jsonArray
            r.args[0].jsonArray.forEachIndexed { k, input ->
                val s = input.jsonPrimitive.content
                val want = outs[k].takeUnless { it is JsonNull }?.jsonPrimitive?.content
                when (r.fn) {
                    "float" -> {
                        val got = runCatching { PyFloat.parse(s) }
                        val bits = got.getOrNull()?.let { java.lang.Long.toHexString(it.toRawBits()).padStart(16, '0') }
                        misses.check(got.isSuccess && bits == want) {
                            "float(${show(s.take(60))}) = ${got.getOrNull()} ($bits), Python ${want ?: "ValueError"}"
                        }
                    }
                    "int" -> {
                        val got = runCatching { PyInt.parse(s) }
                        misses.check(got.isSuccess && got.getOrNull()?.toString() == want) {
                            "int(${show(s.take(60))}) = ${got.getOrNull()}, Python ${want?.take(40) ?: "ValueError"}"
                        }
                    }
                    else -> throw AssertionError("py/sites_numbers.jsonl: no replay for ${r.fn}")
                }
            }
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 3000)
        misses.assertNone()
    }

    // --- str.capitalize -----------------------------------------------------------------------------------------

    fun capitalize() {
        val misses = Misses("py/sites_capitalize.jsonl")
        for (r in Corpus.records("py/sites_capitalize.jsonl")) {
            val arg = r.args[0]
            if (arg is JsonPrimitive) {
                // Every code point: those listed map as listed, every other one to itself.
                val listed = r.out!!.jsonArray.associate { it.jsonArray[0].jsonPrimitive.int to it.jsonArray[1].jsonPrimitive.content }
                val after = when (arg.content) {
                    "each code point alone" -> false
                    "each code point after an a" -> true
                    else -> throw AssertionError("no replay of $arg")
                }
                for (cp in 0 until 0x110000) {
                    val c = String(Character.toChars(cp))
                    val want = listed[cp] ?: c
                    val got = if (after) PyUnicode.capitalize("a$c").let { if (it.startsWith("A")) it.substring(1) else "!$it" }
                              else PyUnicode.capitalize(c)
                    misses.check(got == want) { "capitalize(${if (after) "a" else ""}${hex(c)}) = ${show(got)}, Python ${show(want)}" }
                }
                continue
            }
            val outs = r.out!!.jsonArray
            arg.jsonArray.forEachIndexed { k, s ->
                val text = s.jsonPrimitive.content
                val want = outs[k].jsonPrimitive.content
                val got = PyUnicode.capitalize(text)
                misses.check(got == want) { "capitalize(${show(text)}) = ${show(got)}, Python ${show(want)}" }
            }
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 2_000_000)
        misses.assertNone()
    }

    // --- urljoin, urlunsplit, urlencode -------------------------------------------------------------------------

    fun urls() {
        val misses = Misses("py/sites_url.jsonl")
        for (r in Corpus.records("py/sites_url.jsonl")) {
            val outs = r.out!!.jsonArray
            when (r.fn) {
                "urllib.parse.urljoin" -> {
                    val base = r.args[0].jsonPrimitive.content
                    r.args[1].jsonArray.forEachIndexed { k, url ->
                        val ref = url.jsonPrimitive.content
                        answer(misses, "urljoin(${show(base)}, ${show(ref)})", outs[k]) { PyUrl.urljoin(base, ref) }
                    }
                }
                "urllib.parse.urlunsplit" -> r.args[0].jsonArray.forEachIndexed { k, parts ->
                    val p = parts.jsonArray.map { it.jsonPrimitive.content }
                    answer(misses, "urlunsplit($p)", outs[k]) { PyUrl.urlunsplit(PyUrl.Split(p[0], p[1], p[2], p[3], p[4])) }
                }
                "urllib.parse.urlencode" -> {
                    val doseq = r.kw.getValue("doseq").jsonPrimitive.boolean
                    r.args[0].jsonArray.forEachIndexed { k, case ->
                        val pairs = case.jsonArray.map { it.jsonArray }
                        answer(misses, "urlencode($case, doseq=$doseq)", outs[k]) {
                            if (doseq) {
                                PyUrl.urlencodeDoseq(pairs.map { p ->
                                    val v = p[1]
                                    p[0].jsonPrimitive.content to
                                        if (v is JsonArray) v.map { it.jsonPrimitive.content } else listOf(v.jsonPrimitive.content)
                                })
                            } else {
                                PyUrl.urlencode(pairs.map { it[0].jsonPrimitive.content to it[1].jsonPrimitive.content })
                            }
                        }
                    }
                }
                else -> throw AssertionError("py/sites_url.jsonl: no replay for ${r.fn}")
            }
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 4000)
        misses.assertNone()
    }

    /** [got] against Python's answer: a string, or `{"err": "ValueError: …"}`, which must be PyUrl.Invalid. */
    private fun answer(misses: Misses, call: String, want: JsonElement, got: () -> String) {
        val raised = (want as? JsonObject)?.get("err")?.jsonPrimitive?.content
        val answer = runCatching(got)
        if (raised != null) {
            val e = answer.exceptionOrNull()
            misses.check(e is PyUrl.Invalid && "ValueError: ${e.message}" == raised) { "$call = $answer, Python $raised" }
        } else {
            misses.check(answer.getOrNull() == want.jsonPrimitive.content) { "$call = $answer, Python $want" }
        }
    }
}
