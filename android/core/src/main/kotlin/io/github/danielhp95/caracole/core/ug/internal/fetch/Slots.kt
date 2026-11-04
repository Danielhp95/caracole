package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.songLyrics
import io.github.danielhp95.caracole.core.ug.Candidate
import io.github.danielhp95.caracole.core.ug.Coverage
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgLookup
import io.github.danielhp95.caracole.core.ug.UgPage
import io.github.danielhp95.caracole.core.ug.UgTabPage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** A candidate scored, with the page it was scored from. */
internal typealias Scored = Pair<Candidate, UgTabPage>

/**
 * ug/fetch.py's ratings, pins and slots: each kind group rated from the page of its lowest unrated id, the pins read,
 * then the sheet slot (the top sheets scored for lyric coverage, the best kept as `sheet.txt` and `sheet.json`, the
 * others scored kept beside it as `version-<tab>.txt` and `.json`, no request more) and the tab slot (the best text tab
 * as `tab.txt` and `tab.json`).
 */
internal object Slots {
    // --- ratings and pins ------------------------------------------------------------------------------------

    /** `_seen_ids`: the tabs rated (or found gone) under the song's current match; a stale one is read again. */
    private fun seenIds(run: SongRun): Set<Long> =
        Versions.songVersions(run.db, run.song.id, includeGone = true)
            .filter { it.provider == UgFetch.PROVIDER && !it.stale }.map { it.tabId.toLong() }.toSet()

    /**
     * `_rate_group`: the page of the lowest unrated id read until all are rated, or until [pages] pages of this type
     * were fetched from UG this run (earlier steps' fetches count, cached pages don't). Tabs whose slug names no part
     * go first: a page lists its own (type, part) group.
     */
    fun rateGroup(run: SongRun, tabs: List<IndexTab>, pages: Int) {
        val tried = HashSet<Long>()
        val kinds = tabs.map { it.type }.toSet()
        while (kinds.sumOf { run.fetched[it] ?: 0 } < pages) {
            val seen = seenIds(run)
            val todo = tabs.filter { it.tabId !in seen && it.tabId !in tried }
                .sortedWith(compareBy<IndexTab>({ Ports.label(it) != null }, { it.tabId }))
            if (todo.isEmpty()) return
            tried += todo[0].tabId
            Pages.page(run, todo[0].tabId, Ports.url(todo[0]), todo[0].type)
        }
    }

    /** `_pins`: the song's pins you haven't blocked, in pinned order, each with the address you pasted. */
    fun pins(run: SongRun): List<Pair<Long, String?>> {
        val o = run.ctx.overrides
        val urls = o.pinUrls[run.song.key].orEmpty()
        return o.pin[run.song.key].orEmpty().withIndex().filter { (_, tab) -> tab !in o.block }
            .map { (i, tab) -> tab to urls.getOrNull(i) }
    }

    /**
     * `_pinned_url`: where a pinned tab's page is. UG serves a slugged tab only at its slugged URL, so the slugged
     * address you pasted comes first, even one robots.txt closes; a bare `/tab/{id}` you pasted adds nothing: then
     * UG's own link to the tab, else the index's path, else the bare page.
     */
    private fun pinnedUrl(run: SongRun, tabId: Long, pasted: String?, row: VersionRow?): String {
        if (pasted != null && Pages.onTabHost(pasted) && Pages.sluggedUrl(pasted, tabId)) return pasted
        return row?.url ?: UgLookup.tabUrlFor(run.db, tabId)
    }

    /** `_fetch_pins`: every pinned page read; the pinned ids of each kind group, in pinned order. A pin whose page
     * is gone, Official, not public, closed to caracole or of a type caracole doesn't use pins nothing. */
    fun fetchPins(run: SongRun, pins: List<Pair<Long, String?>>): Map<List<String>, List<Long>> {
        val groups = LinkedHashMap<List<String>, MutableList<Long>>()
        for ((tabId, pasted) in pins) {
            val row = Pages.versionRow(run, tabId)
            val known = UgLookup.indexTab(run.db, tabId)
            val url = pinnedUrl(run, tabId, pasted, row)
            val kind = row?.kind ?: known?.type
            val page = Pages.page(run, tabId, url, kind)
            if (page == null || !Pages.wanted(run, page.tab)) continue
            groups.getOrPut(Pages.groupOf(Ports.kind(page.tab))!!) { ArrayList() } += page.tab.tabId
        }
        return groups
    }

    // --- the slots -------------------------------------------------------------------------------------------

    /** `_rows`: the song's live UG versions of these kinds; blocked ids never compete, nor a version at a URL
     * robots.txt closes. */
    fun rows(run: SongRun, kinds: List<String>): List<VersionRow> {
        val block = run.ctx.overrides.block
        return Versions.songVersions(run.db, run.song.id, kinds = kinds)
            .filter { it.provider == UgFetch.PROVIDER && it.tabId.toLong() !in block && !Pages.closed(it.url) }
    }

