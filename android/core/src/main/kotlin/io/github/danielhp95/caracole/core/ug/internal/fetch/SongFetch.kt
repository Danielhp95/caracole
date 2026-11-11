package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.ug.ArtistRoute
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgLookup
import io.github.danielhp95.caracole.core.ug.UgPage
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.math.BigInteger
import java.time.DateTimeException
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit

/** ug/fetch.py's one song: `process_song`, `_finish`, `keep_version`, `checked_since` and what they read. */
internal object SongFetch {
    private val KEPT_TEXT = UgFetch.SHEET_FILES + UgFetch.TAB_FILES

    /** `_KEPT_TEXT_SQL`: `files f` rows of a kept UG sheet or tab, or of a version kept beside the sheet. */
    private val KEPT_TEXT_SQL =
        "(f.name IN (${KEPT_TEXT.joinToString(",") { "?" }}) OR f.name GLOB '${SheetVersions.PREFIX}[0-9]*')"

    /**
     * `process_song`: one song's UG versions fetched, ranked and kept, one slot at a time. A not-found song is first
     * looked up on its artist's UG page ([ArtistPages]), and goes on only when it is found there; any other song
     * without a match only loses what an undone match kept, with no request. Each kind group is rated and its slot
     * filled before the next is touched, so the sheet is settled before the budget goes to the tab; with [guitar]
     * false (a lookup's sheet pass) the song stays as the tab slot needs it.
     */
    fun processSong(ctx: FetchContext, given: SongRow, guitar: Boolean): SongFetchOutcome {
        val start = ctx.client.requestsMade
        val run = SongRun(ctx, given)
        var song = given
        fun unfinished() = SongFetchOutcome(given.id, null, null, ctx.client.requestsMade - start)

        if (needsArtistPage(song)) {
            if (!ArtistPages.route(run)) return unfinished()
            song = run.song
        } else if (song.matchDecision !in setOf("accept", "pinned")) {
            dropUndone(run)
            return unfinished()
        } else if (song.matchStep == Match.ARTIST_PAGE && !ArtistPages.versions(run, ArtistRoute.ARTIST_PAGE_KINDS)) {
            return unfinished()
        }
        val tabs = songIndexTabs(ctx.db, song, ctx.overrides.block)
        val pinned = Slots.fetchPins(run, Slots.pins(run))

        fun rated(group: List<String>): List<Long>? {
            if (group !in pinned) {
                val pages = if (group == UgFetch.TAB_KINDS) ctx.guitarPagesPerGroup else ctx.maxPagesPerGroup
                for (kind in group) Slots.rateGroup(run, tabs.filter { it.type == kind }, pages)  // UG lists per type
            }
            return pinned[group]
        }

        var sheetKinds = UgFetch.CHORDS_KINDS
        val sheetPins: List<Long>?
        if (UgFetch.UKULELE_KINDS in pinned && UgFetch.CHORDS_KINDS !in pinned) {  // your ukulele pin chooses the sheet
            sheetPins = pinned.getValue(UgFetch.UKULELE_KINDS)
            sheetKinds = UgFetch.UKULELE_KINDS
        } else {
            sheetPins = rated(UgFetch.CHORDS_KINDS)
            if (sheetPins == null && song.matchStep != Match.ARTIST_PAGE && liveChords(ctx.db, song, tabs).isEmpty()) {
                val own = tabs.filter { it.type !in UgFetch.CHORDS_KINDS }
                if (!ArtistPages.versions(run, UgFetch.CHORDS_KINDS, own)) return unfinished()
            }
            if (sheetPins == null && Slots.rows(run, UgFetch.CHORDS_KINDS).isEmpty() &&
                liveChords(ctx.db, song, tabs).isEmpty()) {
                // No chords on UG (an unreadable chords page is no "none": the song waits): its ukulele chords, if any.
                rated(UgFetch.UKULELE_KINDS)
                if (Slots.rows(run, UgFetch.UKULELE_KINDS).isNotEmpty()) sheetKinds = UgFetch.UKULELE_KINDS
            }
        }
        val sheet = Slots.sheetSlot(run, sheetPins, sheetKinds)
        if (!guitar) {
            // The sheet pass: the song stays dirty until its tab slot is done.
            return SongFetchOutcome(given.id, sheet, null, ctx.client.requestsMade - start, settled = true,
                                    keptVersions = run.keptVersions)
        }
        val tab = Slots.tabSlot(run, rated(UgFetch.TAB_KINDS))
        finish(run)
        return SongFetchOutcome(given.id, sheet, tab, ctx.client.requestsMade - start, settled = true,
                                keptVersions = run.keptVersions)
    }

