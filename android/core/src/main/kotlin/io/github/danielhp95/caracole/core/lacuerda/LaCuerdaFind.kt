package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Row
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * lacuerda_index.py's `find`, and the words and scores it reads names by (its `_forms`, `_queries`, `_patterns` and
 * `_Query`, its own, as search.py's are for the Ultimate Guitar index), over its `_rows_like` prefilter. Lengths and
 * indexes are Python's, in code points (Fuzz's alignments are too); every word and key is Normalize's.
 */
internal object LaCuerdaFind {
    const val MIN_SCORE = 70.0
    const val PARTIAL_SCALE = 0.9
    const val NAMED = 80.0
    const val WORD_NAMED = 75.0
    const val INSIDE_SCALE = 0.85
    const val PINYIN_PARTIAL_SCALE = 0.85 // normalize.PINYIN_PARTIAL_SCALE
    val READINGS = listOf("title", "both", "artist")
    const val ARTIST_ROWS = 3
    const val SONG_ROWS = 5
    const val TOP_SONGS = 3
    const val WORD_ARTISTS = 10
    const val WORD_SHARE = 500
    const val ROWS_READ = 2000
    const val MAX_PATTERNS = 3
    const val MAX_EXTRA = 2
    const val CLOSE_LETTERS = 4
    const val WORD_FEW = 2
    const val WORD_KNOWN = 50

    val COLUMNS = listOf("path", "artist_slug", "artist", "artist_key", "title", "title_key", "songs", "versions",
                         "acordes", "popular", "page")
    val SELECT = COLUMNS.joinToString(", ")

    /** A row of lacuerda_index. */
    class IndexRow(val path: String, val artistSlug: String, val artist: String, val artistKey: String, val title: String,
                   val titleKey: String, val songs: Int, val versions: String, val acordes: Int, val popular: Long?,
                   val page: String)

    fun row(r: Row) = IndexRow(r.text(0)!!, r.text(1)!!, r.text(2)!!, r.text(3)!!, r.text(4)!!, r.text(5)!!,
                               r.long(6)!!.toInt(), r.text(7)!!, r.long(8)!!.toInt(), r.long(9), r.text(10)!!)

    // --- find ----------------------------------------------------------------------------------------------------

    private class Named(val score: Double, val via: String, val row: IndexRow)

