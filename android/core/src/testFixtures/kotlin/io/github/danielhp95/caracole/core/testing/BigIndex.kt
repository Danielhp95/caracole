package io.github.danielhp95.caracole.core.testing

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlin.random.Random

/**
 * A big synthetic Ultimate Guitar index, for the benchmarks and the device's timings of an import and the first
 * search after it (prep-db: CheckpointBench, ColdSearchBench, ColdSearchTest): an export of `caracole index export`'s
 * layout (partial-export.jsonl's gtptabs.com and MuseScore, then [rows] ug_index rows in one sitemap), which a phone
 * merges as an import does (IndexTransfer.merge), its triggers filling the keys, their trigrams and words, the artists
 * and the full-text index as the real index's do.
 *
 * Its names are made of syllables from a seeded generator, as a real index's are of words: about [ARTISTS] artists of
 * one to three words, the busiest with hundreds of tabs and most with a few, each song a few words with a tab or two
 * (chords mostly), so a word's first letter, its length and its neighbours spread as an index's do. The same [rows]
 * and [seed] make the same export. [queries] are searches of it: an artist and a title it holds, then the same
 * misspelt, which nothing matches well, so that the search looks for close spellings too.
 */
class BigIndex(val rows: Int, val seed: Int = 7) {
    private val random = Random(seed)
    private val words: List<String> = List(WORDS) { word() }.distinct()
    private val artists: List<String> = List(ARTISTS) { name(1 + random.nextInt(3)) }.distinct()

    /** The first tab's artist and song keys, which [queries] name. */
    private var first: Pair<String, String>? = null

    /** An export of [rows] UG tabs at [file] (made anew); the partial export's other sites beside them. */
    fun export(file: File): File {
        file.delete()
        Fixtures.loadRaw(file, "index/fixtures/partial-export.jsonl")
        val c = BundledSQLiteDriver().open(file.path)
        try {
            c.execSQL("BEGIN")
            c.execSQL(
                "CREATE TABLE ug_index (tab_id INTEGER PRIMARY KEY, artist_key TEXT NOT NULL, " +
                    "song_key TEXT NOT NULL, type TEXT NOT NULL, sitemap TEXT NOT NULL, " +
                    "first_seen TEXT NOT NULL, path TEXT NOT NULL DEFAULT '')",
            )
            c.execSQL(
                "CREATE TABLE ug_artist_tabs (page TEXT NOT NULL, tab_id INTEGER NOT NULL, type TEXT NOT NULL, " +
                    "artist TEXT NOT NULL, title TEXT NOT NULL, label TEXT, rating REAL NOT NULL DEFAULT 0, " +
                    "votes INTEGER NOT NULL DEFAULT 0, url TEXT NOT NULL, artist_key TEXT NOT NULL, " +
                    "song_key TEXT NOT NULL, artist_forms TEXT NOT NULL, title_forms TEXT NOT NULL, " +
                    "forms TEXT NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY (page, tab_id))",
            )
            c.prepare(
                "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                    "VALUES (?, ?, ?, ?, 'big', '2026-10-28T03:30:00Z', ?)",
            ).use { st ->
                var id = 0L
                while (id < rows) {
                    val artist = artists[skewed(artists.size)]
                    val song = name(1 + random.nextInt(4))
                    val tabs = minOf(1 + random.nextInt(3), rows - id.toInt())
                    if (first == null) first = artist to song
                    repeat(tabs) { n ->
                        id++
                        val type = when {
                            n == 0 || random.nextInt(4) > 0 -> "chords"
                            random.nextBoolean() -> "tabs"
                            else -> "ukulele"
                        }
                        st.bindLong(1, id)
                        st.bindText(2, artist)
                        st.bindText(3, song)
                        st.bindText(4, type)
                        st.bindText(5, "$artist/$song-$type-$id")
                        st.step()
                        st.reset()
                    }
                }
            }
            val record = "{\"big\": {\"etag\": null, \"last_modified\": null, " +
                "\"indexed_at\": \"2026-10-28T03:30:00Z\", \"rows\": $rows}}"
            c.execSQL("INSERT INTO kv (key, value) VALUES ('ug:sitemaps', '$record'), ('ug:artist_tabs:keys', '2')")
            c.execSQL("UPDATE caracole_export SET value = '[\"ug\", \"gtptabs\", \"musescore\"]' WHERE key = 'sites'")
            c.execSQL("COMMIT")
        } finally {
            c.close()
        }
        return file
    }

    /** Searches of the index [export] made: an artist and a title it holds, the same misspelt, and a word alone. */
    val queries: List<String>
        get() {
            val (artist, song) = checkNotNull(first) { "no export made yet" }
            val named = "${artist.replace('-', ' ')} ${song.replace('-', ' ')}"
            // Each word of four letters or more with its first two swapped.
            val misspelt = named.split(' ').joinToString(" ") { w ->
                if (w.length > 3) w[1] + w[0].toString() + w.drop(2) else w
            }
            return listOf(named, misspelt, song.substringBefore('-'))
        }

    private fun word(): String = buildString {
        repeat(1 + random.nextInt(3)) { append(SYLLABLES[random.nextInt(SYLLABLES.size)]) }
    }

    private fun name(n: Int): String = List(n) { words[skewed(words.size)] }.joinToString("-")

    /** An index below [size], the first ones far likelier: a few names are everywhere, most are rare. */
    private fun skewed(size: Int): Int = (size * random.nextDouble().let { it * it }).toInt().coerceIn(0, size - 1)

    companion object {
        const val ARTISTS = 30_000
        const val WORDS = 200_000

        private val SYLLABLES = listOf(
            "a", "ba", "be", "bi", "bo", "bu", "ca", "ce", "ci", "co", "cu", "da", "de", "di", "do", "du", "e", "fa",
            "fe", "fi", "fo", "ga", "ge", "go", "ha", "he", "hi", "ho", "i", "ja", "jo", "ka", "ke", "ki", "ko", "la",
            "le", "li", "lo", "lu", "ma", "me", "mi", "mo", "mu", "na", "ne", "ni", "no", "nu", "o", "pa", "pe", "pi",
            "po", "ra", "re", "ri", "ro", "ru", "sa", "se", "si", "so", "su", "ta", "te", "ti", "to", "tu", "u", "va",
            "ve", "vi", "wa", "we", "ya", "yo", "za", "zo", "ar", "er", "in", "on", "an", "en", "ul", "ix", "ed", "ow",
        )

        /** A database's files as a phone killed with it open leaves them ([from] and its -wal and -shm) at [to]: the
         * next start opens what the last one wrote, its WAL and all, never a copy closed cleanly. */
        fun killedCopy(from: File, to: File): File {
            to.parentFile?.mkdirs()
            for (suffix in listOf("", "-wal", "-shm")) {
                val source = File(from.path + suffix)
                val target = File(to.path + suffix)
                if (source.exists()) Files.copy(source.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
                else target.delete()
            }
            return to
        }
    }
}
