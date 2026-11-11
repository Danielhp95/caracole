package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.lookups.Review
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.Instant

/**
 * An uncertain match reviewed on the phone (web/review_routes.py):
 *
 *     GET  /review?song=ID  a song in review's picker, on a page of its own
 *     POST /review          a song in review's answer, as `caracole review --song` writes it
 *
 * A pick from the picker is `caracole review --song "A - T" --pick ARTIST/SONG` (or `--none --seen ARTIST/SONG…`),
 * queued and answered as a fetch is (to the page's script, its job; to a form, its line in the Requests tab), never
 * into the song's own request nor after its lookup (`join` false), and run by the phone's review runner
 * (ReviewRunner), which writes the answer and decides the song's match again. With Fetch it now, a pick is looked up
 * after it: the lookup Fetch now queues (`caracole get`), which matches the song, fetches it and makes its pages, in
 * place of caracole serve's `caracole fetch --song` and `render --song`, which the phone hasn't. The candidates the page
 * showed must be the song's now. The picker is on the cards too (the library page's script); a request that ended in
 * a review leads to its page (the Requests tab's Pick the match), and so does a song not found's line (Look in the
 * index), which offers what `caracole search` finds for it.
 *
 * The page is the message page's frame, style and policy (MessagePage: no script, forms to the server alone), with the
 * phone's form token ([csrf]) and the library named as every page of the phone's names it ([libraryName]).
 * vectors/web/review.jsonl holds both routes to caracole serve's answers (ReviewReplay).
 */