    fun find(db: Db, query: String, artists: Int = ARTIST_ROWS, songs: Int = SONG_ROWS): LaCuerdaFound {
        val queries = queries(query)
        val (patterns, extra) = patterns(query)
        if (queries.isEmpty() || patterns.isEmpty()) return LaCuerdaFound()
        val named = LinkedHashMap<String, Named>()
        val byName = LinkedHashMap<String, Pair<Double, IndexRow>>() // artists only their songs' rows matched
        val byWord = LinkedHashMap<Pair<List<String>, List<String>>, LinkedHashSet<String>>() // named by a word: word, rest
        val otherwise = HashMap<String, Double>() // what those score but for the word
        val found = ArrayList<Named>()
        for (row in rowsLike(db, patterns, extra)) {
            val names = row.artistKey.replace("-", " ")
            if (row.title.isEmpty()) {
                var best: ArtistReading? = null
                for (q in queries) {
                    val reading = q.artist(names)
                    if (best == null || reading.score > best.score) best = reading
                }
                val (score, via, word) = best!!
                if (score >= MIN_SCORE) {
                    named[row.artistSlug] = Named(score, via, row)
                    if (word != null) {
                        byWord.getOrPut(word.run to word.rest) { LinkedHashSet() }.add(row.artistSlug)
                        otherwise[row.artistSlug] = word.otherwise
                    }
                }
                continue
            }
            val (score, via) = reading(queries.map { it.readings(names, row.titleKey.replace("-", " ")) })
            if (score < MIN_SCORE) continue
            if (via == "artist") {
                if (score > (byName[row.artistSlug]?.first ?: 0.0)) byName[row.artistSlug] = score to row
            } else {
                found.add(Named(score, via, row))
            }
        }
        // Beside an artist the query names whole, its other words are a title: a word of them names no one.
        val whole = named.values.any { it.via == "both" && it.score >= NAMED }
        for ((word, slugs) in byWord) {
            for (slug in slugs) {
                val row = named.getValue(slug).row
                if (whole || !wordNames(db, row, word.second, slugs.size <= WORD_FEW)) {
                    val instead = otherwise.getValue(slug)
                    if (instead >= MIN_SCORE) named[slug] = Named(instead, "artist", row) else named.remove(slug)
                }
            }
        }
        for ((slug, pair) in byName) {
            val (score, row) = pair
            val before = named[slug]
            if (before == null || before.score < score) {
                val own = db.one("SELECT $SELECT FROM lacuerda_index WHERE path = ?", "$slug/") { row(it) }
                named[slug] = Named(score, "artist", own ?: row)
            }
        }
        var parts = named.filter { (_, n) -> queries.any { it.partOf(n.row.artistKey.replace("-", " ")) } }.keys.toSet()
        if (parts.size > WORD_ARTISTS && parts.size.toLong() * WORD_SHARE > listedArtists(db)) {
            // A common word ("band", "los"): no name holds it as its own more than another, so its whole words count
            // as letters inside one do ("band" of Banda el Limón), and the artists' songs alone order them.
            for (slug in parts) {
                val n = named.getValue(slug)
                if (n.score <= 100 * PARTIAL_SCALE) named[slug] = Named(n.score * INSIDE_SCALE / PARTIAL_SCALE, n.via, n.row)
            }
            parts = emptySet()
        }
        class Ranked(val n: Named, val notPart: Boolean, val songs: Int, val folded: String)
        val ranked = named.values
            .map { Ranked(it, it.row.artistSlug !in parts, artistSongs(db, it.row), PyUnicode.casefold(it.row.artist)) }
            .sortedWith(compareBy<Ranked>({ -it.n.score }, { it.notPart }, { -it.songs })
                            .thenComparing({ it.folded }, Py.CODE_POINT_ORDER)
                            .thenComparing({ it.n.row.artistSlug }, Py.CODE_POINT_ORDER))
        class Song(val n: Named, val artist: String, val title: String)
        val ordered = found.map { Song(it, PyUnicode.casefold(it.row.artist), PyUnicode.casefold(it.row.title)) }
            .sortedWith(compareBy<Song>({ -it.n.score }, { it.n.row.acordes == 0 }, { -Py.len(it.n.row.versions) })
                            .thenComparing({ it.artist }, Py.CODE_POINT_ORDER)
                            .thenComparing({ it.title }, Py.CODE_POINT_ORDER)
                            .thenComparing({ it.n.row.path }, Py.CODE_POINT_ORDER))
        return LaCuerdaFound(
            artists = ranked.take(maxOf(artists, 0)).map {
                artistHit(db, it.n.row, it.n.score, it.n.via, it.n.row.artistSlug in parts)
            },
            songs = ordered.take(maxOf(songs, 0)).map { songHit(it.n.row, it.n.score, it.n.via) },
        )
    }

    /** The songs the index holds of an artist, most popular first (LaCuerda's own order), then by title; with
     * [acordes], only those with a Letra y Acordes version. */
    fun artistSongs(db: Db, slug: String, limit: Int? = null, acordes: Boolean = false): List<LaCuerdaHit> {
        val where = if (acordes) " AND acordes > 0" else ""
        return db.query(
            "SELECT $SELECT FROM lacuerda_index WHERE artist_slug = ? AND title != ''$where " +
                "ORDER BY popular IS NULL, popular, title COLLATE NOCASE, path LIMIT ?", slug, limit ?: -1,
        ) { songHit(row(it), 0.0, "artist") }
    }

    /** The songs the index holds whose title's key or artist's key holds one of [patterns] (`LIKE`), at most [limit]. */
    fun songsLike(db: Db, patterns: List<String>, limit: Int = ROWS_READ): List<LaCuerdaHit> {
        if (patterns.isEmpty()) return emptyList()
        val where = patterns.joinToString(" OR ") { "title_key LIKE ? OR artist_key LIKE ?" }
        return db.query("SELECT $SELECT FROM lacuerda_index WHERE title != '' AND ($where) ORDER BY path LIMIT ?",
                        *patterns.flatMap { listOf(it, it) }.toTypedArray(), limit) { songHit(row(it), 0.0, "title") }
    }

    /** How many artists LaCuerda's listings the index holds name. */
    private fun listedArtists(db: Db): Long = db.one("SELECT COUNT(*) FROM lacuerda_index WHERE title = ''") { it.long(0)!! }!!

    /** An artist's songs: as their listing counts them, else as many as the index holds. */
    fun artistSongs(db: Db, row: IndexRow): Int {
        if (row.title.isEmpty()) return row.songs
        return db.one("SELECT COUNT(*) FROM lacuerda_index WHERE artist_slug = ? AND title != ''", row.artistSlug) {
            it.long(0)!!.toInt()
        }!!
    }

