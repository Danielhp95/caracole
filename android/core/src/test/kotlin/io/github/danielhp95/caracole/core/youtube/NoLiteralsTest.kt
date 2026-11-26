package io.github.danielhp95.caracole.core.youtube

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * No yt-dlp flag, pattern or word of youtube.py is typed under core/youtube/: each is youtube.json's (the plan's "One
 * source for the rules"). Every file of the package is read, HostGate.kt among them (its host list is Kotlin data
 * for now, a list of names, which no rule here forbids); its string literals, comments aside, may hold none of:
 *
 * - `--` or `-x` at the start: a flag;
 * - yt-dlp's line prefixes, `ERROR:`, `WARNING:` and `[debug]`, or a target's, `ytsearch` and `watch?v=`;
 *
 * and no literal is compiled as a pattern (`Regex(`, `PyRegex.compile(`, `Pattern.compile(` or `.toRegex()` of one).
 */
class NoLiteralsTest {
    private val root = File("src/main/kotlin/io/github/danielhp95/caracole/core/youtube")

    @Test fun noFlagPatternOrPrefixIsTypedInThePackage() {
        val files = root.listFiles { f -> f.name.endsWith(".kt") }.orEmpty().sortedBy { it.name }
        assertTrue(files.map { it.name }.containsAll(listOf("Choose.kt", "Classify.kt", "HostGate.kt", "Videos.kt",
            "YouTubeData.kt")), "the package's files: ${files.map { it.name }}")
        val found = files.flatMap { f -> scan(f.readText()).map { "${f.name}: $it" } }
        assertEquals(emptyList(), found)
    }

    @Test fun theScanFindsWhatItForbids() {
        assertEquals(4, scan("val a = \"--proxy\"; val b = \"-o\"; val c = \"x ERROR: y\"; val d = Regex(\"a+\")").size)
        assertEquals(2, scan("val p = \"\"\"[debug]\"\"\".toRegex()").size + scan("// \"--proxy\" in a comment").size)
        assertEquals(emptyList(), scan("/* \"--x\" */ val s = \"a-b\" // ERROR: said"))
    }

    private val forbidden = Regex("^-(?:-|[A-Za-z]\\b)|ERROR:|WARNING:|\\[debug]|ytsearch|watch\\?v=")
    private val compiles = Regex("(?:\\bRegex|PyRegex\\s*\\.\\s*compile|Pattern\\s*\\.\\s*compile)\\s*\\(\\s*\"|\"\\s*\\.\\s*toRegex\\(")

    /** What [source] holds that it mustn't: each string literal's, and each literal compiled as a pattern. */
    private fun scan(source: String): List<String> {
        val out = ArrayList<String>()
        val code = StringBuilder()
        var i = 0
        while (i < source.length) {
            when {
                source.startsWith("//", i) -> i = source.indexOf('\n', i).let { if (it < 0) source.length else it }
                source.startsWith("/*", i) -> i = source.indexOf("*/", i + 2).let { if (it < 0) source.length else it + 2 }
                source.startsWith("\"\"\"", i) -> {
                    val end = source.indexOf("\"\"\"", i + 3).let { if (it < 0) source.length else it }
                    literal(source.substring(i + 3, end), out)
                    code.append("\"\"")
                    i = end + 3
                }
                source[i] == '"' -> {
                    var j = i + 1
                    while (j < source.length && source[j] != '"') j += if (source[j] == '\\') 2 else 1
                    literal(source.substring(i + 1, minOf(j, source.length)), out)
                    code.append("\"\"")
                    i = j + 1
                }
                source[i] == '\'' && i + 2 < source.length -> {
                    val j = source.indexOf('\'', i + 1 + if (source[i + 1] == '\\') 2 else 1)
                    code.append("''")
                    i = if (j < 0) source.length else j + 1
                }
                else -> code.append(source[i++])
            }
        }
        out += compiles.findAll(code).map { "a literal compiled as a pattern: ${it.value}" }
        return out
    }

    private fun literal(text: String, out: MutableList<String>) {
        if (forbidden.containsMatchIn(text)) out += "a literal of youtube.json's in the code: \"$text\""
    }
}
