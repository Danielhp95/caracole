package io.github.danielhp95.caracole

/**
 * The first start's offer of the site catalogues as the library screen holds it (MainActivity's card,
 * SiteCatalogues.firstStart deciding it is made), apart from Android, so that a JVM test holds it:
 *
 * - [offer]ed, it is [waiting] for its answer, [shown] only once the opening screen is gone ([openingGone]): never
 *   drawn over the logo, nor live under it;
 * - Back while it shows is its Not now ([back]); under the opening screen Back isn't its (the app goes, the offer
 *   still to answer, and the next start offers it again);
 * - a computer set meanwhile ([resumed]) takes it away, opening nothing: it was made to a phone with none;
 * - Not now opens Settings only where a first start would have ([offer]'s `thenSettings`), and not once Settings was
 *   seen while it waited ([settingsSeen]); Download opens it, whose row follows the job;
 * - answered once: each way to answer it gives an [Answer] the first time alone, which the screen acts on (the card
 *   hidden, kv `catalogues:offered` written, the job queued for Download, Settings opened);
 * - kept across a recreation ([saved], [restore]) until it is answered.
 */
internal class CatalogueOffer {
    /** What the screen does of an answer: queue the catalogues' job, open Settings. */
    data class Answer(val download: Boolean, val openSettings: Boolean)

    /** Offered and not answered yet. */
    var waiting = false
        private set

    /** On the screen (the opening screen gone). */
    var shown = false
        private set

    private var thenSettings = false

    /** Offered; [thenSettings]: a first start with nothing set up, which opens Settings once it is answered. */
    fun offer(thenSettings: Boolean) {
        waiting = true
        this.thenSettings = thenSettings
    }

    /** The opening screen gone: whether to show the card now. */
    fun openingGone(): Boolean {
        if (!waiting) return false
        shown = true
        return true
    }

    /** Back: its Not now while it shows; null when Back isn't the offer's. */
    fun back(): Answer? = if (waiting && shown) answer(download = false) else null

    /** The screen back with [server] in the settings: a computer set takes the offer away, opening nothing. */
    fun resumed(server: String): Answer? = if (waiting && server.isNotBlank()) answer(download = false, settings = false) else null

    /** Settings opened while it waited: Not now needn't open it again. */
    fun settingsSeen() {
        thenSettings = false
    }

    /** Download or Not now; [settings] whether Not now opens Settings (the offer's own rule by default). */
    fun answer(download: Boolean, settings: Boolean = thenSettings): Answer? {
        if (!waiting) return null
        waiting = false
        shown = false
        return Answer(download, download || settings)
    }

    /** What a recreation keeps: null when nothing waits, else whether Settings opens after it. */
    fun saved(): Boolean? = if (waiting) thenSettings else null

    /** [saved]'s, after a recreation. */
    fun restore(saved: Boolean?) {
        if (saved != null) offer(saved)
    }
}