    private fun artistHit(db: Db, row: IndexRow, score: Double, via: String, part: Boolean) = LaCuerdaHit(
        artist = row.artist, artistSlug = row.artistSlug, artistKey = row.artistKey,
        url = LaCuerdaUrls.artistUrl(row.artistSlug), score = Py.round(score, 1), via = via,
        songs = artistSongs(db, row), top = artistSongs(db, row.artistSlug, TOP_SONGS, acordes = true), part = part,
    )

    private fun songHit(row: IndexRow, score: Double, via: String): LaCuerdaHit {
        val song = row.path.substringAfter('/', "")
        return LaCuerdaHit(
            artist = row.artist, artistSlug = row.artistSlug, artistKey = row.artistKey,
            url = LaCuerdaUrls.songUrl(row.artistSlug, song), score = Py.round(score, 1), via = via, title = row.title,
            songSlug = song, titleKey = row.titleKey, versions = row.versions, acordes = row.acordes,
        )
    }

    /** The rows whose keys hold one of [patterns]; those holding more of them and of [extra] first, then artists,
     * then the shortest keys: at most [ROWS_READ]. */
    private fun rowsLike(db: Db, patterns: List<String>, extra: List<String>): List<IndexRow> {
        // The keys hyphenated, and written together: "banma" is in "ban-ma-ban-ma", a Chinese name's pinyin.
        fun holds(n: Int) = "(artist_key LIKE ?$n OR title_key LIKE ?$n OR replace(artist_key, '-', '') LIKE ?$n " +
            "OR replace(title_key, '-', '') LIKE ?$n)"
        val every = patterns + extra
        val where = (1..patterns.size).joinToString(" OR ") { holds(it) }
        val held = (1..every.size).joinToString(" + ") { holds(it) }
        return db.query(
            "SELECT $SELECT FROM lacuerda_index WHERE $where " +
                "ORDER BY $held DESC, title != '', length(artist_key) + length(title_key), path LIMIT $ROWS_READ",
            *every.toTypedArray(),
        ) { row(it) }
    }

    /** Whether a word of an artist's name at the query's start or end names them ([WORD_NAMED]): when the rest of the
     * query is a title an index knows of theirs exactly, or when they are well known ([WORD_KNOWN] songs) and the
     * word is in [few] names. */
    private fun wordNames(db: Db, row: IndexRow, rest: List<String>, few: Boolean): Boolean {
        val text = rest.joinToString(" ")
        if (text.isNotEmpty() && (
                db.one("SELECT 1 FROM lacuerda_index WHERE artist_slug = ? AND title_key = ? LIMIT 1",
                       row.artistSlug, Normalize.lacuerdaTitleKey(text)) { 1 } != null ||
                    db.one("SELECT 1 FROM ug_index WHERE artist_key = ? AND song_key = ? LIMIT 1",
                           row.artistKey, Normalize.slugKey(text)) { 1 } != null)) {
            return true
        }
        return few && artistSongs(db, row) >= WORD_KNOWN
    }

    // --- words and scores, as search.py has them -----------------------------------------------------------------

    /** The query as words: as written, as an identity key's title folds it (number words as digits) and as an
     * artist's (a leading article and "y" dropped); Chinese in pinyin too. */
    fun forms(text: String): List<String> {
        val words = Normalize.nameWords(text)
        val forms = mutableListOf(
            words.joinToString(" "),
            Normalize.lacuerdaTitleKey(text).replace("-", " "),
            Normalize.lacuerdaNameKey(text).replace("-", " "),
        )
        if (Normalize.hasHan(text)) {
            forms.add(words.joinToString(" ") { if (Normalize.hasHan(it)) Normalize.fold(Normalize.romanize(it)) else it })
        }
        return LinkedHashSet(forms).filter { it.isNotEmpty() }
    }

    /** The query's forms, ready to be scored. A Chinese query's forms all carry each Chinese word's pinyin
     * ([LcQuery.runs]): the pinyin the keys make of it counts only as whole words of a name. */
    fun queries(text: String): List<LcQuery> {
        val words = Normalize.nameWords(text)
        val plain = words.joinToString("")
        if (Py.len(plain) < (if (Normalize.hasHan(plain)) 2 else 3)) return emptyList()
        val runs = words.filter { Normalize.hasHan(it) }.map { w ->
            Py.split(Normalize.romanize(w)).joinToString("") { Normalize.fold(it) }
        }
        return forms(text).map { LcQuery(it, runs) }
    }

