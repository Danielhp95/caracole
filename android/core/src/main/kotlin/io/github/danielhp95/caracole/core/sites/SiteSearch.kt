package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.GameTabHit
import io.github.danielhp95.caracole.core.search.HarpTabHit
import io.github.danielhp95.caracole.core.search.Queries
import io.github.danielhp95.caracole.core.search.Query
import io.github.danielhp95.caracole.core.search.Reading
import io.github.danielhp95.caracole.core.search.Readings
import io.github.danielhp95.caracole.core.search.SearchLimits.ARTIST_ROWS
import io.github.danielhp95.caracole.core.search.SearchLimits.MIN_SCORE
import io.github.danielhp95.caracole.core.search.SearchLimits.PART
import io.github.danielhp95.caracole.core.search.SearchLimits.SITE_ROWS
import io.github.danielhp95.caracole.core.search.SearchLimits.SITE_ROWS_READ
import io.github.danielhp95.caracole.core.search.SearchLimits.STRONG
import io.github.danielhp95.caracole.core.search.SearchLimits.TOP_SONGS
import io.github.danielhp95.caracole.core.search.SearchLimits.WORD_ARTISTS
import io.github.danielhp95.caracole.core.search.SearchLimits.WORD_LETTERS
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit

/**
 * search.py's other sites on the phone: gtptabs.com's, MuseScore's, harptabs.com's and gametabs.net's indexes,
 * searched as search.py searches them (its lines on `search_gtptabs` … `_title_pages` and `_known_song`), over the
 * same tables, with the same SQL: every query whose rows' order reaches an answer is ordered by stable keys
 * (tests/test_search_determinism.py), so the phone answers what the computer does. Scores go through core.search's
 * Query, as search.py's through its `_Query`; a score is rounded as Python's round(x, 1) rounds it, names sort by code
 * point, and what Python keeps in a dict keeps its order here. tests/conformance/vectors/search/sites.jsonl holds it
 * to Python's answers (SiteSearchTest). It reads the tables alone: nothing is asked of any site.
 */
object SiteSearch {
    // --- gtptabs.com ---------------------------------------------------------------------------------------------

    /**
     * gtptabs.com's song pages that match [q], best first, by any reading, as the index's songs are scored; a title's
     * uploads under one artist ("-2", "-3") are one hit, on its first upload's page. Ties go to the title uploaded
     * more often. The artist is named as Ultimate Guitar's index names them, the title from its slug.
     */
    fun searchGtptabs(db: Db, q: String, limit: Int = SITE_ROWS): List<SiteHit> {
        val patterns = Queries.patterns(Normalize.nameWords(q))
        if (patterns.isEmpty()) return emptyList()
        val queries = Queries.of(q)
        // The page's path holds the artist's slug and the title's, whose words the keys are made of.
        val where = patterns.joinToString(" OR ") { "path LIKE ?" }
        val groups = LinkedHashMap<Pair<String, String>, MutableList<Pair<Boolean, String>>>()
        db.query(
            "SELECT path, artist_key, title_key, base_key FROM gtptabs_index WHERE title_key != '' AND ($where) " +
                "ORDER BY path LIMIT ?", *patterns.toTypedArray(), SITE_ROWS_READ,
        ) { Gtp(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!) }.forEach { row ->
            groups.getOrPut(row.artistKey to row.base) { ArrayList() }.add((row.titleKey != row.base) to row.path)
        }
        class Scored(val score: Double, val uploads: Int, val artistKey: String, val base: String, val path: String,
                     val via: String)
        val scored = ArrayList<Scored>()
        for ((key, pages) in groups) {
            val (artistKey, base) = key
            val reading = Queries.reading(queries.map { it.readings(artistKey.replace("-", " "), base.replace("-", " ")) })
            if (reading.score >= MIN_SCORE) {
                val first = pages.minWith(
                    compareBy<Pair<Boolean, String>> { it.first }.thenComparing({ it.second }, Py.CODE_POINT_ORDER),
                )
                scored.add(Scored(reading.score, pages.size, artistKey, base, first.second, reading.via))
            }
        }
        val ordered = scored.sortedWith(
            compareBy<Scored>({ -it.score }, { -it.uploads })
                .thenComparing({ it.artistKey }, Py.CODE_POINT_ORDER).thenComparing({ it.base }, Py.CODE_POINT_ORDER),
        )
        val names = HashMap<String, String>()
        return ordered.take(maxOf(limit, 0)).map { s ->
            val name = names.getOrPut(s.artistKey) { gtptabsArtist(db, s.artistKey) }
            SiteHit("gtptabs", SiteText.titleWords(s.base), GtpTabs.pageUrl(s.path), Py.round(s.score, 1), name,
                    s.artistKey, s.base, s.uploads, s.via)
        }
    }

