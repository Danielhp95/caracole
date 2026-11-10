package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.sites.SiteText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * lacuerda_index.py's read side and search.py's LaCuerda glue on the phone: LaCuerda's artists and songs in the local
 * index, searched as the computer searches them (`find`, its own `_Query`, `_rows_like`'s SQL as it is), what a search
 * says of an index read in part, and the keys made again from the names it stores. It reads the tables alone and asks
 * LaCuerda nothing. tests/conformance/vectors/search/lacuerda.jsonl holds it to Python's answers (LaCuerdaTest).
 *
 * `lacuerda_unlisted` is not here: the phone answers null for it until milestone 4.
 *
 * The store writers ([storeSongs], [storeArtistPage], [storeSearch]) are lacuerda_index.py's, for what a lookup reads:
 * an artist page's songs in place of those it gave before, and the rows LaCuerda's own search answered beside what
 * the index holds. LaCuerda's rows hold no time, so each store notes the page it wrote (core.index.Reads, kv
 * `phone:read:lacuerda:<page>` at the store's `at`: "<slug>/", or [SEARCH_PAGE]), which the next push of the index
 * to the computer sends; tests/conformance/vectors/sites/lacuerda_store.jsonl holds them to Python's rows.
 */
object LaCuerda {
    fun nameKey(name: String): String = Normalize.lacuerdaNameKey(name)
    fun titleKey(title: String): String = Normalize.lacuerdaTitleKey(title)

    /** lacuerda_index.KEYS_KEY: the KEY_VERSION the keys were made with. */
    const val KEYS_KEY = "lacuerda:index:keys"

    /** lacuerda_index.PAGES_KEY: each listing page in the index, by path. */
    const val PAGES_KEY = "lacuerda:index:pages"

    /** lacuerda_index.COMPLETE_KEY: when every listing page was last read or found unchanged. */
    const val COMPLETE_KEY = "lacuerda:index:complete_at"

    /** lacuerda_index.SEARCH_PAGE: the page of the rows LaCuerda's search answered. */
    const val SEARCH_PAGE = "busca.php"

    /** Reads' name of LaCuerda's pages. */
    const val SITE = "lacuerda"

    private val COLUMNS = listOf("path", "artist_slug", "artist", "artist_key", "title", "title_key", "songs",
                                 "versions", "acordes", "popular", "page")

    /** lacuerda.LETTERS: LaCuerda's initials, as its menu links them ("_num" for "#", "nn" for "Ñ"). */
    val LETTERS: List<String> get() = LaCuerdaUrls.LETTERS

    // --- lacuerda_index.py's store writers ------------------------------------------------------------------------

    /**
     * store_songs: an artist page's songs in place of those it gave before (page "<slug>/"), noted at [at]. [name]:
     * the artist's, as the page heads it; without one, the index's row names them, else their slug does, each word
     * capitalized as str.capitalize does. [popular]: each song's place in the artist's popularity, by slug.
     */
    fun storeSongs(db: Db, slug: String, name: String?, songs: List<LaCuerdaSong>, popular: Map<String, Int>? = null,
                   at: String) {
        val named = if (!name.isNullOrEmpty()) name else {
            db.one("SELECT artist FROM lacuerda_index WHERE path = ?", "$slug/") { it.text(0)!! }
                ?: slug.split("_").filter { it.isNotEmpty() }.joinToString(" ") { PyUnicode.capitalize(it) }.ifEmpty { slug }
        }
        val key = nameKey(named)
        val rows = songs.map { s ->
            listOf("$slug/${s.slug}", slug, named, key, s.title, titleKey(s.title), 0, s.types,
                   LaCuerdaPages.bestAcordesVersion(s) ?: 0, popular?.get(s.slug), "$slug/")
        }
        replace(db, "$slug/", rows, at)
    }

    /** store_artist_page: an artist page's songs into the index, as a lookup reads it, noted at [at]; false, and
     * nothing stored, for LaCuerda's "no such artist" body or a page that won't parse. */
    fun storeArtistPage(db: Db, slug: String, html: String, at: String): Boolean {
        if (LaCuerdaPages.isMissingArtistPage(html)) return false
        val songs = try {
            LaCuerdaPages.parseArtistPage(html)
        } catch (_: LaCuerdaParseError) {
            return false
        }
        storeSongs(db, slug, LaCuerdaPages.parseArtistName(html), songs, LaCuerdaPages.parsePopularity(html), at)
        return true
    }

    /**
     * store_search: the rows of an answer of LaCuerda's search into the index, beside what it holds, in one
     * savepoint; how many it stored. Each song as an artist page's would be, its page [SEARCH_PAGE] (one the index
     * has already keeps its page and its place in the popularity, and takes the answer's versions); each artist no
     * listing names yet a row of their own ([SEARCH_PAGE]), a listing's row never touched. Noted at [at] when the
     * answer has any row.
     */
    fun storeSearch(db: Db, answer: LaCuerdaSearchAnswer, at: String): Int {
        ensureCurrentKeys(db)
        val named = LinkedHashMap<String, Pair<String, Long>>()
        for (a in answer.artists) named[a.slug] = a.name to a.songs
        for (s in answer.songs) named.putIfAbsent(s.artistSlug, s.artist to 0L)
        val columns = COLUMNS.joinToString(", ")
        db.savepoint("lacuerda_index_search") {
            for (s in answer.songs) {
                db.execute("INSERT INTO lacuerda_index ($columns) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, ?) " +
                               "ON CONFLICT(path) DO UPDATE SET title = excluded.title, title_key = excluded.title_key, " +
                               "versions = excluded.versions, acordes = excluded.acordes",
                           "${s.artistSlug}/${s.slug}", s.artistSlug, s.artist, nameKey(s.artist), s.title,
                           titleKey(s.title), s.song.types, LaCuerdaPages.bestAcordesVersion(s.song) ?: 0, SEARCH_PAGE)
            }
            for ((slug, artist) in named) {
                db.execute("INSERT INTO lacuerda_index ($columns) VALUES (?, ?, ?, ?, '', '', ?, '', 0, NULL, ?) " +
                               "ON CONFLICT(path) DO UPDATE SET songs = max(songs, excluded.songs) WHERE page = excluded.page",
                           "$slug/", slug, artist.first, nameKey(artist.first), artist.second, SEARCH_PAGE)
            }
            if (answer.songs.isNotEmpty() || answer.artists.isNotEmpty()) Reads.note(db, SITE, SEARCH_PAGE, at)
        }
        return answer.songs.size + answer.artists.size
    }

    /** _replace: [page]'s rows in place of those it gave before, in one savepoint, and the page noted at [at]. */
    private fun replace(db: Db, page: String, rows: List<List<Any?>>, at: String) {
        ensureCurrentKeys(db)
        val insert = "INSERT OR REPLACE INTO lacuerda_index (${COLUMNS.joinToString(", ")}) " +
            "VALUES (${COLUMNS.joinToString(", ") { "?" }})"
        db.savepoint("lacuerda_index_store") {
            db.execute("DELETE FROM lacuerda_index WHERE page = ?", page)
            for (row in rows) db.execute(insert, *row.toTypedArray())
            Reads.note(db, SITE, page, at)
        }
    }

    // --- search.py's LaCuerda glue -------------------------------------------------------------------------------

    /**
     * LaCuerda's artists and songs in its index that match [q], best first ([find]): an artist's songs that only their
     * name matched are in their row, and beside an artist whose whole name is the query, one whose name is only near
     * it is left out; one whose name holds the query's words among others stays.
     */
    fun searchLacuerda(
        db: Db, q: String, songs: Int = SearchLimits.SITE_ROWS, artists: Int = SearchLimits.ARTIST_ROWS,
    ): Pair<List<SiteArtist>, List<SiteHit>> {
        val found = find(db, q, artists = artists, songs = songs)
        val whole = found.artists.filter { it.score >= 100 }
        val named = if (whole.isNotEmpty()) found.artists.filter { it.score >= 100 || it.part } else found.artists
        return named.map { siteArtist(db, it) } to found.songs.map { siteHit(it) }
    }

    /** One artist of LaCuerda's index, by the slug of their page, as [searchLacuerda] gives them (score 100); null for
     * one it doesn't know. */
    fun lacuerdaArtist(db: Db, slug: String): SiteArtist? {
        val row = db.one("SELECT artist, artist_key, songs FROM lacuerda_index WHERE artist_slug = ? " +
                             "ORDER BY title != '', path LIMIT 1", slug) {
            Triple(it.text(0)!!, it.text(1)!!, it.long(2)!!.toInt())
        } ?: return null
        val hit = LaCuerdaHit(row.first, slug, row.second, LaCuerdaUrls.artistUrl(slug), 100.0, songs = row.third,
                              top = LaCuerdaFind.artistSongs(db, slug, SearchLimits.TOP_SONGS, acordes = true))
        return siteArtist(db, hit)
    }

    /** One artist of LaCuerda's index by their name, as LaCuerda writes it or as you do (each of the name's forms
     * too), as [lacuerdaArtist] gives them: the one the index holds most of; null for a name it has no artist by. */
    fun lacuerdaArtistNamed(db: Db, name: String): SiteArtist? {
        val keys = nameKeys(name)
        if (keys.isEmpty()) return null
        val slug = db.one("SELECT artist_slug FROM lacuerda_index WHERE artist_key IN (${keys.joinToString(", ") { "?" }}) " +
                              "GROUP BY artist_slug ORDER BY COUNT(*) DESC, artist_slug LIMIT 1", *keys.toTypedArray()) {
            it.text(0)!!
        } ?: return null
        return lacuerdaArtist(db, slug)
    }

    /** The songs LaCuerda's index holds of an artist, most popular first, as LaCuerda orders them; none until caracole
     * has read their page. With [title], only those whose title it matches, best first. */
    fun lacuerdaSongs(db: Db, slug: String, title: String? = null): List<SiteHit> =
        SiteText.titledOnly(LaCuerdaFind.artistSongs(db, slug).map { siteHit(it) }, title)

    /** Why a search of LaCuerda's index finds less than LaCuerda has, worded to follow "LaCuerda's": ("empty", …)
     * before the nightly run read any of its listings or artist pages, ("partial", …) while it reads its listings,
     * with the letters read whole so far; null once every listing page was read. */
    fun lacuerdaLeftOut(db: Db): Pair<String, String>? {
        val state = indexState(db)
        if (state.artists == 0 && state.songs == 0) {
            return "empty" to "index is empty: the nightly run reads its listings of every artist"
        }
        if (state.complete) return null
        val letters = lettersText(state.letters)
        val whole = if (letters.isNotEmpty()) ", with $letters read whole" else ""
        return "partial" to ("index is still being read: ${SiteText.grouped(state.artists)} artist" +
            "${if (state.artists == 1) "" else "s"} so far$whole; the nightly run reads the rest")
    }

    /**
     * Whether LaCuerda's group comes before Ultimate Guitar's: the Ultimate Guitar index has no artist whose whole name
     * (or a name near it) the query is and no strong song, and LaCuerda has an artist whose whole name the query is,
     * or one a word names who is well known and has more songs than any Ultimate Guitar artist the query names in part.
     * An Ultimate Guitar artist named in part who leads and outweighs LaCuerda's whole name keeps the lead.
     */
    fun lacuerdaLeads(ug: IndexFound, lc: List<SiteArtist>): Boolean {
        if (ug.artists.any { !it.part } || ug.songs.any { it.score >= SearchLimits.STRONG }) return false
        val rival = ug.artists.maxOfOrNull { it.songs } ?: 0
        val whole = lc.firstOrNull { it.score >= 100 }
        if (whole != null) return !(ug.lead == "artist" && outweighs(ug.artists[0].songs, whole.songs))
        return lc.take(1).any { it.part && it.songs >= SearchLimits.WELL_KNOWN && it.songs > rival }
    }

    /** search.py `_outweighs`: an artist named in part is the one meant before one named whole when well known and
     * with [SearchLimits.OUTWEIGHS] times their songs. */
    private fun outweighs(part: Int, whole: Int): Boolean =
        part >= SearchLimits.WELL_KNOWN && part > SearchLimits.OUTWEIGHS * whole

    private fun siteHit(h: LaCuerdaHit) = SiteHit("lacuerda", h.title, h.url, h.score, h.artist, h.artistKey, h.titleKey,
                                                  uploads = Py.len(h.versions),
                                                  via = h.via, sheet = h.sheetUrl)

    private fun siteArtist(db: Db, a: LaCuerdaHit): SiteArtist {
        // Their songs from their own page: those LaCuerda's search brought alone leave it to be read.
        val known = db.one("SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != '' AND page = ?",
                           a.artistSlug, "${a.artistSlug}/") { it.long(0)!!.toInt() }!!
        return SiteArtist("lacuerda", a.artist, a.artistSlug, a.url, a.score, maxOf(a.songs, known), known, a.via,
                          a.top.map { siteHit(it) }, a.part)
    }

    // --- lacuerda_index.py's read side ---------------------------------------------------------------------------

    /**
     * lacuerda_index.find: LaCuerda's artists and songs the index holds that match [q], best first. Ties go to the
     * artist whose name holds the query's words as words of its own, unless a common word's do; then to the one with
     * more songs; and to the song with a Letra y Acordes version, then with more versions. A query of fewer than
     * three letters (two Chinese characters) finds nothing.
     */
    fun find(db: Db, q: String, artists: Int = 3, songs: Int = 5): LaCuerdaFound = LaCuerdaFind.find(db, q, artists, songs)

    /** lacuerda_index.artist_songs: the songs the index holds of an artist, most popular first, then by title; with
     * [acordes], only those with a Letra y Acordes version. */
    fun artistSongs(db: Db, slug: String, limit: Int? = null, acordes: Boolean = false): List<LaCuerdaHit> =
        LaCuerdaFind.artistSongs(db, slug, limit, acordes)

    /** lacuerda_index.songs_like: the songs whose title's key or artist's key holds one of [patterns], at most [limit]. */
    fun songsLike(db: Db, patterns: List<String>, limit: Int = 2000): List<LaCuerdaHit> =
        LaCuerdaFind.songsLike(db, patterns, limit)

    /** lacuerda_index.artist_slugs: the slugs of the artist pages the listings give for an artist's name, most songs
     * first, by identity key, the name's own and that of each of its forms. */
    fun artistSlugs(db: Db, name: String): List<String> {
        val keys = nameKeys(name)
        if (keys.isEmpty()) return emptyList()
        return db.query("SELECT artist_slug FROM lacuerda_index WHERE artist_key IN (${keys.joinToString(", ") { "?" }}) " +
                            "AND title = '' ORDER BY songs DESC, artist_slug", *keys.toTypedArray()) { it.text(0)!! }
    }

    private fun nameKeys(name: String): List<String> =
        LinkedHashSet(listOf(nameKey(name)) + Normalize.nameForms(name).map { nameKey(it) }).filter { it.isNotEmpty() }

    /** lacuerda_index.IndexState: its artists and songs, whether every listing page was read, the letters read whole. */
    class IndexState(val artists: Int, val songs: Int, val complete: Boolean, val letters: List<String>)

    /** lacuerda_index.index_state; no request. */
    fun indexState(db: Db): IndexState {
        val (artists, songs) = db.one(
            "SELECT COUNT(*) FILTER (WHERE title = ''), COUNT(*) FILTER (WHERE title != '') FROM lacuerda_index",
        ) { it.long(0)!!.toInt() to it.long(1)!!.toInt() }!!
        return IndexState(artists, songs, completeAt(db) != null, letters(db))
    }

    /** lacuerda_index.index_state as helpers.corpus.plain writes it: `artists`, `songs`, `complete` and `letters`,
     * the letters whose every listing page the index holds. Not lacuerda_index.letters_read, a list, which is
     * [letters]; search_routes' `_looked` reads this one's `letters`. */
    fun lettersRead(db: Db): JsonObject {
        val state = indexState(db)
        return JsonObject(linkedMapOf(
            "artists" to JsonPrimitive(state.artists), "songs" to JsonPrimitive(state.songs),
            "complete" to JsonPrimitive(state.complete), "letters" to JsonArray(state.letters.map { JsonPrimitive(it) }),
        ))
    }

    /** lacuerda_index.letters_read: the letters whose every listing page the index holds (read, found unchanged, or
     * gone), in [LETTERS]' order. A refresh the budget cut short leaves the letter it stopped in out until its other
     * pages are read. */
    fun letters(db: Db): List<String> {
        val indexed = (db.kvGetJson(PAGES_KEY) as? JsonObject) ?: JsonObject(emptyMap())
        return LETTERS.filter { letter ->
            val first = indexed[LaCuerdaUrls.listingPath(letter)]
            first != null && first !is JsonNull &&
                ((first.jsonObject["pages"] as? JsonArray) ?: JsonArray(emptyList())).all {
                    LaCuerdaUrls.listingPath(letter, (it as JsonPrimitive).content) in indexed
                }
        }
    }

    /** lacuerda_index.unread_letter: the letter whose listing an artist of this name would be in, while the index
     * hasn't read it whole: the first unread letter of the slugs their page may have; null once those letters are
     * read, or the whole index is, and for a name no slug can be made of. */
    fun unreadLetter(db: Db, name: String): String? {
        if (completeAt(db) != null) return null
        val read = letters(db).toSet()
        for (slug in artistSlugCandidates(name)) {
            val letter = if (PyUnicode.isDigit(slug.codePointAt(0))) "_num" else String(Character.toChars(slug.codePointAt(0)))
            if (letter in LETTERS && letter !in read) return letter
        }
        return null
    }

    /** lacuerda_index.letters_text: letters as LaCuerda's menu names them ("#", "Ñ"), three in a row or more as a
     * range: "#, A–C", "A, B, E". */
    fun lettersText(letters: List<String>): String {
        val order = LETTERS.withIndex().associate { (n, letter) -> letter to n }
        val runs = ArrayList<MutableList<String>>()
        for (letter in LinkedHashSet(letters).sortedBy { order[it] ?: order.size }) {
            val last = runs.lastOrNull()?.last()
            if (last != null && letter != "_num" && last != "_num" && order[letter] == (order[last] ?: -2) + 1) {
                runs.last().add(letter)
            } else {
                runs.add(mutableListOf(letter))
            }
        }
        fun name(x: String) = when (x) { "_num" -> "#"; "nn" -> "Ñ"; else -> PyUnicode.upper(x) }
        return runs.joinToString(", ") { r ->
            if (r.size > 2) "${name(r.first())}–${name(r.last())}" else r.joinToString(", ") { name(it) }
        }
    }

    /** lacuerda.artist_slug_candidates: slugs worth trying for an artist, best guess first. */
    fun artistSlugCandidates(name: String): List<String> = LaCuerdaUrls.artistSlugCandidates(name)

    /** lacuerda.artist_url. */
    fun artistUrl(slug: String): String = LaCuerdaUrls.artistUrl(slug)

    /**
     * lacuerda_index.ensure_current_keys: every row's keys made again from its names after a change to caracole's keys
     * ([Normalize.KEY_VERSION]), once; no request. How many rows changed.
     */
    fun ensureCurrentKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(KEYS_KEY) == version) return 0
        return db.savepoint("lacuerda_index_keys") {
            var changed = 0
            val rows = db.query("SELECT path, artist, title, artist_key, title_key FROM lacuerda_index") {
                listOf(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.text(3)!!, it.text(4)!!)
            }
            for ((path, artist, title, oldArtist, oldTitle) in rows) {
                val artistKey = nameKey(artist)
                val songKey = if (title.isNotEmpty()) titleKey(title) else ""
                if (artistKey != oldArtist || songKey != oldTitle) {
                    db.execute("UPDATE lacuerda_index SET artist_key = ?, title_key = ? WHERE path = ?",
                               artistKey, songKey, path)
                    changed++
                }
            }
            db.kvSet(KEYS_KEY, version)
            changed
        }
    }

    /** lacuerda_index.complete_at, as stamps.parse reads it: null when it is missing or unreadable ([IsoTime]). */
    private fun completeAt(db: Db): String? = db.kvGet(COMPLETE_KEY)?.takeIf { Stamps.parse(it) != null }
}
