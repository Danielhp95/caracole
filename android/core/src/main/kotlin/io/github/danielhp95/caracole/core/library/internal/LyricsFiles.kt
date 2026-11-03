package io.github.danielhp95.caracole.core.library.internal

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.nio.CharBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/**
 * peer_sync.lyrics_files on the phone: the lyrics' files a song's folder holds for its `lyrics_json`, as
 * lyrics.write_lyrics writes them, `lyrics.txt` (the plain text) and `lyrics.lrc` (the timed one), each ending in a
 * newline, or null for one the lyrics have no text for, which goes; both null for no lyrics, or lyrics that can't be
 * read. lyrics.lyrics_from_json's reading of the JSON, LRCLIB's bare records included (Lyrics.from_record: LRC's ID
 * tags dropped, the plain text made from the timed one where it has none), with Python's `\s`, `\d`, `str.strip()` and
 * IGNORECASE. vectors/library/lyrics_files.jsonl holds Python's answers.
 */
internal object LyricsFiles {
    const val TXT = "lyrics.txt"
    const val LRC = "lyrics.lrc"

    fun of(lyricsJson: String?): LinkedHashMap<String, ByteArray?> {
        val (plain, synced) = read(lyricsJson) ?: ("" to null)
        val texts = linkedMapOf(TXT to plain.takeIf { Py.strip(it).isNotEmpty() }, LRC to synced)
        val out = LinkedHashMap<String, ByteArray?>()
        for ((name, text) in texts) out[name] = if (text.isNullOrEmpty()) null else utf8(text.trimEnd('\n') + "\n")
        return out
    }

    /** [text]'s UTF-8, as Python's str.encode gives it: IllegalArgumentException for a lone surrogate (its
     * UnicodeEncodeError, a ValueError, which leaves the unit a take was taking). */
    private fun utf8(text: String): ByteArray = try {
        val encoder = Charsets.UTF_8.newEncoder()
            .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
        val buffer = encoder.encode(CharBuffer.wrap(text))
        ByteArray(buffer.remaining()).also { buffer.get(it) }
    } catch (e: CharacterCodingException) {
        throw IllegalArgumentException("lyrics that can't be written as UTF-8 (a lone surrogate)", e)
    }

    /** lyrics_from_json: (plain, synced), or null for none or what can't be read. */
    private fun read(text: String?): Pair<String, String?>? {
        if (text == null || Py.strip(text).isEmpty()) return null
        val value = try {
            Canonical.parse(text)
        } catch (_: Exception) {
            return null
        }
        if (value !is JsonObject) return null
        if ("raw" !in value || "plain" !in value) return fromRecord(value)
        return (string(value["plain"]) ?: "") to string(value["synced"])
    }

