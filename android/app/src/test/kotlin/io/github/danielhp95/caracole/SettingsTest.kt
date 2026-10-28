package io.github.danielhp95.caracole

import android.content.SharedPreferences
import org.junit.Test
import kotlin.test.assertEquals

class SettingsTest {
    @Test
    fun `the text size is the pages' own until a pinch changes it, and kept`() {
        val prefs = Preferences()
        assertEquals(100, Settings(prefs).textZoom)
        Settings(prefs).textZoom = 135
        // A new Settings over the same preferences: the app started again.
        assertEquals(135, Settings(prefs).textZoom)
        assertEquals(135, prefs.getInt("text_zoom", 0))
    }

    @Test
    fun `a text size is kept fitted, and one stored out of bounds reads fitted`() {
        val prefs = Preferences()
        val settings = Settings(prefs)
        settings.textZoom = 400
        assertEquals(250, prefs.getInt("text_zoom", 0))
        settings.textZoom = 33
        assertEquals(50, settings.textZoom)
        prefs.edit().putInt("text_zoom", 1234).apply()
        assertEquals(250, settings.textZoom)
        prefs.edit().putInt("text_zoom", 103).apply()
        assertEquals(105, settings.textZoom)
    }

    @Test
    fun `the text size leaves the other settings as they were`() {
        val prefs = Preferences()
        val settings = Settings(prefs)
        settings.server = "http://192.168.1.20:8737"
        settings.syncOnWifi = true
        settings.textZoom = 80
        assertEquals("http://192.168.1.20:8737", settings.server)
        assertEquals(true, settings.syncOnWifi)
        assertEquals(80, Settings(prefs).textZoom)
    }

    /** SharedPreferences in memory: what a test needs of Android's, with no device. */
    private class Preferences : SharedPreferences {
        private val values = mutableMapOf<String, Any?>()

        override fun getAll(): Map<String, *> = values.toMap()
        override fun getString(key: String, defValue: String?) = values[key] as String? ?: defValue
        @Suppress("UNCHECKED_CAST")
        override fun getStringSet(key: String, defValues: Set<String>?) = values[key] as Set<String>? ?: defValues
        override fun getInt(key: String, defValue: Int) = values[key] as Int? ?: defValue
        override fun getLong(key: String, defValue: Long) = values[key] as Long? ?: defValue
        override fun getFloat(key: String, defValue: Float) = values[key] as Float? ?: defValue
        override fun getBoolean(key: String, defValue: Boolean) = values[key] as Boolean? ?: defValue
        override fun contains(key: String) = key in values
        override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {}
        override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {}

        override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
            private val changes = mutableMapOf<String, Any?>()
            private val removed = mutableSetOf<String>()
            private var clear = false

            private fun put(key: String, value: Any?): SharedPreferences.Editor {
                changes[key] = value
                return this
            }

            override fun putString(key: String, value: String?) = put(key, value)
            override fun putStringSet(key: String, values: Set<String>?) = put(key, values?.toSet())
            override fun putInt(key: String, value: Int) = put(key, value)
            override fun putLong(key: String, value: Long) = put(key, value)
            override fun putFloat(key: String, value: Float) = put(key, value)
            override fun putBoolean(key: String, value: Boolean) = put(key, value)
            override fun remove(key: String): SharedPreferences.Editor {
                removed.add(key)
                return this
            }
            override fun clear(): SharedPreferences.Editor {
                clear = true
                return this
            }
            override fun commit(): Boolean {
                if (clear) values.clear()
                removed.forEach { values.remove(it) }
                values.putAll(changes)
                return true
            }
            override fun apply() {
                commit()
            }
        }
    }
}
