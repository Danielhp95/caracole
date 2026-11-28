package io.github.danielhp95.caracole.ml

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock

/**
 * What the phone says of its heat and its battery (the design's §3.4), each read as far as its Android gives it and
 * none a crash: the thermal status from API 29 ([PowerManager.getCurrentThermalStatus], its names [statusName]), the
 * thermal headroom forecast 10 s ahead from API 30 ([PowerManager.getThermalHeadroom], asked at most every 10 s, the
 * last answer between; NaN, unsupported or asked too soon: null), the battery's charge counter in µAh and its
 * percent ([BatteryManager]'s properties,
 * null where the gauge gives none), whether it is plugged in (the sticky battery broadcast) and Battery Saver. An API
 * the phone lacks, or one that throws, is [UNKNOWN] or null.
 */
class Heat(context: Context) : HeatGauge {
    data class Reading(
        val thermal: String, val headroom: Float?, val chargeUah: Long?, val percent: Int?, val plugged: Boolean?,
        val powerSave: Boolean?,
    )

    private val app = context.applicationContext
    private val power = app.getSystemService(PowerManager::class.java)
    private val battery = app.getSystemService(BatteryManager::class.java)

    override fun read(): Reading = Reading(thermal(), headroom(), charge(), percent(), plugged(), powerSave())

    private fun thermal(): String =
        if (Build.VERSION.SDK_INT >= 29) guarded { statusName(power.currentThermalStatus) } ?: UNKNOWN else UNKNOWN

    private var headroomAt = Long.MIN_VALUE
    private var lastHeadroom: Float? = null

    /** Asked at most every [HEADROOM_MS]: Android answers NaN to a call that comes sooner. Between, the last answer. */
    @Synchronized private fun headroom(): Float? {
        if (Build.VERSION.SDK_INT < 30) return null
        val now = SystemClock.elapsedRealtime()
        if (headroomAt == Long.MIN_VALUE || now - headroomAt >= HEADROOM_MS) {
            headroomAt = now
            lastHeadroom = guarded { power.getThermalHeadroom(10).takeUnless { it.isNaN() } }
        }
        return lastHeadroom
    }

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
        const val HEADROOM_MS = 10_000L

        /** The statuses at which the bench stops a session (the design's §3.4: critical or worse stops a hearing). */
        val TOO_HOT = setOf("critical", "emergency", "shutdown")

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

/** What the phone says of its heat and battery now: [Heat] on a phone, a script in HeatTest. */
fun interface HeatGauge {
    fun read(): Heat.Reading
}

/** A hearing given up for the phone's heat, in [HeatRules.TOO_HOT]'s words. */
class TooHot(words: String) : Exception(words)

/**
 * The design's §3.4 table, decisions over a [Heat.Reading] alone (HeatTest), which [Pipeline] consults before it
 * starts ([start]), before each stage ([between], waited out by [cool]) and before each window batch and chunk of a
 * model's ([within]):
 *
 * - none or light (or unknown: an Android before 10), headroom under [WARM] or none said: [THREADS] intra-op threads;
 * - moderate, or headroom [WARM] or more, or Battery Saver on: [FEWER_THREADS];
 * - severe: between stages it waits, "waiting for the phone to cool" ([COOLING]), asking every [COOL_POLL_MS], up to
 *   [COOL_MOST_MS], then [TOO_HOT]; within a stage it goes on;
 * - critical or worse: it stops at the next window batch or chunk, [TOO_HOT].
 *
 * And before it starts: under [LOW_BATTERY] % and not charging (or not known to be), it refuses, [CHARGE_FIRST]. A
 * stage's threads are fixed as its model's session opens: within one, only a stop changes anything.
 */
object HeatRules {
    const val THREADS = 4
    const val FEWER_THREADS = 2
    const val WARM = 0.85f
    const val LOW_BATTERY = 15
    const val COOL_POLL_MS = 10_000L
    const val COOL_MOST_MS = 5 * 60_000L
    const val COOLING = "waiting for the phone to cool"
    const val TOO_HOT = "the phone is too hot to work out chords now; try again once it cools"
    const val CHARGE_FIRST = "Charge the phone first: chords from audio need at least 15 % of the battery."

    sealed class Verdict
    data class Go(val threads: Int) : Verdict()
    data class Wait(val words: String) : Verdict()
    data class Stop(val words: String) : Verdict()

    private val SEVERE = "severe"

    /** Why the hearing may not start, or null. */
    fun start(r: Heat.Reading): String? =
        if (r.percent != null && r.percent < LOW_BATTERY && r.plugged != true) CHARGE_FIRST else null

    /** Before a stage. */
    fun between(r: Heat.Reading): Verdict = when {
        r.thermal in Heat.TOO_HOT -> Stop(TOO_HOT)
        r.thermal == SEVERE -> Wait(COOLING)
        else -> Go(threads(r))
    }

    /** Before a chunk within a stage. */
    fun within(r: Heat.Reading): Verdict = if (r.thermal in Heat.TOO_HOT) Stop(TOO_HOT) else Go(threads(r))

    fun threads(r: Heat.Reading): Int =
        if (r.thermal == "moderate" || r.thermal == SEVERE || (r.headroom ?: 0f) >= WARM || r.powerSave == true) {
            FEWER_THREADS
        } else THREADS

    /** [between] waited out: the threads the next stage takes, once [gauge] says go; [waiting] told [COOLING] once a
     * wait begins, [sleep] for [COOL_POLL_MS] between readings, by [now]'s clock; [TooHot] after [COOL_MOST_MS] of
     * waiting, or at a reading that says stop; [check] called before each reading (a cancel: what it throws ends the
     * wait there). */
    fun cool(gauge: HeatGauge, sleep: (Long) -> Unit, now: () -> Long, waiting: (String) -> Unit,
             check: () -> Unit = {}): Int {
        var since: Long? = null
        while (true) {
            check()
            when (val v = between(gauge.read())) {
                is Go -> return v.threads
                is Stop -> throw TooHot(v.words)
                is Wait -> {
                    val began = since ?: now().also { since = it; waiting(v.words) }
                    if (now() - began >= COOL_MOST_MS) throw TooHot(TOO_HOT)
                    sleep(COOL_POLL_MS)
                }
            }
        }
    }

    /** [within] as a stage's chunk asks it: [TooHot] for a stop. */
    fun check(gauge: HeatGauge) {
        val v = within(gauge.read())
        if (v is Stop) throw TooHot(v.words)
    }
}
