package io.github.danielhp95.caracole.viewer.pages.internal

import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerAssets
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * viewer/page.py's HTML and constants, as tests/test_conformance_viewer_pages.py wrote them from the module into
 * caracole/viewer/page.json (that file's docstring is the format's), never retyped; and the page's icon, page_icon.py's
 * `LINK`, from caracole/page/icon.json (M2's). Each read once.
 */
internal object PageConstants {
    private val data: JsonObject by lazy { ViewerData.table("page") }
    private fun text(name: String): String = data.getValue(name).jsonPrimitive.content

    /** page.LIBRARY_PAGE: the library's index.html, two folders up, relative to a song's page. */
    val LIBRARY_PAGE: String by lazy { text("LIBRARY_PAGE") }
    val CREDIT_URL: String by lazy { text("CREDIT_URL") }
    val NOTICE: String by lazy { text("_NOTICE") }
    val CREDIT: String by lazy { text("_CREDIT") }
    val VERSIONS: String by lazy { text("_VERSIONS") }
    val VERSION_LIST: String by lazy { text("_VERSION_LIST") }
    val HARMONY_ROW: String by lazy { text("_HARMONY_ROW") }
    val GUITAR_ROW: String by lazy { text("_GUITAR_ROW") }
    val EXPORT_ROW: String by lazy { text("_EXPORT_ROW") }
    val EXPORT_ASK: String by lazy { text("_EXPORT_ASK") }
    val CONTROLS: String by lazy { text("_CONTROLS") }
    val SHEET_CONTROLS: String by lazy { text("_SHEET_CONTROLS") }
    val NOTHING: String by lazy { text("_NOTHING") }

    /** page._credit_notice(): chords-db's copyright and permission notice, as the footer prints it. */
    val CREDIT_NOTICE: String by lazy { text("credit_notice") }

    /** page._META_POLICY, a bytes pattern Python runs over the page's bytes: compiled over a text whose characters
     * are those bytes (Latin-1, one character a byte). */
    val META_POLICY: Regex by lazy { pattern("_META_POLICY") }
    val HEADER_TEXT: Regex by lazy { pattern("_HEADER_TEXT") }

    private fun pattern(name: String): Regex =
        PyRegex.compile(data.getValue("patterns").jsonObject.getValue(name).jsonPrimitive.content)

    /** page_icon.LINK: the page's icon, a data: URI, for its head. */
    val ICON: String by lazy {
        val path = "caracole/page/icon.json"
        val stream = PageConstants::class.java.classLoader?.getResourceAsStream(path)
            ?: PageConstants::class.java.getResourceAsStream("/$path")
            ?: throw IllegalStateException("$path is not on the classpath")
        val icons = Json.parseToJsonElement(ViewerAssets.strictUtf8(stream.use { it.readBytes() }, path)).jsonObject
        icons.getValue("link").jsonPrimitive.content
    }
}
