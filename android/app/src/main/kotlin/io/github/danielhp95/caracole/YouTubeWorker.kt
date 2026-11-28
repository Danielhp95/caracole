package io.github.danielhp95.caracole

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.lookups.YouTubeAuto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * The automatic YouTube pass's WorkManager work (the phone-youtube design's §5.3): it is no job itself, it runs the
 * phone's [YouTubeAuto.pass], which queues one automatic job at a time and awaits it, and stops at 8 minutes, at fewer
 * than 2 runs left, at a block or at out of date.
 *
 * - [SOON], after a lookup that left its song "Not on the sites" (Phone.onNoSheet): unique one-time work, KEEP, two
 *   minutes on, on an unmetered network with the battery not low;
 * - a pass that stops with songs it hadn't tried, for a reason that passes by itself (8 minutes, a metered network,
 *   the queue full, a cooldown, the day's runs), asks for another (YouTubeAuto.again, [soonAgain]: appended to [SOON]);
 *   the switch turned back on asks for one where a noted song is due ([switchedOn]);
 * - [DAILY], every 24 hours (6 of flex), also charging, scheduled only on a phone that hasn't synced with a computer in
 *   14 days ([schedule]), and letting itself go when it finds the phone synced since.
 *
 * The switch "Find audio on YouTube by itself" off (kv `phone:youtube-auto`) schedules nothing and cancels both; a
 * build with no yt-dlp schedules nothing. The network is checked again before each run by the job itself.
 *
 * It runs long ([foreground]: WorkManager's `setForeground`, a quiet notification on the jobs' channel, the route a
 * job may take into the foreground from the background, where SyncService's own start isn't allowed), so the job it
 * awaits keeps a foreground component for as long as the worker lives.
 */
class YouTubeWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result =
        work(applicationContext, withContext(Dispatchers.IO) { Caracole.phone(applicationContext) }, DAILY in tags) {
            foreground()
        }

    /** Into the foreground, as a long-running worker: a refusal (none allowed now) logged, the pass going on. */
    private suspend fun foreground() {
        try {
            setForeground(foregroundInfo(applicationContext))
            foregroundForTests = true
        } catch (e: IllegalStateException) {
            Log.w("caracole", "the automatic YouTube pass couldn't go into the foreground", e)
        }
    }

    companion object {
        /** What a run of the work does, [daily] the daily one's: nothing in a build with no yt-dlp; the daily one on a
         * phone it no longer belongs on (the switch off, or a sync within 14 days) lets itself go; else the pass. */
        internal suspend fun work(context: Context, phone: Phone, daily: Boolean,
                                  foreground: suspend () -> Unit = {}): Result {
            if (phone.youtube == null) return Result.success()
            if (daily && withContext(Dispatchers.IO) { phone.parts.database.read { db -> !daily(db) } }) {
                WorkManager.getInstance(context).cancelUniqueWork(DAILY)
                return Result.success()
            }
            foreground()
            val ended = phone.youtubeAuto.pass()
            lastForTests = ended
            val again = withContext(Dispatchers.IO) { phone.youtubeAuto.again(ended) }
            Log.i("caracole", "the automatic YouTube pass queued ${ended.jobs.size} job(s), " +
                "stopped: ${ended.stopped}, ${ended.left} song(s) left" +
                (again?.let { ", another pass in ${it.toMinutes()} min" } ?: ""))
            if (again != null) soonAgain(context, again)
            return Result.success()
        }

        /** The worker's notification while it runs long: the jobs' channel, quiet. */
        private const val NOTIFICATION = 5

        private fun foregroundInfo(context: Context): ForegroundInfo {
            Notifications.channel(context)
            val notification = NotificationCompat.Builder(context, Notifications.JOBS)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(context.getString(R.string.youtube_auto_working))
                .setOngoing(true)
                .setSilent(true)
                .build()
            return if (Build.VERSION.SDK_INT >= 29) {
                ForegroundInfo(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else ForegroundInfo(NOTIFICATION, notification)
        }

        /** Whether a worker of this process went into the foreground, for a device test. */
        @Volatile var foregroundForTests = false

        /** What the last pass of this process came to, for a device test. */
        @Volatile var lastForTests: YouTubeAuto.Ended? = null

        const val SOON = "youtube-soon"
        const val DAILY = "youtube-daily"
        private const val SOON_DELAY_MIN = 2L

        private fun on(phone: Phone): Boolean =
            phone.youtube != null && phone.parts.database.read { YouTubeAuto.on(it) }

        /** Whether the daily work belongs on this phone now: the switch on and no sync in 14 days. */
        private fun daily(db: io.github.danielhp95.caracole.core.db.Db): Boolean =
            YouTubeAuto.on(db) && !YouTubeAuto.paired(db, Instant.now())

        /** soon's constraints: an unmetered network, the battery not low. */
        private fun soonConstraints(): Constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.UNMETERED)
            .setRequiresBatteryNotLow(true)
            .build()

        /** The after-a-lookup work enqueued (KEEP: one waiting is the answer), unless the switch is off. */
        fun soon(context: Context, phone: Phone = Caracole.phone(context)) {
            if (!on(phone)) return
            val request = OneTimeWorkRequestBuilder<YouTubeWorker>().setConstraints(soonConstraints())
                .setInitialDelay(SOON_DELAY_MIN, TimeUnit.MINUTES).addTag(SOON).build()
            try {
                WorkManager.getInstance(context).enqueueUniqueWork(SOON, ExistingWorkPolicy.KEEP, request)
            } catch (_: IllegalStateException) {
                // WorkManager isn't there (a test's context): nothing is enqueued.
            }
        }

        /** Another pass [delay] on, after one that stopped with songs left (YouTubeAuto.again): appended to soon's work
         * (APPEND_OR_REPLACE), so that it is enqueued while this pass's own work still runs, where soon's KEEP would
         * keep the running one and enqueue nothing; soon's constraints. */
        internal fun soonAgain(context: Context, delay: Duration) {
            val request = OneTimeWorkRequestBuilder<YouTubeWorker>().setConstraints(soonConstraints())
                .setInitialDelay(delay.toMillis().coerceAtLeast(0L), TimeUnit.MILLISECONDS).addTag(SOON).build()
            try {
                WorkManager.getInstance(context).enqueueUniqueWork(SOON, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
            } catch (_: IllegalStateException) {
                // WorkManager isn't there (a test's context): nothing is enqueued.
            }
        }

        /** Settings' switch turned back on: a pass soon where a song a lookup noted is due (no daily pass takes it on a
         * paired phone). */
        fun switchedOn(context: Context, phone: Phone = Caracole.phone(context)) {
            if (phone.youtube != null && phone.youtubeAuto.notedDue()) soon(context, phone)
        }

        /** The daily work scheduled (KEEP) on a phone it belongs on, else cancelled; the switch off cancels both. */
        fun schedule(context: Context, phone: Phone = Caracole.phone(context)) {
            val manager = try {
                WorkManager.getInstance(context)
            } catch (_: IllegalStateException) {
                return
            }
            if (!on(phone)) manager.cancelUniqueWork(SOON)
            if (phone.youtube == null || !phone.parts.database.read(::daily)) {
                manager.cancelUniqueWork(DAILY)
                return
            }
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.UNMETERED)
                .setRequiresBatteryNotLow(true)
                .setRequiresCharging(true)
                .build()
            val request = PeriodicWorkRequestBuilder<YouTubeWorker>(24, TimeUnit.HOURS, 6, TimeUnit.HOURS)
                .setConstraints(constraints).addTag(DAILY).build()
            manager.enqueueUniquePeriodicWork(DAILY, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
