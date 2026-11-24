package io.github.danielhp95.caracole.core.catalogues

import io.github.danielhp95.caracole.core.catalogues.FakeGitHub.Reply
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.mirror.Http
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URI
import java.time.Instant
import java.time.ZoneOffset
import kotlin.test.assertFailsWith

class ReleaseTest {
    private val github = FakeGitHub()
    private val http = Http()

    @After fun close() = github.close()

    private fun listed(name: String, uploaded: Boolean = true) =
        Listed(name, 1000, "ab".repeat(32), uploaded, "https://api.github.com/repos/Danielhp95/caracole/releases/assets/1")

    // --- choose -----------------------------------------------------------------------------------------------------

    @Test fun passesOverAFileNotUploaded() {
        val c = choose(listOf(listed("indexes-s17-20261124T0312Z.sqlite.gz", uploaded = false),
                              listed("indexes-s17-20261117T0310Z.sqlite.gz")), 17, null)
        assertEquals("indexes-s17-20261117T0310Z.sqlite.gz", (c as Choice.Take).file.name)
        assertEquals(Named(17, Instant.parse("2026-11-17T03:10:00Z")), c.named)
    }

    @Test fun newestIsByTheNamesStampNotTheListsOrder() {
        // 2026-11-24 sorts after 2026-11-17 by its stamp; 03:09 on the 24th before 03:12 on the same day.
        val older = listed("indexes-s17-20261117T0310Z.sqlite.gz")
        val sameDay = listed("indexes-s17-20261124T0309Z.sqlite.gz")
        val newer = listed("indexes-s17-20261124T0312Z.sqlite.gz")
        for (order in listOf(listOf(older, sameDay, newer), listOf(newer, sameDay, older), listOf(sameDay, newer, older))) {
            assertEquals(newer.name, (choose(order, 17, null) as Choice.Take).file.name)
        }
    }

    @Test fun aNewerSchemaIsSaidBeforeAnOlderOne() {
        assertEquals(Choice.Newer(18), choose(listOf(listed("indexes-s18-20261124T0312Z.sqlite.gz"),
                                                    listed("indexes-s16-20261124T0312Z.sqlite.gz")), 17, null))
        assertEquals(Choice.Newer(19), choose(listOf(listed("indexes-s18-20261124T0312Z.sqlite.gz"),
                                                    listed("indexes-s19-20261101T0312Z.sqlite.gz")), 17, null))
        assertEquals(Choice.Older(16), choose(listOf(listed("indexes-s15-20261124T0312Z.sqlite.gz"),
                                                    listed("indexes-s16-20261101T0312Z.sqlite.gz")), 17, null))
    }

    @Test fun thisSchemasFileWinsOverAnyOther() {
        val c = choose(listOf(listed("indexes-s18-20261124T0312Z.sqlite.gz"),
                              listed("indexes-s17-20261117T0310Z.sqlite.gz")), 17, null)
        assertEquals("indexes-s17-20261117T0310Z.sqlite.gz", (c as Choice.Take).file.name)
    }

    @Test fun aSchemaWhoseOnlyFileIsNotUploadedIsNotSaid() {
        assertEquals(Choice.None, choose(listOf(listed("indexes-s18-20261124T0312Z.sqlite.gz", uploaded = false)), 17, null))
    }

    @Test fun theSameFileAsLastTimeIsUpToDate() {
        val list = listOf(listed("indexes-s17-20261117T0310Z.sqlite.gz"), listed("indexes-s17-20261124T0312Z.sqlite.gz"))
        assertEquals(Choice.UpToDate("indexes-s17-20261124T0312Z.sqlite.gz"),
                     choose(list, 17, "indexes-s17-20261124T0312Z.sqlite.gz"))
        // An older one imported: the newest is taken.
        assertTrue(choose(list, 17, "indexes-s17-20261117T0310Z.sqlite.gz") is Choice.Take)
    }

    @Test fun otherNamesAreIgnored() {
        assertEquals(Choice.None, choose(listOf(listed("indexes.json"), listed("indexes-s17-20261124T0312Z.sqlite.gz.next"),
                                                listed("indexes2-s17-20261124T0312Z.sqlite.gz")), 17, null))
        assertEquals(Choice.None, choose(emptyList(), 17, null))
    }