    private class Gtp(val path: String, val artistKey: String, val titleKey: String, val base: String)

    /** A gtptabs.com artist's name: as Ultimate Guitar's slugs write it, under the key or the key with its first word
     * last (gtptabs.com files people last name first: "Elton John" is `john-elton`), else from the key as it is. */
    private fun gtptabsArtist(db: Db, artistKey: String): String {
        val words = artistKey.split("-")
        for (key in LinkedHashSet(listOf(artistKey, (words.drop(1) + words.take(1)).joinToString("-")))) {
            val path = db.one("SELECT path FROM ug_index WHERE artist_key = ? AND path != '' ORDER BY song_key, tab_id " +
                                  "LIMIT 1", key) { it.text(0)!! } ?: continue
            val slug = path.substringBefore('/')
            if (slug.isNotEmpty()) return SiteText.titleWords(slug)
        }
        return SiteText.titleWords(artistKey)
    }

    /**
     * How many songs gtptabs.com's index lists by [artist]: the song pages under the keys of the name's forms, each
     * also with its last word first, as the site files people; a title's uploads ("-2", "-3") one song, an artist's
     * page none. By the table's artist index alone.
     */
    fun gtptabsSongs(db: Db, artist: String): Int {
        val keys = gtptabsKeys(artist)
        if (keys.isEmpty()) return 0
        return db.one("SELECT COUNT(DISTINCT base_key) FROM gtptabs_index WHERE artist_key IN " +
                          "(${keys.joinToString(", ") { "?" }}) AND title_key != ''", *keys.toTypedArray()) {
            it.long(0)!!.toInt()
        }!!
    }

    /** The artist keys gtptabs.com may file a name under: the keys of its forms, each also with its last word first;
     * none of no one's, nor a placeholder's. */
    private fun gtptabsKeys(artist: String): List<String> {
        val keys = LinkedHashSet<String>()
        for (form in Normalize.nameForms(artist)) {
            if (form.isNotEmpty() && !SiteText.noOnes(form) && !Normalize.placeholderArtist(form)) {
                keys.addAll(SiteText.gtptabsFiled(form))
            }
        }
        return keys.toList()
    }

    // --- MuseScore -----------------------------------------------------------------------------------------------

    /**
     * MuseScore's song pages whose title is the query, or the query with an artist's name on either side: the
     * sitemaps give titles alone, so each is a possible match, a run of the query's words a title only when the rest
     * names the artist of a song by that title that an index or your library has. The whole query first, then the
     * longer titles; a title's pages oldest first.
     */
    fun searchMusescore(db: Db, q: String, limit: Int = SITE_ROWS): List<SiteHit> =
        titlePages(db, q, limit, "musescore", MuseScore::titleKey) { key, n ->
            db.query("SELECT page_id, path, title_key FROM musescore_index WHERE title_key = ? ORDER BY page_id LIMIT ?",
                     key, n) { MuseScore.pageUrl(it.text(1)!!) }
        }