    /**
     * `_finish`: every slot is done: the status refreshed and the song marked checked. A song with a page that
     * couldn't be read is neither checked nor clean (an error is never a miss). The tabs [block] left out are
     * remembered (kv `ug:blocked:<song id>`), so that taking one out of [block] brings the song back. info.json is
     * the viewer's (M5): the phone writes none.
     */
    private fun finish(run: SongRun) {
        val db = run.db
        Versions.refreshStatus(db, run.song.id, ignored = false, now = run.stamp)
        if (run.unreadable.isNotEmpty()) {
            Versions.updateSong(db, run.song.id, mapOf("ug_dirty" to true), now = run.stamp)
        } else {
            Versions.updateSong(db, run.song.id, mapOf("ug_dirty" to false, "ug_checked_at" to run.stamp), now = run.stamp)
        }
        val leftOut = leftOut(run)
        if (leftOut.isNotEmpty()) {
            db.kvSetJson(leftOutKey(run.song.id), JsonArray(leftOut.map { JsonPrimitive(it) }))
        } else {
            db.kvDelete(leftOutKey(run.song.id))
        }
    }

    private fun leftOutKey(songId: Long) = "ug:blocked:$songId"

    /** `_left_out`: the tabs you have blocked among the song's: its UG versions, its index tabs and its pins. */
    private fun leftOut(run: SongRun): List<Long> {
        val block = run.ctx.overrides.block
        if (block.isEmpty()) return emptyList()
        val song = run.song
        val ids = Versions.songVersions(run.db, song.id, includeGone = true)
            .filter { it.provider == UgFetch.PROVIDER && !it.stale }.map { it.tabId.toLong() }.toMutableSet()
        ids += songIndexTabs(run.db, song, emptySet()).map { it.tabId }
        ids += run.ctx.overrides.pin[song.key].orEmpty()
        return ids.filter { it in block }.sorted()
    }

    /** `_song_index_tabs`: the song's tabs in the index under its match's keys; blocked ones left out, and ones whose
     * page robots.txt closes. */
    fun songIndexTabs(db: Db, song: SongRow, block: Set<Long>): List<IndexTab> {
        val artist = song.matchArtistKey
        val tabs = if (!song.matchSongKey.isNullOrEmpty() && artist != null) UgLookup.songTabs(db, artist, song.matchSongKey)
                   else emptyList()
        return tabs.filter { it.tabId !in block && !Pages.closed(it.url) }
    }

    /** `_live_chords`: the chords tabs among the song's index [tabs] that UG hasn't since answered 404 for. */
    private fun liveChords(db: Db, song: SongRow, tabs: List<IndexTab>): List<IndexTab> {
        val gone = Versions.songVersions(db, song.id, kinds = UgFetch.CHORDS_KINDS, includeGone = true)
            .filter { it.provider == UgFetch.PROVIDER && it.gone }.map { it.tabId.toLong() }.toSet()
        return tabs.filter { it.type in UgFetch.CHORDS_KINDS && it.tabId !in gone }
    }

    /** `_ignored`. */
    private fun ignored(song: SongRow, overrides: Overrides): Boolean =
        song.status == "ignored" || song.matchDecision == "ignored" || song.key in overrides.ignore

    /** `_undone`: whether the song keeps a sheet or a tab from a UG version an earlier match found. */
    private fun undone(db: Db, songId: Long): Boolean = db.one(
        "SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND v.provider = ? " +
            "AND v.gone = ${Versions.STALE} AND $KEPT_TEXT_SQL LIMIT 1",
        songId, UgFetch.PROVIDER, *KEPT_TEXT.toTypedArray(),
    ) { true } != null

    /** `_drop_undone`: a song that has no UG match now loses the sheet, the tab and the versions an earlier match
     * kept; its status then says what is left. Guitar Pro files and every file of an ignored song stay. */
    fun dropUndone(run: SongRun) {
        if (ignored(run.song, run.ctx.overrides) || !undone(run.db, run.song.id)) return
        Slots.dropLeftOver(run, UgFetch.SHEET_FILES)
        Slots.dropLeftOver(run, UgFetch.TAB_FILES)
        val tabs = Kept.keptFiles(run.db, run.song.id).mapNotNull { SheetVersions.tabOf(it.name) }.toCollection(LinkedHashSet())
        for (tab in tabs) {
            val (txt, doc, _) = SheetVersions.versionNames(tab)
            Slots.dropLeftOver(run, listOf(txt, doc))
        }
        Versions.refreshStatus(run.db, run.song.id, ignored = false, now = run.stamp)
    }

