package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.youtube.DayBudget
import io.github.danielhp95.caracole.core.youtube.Due
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import java.time.Duration
import java.time.Instant

/**
 * The phone's automatic YouTube pass (the phone-youtube design's §5.3; the owner, 2026-11-26: "automatic is okay",
 * "1. yes and allow that setting"): the app's YouTubeWorker calls [pass], after a lookup that left its song "Not on
 * the sites" (`youtube-soon`) and daily on a phone that hasn't synced with a computer in [PAIRED_DAYS] days
 * (`youtube-daily`). It is no job itself: it queues the computer's job for one due song at a time, with no video given
 * (`youtube --sheet --progress --song=…`, YouTubeSheetRunner), [automatic][io.github.danielhp95.caracole.server.jobs
 * .JobSpec.automatic] (the day's runs left its budget, no run on a metered network, its lyrics at the bulk pace, no
 * failed alert), and awaits it before the next.
 *
 * The songs are [Due.songs]' (on a [paired] phone the noted ones alone, kv `youtube-wanted:<id>`), each tried once a
 * pass. Before each, [stop] says whether the pass goes on: the switch "Find audio on YouTube by itself" off (kv
 * [SWITCH]), the route not offered ([problem]: YouTube off, no chord models, no yt-dlp), YouTube cooling down after a
 * block, yt-dlp out of date ([outdated]), a metered network, fewer than [LEAST_RUNS] runs left of the day
 * (DayBudget.left: a song costs two), or [MOST_S] seconds since the pass began. A pass that stops with songs it hadn't
 * tried, for a reason that passes by itself, says when another should go ([again]), which the worker enqueues. A pass
 * with nothing due queues nothing and writes nothing.
 */
