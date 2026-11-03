package io.github.danielhp95.caracole

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit

/** The settings, the last sync's outcome and the last index import's, in the app's own preferences. */
class Settings(private val prefs: SharedPreferences) {
    constructor(context: Context) : this(context.applicationContext.getSharedPreferences("caracole", Context.MODE_PRIVATE))

    /** caracole serve's address, as typed. */
    var server: String
        get() = prefs.getString(SERVER, "") ?: ""
        set(value) = prefs.edit { putString(SERVER, value) }

    /** Whether the app syncs on Wi-Fi by itself. */
    var syncOnWifi: Boolean
        get() = prefs.getBoolean(WIFI, false)
        set(value) = prefs.edit { putBoolean(WIFI, value) }

    /** The pages' text size, in percent of their own ([TextZoom]): as the last pinch left it. */
    var textZoom: Int
        get() = TextZoom.fitted(prefs.getInt(TEXT_ZOOM, TextZoom.DEFAULT))
        set(value) = prefs.edit { putInt(TEXT_ZOOM, TextZoom.fitted(value)) }

    /** How the last sync of the mirror ended. */
    var lastOutcome: Outcome?
        get() = outcome(LAST_AT, LAST_OK, LAST_TEXT)
        set(value) = keep(value, LAST_AT, LAST_OK, LAST_TEXT)

    /** How the last import of the computer's index ended ([IndexImports]). */
    var lastImport: Outcome?
        get() = outcome(IMPORT_AT, IMPORT_OK, IMPORT_TEXT)
        set(value) = keep(value, IMPORT_AT, IMPORT_OK, IMPORT_TEXT)

    private fun outcome(at: String, ok: String, text: String): Outcome? =
        if (prefs.contains(at)) Outcome(prefs.getLong(at, 0), prefs.getBoolean(ok, false), prefs.getString(text, "") ?: "")
        else null

    private fun keep(value: Outcome?, at: String, ok: String, text: String) = prefs.edit {
        if (value == null) remove(at).remove(ok).remove(text)
        else putLong(at, value.at).putBoolean(ok, value.ok).putString(text, value.text)
    }

    private companion object {
        const val SERVER = "server"
        const val WIFI = "sync_on_wifi"
        const val TEXT_ZOOM = "text_zoom"
        const val LAST_AT = "last_sync_at"
        const val LAST_OK = "last_sync_ok"
        const val LAST_TEXT = "last_sync_text"
        const val IMPORT_AT = "last_import_at"
        const val IMPORT_OK = "last_import_ok"
        const val IMPORT_TEXT = "last_import_text"
    }
}