    /** search.py `_title_pages`: a site's pages by title alone ([pages] gives their addresses), whose title is the query
     * or the query less an artist's name on either side, that artist having a song of that title in the Ultimate
     * Guitar index, gtptabs.com's or your library. The whole query first, then the longer titles. */
    private fun titlePages(db: Db, q: String, limit: Int, source: String, titleKey: (String) -> String,
                           pages: (String, Int) -> List<String>): List<SiteHit> {
        val words = Normalize.nameWords(q)
        val runs = ArrayList<Pair<List<String>, List<String>>>()
        runs.add(words to emptyList())
        for (n in words.size - 1 downTo 1) runs.add(words.subList(0, n) to words.subList(n, words.size))
        for (n in words.size - 1 downTo 1) {
            runs.add(words.subList(words.size - n, words.size) to words.subList(0, words.size - n))
        }
        val sorted = runs.sortedBy { -it.first.size } // stable: the whole query, then each length's start before its end
        val hits = ArrayList<SiteHit>()
        val seen = HashSet<String>()
        val mine = SiteText.Mine()
        for ((run, rest) in sorted) {
            val text = run.joinToString(" ")
            val keys = listOf(titleKey(text), if (Normalize.hasHan(text)) titleKey(Normalize.romanize(text)) else "")
            for (key in keys) { // its slugs are ASCII
                if (key.isEmpty() || key in seen) continue
                val urls = pages(key, maxOf(limit, 0))
                if (urls.isEmpty()) continue
                if (rest.isNotEmpty() && !SiteText.knownSong(db, rest.joinToString(" "), key, mine)) continue
                seen.add(key)
                for (url in urls) {
                    hits.add(SiteHit(source, SiteText.titleWords(key), url, 100.0, titleKey = key,
                                     via = if (rest.isNotEmpty()) "both" else "title"))
                }
            }
            if (hits.size >= limit) break
        }
        return hits.take(maxOf(limit, 0))
    }

    // --- gametabs.net --------------------------------------------------------------------------------------------

    /**
     * gametabs.net's tracks in its index that match [q], best first, by any reading: a track of a game a hit, the
     * game as its artist, the game's name or a composer of its tabs (by the game pages caracole read) as its artist's
     * names; its tabs the most viewed first, its url the first's. Ties go to the most viewed. The game is named as its
     * page heads it once caracole read it, else from its slug, and the track as a card writes it, else from its slug.
     */
    fun searchGametabs(db: Db, q: String, limit: Int = SITE_ROWS): List<SiteHit> {
        val patterns = Queries.patterns(Normalize.nameWords(q))
        val queries = Queries.of(q)
        if (patterns.isEmpty() || queries.isEmpty()) return emptyList()
        val paths = gametabsPaths(db, patterns)
        if (paths.isEmpty()) return emptyList()
        val (tracks, names) = gametabsTracks(db, paths)
        class Scored(val score: Double, val views: Int, val name: String, val key: String, val game: String,
                     val tabs: MutableList<GameTab>, val via: String)
        val scored = ArrayList<Scored>()
        for ((track, tabs) in tracks) {
            val (game, key) = track
            val name = names[game]?.ifEmpty { null } ?: SiteText.titleWords(game.replace("_", "-"))
            val reading = gametabsReading(queries, name, game, key, tabs)
            if (reading.score >= MIN_SCORE) {
                val views = tabs.filter { it.listed != null }.maxOfOrNull { it.views } ?: 0
                scored.add(Scored(Py.round(reading.score, 1), views, name, key, game, tabs, reading.via))
            }
        }
        val ordered = scored.sortedWith(
            compareBy<Scored>({ -it.score }, { -it.views })
                .thenComparing({ it.name }, Py.CODE_POINT_ORDER).thenComparing({ it.key }, Py.CODE_POINT_ORDER),
        )
        return ordered.take(maxOf(limit, 0)).map { gametabsHit(it.score, it.name, it.key, it.game, it.tabs, it.via) }
    }

    /** A game page's row of a tab: its title, views, rating, instruments and composers. */
    private class Listed(val title: String, val views: Int, val rating: Double?, val instruments: String?,
                         val composers: String?)

    /** A tab of a track, as [searchGametabs] reads it: its page's path, its title as its game's page lists it (null
     * before caracole read that page), and that page's row of it ([listed], null before). */
    private class GameTab(val path: String, val title: String?, val listed: Listed?) {
        val views: Int get() = listed?.views ?: 0

        /** The tab as a track's hit lists it, under the track's [track] title when its game's page lists none. */
        fun hit(track: String): GameTabHit {
            val shown = title?.ifEmpty { null } ?: track
            if (listed == null) return GameTabHit(shown, GameTabs.pageUrl(path))
            return GameTabHit(shown, GameTabs.pageUrl(path), listed.views, listed.rating,
                              SiteText.listedNames(listed.instruments), SiteText.listedNames(listed.composers))
        }
    }