    /**
     * `needs_artist_page`: whether the index can't settle this song, so its artist's UG page should be read: a
     * not-found song, or a review whose only candidates come from the steps that never accept.
     */
    fun needsArtistPage(song: SongRow): Boolean {
        if (song.matchDecision == "not_found") return true
        if (song.matchDecision != "review") return false
        val candidates = (runCatching { Json.parseToJsonElement(song.matchCandidates) }.getOrNull() as? JsonArray)
            ?: return false
        return candidates.isNotEmpty() && candidates.all { c ->
            ((c as? JsonObject)?.get("step") as? JsonPrimitive)?.takeIf { it.isString }?.content in Match.REVIEW_ONLY_STEPS
        }
    }

    /**
     * `keep_version`: one of the song's UG chords versions kept beside its sheet now, because you asked: its page read
     * (one request at most, none from the cache), kept as `version-<tab>.txt` and `.json` and noted as yours. What
     * came of it: kept, same (its text is a kept one's: that one's page shows it), held (its text is another kept
     * file's, the tab's), sheet, gone, unreadable, closed, no text, or unknown. Only kept and same note it as yours.
     * A block, a spent budget or an error raises, keeping nothing.
     */
    fun keepVersion(ctx: FetchContext, song: SongRow, tabId: Long): String {
        val run = SongRun(ctx, song)
        val db = ctx.db
        val row = Slots.rows(run, Slots.sheetGroup(db, song.id)).firstOrNull { it.tabId == tabId.toString() }
            ?: return "unknown"
        val page = Slots.textPage(run, row)
        if (page == null) {
            if (Versions.get(db, row.id)!!.gone) return "gone"
            if (tabId in run.closed) return "closed"  // no failure and no miss: neither unreadable nor a page with no text
            return if (tabId in run.unreadable) "unreadable" else "no text"
        }
        val content = page.content!!
        Versions.setCoverage(db, row.id, Slots.coverage(run, content, Slots.lyrics(run)))
        val (chosen, kept) = SheetVersions.libraryState(db, song.id)
        if (chosen == row.tabId) return "sheet"
        val ranks = Kept.keptFiles(db, song.id).associate { it.name to it.keptRank }
        val txt = SheetVersions.versionNames(row.tabId).first
        val rank = ranks[txt]?.takeIf { it != 0 }
            ?: ((kept.maxOfOrNull { ranks.getValue(SheetVersions.versionNames(it).first) } ?: 1) + 1)
        if (Beside.keepVersion(run, row.id, page, rank)) {
            SheetVersions.noteKeptByYou(db, song.id, row.tabId)
            return "kept"
        }
        val shown = Beside.sameText(run, txt, UgPage.stripMarkup(content).toByteArray(Charsets.UTF_8)) ?: return "held"
        SheetVersions.noteKeptByYou(db, song.id, row.tabId)
        val same = LinkedHashMap(SheetVersions.samePages(db, song.id))
        same[row.tabId] = shown
        db.kvSetJson(SheetVersions.sameKey(song.id), JsonObject(same.mapValues { JsonPrimitive(it.value) }))
        return "same"
    }

    /**
     * `checked_since`: whether a fetch settled the song at [since] or after, so what it lacks now, UG lacks: a matched
     * song once its fetch finished (`ug_checked_at`), a song with no match yet once its artist's UG page was read for
     * it (kv `ug:artist_page_checked:<song id>`). Both are written to the second.
     */
    fun checkedSince(db: Db, song: SongRow, since: Instant): Boolean {
        val from = since.truncatedTo(ChronoUnit.SECONDS)
        song.ugCheckedAt?.takeIf { it.isNotEmpty() }?.let(Pages::parseIso)?.let { if (it >= from) return true }
        if (song.matchDecision in setOf("accept", "pinned")) return false
        val checked = db.kvGet("ug:artist_page_checked:${song.id}")?.let(Pages::parseIso) ?: return false
        return checked >= from
    }

    // --- fetch_due: whether a run would fetch the song (the to-do page's and the cards' buy list) -------------------

