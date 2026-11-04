package io.github.danielhp95.caracole.core.health

import java.time.Instant

/**
 * What the phone tells its owner, as Android notifications (lane alerts-backups): a block a lookup met, once a
 * cooldown, and a job that failed while the app was in the background (the app decides whether it was). The
 * computer's ntfy is its own; on the phone a lookup alerts, since it has no nightly run to tell.
 */
interface Alerts {
    fun blocked(provider: String, until: Instant?, message: String)
    fun failed(title: String, line: String)

    companion object {
        /** Tells no one. */
        val NONE: Alerts = object : Alerts {
            override fun blocked(provider: String, until: Instant?, message: String) {}
            override fun failed(title: String, line: String) {}
        }
    }
}
