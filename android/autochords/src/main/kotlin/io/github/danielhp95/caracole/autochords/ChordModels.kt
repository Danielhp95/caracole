package io.github.danielhp95.caracole.autochords

import java.io.File
import java.io.IOException

/** What the models heard in a song's audio (sheet.Heard, the design's §4.4 `heard`): its one home is :viewer's
 * viewer.autochords, which lays a sheet out from it (SheetHalf, Relay) and writes and reads it as the computer does
 * (Heard.json, Heard.read). Here it is what [ChordModels.hear] answers: the audio's length as music.py `read_audio`
 * states it, the chords in common names ([Labels.recognized]), beat_this's beats and downbeats. */
typealias Heard = io.github.danielhp95.caracole.viewer.autochords.Heard

/**
 * The chord models, wherever they run (the design's §3.1; on the phone `:ml`'s MlChordModels, the models in a process
 * of their own).
 *
 * - [ready]: null when the models can hear a song here, else why not in words (a file missing, one that isn't the one
 *   pinned).
 * - [hear]: the [audio] file heard, its steps told to [onStep] as they start, in run.py's words (`STEPS`: "setting up
 *   the models", "hearing the chords", "finding the beats"), and the phone's "waiting for the phone to cool"; [waiting]
 *   called about every second while the models work, a hand-over point (the lookups queued meanwhile go first). Audio
 *   that can't be decoded is [AudioUnreadable]; the models' setup failing (missing, stopped, too hot, the battery too
 *   low) [ChordsUnavailable], each in words.
 */
interface ChordModels {
    fun ready(): String?
    fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard
}

/** An audio file the models can't hear: decoded by nothing here, or too short to hold a chord. */
class AudioUnreadable(words: String, cause: Throwable? = null) : IOException(words, cause)

/** The chord models can't hear a song now: their files missing, their process stopped, the phone too hot, its
 * battery too low. Try again may do. */
class ChordsUnavailable(words: String, cause: Throwable? = null) : IOException(words, cause)