class YouTubeAuto(
    private val parts: PhoneParts,
    private val problem: () -> String?,
    private val metered: () -> Boolean,
    private val outdated: (Db, Instant) -> String? = { _, _ -> null },
    private val clock: () -> Instant = { Instant.now() },
    private val monotonic: () -> Double = { System.nanoTime() / 1e9 },
) {
    /** What a pass did: the jobs it queued (their ids), why it stopped (one of the [Stop]s), and the songs it [left]:
     * those due as it stopped that it hadn't tried (a song noted while its last job ran among them), which [again]
     * reads. */
    data class Ended(val jobs: List<Int>, val stopped: Stop, val left: Int = 0)

    enum class Stop { NOTHING_DUE, SWITCHED_OFF, NOT_OFFERED, COOLING, OUTDATED, METERED, FEW_RUNS, TIME, QUEUE_FULL,
                      OVERRIDES }

    /** One pass, a song at a time; returns once it stops. */
    suspend fun pass(): Ended {
        val started = monotonic()
        val tried = HashSet<Long>()
        val jobs = ArrayList<Int>()
        while (true) {
            val timeUp = monotonic() - started >= MOST_S
            val now = clock()
            val next = parts.database.read { db -> next(db, now, timeUp, tried) }
            next.stopped?.let { return Ended(jobs, it, next.left) }
            val song = next.song ?: return Ended(jobs, Stop.NOTHING_DUE)
            tried += song.id
            val job = try {
                parts.queue.submit(spec(song.display, song.key)).first
            } catch (_: QueueFull) {
                return Ended(jobs, Stop.QUEUE_FULL, next.left + 1)
            }
            jobs += job.id
            parts.queue.await(job.id)
        }
    }

    /** A pass's next step: why it stops, with the due songs it hasn't tried ([Step.left]); else its next song. */
    private class Step(val stopped: Stop?, val song: SongRow?, val left: Int)

    private fun next(db: Db, now: Instant, timeUp: Boolean, tried: Set<Long>): Step {
        val stop = if (timeUp) Stop.TIME else stop(db, now)
        val overrides = try {
            Overrides.read(db)
        } catch (_: OverridesError) {
            return Step(stop ?: Stop.OVERRIDES, null, 0)
        }
        val due = Due.songs(db, overrides, now, paired(db, now)).filter { it.id !in tried }
        return when {
            stop != null -> Step(stop, null, due.size)
            due.isEmpty() -> Step(Stop.NOTHING_DUE, null, 0)
            else -> Step(null, due.first(), due.size - 1)
        }
    }

    /** How long before another pass after [ended], or null for none: only for a pass that left songs it hadn't tried
     * ([Ended.left]), stopped for a reason that passes by itself: [MOST_S] or a metered network [AGAIN_SOON] on
     * (the work's own constraint waits for Wi-Fi), a full queue [AGAIN_QUEUE_FULL], a cooldown its end and fewer than
     * [LEAST_RUNS] runs the moment two are free again (DayBudget.freesAt), each [AGAIN_SOON] after. Never for a song
     * this pass tried (its job's failure waits for the next lookup that notes it, or the daily pass; a later pass may
     * try a failed song again, bounded by `give_up_after` and the day's budget), nor for the
     * switch off, the route not offered, out of date or overrides.toml unreadable. On a paired phone there is no
     * daily pass, so without this the songs left would wait for the next lookup that finds no sheet. */
    fun again(ended: Ended): Duration? {
        if (ended.left == 0) return null
        val now = clock()
        return when (ended.stopped) {
            Stop.TIME, Stop.METERED -> AGAIN_SOON
            Stop.QUEUE_FULL -> AGAIN_QUEUE_FULL
            Stop.COOLING -> parts.database.read { db -> Health.state(db, PROVIDER).cooldownUntil }
                ?.let { after(now, it) } ?: AGAIN_SOON
            Stop.FEW_RUNS -> parts.database.read { db -> DayBudget.freesAt(db, parts.config(), now, LEAST_RUNS) }
                ?.let { after(now, it) }
            else -> null
        }
    }

    private fun after(now: Instant, at: Instant): Duration = maxOf(Duration.between(now, at), Duration.ZERO) + AGAIN_SOON

    /** Whether a song a lookup noted (kv `youtube-wanted:<id>`) is due now: Settings' switch turned back on asks for a
     * pass then (YouTubeWorker.switchedOn), as no daily pass takes it on a paired phone. */
    fun notedDue(): Boolean {
        val now = clock()
        return parts.database.read { db ->
            val overrides = try {
                Overrides.read(db)
            } catch (_: OverridesError) {
                return@read false
            }
            Due.songs(db, overrides, now, paired = true).isNotEmpty()
        }
    }

    /** Why no automatic job goes now, or null. */
    fun stop(db: Db, now: Instant): Stop? = when {
        !on(db) -> Stop.SWITCHED_OFF
        problem() != null -> Stop.NOT_OFFERED
        Health.isCooling(db, PROVIDER, now) -> Stop.COOLING
        outdated(db, now) != null -> Stop.OUTDATED
        metered() -> Stop.METERED
        DayBudget.left(db, parts.config(), now) < LEAST_RUNS -> Stop.FEW_RUNS
        else -> null
    }

    companion object {
        private const val PROVIDER = "youtube"

        /** Settings' "Find audio on YouTube by itself": kv `phone:youtube-auto`, "false" for off, on otherwise (and by
         * default); the phone's own, kept by a restore (OwnRecords). */
        const val SWITCH = "phone:youtube-auto"

        /** A pass queues no job after 8 minutes (the design's §5.3). The job it awaits may run longer (a song's hearing
         * takes minutes): the worker is long-running (the app's YouTubeWorker in the foreground through WorkManager's
         * setForeground, which lifts WorkManager's 10 minutes), so it awaits the job to its end, the process in the
         * foreground meanwhile. */
        const val MOST_S = 8 * 60.0

        /** A song costs two runs (a search and a download): a pass stops with fewer left. */
        const val LEAST_RUNS = 2

        /** Another pass after one that stopped at [MOST_S] or on a metered network, with songs left (again). */
        val AGAIN_SOON: Duration = Duration.ofMinutes(2)

        /** Another pass after one that found the queue full, with songs left. */
        val AGAIN_QUEUE_FULL: Duration = Duration.ofMinutes(10)

        /** A phone that synced with a computer within these days is paired: no daily pass, its noted songs alone. */
        const val PAIRED_DAYS = 14L

        fun on(db: Db): Boolean = db.kvGet(SWITCH) != "false"

        fun set(db: Db, on: Boolean) = db.kvSet(SWITCH, if (on) "true" else "false")

        /** Whether the phone synced with a computer (or imported its file) within [PAIRED_DAYS] days of [now]: the
         * latest agreement its bases keep (kv `sync:base:<peer>`, every unit agreed stamped with the sync's time). */
        fun paired(db: Db, now: Instant): Boolean {
            val last = lastSync(db) ?: return false
            return last.isAfter(now.minus(Duration.ofDays(PAIRED_DAYS)))
        }

        /** The time of the phone's last sync, or null for none. */
        fun lastSync(db: Db): Instant? {
            val peers = db.query("SELECT key FROM kv WHERE key LIKE 'sync:base:%'") {
                it.text(0)!!.removePrefix("sync:base:")
            }
            return peers.mapNotNull { peer ->
                Compare.baseOf(db, peer)?.values
                    ?.mapNotNull { (_, at) -> runCatching { Stamps.parse(at) }.getOrNull() }?.maxOrNull()
            }.maxOrNull()?.let(Stamps::instant)
        }

        /** The automatic job of the song [display] ([key], its identity key): the computer's, with no video given. */
        fun spec(display: String, key: String) =
            LookupForms.spec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + key,
                             listOf(Command("Making the sheet",
                                            listOf("youtube", "--sheet", "--progress", "--song=$display"))),
                             display = display).copy(automatic = true)
    }
}