    /** The tab pages a query's patterns find, in their paths' order: by their paths (the game's slug and the
     * track's), and by the composers the game pages caracole read name. */
    private fun gametabsPaths(db: Db, patterns: List<String>): List<String> {
        val paths = HashSet<String>()
        paths.addAll(db.query(
            "SELECT path FROM gametabs_index WHERE kind = ? AND (${patterns.joinToString(" OR ") { "path LIKE ?" }}) " +
                "ORDER BY path LIMIT ?", GameTabs.TAB, *patterns.toTypedArray(), SITE_ROWS_READ,
        ) { it.text(0)!! })
        paths.addAll(db.query(
            "SELECT path FROM gametabs_game_tabs WHERE ${patterns.joinToString(" OR ") { "composers LIKE ?" }} " +
                "ORDER BY +path LIMIT ?", *patterns.toTypedArray(), SITE_ROWS_READ,
        ) { it.text(0)!! })
        return paths.sortedWith(Py.CODE_POINT_ORDER)
    }

    /** The tabs of [paths] by track, a game's slug and a title's key (the title its game's page lists, else the
     * sitemap's key; a tab with neither is none), in the order of [paths], and the names of their games as their
     * pages head them. A tab two of a game's pages list is the last page's, by their numbers. */
    private fun gametabsTracks(
        db: Db, paths: List<String>,
    ): Pair<LinkedHashMap<Pair<String, String>, MutableList<GameTab>>, Map<String, String>> {
        val marks = paths.joinToString(", ") { "?" }
        val listed = HashMap<String, Listed>()
        db.query(
            "SELECT path, title, views, rating, instruments, composers FROM gametabs_game_tabs WHERE path IN ($marks) " +
                "ORDER BY path, length(page), page", *paths.toTypedArray(),
        ) { it.text(0)!! to Listed(it.text(1)!!, it.long(2)!!.toInt(), it.double(3), it.text(4), it.text(5)) }
            .forEach { (path, row) -> listed[path] = row }
        val keyed = HashMap<String, Pair<String, String>>()
        db.query("SELECT path, game, key FROM gametabs_index WHERE kind = ? AND path IN ($marks)",
                 GameTabs.TAB, *paths.toTypedArray()) { Triple(it.text(0)!!, it.text(1)!!, it.text(2)!!) }
            .forEach { (path, game, key) -> keyed[path] = game to key }
        val games = LinkedHashSet<String>()
        keyed.values.forEach { games.add(it.first) }
        listed.keys.forEach { games.add(it.split("/")[1]) }
        val names = HashMap<String, String>()
        if (games.isNotEmpty()) {
            db.query("SELECT game, name FROM gametabs_games WHERE name != '' AND game IN " +
                         "(${games.joinToString(", ") { "?" }}) ORDER BY path", *games.toTypedArray()) {
                it.text(0)!! to it.text(1)!!
            }.forEach { (game, name) -> names[game] = name }
        }
        val tracks = LinkedHashMap<Pair<String, String>, MutableList<GameTab>>()
        for (path in paths) {
            val game = path.split("/")[1]
            val row = listed[path]
            val title = row?.title
            val key = if (!title.isNullOrEmpty()) GameTabs.titleKey(title) else keyed[path]?.second ?: ""
            if (key.isNotEmpty()) tracks.getOrPut(game to key) { ArrayList() }.add(GameTab(path, title, row))
        }
        return tracks to names
    }

    /** A track's best reading of the query: its title, under its game's name, its game's slug or a composer of its
     * tabs as its artist's. */
    private fun gametabsReading(queries: List<Query>, name: String, game: String, key: String,
                                tabs: List<GameTab>): Reading {
        val composers = LinkedHashSet<String>()
        for (tab in tabs) composers.addAll(SiteText.listedNames(tab.listed?.composers))
        val artists = LinkedHashSet<String>()
        artists.add(Normalize.nameWords(name).joinToString(" "))
        artists.add(game.replace('-', ' ').replace('_', ' ')) // re.sub(r"[-_]", " ", game)
        for (c in composers) artists.add(Normalize.nameWords(c).joinToString(" "))
        val title = key.replace("-", " ")
        val scores = ArrayList<Readings>()
        for (q in queries) for (a in artists) if (a.isNotEmpty()) scores.add(q.readings(a, title))
        return Queries.reading(scores)
    }

