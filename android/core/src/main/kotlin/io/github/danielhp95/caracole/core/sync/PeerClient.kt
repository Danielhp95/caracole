package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.serialization.json.JsonObject
import java.io.File

/** /api/peer/state, as the phone reads it. */
data class PeerState(val format: Int, val server: String?, val caracole: String, val name: String, val now: String?,
                     val units: Map<String, SyncUnit>, val base: Base?, val token: String,
                     val indexes: Map<String, String> = emptyMap())

/** The computer's peer routes, from the phone (lane sync-client). */
class PeerClient(val address: ServerAddress, http: Http = Http()) : UnitSource {
    /** GET /api/peer/state, a 60 s read timeout. */
    fun state(asking: String?): PeerState = TODO("lane sync-client")

    /** POST /peer/push/new: the push's id, and the shas the computer needs. */
    fun pushNew(token: String, from: String, files: List<String>): Pair<String, List<String>> = TODO("lane sync-client")
    fun pushFile(token: String, push: String, sha256: String, bytes: ByteArray): Unit = TODO("lane sync-client")

    /** POST /peer/push: the job's id. */
    fun push(token: String, push: String, payload: JsonObject): Int = TODO("lane sync-client")

    /** GET /api/jobs/<id>. */
    fun job(id: Int): JsonObject = TODO("lane sync-client")

    /** GET /api/peer/index, no read timeout. */
    fun index(to: File, sites: List<String>? = null): Unit = TODO("lane sync-client")

    override fun unit(id: String): JsonObject? = TODO("lane sync-client")
    override fun file(songKey: String, name: String, sha256: String): ByteArray = TODO("lane sync-client")
}