    /** The `LIKE` patterns the prefilter needs a row to hold one of (the query's longest words), and up to two more
     * that put the rows holding them first. Chinese words are their pinyin syllables in order; a name of initials is
     * its hyphenated and its compact key. */
    fun patterns(text: String): Pair<List<String>, List<String>> {
        val found = ArrayList<Pair<Int, String>>()
        // A Chinese query's pinyin forms are its syllables apart: only the form that still holds the characters
        // makes patterns, so a word is its syllables in order and never one pattern per syllable.
        val forms = if (Normalize.hasHan(text)) listOf(Normalize.nameWords(text).joinToString(" ")) else forms(text)
        for (form in forms) {
            for (token in Py.split(form)) {
                if (Normalize.hasHan(token)) {
                    val syllables = Py.split(Normalize.romanize(token))
                    val letters = syllables.sumOf { Py.len(it) }
                    if (letters >= 4) found.add(letters to "%" + syllables.joinToString("%") { Normalize.fold(it) } + "%")
                } else if (Py.len(token) >= 2) {
                    found.add(Py.len(token) to "%$token%")
                }
            }
        }
        var long: List<Pair<Int, String>> = found.filter { it.first >= 3 }
        if (long.isEmpty()) { // names made of initials
            val latin = Normalize.nameWords(text).filter { !Normalize.hasHan(it) }
            val key = latin.joinToString("-")
            if (Py.len(latin.joinToString("")) >= 2) {
                long = listOf(Py.len(key) to "%$key%", Py.len(key) to "%${key.replace("-", "")}%")
            }
        }
        val ordered = LinkedHashSet(long.sortedByDescending { it.first }.map { it.second }).toList()
        val patterns = ordered.take(MAX_PATTERNS)
        val rest = found.sortedByDescending { it.first }.map { it.second }.filter { it !in patterns }
        return patterns to LinkedHashSet(rest).toList().take(MAX_EXTRA)
    }

    /** A word of a name the query may name an artist by, the rest of the query, and the score the name has otherwise. */
    class Word(val run: List<String>, val rest: List<String>, val otherwise: Double)

    data class ArtistReading(val score: Double, val via: String, val word: Word?)

    /** One form of a query, ready to be scored against many rows (space-separated words): lacuerda_index's `_Query`. */
    class LcQuery(val text: String, val runs: List<String> = emptyList()) {
        val compact: String = text.replace(" ", "")
        private val words: List<String> = Py.split(text)

        /** Whether each Chinese word's pinyin is a whole run of the words of one of [names]; true for a query with
         * no Chinese. */
        fun holds(vararg names: String): Boolean {
            val split = names.map { Py.split(it) }
            return runs.all { run -> split.any { Normalize.holdsRun(it, run) } }
        }

        /** Whether the query's words are words of an artist's name among others, each Chinese word's pinyin a whole
         * run of them: never letters inside a word, nor the whole name. */
        fun partOf(artist: String): Boolean {
            val name = Py.split(artist)
            return words.size < name.size && words.all { it in name } && holds(artist)
        }

        /** How well the query names an artist, the reading, and, when it names them only by a word of their name, that
         * word, the rest of the query and the score the name has otherwise: 100 for the whole name, at most 90 for a
         * part of it in whole words or its start as typed so far, at most 85 for letters inside a word ("artist");
         * [NAMED] for the whole name, as words of its own, among other words of the query ("both"); [WORD_NAMED] for
         * words of the name, fewer than all, as the query's first or last words among others ("both"). */
        fun artist(artist: String): ArtistReading {
            val a = artist.replace(" ", "")
            val name = Py.split(artist)
            var best = 0.0
            if (holds(artist)) {
                best = maxOf(Fuzz.ratio(text, artist), Fuzz.ratio(compact, a))
                for ((needle, hay, together) in listOf(Triple(text, artist, false), Triple(compact, a, true))) {
                    if (Py.len(needle) < Py.len(hay)) {
                        val part = Fuzz.partialRatioAlignment(needle, hay)
                        best = maxOf(best, scale(part, name, together, listOf(name)) * part.score)
                    }
                }
            }
            if (best < NAMED && name.isNotEmpty() && name.size < words.size &&
                (0..words.size - name.size).any { words.subList(it, it + name.size) == name }) {
                return ArtistReading(NAMED, "both", null)
            }
            if (best < WORD_NAMED && runs.isEmpty()) {
                val word = wordOf(words, name)
                if (word != null) return ArtistReading(WORD_NAMED, "both", Word(word.first, word.second, best))
            }
            return ArtistReading(best, "artist", null)
        }

