package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
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
 * (DayBudget.left: a song costs two), or [MOST_S] seconds since the pass began. A pass with nothing due queues nothing
 * and writes nothing.
 */
class YouTubeAuto(
    private val parts: PhoneParts,
    private val problem: () -> String?,
    private val metered: () -> Boolean,
    private val outdated: (Db, Instant) -> String? = { _, _ -> null },
    private val clock: () -> Instant = { Instant.now() },
    private val monotonic: () -> Double = { System.nanoTime() / 1e9 },
) {
    /** What a pass did: the jobs it queued (their ids), and why it stopped (one of the [Stop]s). */
    data class Ended(val jobs: List<Int>, val stopped: Stop)

    enum class Stop { NOTHING_DUE, SWITCHED_OFF, NOT_OFFERED, COOLING, OUTDATED, METERED, FEW_RUNS, TIME, QUEUE_FULL,
                      OVERRIDES }

    /** One pass, a song at a time; returns once it stops. */
    suspend fun pass(): Ended {
        val started = monotonic()
        val tried = HashSet<Long>()
        val jobs = ArrayList<Int>()
        while (true) {
            if (monotonic() - started >= MOST_S) return Ended(jobs, Stop.TIME)
            val now = clock()
            val next = parts.database.read { db ->
                stop(db, now)?.let { return@read it to null }
                val overrides = try {
                    Overrides.read(db)
                } catch (_: OverridesError) {
                    return@read Stop.OVERRIDES to null
                }
                null to Due.songs(db, overrides, now, paired(db, now)).firstOrNull { it.id !in tried }
            }
            next.first?.let { return Ended(jobs, it) }
            val song = next.second ?: return Ended(jobs, Stop.NOTHING_DUE)
            tried += song.id
            val job = try {
                parts.queue.submit(spec(song.display, song.key)).first
            } catch (_: QueueFull) {
                return Ended(jobs, Stop.QUEUE_FULL)
            }
            jobs += job.id
            parts.queue.await(job.id)
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

        /** A pass stops at 8 minutes into its worker (WorkManager's 10 minutes, less the job it awaits). */
        const val MOST_S = 8 * 60.0

        /** A song costs two runs (a search and a download): a pass stops with fewer left. */
        const val LEAST_RUNS = 2

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
            val peers = db.query("SELECT key FROM kv WHERE key LIKE 'sync:base:%'") { it.text(0)!!.removePrefix("sync:base:") }
            return peers.mapNotNull { peer ->
                Compare.baseOf(db, peer)?.values?.mapNotNull { (_, at) -> runCatching { Stamps.parse(at) }.getOrNull() }?.maxOrNull()
            }.maxOrNull()?.let(Stamps::instant)
        }

        /** The automatic job of the song [display] ([key], its identity key): the computer's, with no video given. */
        fun spec(display: String, key: String) =
            LookupForms.spec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + key,
                             listOf(Command("Making the sheet", listOf("youtube", "--sheet", "--progress", "--song=$display"))),
                             display = display).copy(automatic = true)
    }
}
