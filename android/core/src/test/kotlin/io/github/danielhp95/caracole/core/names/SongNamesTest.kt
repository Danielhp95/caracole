package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * song_names.py against vectors/search/names.jsonl: `clean`, `clean_channel`, and `read_names` with no database and
 * no songs, or over a fixture (vectors/search/fixtures/<name>.jsonl) replayed into a fresh database with its songs
 * (`songs.list_songs`), as Python read them (tests/test_conformance_search.py). The records are SearchReplay.names',
 * which the device runs too.
 */
class SongNamesTest {
    private val records = Corpus.records(VECTOR)

    @Test fun everyRecordIsOneOfSongNamesFunctions() {
        assertEquals(emptySet(), records.map { it.fn }.toSet() - SearchReplay.NAMES_FNS)
        assertTrue(records.none { it.err != null }, "Python raised on a record")
    }

    @Test fun aTextLosesWhatAVideosTitleAddsToASongsName() =
        Misses("$VECTOR $CLEAN").also { SearchReplay.names(it, setOf(CLEAN)) }.assertNone()

    @Test fun aChannelsNameLosesItsLabelWords() =
        Misses("$VECTOR $CLEAN_CHANNEL").also { SearchReplay.names(it, setOf(CLEAN_CHANNEL)) }.assertNone()

    @Test fun aTextNamesTheArtistAndTitlePythonReads() =
        Misses("$VECTOR $READ_NAMES").also { SearchReplay.names(it, setOf(READ_NAMES)) }.assertNone()

    @Test fun noDatabaseKnowsOnlyTheChannelGiven() {
        assertEquals(null, SongNames.readNames(null, "silvana estrada que problema", emptyList()))
        assertEquals("Silvana Estrada" to "que problema",
                     SongNames.readNames(null, "Silvana Estrada - que problema", emptyList()))
        assertEquals("Radiohead" to "Creep", SongNames.readNames(null, "Creep", emptyList(), channel = "Radiohead - Topic"))
    }

    /** IGNORECASE as sre reads it, beyond ASCII: its "i" is İ and ı too. What song_names.py answered, on Python
     * 3.14.7 (names.jsonl's words are ASCII alone). */
    @Test fun aChannelsLabelWordsGoInAnyCaseSreFolds() {
        val python = listOf(
            "Radiohead - TOPİC" to "Radiohead",
            "Radiohead - topıc" to "Radiohead",
            "Shakira OFFİCİAL" to "Shakira",
            "Shakira offıcıal" to "Shakira",
            "Juanes Oficıal CHANNEL" to "Juanes",
            "KKR - Topic" to "KKR",
        )
        for ((channel, name) in python) assertEquals(name, SongNames.cleanChannel(channel), channel)
        assertEquals("Silvana Estrada" to "Que problema",
                     SongNames.readNames(null, "Que problema bY Silvana Estrada", emptyList(), channel = "Silvana Estrada"))
    }

    companion object {
        const val VECTOR = SearchReplay.NAMES
        const val CLEAN = SearchReplay.CLEAN
        const val CLEAN_CHANNEL = SearchReplay.CLEAN_CHANNEL
        const val READ_NAMES = SearchReplay.READ_NAMES
    }
}
