package io.github.danielhp95.caracole.core.youtube

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * No yt-dlp flag, pattern or word of youtube.py is typed under core/youtube/: each is youtube.json's (the plan's "One
 * source for the rules"). Every file of the package is read, HostGate.kt and YtDlp.kt among them (the gate's hosts
 * are youtube.json's, read through YouTubeData); its string literals (a template's text, not what its `${…}` holds),
 * comments aside, may hold none of:
 *
 * - `--` or `-x` at the start: a flag;
 * - yt-dlp's line prefixes, `ERROR:`, `WARNING:` and `[debug]`, or a target's, `ytsearch` and `watch?v=`;
 * - any of the data's own texts of four characters or more ([dataTexts]): the arguments and each template element's
 *   fixed text (`quickjs:`, the `--print` expression), the targets' and the lines' prefixes, every pattern's source
 *   and each of its alternatives that is a phrase (a word alone is any code's), the phone's format and output name,
 *   the gate's hosts and words, the runner's and the answers' words, the search gate's states, keys and words and
 *   the record's; a literal that is exactly one of the data's keys, or of the record's fields (how the code reads the
 *   data and a record), excepted;
 *
 * and no literal is compiled as a pattern (`Regex(`, `PyRegex.compile(`, `Pattern.compile(` or `.toRegex()` of one).
 */
class NoLiteralsTest {
    private val root = File("src/main/kotlin/io/github/danielhp95/caracole/core/youtube")

    @Test fun noFlagPatternOrPrefixIsTypedInThePackage() {
        val files = root.listFiles { f -> f.name.endsWith(".kt") }.orEmpty().sortedBy { it.name }
        assertTrue(files.map { it.name }.containsAll(listOf("Choose.kt", "Classify.kt", "HostGate.kt", "Videos.kt",
            "YouTubeData.kt", "YtDlp.kt", "YtDlpProcess.kt", "SearchGate.kt", "Records.kt")), "the package's files: ${files.map { it.name }}")
        val found = files.flatMap { f -> scan(f.readText()).map { "${f.name}: $it" } }
        assertEquals(emptyList(), found)
    }

    @Test fun theScanFindsWhatItForbids() {
        assertEquals(4, scan("val a = \"--proxy\"; val b = \"-o\"; val c = \"x ERROR: y\"; val d = Regex(\"a+\")").size)
        assertEquals(2, scan("val p = \"\"\"[debug]\"\"\".toRegex()").size + scan("// \"--proxy\" in a comment").size)
        assertEquals(emptyList(), scan("/* \"--x\" */ val s = \"a-b\" // ERROR: said"))
        // The data's own texts, kept in a val or anywhere in a literal.
        assertEquals(1, scan("val f = \"bestaudio[ext=m4a]\"").size)
        assertEquals(1, scan("val w = \"a Too Many Requests here\"").size)
        assertEquals(1, scan("val q = \"quickjs:\$path\"").size)
        assertEquals(1, scan("val h = \"jnn-pa.googleapis.com\"").size)
        assertEquals(1, scan("val y = \"YouTube turned us back\"").size, "the search gate's words")
        assertEquals(1, scan("val k = \"youtube-search:failed\"").size, "the search gate's keys")
        assertEquals(emptyList(), scan("val f = \"unusable_reason\""), "a record's field is how it's read")
        assertEquals(emptyList(), scan("val k = \"live_statuses\"; val n = \"x\""), "a key of the data is how it's read")
    }

    @Test fun aQuoteInsideATemplatesExpressionDoesNotEndTheLiteral() {
        assertEquals(emptyList(), scan("val a = \"x \${f(\"y\")} z\""))
        assertEquals(1, scan("val a = \"\${f(\"y\")} ERROR: z\"").size, "the literal goes on after the expression")
        assertEquals(1, scan("val a = \"\${m[\"k\"]?.let { \"--proxy\" }}\"").size, "a literal inside the expression")
        assertEquals(1, scan("val a = \"\"\"\${g(\"a\")} x\"\"\"; val b = \"ytsearch\"").size)
    }

    private val forbidden = Regex("^-(?:-|[A-Za-z]\\b)|ERROR:|WARNING:|\\[debug]|ytsearch|watch\\?v=")
    private val compiles = Regex("(?:\\bRegex|PyRegex\\s*\\.\\s*compile|Pattern\\s*\\.\\s*compile)\\s*\\(\\s*\"|\"\\s*\\.\\s*toRegex\\(")

    /** The data's keys, at any depth. */
    private val dataKeys: Set<String> by lazy {
        val keys = HashSet<String>()
        fun walk(e: JsonElement) {
            when (e) {
                is JsonObject -> e.forEach { (k, v) -> keys += k; walk(v) }
                is JsonArray -> e.forEach(::walk)
                else -> Unit
            }
        }
        walk(YouTubeData.read().json)
        // The record's fields are its JSON's keys, as a member's name is the data's: how the code reads one.
        YouTubeData.read().json.getValue("record").jsonObject.getValue("fields").jsonArray.forEach { keys += it.jsonPrimitive.content }
        keys
    }

