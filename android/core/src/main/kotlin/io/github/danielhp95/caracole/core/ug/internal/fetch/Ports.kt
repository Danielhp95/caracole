package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.ug.Candidate
import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.UgPage
import io.github.danielhp95.caracole.core.ug.UgVersion
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What the fetch reads of the lanes it builds on (ug-pages' UgPage, UgArtist and UgLookup, rank-coverage's Rank and
 * SheetVersions, overrides-model's picks), named once, as ug/fetch.py imports it.
 *
 * Phase A: the skeleton declares none of these, so each is read here as Python writes it, a stand-in until its lane
 * merges (waiting on ug-pages: TAB_BASE_URL, WWW, UGVersion's kind and label, IndexTab's url and label; on
 * rank-coverage: rank_guitar and sheet_versions' PREFIX, SHEET_PAGE, tab_of, same_key, library_state and same_pages;
 * on overrides-model: LaCuerdaPick.holds). Phase B makes each the lane's own.
 */
internal object Ports {
    /** ug/page.py's TAB_BASE_URL (waiting on ug-pages). */
    const val TAB_BASE_URL = "https://tabs.ultimate-guitar.com/tab/"

    /** ug/artist.py's WWW: UG's site, where its artist pages are (waiting on ug-pages). */
    const val WWW = "https://www.ultimate-guitar.com"

    /** UGVersion.kind: chords, tabs or ukulele; null for every type caracole doesn't use (waiting on ug-pages). */
    fun kind(v: UgVersion): String? = UgPage.kindOf(v.type)

    /** UGVersion.label: its part, else "acoustic" for an acoustic recording, else null (waiting on ug-pages). */
    fun label(v: UgVersion): String? {
        val part = PyUnicode.lower(Py.strip(v.part))
        if (part.isNotEmpty()) return part
        return if (v.isAcoustic) "acoustic" else null
    }

    /** IndexTab.url: a slugged tab's page at its slugged path alone (waiting on ug-pages). */
    fun url(t: IndexTab): String = UgPage.pageUrl(t.tabId, t.path?.ifEmpty { null })

    /** IndexTab.label: a variant slug's label (waiting on ug-pages). */
    fun label(t: IndexTab): String? = Normalize.splitVariant(t.songKey).second

    /** rank.rank_guitar: rank_by_rating (waiting on rank-coverage). */
    fun rankGuitar(cands: List<Candidate>, policy: RankPolicy, variant: String?): List<Candidate> =
        Rank.rankByRating(cands, policy, variant)

    /** sheet_versions.PREFIX and SHEET_PAGE (waiting on rank-coverage). */
    const val VERSION_PREFIX = "version-"
    const val SHEET_PAGE = "sheet.html"
    private val NAME = PyRegex.compile("""version-([0-9]+)\.(?:txt|json|html)""")

    /** sheet_versions.tab_of: the tab id of a version file's name, else null (waiting on rank-coverage). */
    fun tabOf(name: String): String? = PyRe.fullmatch(NAME, name)?.groupValues?.get(1)

    /** sheet_versions.same_key (waiting on rank-coverage). */
    fun sameKey(songId: Long): String = "sheet_versions:same:$songId"

    /** sheet_versions.library_state: the UG tab kept as `sheet.txt` (null when the sheet is another site's or none),
     * and the tabs kept beside it by their `kept_rank` (waiting on rank-coverage). */
    fun libraryState(db: Db, songId: Long): Pair<String?, List<String>> {
        var chosen: String? = null
        val kept = ArrayList<Pair<Int, String>>()
        db.query("SELECT f.name, f.kept_rank, v.provider, v.kind, v.tab_id FROM files f JOIN versions v ON " +
                     "v.id = f.version_id WHERE f.song_id = ? AND (f.name = ? OR substr(f.name, 1, ?) = ?)",
                 songId, "sheet.txt", VERSION_PREFIX.length, VERSION_PREFIX) { r ->
            val name = r.text(0)!!
            if (name == "sheet.txt") {
                if (r.text(2) == "ug" && r.text(3) in listOf("chords", "ukulele")) chosen = r.text(4)
            } else {
                val tab = tabOf(name)
                if (tab != null && name == SheetVersions.versionNames(tab).first) kept += r.long(1)!!.toInt() to tab
            }
        }
        return chosen to kept.sortedWith(compareBy({ it.first }, { it.second.length }, { it.second })).map { it.second }
    }

    /** sheet_versions.same_pages: the song's versions whose text is a kept one's, by tab, with the page that shows it;
     * a page no longer kept is left out (waiting on rank-coverage). */
    fun samePages(db: Db, songId: Long): Map<String, String> {
        val record = db.kvGetJson(sameKey(songId)) as? JsonObject ?: return emptyMap()
        val (chosen, kept) = libraryState(db, songId)
        val pages = kept.map { SheetVersions.versionNames(it).third }.toMutableSet()
        if (chosen != null) pages += SHEET_PAGE
        val out = LinkedHashMap<String, String>()
        for ((tab, page) in record) {
            val p = (page as? JsonPrimitive)?.takeIf { it.isString }?.content ?: continue
            if (p in pages) out[tab] = p
        }
        return out
    }

    /** overrides.LaCuerdaPick.holds: whether a LaCuerda version, by its tab id (`artist/song-N`), is the one picked:
     * that version, or for a song, any of its versions (waiting on overrides-model). */
    fun holds(pick: LaCuerdaPick, tabId: String): Boolean {
        val artist = tabId.substringBefore('/')
        val rest = tabId.substringAfter('/', "")
        val dash = rest.lastIndexOf('-')
        if (dash < 0) return false
        return artist == pick.artist && rest.substring(0, dash) == pick.song &&
            (pick.version == null || rest.substring(dash + 1) == pick.version.toString())
    }
}
