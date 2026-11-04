package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyText

/** inbox.GuitarFile: a Guitar Pro or Power Tab file caracole keeps for a song (`guitar-N.<ext>`, recorded in `files`),
 * filed from the inbox or downloaded from gtptabs.com; [path] where it is, relative to the library. */
data class GuitarFile(val songId: Long, val name: String, val path: String, val number: Int) {
    /** inbox.GuitarFile.in_browser: whether the Guitar Pro page shows it ([GuitarFiles.BROWSER_EXTENSIONS]): not a
     * Power Tab file. */
    val inBrowser: Boolean get() = PyText.lower(PyPath.suffix(name)) in GuitarFiles.BROWSER_EXTENSIONS
}

/**
 * inbox.guitar_files, :core's, so every reader shares one port: the Guitar Pro page (guitar-alphatab, whose port this
 * file is), a viewer's `guitar` (phone-render), the library's cards (library-cards) and a set list's `guitar` mark
 * (songbook-entries).
 */
object GuitarFiles {
    /** inbox.GUITAR_FILE_KINDS: the kinds of version a kept Guitar Pro or Power Tab file is recorded under. */
    val KINDS: List<String> = listOf("guitar-pro", "power")

    /** inbox.BROWSER_EXTENSIONS: the files the Guitar Pro page draws. */
    val BROWSER_EXTENSIONS: Set<String> = setOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp")

    /** inbox.guitar_files: the files caracole keeps, `guitar-N.<ext>` recorded for a version of either kind, of the
     * song [songId] or every song's, or the one at [path]; by song, then N. */
    fun of(db: Db, songId: Long? = null, path: String? = null): List<GuitarFile> = TODO("lane guitar-alphatab")
}
