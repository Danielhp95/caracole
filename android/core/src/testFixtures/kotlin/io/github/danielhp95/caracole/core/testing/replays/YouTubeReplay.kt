package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.youtube.FakeYtDlpProcess
import io.github.danielhp95.caracole.core.youtube.AnswerError
import io.github.danielhp95.caracole.core.youtube.Choose
import io.github.danielhp95.caracole.core.youtube.Classify
import io.github.danielhp95.caracole.core.youtube.Download
import io.github.danielhp95.caracole.core.youtube.Due
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import java.io.File
import java.nio.file.Files
import java.time.Duration
import java.time.Instant
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * youtube.py's phone half (tests/test_conformance_youtube.py), area `youtube`:
 *
 * - argv.jsonl: each `phone` record's argv as YouTubeData.argv fills its template in one pass, or its refusal; the
 *   `computer` records are the computer's own runs, which the phone never makes (passed over, counted);
 * - classify.jsonl: Classify.ofRun of each run's exit status and stderr (`ok` for an exit of 0);
 * - parse.jsonl: Videos.parseSearch, parseVideo and searchQuery, each video's duration as Python's repr, an
 *   AnswerError in Python's words (where its record gives them); a record with `phone` (a well-formed text nested past
 *   PyJson's depth) the phone's AnswerError, not Python's answer;
 * - choose.jsonl: Choose.choose's video and Choose.ranked's videos with their keys;
 * - runs.jsonl: YtDlp over [FakeYtDlpProcess] replaying each scenario's recorded runs, through a real HostGate in
 *   loopback mode, on a fresh database: each call's outcome (the phone's class where classify, beside, says
 *   pass_over or outdated; Python's otherwise, its message too), each run's argv (the phone's template of the
 *   record's kind, target and folder, the gate's proxyArg in it once), the events, the draws and the pauses, the runs
 *   made, the block's record (Health's state: its message, the cooldown from the job's start), and kv
 *   `http:last_request:youtube` written once a run was sent;
 * - gate.jsonl: SearchGate.gate (with its suggestion, /api/search's `youtube`) and videoGate over each scene's kv and
 *   events on a fresh database, YouTube on or off in the phone's settings; recordFailure's kv text byte for byte; and
 *   sheetOnScreen of each record's hits;
 * - record.jsonl: Records.load of each stored text, then Records.save, its kv text byte for byte;
 * - due.jsonl: Due.songs over each scene's fixture library and overrides (`ignore`, `youtube`, `lacuerda`) at its
 *   `now`, unpaired (`due`) and paired (`paired`), the songs' ids in Python's order;
 * - video_cmd.jsonl's `checked_jpeg` records: Thumbs.checkedJpeg of each synthetic head (its command's records are
 *   :server's YouTubeVideoReplay's).
 */
object YouTubeReplay : AreaReplay {
    override val area = "youtube"

