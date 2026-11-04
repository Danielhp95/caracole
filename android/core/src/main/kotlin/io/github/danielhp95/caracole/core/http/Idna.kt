package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigInteger

/**
 * The `idna` package (3.x) as httpx calls it for a host that isn't ASCII, and to show one that is punycoded: `encode`
 * and `decode` with their defaults (no UTS 46 mapping, not strict, so the four dots separate labels), each label
 * checked as IDNA 2008 checks it (NFC, hyphens, no initial combining mark, each code point's class, CONTEXTJ and
 * CONTEXTO, the Bidi rule), the punycode Python's own codec writes and reads. Its tables are data,
 * data/caracole/http/idna.json (tests/test_conformance_http.py, from `idna.idnadata` and `unicodedata`). An error is
 * an [UrlError] whose kind is idna's exception's name.
 */
internal object Idna {
    private const val MAX_INPUT = 1024
    private const val VIRAMA = 9

    private class Ranges(pairs: JsonArray) {
        private val starts = IntArray(pairs.size)
        private val ends = IntArray(pairs.size)

        init {
            pairs.forEachIndexed { i, p -> starts[i] = p.jsonArray[0].jsonPrimitive.int; ends[i] = p.jsonArray[1].jsonPrimitive.int }
        }

        operator fun contains(cp: Int): Boolean {
            var lo = 0
            var hi = starts.size - 1
            while (lo <= hi) {
                val mid = (lo + hi) ushr 1
                when {
                    cp < starts[mid] -> hi = mid - 1
                    cp >= ends[mid] -> lo = mid + 1
                    else -> return true
                }
            }
            return false
        }
    }

    private class Tables(data: JsonObject) {
        val classes = data.getValue("classes").jsonObject.mapValues { Ranges(it.value.jsonArray) }
        val joining = data.getValue("joining").jsonObject.mapValues { Ranges(it.value.jsonArray) }
        val scripts = data.getValue("scripts").jsonObject.mapValues { Ranges(it.value.jsonArray) }
        val unnamed = Ranges(data.getValue("unnamed").jsonArray)
        private val bidiStarts: IntArray
        private val bidiValues: Array<String>

        init {
            val runs = data.getValue("bidi").jsonArray
            bidiStarts = IntArray(runs.size) { runs[it].jsonArray[0].jsonPrimitive.int }
            bidiValues = Array(runs.size) { runs[it].jsonArray[1].jsonPrimitive.content }
        }

        fun bidi(cp: Int): String {
            var lo = 0
            var hi = bidiStarts.size - 1
            while (lo < hi) {
                val mid = (lo + hi + 1) ushr 1
                if (bidiStarts[mid] <= cp) lo = mid else hi = mid - 1
            }
            return bidiValues[lo]
        }
    }

    private val tables: Tables by lazy { Tables(Json.parseToJsonElement(Database.resource("caracole/http/idna.json")).jsonObject) }

    private fun error(message: String, kind: String = "IDNAError") = UrlError(kind, message)

    private fun unot(cp: Int) = "U+" + cp.toString(16).let { h -> buildString { for (c in h) append(if (c in 'a'..'f') c - 32 else c) } }.padStart(4, '0')

    private const val DOTS = ".。．｡"

    /** `_unicode_dots_re.split(s)`. */
    private fun labels(s: String): MutableList<String> {
        val out = ArrayList<String>()
        var start = 0
        for (i in s.indices) if (s[i] in DOTS) { out.add(s.substring(start, i)); start = i + 1 }
        out.add(s.substring(start))
        return out
    }

    /** idna.encode(s): the A-labels of a domain, joined by dots. */
    fun encode(s: String): String {
        if (Py.len(s) > MAX_INPUT) throw error("Domain too long")
        if (Py.len(s) > 254) throw error("Domain too long")
        val labels = labels(s)
        if (labels.isEmpty() || labels == listOf("")) throw error("Empty domain")
        var trailingDot = false
        if (labels.last() == "") {
            labels.removeAt(labels.size - 1)
            trailingDot = true
        }
        val result = ArrayList<String>()
        for (label in labels) {
            val a = alabel(label)
            if (a.isEmpty()) throw error("Empty label")
            result.add(a)
        }
        if (trailingDot) result.add("")
        val joined = result.joinToString(".")
        if (joined.length > (if (trailingDot) 254 else 253)) throw error("Domain too long")
        return joined
    }

