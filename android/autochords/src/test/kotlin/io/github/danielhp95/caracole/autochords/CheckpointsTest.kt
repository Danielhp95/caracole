package io.github.danielhp95.caracole.autochords

import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** [Checkpoints]' writes: a part forced to the disk, renamed into place, then the folder itself forced, so the
 * rename is on the disk too; a platform that won't force a folder is passed over quietly. */
class CheckpointsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun `the folder is forced to the disk after each rename, its new name there`() {
        val audio = tmp.newFile("a.wav").apply { writeBytes(byteArrayOf(1, 2, 3)) }
        val synced = mutableListOf<Pair<File, Boolean>>()
        val points = Checkpoints.of(tmp.newFolder(), audio) { folder ->
            synced += folder to File(folder, Checkpoints.CHORDS).isFile
        }
        points.write(Checkpoints.CHORDS, Checkpoints.chordsJson(emptyList()))
        assertEquals(listOf(points.folder to true), synced)
    }

    @Test
    fun `forcing a folder is quiet where the platform refuses it`() {
        Checkpoints.syncFolder(File(tmp.root, "none"))
        Checkpoints.syncFolder(tmp.newFolder())
        val audio = tmp.newFile("b.wav").apply { writeBytes(byteArrayOf(4)) }
        val points = Checkpoints.of(tmp.newFolder(), audio)
        points.write(Checkpoints.BEATS, Checkpoints.beatsJson(listOf(1.0), emptyList()))
        assertTrue(points.has(Checkpoints.BEATS))
        assertFalse(File(points.folder, Checkpoints.BEATS + Checkpoints.PART).exists())
    }
}
