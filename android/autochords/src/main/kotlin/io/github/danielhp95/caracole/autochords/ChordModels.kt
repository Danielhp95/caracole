package io.github.danielhp95.caracole.autochords

/** What the models heard in a song's audio (sheet.Heard, the design's §4.4 `heard`): its one home is :viewer's
 * viewer.autochords, which lays a sheet out from it (SheetHalf, Relay) and writes and reads it as the computer does
 * (Heard.json, Heard.read). Here it is what [ChordModels.hear] answers: the audio's length as music.py `read_audio`
 * states it, the chords in common names ([Labels.recognized]), beat_this's beats and downbeats. */
typealias Heard = io.github.danielhp95.caracole.viewer.autochords.Heard

/** The chord models, wherever they run: their one home is :viewer's viewer.autochords (ChordModels' KDoc there), so
 * that :server, which the release ships, names them with nothing of this module. */
typealias ChordModels = io.github.danielhp95.caracole.viewer.autochords.ChordModels

/** An audio file the models can't hear (viewer.autochords'). */
typealias AudioUnreadable = io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable

/** The chord models can't hear a song now (viewer.autochords'). */
typealias ChordsUnavailable = io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
