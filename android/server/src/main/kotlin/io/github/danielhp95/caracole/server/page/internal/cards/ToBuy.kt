package io.github.danielhp95.caracole.server.page.internal.cards

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgLookup
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.math.BigInteger
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

/**
 * What a card's buy links rest on: todo.songs_to_buy (the to-do page's buy list) with ug/fetch.py's fetch_due, ug/
 * index.py's index_state and lacuerda_fetch.may_ask, and todo.search_links.
 *
 * fetch_due is ported here, as the page reads it, because :core's fetch keeps its pieces to itself (ug/internal/
 * fetch: `_block_changed`, `_checked_within`, `_undone`, `_recheck_due`, `artist_is_known`); each is Python's line for
 * line, over the same rows and kv (vectors/web/cards_full.jsonl: a song due by its artist's page, by a recheck, by a
 * match undone, by a block, at two times).
 */
internal object ToBuy {
    /** ug/fetch.ARTIST_PAGE_MAX_AGE: an artist's page read for a song is read again after this. */
    val ARTIST_PAGE_MAX_AGE: Duration = Duration.ofDays(30)

    /** ug/index.BUILT_KEY: the index holds every tab sitemap. */
    private const val BUILT_KEY = "ug:index:built_at"

    /** match.ARTIST_PAGE: a match the fetch made on the artist's UG page. */
    private const val ARTIST_PAGE = "artist_page"

    /** ug/fetch.KEPT_TEXT and _KEPT_TEXT_SQL: the files a kept UG sheet or tab is, or a version kept beside it. */
    private val KEPT_TEXT = UgFetch.SHEET_FILES + UgFetch.TAB_FILES
    private val KEPT_TEXT_SQL =
        "(f.name IN (${KEPT_TEXT.joinToString(",") { "?" }}) OR f.name GLOB '${SheetVersions.PREFIX}[0-9]*')"

    /** ug/index.index_state: "empty", "partial" or "complete". */
    fun indexState(db: Db): String {
        if (db.one("SELECT 1 FROM ug_index LIMIT 1") { true } == null) return "empty"
        return if (db.kvGet(BUILT_KEY) != null) "complete" else "partial"
    }

    /**
     * todo.songs_to_buy's buy list: the wanted songs (not ignored, no audio linked) whose next step is buying the track,
     * once nothing caracole will still do may find them a sheet: matched and fetched, or not found with the index read
     * whole; no fetch due, no LaCuerda check due, no pick on LaCuerda still to come. By id, in [songs]' order.
     */
    fun songsToBuy(db: Db, songs: List<SongRow>, overrides: Overrides, now: Instant, audio: Map<Long, String?>):
        List<SongRow> {
        val partial = indexState(db) == "partial"
        val buy = ArrayList<SongRow>()
        for (s in songs) {
            if (s.status != "wanted" || !audio[s.id].isNullOrEmpty() || s.key in overrides.ignore) continue
            if (s.matchDecision !in listOf("accept", "pinned", "not_found")) continue
            val unfetched = s.matchDecision != "not_found" && s.ugCheckedAt.isNullOrEmpty()
            val picked = s.key in overrides.lacuerda && s.lacuerdaCheckedAt == null
            if (unfetched || fetchDue(db, s, overrides, now) || lacuerdaDue(s) || picked) continue
            if (!(partial && s.matchDecision == "not_found")) buy += s
        }
        return buy
    }

    /** todo._lacuerda_due: LaCuerda never answered for the song, and may have it. */
    private fun lacuerdaDue(song: SongRow): Boolean = song.lacuerdaCheckedAt == null && mayAsk(song)

    /** lacuerda_fetch.may_ask: the song looks Spanish (by its lyrics' plain text when it has some, else its title),
     * and a slug of LaCuerda's can be built from its first artist's name. */
    fun mayAsk(song: SongRow): Boolean {
        val lyrics = lyricsFromJson(song.lyricsJson)
        val first = song.artists.firstOrNull() ?: throw IndexOutOfBoundsException("list index out of range")
        return LaCuerdaPages.looksSpanish(Normalize.cleanTitle(song.title), lyrics?.plain) &&
            LaCuerdaPages.artistSlugCandidates(first).isNotEmpty()
    }