    /** A track as [searchGametabs] gives it: its tabs the most viewed first, its title the first a game's page lists,
     * else from its key, the game's [name] as its artist. */
    private fun gametabsHit(score: Double, name: String, key: String, game: String, tabs: MutableList<GameTab>,
                            via: String): SiteHit {
        tabs.sortWith(compareBy<GameTab> { -it.views }.thenComparing({ it.path }, Py.CODE_POINT_ORDER))
        val title = tabs.firstNotNullOfOrNull { it.title?.ifEmpty { null } } ?: SiteText.titleWords(key)
        return SiteHit("gametabs", title, GameTabs.pageUrl(tabs[0].path), score, artist = name,
                       artistKey = Normalize.identityKey(name, "").substringBefore('/'), titleKey = key,
                       uploads = tabs.size, via = via, tabs = tabs.map { it.hit(title) }, page = game)
    }

    // --- harptabs.com --------------------------------------------------------------------------------------------

    /**
     * harptabs.com's artists and songs in its index that match [q], as the Ultimate Guitar index answers it: the
     * artists the query names whole ([STRONG] or more) or by a word of their name ([PART]), beside one named whole only
     * those named whole or in part; then the songs of the artist pages caracole read, by any reading, best first (a
     * song only its artist's name matched is in that artist's row), at most [songs]; then, at most [songs] more, the
     * sitemap's tabs whose artist no page read names, whose title is the query or the query less an artist's name,
     * possible matches.
     */
    fun searchHarptabs(
        db: Db, q: String, songs: Int = SITE_ROWS, artists: Int = ARTIST_ROWS,
    ): Pair<List<SiteArtist>, List<SiteHit>> {
        val queries = Queries.of(q)
        val patterns = Queries.patterns(Normalize.nameWords(q))
        var named: List<SiteArtist> = emptyList()
        var hits: List<SiteHit> = emptyList()
        if (queries.isNotEmpty() && patterns.isNotEmpty()) {
            named = harpArtists(db, q, queries, patterns, artists)
            val theirs = named.map { it.slug }.toSet()
            hits = harpSongs(db, queries, patterns).filter { !(it.via == "artist" && it.page in theirs) }
        }
        // Its tabs' keys join a contraction's end to its word (harptabs.joined), and a row keyed before has the key as
        // it is, until the next harptabs.com pass keys it again (SiteKeys.harptabsEnsureCurrentKeys).
        val byTitle = titlePages(db, q, songs, "harptabs", HarpTabs::titleKey) { key, n ->
            val keys = LinkedHashSet(listOf(HarpTabs.joined(key), key)).toList()
            db.query(
                "SELECT path FROM harptabs_index i WHERE kind = ? AND key IN (${keys.joinToString(", ") { "?" }}) AND NOT " +
                    "EXISTS (SELECT 1 FROM harptabs_artist_tabs t WHERE t.tab_id = i.page_id) ORDER BY page_id, path LIMIT ?",
                HarpTabs.TAB, *keys.toTypedArray(), n,
            ) { HarpTabs.pageUrl(it.text(0)!!) }
        }
        return named to hits.take(maxOf(songs, 0)) + byTitle
    }

    /** One artist of harptabs.com's index, by their page's path, as [searchHarptabs] gives them (score 100); null for
     * one its sitemap doesn't list, or whose page is gone. */
    fun harptabsArtist(db: Db, path: String): SiteArtist? {
        val row = db.one("$HARP_ARTISTS WHERE i.path = ? AND i.kind = 'artist'", path) { harpArtist(it) }
        return if (row != null && !row.gone) harpArtistHit(db, row, 100.0) else null
    }

    /** The songs harptabs.com's index holds of an artist (their page's path), most viewed first: none until caracole
     * has read their page. With [title], only those whose title it matches, best first. */
    fun harptabsSongs(db: Db, path: String, title: String? = null): List<SiteHit> =
        SiteText.titledOnly(harpGrouped(db, "t.artist = ?", listOf(path)), title)

    // harptabs.com's artist rows (i), with what their page said once read (a): a HarpArtist a row, each query adding
    // its WHERE.
    private const val HARP_ARTISTS = "SELECT i.path, i.page_id, i.key, a.name, a.tabs, a.read_at FROM harptabs_index i " +
        "LEFT JOIN harptabs_artists a ON a.path = i.path"

