package io.github.danielhp95.caracole

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * The daily backup: once a day, while the phone is idle and its battery isn't low, the phone's job queue is given a
 * backup labelled `daily` (BackupRunner's job, never run beside a lookup's write), and this waits for it to end, so the
 * process lives while it runs. A backup that fails says why on the Requests tab (and, the app in the background, as
 * an alert); WorkManager tries again the next day.
 */
class BackupWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = daily(withContext(Dispatchers.IO) { Caracole.phone(applicationContext) })

    companion object {
        /** The daily backup queued on [phone] and awaited: success once it is over, done or failed (a failure says
         * why on the Requests tab), or with the queue full (tomorrow's); retry for one cancelled or interrupted. */
        suspend fun daily(phone: Phone): Result {
            val job = BackupRunner(phone.parts).backup(Backups.DAILY)
            val queued = try {
                phone.queue.submit(job).first
            } catch (_: QueueFull) {
                return Result.success()
            }
            val over = phone.queue.await(queued.id)
            return if (over.state == Job.DONE || over.state == Job.FAILED) Result.success() else Result.retry()
        }

        /** The unique periodic work's name. */
        const val WORK = "daily-backup"

        /** The daily backup scheduled, once (a schedule already there is kept). */
        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiresDeviceIdle(true)
                .setRequiresBatteryNotLow(true)
                .build()
            val request = PeriodicWorkRequestBuilder<BackupWorker>(1, TimeUnit.DAYS).setConstraints(constraints).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
