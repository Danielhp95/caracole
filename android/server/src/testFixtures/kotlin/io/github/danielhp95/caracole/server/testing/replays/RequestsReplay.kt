package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.server.jobs.Feed
import io.github.danielhp95.caracole.server.jobs.JobHistory
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.page.RequestsTab
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.time.Instant
import java.time.ZoneId

/**
 * The Requests tab (vectors/web/requests.jsonl, tests/test_conformance_requests.py's docstring has its shapes), every
 * record answered as caracole serve answered it: feed.py's words; `_ordinal` and `_ago`; `stamps.shown(local=True)`
 * under each record's zone (the phone's ZoneNames: Python's `%Z`); library_page's Requests tab for a count; and the
 * Requests tab's answer itself, Feed's, byte for byte, its jobs read back from their history lines (JobHistory.jobOf).
 */
object RequestsReplay : AreaReplay {
    override val area = "requests"
    const val VECTOR = "web/requests.jsonl"

    override fun replay(misses: Misses) {
        val tab = RequestsTab.load()
        for (r in Corpus.records(VECTOR)) {
            when (r.fn) {
                "tables" -> tables(r, misses)
                "caracole.web.feed._ordinal" -> misses.expect(r) { Feed.ordinal(r.args[0].jsonPrimitive.long) }
                "caracole.web.feed._ago" -> misses.expect(r) {
                    Feed.ago(time(r.args[0].jsonPrimitive.content), time(r.args[1].jsonPrimitive.content))
                }
                "caracole.stamps.shown" -> misses.expect(r.fn, "${r.args} in ${zone(r)}", r.out) {
                    Feed.shown(r.args[0].jsonPrimitive.contentOrNull?.let(::time), ZoneId.of(zone(r)))
                }
                "caracole.library_page._requests_tab" -> misses.expect(r.fn, r.extra["active"], r.out) {
                    tab.tab(r.extra.getValue("active").jsonPrimitive.int)
                }
                "caracole.web.feed.feed" -> feed(r, misses)
                else -> misses.check(false) { "a record of no known call: ${r.fn}" }
            }
        }
    }

    private fun tables(r: Record, misses: Misses) {
        val out = r.out!!.jsonObject
        misses.check(out.getValue("STATE_TEXT") == JsonObject(Feed.STATE_TEXT.mapValues { JsonPrimitive(it.value) })) {
            "STATE_TEXT is ${Feed.STATE_TEXT}, Python's ${out["STATE_TEXT"]}"
        }
        misses.check(out.getValue("PRIMARY").jsonArray.map { it.jsonPrimitive.content }.toSet() == Feed.PRIMARY) {
            "PRIMARY is ${Feed.PRIMARY}, Python's ${out["PRIMARY"]}"
        }
        for ((name, ours) in listOf("SEARCH" to Feed.SEARCH, "PICK_STAGE" to Feed.PICK_STAGE, "PICK_STEP" to Feed.PICK_STEP)) {
            misses.check(out.getValue(name).jsonPrimitive.content == ours) { "$name is $ours, Python's ${out[name]}" }
        }
    }

    /** A feed record: its jobs read back from their lines, its lines, outcomes, steps and picks as the record holds
     * them, under its zone; Feed's answer as `json_response` writes it. */
    fun answer(r: Record): String {
        val x = r.extra
        val jobs = x.getValue("jobs").jsonArray.map { JobHistory.jobOf(it.jsonObject) }
        val lines = x.getValue("lines").jsonObject.entries.associate { (id, line) -> id.toInt() to line(line.jsonObject) }
        val outcomes = x.getValue("outcomes").jsonObject.entries
            .filter { it.value !is JsonNull }.associate { (id, said) -> id.toInt() to said.jsonObject }
        val steps = x.getValue("steps").jsonObject.entries
            .associate { (id, chips) -> id.toInt() to chips.jsonArray.map { it.jsonObject } }
        val picks = x.getValue("picks").jsonObject.mapValues { (_, pick) ->
            Feed.Pick(pick.jsonObject.getValue("song_id").jsonPrimitive.long, pick.jsonObject.getValue("search").jsonPrimitive.boolean)
        }
        val opened = x.getValue("opened").jsonArray.map { it.jsonPrimitive.int }.toSet()
        val shown = Feed.feed(jobs, lines, outcomes, steps, picks, opened, time(x.getValue("now").jsonPrimitive.content),
                              ZoneId.of(zone(r)))
        return PyJson.dumps(shown, compact = true)
    }

    private fun feed(r: Record, misses: Misses) {
        val want = r.out!!.jsonPrimitive.content
        val got = try {
            answer(r)
        } catch (e: Exception) {
            misses.check(false) { "feed(${r.extra["note"]}, ${zone(r)}) threw $e" }
            return
        }
        misses.check(got == want) {
            val at = got.indices.firstOrNull { it >= want.length || got[it] != want[it] } ?: want.length
            "feed(${r.extra["note"]}, ${zone(r)}) differs at $at: …${got.substring(maxOf(0, at - 60), minOf(got.length, at + 80))}…" +
                " Python's …${want.substring(maxOf(0, at - 60), minOf(want.length, at + 80))}…"
        }
    }

    /** status.Line from its as_json. */
    fun line(o: JsonObject): Line {
        val link = o["link"] as? JsonObject
        return Line(o.getValue("tone").jsonPrimitive.content, o.getValue("text").jsonPrimitive.content,
                    link?.let { it.getValue("label").jsonPrimitive.content to it.getValue("href").jsonPrimitive.content },
                    (o["details"] as? JsonPrimitive)?.contentOrNull)
    }

    fun zone(r: Record): String = r.extra.getValue("tz").jsonPrimitive.content

    /** A time as history.py writes it (isoformat). */
    fun time(text: String): Instant = Stamps.instant(Stamps.fromisoformat(text))
}
