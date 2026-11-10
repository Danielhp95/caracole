package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.random.Random
import kotlin.test.assertEquals

/**
 * How long the matcher takes on one song, as a lookup matches it (Matcher.matchAll over a fresh IndexView), and the
 * heap what it loads keeps, over a synthetic index the size of the phone's: [ROWS] ug_index rows, [ARTISTS] artist
 * keys, [TITLES] title keys (base keys, a variant such as `-acoustic` with its title) and [CATCH_ALL] songs of the
 * catch-alls step 4 reads. Each figure is printed (no assertion on it: a figure for the plan's risks); what loads when
 * is asserted, so a song steps 1 and 2 settle never loads the artists, the titles or the catch-alls.
 *
 * The names are syllables from a seeded generator, an artist one to three words and a title one to four, a few artists
 * with hundreds of titles and most with a few. The index is stored without ug_index's triggers, whose tables (the
 * keys' words, their trigrams, the full-text index, the artists' words) the matcher never reads, and with its two
 * indexes made after the rows, so the data set is made in seconds.
 */
class MatcherBench {
    @get:Rule val tmp = TemporaryFolder()

    private val policy = MatchPolicy()
    private val random = Random(20261104)

    @Test fun oneSongMatchedOverAnIndexThePhonesSize() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            val made = System.nanoTime()
            val index = database.writeBlocking { build(it) }
            report("the index made: $ROWS rows, ${index.artists.size} artists besides the catch-alls, in ${ms(made)} ms")
            database.writeBlocking { db ->
                assertEquals(ROWS.toLong(), db.one("SELECT COUNT(*) FROM ug_index") { it.long(0)!! })
                val store = LibraryStore(tmp.newFolder("library"))
                val (artist, title) = index.someSong
                // Steps 1 and 2: its title under its own artist, as a lookup of a song UG has mostly is.
                val exact = case(db, store.add(db, words(artist), words(title), now = NOW), "its own artist's title",
                                 loads = emptySet())
                assertEquals("accept" to "exact", exact.decision to exact.step)
                // Step 3: the artist misspelt, a letter changed, its title under the nearest artist key.
                case(db, store.add(db, words(misspelt(index.longArtist.first)), words(index.longArtist.second), now = NOW),
                     "the artist misspelt", loads = setOf("artists"))
                // Steps 4 and 5: a cover, its title under another artist, found on the title alone.
                val cover = case(db, store.add(db, "Nobody Known Qx", words(title), now = NOW), "a cover",
                                 loads = setOf("artists", "titles", "catch_all"))
                assertEquals("review", cover.decision)
                // Every step, then not found: the most a song costs.
                val nothing = store.add(db, "Nobody Known Qx", "Zzqx Wrlpt Vvq", now = NOW)
                val missed = case(db, nothing, "nothing anywhere", loads = setOf("artists", "titles", "catch_all"))
                assertEquals("not_found", missed.decision)
                loadsAndHeap(db, nothing)
            }
        }
    }

    /** One song matched as a lookup does, timed (twice: the first in a JVM that may still be compiling), and what a
     * view of its own loads for it. */
    private fun case(db: Db, song: SongRow, name: String, loads: Set<String>): MatchResult {
        val times = List(2) {
            val started = System.nanoTime()
            Matcher.matchAll(db, Overrides(), policy, listOf(song), dryRun = true)
            ms(started)
        }
        val view = IndexView(db)
        val r = Matcher.matchSong(song, view, Overrides(), policy)
        assertEquals(loads, view.loaded, name)
        report("$name (${r.decision}, ${r.step}): matchAll ${times.joinToString(" then ")} ms, loads ${view.loaded}")
        return r
    }

    /** Each structure a view loads whole, timed and its heap measured on a view of its own, then a second song on a
     * view that has loaded everything, as the nightly run's next song is. */
    private fun loadsAndHeap(db: Db, song: SongRow) {
        val parts = listOf<Pair<String, (IndexView) -> Unit>>(
            "artist keys" to { it.artistKeys() },
            "artist keys without hyphens" to { it.artistKeys(); it.compactArtistKeys() },
            "title keys" to { it.titleKeys() },
            "title keys without hyphens" to { it.titleKeys(); it.compactTitleKeys() },
            "catch-all songs" to { it.catchAllSongs() },
        )
        for ((name, load) in parts) {
            val before = usedHeap()
            val view = IndexView(db)
            val started = System.nanoTime()
            load(view)
            val took = ms(started)
            val heap = usedHeap() - before
            report("$name: ${view.loadedSize()} loaded in $took ms, ${heap / MIB} MiB of heap")
            check(view.db === db)  // the view is live until here
        }
        val before = usedHeap()
        val view = IndexView(db)
        val started = System.nanoTime()
        Matcher.matchSong(song, view, Overrides(), policy)
        val cold = ms(started)
        val heap = usedHeap() - before
        val warm = System.nanoTime().let { Matcher.matchSong(song, view, Overrides(), policy); ms(it) }
        report("every step on one view: $cold ms cold, $warm ms once loaded, ${heap / MIB} MiB of heap kept")
        check(view.loaded.size == 3)
        val runtime = Runtime.getRuntime()
        report("the JVM's heap: ${runtime.maxMemory() / MIB} MiB at most, ${usedHeap() / MIB} MiB in use")
    }

    // --- the index ------------------------------------------------------------------------------------------------

    private class Made(val artists: List<String>, val someSong: Pair<String, String>,
                       val longArtist: Pair<String, String>)

    private fun build(db: Db): Made {
        val raw = db.raw
        val indexes = db.query("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ug_index' " +
                                   "AND sql IS NOT NULL") { it.text(0)!! to it.text(1)!! }
        val triggers = db.query("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'ug_index'") {
            it.text(0)!!
        }
        for (t in triggers) db.execute("DROP TRIGGER \"$t\"")
        for ((name, _) in indexes) db.execute("DROP INDEX \"$name\"")
        val vocabulary = distinct(VOCABULARY) { word() }
        val artists = distinct(ARTISTS - CATCH_ALLS.size) { name(vocabulary, 1 + random.nextInt(3)) }
        val regular = TITLES - CATCH_ALL
        val titles = distinct(regular) { name(vocabulary, 1 + random.nextInt(4)) }
        var tab = 0L
        var someSong: Pair<String, String>? = null
        var longArtist: Pair<String, String>? = null
        db.savepoint("bench_index") {
            raw.prepare("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                            "VALUES (?, ?, ?, ?, '1', '2026-10-28T03:30:00Z', ?)").use { st ->
                fun row(artist: String, song: String) {
                    tab++
                    val type = TYPES[random.nextInt(TYPES.size)]
                    st.bindLong(1, tab)
                    st.bindText(2, artist)
                    st.bindText(3, song)
                    st.bindText(4, type)
                    st.bindText(5, "$artist/$song-$type-$tab")
                    st.step()
                    st.reset()
                }
                // Every artist has a title; the rest go to a few artists far more than to most.
                val owners = IntArray(regular) { if (it < artists.size) it else skewed(artists.size) }
                titles.forEachIndexed { i, title ->
                    val artist = artists[owners[i]]
                    row(artist, title)
                    if (someSong == null && title.contains('-')) someSong = artist to title
                    if (longArtist == null && artist.length >= 16 && i < artists.size) longArtist = artist to title
                }
                // The catch-alls: a show's or a performer's name, then the song's.
                repeat(CATCH_ALL) {
                    row(CATCH_ALLS[it % CATCH_ALLS.size], "${name(vocabulary, 1 + random.nextInt(2))}-" +
                        name(vocabulary, 1 + random.nextInt(3)))
                }
                // More tabs of the titles: the same key, or a variant of it.
                while (tab < ROWS) {
                    val i = skewed(regular)
                    val variant = if (random.nextInt(4) == 0) "-" + VARIANTS[random.nextInt(VARIANTS.size)] else ""
                    row(artists[owners[i]], titles[i] + variant)
                }
            }
        }
        for ((_, sql) in indexes) db.execute(sql)
        db.kvSet(Matcher.BUILT_KEY, "2026-10-28T03:30:00Z")
        val bases = db.one("SELECT COUNT(DISTINCT artist_key) FROM ug_index") { it.long(0)!! }!!
        check(bases.toInt() == ARTISTS) { "$bases artists" }
        return Made(artists, checkNotNull(someSong), checkNotNull(longArtist))
    }

    private fun <T> distinct(n: Int, make: () -> T): List<T> {
        val seen = LinkedHashSet<T>(n * 2)
        while (seen.size < n) seen += make()
        return seen.toList()
    }

    private fun word(): String = buildString {
        repeat(1 + random.nextInt(3)) { append(SYLLABLES[random.nextInt(SYLLABLES.size)]) }
    }

    private fun name(vocabulary: List<String>, n: Int): String =
        List(n) { vocabulary[skewed(vocabulary.size)] }.joinToString("-")

    /** An index below [size], the first ones far likelier. */
    private fun skewed(size: Int): Int = (size * random.nextDouble().let { it * it }).toInt().coerceIn(0, size - 1)

    /** A key as a song's name: its words, spaced. */
    private fun words(key: String): String = key.replace('-', ' ')

    /** The key with its last letter changed to another. */
    private fun misspelt(key: String): String {
        val chars = key.toCharArray()
        val at = chars.indices.filter { chars[it] != '-' }.maxBy { it }
        chars[at] = if (chars[at] == 'q') 'x' else 'q'
        return String(chars)
    }

    /** How many keys or songs a view holds of what it loaded whole. */
    private fun IndexView.loadedSize(): String = buildList {
        if ("artists" in loaded) add("${artistKeys().size} artist keys")
        if ("titles" in loaded) add("${titleKeys().size} title keys")
        if ("catch_all" in loaded) add("${catchAllSongs().size} catch-all songs")
    }.joinToString(", ")

    private fun usedHeap(): Long {
        val runtime = Runtime.getRuntime()
        repeat(3) {
            System.gc()
            Thread.sleep(100)
        }
        return runtime.totalMemory() - runtime.freeMemory()
    }

    private fun ms(started: Long): Long = (System.nanoTime() - started) / 1_000_000

    private fun report(line: String) = println("MatcherBench: $line")

    companion object {
        /** The phone's index, as the plan counts it: about 1.5 M rows, 150k artist keys, 720k title keys and 90k
         * catch-all lines. */
        const val ROWS = 1_500_000
        const val ARTISTS = 150_000
        const val TITLES = 720_000
        const val CATCH_ALL = 90_000
        const val VOCABULARY = 60_000
        private const val NOW = "2026-11-04T09:30:00Z"
        private const val MIB = 1024 * 1024

        private val CATCH_ALLS = (Match.SHOW_CATCH_ALLS + Match.PERFORMER_CATCH_ALLS).sorted()
        private val TYPES = listOf("chords", "chords", "chords", "tabs", "ukulele")
        private val VARIANTS = listOf("acoustic", "live", "intro", "solo")
        private val SYLLABLES = listOf(
            "a", "ba", "be", "bi", "bo", "bu", "ca", "ce", "ci", "co", "da", "de", "di", "do", "du", "e", "fa", "fe",
            "fi", "ga", "go", "ha", "he", "hi", "i", "ja", "jo", "ka", "ke", "ki", "ko", "la", "le", "li", "lo", "lu",
            "ma", "me", "mi", "mo", "mu", "na", "ne", "ni", "no", "o", "pa", "pe", "pi", "po", "ra", "re", "ri", "ro",
            "sa", "se", "si", "so", "su", "ta", "te", "ti", "to", "tu", "u", "va", "ve", "vi", "wa", "ya", "yo", "za",
            "ar", "er", "in", "on", "an", "en", "ul", "ed", "ow", "st", "th", "ng",
        )
    }
}
