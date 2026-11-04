package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.web.Inline
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/**
 * caracole's library_assets/, as its library page inlines them: the files from the classpath copy
 * `caracole/library_assets/` (the build's copyLibraryAssets, byte for byte), in the order of
 * `caracole/page/library_assets.json`, which tests/test_conformance_library_page.py writes from library_page.py's
 * SCRIPTS, STYLESHEETS and TEMPLATES. Each file is its UTF-8 bytes decoded strictly, as `library_assets.read` decodes
 * them: no line's end turned into another, a file that isn't UTF-8 refused.
 *
 * [scripts] and [styles] are the page's one script and one stylesheet, the files concatenated in that order;
 * [scriptHash] and [styleHash], the sources its Content-Security-Policy allows them by (inline.py's sha256_source);
 * [template], a template of the page's skeleton by its name.
 */
class LibraryAssets private constructor(
    /** The scripts' names, in the page's order. */
    val scriptNames: List<String>,
    /** The stylesheets' names, in the page's order. */
    val styleNames: List<String>,
    private val templates: Map<String, String>,
    val scripts: String,
    val styles: String,
) {
    val scriptHash: String by lazy { Inline.sha256Source(scripts) }
    val styleHash: String by lazy { Inline.sha256Source(styles) }

    /** The templates' names, in library_page.py's order. */
    val templateNames: List<String> get() = templates.keys.toList()

    /** The template [name] ("body.html") as it is; IllegalArgumentException for a name the page has no template of. */
    fun template(name: String): String =
        templates[name] ?: throw IllegalArgumentException("library_assets.json names no template $name")

    companion object {
        /** Where the build puts library_assets/ on the classpath. */
        const val FOLDER = "caracole/library_assets/"

        /** The order the page inlines them in (caracole's runtime data, :core's resource root). */
        const val ORDER = "caracole/page/library_assets.json"

        /** The assets on the classpath; IllegalStateException when a file is missing or isn't UTF-8. */
        fun load(): LibraryAssets {
            val order = Json.parseToJsonElement(text(ORDER)).jsonObject
            fun names(list: String) = (order[list] as? JsonArray ?: throw IllegalStateException("$ORDER has no $list"))
                .map { it.jsonPrimitive.content }
            val scripts = names("SCRIPTS")
            val styles = names("STYLESHEETS")
            val templates = names("TEMPLATES").associateWith { text(FOLDER + it) }
            return LibraryAssets(
                scripts, styles, templates,
                scripts = scripts.joinToString("") { text(FOLDER + it) },
                styles = styles.joinToString("") { text(FOLDER + it) },
            )
        }

        private fun text(name: String): String {
            val stream = LibraryAssets::class.java.classLoader?.getResourceAsStream(name)
                ?: throw IllegalStateException("$name isn't on the classpath")
            val bytes = stream.use { it.readBytes() }
            return try {
                Charsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes)).toString()
            } catch (e: CharacterCodingException) {
                throw IllegalStateException("$name isn't UTF-8", e)
            }
        }
    }
}
