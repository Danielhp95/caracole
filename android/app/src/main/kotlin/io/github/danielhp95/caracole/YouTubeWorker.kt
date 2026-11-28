package io.github.danielhp95.caracole

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.lookups.YouTubeAuto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * The automatic YouTube pass's WorkManager work (the phone-youtube design's §5.3): it is no job itself, it runs the
 * phone's [YouTubeAuto.pass], which queues one automatic job at a time and awaits it, and stops at 8 minutes, at fewer
 * than 2 runs left, at a block or at out of date.
 *
 * - [SOON], after a lookup that left its song "Not on the sites" (Phone.onNoSheet): unique one-time work, KEEP, two
 *   minutes on, on an unmetered network with the battery not low;
 * - [DAILY], every 24 hours (6 of flex), also charging, scheduled only on a phone that hasn't synced with a computer in
 *   14 days ([schedule]), and letting itself go when it finds the phone synced since.
 *
 * The switch "Find audio on YouTube by itself" off (kv `phone:youtube-auto`) schedules nothing and cancels both; a
 * build with no yt-dlp schedules nothing. The network is checked again before each run by the job itself.
 */
class YouTubeWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val phone = withContext(Dispatchers.IO) { Caracole.phone(applicationContext) }
        if (phone.youtube == null) return Result.success()
        if (DAILY in tags && withContext(Dispatchers.IO) { phone.parts.database.read { db -> !daily(db) } }) {
            WorkManager.getInstance(applicationContext).cancelUniqueWork(DAILY)
            return Result.success()
        }
        val ended = phone.youtubeAuto.pass()
        Log.i("caracole", "the automatic YouTube pass queued ${ended.jobs.size} job(s), stopped: ${ended.stopped}")
        return Result.success()
    }

    companion object {
        const val SOON = "youtube-soon"
        const val DAILY = "youtube-daily"
        private const val SOON_DELAY_MIN = 2L

        private fun on(phone: Phone): Boolean = phone.youtube != null && phone.parts.database.read { YouTubeAuto.on(it) }

        /** Whether the daily work belongs on this phone now: the switch on and no sync in 14 days. */
        private fun daily(db: io.github.danielhp95.caracole.core.db.Db): Boolean =
            YouTubeAuto.on(db) && !YouTubeAuto.paired(db, Instant.now())

        /** The after-a-lookup work enqueued (KEEP: one waiting is the answer), unless the switch is off. */
        fun soon(context: Context, phone: Phone = Caracole.phone(context)) {
            if (!on(phone)) return
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.UNMETERED)
                .setRequiresBatteryNotLow(true)
                .build()
            val request = OneTimeWorkRequestBuilder<YouTubeWorker>().setConstraints(constraints)
                .setInitialDelay(SOON_DELAY_MIN, TimeUnit.MINUTES).addTag(SOON).build()
            try {
                WorkManager.getInstance(context).enqueueUniqueWork(SOON, ExistingWorkPolicy.KEEP, request)
            } catch (_: IllegalStateException) {
                // WorkManager isn't there (a test's context): nothing is enqueued.
            }
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
