package io.github.danielhp95.caracole.viewer.pages

/** book.BookSong: one song of a songbook as its page draws it, its sheet or why it has none. */
data class BookSong(val title: String, val artist: String, val cho: String? = null, val key: String? = null,
                    val keySource: String? = null, val transpose: Int = 0, val missing: String? = null,
                    val id: String = "", val start: String? = null)

/** viewer/book.py: a songbook's page over the pages' frame (lane songbook-entries: book.py imports version.py, which
 * page.py doesn't). */
object SongbookPage {
    fun build(name: String, songs: List<BookSong>, pdf: String? = null, cho: String? = null,
              pdfTraditional: String? = null): String = TODO("lane songbook-entries")
}
