package io.github.danielhp95.caracole.core.lyrics

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** lyrics.py's model: an LRCLIB record read, stored lyrics read back. */
class LyricsTest {
    @Test fun anLrclibRecordLosesItsIdTagsAndTakesItsPlainFromTheSyncedWhenMissing() {
        val record = Json.parseToJsonElement("""{"id": 7, "duration": 212.0, "instrumental": false,
            "plainLyrics": "", "syncedLyrics": "[ti:x]\n[00:01.00]One <00:01.50>two\n[00:03.00]\n[00:05.00]Three\n[00:07.00]"}""").jsonObject
        val lyrics = Lyrics.fromRecord(record)
        assertEquals("One two\n\nThree", lyrics.plain)
        assertEquals(7L, lyrics.lrclibId)
        assertEquals(212.0, lyrics.duration)
        assertEquals("lrclib", lyrics.provider)
        val tagged = Lyrics.fromRecord(Json.parseToJsonElement("""{"plainLyrics": "[ar:Y]\nLine\n[length: 3:00]"}""").jsonObject)
        assertEquals("Line", tagged.plain)
        assertNull(tagged.synced)
    }

    @Test fun storedLyricsReadBack() {
        val stored = """{"plain": "a", "synced": null, "instrumental": false, "duration": 1.5, "lrclib_id": null,
            "raw": {}, "provider": "megalobiz", "url": "https://www.megalobiz.com/lrc/maker/x"}"""
        val lyrics = lyricsFromJson(stored)!!
        assertEquals("megalobiz", lyrics.provider)
        assertEquals(lyrics, lyricsFromJson(lyrics.toJson()))
        assertNull(lyricsFromJson(null))
        assertNull(lyricsFromJson(" "))
    }
}
