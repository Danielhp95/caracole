package io.github.danielhp95.caracole.viewer.harpfit

import io.github.danielhp95.caracole.viewer.harptab.Tab

/** harpfit.Fit: a harp's fit with the record, its key, the share of the sung notes on a chord tone, of how many. */
data class Fit(val harp: Int, val share: Double, val notes: Int)

/** harpfit.Choice: the harp a tab's page starts on, and why (harpfit.WHY). */
data class Choice(val harp: Int, val why: String, val fits: List<Fit> = emptyList(), val named: Int? = null,
                  val page: Int? = null, val tonic: Int? = null) {
    /** harpfit.Choice.tabs_harp: the harp the tab is played on, as far as caracole can tell. */
    val tabsHarp: Int? get() = TODO("lane harmonica-page")
}

/** viewer/harpfit.py: the harp a tab's page starts on (lane harmonica-page). */
object HarpFit {
    fun choose(tab: Tab, cho: String? = null, key: String? = null, keySource: String? = null,
               pageKey: String? = null): Choice = TODO("lane harmonica-page")
}