    @Test fun theWordsAreTheSpecs() {
        assertEquals("The published catalogues are for a newer caracole (schema 18): update the app.", words(Choice.Newer(18)))
        assertEquals("The published catalogues are for an older caracole (schema 16): new ones are on their way.",
                     words(Choice.Older(16)))
        assertEquals("No catalogues are published yet.", words(Choice.None))
        assertNull(words(Choice.UpToDate("indexes-s17-20261124T0312Z.sqlite.gz")))
        assertNull(words(Choice.Take(listed("indexes-s17-20261124T0312Z.sqlite.gz"), Named(17, Instant.EPOCH))))
    }

    @Test fun aDateIsDayMonthYearInEnglish() {
        assertEquals("24 Nov 2026", date(Named(17, Instant.parse("2026-11-24T03:12:00Z"))))
        assertEquals("1 Jan 2027", date(Named(17, Instant.parse("2027-01-01T00:00:00Z"))))
        assertEquals("29 Feb 2028", date(Named(17, Instant.parse("2028-02-29T23:59:00Z"))))
        assertEquals(listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
                     (1..12).map { date(Named(1, Instant.parse("2026-%02d-15T00:00:00Z".format(it)))).split(" ")[1] })
    }

    @Test fun theErrorsWords() {
        assertEquals("No catalogues are published yet.", NoRelease().message)
        val limited = Limited(Instant.parse("2026-11-24T14:05:00Z"), ZoneOffset.UTC)
        assertEquals("Try again after 14:05 — GitHub has answered this network's share of requests for the hour.",
                     limited.message)
        // A reset within a minute is said as the minute after it: before it, GitHub still says no.
        assertEquals("Try again after 14:06 — GitHub has answered this network's share of requests for the hour.",
                     Limited(Instant.parse("2026-11-24T14:05:17Z"), ZoneOffset.UTC).message)
        assertEquals("Try again after 16:26 — GitHub has answered this network's share of requests for the hour.",
                     Limited(Instant.ofEpochSecond(1795537517), ZoneOffset.UTC).message)
        assertEquals("Try again after 00:00 — GitHub has answered this network's share of requests for the hour.",
                     Limited(Instant.parse("2026-11-24T23:59:30Z"), ZoneOffset.UTC).message)
    }

    // --- the Api source ---------------------------------------------------------------------------------------------

    private val releasePath = "/repos/Danielhp95/caracole/releases/tags/indexes"

    private fun asset(id: Int, name: String, size: Long, state: String, digest: String?): String {
        val url = "${github.base}/repos/Danielhp95/caracole/releases/assets/$id"
        val d = if (digest == null) "null" else "\"$digest\""
        return """{"url":"$url","id":$id,"name":"$name","label":"","state":"$state","size":$size,"digest":$d,""" +
            """"content_type":"application/gzip","browser_download_url":"https://github.com/x/$name"}"""
    }

    @Test fun theApiListsTheReleasesFiles() {
        val hex = "0123456789abcdef".repeat(4)
        github.route(releasePath, Reply(200, ("""{"tag_name":"indexes","prerelease":false,"assets":[""" +
            asset(1, "indexes-s17-20261124T0312Z.sqlite.gz", 52_000_000, "uploaded", "sha256:$hex") + "," +
            asset(2, "indexes-s17-20261201T0312Z.sqlite.gz", 1_000, "starter", null) + "," +
            asset(3, "indexes-s17-20261117T0310Z.sqlite.gz", 51_000_000, "uploaded", null) +
            "]}").toByteArray()))
        val listed = CatalogueSource.Api(http, github.base).list()
        assertEquals(listOf(
            Listed("indexes-s17-20261124T0312Z.sqlite.gz", 52_000_000, hex, true,
                   "${github.base}/repos/Danielhp95/caracole/releases/assets/1"),
            Listed("indexes-s17-20261201T0312Z.sqlite.gz", 1_000, "", false,
                   "${github.base}/repos/Danielhp95/caracole/releases/assets/2"),
            // No digest: GitHub hasn't checked it, so it isn't taken as uploaded.
            Listed("indexes-s17-20261117T0310Z.sqlite.gz", 51_000_000, "", false,
                   "${github.base}/repos/Danielhp95/caracole/releases/assets/3"),
        ), listed)
        assertEquals(listOf("GET $releasePath · application/vnd.github+json"), github.asked)
    }

