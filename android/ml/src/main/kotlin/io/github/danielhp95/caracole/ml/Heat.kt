package io.github.danielhp95.caracole.ml

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager

/**
 * What the phone says of its heat and its battery (the design's §3.4), each read as far as its Android gives it and
 * none a crash: the thermal status from API 29 ([PowerManager.getCurrentThermalStatus], its names [statusName]), the
 * thermal headroom forecast 10 s ahead from API 30 ([PowerManager.getThermalHeadroom], NaN when unsupported or asked
 * again within a second: null), the battery's charge counter in µAh and its percent ([BatteryManager]'s properties,
 * null where the gauge gives none), whether it is plugged in (the sticky battery broadcast) and Battery Saver. An API
 * the phone lacks, or one that throws, is [UNKNOWN] or null.
 */
class Heat(context: Context) {
    data class Reading(
        val thermal: String, val headroom: Float?, val chargeUah: Long?, val percent: Int?, val plugged: Boolean?,
        val powerSave: Boolean?,
    )

    private val app = context.applicationContext
    private val power = app.getSystemService(PowerManager::class.java)
    private val battery = app.getSystemService(BatteryManager::class.java)

    fun read(): Reading = Reading(thermal(), headroom(), charge(), percent(), plugged(), powerSave())

    private fun thermal(): String =
        if (Build.VERSION.SDK_INT >= 29) guarded { statusName(power.currentThermalStatus) } ?: UNKNOWN else UNKNOWN

    private fun headroom(): Float? =
        if (Build.VERSION.SDK_INT >= 30) guarded { power.getThermalHeadroom(10).takeUnless { it.isNaN() } } else null

    private fun charge(): Long? = guarded {
        battery.getLongProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER).takeIf { it > 0 }
    }

    private fun percent(): Int? = guarded {
        battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).takeIf { it in 0..100 }
    }

    private fun plugged(): Boolean? = guarded {
        app.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1)?.takeIf { it >= 0 }?.let { it != 0 }
    }

    private fun powerSave(): Boolean? = guarded { power.isPowerSaveMode }

    private inline fun <T> guarded(read: () -> T?): T? = try {
        read()
    } catch (e: RuntimeException) {
        null
    }

    companion object {
        const val UNKNOWN = "unknown"

        /** PowerManager's THERMAL_STATUS_* by name. */
        fun statusName(status: Int): String = when (status) {
            0 -> "none"
            1 -> "light"
            2 -> "moderate"
            3 -> "severe"
            4 -> "critical"
            5 -> "emergency"
            6 -> "shutdown"
            else -> UNKNOWN
        }
    }
}