    /** idna.decode(s): the U-labels of an ASCII domain. */
    fun decode(s: String): String {
        if (!s.all { it.code < 0x80 }) throw error("Invalid ASCII in A-label")
        if (s.length > MAX_INPUT) throw error("Domain too long")
        if (s.length > 254) throw error("Domain too long")
        val labels = labels(s)
        if (labels.isEmpty() || labels == listOf("")) throw error("Empty domain")
        var trailingDot = false
        if (labels.last().isEmpty()) {
            labels.removeAt(labels.size - 1)
            trailingDot = true
        }
        val result = ArrayList<String>()
        for (label in labels) {
            val u = ulabel(label)
            if (u.isEmpty()) throw error("Empty label")
            result.add(u)
        }
        if (trailingDot) result.add("")
        return result.joinToString(".")
    }

    private fun alabel(label: String): String {
        if (Py.len(label) > MAX_INPUT) throw error("Label too long")
        if (label.all { it.code < 0x80 }) {
            ulabelAscii(label)
            if (label.length > 63) throw error("Label too long")
            return label
        }
        checkLabel(label)
        val a = "xn--" + Punycode.encode(label)
        if (a.length > 63) throw error("Label too long")
        return a
    }

    /** ulabel of a str: a non-ASCII label checked as it is, an ASCII one read as its bytes. */
    private fun ulabel(label: String): String {
        if (Py.len(label) > MAX_INPUT) throw error("Label too long")
        if (!label.all { it.code < 0x80 }) {
            checkLabel(label)
            return label
        }
        return ulabelAscii(label)
    }

    private fun ulabelAscii(given: String): String {
        val label = Py.asciiLower(given)
        if (!label.startsWith("xn--")) {
            checkLabel(label)
            return label
        }
        val rest = label.substring(4)
        if (rest.isEmpty()) throw error("Malformed A-label, no Punycode eligible content found")
        if (rest.endsWith("-")) throw error("A-label must not end with a hyphen")
        val decoded = Punycode.decode(rest) ?: throw error("Invalid A-label")
        checkLabel(decoded)
        return decoded
    }

    private fun checkLabel(label: String) {
        val cps = Py.codePoints(label)
        if (cps.size > MAX_INPUT) throw error("Label too long")
        if (cps.isEmpty()) throw error("Empty Label")
        if (cps.size > 254) throw error("Label too long")
        if (PyUnicode.nfc(label) != label) throw error("Label must be in Normalization Form C")
        if (cps.size >= 4 && cps[2] == '-'.code && cps[3] == '-'.code) {
            throw error("Label has disallowed hyphens in 3rd and 4th position")
        }
        if (cps[0] == '-'.code || cps[cps.size - 1] == '-'.code) throw error("Label must not start or end with a hyphen")
        if (PyUnicode.category(cps[0]).startsWith("M")) throw error("Label begins with an illegal combining character")
        val t = tables
        for ((pos, cp) in cps.withIndex()) {
            if (cp in t.classes.getValue("PVALID")) continue
            if (cp in t.classes.getValue("CONTEXTJ")) {
                // idna raises its InvalidCodepointContext for a joiner out of context inside `try: … except
                // ValueError:`, which catches it (an IDNAError is a ValueError) as it catches a code point with no
                // name: either way the label's error is this IDNAError.
                val valid = try {
                    contextj(cps, pos)
                } catch (e: NoName) {
                    false
                }
                if (!valid) {
                    throw error("Unknown codepoint adjacent to joiner ${unot(cp)} at position ${pos + 1} in ${PyStr.repr(label)}")
                }
            } else if (cp in t.classes.getValue("CONTEXTO")) {
                if (!contexto(cps, pos)) {
                    throw error("Codepoint ${unot(cp)} not allowed at position ${pos + 1} in ${PyStr.repr(label)}",
                                "InvalidCodepointContext")
                }
            } else {
                throw error("Codepoint ${unot(cp)} at position ${pos + 1} of ${PyStr.repr(label)} not allowed",
                            "InvalidCodepoint")
            }
        }
        checkBidi(cps, label)
    }

    private class NoName : Exception()

    private fun combiningClass(cp: Int): Int {
        val v = PyUnicode.combining(cp)
        if (v == 0 && cp in tables.unnamed) throw NoName()
        return v
    }

    private fun joiningType(cp: Int): String? = tables.joining.entries.firstOrNull { cp in it.value }?.key

