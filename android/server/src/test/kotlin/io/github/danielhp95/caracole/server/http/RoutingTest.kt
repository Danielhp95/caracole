package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.Base64
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** web/app.py's router on the phone: every request of vectors/web/routing.jsonl answered as WebApp.handle answers it,
 * behind the launch's secret; the stubs; the modules' table. */
class RoutingTest {
    @get:Rule val tmp = TemporaryFolder()

    private val routing = Corpus.records("web/routing.jsonl")
    private val setup = routing.first().also { check(it.fn == "routes") }.out!!.jsonObject

    /** The vector's routes, each answering as test_conformance_web.py's ANSWERS say. */
    private fun vectorRoutes(app: () -> App): RouteModule = object : RouteModule {
        override val routes = setup["routes"]!!.jsonArray.map { it.jsonObject }.map { spec ->
            val method = spec["method"]!!.jsonPrimitive.content
            val path = spec["path"]!!.jsonPrimitive.content
            fun answer(request: Request, form: Map<String, String>?): Response =
                when (spec["answer"]!!.jsonPrimitive.content) {
                    "echo" -> app().json(JsonObject(buildMap {
                        put("route", JsonPrimitive(path))
                        put("method", JsonPrimitive(request.method))
                        if (form != null) put("form", JsonObject(form.mapValues { JsonPrimitive(it.value) }))
                    }))
                    "page" -> Response(200, Body.Bytes("<!doctype html>\n<p>page</p>\n".toByteArray()), mutableListOf(
                        "Content-Type" to "text/html; charset=utf-8", "Content-Security-Policy" to "default-src 'none'"))
                    "refuse" -> throw Refused(409, "Not here yet", "That isn't here yet.")
                    "kept" -> Response(200, Body.Bytes("kept\n".toByteArray()), mutableListOf(
                        "Content-Type" to "text/plain; charset=utf-8", "Cache-Control" to "max-age=60",
                        "x-frame-options" to "SAMEORIGIN"))
                    "queued" -> app().queued(JsonObject(mapOf("id" to JsonPrimitive(7), "state" to JsonPrimitive("queued"))))
                    else -> error("no such answer: $spec")
                }
            Route(method, path, "the vector's ${spec["answer"]}", under = spec["under"]!!.jsonPrimitive.boolean,
                  scriptOnly = spec["script_only"]!!.jsonPrimitive.boolean, page = spec["page"]!!.jsonPrimitive.content,
                  get = if (method == "GET") GetAnswer { answer(it, null) } else null,
                  post = if (method == "POST") PostAnswer { request, form -> answer(request, form) } else null)
        }
    }

    private object None : RouteModule {
        override val routes = emptyList<Route>()
    }

