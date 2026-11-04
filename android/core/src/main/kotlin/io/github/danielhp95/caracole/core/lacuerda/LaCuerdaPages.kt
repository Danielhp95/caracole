package io.github.danielhp95.caracole.core.lacuerda

/** lacuerda.py's pages read: an artist's page, a song's versions, a sheet (lane lacuerda-pages). */
object LaCuerdaPages {
    fun parseArtist(html: ByteArray, url: String? = null): List<LaCuerdaSong> = TODO("lane lacuerda-pages")
    fun parseSearch(html: ByteArray, url: String? = null): LaCuerdaSearchAnswer = TODO("lane lacuerda-pages")
}