    private fun contextj(cps: IntArray, pos: Int): Boolean {
        val cp = cps[pos]
        if (cp == 0x200C) {
            if (pos > 0 && combiningClass(cps[pos - 1]) == VIRAMA) return true
            var ok = false
            for (i in pos - 1 downTo 0) {
                val jt = joiningType(cps[i])
                if (jt == "T") continue
                if (jt == "L" || jt == "D") ok = true
                break
            }
            if (!ok) return false
            ok = false
            for (i in pos + 1 until cps.size) {
                val jt = joiningType(cps[i])
                if (jt == "T") continue
                if (jt == "R" || jt == "D") ok = true
                break
            }
            return ok
        }
        if (cp == 0x200D) return pos > 0 && combiningClass(cps[pos - 1]) == VIRAMA
        return false
    }

    private fun script(cp: Int, name: String) = cp in tables.scripts.getValue(name)

    private fun contexto(cps: IntArray, pos: Int): Boolean {
        val cp = cps[pos]
        val n = cps.size
        return when {
            cp == 0x00B7 -> pos in 1 until n - 1 && cps[pos - 1] == 0x6C && cps[pos + 1] == 0x6C
            cp == 0x0375 -> pos < n - 1 && n > 1 && script(cps[pos + 1], "Greek")
            cp == 0x05F3 || cp == 0x05F4 -> pos > 0 && script(cps[pos - 1], "Hebrew")
            cp == 0x30FB -> cps.any { it != 0x30FB && (script(it, "Hiragana") || script(it, "Katakana") || script(it, "Han")) }
            cp in 0x660..0x669 -> cps.none { it in 0x6F0..0x6F9 }
            cp in 0x6F0..0x6F9 -> cps.none { it in 0x660..0x669 }
            else -> false
        }
    }

    private val RTL_FIRST = setOf("R", "AL")
    private val RTL = setOf("R", "AL", "AN")
    private val RTL_ALLOWED = setOf("R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM")
    private val RTL_ENDING = setOf("R", "AL", "EN", "AN")
    private val NUMERIC = setOf("AN", "EN")
    private val LTR_ALLOWED = setOf("L", "EN", "ES", "CS", "ET", "ON", "BN", "NSM")
    private val LTR_ENDING = setOf("L", "EN")

    private fun bidiError(message: String) = error(message, "IDNABidiError")

    private fun checkBidi(cps: IntArray, label: String) {
        val t = tables
        var bidiLabel = false
        for ((idx, cp) in cps.withIndex()) {
            val direction = t.bidi(cp)
            if (direction.isEmpty()) throw bidiError("Unknown directionality in label ${PyStr.repr(label)} at position ${idx + 1}")
            if (direction in RTL) bidiLabel = true
        }
        if (!bidiLabel) return
        val first = t.bidi(cps[0])
        val rtl = when {
            first in RTL_FIRST -> true
            first == "L" -> false
            else -> throw bidiError("First codepoint in label ${PyStr.repr(label)} must be directionality L, R or AL")
        }
        var validEnding = false
        var numberType: String? = null
        for ((i, cp) in cps.withIndex()) {
            val idx = i + 1
            val direction = t.bidi(cp)
            if (rtl) {
                if (direction !in RTL_ALLOWED) {
                    throw bidiError("Invalid direction for codepoint at position $idx in a right-to-left label")
                }
                if (direction in RTL_ENDING) validEnding = true else if (direction != "NSM") validEnding = false
                if (direction in NUMERIC) {
                    if (numberType == null) numberType = direction
                    else if (numberType != direction) throw bidiError("Can not mix numeral types in a right-to-left label")
                }
            } else {
                if (direction !in LTR_ALLOWED) {
                    throw bidiError("Invalid direction for codepoint at position $idx in a left-to-right label")
                }
                if (direction in LTR_ENDING) validEnding = true else if (direction != "NSM") validEnding = false
            }
        }
        if (!validEnding) throw bidiError("Label ends with illegal codepoint directionality")
    }

    /** Python's "punycode" codec (RFC 3492), strict: encode, and decode or null where Python raises. */
    private object Punycode {
        private const val DIGITS = "abcdefghijklmnopqrstuvwxyz0123456789"

        private fun asciiUpper(s: String) = buildString(s.length) { for (c in s) append(if (c in 'a'..'z') c - 32 else c) }