    override fun replay(misses: Misses) {
        val counts = mapOf("argv" to argv(misses), "classify" to classify(misses), "parse" to parse(misses),
            "choose" to choose(misses), "runs" to runs(misses), "gate" to gate(misses), "record" to record(misses),
            "video_cmd" to jpegs(misses), "due" to due(misses))
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
            }
            val error = text(r, "error")
            val phone = r["phone"]?.jsonObject
            when {
                phone != null -> misses.check(got is Pair<*, *> && got.first == text(phone, "error")) {
                    "$fn($shownInput) = $got, where the phone's answer is ${text(phone, "error")}: ${text(phone, "why")}"
                }
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

    private fun runs(misses: Misses): Int {
        val data = YouTubeData.read()
        var n = 0
        for (r in records("runs")) {
            n++
            val name = text(r, "scenario")!!
            val delay = r.getValue("delay").jsonArray.let { it[0].jsonPrimitive.double to it[1].jsonPrimitive.double }
            val timeouts = r.getValue("timeouts").jsonArray.let { it[0].jsonPrimitive.double to it[1].jsonPrimitive.double }
            val budget = r.getValue("budget").jsonPrimitive.int
            val draws = ArrayDeque(r.getValue("draws").jsonArray.map { it.jsonPrimitive.double })
            val calls = r.getValue("calls").jsonArray.map { it.jsonObject }
            val dir = Files.createTempDirectory("caracole-ytdlp-runs").toFile()
            val into = File(dir, "into").also { it.mkdir() }
            val cache = File(dir, "cache")
            val gate = HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
            try {
                val opened = gate.start()
                PoliteDb.with { db ->
                    var t = 1000.0
                    val slept = mutableListOf<Double>()
                    val started = Instant.parse("2026-11-26T12:00:00Z")
                    val pacing = Pacing(
                        sleep = { slept += it; t += it },
                        draws = Draws { low, high ->
                            misses.check(low to high == delay) { "runs $name: a draw of ($low, $high), the policy's $delay" }
                            draws.removeFirstOrNull() ?: run { misses.check(false) { "runs $name: a draw Python didn't make" }; low }
                        },
                        wallSeconds = { 1_795_000_000.0 + t }, monotonic = { t }, clock = { started },
                    )
                    val planned = calls.mapNotNull { c ->
                        val ran = c["ran"]?.takeIf { it !is JsonNull }?.jsonObject ?: return@mapNotNull null
                        if (ran["timed_out"]?.jsonPrimitive?.boolean == true) return@mapNotNull FakeYtDlpProcess.Planned(Ran.timedOut())
                        val writes = ran["writes"]?.jsonObject
                        FakeYtDlpProcess.Planned(
                            Ran(ran.getValue("exit").jsonPrimitive.int, text(ran, "stdout")!!.replace(INTO, into.path),
                                text(ran, "stderr")!!),
                            during = { if (writes != null) File(into, text(writes, "name")!!).writeText(text(writes, "data")!!) },
                        )
                    }
                    val fake = FakeYtDlpProcess(planned)
                    val yt = YtDlp(fake, ProviderPolicy(budget.toLong(), delay), cache, QJS, { YtDlpGate.keptOpen(opened) }, YtDlp.Writes.of(db), pacing,
                                   budget = budget, runId = "youtube-replay", timeouts = timeouts)
                    var made = 0
                    for (c in calls) {
                        t += c.getValue("gap").jsonPrimitive.double
                        val call = text(c, "call")!!
                        val arg = text(c, "arg")!!
                        val got: Any? = try {
                            when (call) {
                                "search" -> yt.search(arg).map { it.id }
                                "video" -> yt.video(arg).let { listOf(it.id, it.title, it.channel, it.duration) }
                                else -> yt.download(arg, into).let { d: Download ->
                                    listOf(d.video.id, d.video.title, d.video.channel, d.video.duration) to
                                        d.path.relativeTo(into).invariantSeparatorsPath
                                }
                            }
                        } catch (e: Exception) {
                            (e::class.simpleName ?: "?") to e.message
                        }
                        val outcome = c.getValue("outcome").jsonObject
                        val raised = text(outcome, "raised")
                        val want: Any? = when {
                            raised != null -> (PHONE_CLASS[raised to text(c, "classify")] ?: raised) to text(outcome, "message")
                            call == "search" -> outcome.getValue("videos").jsonArray.map { it.jsonPrimitive.content }
                            else -> outcome.getValue("video").jsonArray.let {
                                listOf(it[0].jsonPrimitive.content, it[1].jsonPrimitive.content, it[2].jsonPrimitive.content,
                                       it[3].jsonPrimitive.doubleOrNull)
                            }.let { v -> if (call == "video") v else v to text(outcome, "file") }
                        }
                        misses.check(got == want) { "runs $name: $call($arg) = $got, Python's $want" }
                        val argv = c["argv"]?.takeIf { it !is JsonNull }?.jsonObject
                        if (argv != null) {
                            val given = fake.argvs.getOrNull(made)
                            made++
                            val folder = text(argv, "into")?.let { into.path }
                            val expected = data.argv(text(argv, "what")!!, text(argv, "target")!!,
                                                     File(cache, data.text("cache_folder", data.runner)).path, QJS,
                                                     opened.proxyArg, folder)
                            misses.check(given == expected && given.count { it == opened.proxyArg } == 1) {
                                "runs $name: $call($arg)'s argv $given, the phone's template ${expected.size} long"
                            }
                        }
                    }
                    misses.check(made == fake.argvs.size && fake.unmade == 0) {
                        "runs $name: ${fake.argvs.size} runs made, $made planned, ${fake.unmade} left"
                    }
                    misses.check(yt.requestsMade == r.getValue("requests_made").jsonPrimitive.int) {
                        "runs $name: ${yt.requestsMade} runs counted, Python's ${r["requests_made"]}"
                    }
                    misses.check(draws.isEmpty()) { "runs $name: Python drew ${draws.size} more" }
                    val wantSlept = r.getValue("slept").jsonArray.map { it.jsonPrimitive.double }
                    misses.check(slept == wantSlept) { "runs $name: slept $slept, Python's $wantSlept" }
                    val events = db.query("SELECT url, status, decision, message FROM events ORDER BY id") { row ->
                        listOf(row.text(0), row.long(1)?.toInt(), row.text(2), row.text(3))
                    }
                    val wantEvents = r.getValue("events").jsonArray.map { e ->
                        val f = e.jsonArray
                        listOf(text0(f[0]), f[1].jsonPrimitive.intOrNull, text0(f[2]), text0(f[3]))
                    }
                    misses.check(events == wantEvents) { "runs $name: events $events, Python's $wantEvents" }
                    val sent = wantEvents.any { it[2] in Pace.SENT }
                    misses.check((db.kvGet(Pace.LAST_SENT + "youtube") != null) == sent) {
                        "runs $name: kv http:last_request:youtube ${db.kvGet(Pace.LAST_SENT + "youtube")}, a run sent: $sent"
                    }
                    val state = Health.state(db, "youtube")
                    val block = r["block"]?.takeIf { it !is JsonNull }?.jsonObject
                    if (block == null) {
                        misses.check(state.cooldownUntil == null) { "runs $name: a cooldown with no block" }
                    } else {
                        val hours = block.getValue("cooldown_hours").jsonPrimitive.double
                        misses.check(state.lastError == text(block, "message") &&
                                     state.cooldownUntil == started.plus(Duration.ofMinutes((hours * 60).toLong()))) {
                            "runs $name: block recorded $state, Python's $block"
                        }
                    }
                }
            } finally {
                gate.close()
                dir.deleteRecursively()
            }
        }
        return n
    }

    private fun text0(e: JsonElement): String? = if (e is JsonNull) null else e.jsonPrimitive.content

    private const val INTO = "<into>"
    private const val QJS = "/data/app/lib/arm64/libqjs.so"

    /** The phone's class for what the computer raised, by classify beside it: the computer's otherwise. */
    private val PHONE_CLASS = mapOf(("ProviderError" to "pass_over") to "PassedOver",
                                    ("ProviderError" to "outdated") to "ExtractorOutdated")

    private fun gate(misses: Misses): Int {
        var n = 0
        for (r in records("gate")) {
            n++
            when (text(r, "fn")) {
                "sheet_on_screen" -> {
                    val got = SearchGate.sheetOnScreen(r.getValue("mine").jsonArray.map {
                        LibraryHit(SONG, it.jsonArray[0].jsonPrimitive.double, it.jsonArray[1].jsonPrimitive.content)
                    }, IndexFound(
                        artists = r.getValue("artists").jsonArray.map {
                            ArtistHit("a", "A", it.jsonArray[0].jsonPrimitive.double, 1, 1, part = it.jsonArray[1].jsonPrimitive.boolean)
                        },
                        songs = r.getValue("songs").jsonArray.map { IndexHit("a", "b", LinkedHashMap(), it.jsonPrimitive.double, "u") },
                    ), r.getValue("lc_artists").jsonArray.map {
                        SiteArtist("lacuerda", "A", "a", "u", it.jsonArray[0].jsonPrimitive.double, part = it.jsonArray[1].jsonPrimitive.boolean)
                    }, r.getValue("lc_songs").jsonArray.map {
                        SiteHit("lacuerda", "T", "u", it.jsonArray[0].jsonPrimitive.double, sheet = text0(it.jsonArray[1]))
                    })
                    val want = r.getValue("on_screen").jsonPrimitive.boolean
                    misses.check(got == want) { "sheet_on_screen($r) = $got, Python's $want" }
                }
                "record_failure" -> PoliteDb.with { db ->
                    for ((k, v) in r.getValue("kv").jsonObject) db.kvSet(k, v.jsonPrimitive.content)
                    val now = Instant.parse(text(r, "now")!!)
                    SearchGate.recordFailure(db, text(r, "key")!!, now, text(r, "error")!!)
                    val failedKey = YouTubeData.read().json.getValue("search").jsonObject.getValue("failed_key").jsonPrimitive.content
                    misses.check(db.kvGet(failedKey) == text(r, "after")) {
                        "record_failure(${text(r, "key")}): ${db.kvGet(failedKey)}, Python's ${text(r, "after")}"
                    }
                }
                else -> PoliteDb.with { db ->
                    val scene = "${text(r, "fn")} ${text(r, "scene")}"
                    db.execute("DELETE FROM events")
                    db.execute("DELETE FROM kv WHERE key LIKE 'provider:%' OR key LIKE 'youtube-search:%'")
                    for ((k, v) in r.getValue("kv").jsonObject) db.kvSet(k, v.jsonPrimitive.content)
                    for (e in r.getValue("events").jsonArray) {
                        val (run, at, provider) = e.jsonArray.map { it.jsonPrimitive.content }
                        db.execute("INSERT INTO events (run, at, provider, url, status, decision, message) " +
                                   "VALUES (?, ?, ?, NULL, NULL, 'ok', NULL)", run, at, provider)
                    }
                    val defaults = PhoneConfig.read(db)
                    val cfg = if (r.getValue("route").jsonPrimitive.boolean) defaults else defaults.copy(
                        providers = defaults.providers + ("youtube" to defaults.provider("youtube").copy(enabled = false)))
                    val now = Instant.parse(text(r, "now")!!)
                    val given = text(r, "given")!!
                    val got = if (text(r, "fn") == "gate") {
                        SearchGate.gate(cfg, db, given, r.getValue("on_screen").jsonPrimitive.boolean, now)
                    } else {
                        SearchGate.videoGate(cfg, db, given, now)
                    }
                    val want = r["gate"]?.takeIf { it !is JsonNull }?.jsonObject
                    val shown = got?.let {
                        JsonObject(mapOf("state" to JsonPrimitive(it.state), "key" to JsonPrimitive(it.key),
                            "asked" to (it.asked ?: JsonNull), "why" to JsonPrimitive(it.why)))
                    }
                    misses.check(shown == want) { "$scene: the gate $shown, Python's $want" }
                    if (text(r, "fn") == "gate") {
                        val said = SearchGate.suggestion(got, given)
                        val wanted = r["youtube"]?.takeIf { it !is JsonNull }
                        misses.check(said == wanted) { "$scene: youtube $said, Python's $wanted" }
                    }
                }
            }
        }
        return n
    }

    private fun record(misses: Misses): Int {
        var n = 0
        PoliteDb.with { db ->
            for (r in records("record")) {
                n++
                val song = r.getValue("song").jsonPrimitive.long
                val stored = text(r, "stored")
                if (stored != null) db.kvSet(Records.key(song), stored)
                Records.save(db, song, Records.load(db, song))
                misses.check(db.kvGet(Records.key(song)) == text(r, "saved")) {
                    "record $song ($stored): saved ${db.kvGet(Records.key(song))}, Python's ${text(r, "saved")}"
                }
            }
        }
        return n
    }

    /** due.jsonl: Due.songs of each scene, unpaired and paired, against Python's ids in order. */
    private fun due(misses: Misses): Int {
        var n = 0
        for (r in records("due")) {
            n++
            val case = text(r, "case")!!
            val o = r.getValue("overrides").jsonObject
            val overrides = Overrides(
                ignore = o.getValue("ignore").jsonArray.map { it.jsonPrimitive.content }.toSet(),
                youtube = o.getValue("youtube").jsonObject.mapValues { (_, v) -> v.jsonPrimitive.contentOrNull },
                lacuerda = o.getValue("lacuerda").jsonObject.mapValues { (_, v) ->
                    val p = v.jsonObject
                    LaCuerdaPick(text(p, "artist")!!, text(p, "song")!!, p["version"]?.jsonPrimitive?.intOrNull)
                },
            )
            val now = Instant.parse(text(r, "now")!!)
            PoliteDb.with { db ->
                Fixtures.loadRecords(db, r.getValue("fixture").jsonArray.map { it.jsonObject }, name = case)
                for ((key, paired) in listOf("due" to false, "paired" to true)) {
                    val want = r.getValue(key).jsonArray.map { it.jsonPrimitive.long }
                    val got = Due.songs(db, overrides, now, paired).map { it.id }
                    misses.check(got == want) { "due $case, paired $paired: $got, Python's $want" }
                }
            }
        }
        return n
    }

    /** video_cmd.jsonl's `checked_jpeg` records (its command's records are :server's, YouTubeVideoReplay): Thumbs'
     * reading of each head with its trailing zeros, kept or not as Python's. */
    private fun jpegs(misses: Misses): Int {
        var n = 0
        for (r in records("video_cmd").filter { it["fn"]?.jsonPrimitive?.content == "checked_jpeg" }) {
            n++
            val data = java.util.Base64.getDecoder().decode(r.getValue("base64").jsonPrimitive.content) +
                ByteArray(r.getValue("zeros").jsonPrimitive.int)
            val kept = Thumbs.checkedJpeg(data) != null
            misses.check(kept == r.getValue("kept").jsonPrimitive.boolean) {
                "checked_jpeg of ${r["base64"]} and ${r["zeros"]} zeros: kept $kept, Python's ${r["kept"]}"
            }
        }
        return n
    }

    /** A song of no consequence: sheet_on_screen reads a library hit's score and reading alone. */
    private val SONG = SongRow(0, "", "", "", emptyList(), null, null, null, "{}", "", null, "wanted", false, null, null,
        null, null, null, "[]", null, false, null, "pending", null, null, null, "")
}
