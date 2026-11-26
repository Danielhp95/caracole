package io.github.danielhp95.caracole.server.jobs

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** web/jobs.py's lyrics search and lyrics pick as the phone tells them apart (the vectors hold their stages and
 * progress lines): the search a lookup of no song's, the pick its song's. */
class JobCommandsTest {
    private val search = listOf("lyrics", "--song=A - T (Live)", "--as=A - T")
    private val pick = listOf("lyrics", "--song=A - T (Live)", "--record=lrclib:28399373", "--progress")

    @Test
    fun aLyricsSearchIsALookupOfNoSongsAndAPickIsItsSongs() {
        assertTrue(JobCommands.INDEX_READS.any { (JobCommands.LYRICS_SEARCH + "a/t").startsWith(it) })
        assertEquals(JobCommands.LYRICS_SEARCH + "a/t", JobCommands.songKeyOf(JobCommands.LYRICS_SEARCH + "a/t"))
        assertEquals("a/t", JobCommands.songKeyOf(JobCommands.LYRICS_PICK + "a/t"))
        assertEquals("a/t", JobCommands.songKeyOf(JobCommands.LYRICS_CLEAR + "a/t"))  // a clear's view is the song's
        assertTrue(JobCommands.isLookup(search))
        assertFalse(JobCommands.isLookup(pick))
        assertFalse(JobCommands.isLookup(listOf("lyrics", "--song=A - T", "--clear")))
        assertFalse(JobCommands.isLookup(listOf("lyrics", "--", "--as=x")))
        assertTrue(JobCommands.picksLyrics(pick))
        assertTrue(JobCommands.picksLyrics(listOf("lyrics", "--song=A - T", "--pick=1")))
        assertFalse(JobCommands.picksLyrics(search))
        assertFalse(JobCommands.picksLyrics(listOf("lyrics", "--", "--record=x")))
        assertEquals(JobCommands.LYRICS_PICK_STAGES, JobCommands.stages(listOf(pick)))
    }
}
