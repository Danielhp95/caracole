package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.youtube.AnswerError
import io.github.danielhp95.caracole.core.youtube.Choose
import io.github.danielhp95.caracole.core.youtube.Classify
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * youtube.py's phone half (tests/test_conformance_youtube.py), area `youtube`:
 *
 * - argv.jsonl: each `phone` record's argv as YouTubeData.argv fills its template in one pass, or its refusal; the
 *   `computer` records are the computer's own runs, which the phone never makes (passed over, counted);
 * - classify.jsonl: Classify.ofRun of each run's exit status and stderr (`ok` for an exit of 0);
 * - parse.jsonl: Videos.parseSearch, parseVideo and searchQuery, each video's duration as Python's repr, an
 *   AnswerError in Python's words (where its record gives them) or an ArithmeticException for its OverflowError;
 * - choose.jsonl: Choose.choose's video and Choose.ranked's videos with their keys.
 */
object YouTubeReplay : AreaReplay {
    override val area = "youtube"

    override fun replay(misses: Misses) {
        val counts = mapOf("argv" to argv(misses), "classify" to classify(misses), "parse" to parse(misses),
            "choose" to choose(misses))
        for ((name, n) in counts) misses.check(n > 0) { "youtube/$name.jsonl holds no record" }
    }

    private fun records(name: String): List<JsonObject> =
        Corpus.lines("youtube/$name.jsonl").filter { it["header"]?.jsonPrimitive?.content != "true" }

    private fun text(o: JsonObject, key: String): String? = (o[key] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.content

    private fun argv(misses: Misses): Int {
        val data = YouTubeData.read()
        var n = 0
        for (r in records("argv")) {
            val phone = r["phone"]?.jsonObject ?: continue // the computer's own runs: not the phone's
            n++
            val what = text(phone, "what")!!
            val got = try {
                data.argv(what, text(phone, "target")!!, text(phone, "cache_dir")!!, text(phone, "qjs")!!,
                    text(phone, "proxy")!!, text(phone, "into"))
            } catch (e: YouTubeData.Refused) {
                null
            }
            val refused = r["refused"]?.jsonPrimitive?.boolean == true
            if (refused) {
                misses.check(got == null) { "phone_argv($phone): Python refused it, the phone gave $got" }
            } else {
                val want = r.getValue("argv").jsonArray.map { it.jsonPrimitive.content }
                misses.check(got == want) { "phone_argv($phone) = $got, Python's $want" }
            }
        }
        return n
    }

    private fun classify(misses: Misses): Int {
        var n = 0
        for (r in records("classify")) {
            n++
            val stderr = text(r, "stderr")!!
            val exit = r.getValue("exit").jsonPrimitive.int
            val want = text(r, "class")!!
            val got = Classify.ofRun(exit, stderr)
            misses.check(got == want) { "classify(exit $exit, ${PyJson.dumps(r.getValue("stderr")).take(200)}) = $got, Python's $want" }
        }
        return n
    }

    private fun repr(d: Double): String = when {
        d.isNaN() -> "nan"
        d == Double.POSITIVE_INFINITY -> "inf"
        d == Double.NEGATIVE_INFINITY -> "-inf"
        else -> PyJson.floatText(d)
    }

    private fun shown(v: Video): List<Any?> = listOf(v.id, v.title, v.channel, v.duration?.let(::repr), v.live, v.short)

    private fun wanted(v: JsonElement): List<Any?> = v.jsonArray.let {
        listOf(it[0].jsonPrimitive.content, it[1].jsonPrimitive.content, it[2].jsonPrimitive.content,
            it[3].jsonPrimitive.contentOrNull, it[4].jsonPrimitive.boolean, it[5].jsonPrimitive.boolean)
    }

    private fun parse(misses: Misses): Int {
        var n = 0
        for (r in records("parse")) {
            n++
            val fn = text(r, "fn")!!
            if (fn == "search_query") {
                val got = Videos.searchQuery(text(r, "artist")!!, text(r, "title")!!)
                misses.check(got == text(r, "query")) { "search_query(${r["artist"]}, ${r["title"]}) = $got, Python's ${r["query"]}" }
                continue
            }
            val input = text(r, "text")!!
            val shownInput = PyJson.dumps(r.getValue("text")).take(160)
            val got: Any = try {
                if (fn == "parse_search") Videos.parseSearch(input).map(::shown) else shown(Videos.parseVideo(input, text(r, "id")!!))
            } catch (e: AnswerError) {
                "ProviderError" to e.message
            } catch (e: ArithmeticException) {
                "OverflowError" to null
            }
            val error = text(r, "error")
            when {
                error != null -> {
                    val message = text(r, "message")
                    misses.check(got is Pair<*, *> && got.first == error && (message == null || got.second == message)) {
                        "$fn($shownInput) = $got, Python raised $error: $message"
                    }
                }
                fn == "parse_search" -> {
                    val want = r.getValue("videos").jsonArray.map(::wanted)
                    misses.check(got == want) { "$fn($shownInput) = $got, Python's $want" }
                }
                else -> {
                    val want = wanted(r.getValue("video"))
                    misses.check(got == want) { "$fn($shownInput) = $got, Python's $want" }
                }
            }
        }
        return n
    }

    private fun choose(misses: Misses): Int {
        var n = 0
        for (r in records("choose")) {
            n++
            val s = r.getValue("song").jsonArray
            val song = Choose.Song(s[0].jsonPrimitive.content, s[1].jsonPrimitive.content,
                s[2].jsonArray.map { it.jsonPrimitive.content })
            val videos = r.getValue("videos").jsonArray.map {
                val v = it.jsonArray
                Video(v[0].jsonPrimitive.content, v[1].jsonPrimitive.content, v[2].jsonPrimitive.content,
                    v[3].jsonPrimitive.doubleOrNull, v[4].jsonPrimitive.boolean, v[5].jsonPrimitive.boolean)
            }
            val expected = (r["expected"] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.double
            val skip = r.getValue("skip").jsonArray.map { it.jsonPrimitive.content }.toSet()
            val chosen = Choose.choose(song, videos, expected, skip)?.id
            val ranked = Choose.ranked(song, videos, expected, skip).map {
                listOf(it.video.id, it.tier, -it.title, it.close, -it.official, it.rank)
            }
            val want = (r["chosen"] as? JsonElement)?.takeIf { it !is JsonNull }?.jsonPrimitive?.content
            val wantRanked = (r.getValue("ranked") as JsonArray).map { row ->
                row.jsonArray.mapIndexed { i, e -> if (i == 0) e.jsonPrimitive.content else e.jsonPrimitive.int }
            }
            misses.check(chosen == want && ranked == wantRanked) {
                "choose(${r["song"]}, ${r["videos"].toString().take(300)}, $expected, $skip) = $chosen $ranked, " +
                    "Python's $want $wantRanked"
            }
        }
        return n
    }
}