    private fun string(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** lyrics._text: a text's line ends made `\n`, "" for anything but text. */
    private fun lines(e: JsonElement?): String = string(e)?.replace("\r\n", "\n")?.replace("\r", "\n") ?: ""

    /** Lyrics.from_record. */
    private fun fromRecord(raw: JsonObject): Pair<String, String?> {
        val synced = lines(raw["syncedLyrics"])
        val fromSynced = plainFromSynced(synced)
        val plain = withoutIdTags(lines(raw["plainLyrics"]))
        return (if (Py.strip(plain).isNotEmpty()) plain else fromSynced) to (if (fromSynced.isNotEmpty()) synced else null)
    }

    /** lyrics._without_id_tags: the lines that are LRC ID tags (`[ar:…]`, `[length:…]`, …) dropped. */
    private fun withoutIdTags(plain: String): String =
        plain.split("\n").filterNot { isIdTag(Py.strip(it)) }.joinToString("\n").trim('\n')

    private val ID_TAGS = listOf("ar", "al", "ti", "au", "by", "re", "ve", "la", "id", "length", "offset", "tool", "#")
        .map { PyRegex.ignoreCase(it) }

    /** `\[(?:ar|al|…|#):[^\]]*\]` fullmatched, IGNORECASE. */
    private fun isIdTag(line: String): Boolean {
        if (!line.startsWith("[") || !line.endsWith("]") || line.length < 3) return false
        val colon = line.indexOf(':')
        if (colon < 0) return false
        if (PyRegex.ignoreCase(line.substring(1, colon)) !in ID_TAGS) return false
        return ']' !in line.substring(colon + 1, line.length - 1)
    }

    /** lyrics.plain_from_synced: an empty timed line a break between stanzas. */
    private fun plainFromSynced(synced: String): String {
        val out = mutableListOf<String>()
        for ((_, text) in syncedLines(synced)) if (text.isNotEmpty() || (out.isNotEmpty() && out.last().isNotEmpty())) out += text
        while (out.isNotEmpty() && out.last().isEmpty()) out.removeAt(out.size - 1)
        return out.joinToString("\n")
    }

    /** lyrics.synced_lines: each line's stamps' times with its text, word stamps out and spaces collapsed, by time
     * (a stable sort). */
    private fun syncedLines(synced: String): List<Pair<Double, String>> {
        val timed = mutableListOf<Pair<Double, String>>()
        for (line in synced.split("\n")) {
            val cps = line.codePoints().toArray()
            val (stamps, end) = leadingStamps(cps)
            if (stamps.isEmpty()) continue
            val text = Py.split(withoutWordStamps(cps, end)).joinToString(" ")
            for ((minutes, seconds) in stamps) timed += (minutes.toDouble() + seconds) to text
        }
        return timed.sortedBy { it.first }
    }

    /** `(?:\s*\[\d+:\d{2}(?:\.\d+)?\])+` matched at the start: each stamp's minutes (times 60) and seconds, and where
     * the match ends; no stamps when it doesn't match. */
    private fun leadingStamps(cps: IntArray): Pair<List<Pair<BigInteger, Double>>, Int> {
        val stamps = mutableListOf<Pair<BigInteger, Double>>()
        var end = 0
        while (true) {
            var p = end
            while (p < cps.size && PyUnicode.isSpace(cps[p])) p++
            val stamp = stamp(cps, p, '['.code, ']'.code) ?: break
            stamps += stamp.first
            end = stamp.second
        }
        return stamps to end
    }

    /** One `<open>\d+:\d{2}(?:\.\d+)?<close>` at [from]: (minutes × 60, seconds) and where it ends. */
    private fun stamp(cps: IntArray, from: Int, open: Int, close: Int): Pair<Pair<BigInteger, Double>, Int>? {
        if (from >= cps.size || cps[from] != open) return null
        var p = from + 1
        val minutes = StringBuilder()
        while (p < cps.size && PyUnicode.isDecimal(cps[p])) minutes.append(digit(cps[p++]))
        if (minutes.isEmpty() || p >= cps.size || cps[p] != ':'.code) return null
        p++
        val seconds = StringBuilder()
        repeat(2) {
            if (p >= cps.size || !PyUnicode.isDecimal(cps[p])) return null
            seconds.append(digit(cps[p++]))
        }
        if (p + 1 < cps.size && cps[p] == '.'.code && PyUnicode.isDecimal(cps[p + 1])) {
            seconds.append('.')
            p++
            while (p < cps.size && PyUnicode.isDecimal(cps[p])) seconds.append(digit(cps[p++]))
        }
        if (p >= cps.size || cps[p] != close) return null
        return (BigInteger(minutes.toString()).multiply(BigInteger.valueOf(60)) to seconds.toString().toDouble()) to p + 1
    }

    /** lyrics._WORD_STAMP (`<\d+:\d{2}(?:\.\d+)?>`) taken out of the line from [from] on. */
    private fun withoutWordStamps(cps: IntArray, from: Int): String {
        val out = StringBuilder()
        var p = from
        while (p < cps.size) {
            val stamp = stamp(cps, p, '<'.code, '>'.code)
            if (stamp != null) {
                p = stamp.second
            } else {
                out.appendCodePoint(cps[p++])
            }
        }
        return out.toString()
    }

    /** A decimal digit's value as an ASCII digit: Unicode's decimal digits come in runs of ten from their zero, so
     * a digit's value is its distance from the start of its run of digits, modulo ten. */
    private fun digit(cp: Int): Char {
        if (cp in '0'.code..'9'.code) return cp.toChar()
        var start = cp
        while (PyUnicode.isDecimal(start - 1)) start--
        return '0' + (cp - start) % 10
    }
}
