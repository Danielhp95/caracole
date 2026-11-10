package io.github.danielhp95.caracole

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * The app's notification channels but the alerts' (AndroidAlerts'): [JOBS], for the work the phone's caracole does in
 * the foreground (its job queue's: SyncService), and [SYNCS], the unattended sync's word of the conflicts it left
 * ([conflictsLeft]).
 */
object Notifications {
    const val JOBS = "jobs"
    const val SYNCS = "syncs"

    /** The conflicts' notification: one, replaced by the next sync's. */
    private const val CONFLICTS = 4

    /** The [JOBS] channel, made once. */
    fun channel(context: Context) = made(context, JOBS, R.string.jobs_channel, NotificationManager.IMPORTANCE_LOW)

    /**
     * Sync on Wi-Fi's [count] conflicts left (each a unit changed on both sides, left as it is on both), on [SYNCS]:
     * "2 songs changed on both sides: tap to choose" ([songs]: every one a song's; else "2 changes on both sides…"). Its
     * tap opens the library page's sync sheet (MainActivity's [MainActivity.SHEET], "sync"), where the cards ask.
     * Nothing when the owner took the right to notify back.
     */
    fun conflictsLeft(context: Context, count: Int, songs: Boolean) {
        made(context, SYNCS, R.string.syncs_channel, NotificationManager.IMPORTANCE_DEFAULT)
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) return
        val text = context.resources.getQuantityString(
            if (songs) R.plurals.conflicts_left else R.plurals.conflicts_left_changes, count, count)
        val sheet = PendingIntent.getActivity(context, CONFLICTS,
            Intent(context, MainActivity::class.java).putExtra(MainActivity.SHEET, MainActivity.SYNC)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(context, SYNCS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(context.getString(R.string.app_name))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(sheet)
            .setAutoCancel(true)
            .build()
        try {
            manager.notify(CONFLICTS, notification)
        } catch (_: SecurityException) {
            // The right to notify taken back meanwhile: nothing is said.
        }
    }

    private fun made(context: Context, id: String, name: Int, importance: Int) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(id) != null) return
        manager.createNotificationChannel(NotificationChannel(id, context.getString(name), importance))
    }
}