    private fun inOrder(rows: List<VersionRow>, tabIds: List<Long>): List<VersionRow> {
        val byTab = rows.associateBy { it.tabId.toLong() }
        return tabIds.mapNotNull { byTab[it] }
    }

    fun candidate(row: VersionRow): Candidate = Candidate(
        provider = row.provider, tabId = row.tabId, kind = row.kind, rating = row.rating, votes = row.votes,
        version = row.version, label = row.label, coverage = row.coverage, versionId = row.id,
    )

    /** `_text_page`: a version's page with its text, or null when the page is gone or can't be read now. */
    fun textPage(run: SongRun, row: VersionRow): UgTabPage? =
        Pages.page(run, row.tabId.toLong(), row.url, row.kind)?.takeIf { it.content != null }

    /** `_first_with_text`: the best-ranked candidate whose page still has its text, with that page. */
    private fun firstWithText(run: SongRun, ranked: Sequence<Candidate>, rows: List<VersionRow>,
                              pages: Map<Long, UgTabPage>): Scored? {
        val byId = rows.associateBy { it.id }
        for (c in ranked) {
            val page = pages[c.versionId!!] ?: textPage(run, byId.getValue(c.versionId)) ?: continue
            return c to page
        }
        return null
    }

    /** `_keep`: one file kept, unless this version's identical bytes are kept already (then only its rank). */
    private fun keep(run: SongRun, versionId: Long, name: String, data: ByteArray, rank: Int) {
        val lib = run.ctx.library
        if (Kept.keptAlready(run.db, lib, run.song, versionId, name, data)) {
            run.db.execute("UPDATE files SET kept_rank = ? WHERE song_id = ? AND name = ? AND kept_rank != ?",
                           rank, run.song.id, name, rank)
            return
        }
        Kept.keepFile(run.db, lib, run.song, versionId, name, data, rank, run.stamp)
    }

    /** `_keep_text`: a sheet or tab kept, the text without UG's markup and the version's JSON with the raw content
     * and the page's `meta`, where UG gives the capo. */
    fun keepText(run: SongRun, versionId: Long, page: UgTabPage, names: Pair<String, String>, rank: Int = 1) {
        val content = page.content!!
        val url = Versions.get(run.db, versionId)!!.url
        keep(run, versionId, names.first, UgPage.stripMarkup(content).toByteArray(Charsets.UTF_8), rank)
        val body = JsonObject(linkedMapOf(
            "version" to page.tab.raw, "content" to JsonPrimitive(content), "url" to JsonPrimitive(url),
            "meta" to page.meta,
        ))
        keep(run, versionId, names.second, Pages.keptJson(body), rank)
    }

    /** `_kept_version`: the version a kept file came from, whichever step kept it. */
    fun keptVersion(db: Db, songId: Long, name: String): VersionRow? =
        Kept.keptFiles(db, songId).firstOrNull { it.name == name }?.let { Versions.get(db, it.versionId) }

    /** `_retire_auto_sheet`: a complete human sheet is kept, so the auto-chords sheet, which stands in for one, goes. */
    private fun retireAutoSheet(db: Db, lib: LibraryStore, song: SongRow) {
        val auto = keptVersion(db, song.id, UgFetch.AUTO_SHEET) ?: return
        Kept.dropFile(db, lib, song, UgFetch.AUTO_SHEET)
        Versions.setPicks(db, song.id, listOf(auto.kind), emptyList())
    }

    /** `_drop_left_over`: files kept from a UG version you have blocked since, or that an earlier match found, go even
     * when nothing replaces them. */
    fun dropLeftOver(run: SongRun, names: List<String>) {
        val kept = keptVersion(run.db, run.song.id, names[0])
        if (kept == null || kept.provider != UgFetch.PROVIDER) return
        if (kept.stale || kept.tabId.toLong() in run.ctx.overrides.block) {
            for (name in names) Kept.dropFile(run.db, run.ctx.library, run.song, name)
        }
    }

    /** `_lyric_lines`' source: the song's plain lyrics ("" for none), which Coverage reads its lines from. */
    fun lyrics(run: SongRun): String = songLyrics(run.db, run.song.id)?.plain ?: ""

    /** coverage.coverage(content, lyric_lines(plain), line_match=rank.line_match). */
    fun coverage(run: SongRun, content: String, lyrics: String): Double? = Coverage.coverage(content, lyrics, run.ctx.rank)

    /** Python's `seq[:n]`. */
    fun <T> head(list: List<T>, n: Int): List<T> = if (n >= 0) list.take(n) else list.dropLast(minOf(-n, list.size))

