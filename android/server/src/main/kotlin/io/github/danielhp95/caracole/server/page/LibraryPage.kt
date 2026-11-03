package io.github.danielhp95.caracole.server.page

import kotlinx.serialization.json.JsonObject

/** library_page.WebControls on the phone: what its server adds to the page. */
data class ServerControls(
    val csrf: String, val busy: Set<Long> = emptySet(), val active: Int = 0, val held: Set<Long> = emptySet(),
    val removing: Set<Long> = emptySet(), val jobs: List<JsonObject> = emptyList(),
    val timers: Map<String, Int>? = null, val badge: String? = "Phone", val sync: Boolean = false,
)

/** library_page.assemble_page's served branch (lane library-page). */
class LibraryPage(val assets: LibraryAssets) {
    fun served(data: JsonObject, controls: ServerControls, libraryName: String): String = TODO("lane library-page")
}
