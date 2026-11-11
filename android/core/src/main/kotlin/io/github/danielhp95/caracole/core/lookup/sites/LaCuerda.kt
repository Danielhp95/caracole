package io.github.danielhp95.caracole.core.lookup.sites

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSheets
import io.github.danielhp95.caracole.core.lacuerda.internal.fetch.ToTry
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd

/**
 * get.py's sheet stage from a LaCuerda page picked (`--lacuerda`, `[lacuerda]`): LaCuerda asked first, for the sheet
 * you picked there, as get.py's `sheet` asks `lacuerda()` before Ultimate Guitar. The work is the lacuerda stage's
 * ([LaCuerdaStages.ask]); the frame (lane lookup's Lookup) asks LaCuerda once a lookup, through the plain envelope
 * for a pick, says the stage's words for the sheet, and turns to Ultimate Guitar when the sheet kept isn't the pick.
 */
object LaCuerdaPickStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = LaCuerdaStages.ask(ctx)
}

/**
 * get.py's lacuerda stage, `_Lookup.lacuerda`: LaCuerda's pass for the song alone ([LaCuerdaSheets.lacuerdaSheets],
 * `only` its id), its spent budget or its first failure raised inside the asking as get.py's work raises them; "sheet
 * kept from LaCuerda", "not on LaCuerda" or "kept what it had", or, when the pass tried nothing, why (the pick kept
 * already, the pick waiting, or not a song for LaCuerda). The frame asks it for the sheet when UG kept none, within
 * what leaves `SHEETS_SHARE` for sheets once the song has one, and says what that came to again at this stage.
 */
object LaCuerdaStage : SiteStage {
    override fun run(ctx: StageContext): StageEnd = LaCuerdaStages.ask(ctx)
}

/** What the two LaCuerda stages share: the asking and get.py's words for what the work came to; an end that isn't
 * the work's (a cooldown, a block, a spent budget, an error) is LookupWords.end's (`_usable` and `asking`). */
internal object LaCuerdaStages {
    const val KEPT = "sheet kept from LaCuerda"
    const val MISSING = "not on LaCuerda"
    const val KEPT_WHAT_IT_HAD = "kept what it had"
    const val PICK_KEPT = "your LaCuerda pick is the sheet already"
    const val NOT_FOR_LACUERDA = "not for LaCuerda: not Spanish, a full sheet already, or asked this month"
    const val PIN_KEPT = "your pinned UG tab is kept over your LaCuerda pick"
    const val PICK_ASKED = "your LaCuerda pick waits: asked this month already"
    const val PICK_WAITS = "your LaCuerda pick comes tonight"

    /** `lacuerda()`'s `ask` through the stage's asking, and its end in get.py's words. */
    fun ask(ctx: StageContext): StageEnd {
        val asked = ctx.asking.ask(LaCuerdaSheets.PROVIDER) { client ->
            val s = LaCuerdaSheets.lacuerdaSheets(ctx.db, client, ctx.library, ctx.config.rank, ctx.now, ctx.overrides,
                                                  setOf(ctx.song.id))
            if (s.budgetExhausted) throw BudgetExhausted(LaCuerdaSheets.PROVIDER)
            s.failures.firstOrNull()?.let { throw it.second }
            when {
                s.tried == 0 && holdsPick(ctx) -> StageEnd("done", PICK_KEPT)
                s.tried == 0 && picked(ctx) != null -> StageEnd("skipped", pickWaits(ctx))
                s.tried == 0 -> StageEnd("skipped", NOT_FOR_LACUERDA)
                s.kept > 0 -> StageEnd("done", KEPT)
                s.missing > 0 -> StageEnd("done", MISSING)
                else -> StageEnd("done", KEPT_WHAT_IT_HAD)
            }
        }
        return LookupWords.end(ctx.config, LaCuerdaSheets.PROVIDER, asked)
    }

    /** `_picked`: the LaCuerda song or version you picked for the song, or null. */
    private fun picked(ctx: StageContext): LaCuerdaPick? = ctx.overrides.lacuerda[ctx.song.key]

    /** get.kept_sheet's version: the song's human sheet, else its auto sheet. */
    private fun keptSheet(ctx: StageContext): VersionRow? {
        val kept = Kept.keptFiles(ctx.db, ctx.song.id).associateBy { it.name }
        val f = Versions.SHEET_FILE_NAMES.firstNotNullOfOrNull { kept[it] } ?: return null
        return Versions.get(ctx.db, f.versionId)
    }

    /** `_holds_pick`: whether the sheet kept is the LaCuerda one you picked. */
    private fun holdsPick(ctx: StageContext): Boolean {
        val pick = picked(ctx) ?: return false
        val version = keptSheet(ctx) ?: return false
        return version.provider == LaCuerdaSheets.PROVIDER && pick.holds(version.tabId)
    }

    /** `_pick_waits`: why the LaCuerda song you picked wasn't asked for: the tab you pinned on Ultimate Guitar is the
     * sheet kept, which no pick replaces, or LaCuerda answered for the song this month. */
    private fun pickWaits(ctx: StageContext): String {
        val version = keptSheet(ctx)
        if (version != null && ToTry.pinned(ctx.overrides, ctx.song, version)) return PIN_KEPT
        val checked = Songs.byId(ctx.db, ctx.song.id)?.lacuerdaCheckedAt
        return if (!checked.isNullOrEmpty()) PICK_ASKED else PICK_WAITS
    }
}
