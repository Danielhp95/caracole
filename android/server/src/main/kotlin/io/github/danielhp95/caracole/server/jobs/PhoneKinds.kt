package io.github.danielhp95.caracole.server.jobs

/**
 * The phone's own job kinds, which Python never queues, their key, stage and words, one table that JobViews reads
 * (AGENTS.md records them as the phone's; the plan's §5.3): the render job (the phone's pages made again by a new
 * build), a file shared to the app filed, a backup made and one restored. Each line's `{…}` blanks are filled by the
 * job's runner ([fill]).
 */
object PhoneKinds {
    /** A kind: its job's key prefix, its one stage (name, label), and its lines while it runs, once done (and
     * [otherwise], a second way it may end well) and failed. */
    data class Kind(val kind: String, val key: String, val stage: Pair<String, String>, val running: String,
                    val done: String, val failed: String, val otherwise: String? = null)

    val RENDER = Kind("render", "render:", "render" to "Making the pages", "Making the pages again: {done} of {total}",
                      "Pages made again for {n} songs", "Pages not made: {why}")
    val INBOX = Kind("inbox", "inbox:", "file" to "Filing the file", "Filing {name}…", "Filed as {name} of {song}",
                     "Not filed: {why}", otherwise = "Waiting for a song that fits: {name}")
    val BACKUP = Kind("backup", "backup:", "backup" to "Backing up", "Backing up the library…", "Backed up ({label})",
                      "Not backed up: {why}")
    val RESTORE = Kind("restore", "restore:", "restore" to "Restoring", "Restoring the library…",
                       "Restored the library of {date}", "Not restored: {why}")

    val ALL: Map<String, Kind> = listOf(RENDER, INBOX, BACKUP, RESTORE).associateBy { it.kind }

    /** [line] with each `{name}` blank filled from [values]; a blank no value names is left as it is. */
    fun fill(line: String, vararg values: Pair<String, Any>): String =
        values.fold(line) { text, (name, value) -> text.replace("{$name}", value.toString()) }
}
