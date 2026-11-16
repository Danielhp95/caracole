package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.server.http.Refused
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class SongFormTest {
    @Test
    fun aControlCharacterInANameIsRefusedAsTheComputerRefusesIt() {
        // library_routes.wanted_line: a NUL would reach wanted.txt and a command no process can be started with,
        // and a song the phone took one with would carry it to the computer at a sync.
        for (form in listOf(
            mapOf("artist" to "Radio\u0000head", "title" to "Creep"),
            mapOf("artist" to "Radiohead", "title" to "Creep\u001b[2J"),
            mapOf("artist" to "Radiohead", "title" to "Creep", "album" to "Pablo\u0000Honey"),
        )) {
            val refused = assertThrows(Refused::class.java) { SongForm.song(form) }
            assertEquals(400, refused.status)
            assertTrue(refused.message!!, refused.message!!.contains("holds a control character"))
        }
        // whitespace is no control character a name can't hold: wanted.txt's line folds it into a space
        assertEquals("Creep Oasis", SongForm.song(mapOf("artist" to "Radiohead", "title" to "Creep\tOasis")).title)
    }
}