    /** An artist row of harptabs.com's index, with what their page said once read ([name] "" or null before, and for
     * a page gone). */
    private class HarpArtist(val path: String, val pageId: Long, val key: String, val name: String?, val tabs: Long?,
                             val readAt: String?) {
        val shown: String get() = name?.ifEmpty { null } ?: SiteText.titleWords(key)

        /** Whether caracole read their page and it was gone: a page gone names no one. */
        val gone: Boolean get() = readAt != null && name.isNullOrEmpty()

        /** The name's words to score: the slug's key, and the page's name once read. */
        fun forms(): List<String> {
            val forms = LinkedHashSet<String>()
            forms.add(key.replace("-", " "))
            if (!name.isNullOrEmpty()) forms.add(Normalize.nameWords(name).joinToString(" "))
            return forms.filter { it.isNotEmpty() }
        }
    }

    private fun harpArtist(r: Row) = HarpArtist(r.text(0)!!, r.long(1)!!, r.text(2)!!, r.text(3), r.long(4), r.text(5))

    /** The artists the query names: as their whole name, scored, else by words of their name among others ([PART]),
     * unless more than [WORD_ARTISTS] names hold them; beside one named whole, only those named whole or in part. */
    private fun harpArtists(db: Db, q: String, queries: List<Query>, patterns: List<String>, limit: Int): List<SiteArtist> {
        val where = patterns.joinToString(" OR ") { "i.key LIKE ?" }
        val rows = db.query("$HARP_ARTISTS WHERE i.kind = 'artist' AND ($where) ORDER BY i.key, i.path LIMIT ?",
                            *patterns.toTypedArray(), SITE_ROWS_READ) { harpArtist(it) }
        val (whole, parts) = harpNamed(rows.filter { !it.gone }, q, queries)
        class Found(val score: Double, val part: Boolean, val row: HarpArtist)
        var found = whole.map { Found(it.first, false, it.second) } + parts.map { Found(PART, true, it) }
        if (found.any { it.score >= 100 }) found = found.filter { it.score >= 100 || it.part }
        val known = harpKnown(db, found.map { it.row.path })
        val ordered = found.sortedWith(compareBy<Found>({ -it.score }, { -(known[it.row.path] ?: 0) },
                                                        { -(it.row.tabs ?: 0L) }, { it.row.pageId }))
        return ordered.take(maxOf(limit, 0)).map { harpArtistHit(db, it.row, it.score, it.part, known[it.row.path] ?: 0) }
    }

    /** Of [rows], the artists the query names as their whole name ([STRONG] or more), each with its score, and those
     * whose names hold its words among others, none when more than [WORD_ARTISTS] do. */
    private fun harpNamed(
        rows: List<HarpArtist>, q: String, queries: List<Query>,
    ): Pair<List<Pair<Double, HarpArtist>>, List<HarpArtist>> {
        val words = Normalize.nameWords(q).toSet()
        val whole = ArrayList<Pair<Double, HarpArtist>>()
        var parts = ArrayList<HarpArtist>()
        for (row in rows) {
            val forms = row.forms()
            val score = queries.flatMap { query -> forms.map { query.name(it) } }.max()
            if (score >= STRONG) {
                whole.add(Py.round(score, 1) to row)
            } else if (words.all { Py.len(it) >= WORD_LETTERS } && forms.any { Py.split(it).toSet().containsAll(words) }) {
                parts.add(row)
            }
        }
        if (parts.size > WORD_ARTISTS) parts = ArrayList() // a common word ("band", "john") names no one in part
        return whole to parts
    }

    /** How many tabs the index holds of each artist (their page's path). */
    private fun harpKnown(db: Db, paths: List<String>): Map<String, Int> {
        if (paths.isEmpty()) return emptyMap()
        val out = HashMap<String, Int>()
        db.query("SELECT artist, COUNT(*) FROM harptabs_artist_tabs WHERE artist IN (${paths.joinToString(", ") { "?" }}) " +
                     "GROUP BY artist", *paths.toTypedArray()) { it.text(0)!! to it.long(1)!!.toInt() }
            .forEach { (artist, n) -> out[artist] = n }
        return out
    }