    /**
     * `_sheet_slot`: the top sheets scored for lyric coverage, ranked, the best kept (or the first pin's). [kinds] is
     * the group the sheet comes from: chords, or for a song with none, ukulele chords. A sheet another site gave
     * (LaCuerda's) is replaced only as `versions.replaces_sheet` says; a pin always wins; the LaCuerda sheet you picked
     * no sheet but a pin replaces. The sheet kept becomes the slot's only pick, and a complete one retires the
     * auto-chords sheet. The other versions scored are kept beside it, no request more; a pinned sheet keeps the top
     * versions by rating beside it, from the cache alone.
     */
    fun sheetSlot(run: SongRun, pinned: List<Long>?, kinds: List<String> = UgFetch.CHORDS_KINDS): Long? {
        val policy = run.ctx.rank
        val rows = rows(run, kinds)
        val lyrics = lyrics(run)
        val byId = rows.associateBy { it.id }
        val pages = LinkedHashMap<Long, UgTabPage>()

        /** Fetch the sheet and score its coverage: the candidate scored, or null when its page is gone or unreadable. */
        fun scored(c: Candidate): Candidate? {
            val page = textPage(run, byId.getValue(c.versionId!!)) ?: return null
            pages[c.versionId] = page
            val cov = coverage(run, page.content!!, lyrics)
            Versions.setCoverage(run.db, c.versionId, cov)
            return c.copy(coverage = cov)
        }

        val ranked: Sequence<Candidate>
        val rankedList: List<Candidate>
        if (pinned != null) {
            ranked = inOrder(rows, pinned).asSequence().map(::candidate).mapNotNull(::scored)
            rankedList = emptyList()
        } else {
            val alive = ArrayList<Candidate>()
            for (c in Rank.rankByRating(rows.map(::candidate), policy, run.song.variant)) {
                if (pages.size < policy.scoredSheets) {
                    alive += scored(c) ?: continue  // gone or unreadable; the next one is scored instead
                } else {
                    alive += c
                }
            }
            rankedList = Rank.rankSheets(alive, policy, run.song.variant)
            ranked = rankedList.asSequence()
        }

        fun keepBeside(chosen: Long?) {
            if (!run.ctx.versions) return
            val top = if (pinned != null) Beside.besideAPin(run, rows, lyrics)
                      else rankedList.mapNotNull { c -> pages[c.versionId]?.let { c to it } }
            val (yours, hold) = Beside.yours(run, rows, lyrics, top)
            Beside.keepBeside(run, chosen, top + yours, hold)
        }

        val best = firstWithText(run, ranked, rows, pages)
        if (best == null) {
            Versions.setPicks(run.db, run.song.id, kinds, emptyList())
            dropLeftOver(run, UgFetch.SHEET_FILES)
            keepBeside(null)
            return null
        }
        val (c, page) = best
        val kept = keptVersion(run.db, run.song.id, UgFetch.SHEET_FILES[0])
        val chosen = run.ctx.overrides.lacuerda[run.song.key]
        if (kept != null && kept.provider != UgFetch.PROVIDER && pinned == null &&
            ((chosen != null && kept.provider == "lacuerda" && Ports.holds(chosen, kept.tabId)) ||
                !Rank.replacesSheet(c.coverage, kept.coverage, policy.coverageThreshold))) {
            Versions.setPicks(run.db, run.song.id, kinds, emptyList())  // the other site's sheet stays the pick
            keepBeside(null)
            return null
        }
        Beside.makeWay(run, c.tabId, page)
        keepText(run, c.versionId!!, page, UgFetch.SHEET_FILES[0] to UgFetch.SHEET_FILES[1])
        Versions.setPicks(run.db, run.song.id, Versions.SHEET_KINDS, listOf(c.versionId))
        if (Rank.isComplete(c, policy)) retireAutoSheet(run.db, run.ctx.library, run.song)
        keepBeside(c.versionId)
        return c.tabId.toLong()
    }

    /** `_tab_slot`: the best text tab (or the first pin) kept as tab.txt and tab.json. */
    fun tabSlot(run: SongRun, pinned: List<Long>?): Long? {
        val rows = rows(run, UgFetch.TAB_KINDS)
        val ranked = if (pinned != null) inOrder(rows, pinned).map(::candidate)
                     else Ports.rankGuitar(rows.map(::candidate), run.ctx.rank, run.song.variant)
        val best = firstWithText(run, ranked.asSequence(), rows, emptyMap())
        if (best == null) {
            Versions.setPicks(run.db, run.song.id, UgFetch.TAB_KINDS, emptyList())
            dropLeftOver(run, UgFetch.TAB_FILES)
            return null
        }
        val (c, page) = best
        keepText(run, c.versionId!!, page, UgFetch.TAB_FILES[0] to UgFetch.TAB_FILES[1])
        Versions.setPicks(run.db, run.song.id, UgFetch.TAB_KINDS, listOf(c.versionId))
        return c.tabId.toLong()
    }

    /** sha256 hex of [data], as hashlib writes it. */
    fun sha256(data: ByteArray): String = Canonical.sha256Hex(data)

    /** `sheet_group`: the UG kinds the song's sheet comes from: ukulele chords when its kept sheet is a UG ukulele
     * version, else chords; the versions kept beside it are of the same group. */
    fun sheetGroup(db: Db, songId: Long): List<String> =
        if (SheetVersions.sheetKind(db, songId) in UgFetch.UKULELE_KINDS) UgFetch.UKULELE_KINDS else UgFetch.CHORDS_KINDS
}