    /** ug/fetch.fetch_due: whether a run would fetch the song. */
    fun fetchDue(db: Db, song: SongRow, overrides: Overrides, now: Instant,
                 maxAge: Duration = ARTIST_PAGE_MAX_AGE): Boolean {
        if (ignored(song, overrides)) return false
        val matched = song.matchDecision == "accept" || song.matchDecision == "pinned"
        val dirty = matched && (song.ugDirty || blockChanged(db, song, overrides.block))
        val due = UgFetch.needsArtistPage(song) && !checkedWithin(db, song.id, now, maxAge) &&
            artistIsKnown(db, song, overrides)
        val undone = !matched && undone(db, song.id)
        return dirty || due || undone || recheckDue(db, song, overrides, now, maxAge)
    }

    private fun ignored(song: SongRow, overrides: Overrides): Boolean =
        song.status == "ignored" || song.matchDecision == "ignored" || song.key in overrides.ignore

    /** `_block_changed`: a tab the song keeps or picks blocked since its fetch, or one it left out no longer blocked
     * (kv `ug:blocked:<id>`). */
    private fun blockChanged(db: Db, song: SongRow, block: Set<Long>): Boolean {
        val leftOut = db.kvGet("ug:blocked:${song.id}")?.let { PyJson.loads(it) } as? JsonArray ?: JsonArray(emptyList())
        val blocked = block.map(BigInteger::valueOf).toSet()
        if (leftOut.any { t -> (t as? JsonPrimitive)?.let { p -> number(p) }.let { it == null || it !in blocked } }) {
            return true
        }
        if (block.isEmpty()) return false
        val rows = db.query(
            "SELECT v.tab_id FROM versions v WHERE v.song_id = ? AND v.provider = ? AND (v.pick_rank IS NOT NULL " +
                "OR EXISTS (SELECT 1 FROM files f WHERE f.version_id = v.id AND $KEPT_TEXT_SQL))",
            song.id, UgFetch.PROVIDER, *KEPT_TEXT.toTypedArray(),
        ) { it.text(0)!! }
        return rows.any { int(it) in blocked }
    }

    /** Python's int() of a tab id, its ValueError an IllegalArgumentException. */
    private fun int(text: String): BigInteger =
        PyInt.parse(text) ?: throw IllegalArgumentException("invalid literal for int() with base 10: '$text'")

    /** A JSON integer as Python's int (a bool is an int too: True is 1). */
    private fun number(p: JsonPrimitive): BigInteger? = when {
        p.isString -> null
        p.booleanOrNull != null -> if (p.booleanOrNull == true) BigInteger.ONE else BigInteger.ZERO
        else -> p.content.toBigIntegerOrNull()
    }

    /** `_last_checked`: when the song was last looked up on its artist's UG page (kv `ug:artist_page_checked:<id>`). */
    private fun lastChecked(db: Db, songId: Long): Instant? =
        db.kvGet("ug:artist_page_checked:$songId")?.let(::parseIso)

    /** ug/fetch._parse_iso: `strptime(value, "%Y-%m-%dT%H:%M:%SZ")` in UTC (its fields Python's `\d` runs, %Y of four);
     * anything else its ValueError, an IllegalArgumentException. */
    private fun parseIso(value: String): Instant {
        val m = PyRe.fullmatch(ISO, value) ?: throw IllegalArgumentException("time data '$value' does not match format")
        val (year, month, day, hour, minute, second) = m.groupValues.drop(1).map { PyInt.parse(it)!!.toInt() }
        return try {
            LocalDateTime.of(year, month, day, hour, minute, second).toInstant(ZoneOffset.UTC)
        } catch (e: java.time.DateTimeException) {
            throw IllegalArgumentException(e.message, e)
        }
    }

    private operator fun <T> List<T>.component6(): T = this[5]

    private val ISO: Regex = PyRegex.compile("""(\d{4})-(\d{1,2})-(\d{1,2})T(\d{1,2}):(\d{1,2}):(\d{1,2})Z""")

    private fun checkedWithin(db: Db, songId: Long, now: Instant, maxAge: Duration): Boolean {
        val checked = lastChecked(db, songId) ?: return false
        return Duration.between(checked, now) < maxAge
    }

