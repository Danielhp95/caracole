package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * youtube.classify: what a yt-dlp run that failed came to, by the data's `classify` member, its `order` the caller's:
 * the gate's log first ([GATE], the runner's step: a refusal of the app's gate or its 407 is never read from
 * stderr), then the exit status ([OK_EXIT] is [OK], [of] not asked), then [of] over stderr.
 *
 * [of]: stderr's lines by str.splitlines, each Python-stripped, the empty ones and those that begin `skip_prefix`
 * dropped; the error line, the last that begins `error_prefix`, less it, stripped; the warning lines, those that begin
 * `warning_prefix`; then the `steps` in order (each `over` one of those, its `pattern` the data's, an `and` a second
 * that must match too), the first that matches deciding, else `otherwise`.
 */
object Classify {
    private class Step(val cls: String, val over: String, val pattern: String, val and: Step?)

    private val rules: JsonObject by lazy { YouTubeData.read().classify }
    private val gateStep: JsonObject by lazy {
        rules.getValue("steps").jsonArray.map { it.jsonObject }.single { it.getValue("over").jsonPrimitive.content == GATE_LOG }
    }
    private val steps: List<Step> by lazy {
        rules.getValue("steps").jsonArray.map { it.jsonObject }
            .filter { it.getValue("over").jsonPrimitive.content != GATE_LOG }
            .map { s ->
                val and = s["and"]?.jsonObject
                Step(s.getValue("class").jsonPrimitive.content, s.getValue("over").jsonPrimitive.content,
                    s.getValue("pattern").jsonPrimitive.content,
                    and?.let { Step("", it.getValue("over").jsonPrimitive.content, it.getValue("pattern").jsonPrimitive.content, null) })
            }
    }
    private fun text(name: String): String = rules.getValue(name).jsonPrimitive.content

    /** The exit status of a run that is ok whatever its stderr says. */
    val OK_EXIT: Int by lazy { rules.getValue("ok_exit").jsonPrimitive.int }

    /** What such a run is. */
    val OK: String by lazy { text("ok_class") }

    /** The gate's step's class: decided from the gate's log by the runner, before the exit status and stderr. */
    val GATE: String by lazy { gateStep.getValue("class").jsonPrimitive.content }

    /** What [of] answers (`classes`: blocked, unavailable, pass_over, outdated, error). */
    val CLASSES: List<String> by lazy { YouTubeData.read().json.getValue("classes").jsonArray.map { it.jsonPrimitive.content } }

    /** A run the gate didn't refuse: [OK] where it exited [OK_EXIT], else [of] its stderr. */
    fun ofRun(exit: Int, stderr: String): String = if (exit == OK_EXIT) OK else of(stderr)

    /** classify(stderr), of a run that exited otherwise than [OK_EXIT]. */
    fun of(stderr: String): String {
        val skip = text("skip_prefix")
        val errorPrefix = text("error_prefix")
        val warningPrefix = text("warning_prefix")
        val lines = PyStr.splitlines(stderr).map { Py.strip(it) }.filter { it.isNotEmpty() && !it.startsWith(skip) }
        val errors = lines.filter { it.startsWith(errorPrefix) }.map { Py.strip(it.removePrefix(errorPrefix)) }
        val read = mapOf(
            "stderr" to lines,
            "error_line" to errors.takeLast(1),
            "warning_lines" to lines.filter { it.startsWith(warningPrefix) },
        )
        val data = YouTubeData.read()
        fun found(over: String, pattern: String): Boolean {
            val regex = data.pattern(pattern)
            return read.getValue(over).any { regex.containsMatchIn(it) }
        }
        for (step in steps) {
            if (found(step.over, step.pattern) && (step.and == null || found(step.and.over, step.and.pattern))) return step.cls
        }
        return text("otherwise")
    }

    private const val GATE_LOG = "gate_log"
}
