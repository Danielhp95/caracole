package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.http.UnreadablePage
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.ug.ArtistRoute
import io.github.danielhp95.caracole.core.ug.ArtistTabs
import io.github.danielhp95.caracole.core.ug.IndexTab
import io.github.danielhp95.caracole.core.ug.UgArtist
import io.github.danielhp95.caracole.core.ug.UgArtistPage
import io.github.danielhp95.caracole.core.ug.UgLookup
import io.github.danielhp95.caracole.core.ug.UgVersion
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * ug/fetch.py's artist-page route (A6), which [SongFetch.processSong] calls: a song the index can't place looked up
 * on its artist's UG page ([route]), and a matched song's entries in its artist's lists read as its versions
 * ([versions]). UG's artist page lists the bare-id tabs the sitemap index can't see.
 *
 * - **The page's address**: your `[artist_url]` (the artist's page, or one of their tab pages, read once for the page
 *   it links to: kv `ug:pasted_tab:<tab>`, and what is wrong with it when it leads nowhere), else one learned from a
 *   tab page (kv `ug:artist_url:<artist key>`), else learned now from a slugged tab of the artist in the index,
 *   [ArtistRoute.LEARN_TRIES] at most (a matched song's own index tabs first).
 * - **The lists**: the chords list first, then the others its filter bar offers (a list that answers 404 sends
 *   caracole to the unfiltered page, whose bar names them; a 404 there too is a page gone, forgotten). A list is read
 *   page by page until the title's entries end, [io.github.danielhp95.caracole.core.ug.FetchContext.artistPagesPerKind]
 *   pages a kind at most (cut short: the song as it was, for the next lookup), each from the cache within
 *   [io.github.danielhp95.caracole.core.ug.FetchContext.artistPageMaxAge] (a stale copy, which the client serves only
 *   once the budget is spent, is no answer: BudgetExhausted), every page read stored for searches
 *   ([ArtistTabs.store], which notes it for the computer) and a list read to its end the whole of its kind
 *   ([ArtistTabs.keepOnly]).
 * - **Titles**: every exact one, else the best fuzzy title (rapidfuzz ratio [ArtistRoute.TITLE_MATCH] at least)
 *   when it leads the next different title by [ArtistRoute.TITLE_MARGIN]; a UG song you `[reject]`ed drops out first.
 * - Found: the hits recorded as the song's versions (only a list read from UG now updates ratings), the match written
 *   with step `artist_page`; not found: the check recorded (kv `ug:artist_page_checked:<song>`) and what an undone
 *   match kept dropped. A pasted tab page that leads nowhere, or can't be read, records no check.
 */
internal object ArtistPages {
    /** A tab whose listed title is the song's, on an artist page; [fresh]: read from UG this run, not the cache. */
    class Hit(val tab: UgVersion, val key: String, val score: Double, val fresh: Boolean)

    /** What an artist's UG page lists for one song: [complete] false when this run's page cap cut a list short,
     * [gone] when UG answered 404 for the artist page itself. */
    class Listing(val hits: MutableList<Hit> = ArrayList(), var name: String = "", var complete: Boolean = true,
                  var gone: Boolean = false)

    // --- the route ---------------------------------------------------------------------------------------------

    /** `_artist_page_route`: a not-found song looked up on its artist's UG page; true when it was found and accepted
     * there ([SongRun.song] then its match). */
    fun route(run: SongRun): Boolean {
        val overrides = run.ctx.overrides
        val keys = ArtistRoute.artistKeys(run.song, overrides)
        readPastedTabPage(run, keys)
        val base = knownArtistPage(run.db, keys, overrides) ?: learnArtistPage(run, keys)
        if (base == null) {
            if (pasteProblem(run.db, keys, overrides) != null) return false
            return notOnArtistPage(run)
        }
        val listing = readArtistPage(run, base, ArtistRoute.ARTIST_PAGE_KINDS,
                                     Normalize.nameForms(Normalize.cleanTitle(run.song.title)))
        if (!listing.complete) return false
        if (listing.gone) {
            artistPageGone(run, keys, base)
            return notOnArtistPage(run)
        }
        val best = usableHits(run, listing.hits, listing.name)
        if (best.isEmpty()) return notOnArtistPage(run)
        markChecked(run)
        acceptArtistPageMatch(run, best, listing.name)
        return true
    }

    /**
     * `_artist_page_versions`: a matched song's entries in its artist's UG lists of [kinds] read as its versions, for
     * tabs the index can't watch (bare ids): every list of a song accepted on its artist's page, or the chords list of
     * a song whose index tabs hold no chords, [own] those tabs, whose pages teach the artist page first. The match
     * stands whatever the lists say. False when this run's page cap cut a list short; the check is recorded once the
     * lists are read, the song marked dirty first.
     */
    fun versions(run: SongRun, kinds: List<String>, own: List<IndexTab> = emptyList()): Boolean {
        Versions.updateSong(run.db, run.song.id, mapOf("ug_dirty" to true), now = run.stamp)
        val overrides = run.ctx.overrides
        val keys = matchedArtistKeys(run)
        readPastedTabPage(run, keys)
        val base = knownArtistPage(run.db, keys, overrides) ?: learnFromOwnTabs(run, own, keys)
            ?: learnArtistPage(run, keys)
        if (base != null) {
            val listing = readArtistPage(run, base, kinds, matchedTitleForms(run.song))
            if (!listing.complete) return false
            if (listing.gone) {
                artistPageGone(run, keys, base)
            } else {
                recordHits(run, usableHits(run, listing.hits, listing.name))
            }
        }
        markChecked(run)
        return true
    }

    /** `artist_is_known`: [ArtistRoute.artistIsKnown]. */
    fun artistIsKnown(db: Db, song: SongRow, overrides: Overrides): Boolean = ArtistRoute.artistIsKnown(db, song, overrides)

    // --- the page's address --------------------------------------------------------------------------------------

    private fun pastedKey(tabId: Long): String = "ug:pasted_tab:$tabId"

    /** `_pasted_record`: what reading the tab page at an `[artist_url]` address found, once read (`artist_url`, or
     * `problem`); null for an artist page or a tab page not read. */
    private fun pastedRecord(db: Db, url: String): JsonObject? {
        val tabId = OverrideUrls.pastedTabId(url) ?: return null
        return db.kvGetJson(pastedKey(tabId)) as? JsonObject
    }

    private fun text(record: JsonObject?, name: String): String? =
        (record?.get(name) as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { it.isNotEmpty() }

    /** `_pasted_page`: the artist page an `[artist_url]` address gives: itself, or the one the tab page there links
     * to, once that page is read. */
    private fun pastedPage(db: Db, url: String): String? {
        if (OverrideUrls.pastedTabId(url) == null) return url
        return text(pastedRecord(db, url), "artist_url")
    }

    /** `_known_artist_page`: the artist page you pasted under `[artist_url]` (or the one the tab page you pasted there
     * links to, once read), else one learned from a tab page. */
    fun knownArtistPage(db: Db, keys: List<String>, overrides: Overrides): String? {
        val entry = overrides.artistUrlEntry(keys)
        if (entry != null) pastedPage(db, entry.second)?.let { return it }
        for (key in keys) {
            UgLookup.learnedArtistUrl(db, key)?.takeIf { it.isNotEmpty() }?.let { return it }
        }
        return null
    }

    /** `_failed_paste`: your `[artist_url]` address for an artist with these keys and what is wrong with it, when it
     * is a tab page that reading showed leads to no artist page. */
    fun failedPaste(db: Db, keys: List<String>, overrides: Overrides): Pair<String, String>? {
        val entry = overrides.artistUrlEntry(keys) ?: return null
        val problem = text(pastedRecord(db, entry.second), "problem") ?: return null
        return entry.second to problem
    }

    /** `_unread_paste`: your `[artist_url]` tab page not read yet whose page won't parse, even fetched again, and when
     * caracole asks for it again (kv `ug:unreadable:<tab>`). */
    private fun unreadPaste(db: Db, keys: List<String>, overrides: Overrides): Pair<String, String>? {
        val entry = overrides.artistUrlEntry(keys) ?: return null
        val tabId = OverrideUrls.pastedTabId(entry.second) ?: return null
        if (pastedRecord(db, entry.second) != null) return null
        val until = text(db.kvGetJson(Pages.unreadableKey(tabId)) as? JsonObject, "until") ?: return null
        return entry.second to until
    }

    /** `_paste_problem`: the tab page you pasted and what is wrong with it: it leads to no artist page, or it
     * couldn't be read and when caracole asks for it again. */
    fun pasteProblem(db: Db, keys: List<String>, overrides: Overrides): Pair<String, String>? {
        failedPaste(db, keys, overrides)?.let { return it }
        val (url, until) = unreadPaste(db, keys, overrides) ?: return null
        return url to "${ArtistRoute.PASTE_UNREADABLE}; caracole asks for it again after ${until.take(10)}"
    }

    /**
     * `_read_pasted_tab_page`: the tab page you pasted under `[artist_url]` for the song's artist read once, for the
     * artist page it links to, and what it said remembered (kv `ug:pasted_tab:<tab>`). A request like any other; an
     * error leaves it to be read again, and a page that won't parse, even fetched again, is asked for again on the
     * tab-page rule's dates. A bare `/tab/{id}` of a slugged tab is read at the index's slugged path. The artist page
     * is filed under UG's names for the artist and under your entry's key; a page that gives none (gone, closed to
     * caracole, or linking nowhere) is remembered as such.
     */
    private fun readPastedTabPage(run: SongRun, keys: List<String>) {
        val (key, url) = run.ctx.overrides.artistUrlEntry(keys) ?: return
        val tabId = OverrideUrls.pastedTabId(url) ?: return
        if (pastedRecord(run.db, url) != null || Pages.waits(run, tabId)) return
        val target = if (Pages.sluggedUrl(url, tabId)) url else UgLookup.tabUrlFor(run.db, tabId)
        var artist: String? = null
        var problem: String? = ArtistRoute.PASTE_CLOSED  // unless read: robots.txt closes it, or where UG sends it
        if (!Pages.closed(target)) {
            var redirected = false  // RobotsClosed: UG sent it where robots.txt closes, neither gone nor read
            val page = try {
                Pages.getPage(run.ctx.client, target, Pages::tabPage).first
            } catch (e: RobotsClosed) {
                redirected = true
                null
            } catch (e: UnreadablePage) {
                Pages.noteUnreadable(run, tabId, e)
                return
            }
            if (!redirected) {
                run.db.kvDelete(Pages.unreadableKey(tabId))
                if (page == null) {
                    problem = ArtistRoute.PASTE_GONE
                } else {
                    artist = Pages.learnArtistUrl(run.db, page, listOf(key))
                    problem = if (artist == null) ArtistRoute.PASTE_NO_ARTIST else null
                }
            }
        }
        run.db.kvSetJson(pastedKey(tabId), JsonObject(linkedMapOf(
            "artist_url" to (artist?.let { JsonPrimitive(it) } ?: JsonNull),
            "problem" to (problem?.let { JsonPrimitive(it) } ?: JsonNull),
            "at" to JsonPrimitive(run.stamp),
        )))
    }

    /** `_learn_artist_page`: a slugged tab of the artist, from the index, read for the artist page it links to. The
     * tab is another song's, so none of its versions are recorded; a tab robots.txt closes, or UG redirects to where
     * it does, is passed over. */
    private fun learnArtistPage(run: SongRun, keys: List<String>): String? {
        for (key in keys) {
            for (tab in UgLookup.artistTabs(run.db, key, limit = ArtistRoute.LEARN_TRIES)) {
                val url = Ports.url(tab)
                if (Pages.closed(url)) continue
                val page = try {
                    Pages.getPage(run.ctx.client, url, Pages::tabPage).first
                } catch (e: RobotsClosed) {
                    continue
                }
                if (page != null) Pages.learnArtistUrl(run.db, page, listOf(key))?.let { return it }
            }
        }
        return null
    }

    /** `_learn_from_own_tabs`: the song's own slugged tabs, which its tab slot needs anyway, read for the artist
     * page. */
    private fun learnFromOwnTabs(run: SongRun, tabs: List<IndexTab>, keys: List<String>): String? {
        for (tab in tabs.take(ArtistRoute.LEARN_TRIES)) {
            val page = Pages.page(run, tab.tabId, Ports.url(tab), tab.type)
            if (page != null) knownArtistPage(run.db, keys, run.ctx.overrides)?.let { return it }
        }
        return null
    }

    // --- the lists -----------------------------------------------------------------------------------------------

    private fun artistPage(html: ByteArray, url: String): UgArtistPage = UgArtist.parse(html, url)

    /**
     * `_read_list`: the song's entries in the artist's list of [kind]; whether the list was read far enough (false
     * when this run's page cap stopped it); and the list's first page (null when UG answered 404). Lists are sorted
     * by title, so reading stops once the title's entries end, and goes on to the next page only when they reach the
     * end of this one. A page robots.txt closes, or UG redirects to where it does, ends the list, unread. Every page
     * read is kept for searches, and a list read to its end, an empty one (404) included, is every tab of its kind.
     */
    private fun readList(run: SongRun, base: String, kind: String, forms: List<String>): Triple<List<Hit>, Boolean, UgArtistPage?> {
        val ctx = run.ctx
        val hits = ArrayList<Hit>()
        var first: UgArtistPage? = null
        var fetched = 0
        var number = 1
        var last = 1
        val kept = ArrayList<Long>()
        var oldest: String? = null  // the earliest of the pages' reads
        var whole = false
        var broke = false
        while (number <= last) {
            if (fetched >= ctx.artistPagesPerKind) return Triple(hits, false, first)
            val url = UgArtist.pageUrl(base, kind = kind, page = number)
            if (Pages.closed(url)) {
                broke = true
                break
            }
            val (page, resp) = try {
                Pages.readPage(ctx.client, url, ::artistPage, maxAge = ctx.artistPageMaxAge, now = ctx.now)
            } catch (e: RobotsClosed) {
                broke = true
                break
            }
            val fresh = !resp.fromCache
            if (fresh) fetched += 1
            val readAt = resp.fetchedAt ?: run.stamp
            oldest = oldest?.let { if (readAt < it) readAt else it } ?: readAt
            if (page == null) {
                whole = number == 1  // an empty list may answer 404
                broke = true
                break
            }
            first = first ?: page
            last = maxOf(last, page.pages)
            val listed = page.tabs.filter { Ports.kind(it) == kind }
            Pages.checkLinks(run, listed, url)
            kept += ArtistTabs.store(run.db, base, page.name, listed, readAt)
            val found = listed.mapNotNull { titleHit(it, forms, fresh) }
            hits += found
            if (hits.isNotEmpty() && !(found.isNotEmpty() && found.last().tab === listed.last())) {
                whole = number >= last
                broke = true
                break
            }
            number += 1
        }
        if (!broke) whole = true
        if (whole && oldest != null) ArtistTabs.keepOnly(run.db, base, kind, kept, oldest)
        return Triple(hits, true, first)
    }

    /** `_offered_kinds`: the kinds of list the artist page offers, read from its unfiltered first page; null when it's
     * gone, and none when robots.txt closes it (or the page redirects to where it does). Its tabs, every kind mixed,
     * are kept for searches, never as all of a kind's. */
    private fun offeredKinds(run: SongRun, base: String): Set<String>? {
        val url = UgArtist.pageUrl(base)
        if (Pages.closed(url)) return emptySet()
        val (page, resp) = try {
            Pages.readPage(run.ctx.client, url, ::artistPage, maxAge = run.ctx.artistPageMaxAge, now = run.ctx.now)
        } catch (e: RobotsClosed) {
            return emptySet()
        }
        if (page == null) return null
        ArtistTabs.store(run.db, base, page.name, page.tabs, resp.fetchedAt ?: run.stamp)
        return page.filters.ifEmpty { ArtistRoute.ARTIST_PAGE_KINDS.toSet() }
    }

    /** `_read_artist_page`: the song's entries in the artist's lists of [kinds], read in order. The first list read
     * tells, from its filter bar, which of the others the artist has; an empty list may answer 404, so the unfiltered
     * page tells then, and a 404 there too means the page is gone. */
    private fun readArtistPage(run: SongRun, base: String, kinds: List<String>, forms: List<String>): Listing {
        val listing = Listing()
        var offered: Set<String>? = null
        for (kind in kinds) {
            if (offered != null && kind !in offered) continue
            val (found, complete, first) = readList(run, base, kind, forms)
            if (!complete) {
                listing.complete = false
                return listing
            }
            if (first != null) {
                if (listing.name.isEmpty()) listing.name = first.name
                if (offered == null && first.filters.isNotEmpty()) offered = first.filters
            } else if (offered == null) {
                offered = offeredKinds(run, base)
                if (offered == null) {
                    listing.gone = true
                    return listing
                }
            }
            listing.hits += found
        }
        return listing
    }

    /** `_artist_page_gone`: UG answered 404 for the artist page: the address learned for it forgotten, and what it
     * listed, which a search no longer finds. */
    private fun artistPageGone(run: SongRun, keys: List<String>, base: String) {
        for (key in keys) {
            if (UgLookup.learnedArtistUrl(run.db, key) == base) UgLookup.forgetArtistUrl(run.db, key)
        }
        ArtistTabs.forget(run.db, base)
    }

    // --- titles ----------------------------------------------------------------------------------------------------

    /** `_title_score`: 100 for the same title (in either script, in pinyin, or once hyphens go), else rapidfuzz's
     * ratio. */
    fun titleScore(forms: List<String>, listed: List<String>): Double {
        var best = 0.0
        for (a in forms) {
            for (b in listed) {
                if (a == b || Normalize.compact(a) == Normalize.compact(b)) return 100.0
                best = maxOf(best, Fuzz.ratio(a, b))
            }
        }
        return best
    }

    /** `_title_hit`: the tab as a hit of the song's title [forms], or null. */
    fun titleHit(tab: UgVersion, forms: List<String>, fresh: Boolean): Hit? {
        val listed = Normalize.listingForms(Normalize.cleanTitle(tab.songName))
        if (listed.isEmpty() || forms.isEmpty()) return null
        val score = titleScore(forms, listed)
        return if (score >= ArtistRoute.TITLE_MATCH) Hit(tab, listed[0], score, fresh) else null
    }

    /** `_best_title`: the hits of the song's title: every exact one, else the best fuzzy title when it leads the next
     * different one by [ArtistRoute.TITLE_MARGIN]. */
    fun bestTitle(hits: List<Hit>): List<Hit> {
        val exact = hits.filter { it.score >= 100 }
        if (exact.isNotEmpty() || hits.isEmpty()) return exact
        val scores = LinkedHashMap<String, Double>()
        for (h in hits) scores[h.key] = maxOf(scores[h.key] ?: 0.0, h.score)
        val ranked = scores.entries.sortedByDescending { it.value }  // stable, as Python's sorted
        val (key, best) = ranked[0]
        if (ranked.size > 1 && best - ranked[1].value < ArtistRoute.TITLE_MARGIN) return emptyList()
        return hits.filter { it.key == key }
    }

    /** `_listed_keys`: the UG keys of a tab on an artist page: the page's artist and the tab's title, as the match a
     * hit makes stores them, and as `[reject]` names them. */
    private fun listedKeys(run: SongRun, tab: UgVersion, artistName: String): Pair<String, String> {
        val artistKey = Normalize.slugKey(artistName).ifEmpty { Normalize.slugKey(tab.artistName) }.ifEmpty { run.artistKey }
        val songKey = Normalize.slugKey(Normalize.cleanTitle(tab.songName))
            .ifEmpty { Normalize.slugKey(Normalize.cleanTitle(run.song.title)) }
        return artistKey to songKey
    }

    /** `_usable_hits`: the hits of the song's title caracole may use, a UG song you rejected for the song dropped
     * first (never hiding the page's other titles). */
    private fun usableHits(run: SongRun, hits: List<Hit>, artistName: String): List<Hit> {
        val rejected = run.ctx.overrides.reject[run.song.key].orEmpty()
        val allowed = hits.filter { listedKeys(run, it.tab, artistName) !in rejected }
        return bestTitle(allowed).filter { Pages.usable(run, it.tab) }
    }

    /** `_record_hits`: listed tabs recorded as the song's versions; only a list read from UG this run updates
     * ratings. */
    private fun recordHits(run: SongRun, hits: List<Hit>) {
        Pages.record(run, hits.filter { it.fresh }.map { it.tab }, fresh = true)
        Pages.record(run, hits.filter { !it.fresh }.map { it.tab }, fresh = false)
    }

    /** `_accept_artist_page_match`: the matching tabs recorded as the song's versions, and the match (step
     * `artist_page`). */
    private fun acceptArtistPageMatch(run: SongRun, hits: List<Hit>, artistName: String) {
        recordHits(run, hits)
        val best = hits.maxByOrNull { it.score }!!
        val (artistKey, songKey) = listedKeys(run, best.tab, artistName)
        Versions.updateSong(run.db, run.song.id, linkedMapOf(
            "match_decision" to "accept", "match_step" to Match.ARTIST_PAGE, "match_score" to best.score,
            "match_artist_key" to artistKey, "match_song_key" to songKey, "review" to false,
            "matched_at" to run.stamp,
            "match_candidates" to listOf(linkedMapOf<String, Any?>("artist_key" to artistKey, "song_key" to songKey,
                                                                   "score" to best.score, "step" to Match.ARTIST_PAGE)),
            "ug_dirty" to true,
        ), now = run.stamp)
        run.song = Songs.byId(run.db, run.song.id)!!
    }

    // --- the check ---------------------------------------------------------------------------------------------------

    private fun markChecked(run: SongRun) = run.db.kvSet("ug:artist_page_checked:${run.song.id}", run.stamp)

    /** `_not_on_artist_page`: the artist's page settled it for now: the song isn't there. The check recorded, and an
     * undone match's files dropped. False. */
    private fun notOnArtistPage(run: SongRun): Boolean {
        markChecked(run)
        SongFetch.dropUndone(run)
        return false
    }

    /** `_matched_artist_keys`: the UG artist keys of a matched song: its match's first, then its own artists'. */
    private fun matchedArtistKeys(run: SongRun): List<String> =
        LinkedHashSet(listOf(run.song.matchArtistKey.orEmpty()) + ArtistRoute.artistKeys(run.song, run.ctx.overrides))
            .filter { it.isNotEmpty() }

    /** `_matched_title_forms`: the keys a matched song's title may be listed under: its own title's, then its
     * match's. */
    private fun matchedTitleForms(song: SongRow): List<String> =
        LinkedHashSet(Normalize.nameForms(Normalize.cleanTitle(song.title)) + song.matchSongKey.orEmpty())
            .filter { it.isNotEmpty() }
}
