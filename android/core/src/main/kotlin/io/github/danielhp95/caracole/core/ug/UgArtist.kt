package io.github.danielhp95.caracole.core.ug

/** ug/artist.py's UGArtistPage. */
data class UgArtistPage(val artistId: Long, val name: String, val tabs: List<UgVersion>, val page: Int, val pages: Int,
                        val filters: Set<String>)

/** ug/artist.py: UG's artist pages. */
object UgArtist {
    fun parse(html: ByteArray, url: String? = null): UgArtistPage = TODO("lane ug-pages")
    fun pageUrl(base: String, kind: String? = null, page: Int = 1): String = TODO("lane ug-pages")
}
