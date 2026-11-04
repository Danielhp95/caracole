package io.github.danielhp95.caracole.viewer

import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.util.concurrent.ConcurrentHashMap

/**
 * viewer/'s stylesheets and scripts as page.py inlines them: each file's text as `Path.read_text(encoding="utf-8")`
 * reads it (strict UTF-8, a CR or CRLF read as LF: universal newlines, though no asset holds a CR, which
 * ViewerAssetsTest holds), from caracole/viewer/ on the classpath ([Viewer.asset]), and the files each kind of page
 * inlines, in their order ([Page]).
 */
object ViewerAssets {
    /**
     * A kind of page and what it inlines in its head and at its end, in order: page.py's `build_viewer` (a sheet and a
     * kept version's page), book.py's `build_songbook`, harptab_page.py's `build_harmonica_viewer`. Python passes the
     * files' texts to `_page` by hand; vectors/viewer/theory_assets.jsonl holds what a page Python built inlines, and
     * the theory replay compares.
     */
    enum class Page(val styles: List<String>, val scripts: List<String>) {
        SHEET(listOf("viewer.css"), listOf("strum.js", "overlay.js", "instruments.js", "winds.js", "viewer.js")),
        SONGBOOK(
            listOf("viewer.css", "book.css"),
            listOf("book.js", "strum.js", "overlay.js", "instruments.js", "winds.js", "viewer.js"),
        ),
        HARMONICA(listOf("viewer.css", "harptab.css"), listOf("strum.js", "overlay.js", "harptab.js")),
    }

    private val texts = ConcurrentHashMap<String, String>()

    /**
     * The text of viewer/'s file [name] ("viewer.js"), read once. A name that is no asset of viewer/ (what
     * viewer/build.gradle.kts's copyViewerAssets copies: `*.js`, `*.css`, `voicings*.json`, `LICENSE-chords-db`)
     * is an [IllegalArgumentException]; one missing from the classpath, or not UTF-8, an [IllegalStateException].
     */
    fun text(name: String): String {
        require(isAsset(name)) { "$name is no asset of viewer/" }
        return texts.getOrPut(name) {
            val bytes = Viewer.asset(name) ?: throw IllegalStateException("caracole/viewer/$name is not on the classpath")
            universalNewlines(strictUtf8(bytes, "caracole/viewer/$name"))
        }
    }

    /** The texts of the stylesheets [page] inlines, in order. */
    fun styles(page: Page): List<String> = page.styles.map(::text)

    /** The texts of the scripts [page] inlines, in order. */
    fun scripts(page: Page): List<String> = page.scripts.map(::text)

    /** Whether [name] is one of the files copyViewerAssets puts on the classpath: a name with no folder. */
    fun isAsset(name: String): Boolean =
        '/' !in name && '\\' !in name && name.isNotEmpty() && !name.startsWith(".") &&
            (name.endsWith(".js") || name.endsWith(".css") ||
                (name.startsWith("voicings") && name.endsWith(".json")) || name == "LICENSE-chords-db")

    /** [bytes] as UTF-8, refusing what isn't (Python's "strict"), a byte order mark kept as U+FEFF as Python keeps it. */
    internal fun strictUtf8(bytes: ByteArray, name: String): String = try {
        Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes)).toString()
    } catch (e: CharacterCodingException) {
        throw IllegalStateException("$name is not UTF-8", e)
    }

    /** Python's universal newlines: "\r\n" and a lone "\r" read as "\n". */
    internal fun universalNewlines(text: String): String =
        if ('\r' !in text) text else text.replace("\r\n", "\n").replace('\r', '\n')
}
