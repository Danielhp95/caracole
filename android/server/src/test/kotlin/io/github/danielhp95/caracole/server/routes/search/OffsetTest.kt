package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.server.testing.SearchApp
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/** search_routes.api_artist: an offset of more digits than SQLite takes (nine at most) is no number, as on the
 * computer, where one past Python's 4,300 digits was a bug. */
class OffsetTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun an_offset_of_more_digits_than_sqlite_takes_isnt_a_number() {
        SearchApp(tmp.newFolder("search"), "lacuerda").use { search ->
            for (offset in listOf("9999999999", "9".repeat(5000))) {
                assertEquals(400, search.app.get("/api/artist?key=estopa&offset=$offset").status, offset.take(12))
            }
        }
    }
}
