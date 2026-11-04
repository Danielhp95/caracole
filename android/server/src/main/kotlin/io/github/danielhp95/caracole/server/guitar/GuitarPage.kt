package io.github.danielhp95.caracole.server.guitar

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.server.http.LibraryName

/** alphatab.AlphaTab: the bundle as the page loads it, its file name under `/assets/alphatab/`, its bytes, its SRI
 * string, the CSP source that allows it and the one that allows the stylesheet alphaTab adds. */
class AlphaTab(val name: String, val body: ByteArray, val integrity: String, val scriptSource: String,
               val fontFace: String)

/** inbox.GuitarFile: a Guitar Pro or Power Tab file caracole keeps for a song, `guitar-N.<ext>`, its path in the
 * library. */
data class GuitarFile(val songId: Long, val name: String, val path: String, val number: Int)

/** web/guitar_page.py, and inbox.guitar_files: a song's kept Guitar Pro file drawn by alphaTab (lane
 * guitar-alphatab). */
object GuitarPage {
    fun style(): String = TODO("lane guitar-alphatab")
    fun script(): String = TODO("lane guitar-alphatab")
    fun policy(at: AlphaTab): String = TODO("lane guitar-alphatab")
    fun build(title: String, artist: String, songId: Long, path: String, label: String, data: ByteArray, at: AlphaTab,
              sheet: String? = null, libraryName: LibraryName? = null): String = TODO("lane guitar-alphatab")
    /** inbox.guitar_files: of the song [songId] or every song's, or the one at [path]; by song, then N. */
    fun guitarFiles(db: Db, songId: Long? = null, path: String? = null): List<GuitarFile> = TODO("lane guitar-alphatab")
}