    /** `_undone`: the song keeps a sheet or a tab from a UG version an earlier match found. */
    private fun undone(db: Db, songId: Long): Boolean = db.one(
        "SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND v.provider = ? " +
            "AND v.gone = ${Versions.STALE} AND $KEPT_TEXT_SQL LIMIT 1",
        songId, UgFetch.PROVIDER, *KEPT_TEXT.toTypedArray(),
    ) { true } != null

    /** `_recheck_due`: an accepted song whose artist's page is due again (accepted there, or its index tabs hold no
     * chords UG still has), once [maxAge] has passed since it was read for it. */
    private fun recheckDue(db: Db, song: SongRow, overrides: Overrides, now: Instant, maxAge: Duration): Boolean {
        if (song.matchDecision != "accept") return false
        val checked = lastChecked(db, song.id) ?: return false
        if (Duration.between(checked, now) < maxAge) return false
        return song.matchStep == ARTIST_PAGE || liveChords(db, song, songIndexTabs(db, song, overrides.block)).isEmpty()
    }

    private fun songIndexTabs(db: Db, song: SongRow, block: Set<Long>) =
        (if (!song.matchSongKey.isNullOrEmpty()) UgLookup.songTabs(db, song.matchArtistKey ?: "", song.matchSongKey!!)
         else emptyList()).filter { it.tabId !in block && Robots.disallows(it.url) == null }

    private fun liveChords(db: Db, song: SongRow, tabs: List<io.github.danielhp95.caracole.core.ug.IndexTab>) =
        Versions.songVersions(db, song.id, kinds = UgFetch.CHORDS_KINDS, includeGone = true)
            .filter { it.provider == UgFetch.PROVIDER && it.gone }.map { int(it.tabId) }.toSet()
            .let { gone -> tabs.filter { it.type in UgFetch.CHORDS_KINDS && BigInteger.valueOf(it.tabId) !in gone } }

    /** `artist_is_known`: the song's artist page can be found: pasted in `[artist_url]` (a tab page there until
     * reading it showed it leads to no artist page), learned, or in the index. */
    private fun artistIsKnown(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val keys = artistKeys(song, overrides)
        val entry = overrides.artistUrlEntry(keys)
        if (entry != null && failedPaste(db, entry.second) == null) return true
        return keys.any { !UgLookup.learnedArtistUrl(db, it).isNullOrEmpty() || UgLookup.artistKnown(db, it) }
    }

    /** `artist_keys`: `[alias]` first, then each artist's own keys, each once, in order, none empty. */
    private fun artistKeys(song: SongRow, overrides: Overrides): List<String> {
        val keys = ArrayList<String>()
        for (name in song.artists.ifEmpty { listOf(song.artist) }) {
            keys += overrides.alias[Normalize.slugKey(name)].orEmpty()
            keys += Normalize.nameForms(name)
        }
        return keys.distinct().filter { it.isNotEmpty() }
    }

    /** `_failed_paste`: what reading the tab page at an `[artist_url]` address found wrong, if it led to no page. */
    private fun failedPaste(db: Db, url: String): String? {
        val tab = OverrideUrls.pastedTabId(url) ?: return null
        val record = db.kvGet("ug:pasted_tab:$tab")?.let { PyJson.loads(it) } as? JsonObject ?: return null
        return (record["problem"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { it.isNotEmpty() }
    }

    /** todo.search_links: where to look for what caracole won't do itself: buying, Chordify, Songsterr, YouTube. */
    fun searchLinks(artist: String, title: String): Map<String, String> {
        val q = "$artist ${Normalize.cleanTitle(title)}"
        val lesson = if (Normalize.hasHan(q)) "$q 吉他教学" else "$q guitar lesson"
        val quoted = PyUrl.quote(q)
        return linkedMapOf(
            "bandcamp" to "https://bandcamp.com/search?q=$quoted&item_type=t",
            "qobuz" to "https://www.qobuz.com/us-en/search?q=$quoted",
            "itunes" to "https://music.apple.com/us/search?term=$quoted",
            "chordify" to "https://chordify.net/search/$quoted",
            "songsterr" to "https://www.songsterr.com/?pattern=$quoted",
            "youtube" to "https://www.youtube.com/results?search_query=${PyUrl.quote(lesson)}",
        )
    }
}