    /** The data's own texts a literal may not hold (this class's KDoc), each four characters or more. */
    private val dataTexts: Set<String> by lazy {
        val json = YouTubeData.read().json
        val out = HashSet<String>()
        val marks = Regex("<[a-z_]+>|\\{[^}]*\\}")
        fun fixed(text: String) = text.split(marks).forEach { out += it }
        fun strings(e: JsonElement): List<String> = when (e) {
            is JsonObject -> e.values.flatMap(::strings)
            is JsonArray -> e.flatMap(::strings)
            is JsonPrimitive -> if (e.isString) listOf(e.content) else emptyList()
        }
        fun patterns(group: JsonObject) = group.values.forEach { p ->
            val source = p.jsonObject.getValue("pattern").jsonPrimitive.content
            out += source
            // Its alternatives that are phrases ("not a bot", "Too Many Requests"): a word alone is any code's.
            source.replace(Regex("\\\\[a-zA-Z]"), "|").split(Regex("[|()\\[\\]?*+^$\\\\]|\\?:"))
                .map { it.trim() }.filter { ' ' in it }.forEach { out += it }
        }
        strings(json.getValue("args")).forEach(::fixed)
        strings(json.getValue("phone_argv")).forEach(::fixed)
        for (name in listOf("search_prefix", "watch_url")) fixed(json.getValue("targets").jsonObject.getValue(name).jsonPrimitive.content)
        for (name in listOf("skip_prefix", "error_prefix", "warning_prefix")) {
            out += json.getValue("classify").jsonObject.getValue(name).jsonPrimitive.content
        }
        patterns(json.getValue("patterns").jsonObject)
        patterns(json.getValue("choose").jsonObject.getValue("patterns").jsonObject)
        patterns(JsonObject(mapOf("video_id" to json.getValue("targets").jsonObject.getValue("video_id"))))
        for (name in listOf("phone_format", "output_name", "max_filesize", "search_query")) {
            fixed(json.getValue(name).jsonPrimitive.content)
        }
        strings(json.getValue("gate")).forEach(::fixed)
        strings(json.getValue("runner")).forEach(::fixed)
        strings(json.getValue("search")).forEach(::fixed)
        json.getValue("record").jsonObject.let { r -> strings(JsonObject(r - "fields")).forEach(::fixed) }
        strings(json.getValue("answers").jsonObject.let { JsonObject(it - "provider" - "live_statuses") }).forEach(::fixed)
        out.filter { it.length >= 4 }.toSet()
    }

    /** What [source] holds that it mustn't: each string literal's, and each literal compiled as a pattern. */
    private fun scan(source: String): List<String> {
        val out = ArrayList<String>()
        val code = StringBuilder()
        Lexer(source, out, code).code(0, inTemplate = false)
        out += compiles.findAll(code).map { "a literal compiled as a pattern: ${it.value}" }
        return out
    }

    /**
     * Kotlin's source split into code and literals: a `//` or `/* */` comment skipped, a `"…"` or `"""…"""` literal's
     * text collected (its `${…}` expressions read as code, their own literals among them), a character literal
     * skipped. [code] gets the code with each literal left as `""`.
     */
    private inner class Lexer(val s: String, val out: MutableList<String>, val code: StringBuilder) {
        /** Code from [start] to its end, or, [inTemplate], to the `}` closing a `${`: the index after it. */
        fun code(start: Int, inTemplate: Boolean): Int {
            var i = start
            var depth = 0
            while (i < s.length) {
                when {
                    s.startsWith("//", i) -> i = s.indexOf('\n', i).let { if (it < 0) s.length else it }
                    s.startsWith("/*", i) -> i = s.indexOf("*/", i + 2).let { if (it < 0) s.length else it + 2 }
                    s.startsWith("\"\"\"", i) -> {
                        code.append("\"\"")
                        i = literal(i + 3, raw = true)
                    }
                    s[i] == '"' -> {
                        code.append("\"\"")
                        i = literal(i + 1, raw = false)
                    }
                    s[i] == '\'' && i + 2 < s.length -> {
                        val j = s.indexOf('\'', i + 1 + if (s[i + 1] == '\\') 2 else 1)
                        code.append("''")
                        i = if (j < 0) s.length else j + 1
                    }
                    inTemplate && s[i] == '{' -> { depth++; code.append(s[i++]) }
                    inTemplate && s[i] == '}' -> {
                        if (depth == 0) return i + 1
                        depth--
                        code.append(s[i++])
                    }
                    else -> code.append(s[i++])
                }
            }
            return i
        }

        /** A literal's text from [start] (after its opening quotes), each `${…}` read as code and its text split
         * there: the index after its closing quotes. */
        fun literal(start: Int, raw: Boolean): Int {
            val text = StringBuilder()
            var i = start
            val close = if (raw) "\"\"\"" else "\""
            while (i < s.length && !s.startsWith(close, i)) {
                when {
                    !raw && s[i] == '\\' -> { text.append(s, i, minOf(i + 2, s.length)); i += 2 }
                    s.startsWith("\${", i) -> {
                        check(text)
                        text.clear()
                        i = code(i + 2, inTemplate = true)
                    }
                    else -> text.append(s[i++])
                }
            }
            check(text)
            return minOf(i + close.length, s.length)
        }

        private fun check(text: CharSequence) {
            val t = text.toString()
            if (t.isEmpty() || t in dataKeys) return
            val held = dataTexts.firstOrNull { it in t }
            if (forbidden.containsMatchIn(t) || held != null) out += "a literal of youtube.json's in the code: \"$t\" ($held)"
        }
    }
}
