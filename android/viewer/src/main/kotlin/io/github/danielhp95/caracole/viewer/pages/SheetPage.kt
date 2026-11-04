package io.github.danielhp95.caracole.viewer.pages

import kotlinx.serialization.json.JsonObject

/** page.build_viewer's arguments, in its order. */
data class ViewerInputs(val cho: String, val key: String? = null, val keySource: String? = null, val transpose: Int = 0,
                        val start: String? = null, val pdf: String? = null, val export: Boolean = true,
                        val versions: JsonObject? = null, val guitar: List<String> = emptyList(),
                        val harmonica: List<JsonObject> = emptyList(), val pdfTraditional: String? = null,
                        val video: JsonObject? = null)

/** viewer/page.py's builder: a sheet's page, byte for byte, and the page frame book.py reuses (lane pages). */
object SheetPage {
    fun build(i: ViewerInputs): String = TODO("lane pages")
    fun viewerCsp(page: ByteArray): String = TODO("lane pages")
}
