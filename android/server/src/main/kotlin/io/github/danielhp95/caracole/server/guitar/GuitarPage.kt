package io.github.danielhp95.caracole.server.guitar

import io.github.danielhp95.caracole.server.http.LibraryName

/** alphatab.AlphaTab: the bundle as the page loads it, its file name under `/assets/alphatab/`, its bytes, its SRI
 * string, the CSP source that allows it and the one that allows the stylesheet alphaTab adds. */
class AlphaTab(val name: String, val body: ByteArray, val integrity: String, val scriptSource: String,
               val fontFace: String)

/** web/guitar_page.py: a song's kept Guitar Pro file drawn by alphaTab (lane guitar-alphatab). The files a song
 * keeps are :core's GuitarFiles.of (inbox.guitar_files, this lane's port too), which the render and the cards read. */
object GuitarPage {
    fun style(): String = TODO("lane guitar-alphatab")
    fun script(): String = TODO("lane guitar-alphatab")
    fun policy(at: AlphaTab): String = TODO("lane guitar-alphatab")
    fun build(title: String, artist: String, songId: Long, path: String, label: String, data: ByteArray, at: AlphaTab,
              sheet: String? = null, libraryName: LibraryName? = null): String = TODO("lane guitar-alphatab")
}
