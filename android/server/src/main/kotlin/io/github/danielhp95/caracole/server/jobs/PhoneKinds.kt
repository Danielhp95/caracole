package io.github.danielhp95.caracole.server.jobs

/**
 * The phone's own job kinds, which Python never queues, their key, stages and words, one table that JobViews reads
 * (AGENTS.md records them as the phone's): skeleton-m5m6 adds render, inbox, backup and restore (the plan's §5.3).
 * Milestone 4 has none.
 */
object PhoneKinds {
    /** A kind: its job's key prefix, its one stage (name, label), and its lines while it runs, once done and failed
     * (each with its `{…}` blanks, filled by the job's runner). */
    data class Kind(val kind: String, val key: String, val stage: Pair<String, String>, val running: String,
                    val done: String, val failed: String)

    val ALL: Map<String, Kind> = emptyMap()
}