class ReviewRoutes(val parts: PhoneParts, private val csrf: String,
                   private val libraryName: () -> String = { parts.config().libraryName.orEmpty() },
                   private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/review", "a song in review's picker, on a page of its own (song)",
              get = GetAnswer { picker(it) }),
        Route("POST", "/review", "a song in review's answer, as caracole review --song writes it (song, pick, shown, " +
                                 "fetch)",
              post = PostAnswer { _, form -> review(form) }),
    )

    /** pages.Pick: a song in review and its candidates (library_page.review_choices), for the picker; with [search],
     * a song not found and what `caracole search` finds for it. [title] as the card shows it (clean_title). */
    internal data class Pick(val songId: Long, val display: String, val title: String, val artist: String,
                             val choices: List<JsonObject>, val search: Boolean = false) {
        val refs: List<String> get() = choices.map { (it["ref"] as JsonPrimitive).content }
    }

    /** review_routes.picker: a song in review's picker, on a page of its own. */
    private fun picker(request: Request): Response {
        val asked = LookupForms.songId(PyUrl.query(request.target)["song"].orEmpty(), where = "address")
        val (song, overrides, pick) = parts.database.read { db ->
            val overrides = LookupForms.overrides(db)
            val song = LookupForms.song(db, asked)
            Triple(song, overrides, offer(db, song, overrides, search = true))
        }
        if (pick == null) LookupForms.notIgnored(song, overrides)
        if (pick == null && song.review) {
            throw Refused(409, NOTHING, "${song.display} has no candidates. caracole review offers a pin or an " +
                                        "ignore.")
        }
        if (pick == null) throw Refused(409, NOTHING, "${song.display} needs no review. Nothing to pick.")
        if (pick.choices.isEmpty()) {
            throw Refused(409, NOTHING, "Nothing close to ${song.display} in UG's index.")
        }
        val html = page(pick, csrf, LibraryName.phone(libraryName()))
        return Response(200, Body.Bytes(html.toByteArray(Charsets.UTF_8)),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to MessagePage.csp))
    }

    /**
     * review_routes.review: a song in review's answer, from the picker, queued: `pick` a candidate's ARTIST/SONG,
     * looked up at once with `fetch`, or "none", which rejects the candidates `shown`. They must be the song's
     * candidates now; a song not found takes one of its search hits, the same way. The song's own request, if one
     * waits or runs, goes first.
     */
    private fun review(form: Map<String, String>): Response {
        val asked = LookupForms.songId(form["song"].orEmpty())
        val pick = Py.strip(form["pick"].orEmpty())
        val (song, overrides, offered) = parts.database.read { db ->
            val overrides = LookupForms.overrides(db)
            val song = LookupForms.song(db, asked)
            Triple(song, overrides, offer(db, song, overrides, search = true))
        }
        LookupForms.notIgnored(song, overrides)
        if (offered == null) {
            throw Refused(409, NOTHING, "${song.display} needs no review now. Reload to see where it stands.")
        }
        val refs = offered.refs
        if (pick.isEmpty()) throw Refused(400, "No answer", "Pick a candidate, or None of these.")
        if (Py.split(form["shown"].orEmpty()) != refs || refs.isEmpty()) {
            throw Refused(409, "The candidates changed",
                          "${song.display} was matched again since this page loaded; its candidates changed. " +
                              "Reload and pick again.")
        }
        if (pick == NONE && offered.search) {
            throw Refused(400, "Not an answer", "A song not found takes one of its search hits, or nothing.")
        }
        if (pick != NONE && pick !in refs) throw Refused(400, "Not a candidate", "$pick isn't one of its candidates.")
        val fetch = pick != NONE && form["fetch"] in FETCH
        var title = if (pick == NONE) "None of these for ${song.display}" else "Pick $pick for ${song.display}"
        var commands = if (pick == NONE) JobCommands.reviewSteps(song.display, seen = refs)
                       else JobCommands.reviewSteps(song.display, pick = pick)
        if (fetch) {  // the review matched it again already; the phone's lookup is its fetch
            title += ", and fetch"
            commands = commands + JobCommands.lookupSteps(song.artist, song.title)
        }
        val spec = JobSpec(title = title, key = song.key,
                           kind = JobCommands.kindOf(song.key, commands.map { it.args }, emptyList()),
                           stages = emptyList(), display = song.display, join = false, commands = commands,
                           fetching = fetch)
        // Never into the song's own request, nor after its lookup: checked under the queue's lock.
        val (job, new) = parts.queue.submitOrRefuse(spec)
        if (!new) {
            throw Refused(409, "Wait for its request",
                          "A request for ${song.display} is queued or running. Pick once it ends.")
        }
        return Answers.queued(LookupForms.view(parts.database, parts.queue, parts.cards, job, clock()))
    }

    /** review_routes._offer: what a song's picker offers: a review's candidates; for a song not found, with [search],
     * what `caracole search` finds for it, or without, no choices yet. Null for a song with nothing to pick: ignored,
     * settled, or a review without candidates. */
    private fun offer(db: Db, song: SongRow, overrides: Overrides, search: Boolean = false): Pick? {
        if (song.status == "ignored" || song.key in overrides.ignore) return null
        val title = Normalize.cleanTitle(song.title)
        if (song.review) {
            val choices = Review.choices(db, song)
            return if (choices.isNotEmpty()) Pick(song.id, song.display, title, song.artist, choices) else null
        }
        if (song.matchDecision != "not_found") return null
        val hits = if (search) Review.searchCandidates(db, song, overrides.reject[song.key].orEmpty()) else emptyList()
        return Pick(song.id, song.display, title, song.artist, Review.choices(db, song, hits), search = true)
    }

    internal companion object {
        private const val NOTHING = "Nothing to pick"
        private const val NONE = "none"
        private val FETCH = setOf("1", "on", "yes")

        /** pages.review_page: a song in review's picker on a page of its own, for the Requests tab to link to; or a
         * song not found's, with what `caracole search` finds for it. */
        fun page(pick: Pick, csrf: String, name: LibraryName): String {
            val lede = if (pick.search) {
                "<p class=\"lede\">Nothing in UG's index matched ${esc(pick.display)} closely. These are what " +
                    "<code>caracole search</code> finds for its artist and title: pick one only if it's the song, and " +
                    "we note it under <code>[match]</code>.</p>"
            } else {
                "<p class=\"lede\">Not sure which UG song ${esc(pick.display)} is. Pick it here, as " +
                    "<code>caracole review</code> would ask.</p>"
            }
            return MessagePage.html("Pick the match", "<div class=\"pick-page\">$lede${form(pick, csrf, focus = true)}</div>",
                                    name)
        }

        /** pages.picker_form: the picker's form, as the library page's script builds it on a card: a radio group of
         * the candidates and "None of these" (not for search hits: nothing proposed them), "Fetch it now" (ticked) and
         * Pick, posted to `/review`; [focus], its first candidate takes the focus when the page opens. */
        fun form(pick: Pick, csrf: String, focus: Boolean = false): String {
            val rows = ArrayList<String>()
            for ((n, c) in pick.choices.withIndex()) {
                val why = listOf(text(c, "why"), "score ${score(c)}", text(c, "tabs")).filter { it.isNotEmpty() }
                    .joinToString(" · ")
                val name = "${text(c, "artist")} – ${text(c, "title")}"
                val href = text(c, "href")
                val page = if (href.startsWith("https://") || href.startsWith("http://")) {
                    "<a class=\"choice-link\" href=\"${esc(href)}\" target=\"_blank\" rel=\"noopener noreferrer\" " +
                        "aria-label=\"${esc(name)} on UG, new tab\">UG ↗</a>"
                } else ""
                rows += choice(text(c, "ref"), "${text(c, "n")}. $name", why, autofocus = focus && n == 0) + page + "</div>"
            }
            val hint = if (pick.search) {
                "Your pick goes in overrides.toml under [match], with no [alias]: a hit under another artist may be a " +
                    "cover. Fetch then asks UG for it."
            } else {
                rows += choice(NONE, "None of these", "Drops them for good; we keep looking",
                               cls = "choice none") + "</div>"
                "Your answer goes in overrides.toml. Fetch then asks UG for the song picked; None of these fetches " +
                    "nothing."
            }
            val shown = pick.refs.joinToString(" ")
            val question = "Which UG song is “${pick.title}” by ${pick.artist}?"
            return "<form class=\"pick-form\" method=\"post\" action=\"/review\">\n" +
                "  <input type=\"hidden\" name=\"csrf\" value=\"${esc(csrf)}\">\n" +
                "  <input type=\"hidden\" name=\"song\" value=\"${pick.songId}\">\n" +
                "  <input type=\"hidden\" name=\"shown\" value=\"${esc(shown)}\">\n" +
                "  <fieldset class=\"choices\"><legend>${esc(question)}</legend>\n  " + rows.joinToString("\n  ") +
                "\n  </fieldset>\n" +
                "  <div class=\"pick-row\"><label class=\"pick-check\"><input type=\"checkbox\" name=\"fetch\" " +
                "value=\"1\" checked>Fetch</label><button class=\"btn primary\" type=\"submit\">Pick</button></div>\n" +
                "  <p class=\"pick-hint\">${esc(hint)}</p>\n</form>"
        }

        /** pages._choice: one radio of the picker, in its row (left open, for the row's link). */
        private fun choice(value: String, name: String, why: String, cls: String = "choice",
                           autofocus: Boolean = false): String =
            "<div class=\"$cls\"><label class=\"choice-pick\"><input type=\"radio\" name=\"pick\" " +
                "value=\"${esc(value)}\" required${if (autofocus) " autofocus" else ""}><span class=\"choice-text\">" +
                "<span class=\"choice-name\">${esc(name)}</span><span class=\"choice-why\">${esc(why)}</span>" +
                "</span></label>"

        /** A choice's member as str() gives it ("" for none). */
        private fun text(c: JsonObject, name: String): String = (c[name] as? JsonPrimitive)?.contentOrNull.orEmpty()

        /** `c.get('score') or 0`: the choice's score, 0 for none. */
        private fun score(c: JsonObject): String = text(c, "score").ifEmpty { "0" }

        private fun esc(s: String): String = PyText.escape(s)
    }
}
