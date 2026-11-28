package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.testing.replays.AudioRoutesReplay
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The audio routes on the phone (vectors/web/audio_routes.jsonl: POST /audio/upload, /audio and /audio/drop over
 * each scene, answered as caracole serve answered them; the routes' declared bodies and limits). */
class AudioRoutesTest {
    @Test fun `each route answers as caracole serve's over each scene`() {
        val misses = Misses("web: audio_routes.jsonl")
        WebReplay.audioRoutes(misses)
        misses.assertNone()
        assertTrue(misses.checked > 80, "${misses.checked} answers checked")
    }

    @Test fun `the routes declare caracole serve's bodies and limits, the upload spooled`() {
        val misses = Misses("web: audio_routes.jsonl's limits")
        AudioRoutesReplay.limits(misses)
        misses.assertNone()
    }

    @Test fun `the uploads named are those the waiting and running sheets from a file name`() {
        val queue = JobQueue(CoroutineScope(Job().apply { cancel() }))
        fun queued(key: String, vararg args: String) = queue.submit(JobSpec(
            title = key, key = key, kind = "song", stages = emptyList(), commands = listOf(Command("x", args.toList()))))
        queued("audio:a/b", "audio", "--progress", "--upload=0123456789abcdef", "--song=A - B")
        queued("audio:c/d", "audio", "--progress", "--upload=fedcba9876543210", "--song=C - D")
        queued("c/d", "get", "--upload=1111111111111111")  // no sheet from a file: names none
        assertEquals(setOf("0123456789abcdef", "fedcba9876543210"), JobCommands.uploadsNamed(queue.snapshot()))
        queue.cancel(queue.snapshot().first { it.key == "audio:a/b" }.id)
        assertEquals(setOf("fedcba9876543210"), JobCommands.uploadsNamed(queue.snapshot()))
    }

    @Test fun `a file's name is less its last suffix and its track number, as pathlib and music py read it`() {
        val cases = mapOf("03 - A - B.mp3" to "A - B", "...mp3" to "...mp3", ".mp3" to ".mp3", "." to "",
                          "12 Song.tar.gz" to "Song.tar", "7.mp3" to "7", "07. Song.flac" to "Song")
        for ((name, bare) in cases) assertEquals(bare, AudioRoutes.bareName(name), name)
    }
}
