package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db

/** inbox.HarmonicaFile: a harmonica tab caracole keeps for a song (`harmonica-N.txt`, harptabs_fetch.py): its name,
 * where it is (relative to the library), its N, the key its page's Key chip names and the harp its harp chip names
 * ("Diatonic", "Chromatic"), each null where it names none. */
data class HarmonicaFile(val songId: Long, val name: String, val path: String, val number: Int,
                         val key: String? = null, val harp: String? = null) {
    /** Its page, written beside it at render time: "harmonica-1.html" (inbox.HarmonicaFile.page). */
    val page: String get() = HarmonicaFiles.page(name) ?: ""
}

/**
 * inbox.harmonica_files and harmonica_page, :core's, so every reader shares one port: the phone's render (a viewer's
 * `harmonicaTabs` and the tabs' pages: phone-render, whose port this file is), the library's cards (library-cards) and
 * a harmonica tab's readings (versions-harmonica).
 */
object HarmonicaFiles {
    /** inbox.HARMONICA_KIND: a kept tab's version's kind. */
    const val KIND = "harmonica"

    /** inbox.harmonica_files: the harmonica tabs caracole keeps, of the song [songId] or every song's; by song, then
     * N. */
    fun of(db: Db, songId: Long? = null): List<HarmonicaFile> = TODO("lane phone-render")

    /** inbox.harmonica_page: the page of the harmonica tab [name] ("harmonica-1.txt" → "harmonica-1.html"), or null
     * for a name that is no kept tab's. */
    fun page(name: String): String? = TODO("lane phone-render")
}