    /** `fetch_due`: `songs_to_fetch` for one song: matched and dirty (or its `[block]` changed since), due on its
     * artist's UG page, an undone match still kept, or an accepted song's artist page due again. */
    fun fetchDue(db: Db, song: SongRow, overrides: Overrides, now: Instant, maxAge: Duration): Boolean {
        if (ignored(song, overrides)) return false
        val matched = song.matchDecision == "accept" || song.matchDecision == "pinned"
        val dirty = matched && (song.ugDirty || blockChanged(db, song, overrides.block))
        val due = needsArtistPage(song) && !checkedWithin(db, song.id, now, maxAge) &&
            ArtistRoute.artistIsKnown(db, song, overrides)
        val undone = !matched && undone(db, song.id)
        return dirty || due || undone || recheckDue(db, song, overrides, now, maxAge)
    }

    /** `_block_changed`: a tab the song keeps (as sheet.txt or tab.txt) or picks blocked since its fetch, or a tab the
     * fetch left out (kv `ug:blocked:<id>`) no longer blocked. A tab id there is compared as Python's int (a bool its
     * 0 or 1, anything else never in [block]); a kept version's id that isn't one an error, int()'s ValueError. */
    private fun blockChanged(db: Db, song: SongRow, block: Set<Long>): Boolean {
        val leftOut = db.kvGet(leftOutKey(song.id))?.let { PyJson.loads(it) } as? JsonArray ?: JsonArray(emptyList())
        val blocked = block.mapTo(HashSet(), BigInteger::valueOf)
        if (leftOut.any { t -> (t as? JsonPrimitive)?.let(::pythonInt).let { it == null || it !in blocked } }) {
            return true
        }
        if (block.isEmpty()) return false
        val rows = db.query(
            "SELECT v.tab_id FROM versions v WHERE v.song_id = ? AND v.provider = ? AND (v.pick_rank IS NOT NULL " +
                "OR EXISTS (SELECT 1 FROM files f WHERE f.version_id = v.id AND $KEPT_TEXT_SQL))",
            song.id, UgFetch.PROVIDER, *KEPT_TEXT.toTypedArray(),
        ) { it.text(0)!! }
        return rows.any { tab ->
            (PyInt.parse(tab) ?: throw IllegalArgumentException("invalid literal for int() with base 10: '$tab'")) in blocked
        }
    }

    /** A JSON number as Python's int compares it (True is 1); null for anything that is no int. */
    private fun pythonInt(p: JsonPrimitive): BigInteger? = when {
        p.isString -> null
        p.booleanOrNull != null -> if (p.booleanOrNull == true) BigInteger.ONE else BigInteger.ZERO
        else -> p.content.toBigIntegerOrNull()
    }

    /** `_last_checked`: when the song was last looked up on its artist's UG page (kv `ug:artist_page_checked:<id>`),
     * read as `_parse_iso`'s strptime reads it: a time it can't read is its ValueError, an IllegalArgumentException. */
    private fun lastChecked(db: Db, songId: Long): Instant? =
        db.kvGet("ug:artist_page_checked:$songId")?.let(::strptime)

    /** `_parse_iso`: `strptime(value, "%Y-%m-%dT%H:%M:%SZ")` in UTC (each field a run of Python's `\d`, %Y four of
     * them, the others one or two); anything else its ValueError, an IllegalArgumentException. */
    private fun strptime(value: String): Instant {
        val m = PyRe.fullmatch(STRPTIME, value) ?: throw IllegalArgumentException("time data '$value' does not match format")
        val f = m.groupValues.drop(1).map { PyInt.parse(it)!!.toInt() }
        return try {
            LocalDateTime.of(f[0], f[1], f[2], f[3], f[4], f[5]).toInstant(ZoneOffset.UTC)
        } catch (e: DateTimeException) {
            throw IllegalArgumentException(e.message, e)
        }
    }

    private val STRPTIME: Regex by lazy {
        PyRegex.compile("""(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{1,2}):(\d{1,2})Z""")
    }

    /** `_checked_within`. */
    private fun checkedWithin(db: Db, songId: Long, now: Instant, maxAge: Duration): Boolean {
        val checked = lastChecked(db, songId) ?: return false
        return Duration.between(checked, now) < maxAge
    }

    /** `_recheck_due`: an accepted song whose artist's UG page is due again (accepted there, or its index tabs hold no
     * chords UG still has), once [maxAge] has passed since it was read for it. */
    private fun recheckDue(db: Db, song: SongRow, overrides: Overrides, now: Instant, maxAge: Duration): Boolean {
        if (song.matchDecision != "accept") return false
        val checked = lastChecked(db, song.id) ?: return false
        if (Duration.between(checked, now) < maxAge) return false
        return song.matchStep == Match.ARTIST_PAGE || liveChords(db, song, songIndexTabs(db, song, overrides.block)).isEmpty()
    }
}