    /** An artist row as a SiteArtist, with their [TOP_SONGS] most viewed songs. */
    private fun harpArtistHit(db: Db, row: HarpArtist, score: Double, part: Boolean = false, known: Int? = null): SiteArtist {
        val held = known ?: (harpKnown(db, listOf(row.path))[row.path] ?: 0)
        val top = if (held != 0) harpGrouped(db, "t.artist = ?", listOf(row.path)).take(TOP_SONGS) else emptyList()
        return SiteArtist("harptabs", row.shown, row.path, HarpTabs.pageUrl(row.path), score,
                          songs = (row.tabs ?: 0L).toInt(), known = held, top = top, part = part, read = row.readAt != null)
    }

    /** The songs of the artist pages read that the query matches by any reading, best first, then most viewed. */
    private fun harpSongs(db: Db, queries: List<Query>, patterns: List<String>): List<SiteHit> {
        val where = patterns.joinToString(" OR ") { "t.song_key LIKE ? OR a.key LIKE ?" }
        val hits = harpGrouped(db, where, patterns.flatMap { listOf(it, it) }, SITE_ROWS_READ)
        val pages = hits.map { it.page }.toSet().sortedWith(Py.CODE_POINT_ORDER)
        val slugs = HashMap<String, String>()
        if (pages.isNotEmpty()) {
            db.query("SELECT path, key FROM harptabs_artists WHERE path IN (${pages.joinToString(", ") { "?" }})",
                     *pages.toTypedArray()) { it.text(0)!! to it.text(1)!! }.forEach { (path, key) -> slugs[path] = key }
        }
        class Scored(val score: Double, val n: Int, val hit: SiteHit)
        val scored = ArrayList<Scored>()
        hits.forEachIndexed { n, hit ->
            val title = hit.titleKey.replace("-", " ")
            val names = LinkedHashSet(listOf((slugs[hit.page] ?: "").replace("-", " ") to title,
                                             Normalize.nameWords(hit.artist).joinToString(" ") to title))
            val reading = Queries.reading(queries.flatMap { query -> names.map { (a, t) -> query.readings(a, t) } })
            if (reading.score >= MIN_SCORE) {
                val score = Py.round(reading.score, 1)
                scored.add(Scored(score, n, hit.copy(score = score, via = reading.via)))
            }
        }
        return scored.sortedWith(compareBy<Scored>({ -it.score }, { it.n })).map { it.hit }
    }

    /** The tabs of the artist pages read that [where] keeps (t, the tab; a, its artist), a song a hit: the tabs of one
     * title by one artist, the most viewed first; the songs most viewed first. */
    private fun harpGrouped(db: Db, where: String, args: List<Any?>, limit: Int? = null): List<SiteHit> {
        val rows = db.query(
            "SELECT t.artist, t.path, t.title, t.song_key, t.views, t.rating, t.harp_key, t.difficulty, a.name " +
                "FROM harptabs_artist_tabs t JOIN harptabs_artists a ON a.path = t.artist " +
                "WHERE $where ORDER BY t.views DESC, t.place, t.artist, t.tab_id" + (if (limit != null) " LIMIT ?" else ""),
            *(if (limit != null) args + limit else args).toTypedArray(),
        ) {
            HarpTab(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.long(4)!!.toInt(), it.double(5), it.text(6),
                    it.text(7), it.text(8)!!)
        }
        val songs = LinkedHashMap<Pair<String, String>, MutableList<HarpTab>>()
        for (row in rows) songs.getOrPut(row.artist to row.songKey) { ArrayList() }.add(row)
        return songs.map { (song, tabs) ->
            val (page, key) = song
            val best = tabs[0]
            SiteHit("harptabs", HarpTabs.songTitle(best.title), HarpTabs.pageUrl(best.path), 100.0, artist = best.name,
                    artistKey = Normalize.identityKey(best.name, "").substringBefore('/'), titleKey = key,
                    uploads = tabs.size, via = "title",
                    tabs = tabs.map {
                        HarpTabHit(it.title, HarpTabs.pageUrl(it.path), it.views, it.rating, it.harpKey, it.difficulty)
                    },
                    page = page)
        }
    }

    private class HarpTab(val artist: String, val path: String, val title: String, val songKey: String, val views: Int,
                          val rating: Double?, val harpKey: String?, val difficulty: String?, val name: String)
}
