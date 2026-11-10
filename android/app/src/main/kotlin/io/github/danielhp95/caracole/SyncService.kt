package io.github.danielhp95.caracole

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

/**
 * The foreground service (a data sync) that keeps the phone's caracole alive while its job queue works: a sync from
 * the Sync tab, an add, a removal, a lookup on the sites (Get it, Fetch now, an artist's Songs, LaCuerda's own search,
 * Fetch them) ([Working]). Its notification, on the `jobs` channel, names the job that runs ("Sharing logs with Daniel's
 * library…", "Estopa - Tu calorro · Looking up the lyrics…"); a tap on it opens the library. Started as the queue gets
 * such a job, it stops itself once none waits or runs. An index import has none: its worker is in the foreground with
 * its own notification.
 *
 * Android may refuse to start it while the app is in the background (from Android 12); the job then goes on as long
 * as the process lives, as it did before. Jobs are asked for from the app's own screen, where the start is allowed.
 */
class SyncService : Service() {
    private val scope = MainScope()
    private var watching: Job? = null
    private var foreground = false
    private var lastStart = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStart = startId
        val line = Caracole.working()?.line ?: MutableStateFlow(null)
        // In the foreground at once, as startForegroundService asks of every start, then the line followed: once it
        // is gone the service stops (stopSelf of the last start alone: a start asked since keeps it).
        show(line.value ?: getString(R.string.working))
        if (watching == null) {
            watching = scope.launch {
                line.collect { said -> if (said == null) stop() else show(said) }
            }
        }
        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        // Android 15's limit on a data sync's time in the foreground: given up as it asks, the job going on.
        stop()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun show(text: String) {
        val notification = notification(text)
        if (foreground) {
            getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION, notification)
            return
        }
        val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, NOTIFICATION, notification, type)
        foreground = true
    }

    private fun stop() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        foreground = false
        stopSelf(lastStart)
    }

    private fun notification(text: String): Notification {
        Notifications.channel(this)
        val library = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, Notifications.JOBS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setContentIntent(library)
            .setProgress(0, 0, true)
            .build()
    }

    companion object {
        private const val TAG = "CaracoleSync"
        private const val NOTIFICATION = 3

        /** Started for the queue's work ([Working]'s start); refused in the background, which is said in the log. */
        fun start(context: Context) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, SyncService::class.java))
            } catch (e: IllegalStateException) {
                // ForegroundServiceStartNotAllowedException (Android 12 and later) among them.
                Log.w(TAG, "the foreground service for the phone's work wasn't started: $e")
            }
        }
    }
}
