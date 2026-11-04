package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.ug.Candidate
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgPage
import io.github.danielhp95.caracole.core.ug.UgTabPage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * ug/fetch.py's versions kept beside the sheet (sheet_versions.py): each as `version-<tab>.txt` and `.json` with its
 * rank, one text under one name (`library.keep_file`), the versions whose text is a kept one's listed with that one's
 * page (kv `sheet_versions:same:<song id>`), and those you kept (`sheet_versions.kept_by_you`) kept whatever the
 * ranking, from the pages in hand or the cache alone.
 */
internal object Beside {
    private fun stripped(page: UgTabPage): ByteArray = UgPage.stripMarkup(page.content ?: "").toByteArray(Charsets.UTF_8)

    /** `_holder`: the name of the song's kept file that holds [data] already under another name than [name]. */
    private fun holder(run: SongRun, name: String, data: ByteArray): String? {
        val sha = Slots.sha256(data)
        return Kept.keptFiles(run.db, run.song.id).firstOrNull { it.sha256 == sha && it.name != name }?.name
    }

    /** `_same_text`: the viewer page of a song's kept text that holds [data] already under another name than [name]:
     * the sheet's or a kept version's; null for none, and for any other file's (the tab's). */
    fun sameText(run: SongRun, name: String, data: ByteArray): String? {
        val held = holder(run, name, data)
        if (held == UgFetch.SHEET_FILES[0]) return Ports.SHEET_PAGE
        val tab = held?.let(Ports::tabOf)
        if (tab != null && held == SheetVersions.versionNames(tab).first) return SheetVersions.versionNames(tab).third
        return null
    }

    /** `_keep_version`: a version kept beside the sheet with `kept_rank` [rank]; false when its text is a kept file's
     * already (two UG tabs, one text; or the tab's), and nothing is written. */
    fun keepVersion(run: SongRun, versionId: Long, page: UgTabPage, rank: Int = 2): Boolean {
        val tab = Versions.get(run.db, versionId)!!.tabId
        val (txt, doc, _) = SheetVersions.versionNames(tab)
        if (holder(run, txt, stripped(page)) != null) return false
        Slots.keepText(run, versionId, page, txt to doc, rank)
        return true
    }

    private fun dropVersion(run: SongRun, tab: String) {
        val (txt, doc, _) = SheetVersions.versionNames(tab)
        for (name in listOf(txt, doc)) Kept.dropFile(run.db, run.ctx.library, run.song, name)
    }

    /** `_make_way`: a version that becomes the sheet leaves its version files, and so does any version holding its
     * text: one text has one name in the library, and it is the sheet's. */
    fun makeWay(run: SongRun, tab: String, page: UgTabPage) {
        val sha = Slots.sha256(stripped(page))
        dropVersion(run, tab)
        for (f in Kept.keptFiles(run.db, run.song.id)) {
            val other = Ports.tabOf(f.name)
            if (f.sha256 == sha && other != null) dropVersion(run, other)
        }
    }

    private fun keptVersionTabs(run: SongRun): Set<String> =
        Kept.keptFiles(run.db, run.song.id).mapNotNull { Ports.tabOf(it.name) }.toCollection(LinkedHashSet())

    /**
     * `_keep_beside`: [beside] (rank order) kept as the song's versions, but for the [chosen] one (`sheet.txt`), and
     * every other version's files dropped: they left the kept set, were blocked, or were found under an earlier match.
     * A version whose page couldn't be read this run keeps its files (an error is never a miss), as do those in
     * [hold] (yours, with no page in hand). A version whose text is a kept one's is listed with that one's page
     * instead. Those leaving go first, so a version that shared its text with one of them keeps the text itself.
     */
    fun keepBeside(run: SongRun, chosen: Long?, beside: List<Scored>, hold: Set<String> = emptySet()) {
        val staying = beside.filter { (c, _) -> c.versionId != chosen }.map { it.first.tabId }.toSet()
        val waiting = run.unreadable.map { it.toString() }.toSet() + hold
        for (tab in keptVersionTabs(run) - staying - waiting) dropVersion(run, tab)
        val kept = ArrayList<String>()
        val same = LinkedHashMap<String, String>()
        for ((c, page) in beside) {
            if (c.versionId == chosen) continue
            if (keepVersion(run, c.versionId!!, page, rank = kept.size + 2)) {
                kept += c.tabId
            } else {
                dropVersion(run, c.tabId)
                val shown = sameText(run, SheetVersions.versionNames(c.tabId).first, stripped(page))
                if (shown != null) same[c.tabId] = shown
            }
        }
        val key = Ports.sameKey(run.song.id)
        if (same.isNotEmpty()) {
            run.db.kvSetJson(key, JsonObject(same.mapValues { JsonPrimitive(it.value) }))
        } else {
            run.db.kvDelete(key)
        }
        run.keptVersions = kept
    }

    /** `_cached_text_page`: a version's page with its text, from this run's pages or the HTTP cache alone: nothing is
     * sent. Null when neither has it, or it doesn't parse. */
    fun cachedTextPage(run: SongRun, row: VersionRow): UgTabPage? {
        val tabId = row.tabId.toLong()
        val page = if (tabId in run.pages) {
            run.pages[tabId]
        } else {
            val resp = run.ctx.client.cached(row.url) ?: return null
            try {
                UgPage.parseTabPage(resp.content, row.url)
            } catch (e: PageParseError) {
                return null
            }
        }
        return page?.takeIf { it.content != null }
    }

    /** `_beside_a_pin`: the versions a pinned sheet keeps beside it: the top `scored_sheets` by rating, read from the
     * cache alone (no request is spent on them), scored, in rank order. */
    fun besideAPin(run: SongRun, rows: List<VersionRow>, lyrics: String): List<Scored> {
        val policy = run.ctx.rank
        val found = LinkedHashMap<Long, UgTabPage>()
        val top = Slots.head(Rank.rankByRating(rows.map(Slots::candidate), policy, run.song.variant),
                             policy.scoredSheets)
        val byId = rows.associateBy { it.id }
        val scored = ArrayList<Candidate>()
        for (c in top) {
            val page = cachedTextPage(run, byId.getValue(c.versionId!!)) ?: continue
            val cov = Slots.coverage(run, page.content!!, lyrics)
            Versions.setCoverage(run.db, c.versionId, cov)
            found[c.versionId] = page
            scored += c.copy(coverage = cov)
        }
        return Rank.rankSheets(scored, policy, run.song.variant).map { it to found.getValue(it.versionId!!) }
    }

    /** `_yours`: the versions you kept that [beside] hasn't, from the pages in hand or the cache alone, scored; and
     * those with no page there, whose files stay as they are. One UG no longer has, or that you block, isn't among
     * [rows], and leaves. */
    fun yours(run: SongRun, rows: List<VersionRow>, lyrics: String, beside: List<Scored>): Pair<List<Scored>, Set<String>> {
        val have = beside.map { it.first.versionId }.toSet()
        val byTab = rows.associateBy { it.tabId }
        val found = ArrayList<Scored>()
        val hold = LinkedHashSet<String>()
        for (tab in SheetVersions.keptByYou(run.db, run.song.id)) {
            val row = byTab[tab]
            if (row == null || row.id in have) continue
            val page = cachedTextPage(run, row)
            if (page == null) {
                hold += tab
                continue
            }
            val cov = Slots.coverage(run, page.content!!, lyrics)
            Versions.setCoverage(run.db, row.id, cov)
            found += Slots.candidate(row).copy(coverage = cov) to page
        }
        return found to hold
    }
}
