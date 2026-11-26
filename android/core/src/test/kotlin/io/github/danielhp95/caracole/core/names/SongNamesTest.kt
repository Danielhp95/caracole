package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
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

    /** A known artist of your library before a tag bracket or a title bracket, which names.jsonl can't hold (no fixture
     * knows 周杰倫): what song_names.py answered on Python 3.14.7, with no database and these two songs (credible: two
     * of theirs). */
    @Test fun aKnownArtistOfYoursBeforeABracketIsTheArtist() {
        val songs = listOf(song(1, "晴天"), song(2, "稻香"))
        assertEquals("周杰倫" to "七里香【Live】", SongNames.readNames(null, "周杰倫 七里香【Live】", songs))
        assertEquals("周杰倫" to "七里香", SongNames.readNames(null, "周杰倫 七里香《周杰倫的床邊故事》", songs))
        assertEquals("周杰倫 Jay Chou" to "告白氣球 Love Confession",
                     SongNames.readNames(null, "周杰倫 Jay Chou【告白氣球 Love Confession】Official MV", songs))
        assertEquals(null, SongNames.readNames(null, "周杰倫 七里香【Live】", emptyList()))
    }

    /** A long quote of Latin words after an artist of your library, whole, is the title, else a lyric
     * (helpers/song_name_cases.py's KNOWN): what song_names.py answers with these two songs, and with none. */
    @Test fun aLongLatinQuoteAfterAnArtistOfYoursIsTheTitle() {
        val songs = listOf(song(1, "1", "LiSA"), song(2, "2", "LiSA"))
        assertEquals("LiSA" to "Rising Hope and Glory", SongNames.readNames(null, "LiSA「Rising Hope and Glory」", songs))
        assertEquals(null, SongNames.readNames(null, "LiSA「Rising Hope and Glory」", emptyList()))
    }

    private fun song(id: Long, title: String, artist: String = "周杰倫") = SongRow(
        id = id, key = Normalize.identityKey(artist, title), artist = artist, title = title, artists = listOf(artist),
        album = null, durationMs = null, isrc = null, sourceIds = "{}", addedAt = "2026-11-25T00:00:00Z",
        variant = null, status = "wanted", review = false, matchDecision = null, matchStep = null, matchScore = null,
        matchArtistKey = null, matchSongKey = null, matchCandidates = "[]", matchedAt = null, ugDirty = false,
        ugCheckedAt = null, lyricsStatus = "pending", lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null,
        createdAt = "2026-11-25T00:00:00Z",
    )

    companion object {
        const val VECTOR = SearchReplay.NAMES
        const val CLEAN = SearchReplay.CLEAN
        const val CLEAN_CHANNEL = SearchReplay.CLEAN_CHANNEL
        const val READ_NAMES = SearchReplay.READ_NAMES
    }
}
