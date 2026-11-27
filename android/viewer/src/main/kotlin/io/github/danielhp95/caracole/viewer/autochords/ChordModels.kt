package io.github.danielhp95.caracole.viewer.autochords

import java.io.File
import java.io.IOException

/**
 * The chord models, wherever they run (the design's §3.1; on the phone `:ml`'s MlChordModels, the models in a process
 * of their own). Here, in :viewer, beside [Heard], so that :server's AudioRunner, which the release ships, names it
 * with no part of `:autochords` (the front ends and their data, the debug build's alone until stage S: the release
 * may carry nothing under `caracole/autochords/`, android/scripts/release-check.sh); `:autochords` names it by a
 * typealias.
 *
 * - [ready]: null when the models can hear a song here, else why not in words (a file missing, one that isn't the one
 *   pinned).
 * - [hear]: the [audio] file heard, its steps told to [onStep] as they start, in run.py's words (`STEPS`: "setting up
 *   the models", "hearing the chords", "finding the beats"), and the phone's "waiting for the phone to cool"; [waiting]
 *   called about every second while the models work, a hand-over point (the lookups queued meanwhile go first). Audio
 *   that can't be decoded is [AudioUnreadable]; the models' setup failing (missing, stopped, too hot, the battery too
 *   low) [ChordsUnavailable], each in words. Whatever [waiting] throws (the queue's CancellationException, from
 *   its yield, when the queue stops mid-hearing) propagates as itself, never wrapped as [ChordsUnavailable]: a stop
 *   is no setup's failure.
 * - [forget]: what [hear] kept of [audio] to go on from (its checkpoints, the design's §3.3) let go, called once the
 *   sheet heard of it is kept, never before: a keep that fails leaves them, so that Try again hears nothing again.
 *   Never throws; none to let go by default.
 * - [runtime]: what runs them, an auto sheet's `raw["runtime"]` ("onnxruntime 1.32.0"); null where it says none.
 */
interface ChordModels {
    fun ready(): String?
    fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard
    fun forget(audio: File) {}
    val runtime: String? get() = null
}

/** An audio file the models can't hear: decoded by nothing here, or too short to hold a chord. */
class AudioUnreadable(words: String, cause: Throwable? = null) : IOException(words, cause)

/** The chord models can't hear a song now: their files missing, their process stopped, the phone too hot, its
 * battery too low. Try again may do. */
class ChordsUnavailable(words: String, cause: Throwable? = null) : IOException(words, cause)
