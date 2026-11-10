package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.GuitarFile
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.sites.MuseScorePage
import io.github.danielhp95.caracole.core.sites.MuseScorePages
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.IOException
import java.math.BigInteger

/**
 * What the cards read of other lanes' ports, in one place: inbox.guitar_files (GuitarFiles.of, lane guitar-alphatab),
 * inbox.harmonica_page (HarmonicaFiles.page, lane phone-render), musescore.song_pages (MuseScorePages.songPages, lane
 * tab-files) and the phone's render record of each song (kv `render:<id>:phone`, its sheet's `script` and the `unit`
 * digest it was made at: WrittenPages.rendered, lane phone-render).
 *
 * Phase A: waiting on lanes guitar-alphatab, phone-render and tab-files. Until each lands, its declaration is the
 * skeleton's TODO and the cards read the same rows as Python does here ([guitarFiles], [harmonicaPage],
 * [museScorePages], [rendered]); Phase B calls the producers alone and drops these readings.
 */
internal object Producers {
    /** inbox.guitar_files of every song. */
    fun guitarFiles(db: Db): List<GuitarFile> = try {
        GuitarFiles.of(db)
    } catch (_: NotImplementedError) {
        guitarFilesHere(db) // Phase A: waiting on lane guitar-alphatab
    }

    /** inbox.harmonica_page: "harmonica-1.txt" → "harmonica-1.html"; null for a name that is no kept tab's. */
    fun harmonicaPage(name: String): String? = try {
        HarmonicaFiles.page(name)
    } catch (_: NotImplementedError) {
        PyRe.fullmatch(HARMONICA, name)?.let { "harmonica-${it.groupValues[1]}.html" } // Phase A: lane phone-render
    }

    /** musescore.song_pages: the index's pages with the song's title, oldest first, three at most. */
    fun museScorePages(db: Db, song: SongRow): List<MuseScorePage> = try {
        MuseScorePages.songPages(db, song)
    } catch (_: NotImplementedError) {
        museScoreHere(db, song) // Phase A: waiting on lane tab-files
    }

    /** The phone's record of a song it rendered (kv `render:<id>:phone`): the unit digest its pages were made at, and
     * its sheet's script; null for a song never rendered, or a record that can't be read. */
    fun rendered(db: Db, songId: Long): Pair<String, String?>? {
        val text = db.kvGet("render:$songId:phone") ?: return null // Phase A: WrittenPages.rendered, lane phone-render
        val record = try {
            PyJson.loads(text)
        } catch (_: IllegalArgumentException) {
            return null
        } catch (_: IOException) {
            return null
        } as? JsonObject ?: return null
        fun text(name: String) = (record[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val unit = text("unit") ?: return null
        text("build") ?: return null
        return unit to text("script")
    }

    // --- Phase A's readings, Python's own ------------------------------------------------------------------------

    private val KEPT_GUITAR: Regex = PyRegex.compile("""guitar-(\d+)(\.[A-Za-z0-9]+)""")
    private val HARMONICA: Regex = PyRegex.compile("""harmonica-(\d+)\.txt""")
    private val GP_EXTENSIONS = setOf(".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb")

    private fun guitarFilesHere(db: Db): List<GuitarFile> {
        val found = db.query(
            "SELECT f.song_id, f.name, f.path FROM files f JOIN versions v ON v.id = f.version_id " +
                "WHERE v.kind IN (${GuitarFiles.KINDS.joinToString(", ") { "?" }})",
            *GuitarFiles.KINDS.toTypedArray(),
        ) { row ->
            val name = row.text(1)!!
            val m = PyRe.fullmatch(KEPT_GUITAR, name) ?: return@query null
            if (PyText.lower(m.groupValues[2]) !in GP_EXTENSIONS) return@query null
            val n = PyInt.parse(m.groupValues[1]) ?: return@query null
            n to GuitarFile(row.long(0)!!, name, row.text(2)!!, if (n.bitLength() < 32) n.toInt() else Int.MAX_VALUE)
        }.filterNotNull()
        return found.sortedWith(compareBy<Pair<BigInteger, GuitarFile>> { it.second.songId }.thenBy { it.first }
                                    .thenComparator { a, b -> Py.CODE_POINT_ORDER.compare(a.second.name, b.second.name) })
            .map { it.second }
    }

    private fun museScoreHere(db: Db, song: SongRow): List<MuseScorePage> {
        val key = Normalize.slugKey(Normalize.cleanTitle(song.title))
        if (key.isEmpty()) return emptyList()
        return db.query("SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? ORDER BY page_id LIMIT ?",
                        key, 3) { MuseScorePage(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
    }
}
