package io.github.danielhp95.caracole

import android.app.Activity
import android.app.ActivityManager
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.lookup.LookupWords
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Collections
import java.util.Locale
import java.util.WeakHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * The phone's alerts as Android notifications on their own channel, [CHANNEL] (Caracole gives it to the phone, made
 * once a process at its start):
 *
 * - [blocked]: a block a lookup met, titled as the computer's ntfy alert is ("caracole: Ultimate Guitar blocked"),
 *   saying when its cooldown ends: once a cooldown, so a second block within it (the same cooldown's end) posts none,
 *   even after the app starts again (the cooldown posted is kept in [PREFS]);
 * - [failed]: a job that failed while the app was in the background, by its line, as the Requests tab says it. In the
 *   background means no screen of the app's is started, by the activities' lifecycle; a screen that started before
 *   this was made (the phone is made on another thread as the library screen opens) is counted by the process being
 *   in the foreground then, until a screen stops.
 *
 * Nothing is posted while the owner hasn't let the app notify. Each notification opens the library screen. Being
 * made at the phone's start, it also keeps the daily backup scheduled ([BackupWorker.schedule]).
 */
class AndroidAlerts(context: Context) : Alerts {
    private val context: Context = context.applicationContext
    private val prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val started: MutableSet<Activity> = Collections.newSetFromMap(WeakHashMap())
    @Volatile private var seenInForeground = false
    private val failures = AtomicInteger()

    init {
        channel(this.context)
        val info = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(info)
        seenInForeground = info.importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND
        (this.context as? Application)?.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: Activity) {
                synchronized(started) { started.add(activity) }
            }

            override fun onActivityStopped(activity: Activity) {
                synchronized(started) { started.remove(activity) }
                seenInForeground = false
            }

            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) {}
            override fun onActivityResumed(activity: Activity) {}
            override fun onActivityPaused(activity: Activity) {}
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) {}
            override fun onActivityDestroyed(activity: Activity) {}
        })
        try {
            BackupWorker.schedule(this.context)
        } catch (_: IllegalStateException) {
            // WorkManager isn't there (a test's context): no daily backup is scheduled from here.
        }
    }

    /** Whether the owner is in the app: one of its screens started (or, before any stopped, its process in the
     * foreground as this was made). */
    fun inForeground(): Boolean = seenInForeground || synchronized(started) { started.isNotEmpty() }

    override fun blocked(provider: String, until: Instant?, message: String) {
        val mark = until?.toString() ?: "-"
        val key = BLOCKED + provider
        synchronized(this) {
            if (prefs.getString(key, null) == mark) return
            prefs.edit().putString(key, mark).apply()
        }
        val name = LookupWords.NAMES[provider] ?: provider
        val title = context.getString(R.string.alert_blocked, name)
        val end = until?.let { context.getString(R.string.alert_cooling, SHOWN.format(it.atZone(ZoneId.systemDefault()))) }
        val text = listOfNotNull(end, message.trim().takeIf { it.isNotEmpty() }).joinToString("\n")
        post(BLOCKED_ID + (provider.hashCode() and 0x3ff), title, text)
    }

    override fun failed(title: String, line: String) {
        if (inForeground()) return
        post(FAILED_ID + (failures.getAndIncrement() and 0x3ff), title, line)
    }

    private fun post(id: Int, title: String, text: String) {
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) return
        val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(text.lineSequence().firstOrNull().orEmpty())
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            manager.notify(id, notification)
        } catch (_: SecurityException) {
            // The owner took the right to notify back meanwhile: nothing is said.
        }
    }

    companion object {
        /** The alerts' notification channel (its name: R.string.alerts_channel). */
        const val CHANNEL = "alerts"

        /** Where the cooldown each provider's last block alert was for is kept. */
        const val PREFS = "alerts"
        private const val BLOCKED = "blocked:"

        private const val BLOCKED_ID = 1000
        private const val FAILED_ID = 2000

        private val SHOWN = DateTimeFormatter.ofPattern("d MMM, HH:mm", Locale.ROOT)

        /** The alerts' channel, made once. */
        fun channel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL) != null) return
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, context.getString(R.string.alerts_channel), NotificationManager.IMPORTANCE_DEFAULT))
        }
    }
}