    @Test fun theApiAnswering404IsNoRelease() {
        assertFailsWith<NoRelease> { CatalogueSource.Api(http, github.base).list() }
    }

    @Test fun theApiAnswering403WithNoRequestsLeftIsLimitedUntilItsReset() {
        for (status in listOf(403, 429)) {
            github.route(releasePath, Reply(status, """{"message":"API rate limit exceeded"}""".toByteArray(),
                mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to "1795537517")))
            val e = assertFailsWith<Limited> { CatalogueSource.Api(http, github.base).list() }
            assertEquals(Instant.ofEpochSecond(1795537517), e.until)
        }
    }

    @Test fun theApiAnswering403WithRequestsLeftIsAnErrorButNotLimited() {
        github.route(releasePath, Reply(403, """{"message":"Forbidden"}""".toByteArray(),
            mapOf("x-ratelimit-remaining" to "12", "x-ratelimit-reset" to "1795537517")))
        val e = assertFailsWith<CatalogueError> { CatalogueSource.Api(http, github.base).list() }
        assertTrue(e !is Limited)
        assertEquals("GitHub answered HTTP 403. Try again later.", e.message)
    }

    @Test fun anAnswerThatIsntAListingIsAnError() {
        for (body in listOf("<html>", """{"assets":"no"}""", """[]""", """{"assets":[{"name":1}]}""")) {
            github.route(releasePath, Reply(200, body.toByteArray()))
            val e = assertFailsWith<CatalogueError> { CatalogueSource.Api(http, github.base).list() }
            assertEquals(body, "GitHub answered with something the phone can't read.", e.message)
        }
    }

    @Test fun aSourceNeverReachesGitHubFromATest() {
        assertFailsWith<TransportError> { CatalogueSource.Api(http).list() }
    }

    @Test fun anAssetOfAnotherHostOrRepositoryIsUnreadable() {
        for (url in listOf("https://evil.example/repos/Danielhp95/caracole/releases/assets/1",
                           "${github.base}/repos/someone/else/releases/assets/1",
                           "${github.base}/repos/Danielhp95/caracole/releases/assets/1/../2",
                           "${github.base}/repos/Danielhp95/caracole/releases/assets/")) {
            github.route(releasePath, Reply(200, ("""{"assets":[{"url":"$url","name":"x","state":"uploaded",""" +
                """"size":1,"digest":"sha256:00"}]}""").toByteArray()))
            val e = assertFailsWith<CatalogueError> { CatalogueSource.Api(http, github.base).list() }
            assertEquals(url, "GitHub answered with something the phone can't read.", e.message)
        }
        // GitHub's canonical login may be cased otherwise than the constant.
        github.route(releasePath, Reply(200, ("""{"assets":[{"url":"${github.base}/repos/danielhp95/Caracole/releases/assets/9",""" +
            """"name":"x","state":"uploaded","size":1,"digest":"sha256:00"}]}""").toByteArray()))
        assertEquals(1, CatalogueSource.Api(http, github.base).list().size)
    }

    @Test fun aBaseWithASlashAtItsEndAsksTheSamePaths() {
        github.route(releasePath, Reply(200, """{"assets":[]}""".toByteArray()))
        assertEquals(emptyList<Listed>(), CatalogueSource.Api(http, URI("${github.base}/")).list())
        assertEquals(listOf("GET $releasePath · application/vnd.github+json"), github.asked)
    }

    @Test fun theSourcesAskWhereTheBriefSays() {
        assertEquals(URI("https://api.github.com"), CatalogueSource.Api(http).base)
        assertEquals(setOf("release-assets.githubusercontent.com"), CatalogueSource.Api(http).redirects)
    }
}