        private fun t(j: Int, bias: Int): Int = (36 * (j + 1) - bias).coerceIn(1, 26)

        private fun adapt(given: Long, first: Boolean, numchars: Int): Int {
            var delta = if (first) given / 700 else given / 2
            delta += delta / numchars
            var divisions = 0
            while (delta > 455) {
                delta /= 35
                divisions += 36
            }
            return divisions + (36 * delta / (delta + 38)).toInt()
        }

        fun encode(text: String): String {
            val cps = Py.codePoints(text)
            val base = StringBuilder()
            for (cp in cps) if (cp < 128) base.append(cp.toChar())
            val extended = cps.filter { it >= 128 }.toSortedSet()
            // insertion_unsort
            val deltas = ArrayList<Long>()
            var oldchar = 0x80
            var oldindex = -1L
            for (c in extended) {
                var index = -1L
                var pos = -1
                val curlen = cps.count { it < c }
                var delta = (curlen + 1).toLong() * (c - oldchar)
                while (true) {
                    // selective_find
                    var found = false
                    while (true) {
                        pos += 1
                        if (pos == cps.size) break
                        val x = cps[pos]
                        if (x == c) { index += 1; found = true; break } else if (x < c) index += 1
                    }
                    if (!found) break
                    delta += index - oldindex
                    deltas.add(delta - 1)
                    oldindex = index
                    delta = 0
                }
                oldchar = c
            }
            // generate_integers
            val out = StringBuilder()
            var bias = 72
            for ((points, delta) in deltas.withIndex()) {
                var n = delta
                var j = 0
                while (true) {
                    val tt = t(j, bias)
                    if (n < tt) { out.append(DIGITS[n.toInt()]); break }
                    out.append(DIGITS[(tt + ((n - tt) % (36 - tt))).toInt()])
                    n = (n - tt) / (36 - tt)
                    j++
                }
                bias = adapt(delta, points == 0, base.length + points + 1)
            }
            return if (base.isNotEmpty()) "$base-$out" else out.toString()
        }

        fun decode(text: String): String? {
            val pos = text.lastIndexOf('-')
            val base: String
            val extended: String
            if (pos == -1) {
                base = ""
                extended = asciiUpper(text)
            } else {
                base = text.substring(0, pos)
                extended = asciiUpper(text.substring(pos + 1))
            }
            val out = ArrayList<Int>()
            base.forEach { out.add(it.code) }
            var char = BigInteger.valueOf(0x80)
            var at = BigInteger.valueOf(-1)
            var bias = 72
            var extpos = 0
            val maxChar = BigInteger.valueOf(0x10FFFF)
            while (extpos < extended.length) {
                // decode_generalized_number
                var result = BigInteger.ZERO
                var w = BigInteger.ONE
                var j = 0
                var p = extpos
                while (true) {
                    if (p >= extended.length) return null  // incomplete punycode string
                    val c = extended[p].code
                    p += 1
                    val digit = when (c) {
                        in 0x41..0x5A -> c - 0x41
                        in 0x30..0x39 -> c - 22
                        else -> return null  // invalid extended code point
                    }
                    val tt = t(j, bias)
                    result += BigInteger.valueOf(digit.toLong()) * w
                    if (digit < tt) break
                    w *= BigInteger.valueOf((36 - tt).toLong())
                    j++
                }
                val delta = result
                at += delta + BigInteger.ONE
                val size = BigInteger.valueOf((out.size + 1).toLong())
                char += at / size
                if (char > maxChar) return null  // invalid character
                at = at.mod(size)
                out.add(at.toInt(), char.toInt())
                // adapt with a delta that may be big: what Python's ints do, in Long once it fits
                bias = adaptBig(delta, extpos == 0, out.size)
                extpos = p
            }
            return buildString { for (cp in out) appendCodePoint(cp) }
        }

        private fun adaptBig(given: BigInteger, first: Boolean, numchars: Int): Int {
            var delta = if (first) given / BigInteger.valueOf(700) else given / BigInteger.TWO
            delta += delta / BigInteger.valueOf(numchars.toLong())
            var divisions = 0
            val limit = BigInteger.valueOf(455)
            while (delta > limit) {
                delta /= BigInteger.valueOf(35)
                divisions += 36
            }
            return divisions + (BigInteger.valueOf(36) * delta / (delta + BigInteger.valueOf(38))).toInt()
        }
    }
}
