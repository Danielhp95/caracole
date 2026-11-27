package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.YouTubeReplay
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** core.youtube against youtube.py: the corpus's records (YouTubeReplay), and a few cases by hand. */
class YouTubeRulesTest {
    private val data = YouTubeData.read()
    private val proxy = "http://u:secret@127.0.0.1:1"

    @Test fun everyRecordOfTheCorpusIsAnsweredAsPythonAnswersIt() {
        val misses = Misses(YouTubeReplay.area)
        YouTubeReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun aTargetThatHoldsPlaceholderTextGoesAsItIs() {
        val tricky = data.searchTarget(data.placeholders.values.joinToString(" "), 1)
        val argv = data.argv("search", tricky, "/c", "/q", proxy)
        assertEquals(tricky, argv.last())
        assertEquals(1, argv.count { it == proxy })
    }

    @Test fun aDownloadsFolderLosesItsTrailingSlashesAndAnEmptyOneIsRefused() {
        val url = data.watchUrl("dQw4w9WgXcQ")
        val plain = data.argv("download", url, "/c", "/q", proxy, "/a/b")
        assertEquals(plain, data.argv("download", url, "/c", "/q", proxy, "/a/b//"))
        for (into in listOf("", "/", "//")) {
            assertFailsWith<YouTubeData.Refused> { data.argv("download", url, "/c", "/q", proxy, into) }
        }
        assertFailsWith<YouTubeData.Refused> { data.argv("download", url, "/c", "/q", proxy) }
        assertFailsWith<YouTubeData.Refused> { data.argv("video", url + "&list=PL1", "/c", "/q", proxy) }
        assertFailsWith<YouTubeData.Refused> { data.argv("search", "", "/c", "/q", proxy) }
        assertFailsWith<YouTubeData.Refused> { data.argv("search", "x", "/c", "/q\u0000", proxy) }
    }

    @Test fun theExitStatusComesBeforeStderrAndTheGateBeforeBoth() {
        val blocked = "ERROR: [youtube] x: Sign in to confirm you're not a bot"
        assertEquals(Classify.OK, Classify.ofRun(Classify.OK_EXIT, blocked))
        assertEquals("blocked", Classify.ofRun(1, blocked))
        assertEquals("gate", Classify.GATE)
        assertEquals(listOf("blocked", "unavailable", "pass_over", "outdated", "error"), Classify.CLASSES)
    }

    @Test fun theSongsTopicChannelComesFirst() {
        val creep = Choose.Song("Radiohead", "Creep")
        val lyrics = Video("lyricsxxxxx", "Radiohead - Creep (Lyrics)", "7clouds", 239.0)
        val topic = Video("topicxxxxxx", "Creep", "Radiohead - Topic", 239.0)
        assertEquals(topic, Choose.choose(creep, listOf(lyrics, topic), null))
        assertEquals(lyrics, Choose.choose(creep, listOf(lyrics, topic), null, setOf(topic.id)))
        assertNull(Choose.choose(creep, listOf(topic), 270.0))
    }

    @Test fun aTemplateElementOfTwoPlaceholdersFailsAsTheDataIsRead() {
        val json = YouTubeData.read().json
        val argv = json.getValue("phone_argv").jsonObject
        val search = argv.getValue("search").jsonArray
        val twice = JsonArray(search.map { e ->
            if ("<qjs>" in e.jsonPrimitive.content) JsonPrimitive(e.jsonPrimitive.content + "<proxy>") else e
        })
        val bad = JsonObject(json + ("phone_argv" to JsonObject(argv + ("search" to twice))))
        val e = assertFailsWith<IllegalStateException> { YouTubeData.of(bad) }
        assertTrue("search" in e.message!!, e.message)
        YouTubeData.of(json)
    }
}
