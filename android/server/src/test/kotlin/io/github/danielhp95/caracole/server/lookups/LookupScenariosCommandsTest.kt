package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * The computer's `caracole versions --choose` and `--clear` against the phone's own (vectors/lookup/commands_get.jsonl,
 * tests/test_conformance_lookup_scenarios.py's): each record's world made as LookupScenariosReplay makes one, then
 * [VersionsRunner] given the command line the phone queues ([JobCommands.versionSteps]) over the world's parts, its
 * job's context keeping what it is told. Compared as the replay compares a lookup, of what the run tells: the stage
 * stream, and from it each stage's end, the song and the files readable; the command's own lines and get's totals
 * (its output, as versions_cmd.py's own lines are picked from Python's: those of `Took ` and `No [pin] `, then the
 * last); the tab address the lookup was given (the `[pin]` its match stage read); and every request, event, row, kv
 * record and file.
 */
class LookupScenariosCommandsTest {
    private val cases: List<String> = Corpus.lines(LookupScenariosReplay.COMMANDS)
        .filter { it["header"] != JsonPrimitive(true) }.map { it.getValue("case").jsonPrimitive.content }

    /** A job's context that tells the replay's progress what it hears, and keeps the stages' ends and its lines. */
    private class Told(private val progress: Progress) : JobContext {
        val said = ArrayList<String>()
        val states = LinkedHashMap<String, JsonElement>()
        val details = LinkedHashMap<String, JsonElement>()
        var song: Pair<Long, String>? = null
        var files: Map<String, String> = emptyMap()

        override fun stage(name: String, state: String, detail: String) {
            progress.stage(name, state, detail)
            if (state == "running") return
            states[name] = JsonPrimitive(state)
            details[name] = JsonPrimitive(detail)
        }

        override fun say(line: String) {
            said += line
        }

        override fun song(id: Long, display: String) {
            progress.song(id, display)
            song = id to display
        }

        override fun readable(files: Map<String, String>, seconds: Double) {
            progress.readable(files, seconds)
            this.files = files
        }

        override fun outcome(value: JsonObject) {}
        override val isCancelled: Boolean = false
    }

    /** versions_cmd.py's `choose` and `clear` as the phone runs them. */
    private val versions = LookupScenariosReplay.Run { w ->
        val display = w.kw.getValue("display").jsonPrimitive.content
        val (artist, title) = display.split(" - ", limit = 2)
        val steps = when (w.fn) {
            "caracole.versions_cmd.choose" -> JobCommands.versionSteps(artist, title,
                                                                       choose = w.kw.getValue("tab").jsonPrimitive.content)
            "caracole.versions_cmd.clear" -> JobCommands.versionSteps(artist, title)
            else -> throw AssertionError("no versions command runs ${w.fn}")
        }
        val scope = CoroutineScope(SupervisorJob())
        try {
            val state = File(w.cacheDir.parentFile, "state").apply { mkdirs() }
            val parts = PhoneParts(w.database, w.store, state, { w.config }, JobQueue(scope), MirrorPageData(null),
                                   { w.clients() }, SongPages.NONE, SongbookPages.NONE, Alerts.NONE, w.pacing,
                                   searchesLacuerda = false)
            var address: String? = null
            val all = SiteStages.ALL
            val seen = SiteStages(SiteStage { ctx ->
                address = ctx.overrides.pinUrls[ctx.song.key]?.singleOrNull()
                all.match.run(ctx)
            }, all.ugSheet, all.ug, all.lacuerdaPick, all.lacuerda, all.lrclib, all.megalobiz, all.azlyrics, all.gtptabs,
                                  all.harptabs, all.gametabs)
            val told = Told(w.progress)
            val exit = try {
                runBlocking { VersionsRunner(parts, stages = seen).run(steps.single().args, told) }
                null
            } catch (e: CommandExit) {
                "exited ${e.code}: ${e.message}"
            }
            val own = told.said.filter { it.startsWith("Took ") || it.startsWith("No [pin] ") }
            LookupScenariosReplay.Ran(JsonObject(mapOf(
                "song_id" to (told.song?.first?.let(::JsonPrimitive) ?: JsonNull),
                "display" to JsonPrimitive(told.song?.second ?: display),
                "states" to JsonObject(told.states),
                "details" to JsonObject(told.details),
                "files" to JsonObject(told.files.mapValues { JsonPrimitive(it.value) }),
                "bug" to (exit?.let(::JsonPrimitive) ?: JsonNull),
            )), said = own + listOfNotNull(told.said.lastOrNull()), address = address)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun everyVersionsCommandDoesWhatPythonsDid() {
        val misses = Misses("lookup-scenarios commands")
        val replayed = LookupScenariosReplay.replay(LookupScenariosReplay.COMMANDS, misses, versions)
        misses.assertNone()
        assertEquals(cases, replayed)
        for (w in listOf("--choose", "--clear")) assertTrue(cases.any { w in it }, "no case of $w among $cases")
    }

    @Test
    fun aCommandThatStraysFromPythonsIsTold() {
        fun result(r: JsonObject): JsonObject = r.getValue("out").jsonObject.getValue("result").jsonObject
        fun withResult(r: JsonObject, field: String, value: JsonElement): JsonObject {
            val out = r.getValue("out").jsonObject
            return JsonObject(r + ("out" to JsonObject(out + ("result" to JsonObject(result(r) + (field to value))))))
        }
        val strays = mapOf<String, (JsonObject) -> JsonObject>(
            "said" to { r -> withResult(r, "said", JsonArray(listOf(JsonPrimitive("Done.")))) },
            "address" to { r -> withResult(r, "address", JsonPrimitive("https://tabs.ultimate-guitar.com/tab/1")) },
            "progress" to { r -> withResult(r, "progress", JsonArray(emptyList())) },
            "details" to { r ->
                val said = result(r).getValue("result").jsonObject
                val details = said.getValue("details").jsonObject
                withResult(r, "result", JsonObject(said + ("details" to JsonObject(details + ("song" to JsonPrimitive("?"))))))
            },
            "requests" to { r ->
                val out = r.getValue("out").jsonObject
                JsonObject(r + ("out" to JsonObject(out + ("requests" to JsonArray(listOf(JsonPrimitive("GET x")))))))
            },
        )
        for (case in cases) {
            for ((what, stray) in strays) {
                val misses = Misses("strayed")
                LookupScenariosReplay.replay(LookupScenariosReplay.COMMANDS, misses, versions, only = setOf(case),
                                             edit = stray)
                val failed = runCatching { misses.assertNone() }.exceptionOrNull()
                assertNotNull(failed, "$case: a record whose $what strays passed")
                assertTrue(failed.message.orEmpty().contains("$case: "), "$case: its $what stray isn't told as its own")
            }
        }
    }
}