    @Test fun everyRoutingVectorIsAnsweredAsWebAppAnswersIt() {
        lateinit var built: App
        TestApp(tmp.root, { listOf(vectorRoutes { built }) }, stubs = None, csrf = setup["csrf"]!!.jsonPrimitive.content,
                allowed = setup["allowed"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet(),
                libraryName = setup["library_name"]!!.jsonPrimitive.content).use { test ->
            built = test.app
            assertEquals(MessagePage.PHONE_BADGE, setup["badge"]!!.jsonPrimitive.content)
            val requests = routing.filter { it.fn == "caracole.web.app.WebApp.handle" }
            assertTrue(requests.size > 100)
            val mark = "<style>${setup["style_mark"]!!.jsonPrimitive.content}</style>"
            val style = "<style>${MessagePage.style}</style>"
            val wrong = requests.mapNotNull { record ->
                val asked = record.args[0].jsonObject
                val headers = asked["headers"]!!.jsonObject.mapValues { it.value.jsonPrimitive.content } +
                    ("cookie" to "${Security.SECRET_COOKIE}=${test.secret}")
                val response = test.handle(Request(asked["method"]!!.jsonPrimitive.content,
                                                   asked["target"]!!.jsonPrimitive.content, headers, body(asked)))
                val out = record.out!!.jsonObject
                val expected = Triple(out["status"]!!.jsonPrimitive.content.toInt(),
                                      out["headers"]!!.jsonArray.map { h -> h.jsonArray.map { it.jsonPrimitive.content } },
                                      body(out).toString(Charsets.UTF_8).replace(mark, style))
                val got = Triple(response.status, response.headers.map { listOf(it.first, it.second) }, response.text)
                if (got == expected) null else "${record.extra["note"]}: $got\n   Python: $expected"
            }
            assertEquals(emptyList(), wrong.take(5), "${wrong.size} of ${requests.size} differ")
        }
    }

    private fun body(o: JsonObject): ByteArray = o["body"]?.jsonPrimitive?.content?.toByteArray()
        ?: Base64.getDecoder().decode(o["body_b64"]!!.jsonPrimitive.content)

    private val finished = listOf("Content-Security-Policy" to "frame-ancestors 'none'",
                                  "X-Content-Type-Options" to "nosniff", "X-Frame-Options" to "DENY",
                                  "Referrer-Policy" to "same-origin", "Cross-Origin-Resource-Policy" to "same-origin",
                                  "Cross-Origin-Opener-Policy" to "same-origin", "Cache-Control" to "no-store")

    @Test fun withoutTheLaunchsSecretNothingIsAnsweredNotEvenAHostCheck() {
        TestApp(tmp.root).use { test ->
            for (secret in listOf(null, "", "wrong", test.secret + "0", test.secret.uppercase())) {
                for (host in listOf(TestApp.HOST, "evil.example")) {
                    val response = test.handle(TestApp.request("GET", "/api/youtube/video?id=dQw4w9WgXcQ",
                                                               mapOf("host" to host), ByteArray(0), secret))
                    assertEquals(403, response.status, "$secret at $host")
                    assertEquals("Not this app's caracole.\n", response.text)
                    assertEquals(listOf("Content-Type" to "text/plain; charset=utf-8") + finished, response.headers)
                    assertNull(response.data)
                }
            }
            val posted = test.handle(TestApp.request("POST", "/request", mapOf(
                "content-type" to "application/x-www-form-urlencoded", "accept" to "application/json",
            ), TestApp.form(listOf("csrf" to test.csrf)), "wrong"))
            assertEquals(403, posted.status)
            assertEquals("Not this app's caracole.\n", posted.text, "never JSON: no page of ours asked")
            assertEquals(200, test.get("/api/youtube/video?id=dQw4w9WgXcQ").status, "with it, the route")
        }
    }

    private fun route(method: String, path: String, said: String, under: Boolean = false, limit: Int = 16_384) =
        Route(method, path, said, under = under, limit = limit,
              get = if (method == "GET") GetAnswer { Response(200, Body.Bytes(said.toByteArray())) } else null,
              post = if (method == "POST") PostAnswer { _, form -> Response(200, Body.Bytes((said + form).toByteArray())) } else null)

    private fun module(vararg routes: Route) = object : RouteModule {
        override val routes = routes.toList()
    }

    @Test fun twoModulesAnsweringOneRouteRefuseToConstruct() {
        TestApp(tmp.newFolder()).use { test ->
            val twice = assertFailsWith<IllegalArgumentException> {
                App(AppConfig("c", "s"), listOf(module(route("GET", "/x", "a")), module(route("GET", "/x", "b"))), None,
                    test.files)
            }
            assertTrue("GET /x" in twice.message!!, twice.message)
            assertFailsWith<IllegalArgumentException> {
                App(AppConfig("c", "s"), listOf(module(route("POST", "/x", "a"), route("POST", "/x", "b"))), None,
                    test.files)
            }
            // one path, two methods, is two routes
            App(AppConfig("c", "s"), listOf(module(route("GET", "/x", "a")), module(route("POST", "/x", "b"))), None,
                test.files)
            assertFailsWith<IllegalArgumentException> {
                App(AppConfig("c", "s"), listOf(module(Route("GET", "/x", "no answer"))), None, test.files)
            }
            assertFailsWith<IllegalArgumentException> {
                App(AppConfig("c", "s"), listOf(module(Route("PUT", "/x", "a", get = GetAnswer { Response(200) }))),
                    None, test.files)
            }
        }
    }

    @Test fun aStubAnswersOnlyWhereNoModuleDoes() {
        val stubs = module(route("GET", "/x", "stub x"), route("GET", "/y", "stub y"), route("GET", "/z/", "stub z/", true),
                           route("POST", "/p", "stub p"))
        TestApp(tmp.root, { listOf(module(route("GET", "/x", "module x"), route("GET", "/z/1", "module z/1")),
                                   module(route("GET", "/w/", "module w/", true))) }, stubs = stubs).use { test ->
            assertEquals("module x", test.get("/x").text)
            assertEquals("stub y", test.get("/y").text)
            assertEquals("module z/1", test.get("/z/1").text, "a module's exact route before a stub's prefix")
            assertEquals("stub z/", test.get("/z/2").text)
            assertEquals("module w/", test.get("/w/anything").text)
            assertEquals("stub p{csrf=${test.csrf}, a=1}", test.post("/p", listOf("a" to "1")).text)
            assertEquals("module x", test.handle(test.request("HEAD", "/x")).text, "a GET route answers HEAD")
        }
    }

    @Test fun aRouteSaysHowLongItsFormMayBe() {
        val big = "x".repeat(20_000)
        TestApp(tmp.root, { listOf(module(route("POST", "/big", "big", limit = 1_048_576), route("POST", "/small", "s"))) }).use { test ->
            assertEquals(200, test.post("/big", listOf("pad" to big)).status)
            assertEquals(413, test.post("/small", listOf("pad" to big)).status)
            assertEquals(1_048_576, test.app.bodyLimit("POST", "/big?x=1"))
            assertEquals(16_384, test.app.bodyLimit("POST", "/small"))
            assertEquals(16_384, test.app.bodyLimit("POST", "/nowhere"))
            assertEquals(16_384, test.app.bodyLimit("GET", "/%ff"))
        }
    }

    @Test fun aJobQueuedIsARedirectToItsLineOrItsViewToTheScript() {
        TestApp(tmp.root).use { test ->
            val sync = JsonObject(mapOf("id" to JsonPrimitive(3), "kind" to JsonPrimitive("sync"),
                                        "details" to JsonPrimitive("#tab=sync")))
            val queued = test.app.queued(sync)
            assertEquals(303, queued.status)
            assertEquals("/#tab=sync", queued.header("Location"))
            assertEquals(JsonObject(mapOf("job" to sync)), queued.data)
            val plain = test.app.queued(JsonObject(mapOf("id" to JsonPrimitive(4))))
            assertEquals("/#tab=requests&job=4", plain.header("Location"))
            val json = test.app.json(JsonObject(mapOf("a" to JsonArray(listOf(JsonPrimitive("é<"), JsonNull)))), 202)
            assertEquals(202, json.status)
            assertEquals("""{"a":["é<",null]}""", json.text)
            assertEquals("application/json; charset=utf-8", json.header("Content-Type"))
        }
    }

    @Test fun aRefusalThatSaysReloadTellsTheScriptSo() {
        val reloading = module(Route("POST", "/r", "reload", post = PostAnswer { _, _ ->
            throw Refused(403, "Refused", "Reload it.", reload = true)
        }))
        TestApp(tmp.root, { listOf(reloading) }).use { test ->
            val answer = test.postScript("/r")
            assertEquals(403, answer.status)
            assertEquals("""{"error":"Reload it.","reload":true}""", answer.text)
            assertTrue("<h1>Refused</h1>" in test.post("/r").text)
        }
    }

    @Test fun theStubsSayWhatIsntOnThePhoneYet() {
        TestApp(tmp.root).use { test ->
            for (path in listOf("/review", "/versions", "/harmonica", "/guitar", "/lookup", "/export.pdf")) {
                val page = test.get("$path?song=1")
                assertEquals(409, page.status, path)
                assertEquals("text/html; charset=utf-8", page.header("Content-Type"))
                assertTrue("isn&#x27;t on the phone yet." in page.text || "aren&#x27;t on the phone yet." in page.text,
                           page.text.substringAfter("<p class=\"message\">").substringBefore("</p>"))
                val said = test.script("$path?song=1").json.jsonObject["error"]!!.jsonPrimitive.content
                assertTrue(said.endsWith(" on the phone yet."), said)
            }
            val posts = Stubs().routes.filter { it.method == "POST" }.map { it.path }
            for (path in listOf("/fetch", "/review", "/versions/choose", "/versions/keep", "/versions/clear",
                                "/versions/keep-more", "/songbook/make", "/songbook/add", "/songbook/add-song",
                                "/songbook/set", "/songbook/delete", "/lacuerda/search", "/lacuerda/artist",
                                "/harptabs/artist", "/youtube", "/youtube/search", "/youtube/video", "/jobs/again",
                                "/harmonica/pin", "/harmonica/clear", "/request", "/lookup", "/remove")) {
                assertTrue(path in posts, path)
                val refused = test.postScript(path, listOf("song" to "1"))
                assertEquals(409, refused.status, path)
                assertTrue(refused.json.jsonObject["error"]!!.jsonPrimitive.content.endsWith(" on the phone yet."))
                assertEquals(403, test.postScript(path, token = "old").status, "$path: the form's checks come first")
            }
            assertEquals(404, test.post("/peer/push").status, "no stub for a route the phone never answers")
            assertTrue(Stubs().routes.all { it.doc.isNotBlank() })
        }
    }

    @Test fun youTubeIsOffOnThePhone() {
        TestApp(tmp.root).use { test ->
            val off = test.script("/api/youtube/video?id=dQw4w9WgXcQ")
            assertEquals(200, off.status)
            assertEquals("""{"id":"dQw4w9WgXcQ","url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","state":"off",""" +
                         """"why":"YouTube isn't on the phone.","video":null,"guess":{"artist":"","title":""},""" +
                         """"song":null}""", off.text)
            for (link in listOf("https://youtu.be/dQw4w9WgXcQ", "www.youtube.com/watch?v=dQw4w9WgXcQ&t=1",
                                "https://m.youtube.com/shorts/dQw4w9WgXcQ/", "https://music.youtube.com/embed/dQw4w9WgXcQ")) {
                val read = test.script("/api/youtube/video?url=" + java.net.URLEncoder.encode(link, Charsets.UTF_8))
                assertEquals("dQw4w9WgXcQ", read.json.jsonObject["id"]!!.jsonPrimitive.content, link)
            }
            for (bad in listOf("?id=short", "?url=https%3A%2F%2Fevil.example%2Fwatch%3Fv%3DdQw4w9WgXcQ", "", "?id=")) {
                val refused = test.script("/api/youtube/video$bad")
                assertEquals(400, refused.status, bad)
                assertEquals("""{"error":"Not a YouTube video link."}""", refused.text)
            }
        }
    }

    /** A number written with a point or an exponent (never true, false or null). */
    private fun isFloat(value: JsonPrimitive) = !value.isString && value !is JsonNull &&
        (value.content.first() == '-' || value.content.first().isDigit()) && value.content.any { it in ".eE" }

    /** [value] as Kotlin would build it: every float a Double, through PyJson.float (never JsonPrimitive(Double)). */
    private fun builtInKotlin(value: JsonElement): JsonElement = when (value) {
        is JsonObject -> JsonObject(value.mapValues { builtInKotlin(it.value) })
        is JsonArray -> JsonArray(value.map(::builtInKotlin))
        is JsonPrimitive -> if (isFloat(value)) PyJson.float(value.content.toDouble()) else value
    }

    private fun floats(value: JsonElement): Int = when (value) {
        is JsonObject -> value.values.sumOf(::floats)
        is JsonArray -> value.sumOf(::floats)
        is JsonPrimitive -> if (isFloat(value)) 1 else 0
    }

    @Test fun everyJsonAnswerAndDataBlockIsWrittenAsPythonWritesIt() {
        val records = routing.filter { it.fn.startsWith("caracole.inline.") || it.fn == "caracole.web.app.json_response" }
        assertTrue(records.count { it.fn == "caracole.inline.json_block" } > 20)
        TestApp(tmp.root).use { test ->
            var floats = 0
            for (record in records) {
                val args = record.args.map { it.jsonPrimitive.content }
                val expected = record.out!!.jsonPrimitive.content
                when (record.fn) {
                    "caracole.inline.sha256_source" -> assertEquals(expected, Inline.sha256Source(args[0]), args[0])
                    "caracole.inline.json_block" -> {
                        val data = Json.parseToJsonElement(args[1])
                        assertEquals(expected, Inline.jsonBlock(args[0], data), args[1])
                        assertEquals(expected, Inline.jsonBlock(args[0], builtInKotlin(data)), "built in Kotlin: ${args[1]}")
                    }
                    else -> {
                        val data = Json.parseToJsonElement(args[0])
                        assertEquals(expected, test.app.json(data).text, args[0])
                        assertEquals(expected, test.app.json(builtInKotlin(data)).text, "built in Kotlin: ${args[0]}")
                        floats += floats(data)
                    }
                }
            }
            assertTrue(floats > 20, "the vectors hold floats: $floats")
        }
    }

    @Test fun inlineIsInlinePys() {
        assertEquals("'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='", Inline.sha256Source(""))
        val block = Inline.jsonBlock("songs\"x", JsonObject(mapOf("t" to JsonPrimitive("</script><!--é"))))
        assertEquals("<script type=\"application/json\" id=\"songs&quot;x\">{\"t\":\"\\u003c/script>\\u003c!--é\"}</script>\n",
                     block)
        assertContentEquals("x".toByteArray(), Response(200, Body.Bytes("x".toByteArray())).bytes)
    }
}
