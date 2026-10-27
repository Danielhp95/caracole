package io.github.danielhp95.caracole

import android.content.Context
import androidx.core.content.edit

/** The settings and the last sync's outcome, in the app's own preferences. */
class Settings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("caracole", Context.MODE_PRIVATE)

    /** caracole serve's address, as typed. */
    var server: String
        get() = prefs.getString(SERVER, "") ?: ""
        set(value) = prefs.edit { putString(SERVER, value) }

    /** Whether the app syncs on Wi-Fi by itself. */
    var syncOnWifi: Boolean
        get() = prefs.getBoolean(WIFI, false)
        set(value) = prefs.edit { putBoolean(WIFI, value) }

    var lastOutcome: Outcome?
        get() = if (prefs.contains(LAST_AT)) {
            Outcome(prefs.getLong(LAST_AT, 0), prefs.getBoolean(LAST_OK, false), prefs.getString(LAST_TEXT, "") ?: "")
        } else null
        set(value) = prefs.edit {
            if (value == null) remove(LAST_AT).remove(LAST_OK).remove(LAST_TEXT)
            else putLong(LAST_AT, value.at).putBoolean(LAST_OK, value.ok).putString(LAST_TEXT, value.text)
        }

    private companion object {
        const val SERVER = "server"
        const val WIFI = "sync_on_wifi"
        const val LAST_AT = "last_sync_at"
        const val LAST_OK = "last_sync_ok"
        const val LAST_TEXT = "last_sync_text"
    }
}
