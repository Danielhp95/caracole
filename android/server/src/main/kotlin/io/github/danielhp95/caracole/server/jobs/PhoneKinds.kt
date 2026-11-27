package io.github.danielhp95.caracole.server.jobs

/**
 * The phone's own job kinds, which Python never queues, their key, names, stage and words, one table that JobViews
 * reads (AGENTS.md records them as the phone's; the plan's §5.3): the render job (the phone's pages made again by a
 * new build, or after a take), a file shared to the app filed, a backup made and one restored, and the site catalogues
 * downloaded and imported (CataloguesRunner), and the chord models downloaded (ModelsRunner). Each line's `{…}`
 * blanks are filled by whoever queues or runs the job ([fill]).
 */
object PhoneKinds {
    /** A kind: its job's key prefix, its [title] and [display] (JobSpec's), its one stage (name, label), and its lines
     * while it runs, once done (and [otherwise], a second way it may end well, with [formerly] its older words, which a
     * request kept in the history may still say) and failed. */
    data class Kind(val kind: String, val key: String, val title: String, val display: String,
                    val stage: Pair<String, String>, val running: String, val done: String, val failed: String,
                    val otherwise: String? = null, val formerly: List<String> = emptyList(),
                    val pauses: List<String> = emptyList()) {
        /** Whether [line] is the kind's second way to end ([otherwise], one of its [formerly] words, or of its other
         * waits, [pauses], filled). */
        fun waits(line: String): Boolean = (listOfNotNull(otherwise) + formerly + pauses).any { fits(line, it) }
    }

    val RENDER = Kind("render", "render:", "Remake the pages", "The phone's pages", "render" to "Making the pages",
                      "Remaking pages · {done} of {total}", "Pages remade · {n} songs",
                      "Pages not made: {why}")
    val INBOX = Kind("inbox", "inbox:", "File {name}", "{name}", "file" to "Filing", "Filing {name}…",
                     "Filed · {name} of {song}", "Not filed: {why}", otherwise = "Waiting for its song: {name}")
    val BACKUP = Kind("backup", "backup:", "Back up the book", "A backup ({label})", "backup" to "Backing up",
                      "Backing up the book…", "Backed up ({label})", "Not backed up: {why}")
    val RESTORE = Kind("restore", "restore:", "Restore the book of {date}", "The book of {date}",
                       "restore" to "Restoring", "Restoring the book…", "Restored the book of {date}",
                       "Not restored: {why}")

    /** The site catalogues GitHub's release holds, downloaded and merged: its stage's words while it runs are what it
     * is doing (`{doing}`), its date the file's; its [Kind.otherwise], a wait, the download a metered network leaves
     * for the owner's go-ahead ({size}): nothing starts it again on Wi-Fi by itself, and the Journal's Try again
     * queues a job that stops so again, so its words name where the go-ahead is given, Settings' question ("… on a
     * metered network?"), in that question's words. */
    val CATALOGUES = Kind("catalogues", "catalogues:", "Download the site catalogues", "The site catalogues",
                          "catalogues" to "Catalogues", "{doing}", "Catalogues of {date}", "Not imported: {why}",
                          otherwise = "{size} to download: waiting for your go-ahead in Settings (a metered network)",
                          formerly = listOf("{size} to download: waiting for Wi-Fi or your go-ahead",
                                            "{size} to download: waiting for your go-ahead to use mobile data"))

    /** The chord models downloaded (the design's §8.4): its stage's words while it runs are what it is doing
     * (`{doing}`: "Asking GitHub for the chord models…", "Downloading the chord models · 21 of 54 MB", "Checking the
     * chord models…"), {size} the bytes on the phone once done; its [Kind.otherwise] the catalogues' metered stop, in
     * the catalogues' words, and its other wait ([Kind.pauses]) GitHub's hour spent, core.catalogues' [LIMITED]
     * words, whose {time} is when it may be asked again. */
    val MODELS = Kind("models", "models:", "Download the chord models", "The chord models", "models" to "Chord models",
                      "{doing}", "Chord models ready · {size}", "Not downloaded: {why}",
                      otherwise = "{size} to download: waiting for your go-ahead in Settings (a metered network)",
                      pauses = listOf(LIMITED))

    /** core.catalogues' Limited, its words as a template: GitHub's share of the hour spent, {time} the minute after
     * which it may be asked again. */
    const val LIMITED = "Try again after {time} — GitHub has answered this network's share of requests for the hour."

    val ALL: Map<String, Kind> = listOf(RENDER, INBOX, BACKUP, RESTORE, CATALOGUES, MODELS).associateBy { it.kind }

    /** Whether [line] is [template] with its `{name}` blanks filled (each blank any text): its words between the blanks,
     * in their order, the first at its start and the last at its end. */
    fun fits(line: String, template: String): Boolean {
        val pieces = ArrayList<String>()
        var at = 0
        while (true) {
            val open = template.indexOf('{', at)
            val close = if (open < 0) -1 else template.indexOf('}', open)
            if (close < 0) {
                pieces += template.substring(at)
                break
            }
            pieces += template.substring(at, open)
            at = close + 1
        }
        if (pieces.size == 1) return line == pieces[0]
        if (!line.startsWith(pieces.first())) return false
        var from = pieces.first().length
        for (piece in pieces.subList(1, pieces.size - 1)) {
            val found = line.indexOf(piece, from)
            if (found < 0) return false
            from = found + piece.length
        }
        return line.length - pieces.last().length >= from && line.endsWith(pieces.last())
    }

    /** [line] with each `{name}` blank filled from [values]; a blank no value names is left as it is. */
    fun fill(line: String, vararg values: Pair<String, Any>): String =
        values.fold(line) { text, (name, value) -> text.replace("{$name}", value.toString()) }
}