        /** What a partial match counts for: [PARTIAL_SCALE] when it is whole words of [words] (spaced, or
         * [together]), or the query is the start of one of [starts] as typed so far; [INSIDE_SCALE] for letters inside
         * a word; a Chinese query's pinyin, [PINYIN_PARTIAL_SCALE]. */
        private fun scale(part: Fuzz.Alignment, words: List<String>, together: Boolean, starts: List<List<String>>): Double {
            if (runs.isNotEmpty()) return PINYIN_PARTIAL_SCALE
            val (begins, ends) = bounds(words, together)
            if ((part.destStart in begins && part.destEnd in ends) || starts.any { typedStart(this.words, it) }) {
                return PARTIAL_SCALE
            }
            return INSIDE_SCALE
        }

        /** How well the query names a song, by reading: as its title, as both its names (their words in any order),
         * as its artist. A part of the names counts for the title or the artist when it lies within that name, else
         * for both. */
        fun readings(artist: String, title: String): DoubleArray {
            if (runs.isNotEmpty() && !holds(artist, title)) return doubleArrayOf(0.0, 0.0, 0.0)
            val a = artist.replace(" ", "")
            val t = title.replace(" ", "")
            val full = "$artist $title"
            val fullWords = Py.split(full)
            val by = doubleArrayOf(
                maxOf(Fuzz.ratio(text, title), Fuzz.ratio(compact, t)),
                maxOf(Fuzz.tokenSortRatio(text, full), Fuzz.ratio(compact, a + t)),
                maxOf(Fuzz.ratio(text, artist), Fuzz.ratio(compact, a)),
            )
            // Spaced, the title starts after the artist and a space; compact, right after the artist.
            val sides = listOf(Side(text, full, Py.len(artist), 1), Side(compact, a + t, Py.len(a), 0))
            for (side in sides) {
                if (Py.len(side.needle) < Py.len(side.names)) {
                    val part = Fuzz.partialRatioAlignment(side.needle, side.names)
                    val where = when {
                        part.destStart >= side.edge -> 0
                        part.destEnd <= side.edge + side.gap -> 2
                        else -> 1
                    }
                    val scale = scale(part, fullWords, side.gap == 0, listOf(Py.split(title), Py.split(artist), fullWords))
                    by[where] = maxOf(by[where], scale * part.score)
                }
            }
            return by
        }

        private class Side(val needle: String, val names: String, val edge: Int, val gap: Int)
    }

    /** Where each word starts, and where each ends, in [words] written spaced or [together]. */
    private fun bounds(words: List<String>, together: Boolean): Pair<Set<Int>, Set<Int>> {
        val begins = HashSet<Int>()
        val ends = HashSet<Int>()
        var at = 0
        for (word in words) {
            begins.add(at)
            at += Py.len(word)
            ends.add(at)
            at += if (together) 0 else 1
        }
        return begins to ends
    }

    /** Whether the query is the start of a name as typed so far: two words or more, each but the last a word of the
     * name's start, the last the start of the next ("joaquin sab"). One word alone is letters of a word. */
    private fun typedStart(query: List<String>, name: List<String>): Boolean {
        val k = query.size
        return k in 2..name.size && query.subList(0, k - 1) == name.subList(0, k - 1) && name[k - 1].startsWith(query[k - 1])
    }

    /** The longest run of the query's first or last words, fewer than all, that is a run of a name's words, fewer than
     * all, with a word of [CLOSE_LETTERS] letters at least, and the query's other words. Null for none. */
    private fun wordOf(words: List<String>, name: List<String>): Pair<List<String>, List<String>>? {
        for (n in minOf(words.size, name.size) - 1 downTo 1) {
            val runs = listOf(words.subList(0, n) to words.subList(n, words.size),
                              words.subList(words.size - n, words.size) to words.subList(0, words.size - n))
            for ((run, rest) in runs) {
                if (run.any { Py.len(it) >= CLOSE_LETTERS } && (0..name.size - n).any { name.subList(it, it + n) == run }) {
                    return run.toList() to rest.toList()
                }
            }
        }
        return null
    }

    /** The best of several (title, both, artist) readings, and which it is; a tie goes to the title, then both. */
    fun reading(scores: List<DoubleArray>): Pair<Double, String> {
        var best = 0.0
        var via = READINGS[0]
        for (triple in scores) {
            for (i in READINGS.indices) {
                if (triple[i] > best) {
                    best = triple[i]
                    via = READINGS[i]
                }
            }
        }
        return best to via
    }
}
