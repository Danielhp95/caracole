package io.github.danielhp95.caracole

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context

/**
 * The app's notification channels but the alerts' (AndroidAlerts'): [JOBS], for the work the phone's caracole does in
 * the foreground (its job queue's: SyncService).
 */
object Notifications {
    const val JOBS = "jobs"

    /** The [JOBS] channel, made once. */
    fun channel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(JOBS) != null) return
        manager.createNotificationChannel(
            NotificationChannel(JOBS, context.getString(R.string.jobs_channel), NotificationManager.IMPORTANCE_LOW))
    }
}
