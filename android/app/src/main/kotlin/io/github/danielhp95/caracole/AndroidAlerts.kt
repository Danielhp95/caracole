package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.health.Alerts
import java.time.Instant

/**
 * The phone's alerts as Android notifications on their own channel, [CHANNEL] (lane alerts-backups): a block a lookup
 * met, once a cooldown, and a job that failed while the app was in the background. Caracole gives it to the phone.
 *
 * Until its lane lands it tells no one, as Alerts.NONE.
 */
class AndroidAlerts(private val context: Context) : Alerts {
    override fun blocked(provider: String, until: Instant?, message: String) {}

    override fun failed(title: String, line: String) {}

    companion object {
        /** The alerts' notification channel (its name: R.string.alerts_channel). */
        const val CHANNEL = "alerts"
    }
}
